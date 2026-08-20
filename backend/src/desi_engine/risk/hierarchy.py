"""Hiyerarsik hasar orani kestirimi -- `R_k` teriminin motoru.

Problem
    `(firma, bolge, kategori)` kiriliminda 80 hucre var ama gecmis veri carpik:
    en yogun hucrede 9118 gonderi, en seyrekte 5. Ham oranlar kullanilamaz --
    5 gonderide 0 hasar "bu firma bu bolgede hatasiz" demek degildir, "hicbir sey
    bilmiyoruz" demektir. Ters yonde de tehlikeli: 33 gonderide 1 hasar, ham
    haliyle %3 gorunur ve gercek oranin (~%0.5) alti katidir.

Cozum: dort katmanli Beta-Binom shrinkage

    p0    = genel ortalama
    p_k   = (k0*p0   + d_k)   / (k0 + n_k)        firma
    p_kz  = (k1*p_k  + d_kz)  / (k1 + n_kz)       firma x bolge
    p_kzc = (k2*p_kz + d_kzc) / (k2 + n_kzc)      firma x bolge x kategori

    Her katmanin tahmini, bir alt katmanin onseli olur. Veri boldugunda tahmin
    ham orana yakinsar; kitken ust katmanin ortalamasina yaslanir. Gecis
    kesintisiz ve otomatiktir -- "n < 30 ise ust katmani kullan" gibi keyfi bir
    esik yoktur.

    `k0`, `k1`, `k2` elle secilmez; her katmanda marjinal olabilirlik
    maksimize edilerek veriden kestirilir.

Yoneticiye tek cumleyle: *"az veri varsa iddiali konusmuyoruz."*
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Self

import numpy as np
import pandas as pd

from ..domain.enums import CarrierCode, RiskCategory, ZoneClass
from .beta_binomial import BetaPosterior, fit_concentration, posterior

#: Gecmis veri dosyasinda beklenen sutunlar.
REQUIRED_COLUMNS: frozenset[str] = frozenset({"carrier", "zone", "risk_category", "damaged"})


@dataclass(slots=True)
class _Level:
    """Hiyerarsinin tek bir katmani: gruplama anahtari, kestirilmis kappa, tahminler."""

    keys: tuple[str, ...]
    kappa: float = 0.0
    estimates: dict[tuple, BetaPosterior] = field(default_factory=dict)


class DamageRateEstimator:
    """Hiyerarsik Beta-Binom hasar orani kestiricisi."""

    #: Katman tanimlari, genelden ozele.
    LEVEL_KEYS: tuple[tuple[str, ...], ...] = (
        ("carrier",),
        ("carrier", "zone"),
        ("carrier", "zone", "risk_category"),
    )

    def __init__(self) -> None:
        self.global_rate: float = 0.0
        self.total_shipments: int = 0
        self._levels: list[_Level] = [_Level(keys=k) for k in self.LEVEL_KEYS]
        self._fitted = False

    # ---- egitim -------------------------------------------------------------

    def fit(self, history: pd.DataFrame) -> Self:
        """Gecmis sevkiyat verisinden tum katmanlari kestirir.

        `history` satir basina bir gonderi icermelidir; `damaged` sutunu 0/1.
        """
        missing = REQUIRED_COLUMNS - set(history.columns)
        if missing:
            raise ValueError(f"Gecmis veride eksik sutun: {sorted(missing)}")
        if history.empty:
            raise ValueError("Gecmis veri bos -- hasar modeli egitilemez")

        self.total_shipments = len(history)
        self.global_rate = float(history["damaged"].mean())

        parent_lookup: dict[tuple, float] = {}
        for level in self._levels:
            counts = (
                history.groupby(list(level.keys), observed=True)["damaged"]
                .agg(n="size", d="sum")
                .reset_index()
            )

            # Her hucrenin onseli, bir ust katmanin o hucre icin urettigi tahmin.
            priors = np.array(
                [
                    self._parent_mean(tuple(row[k] for k in level.keys), parent_lookup)
                    for _, row in counts.iterrows()
                ]
            )

            level.kappa = fit_concentration(counts["n"].to_numpy(), counts["d"].to_numpy(), priors)

            level.estimates = {}
            for (_, row), prior_mean in zip(counts.iterrows(), priors, strict=True):
                key = tuple(row[k] for k in level.keys)
                level.estimates[key] = posterior(
                    observations=int(row["n"]),
                    events=int(row["d"]),
                    prior_mean=float(prior_mean),
                    kappa=level.kappa,
                )

            parent_lookup = {key: est.mean for key, est in level.estimates.items()}

        self._fitted = True
        return self

    def _parent_mean(self, key: tuple, parent_lookup: dict[tuple, float]) -> float:
        """Bir hucrenin onsel ortalamasi: bir ust katmandaki karsiligi.

        En ust katmanda ust yoktur; genel ortalama kullanilir. Ust katmanda o
        anahtar hic gorulmemisse (gecmiste o firma o bolgeye hic gonderi
        yapmamis) yine genel ortalamaya duseriz.
        """
        if not parent_lookup:
            return self.global_rate
        return parent_lookup.get(key[:-1], self.global_rate)

    # ---- kestirim -----------------------------------------------------------

    def estimate(
        self, carrier: CarrierCode, zone: ZoneClass, category: RiskCategory
    ) -> BetaPosterior:
        """Bir `(firma, bolge, kategori)` hucresi icin posterior hasar orani.

        Hucre gecmiste hic gorulmemisse en ozel gorulen ustune duser; hicbiri
        yoksa genel ortalamadan bir posterior uretilir. Boylece motor her zaman
        bir cevap alir ve `KeyError` ile durmaz -- ama cevabin ne kadar zayif
        oldugu `shrinkage_weight` uzerinden gorulur.
        """
        self._require_fitted()
        full_key = (carrier.value, zone.value, category.value)

        for level in reversed(self._levels):
            key = full_key[: len(level.keys)]
            found = level.estimates.get(key)
            if found is not None:
                return found

        return posterior(0, 0, self.global_rate, self._levels[0].kappa or 1.0)

    def raw_rate(self, carrier: CarrierCode, zone: ZoneClass, category: RiskCategory) -> float:
        """Shrinkage uygulanmamis ham oran -- arayuzdeki 'once/sonra' karsilastirmasi."""
        self._require_fitted()
        key = (carrier.value, zone.value, category.value)
        found = self._levels[-1].estimates.get(key)
        return found.raw_rate if found else float("nan")

    # ---- tanilama -----------------------------------------------------------

    @property
    def kappas(self) -> dict[str, float]:
        """Katman basina kestirilmis konsantrasyon. Modelin ne ogrendigini gosterir.

        Kucuk `kappa`: hucreler gercekten farkli, veriye guven.
        Buyuk `kappa`: gozlenen farklar gurultuden ibaret, ust katmana yaslan.
        """
        self._require_fitted()
        return {"->".join(level.keys): level.kappa for level in self._levels}

    def heatmap_frame(self) -> pd.DataFrame:
        """Arayuzun risk isi haritasini besleyen tablo.

        Ham oran, shrinkage'li tahmin, guvenilir aralik ve onsel agirligi yan yana.
        """
        self._require_fitted()
        rows = []
        for key, est in self._levels[-1].estimates.items():
            low, high = est.credible_interval()
            rows.append(
                {
                    "carrier": key[0],
                    "zone": key[1],
                    "risk_category": key[2],
                    "shipments": est.observations,
                    "damages": est.events,
                    "raw_rate": est.raw_rate,
                    "shrunk_rate": est.mean,
                    "ci_low": low,
                    "ci_high": high,
                    "upper_95": est.upper_bound(),
                    "prior_weight": est.shrinkage_weight,
                }
            )
        return pd.DataFrame(rows).sort_values(["carrier", "zone", "risk_category"])

    def _require_fitted(self) -> None:
        if not self._fitted:
            raise RuntimeError("Kestirici once `fit()` ile egitilmeli")
