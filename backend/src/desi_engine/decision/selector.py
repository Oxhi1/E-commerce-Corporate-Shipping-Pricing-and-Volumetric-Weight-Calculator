"""Karar motoru -- tum parcalari birlestirip firmayi secer.

Akis:

    sepet
      -> PackingPlanner        birkac aday koli plani
      -> her (firma, plan) icin:
           kisit denetimi      uygun mu
           FreightCalculator   F_k
           DamageCostModel     E[hasar]  (Bayesci p_hat x zarar fonksiyonu)
           DelayCostModel      Z_k
           ObjectiveParams     kuyruk riski primi
      -> firma basina en iyi plani sec
      -> firmalari skora gore sirala
      -> gerekce uret

Onemli tasarim notu: **plan secimi firma secimiyle birlikte yapilir.**
Once "en iyi plan"i secip sonra firma aramak yanlis olurdu; PTT'nin 50 desilik
parca siniri, tek koliye sikistiran plani onun icin uygunsuz kilarken iki koliye
bolen plani uygun kilar. Dogru cift, ancak ikisi birlikte arandiginda bulunur.
"""

from __future__ import annotations

from datetime import time

from ..domain.enums import CarrierCode
from ..domain.models import Order
from ..domain.units import chargeable_desi, money
from ..packing.packer import PackingPlan, PackingPlanner
from ..risk.damage_cost import DamageCostModel
from ..sla.delay_cost import DelayCostModel
from ..tariff.calculator import FreightCalculator
from ..tariff.loader import TariffRepository
from ..tariff.schema import Tariff
from ..tariff.zones import ProvinceRegistry
from .constraints import CapacityLedger, Eligibility, check_eligibility
from .explain import CarrierEvaluation, Decision, build_rationale, build_warnings
from .objective import CostComponents, ObjectiveParams, tail_premium


class NoEligibleCarrierError(RuntimeError):
    """Hicbir firma bu siparisi tasiyamiyor.

    Gercek hayatta bu bir istisna degil, bir is kurali ihlalidir: operasyona
    dusmesi ve elle cozulmesi gerekir. Sessizce en yakin firmayi secmek,
    Hakkari'ye hizmet vermeyen bir firmaya etiket bastirmak demektir.
    """


class CarrierSelector:
    """Cok firmali karar motoru."""

    def __init__(
        self,
        tariffs: TariffRepository,
        provinces: ProvinceRegistry,
        planner: PackingPlanner,
        calculator: FreightCalculator,
        damage_model: DamageCostModel,
        delay_model: DelayCostModel,
        params: ObjectiveParams | None = None,
    ) -> None:
        self.tariffs = tariffs
        self.provinces = provinces
        self.planner = planner
        self.calculator = calculator
        self.damage_model = damage_model
        self.delay_model = delay_model
        self.params = params or ObjectiveParams()

    # ---- genel arayuz -------------------------------------------------------

    def decide(
        self,
        order: Order,
        *,
        ledger: CapacityLedger | None = None,
        order_time: time | None = None,
    ) -> Decision:
        """Siparis icin firmayi secer ve tam gerekceyi uretir."""
        evaluations = self.evaluate_all(order, ledger=ledger, order_time=order_time)

        eligible = sorted((e for e in evaluations if e.eligible), key=lambda e: e.score_try)
        rejected = [e for e in evaluations if not e.eligible]

        if not eligible:
            reasons = "; ".join(
                f"{e.display_name}: {', '.join(e.ineligibility_reasons)}" for e in rejected
            )
            raise NoEligibleCarrierError(f"{order.order_id} icin uygun firma yok — {reasons}")

        selected = eligible[0]
        cheapest_freight = min(
            (e for e in eligible if e.freight), key=lambda e: e.freight_try, default=None
        )

        return Decision(
            order_id=order.order_id,
            zone=self.provinces.zone_class(order.origin_plate, order.address.city_plate),
            cart_value_try=order.cart.total_value_try,
            selected=selected,
            ranked=eligible,
            rejected=rejected,
            rationale=build_rationale(
                {
                    "selected": selected,
                    "cheapest_freight": cheapest_freight,
                    "rejected": rejected,
                }
            ),
            warnings=build_warnings(selected, len(eligible)),
        )

    def evaluate_all(
        self,
        order: Order,
        *,
        ledger: CapacityLedger | None = None,
        order_time: time | None = None,
    ) -> list[CarrierEvaluation]:
        """Her firma icin en iyi (firma, plan) ciftini degerlendirir."""
        plans = self.planner.candidates(order.cart)
        zone = self.provinces.zone_class(order.origin_plate, order.address.city_plate)

        results: list[CarrierEvaluation] = []
        for carrier in self.tariffs.carriers:
            tariff = self.tariffs.get(carrier)
            best, blockers = self._best_plan_for_carrier(
                tariff, order, plans, zone, ledger=ledger, order_time=order_time
            )
            results.append(
                best
                if best is not None
                else CarrierEvaluation(
                    carrier=carrier.value,
                    display_name=tariff.display_name,
                    eligible=False,
                    ineligibility_reasons=blockers,
                )
            )
        return results

    # ---- degerlendirme ------------------------------------------------------

    def _best_plan_for_carrier(
        self,
        tariff: Tariff,
        order: Order,
        plans: list[PackingPlan],
        zone,
        *,
        ledger: CapacityLedger | None,
        order_time: time | None,
    ) -> tuple[CarrierEvaluation | None, list[str]]:
        """Bu firma icin en dusuk skorlu plani bulur.

        Hicbir plan uygun degilse `(None, gerekceler)` doner; gerekceler tum
        planlarda ortaya cikan benzersiz engellerdir.
        """
        best: CarrierEvaluation | None = None
        blockers: list[str] = []

        for plan in plans:
            eligibility = check_eligibility(
                tariff, order, plan, ledger=ledger, order_time=order_time
            )
            if not eligibility.is_eligible:
                for reason in _reason_labels(eligibility):
                    if reason not in blockers:
                        blockers.append(reason)
                continue

            evaluation = self._evaluate(tariff, order, plan, zone)
            if best is None or evaluation.score_try < best.score_try:
                best = evaluation

        return best, blockers

    def _evaluate(self, tariff: Tariff, order: Order, plan: PackingPlan, zone) -> CarrierEvaluation:
        """Tek bir (firma, plan) cifti icin tam maliyet hesabi."""
        # Ucretli desi firmaya baglidir: yuvarlama kurali ve adimi sozlesmede yazar.
        parcel_desis = [
            chargeable_desi(
                volumetric=box.outer_desi,
                weight_kg=box.gross_weight_kg,
                rule=tariff.rounding,
                step=tariff.desi_step,
            )
            for box in plan.boxes
        ]

        freight = self.calculator.quote(
            tariff,
            parcel_desis,
            zone,
            declared_value_try=order.cart.total_value_try,
            is_cod=order.is_cod,
        )

        damage_total, per_box = self.damage_model.shipment_expected_cost(
            plan.boxes, tariff.carrier, zone, order.customer_clv_try
        )

        delay = self.delay_model.expected_cost(
            tariff.carrier,
            zone,
            tariff.service.promised_days(zone, is_rural=order.address.is_rural),
            is_rural=order.address.is_rural,
            customer_clv_try=order.customer_clv_try,
        )

        # Kuyruk riski: en riskli koli uzerinden. Toplam gonderi riskini kullanmak
        # cok parcali planlari haksiz cezalandirirdi -- her koli ayri bir kuyruk
        # olayidir, hepsi ayni anda gerceklesmez.
        riskiest = max(per_box, key=lambda item: item.probability * item.loss.total_try)
        premium = tail_premium(
            riskiest.probability, riskiest.loss.total_try, self.params.risk_aversion_lambda
        )

        components = CostComponents(
            freight_try=freight.total_try,
            damage_try=damage_total,
            delay_try=delay.total_try,
            packaging_try=(
                money(plan.packaging_cost_try) if self.params.include_packaging_cost else 0.0
            ),
            friction_try=self.params.friction_for(tariff.carrier.value),
            tail_premium_try=premium,
        )

        return CarrierEvaluation(
            carrier=tariff.carrier.value,
            display_name=tariff.display_name,
            eligible=True,
            plan_strategy=plan.strategy,
            plan_variant=plan.variant,
            parcel_count=plan.parcel_count,
            box_codes=[box.box.code for box in plan.boxes],
            chargeable_desi=sum(parcel_desis),
            contaminating_boxes=plan.contaminating_boxes,
            freight=freight,
            delay=delay,
            components=components,
            damage_probability=riskiest.probability,
            damage_probability_raw=riskiest.probability_raw,
            damage_loss_try=riskiest.loss.total_try,
            damage_prior_weight=riskiest.prior_weight,
            dominant_risk_category=riskiest.dominant_category,
            parcel_risk_categories=[item.dominant_category for item in per_box],
            parcel_loss_try=[item.loss.total_try for item in per_box],
        )

    # ---- yardimci -----------------------------------------------------------

    def cheapest_freight_carrier(self, order: Order) -> CarrierCode | None:
        """Mevcut sistemin secimi -- karsilastirma icin."""
        evaluations = [e for e in self.evaluate_all(order) if e.eligible and e.freight]
        if not evaluations:
            return None
        return CarrierCode(min(evaluations, key=lambda e: e.freight_try).carrier)


def _reason_labels(eligibility: Eligibility) -> list[str]:
    from .constraints import INELIGIBILITY_LABELS

    return [INELIGIBILITY_LABELS[reason] for reason in eligibility.reasons]
