"""Monte Carlo kosucusu -- politikalari ayni siparis akisinda yaristirir.

Metodolojik omurga uc ilkeye dayaniyor:

1. **Motor gercegi bilmez.**
   Karar motoru yalnizca gecmis veriden kestirdigi parametreleri kullanir.
   Sonuclar `TrueWorld`'un gercek olasiliklariyla gerceklestirilir. Motor bu
   yuzden -- gercek hayatta oldugu gibi -- yanilabilir.

2. **Ortak rastgele sayilar (CRN).**
   Her siparis icin rastgele olay cekilisleri **bir kez** yapilir ve tum
   politikalar ayni cekilisleri kullanir. "MNG'yi secseydim bu koli hasar gorur
   muydu" sorusu, ayni sansla cevaplanir. Bu olmadan politikalar arasindaki
   fark, siparislerin ve sansin gurultusunde kaybolurdu.

3. **Ayni degerlendirme, farkli secim.**
   Fiyatlama, paketleme ve risk hesabi siparis basina bir kez yapilir; politikalar
   yalnizca secim kuralinda ayrisir. Aksi halde "P3 daha iyi" sonucu, karar
   kuralindan mi farkli bir hesaplamadan mi geldigi anlasilamazdi.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Final

import numpy as np
from pydantic import BaseModel, ConfigDict

from ..decision.constraints import CapacityLedger
from ..decision.explain import CarrierEvaluation
from ..domain.enums import CarrierCode, PolicyCode
from ..domain.models import Order
from ..engine import Engine
from .generators import OrderGenerator, OrderGeneratorConfig
from .metrics import (
    BootstrapComparison,
    CalibrationBin,
    OrderOutcome,
    PolicyRecords,
    PolicySummary,
    calibration_curve,
    calibration_error,
    paired_bootstrap,
    summarize,
)
from .policies import Policy, default_policies
from .world import TrueWorld

#: Tek bir siparisin uretebilecegi azami koli sayisi. CRN cekilisleri bu boyutta
#: onceden yapilir; boylece politikalarin farkli koli sayilari ayni cekilislere
#: baksa bile ayni indeksten okur.
MAX_PARCELS_PER_ORDER: Final[int] = 12


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    """Kosu ayarlari."""

    n_orders: int = 20_000
    seed: int = 42
    days: int = 30
    """Kosunun kac gune yayildigi. Kapasite limitleri gun basina uygulanir."""

    capacity_share: float = 0.35
    """P4'te tek bir firmanin gunluk hacimden alabilecegi azami pay.
    1.0 verilirse kapasite kisiti fiilen devre disi kalir."""

    single_carrier: CarrierCode = CarrierCode.ARAS
    bootstrap_samples: int = 2000
    confidence: float = 0.95
    generator: OrderGeneratorConfig | None = None
    progress_every: int = 0
    """0'dan buyukse her N sipariste bir ilerleme yazdirir."""


@dataclass(slots=True)
class _CommonRandomNumbers:
    """Bir siparis icin, tum politikalarin paylastigi rastgele cekilisler."""

    damage_draws: np.ndarray
    """Koli basina tekduze [0,1) cekilis. Hasar: `cekilis < gercek_olasilik`."""

    delivery_z: float
    """Standart normal cekilis. Teslimat suresi: `exp(mu + sigma * z)`."""

    return_draw: float
    churn_draw: float


class SimulationResult(BaseModel):
    """Bir kosunun tum ciktilari."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    n_orders: int
    seed: int
    elapsed_seconds: float

    summaries: dict[PolicyCode, PolicySummary]
    comparisons: list[BootstrapComparison]
    calibration: list[CalibrationBin]
    calibration_error: float
    packing_cache_hit_rate: float

    def summary_table(self) -> list[dict]:
        """Rapor ve arayuz icin duz tablo."""
        return [
            {
                "policy": summary.policy_code.value,
                "label": summary.label,
                "cost_per_order_try": summary.cost_per_order_try,
                "freight_per_order_try": summary.freight_per_order_try,
                "hidden_cost_share": summary.hidden_cost_share,
                "damage_rate": summary.damage_rate,
                "late_rate": summary.late_rate,
                "mean_delivery_days": summary.mean_delivery_days,
                "mean_parcels": summary.mean_parcels,
                "mean_desi": summary.mean_chargeable_desi,
            }
            for summary in self.summaries.values()
        ]

    def headline(self) -> str:
        """Yonetime gosterilecek tek cumle -- guven araligiyla birlikte."""
        against_baseline = [c for c in self.comparisons if c.baseline.startswith("P0")]
        if not against_baseline:
            return "Karsilastirma uretilemedi."
        best = max(against_baseline, key=lambda c: c.mean_difference)
        return best.describe()


class SimulationRunner:
    """Politikalari ayni siparis akisi uzerinde yaristirir."""

    def __init__(
        self,
        engine: Engine,
        config: SimulationConfig | None = None,
        policies: list[Policy] | None = None,
    ) -> None:
        self.engine = engine
        self.config = config or SimulationConfig()
        self.policies = policies or default_policies(self.config.single_carrier)
        self.world = TrueWorld.from_tariffs(engine.tariffs)

    # ---- kosu ---------------------------------------------------------------

    def run(self) -> SimulationResult:
        started = time.perf_counter()
        config = self.config

        rng = np.random.default_rng(config.seed)
        generator = OrderGenerator(self.engine.products, self.engine.provinces, config.generator)

        records: dict[PolicyCode, PolicyRecords] = {p.code: PolicyRecords() for p in self.policies}
        ledgers = self._build_ledgers()
        orders_per_day = max(1, config.n_orders // max(1, config.days))

        for index, order in enumerate(generator.stream(config.n_orders, rng)):
            if index % orders_per_day == 0:
                for ledger in ledgers.values():
                    if ledger is not None:
                        ledger.reset()

            evaluations = self.engine.selector.evaluate_all(order)
            crn = self._draw(rng)
            zone = self.engine.provinces.zone_class(order.origin_plate, order.address.city_plate)

            for policy in self.policies:
                ledger = ledgers[policy.code]
                chosen = policy.choose(evaluations, ledger)
                if chosen is None:
                    records[policy.code].unserved += 1
                    continue
                if ledger is not None:
                    ledger.consume(CarrierCode(chosen.carrier), chosen.parcel_count)
                records[policy.code].outcomes.append(self._realize(order, zone, chosen, crn))

            if config.progress_every and (index + 1) % config.progress_every == 0:
                print(f"  {index + 1:,}/{config.n_orders:,} siparis islendi")

        return self._assemble(records, time.perf_counter() - started)

    # ---- gerceklestirme -----------------------------------------------------

    def _draw(self, rng: np.random.Generator) -> _CommonRandomNumbers:
        return _CommonRandomNumbers(
            damage_draws=rng.random(MAX_PARCELS_PER_ORDER),
            delivery_z=float(rng.standard_normal()),
            return_draw=float(rng.random()),
            churn_draw=float(rng.random()),
        )

    def _realize(
        self,
        order: Order,
        zone,
        evaluation: CarrierEvaluation,
        crn: _CommonRandomNumbers,
    ) -> OrderOutcome:
        """Secilen firmanin gercek dunyada basina ne geldigini hesaplar."""
        carrier = CarrierCode(evaluation.carrier)
        damage_params = self.engine.damage_model.params
        delay_params = self.engine.delay_model.params

        # -- hasar: koli koli gerceklestir
        damage_cost = 0.0
        any_damage = False
        for index, category in enumerate(evaluation.parcel_risk_categories):
            true_rate = self.world.damage_rate(carrier, zone, category)
            if crn.damage_draws[index % MAX_PARCELS_PER_ORDER] < true_rate:
                any_damage = True
                damage_cost += evaluation.parcel_loss_try[index]
        if any_damage and crn.churn_draw < damage_params.churn_probability:
            damage_cost += order.customer_clv_try

        # -- teslimat: ayni z cekilisi ile
        distribution = self.world.delivery_distribution(
            carrier, zone, is_rural=order.address.is_rural
        )
        delivery_days = float(np.exp(distribution.mu + distribution.sigma * crn.delivery_z))
        promised = evaluation.delay.promised_days if evaluation.delay else 0
        late = delivery_days > promised

        delay_cost = 0.0
        if late:
            delay_cost += delay_params.call_center_cost_try
            if crn.return_draw < delay_params.return_probability_if_late:
                delay_cost += delay_params.return_cost_try
            if crn.churn_draw < delay_params.churn_probability_if_late:
                delay_cost += order.customer_clv_try
            lateness = min(delivery_days - promised, delay_params.max_charged_lateness_days)
            delay_cost += lateness * delay_params.goodwill_per_day_try

        components = evaluation.components
        assert components is not None

        return OrderOutcome(
            order_id=order.order_id,
            carrier=evaluation.carrier,
            freight_try=components.freight_try,
            packaging_try=components.packaging_try,
            damage_try=damage_cost,
            delay_try=delay_cost,
            parcels=evaluation.parcel_count,
            chargeable_desi=evaluation.chargeable_desi,
            delivery_days=delivery_days,
            promised_days=promised,
            damaged=any_damage,
            late=late,
            predicted_damage_probability=evaluation.damage_probability,
        )

    # ---- kurulum ve toplama -------------------------------------------------

    def _build_ledgers(self) -> dict[PolicyCode, CapacityLedger | None]:
        """Yalnizca P4 kapasite kisiti tasir; digerleri sinirsiz calisir."""
        config = self.config
        if config.capacity_share >= 1.0:
            return {policy.code: None for policy in self.policies}

        daily_volume = max(1, config.n_orders // max(1, config.days))
        cap = max(1, int(daily_volume * config.capacity_share))
        return {
            policy.code: (
                CapacityLedger(daily_limits={c: cap for c in CarrierCode})
                if policy.code is PolicyCode.P4_TELC_CONSTRAINED
                else None
            )
            for policy in self.policies
        }

    def _assemble(
        self, records: dict[PolicyCode, PolicyRecords], elapsed: float
    ) -> SimulationResult:
        labels = {policy.code: policy.label for policy in self.policies}
        summaries = {
            code: summarize(code, labels[code], record.outcomes, record.unserved)
            for code, record in records.items()
            if record.outcomes
        }

        comparisons = self._compare(records, labels)
        bins, error = self._calibration(records)

        return SimulationResult(
            n_orders=self.config.n_orders,
            seed=self.config.seed,
            elapsed_seconds=elapsed,
            summaries=summaries,
            comparisons=comparisons,
            calibration=bins,
            calibration_error=error,
            packing_cache_hit_rate=self.engine.planner.cache_hit_rate,
        )

    def _compare(
        self, records: dict[PolicyCode, PolicyRecords], labels: dict[PolicyCode, str]
    ) -> list[BootstrapComparison]:
        """Motoru (P3, P4) mevcut duruma (P0) ve yaygin pratige (P1) karsi olcer."""
        rng = np.random.default_rng(self.config.seed + 1)
        comparisons: list[BootstrapComparison] = []

        baselines = [PolicyCode.P0_SINGLE_CARRIER, PolicyCode.P1_CHEAPEST_FREIGHT]
        treatments = [PolicyCode.P3_TELC, PolicyCode.P4_TELC_CONSTRAINED]

        for baseline in baselines:
            for treatment in treatments:
                if baseline not in records or treatment not in records:
                    continue
                base_costs = records[baseline].cost_array()
                treat_costs = records[treatment].cost_array()
                # Eslestirme ancak ayni siparisler islendiyse gecerli; bir politika
                # bazi siparisleri tasiyamadiysa (unserved) diziler ayrisir.
                if base_costs.size != treat_costs.size:
                    continue
                comparisons.append(
                    paired_bootstrap(
                        base_costs,
                        treat_costs,
                        baseline_name=f"{baseline.value} {labels[baseline]}",
                        treatment_name=f"{treatment.value} {labels[treatment]}",
                        samples=self.config.bootstrap_samples,
                        confidence=self.config.confidence,
                        rng=rng,
                    )
                )
        return comparisons

    def _calibration(
        self, records: dict[PolicyCode, PolicyRecords]
    ) -> tuple[list[CalibrationBin], float]:
        """Motorun hasar tahminleri gerceklesen frekansla ortusuyor mu."""
        record = records.get(PolicyCode.P3_TELC)
        if record is None or not record.outcomes:
            return [], float("nan")

        predicted = np.array([o.predicted_damage_probability for o in record.outcomes])
        observed = np.array([float(o.damaged) for o in record.outcomes])
        bins = calibration_curve(predicted, observed)
        return bins, calibration_error(bins)


@dataclass(slots=True)
class SensitivitySweep:
    """Bir parametreyi iki uc degerde kosturup sonucun ne kadar kaydigini olcer."""

    parameter: str
    low: float
    high: float
    apply: object = field(repr=False)
    """`(EngineConfig kwargs, deger) -> yeni kwargs` seklinde bir fonksiyon."""
