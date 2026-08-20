"""Simulasyon metrikleri ve istatistiksel karsilastirma.

Bir politikanin digerinden "%7 daha ucuz" oldugunu soylemek yetmez; o %7'nin
gurultu olup olmadigi da soylenmeli. Iki teknik bunu sagliyor:

**Ortak rastgele sayilar (CRN)** -- `runner.py`
    Tum politikalar birebir ayni siparis akisi ve ayni rastgele olay cekilisleri
    uzerinde kosuyor. Politikalar arasindaki fark, siparislerin rastgeleliginden
    degil yalnizca secim kuralindan geliyor.

**Eslestirilmis bootstrap** -- burada
    CRN sayesinde ayni siparis icin iki politikanin maliyeti **eslesmis** bir
    cift olusturuyor. Farklarin dagilimindan yeniden orneklemeyle guven araligi
    cikariliyor. Eslestirmeden yapilan bir bootstrap, siparis buyuklugu
    varyansini farka tasir ve araligi gereksiz yere genisletir -- gercek bir
    kazanci "anlamsiz" gosterebilir.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from itertools import pairwise

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from ..domain.enums import PolicyCode
from ..domain.units import money


@dataclass(slots=True)
class OrderOutcome:
    """Tek bir siparisin, tek bir politika altinda **gerceklesmis** sonucu.

    Beklenen degerler degil, simulasyonda fiilen olan seyler: koli hasar gordu mu,
    kac gunde teslim edildi. Politikalar bu gerceklesmelere gore yargilanir --
    kendi tahminlerine gore degil.
    """

    order_id: str
    carrier: str
    freight_try: float
    packaging_try: float
    damage_try: float
    delay_try: float
    parcels: int
    chargeable_desi: float
    delivery_days: float
    promised_days: int
    damaged: bool
    late: bool
    predicted_damage_probability: float

    @property
    def total_try(self) -> float:
        return self.freight_try + self.packaging_try + self.damage_try + self.delay_try


class PolicySummary(BaseModel):
    """Bir politikanin tum siparisler uzerindeki performansi."""

    model_config = ConfigDict(frozen=True)

    policy_code: PolicyCode
    label: str
    orders: int

    total_cost_try: float
    freight_try: float
    damage_try: float
    delay_try: float
    packaging_try: float

    cost_per_order_try: float
    freight_per_order_try: float

    damage_count: int
    damage_rate: float
    late_count: int
    late_rate: float

    mean_delivery_days: float
    p95_delivery_days: float
    mean_parcels: float
    mean_chargeable_desi: float

    carrier_mix: dict[str, int]
    unserved_orders: int = 0

    @property
    def hidden_cost_try(self) -> float:
        """Faturada gorunmeyen ama odenen kisim."""
        return money(self.damage_try + self.delay_try + self.packaging_try)

    @property
    def hidden_cost_share(self) -> float:
        return self.hidden_cost_try / self.total_cost_try if self.total_cost_try else 0.0


def summarize(
    policy_code: PolicyCode, label: str, outcomes: list[OrderOutcome], unserved: int = 0
) -> PolicySummary:
    """Gerceklesmis sonuclari tek bir ozete indirger."""
    if not outcomes:
        raise ValueError(f"{policy_code}: ozetlenecek sonuc yok")

    count = len(outcomes)
    days = np.array([o.delivery_days for o in outcomes])

    return PolicySummary(
        policy_code=policy_code,
        label=label,
        orders=count,
        total_cost_try=money(sum(o.total_try for o in outcomes)),
        freight_try=money(sum(o.freight_try for o in outcomes)),
        damage_try=money(sum(o.damage_try for o in outcomes)),
        delay_try=money(sum(o.delay_try for o in outcomes)),
        packaging_try=money(sum(o.packaging_try for o in outcomes)),
        cost_per_order_try=money(sum(o.total_try for o in outcomes) / count),
        freight_per_order_try=money(sum(o.freight_try for o in outcomes) / count),
        damage_count=sum(o.damaged for o in outcomes),
        damage_rate=sum(o.damaged for o in outcomes) / count,
        late_count=sum(o.late for o in outcomes),
        late_rate=sum(o.late for o in outcomes) / count,
        mean_delivery_days=float(days.mean()),
        p95_delivery_days=float(np.percentile(days, 95)),
        mean_parcels=sum(o.parcels for o in outcomes) / count,
        mean_chargeable_desi=sum(o.chargeable_desi for o in outcomes) / count,
        carrier_mix=dict(Counter(o.carrier for o in outcomes)),
        unserved_orders=unserved,
    )


# ---- istatistiksel karsilastirma ---------------------------------------------


class BootstrapComparison(BaseModel):
    """Iki politika arasindaki farkin guven arali ile birlikte tahmini."""

    model_config = ConfigDict(frozen=True)

    baseline: str
    treatment: str
    metric: str

    mean_difference: float
    """Pozitif = `treatment` daha ucuz (baz cizgi eksi tedavi)."""

    ci_low: float
    ci_high: float
    confidence: float
    relative_saving: float
    """Baz cizginin yuzdesi olarak tasarruf."""

    @property
    def is_significant(self) -> bool:
        """Guven araligi sifiri kapsamiyorsa fark istatistiksel olarak anlamli."""
        return not (self.ci_low <= 0.0 <= self.ci_high)

    def describe(self) -> str:
        verdict = "anlamli" if self.is_significant else "ANLAMSIZ (aralik sifiri kapsiyor)"
        return (
            f"{self.treatment} vs {self.baseline}: siparis basina "
            f"{self.mean_difference:+.2f} TL tasarruf "
            f"(%{self.relative_saving * 100:+.2f}), "
            f"%{self.confidence * 100:.0f} G.A. "
            f"[{self.ci_low:+.2f}, {self.ci_high:+.2f}] — {verdict}"
        )


def paired_bootstrap(
    baseline_costs: np.ndarray,
    treatment_costs: np.ndarray,
    *,
    baseline_name: str,
    treatment_name: str,
    metric: str = "siparis basina toplam maliyet",
    samples: int = 2000,
    confidence: float = 0.95,
    rng: np.random.Generator | None = None,
) -> BootstrapComparison:
    """Eslestirilmis bootstrap ile tasarruf farkinin guven araligi.

    Diziler **ayni siparisleri ayni sirada** temsil etmeli; eslestirmenin butun
    degeri bundan geliyor.
    """
    if baseline_costs.shape != treatment_costs.shape:
        raise ValueError("Eslestirilmis bootstrap ayni uzunlukta diziler gerektirir")
    if baseline_costs.size == 0:
        raise ValueError("Bos dizi ile bootstrap yapilamaz")

    rng = rng or np.random.default_rng(0)
    differences = baseline_costs - treatment_costs
    n = differences.size

    indexes = rng.integers(0, n, size=(samples, n))
    resampled_means = differences[indexes].mean(axis=1)

    tail = (1.0 - confidence) / 2.0
    low, high = np.percentile(resampled_means, [100 * tail, 100 * (1 - tail)])
    baseline_mean = float(baseline_costs.mean())

    return BootstrapComparison(
        baseline=baseline_name,
        treatment=treatment_name,
        metric=metric,
        mean_difference=float(differences.mean()),
        ci_low=float(low),
        ci_high=float(high),
        confidence=confidence,
        relative_saving=float(differences.mean() / baseline_mean) if baseline_mean else 0.0,
    )


# ---- kalibrasyon -------------------------------------------------------------


@dataclass(slots=True)
class CalibrationBin:
    """Kalibrasyon egrisinin bir kovasi."""

    lower: float
    upper: float
    count: int
    predicted_mean: float
    observed_rate: float


def calibration_curve(
    predicted: np.ndarray, observed: np.ndarray, bins: int = 8
) -> list[CalibrationBin]:
    """Tahmin edilen hasar olasiligi ile gerceklesen frekansi karsilastirir.

    Modelin **durustluk sinavi**: "%2 hasar olasiligi" dedigi gonderilerin
    gercekten yaklasik %2'si hasar gormeli. Iyi ayrim yapan ama kalibre olmayan
    bir model, dogru firmayi secse bile maliyetleri yanlis buyuklukte tahmin eder
    ve tasarruf raporu guvenilmez olur.

    Kovalar esit genislikte degil, **esit sayida gozlem** icerecek sekilde
    (quantile) olusturulur; hasar olasiliklari cok carpik dagildigi icin esit
    genislikli kovalarin cogu bos kalirdi.
    """
    if predicted.size != observed.size:
        raise ValueError("Tahmin ve gozlem dizileri ayni uzunlukta olmali")
    if predicted.size == 0:
        return []

    edges = np.unique(np.quantile(predicted, np.linspace(0, 1, bins + 1)))
    if edges.size < 2:
        return [
            CalibrationBin(
                lower=float(predicted.min()),
                upper=float(predicted.max()),
                count=int(predicted.size),
                predicted_mean=float(predicted.mean()),
                observed_rate=float(observed.mean()),
            )
        ]

    result: list[CalibrationBin] = []
    for lower, upper in pairwise(edges):
        is_last = upper == edges[-1]
        mask = (predicted >= lower) & ((predicted <= upper) if is_last else (predicted < upper))
        if not mask.any():
            continue
        result.append(
            CalibrationBin(
                lower=float(lower),
                upper=float(upper),
                count=int(mask.sum()),
                predicted_mean=float(predicted[mask].mean()),
                observed_rate=float(observed[mask].mean()),
            )
        )
    return result


def calibration_error(bins: list[CalibrationBin]) -> float:
    """Beklenen kalibrasyon hatasi (ECE): gozlem sayisiyla agirlikli ortalama sapma."""
    total = sum(b.count for b in bins)
    if not total:
        return float("nan")
    return sum(b.count * abs(b.predicted_mean - b.observed_rate) for b in bins) / total


@dataclass(slots=True)
class SensitivityResult:
    """Bir parametrenin sonuca etkisi (tornado grafigi girdisi)."""

    parameter: str
    low_value: float
    high_value: float
    saving_at_low: float
    saving_at_high: float
    baseline_saving: float

    @property
    def swing(self) -> float:
        """Tasarruf sonucundaki toplam salinim. Tornado cubugunun uzunlugu."""
        return abs(self.saving_at_high - self.saving_at_low)

    @property
    def flips_conclusion(self) -> bool:
        """Parametre, tasarrufun isaretini degistiriyor mu.

        Degistiriyorsa sonuc o varsayima *bagli* demektir ve raporda oyle sunulmali.
        """
        return (self.saving_at_low > 0) != (self.saving_at_high > 0)


def sensitivity_frame(results: list[SensitivityResult]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "parameter": r.parameter,
                "low_value": r.low_value,
                "high_value": r.high_value,
                "saving_at_low": r.saving_at_low,
                "saving_at_high": r.saving_at_high,
                "swing": r.swing,
                "flips_conclusion": r.flips_conclusion,
            }
            for r in results
        ]
    ).sort_values("swing", ascending=False)


@dataclass(slots=True)
class PolicyRecords:
    """Bir politikanin ham sonuc kayitlari; ozet ve bootstrap bunlardan uretilir."""

    outcomes: list[OrderOutcome] = field(default_factory=list)
    unserved: int = 0

    def cost_array(self) -> np.ndarray:
        return np.array([o.total_try for o in self.outcomes], dtype=float)

    def freight_array(self) -> np.ndarray:
        return np.array([o.freight_try for o in self.outcomes], dtype=float)
