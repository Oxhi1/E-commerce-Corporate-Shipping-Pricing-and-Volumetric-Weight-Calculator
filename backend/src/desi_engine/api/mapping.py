"""Ic modellerden API semalarina donusum.

Bu katmanin tek isi cevirmek; hicbir karar burada verilmez. Ayri bir modulde
durmasi, `routers` icindeki uc nokta tanimlarinin okunabilir kalmasini sagliyor.
"""

from __future__ import annotations

import math

from ..decision.explain import CarrierEvaluation, Decision
from ..domain.models import Product
from ..packing.packer import PackingPlan
from ..tariff.schema import Tariff
from ..tariff.zones import Province
from . import schemas as api


def _finite(value: float | None) -> float | None:
    """JSON `NaN`/`Infinity` tasiyamaz; bunlari `null`'a cevirir.

    Ham hasar orani gorulmemis bir hucrede `NaN` olabilir ve skor, uygun olmayan
    bir firmada `inf`'tir. Ikisi de gecerli JSON degil -- sessizce bozuk cevap
    uretmek yerine acikca `null` donuyoruz.
    """
    if value is None or not math.isfinite(value):
        return None
    return value


def product_out(product: Product) -> api.ProductOut:
    return api.ProductOut(
        sku=product.sku,
        name=product.name,
        category=product.category.value,
        risk_category=product.risk_category.value,
        length_cm=product.dims.length_cm,
        width_cm=product.dims.width_cm,
        height_cm=product.dims.height_cm,
        weight_kg=product.weight_kg,
        unit_price_try=product.unit_price_try,
        desi=round(product.dims.desi, 3),
        fragility=product.fragility.value,
        is_liquid=product.is_liquid,
        is_absorbent=product.is_absorbent,
    )


def city_out(province: Province) -> api.CityOut:
    return api.CityOut(
        plate=province.plate,
        name=province.name,
        region=province.region.value,
        is_remote=province.is_remote,
    )


def carrier_out(tariff: Tariff) -> api.CarrierOut:
    return api.CarrierOut(
        code=tariff.carrier.value,
        display_name=tariff.display_name,
        is_synthetic_tariff=tariff.is_synthetic,
        note=tariff.note,
        min_charge_try=tariff.min_charge,
        max_desi_per_parcel=tariff.constraints.max_desi_per_parcel,
        unserved_plates=tariff.constraints.unserved_plates,
        sla_days={zone.value: days for zone, days in tariff.service.sla_days.items()},
    )


def packing_plan_out(plan: PackingPlan) -> api.PackingPlanOut:
    return api.PackingPlanOut(
        strategy=plan.strategy,
        variant=plan.variant,
        parcel_count=plan.parcel_count,
        packed_desi=round(plan.packed_desi, 2),
        desi_savings_pct=plan.desi_savings_pct,
        quote_gap_pct=plan.quote_gap_pct,
        mean_fill_ratio=plan.mean_fill_ratio,
        contaminating_boxes=plan.contaminating_boxes,
        packaging_cost_try=plan.packaging_cost_try,
        boxes=[
            api.PackedBoxOut(
                box_code=packed.box.code,
                box_name=packed.box.name,
                inner_length_cm=packed.box.inner.length_cm,
                inner_width_cm=packed.box.inner.width_cm,
                inner_height_cm=packed.box.inner.height_cm,
                outer_desi=round(packed.outer_desi, 2),
                gross_weight_kg=round(packed.gross_weight_kg, 2),
                fill_ratio=packed.fill_ratio,
                placements=[
                    api.PlacementOut(
                        sku=placement.sku,
                        name=placement.name,
                        x=placement.x,
                        y=placement.y,
                        z=placement.z,
                        dx=placement.dx,
                        dy=placement.dy,
                        dz=placement.dz,
                        is_liquid=placement.is_liquid,
                        is_absorbent=placement.is_absorbent,
                        risk_category=placement.risk_category.value,
                    )
                    for placement in packed.placements
                ],
            )
            for packed in plan.boxes
        ],
    )


def evaluation_out(evaluation: CarrierEvaluation) -> api.CarrierEvaluationOut:
    components = evaluation.components
    delay = evaluation.delay

    return api.CarrierEvaluationOut(
        carrier=evaluation.carrier,
        display_name=evaluation.display_name,
        eligible=evaluation.eligible,
        ineligibility_reasons=evaluation.ineligibility_reasons,
        plan_strategy=evaluation.plan_strategy,
        plan_variant=evaluation.plan_variant,
        parcel_count=evaluation.parcel_count,
        box_codes=evaluation.box_codes,
        chargeable_desi=evaluation.chargeable_desi,
        contaminating_boxes=evaluation.contaminating_boxes,
        freight_try=components.freight_try if components else None,
        damage_try=components.damage_try if components else None,
        delay_try=components.delay_try if components else None,
        packaging_try=components.packaging_try if components else None,
        tail_premium_try=components.tail_premium_try if components else None,
        expected_total_try=_finite(evaluation.expected_total_try),
        score_try=_finite(evaluation.score_try),
        hidden_cost_try=components.hidden_cost_try if components else None,
        damage_probability=evaluation.damage_probability,
        damage_probability_raw=_finite(evaluation.damage_probability_raw),
        damage_loss_try=evaluation.damage_loss_try,
        damage_prior_weight=evaluation.damage_prior_weight,
        is_low_confidence=evaluation.is_low_confidence,
        dominant_risk_category=(
            evaluation.dominant_risk_category.value if evaluation.dominant_risk_category else None
        ),
        delay=(
            api.DelayOut(
                promised_days=delay.promised_days,
                expected_days=delay.expected_days,
                p95_days=delay.p95_days,
                probability_late=delay.probability_late,
                total_try=delay.total_try,
                estimate_source=delay.estimate_source,
                observations=delay.observations,
            )
            if delay
            else None
        ),
        cost_lines=[
            api.CostLineOut(label=label, amount_try=amount)
            for label, amount in (components.explain_lines() if components else [])
        ],
    )


def decision_out(decision: Decision, city_name: str) -> api.DecisionResponse:
    cheapest = decision.cheapest_freight
    return api.DecisionResponse(
        order_id=decision.order_id,
        zone=decision.zone.value,
        city_name=city_name,
        cart_value_try=decision.cart_value_try,
        selected=evaluation_out(decision.selected),
        ranked=[evaluation_out(e) for e in decision.ranked],
        rejected=[evaluation_out(e) for e in decision.rejected],
        margin_try=decision.margin_try,
        margin_pct=decision.margin_pct,
        overrode_cheapest_freight=decision.overrode_cheapest_freight,
        cheapest_freight_carrier=cheapest.carrier if cheapest else None,
        savings_vs_cheapest_freight_try=decision.savings_vs_cheapest_freight_try,
        rationale=decision.rationale,
        warnings=decision.warnings,
    )
