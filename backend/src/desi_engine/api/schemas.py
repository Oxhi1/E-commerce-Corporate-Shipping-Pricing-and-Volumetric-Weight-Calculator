"""API istek ve cevap semalari.

Ic modeller (`domain`, `decision`) dogrudan API'ye acilmiyor. Sebep: ic modeller
algoritmanin ihtiyaclarina gore sekillenir ve sik degisir; API sozlesmesi ise
aray uzun bagli oldugu, kararli kalmasi gereken bir yuzey. Ikisini ayirmak,
motoru yeniden duzenlerken aray uzu kirmadan calisabilmeyi sagliyor.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class CartLineIn(BaseModel):
    """Sepet satiri girdisi."""

    sku: str = Field(description="Katalog urun kodu", examples=["HV-003"])
    quantity: Annotated[int, Field(ge=1, le=99)] = 1


class OrderIn(BaseModel):
    """Fiyatlanacak siparis girdisi."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "lines": [
                        {"sku": "GD-001", "quantity": 1},
                        {"sku": "NV-002", "quantity": 1},
                    ],
                    "city_plate": 65,
                    "is_cod": True,
                    "customer_clv_try": 4500,
                }
            ]
        }
    )

    lines: list[CartLineIn] = Field(min_length=1)
    city_plate: Annotated[int, Field(ge=1, le=81)]
    is_rural: bool = False
    is_cod: bool = False
    customer_clv_try: Annotated[float, Field(ge=0)] = 0.0
    order_id: str = "API-001"


# ---- katalog -----------------------------------------------------------------


class ProductOut(BaseModel):
    sku: str
    name: str
    category: str
    risk_category: str
    length_cm: float
    width_cm: float
    height_cm: float
    weight_kg: float
    unit_price_try: float
    desi: float
    fragility: str
    is_liquid: bool
    is_absorbent: bool


class CityOut(BaseModel):
    plate: int
    name: str
    region: str
    is_remote: bool


class CarrierOut(BaseModel):
    code: str
    display_name: str
    is_synthetic_tariff: bool
    note: str
    min_charge_try: float
    max_desi_per_parcel: float
    unserved_plates: list[int]
    sla_days: dict[str, int]


# ---- paketleme ---------------------------------------------------------------


class PlacementOut(BaseModel):
    """Bir urunun koli icindeki konumu -- 3B gorsellestirmenin veri kaynagi."""

    sku: str
    name: str
    x: float
    y: float
    z: float
    dx: float
    dy: float
    dz: float
    is_liquid: bool
    is_absorbent: bool
    risk_category: str


class PackedBoxOut(BaseModel):
    box_code: str
    box_name: str
    inner_length_cm: float
    inner_width_cm: float
    inner_height_cm: float
    outer_desi: float
    gross_weight_kg: float
    fill_ratio: float
    placements: list[PlacementOut]


class BaselinesOut(BaseModel):
    quoted_sum_desi: float
    one_box_per_item_desi: float
    one_box_per_item_parcels: int
    volume_rule_desi: float
    volume_rule_parcels: int


class PackingPlanOut(BaseModel):
    strategy: str
    variant: str
    parcel_count: int
    packed_desi: float
    desi_savings_pct: float
    quote_gap_pct: float
    mean_fill_ratio: float
    contaminating_boxes: int
    packaging_cost_try: float
    boxes: list[PackedBoxOut]


class PackResponse(BaseModel):
    baselines: BaselinesOut
    plans: list[PackingPlanOut]


# ---- fiyatlama ve karar ------------------------------------------------------


class CostLineOut(BaseModel):
    label: str
    amount_try: float


class FreightQuoteOut(BaseModel):
    carrier: str
    display_name: str
    is_synthetic_tariff: bool
    parcel_count: int
    chargeable_desi: float
    total_try: float
    subtotal_before_vat_try: float
    vat_try: float
    lines: list[CostLineOut]


class RateResponse(BaseModel):
    zone: str
    city_name: str
    quotes: list[FreightQuoteOut]
    ineligible: list[dict[str, str]]
    synthetic_tariff_warning: bool


class DelayOut(BaseModel):
    promised_days: int
    expected_days: float
    p95_days: float
    probability_late: float
    total_try: float
    estimate_source: str
    observations: int


class CarrierEvaluationOut(BaseModel):
    carrier: str
    display_name: str
    eligible: bool
    ineligibility_reasons: list[str]

    plan_strategy: str = ""
    plan_variant: str = ""
    parcel_count: int = 0
    box_codes: list[str] = Field(default_factory=list)
    chargeable_desi: float = 0.0
    contaminating_boxes: int = 0

    freight_try: float | None = None
    damage_try: float | None = None
    delay_try: float | None = None
    packaging_try: float | None = None
    tail_premium_try: float | None = None
    expected_total_try: float | None = None
    score_try: float | None = None
    hidden_cost_try: float | None = None

    damage_probability: float = 0.0
    damage_probability_raw: float | None = None
    damage_loss_try: float = 0.0
    damage_prior_weight: float = 1.0
    is_low_confidence: bool = False
    dominant_risk_category: str | None = None

    delay: DelayOut | None = None
    cost_lines: list[CostLineOut] = Field(default_factory=list)


class DecisionResponse(BaseModel):
    """`/decide` cevabi -- asla ciplak bir firma adi degil, tam gerekce agaci."""

    order_id: str
    zone: str
    city_name: str
    cart_value_try: float

    selected: CarrierEvaluationOut
    ranked: list[CarrierEvaluationOut]
    rejected: list[CarrierEvaluationOut]

    margin_try: float
    margin_pct: float
    overrode_cheapest_freight: bool
    cheapest_freight_carrier: str | None
    savings_vs_cheapest_freight_try: float

    rationale: list[str]
    warnings: list[str]


# ---- risk --------------------------------------------------------------------


class RiskCellOut(BaseModel):
    carrier: str
    zone: str
    risk_category: str
    shipments: int
    damages: int
    raw_rate: float | None
    shrunk_rate: float
    ci_low: float
    ci_high: float
    upper_95: float
    prior_weight: float


class RiskHeatmapResponse(BaseModel):
    global_rate: float
    total_shipments: int
    kappas: dict[str, float]
    cells: list[RiskCellOut]


# ---- etiket ------------------------------------------------------------------


class LabelOut(BaseModel):
    tracking_number: str
    carrier: str
    carrier_display: str
    parcel_index: int
    parcel_count: int
    box_code: str
    chargeable_desi: float
    recipient: str
    zone: str
    is_cod: bool
    cod_amount_try: float
    decision_note: str
    is_synthetic_tariff: bool
    barcode_svg: str
    zpl: str


class LabelResponse(BaseModel):
    order_id: str
    carrier: str
    labels: list[LabelOut]


# ---- simulasyon --------------------------------------------------------------


class SimulationRequest(BaseModel):
    n_orders: Annotated[int, Field(ge=100, le=100_000)] = 5_000
    seed: int = 42
    capacity_share: Annotated[float, Field(gt=0, le=1.0)] = 0.35
    risk_aversion_lambda: Annotated[float, Field(ge=0, le=5)] = 0.0


class PolicySummaryOut(BaseModel):
    policy: str
    label: str
    orders: int
    cost_per_order_try: float
    freight_per_order_try: float
    hidden_cost_share: float
    damage_rate: float
    late_rate: float
    mean_delivery_days: float
    mean_parcels: float
    mean_chargeable_desi: float
    carrier_mix: dict[str, int]


class ComparisonOut(BaseModel):
    baseline: str
    treatment: str
    mean_difference: float
    ci_low: float
    ci_high: float
    relative_saving: float
    is_significant: bool
    description: str


class CalibrationBinOut(BaseModel):
    lower: float
    upper: float
    count: int
    predicted_mean: float
    observed_rate: float


class SimulationStatus(BaseModel):
    run_id: str
    state: str = Field(description="pending | running | done | failed")
    progress: float = 0.0
    message: str = ""


class SimulationResultOut(BaseModel):
    run_id: str
    n_orders: int
    seed: int
    elapsed_seconds: float
    headline: str
    summaries: list[PolicySummaryOut]
    comparisons: list[ComparisonOut]
    calibration: list[CalibrationBinOut]
    calibration_error: float
