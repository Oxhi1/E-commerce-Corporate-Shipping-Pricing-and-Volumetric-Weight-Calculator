"""Teslimat suresi dagiliminin gecmis veriden kestirimi.

Firmanin sozlesmede yazan SLA'si bir **vaat**tir; gerceklesen sure baska bir sey.
Karar motoru vaadi degil, gecmis veriden kestirdigi gercek dagilimi kullanir --
"3 gun" diyen ama gonderilerin %30'unu 5 gunde teslim eden bir firmanin gercek
maliyeti farklidir.

Neden log-normal?
    Teslimat suresi pozitif, saga carpik ve carpimsal gecikmelerden olusur
    (aktarma bekleme x hat yogunlugu x sube kapasitesi). Normal dagilim negatif
    gun uretir; ustel dagilim kuyrugu fazla kalin modeller.

Neden **vaade gore asim** uzerinden calisiliyor?
    Ilk surumde dagilim dogrudan gun sayisi uzerinde kestiriliyor ve seyrek
    hucreler firma ortalamasina cekiliyordu. Bu yanlisti: 1 gunluk bir sehir ici
    hucresi, ayni firmanin 4 gunluk uzak bolge hucreleriyle ayni havuza giriyor
    ve yukari cekiliyordu -- Yurtici sehir icinde gercek %5 gecikmeye karsi
    %13 tahmin uretiliyordu.

    Cozum: kestirim `log(gerceklesen / vaat)` uzerinde yapiliyor. Bu buyukluk
    olcekten bagimsizdir ("firma vaadini yuzde kac asiyor") ve bolgeler arasi
    havuzlama artik anlamli. Mutlak dagilima donus, sorulan hucrenin kendi SLA'si
    ile yapiliyor:

        mu_mutlak = mu_asim + ln(SLA)

Not -- shrinkage burada hasar modelindekinden daha basit: sabit bir sozde-gozlem
sayisi kullaniliyor. Teslimat hucreleri hasar hucrelerinden cok daha kalabalik
oldugu icin tam Bayesci kestirimin marjinal katkisi kucuk. Bu bir basitlestirmedir.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Final, Self

import numpy as np
import pandas as pd
from scipy.stats import norm

from ..domain.enums import CarrierCode, ZoneClass

REQUIRED_COLUMNS: frozenset[str] = frozenset(
    {"carrier", "zone", "is_rural", "delivery_days", "promised_days"}
)

#: Hucre tahmininin firma ortalamasina cekilmesinde kullanilan sozde-gozlem sayisi.
SHRINKAGE_PSEUDO_COUNT: Final[float] = 40.0

#: Bir hucrenin kendi basina konustugu kabul edilmesi icin gereken asgari gozlem.
MIN_CELL_OBSERVATIONS: Final[int] = 8


@lru_cache(maxsize=64)
def _z_score(q: float) -> float:
    """Standart normal yuzdelik. `scipy.stats.norm.ppf` pahali ve her `DelayCost`
    olusturmada ayni birkac deger icin cagriliyor; onbellek ucuz bir kazanc."""
    return float(norm.ppf(q))


@dataclass(frozen=True, slots=True)
class OvershootFit:
    """Olcekten bagimsiz uyum: `log(gerceklesen / vaat)` dagilimi."""

    mu: float
    """Ortalama log-asim. 0 = medyan tam vaat gununde, >0 = vaadi asiyor."""

    sigma: float
    observations: int
    source: str
    """`hucre`, `firma` veya `genel` -- tahminin nereden geldigi."""

    def at_sla(self, sla_days: float) -> FittedDelivery:
        """Belirli bir SLA icin mutlak gun olceginde dagilimi kurar."""
        return FittedDelivery(
            mu=self.mu + float(np.log(sla_days)),
            sigma=self.sigma,
            observations=self.observations,
            source=self.source,
        )


@dataclass(frozen=True, slots=True)
class FittedDelivery:
    """Mutlak gun olceginde teslimat suresi dagilimi (log-normal).

    `T` **surekli** transit suresidir; gonderi `ceil(T)`. gunde teslim edilir.
    `T > vaat` tam olarak "gec kaldi" demektir.
    """

    mu: float
    sigma: float
    observations: int
    source: str

    @property
    def median_days(self) -> float:
        return float(np.exp(self.mu))

    @property
    def mean_days(self) -> float:
        return float(np.exp(self.mu + self.sigma**2 / 2))

    def percentile(self, q: float) -> float:
        """Teslimat suresinin `q` yuzdelik dilimi (0.95 -> '20 gonderiden 19'u')."""
        return float(np.exp(self.mu + self.sigma * _z_score(q)))

    def probability_late(self, promised_days: float) -> float:
        """`P(T > vaat)` -- gecikme olasiligi."""
        if promised_days <= 0:
            return 1.0
        return float(norm.sf((np.log(promised_days) - self.mu) / self.sigma))

    def expected_lateness_days(self, promised_days: float) -> float:
        """`E[(T - vaat)+]` -- beklenen gecikme suresi (zamaninda gelenler 0 sayilir).

        Log-normal icin kapali form:
            E[(T-d)+] = E[T] * Phi((mu + sigma^2 - ln d)/sigma) - d * Phi((mu - ln d)/sigma)

        Kapali form onemli: Monte Carlo'da milyonlarca kez cagriliyor; sayisal
        integral veya orneklem her kosuyu dakikalarca uzatirdi.
        """
        if promised_days <= 0:
            return self.mean_days
        log_d = np.log(promised_days)
        term_mean = self.mean_days * norm.cdf((self.mu + self.sigma**2 - log_d) / self.sigma)
        term_threshold = promised_days * norm.cdf((self.mu - log_d) / self.sigma)
        return float(max(0.0, term_mean - term_threshold))


class DeliveryTimeEstimator:
    """Gecmis teslimat surelerinden hucre bazli asim dagilimi kestirir."""

    def __init__(self, pseudo_count: float = SHRINKAGE_PSEUDO_COUNT) -> None:
        self.pseudo_count = pseudo_count
        self._cells: dict[tuple[str, str, bool], OvershootFit] = {}
        self._carriers: dict[str, OvershootFit] = {}
        self._global: OvershootFit | None = None
        self._fitted = False

    # ---- egitim -------------------------------------------------------------

    def fit(self, history: pd.DataFrame) -> Self:
        missing = REQUIRED_COLUMNS - set(history.columns)
        if missing:
            raise ValueError(f"Gecmis veride eksik sutun: {sorted(missing)}")
        if history.empty:
            raise ValueError("Gecmis veri bos -- teslimat modeli egitilemez")

        frame = history.loc[(history["delivery_days"] > 0) & (history["promised_days"] > 0)].copy()
        frame["log_overshoot"] = np.log(frame["delivery_days"] / frame["promised_days"])

        self._global = self._fit_series(frame["log_overshoot"], source="genel")

        self._carriers = {
            str(carrier): self._blend(
                self._fit_series(group["log_overshoot"], source="firma"), self._global
            )
            for carrier, group in frame.groupby("carrier", observed=True)
        }

        self._cells = {}
        for (carrier, zone, rural), group in frame.groupby(
            ["carrier", "zone", "is_rural"], observed=True
        ):
            parent = self._carriers.get(str(carrier), self._global)
            fitted = self._fit_series(group["log_overshoot"], source="hucre")
            self._cells[(str(carrier), str(zone), bool(rural))] = self._blend(fitted, parent)

        self._fitted = True
        return self

    @staticmethod
    def _fit_series(log_overshoot: pd.Series, source: str) -> OvershootFit:
        """Log-normal MLE: log-olcekli ortalama ve standart sapma."""
        n = len(log_overshoot)
        sigma = float(log_overshoot.std(ddof=1)) if n > 1 else 0.30
        return OvershootFit(
            mu=float(log_overshoot.mean()),
            sigma=max(sigma, 0.05),  # sifir varyans sayisal olarak patlar
            observations=n,
            source=source,
        )

    def _blend(self, child: OvershootFit, parent: OvershootFit | None) -> OvershootFit:
        """Hucre tahminini ust katmana ceker; agirlik gozlem sayisina bagli."""
        if parent is None:
            return child

        weight = child.observations / (child.observations + self.pseudo_count)
        source = child.source if child.observations >= MIN_CELL_OBSERVATIONS else parent.source
        return OvershootFit(
            mu=weight * child.mu + (1 - weight) * parent.mu,
            sigma=weight * child.sigma + (1 - weight) * parent.sigma,
            observations=child.observations,
            source=source,
        )

    # ---- kestirim -----------------------------------------------------------

    def overshoot(
        self, carrier: CarrierCode, zone: ZoneClass, *, is_rural: bool = False
    ) -> OvershootFit:
        """Olcekten bagimsiz asim dagilimi. Veri yoksa firma, o da yoksa genele duser."""
        self._require_fitted()
        for key in (
            (carrier.value, zone.value, is_rural),
            (carrier.value, zone.value, False),
        ):
            found = self._cells.get(key)
            if found is not None:
                return found
        found = self._carriers.get(carrier.value)
        if found is not None:
            return found
        assert self._global is not None
        return self._global

    def estimate(
        self,
        carrier: CarrierCode,
        zone: ZoneClass,
        sla_days: float,
        *,
        is_rural: bool = False,
    ) -> FittedDelivery:
        """Mutlak gun olceginde teslimat dagilimi.

        `sla_days` firmanin bu bolge icin sozlesmede yazan vaadi; dagilimin
        olcek capasi odur. Musteriye verilen vaat farkli olabilir ve gecikme
        esigi olarak ayrica degerlendirilir.
        """
        return self.overshoot(carrier, zone, is_rural=is_rural).at_sla(sla_days)

    def summary_frame(self, sla_lookup: dict[tuple[str, str], int]) -> pd.DataFrame:
        """Arayuz icin ozet tablo. `sla_lookup`: (firma, bolge) -> vaat gunu."""
        self._require_fitted()
        rows = []
        for (carrier, zone, rural), fit in self._cells.items():
            sla = sla_lookup.get((carrier, zone))
            if sla is None:
                continue
            absolute = fit.at_sla(sla + (1 if rural else 0))
            rows.append(
                {
                    "carrier": carrier,
                    "zone": zone,
                    "is_rural": rural,
                    "observations": fit.observations,
                    "overshoot_pct": float(np.exp(fit.mu) - 1.0),
                    "median_days": absolute.median_days,
                    "mean_days": absolute.mean_days,
                    "p95_days": absolute.percentile(0.95),
                    "probability_late": absolute.probability_late(sla + (1 if rural else 0)),
                    "source": fit.source,
                }
            )
        return pd.DataFrame(rows).sort_values(["carrier", "zone", "is_rural"])

    def _require_fitted(self) -> None:
        if not self._fitted:
            raise RuntimeError("Kestirici once `fit()` ile egitilmeli")
