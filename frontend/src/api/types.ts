/**
 * Backend sozlesmesinin TypeScript karsiligi.
 *
 * Elle yazildi (OpenAPI'den uretilmedi) cunku bu yuzey kucuk ve kararli; kod
 * uretimi zinciri eklemek staj projesinin karmasikligini gereksiz artirirdi.
 * Backend semasi degistiginde burasi da guncellenmeli -- `npm run typecheck`
 * kullanim yerlerindeki uyumsuzluklari yakalar.
 */

export interface CartLineIn {
  sku: string;
  quantity: number;
}

export interface OrderIn {
  lines: CartLineIn[];
  city_plate: number;
  is_rural?: boolean;
  is_cod?: boolean;
  customer_clv_try?: number;
  order_id?: string;
}

export interface Product {
  sku: string;
  name: string;
  category: string;
  risk_category: string;
  length_cm: number;
  width_cm: number;
  height_cm: number;
  weight_kg: number;
  unit_price_try: number;
  desi: number;
  fragility: string;
  is_liquid: boolean;
  is_absorbent: boolean;
}

export interface City {
  plate: number;
  name: string;
  region: string;
  is_remote: boolean;
}

export interface Carrier {
  code: string;
  display_name: string;
  is_synthetic_tariff: boolean;
  note: string;
  min_charge_try: number;
  max_desi_per_parcel: number;
  unserved_plates: number[];
  sla_days: Record<string, number>;
}

export interface Placement {
  sku: string;
  name: string;
  x: number;
  y: number;
  z: number;
  dx: number;
  dy: number;
  dz: number;
  is_liquid: boolean;
  is_absorbent: boolean;
  risk_category: string;
}

export interface PackedBox {
  box_code: string;
  box_name: string;
  inner_length_cm: number;
  inner_width_cm: number;
  inner_height_cm: number;
  outer_desi: number;
  gross_weight_kg: number;
  fill_ratio: number;
  placements: Placement[];
}

export interface Baselines {
  quoted_sum_desi: number;
  one_box_per_item_desi: number;
  one_box_per_item_parcels: number;
  volume_rule_desi: number;
  volume_rule_parcels: number;
}

export interface PackingPlan {
  strategy: string;
  variant: string;
  parcel_count: number;
  packed_desi: number;
  desi_savings_pct: number;
  quote_gap_pct: number;
  mean_fill_ratio: number;
  contaminating_boxes: number;
  packaging_cost_try: number;
  boxes: PackedBox[];
}

export interface PackResponse {
  baselines: Baselines;
  plans: PackingPlan[];
}

export interface CostLine {
  label: string;
  amount_try: number;
}

export interface Delay {
  promised_days: number;
  expected_days: number;
  p95_days: number;
  probability_late: number;
  total_try: number;
  estimate_source: string;
  observations: number;
}

export interface CarrierEvaluation {
  carrier: string;
  display_name: string;
  eligible: boolean;
  ineligibility_reasons: string[];
  plan_strategy: string;
  plan_variant: string;
  parcel_count: number;
  box_codes: string[];
  chargeable_desi: number;
  contaminating_boxes: number;
  freight_try: number | null;
  damage_try: number | null;
  delay_try: number | null;
  packaging_try: number | null;
  tail_premium_try: number | null;
  expected_total_try: number | null;
  score_try: number | null;
  hidden_cost_try: number | null;
  damage_probability: number;
  damage_probability_raw: number | null;
  damage_loss_try: number;
  damage_prior_weight: number;
  is_low_confidence: boolean;
  dominant_risk_category: string | null;
  delay: Delay | null;
  cost_lines: CostLine[];
}

export interface DecisionResponse {
  order_id: string;
  zone: string;
  city_name: string;
  cart_value_try: number;
  selected: CarrierEvaluation;
  ranked: CarrierEvaluation[];
  rejected: CarrierEvaluation[];
  margin_try: number;
  margin_pct: number;
  overrode_cheapest_freight: boolean;
  cheapest_freight_carrier: string | null;
  savings_vs_cheapest_freight_try: number;
  rationale: string[];
  warnings: string[];
}

export interface RiskCell {
  carrier: string;
  zone: string;
  risk_category: string;
  shipments: number;
  damages: number;
  raw_rate: number | null;
  shrunk_rate: number;
  ci_low: number;
  ci_high: number;
  upper_95: number;
  prior_weight: number;
}

export interface RiskHeatmap {
  global_rate: number;
  total_shipments: number;
  kappas: Record<string, number>;
  cells: RiskCell[];
}

export interface ShippingLabel {
  tracking_number: string;
  carrier: string;
  carrier_display: string;
  parcel_index: number;
  parcel_count: number;
  box_code: string;
  chargeable_desi: number;
  recipient: string;
  zone: string;
  is_cod: boolean;
  cod_amount_try: number;
  decision_note: string;
  is_synthetic_tariff: boolean;
  barcode_svg: string;
  zpl: string;
}

export interface LabelResponse {
  order_id: string;
  carrier: string;
  labels: ShippingLabel[];
}

export interface PolicySummary {
  policy: string;
  label: string;
  orders: number;
  cost_per_order_try: number;
  freight_per_order_try: number;
  hidden_cost_share: number;
  damage_rate: number;
  late_rate: number;
  mean_delivery_days: number;
  mean_parcels: number;
  mean_chargeable_desi: number;
  carrier_mix: Record<string, number>;
}

export interface Comparison {
  baseline: string;
  treatment: string;
  mean_difference: number;
  ci_low: number;
  ci_high: number;
  relative_saving: number;
  is_significant: boolean;
  description: string;
}

export interface CalibrationBin {
  lower: number;
  upper: number;
  count: number;
  predicted_mean: number;
  observed_rate: number;
}

export interface SimulationResult {
  run_id: string;
  n_orders: number;
  seed: number;
  elapsed_seconds: number;
  headline: string;
  summaries: PolicySummary[];
  comparisons: Comparison[];
  calibration: CalibrationBin[];
  calibration_error: number;
}

export interface SimulationStatus {
  run_id: string;
  state: "pending" | "running" | "done" | "failed";
  progress: number;
  message: string;
}
