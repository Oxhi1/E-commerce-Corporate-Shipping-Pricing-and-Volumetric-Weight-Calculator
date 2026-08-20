"""Karar ciktilari ve gerekce uretimi.

Motor asla ciplak bir firma adi dondurmez. Her karar; secilen firmayi, elenen
firmalari ve gerekcelerini, her adayin kalem kalem maliyetini ve -- en onemlisi --
**en ucuz nakliye teklifi neden reddedildigini** tasir.

Bu bir susleme degil. Depoda etiket basacak personel, bugune kadar "en ucuzu
sec" kuralıyla calisti; sistem ondan pahali gorunen bir firmayi secmesini
istiyorsa gerekcesini gostermek zorunda. Gerekce gosteremeyen bir motor,
ilk itirazda devre disi birakilir.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ..domain.enums import RiskCategory, ZoneClass
from ..domain.units import money
from ..sla.delay_cost import DelayCost
from ..tariff.calculator import FreightQuote
from .objective import CostComponents


class CarrierEvaluation(BaseModel):
    """Tek bir firmanin tek bir koli plani icin tam degerlendirmesi."""

    model_config = ConfigDict(frozen=True)

    carrier: str
    display_name: str

    eligible: bool
    ineligibility_reasons: list[str] = Field(default_factory=list)

    # -- secilen koli plani
    plan_strategy: str = ""
    plan_variant: str = ""
    parcel_count: int = 0
    box_codes: list[str] = Field(default_factory=list)
    chargeable_desi: float = 0.0
    contaminating_boxes: int = 0

    # -- maliyet bilesenleri
    freight: FreightQuote | None = None
    delay: DelayCost | None = None
    components: CostComponents | None = None

    # -- risk tanilamasi
    damage_probability: float = 0.0
    damage_probability_raw: float = float("nan")
    damage_loss_try: float = 0.0
    damage_prior_weight: float = 1.0
    dominant_risk_category: RiskCategory | None = None

    # -- koli duzeyinde gerceklestirme girdileri
    #
    # Simulasyon, hasari koli koli **gerceklestirmek** zorunda: gercek dunyanin
    # hasar olasiligi koli icerigine bagli ve motorun tahmininden farkli. Bu iki
    # alan, `PackingPlan`'i simulasyona kadar tasimadan bunu mumkun kilar.
    parcel_risk_categories: list[RiskCategory] = Field(default_factory=list)
    parcel_loss_try: list[float] = Field(
        default_factory=list,
        description="Koli basina, hasar gerceklesirse olusacak zarar (churn haric)",
    )

    @property
    def score_try(self) -> float:
        """Siralama skoru. Uygun degilse sonsuz -- her zaman en sona duser."""
        return self.components.score_try if self.components else float("inf")

    @property
    def expected_total_try(self) -> float:
        return self.components.expected_total_try if self.components else float("inf")

    @property
    def freight_try(self) -> float:
        return self.freight.total_try if self.freight else float("inf")

    @property
    def uses_synthetic_tariff(self) -> bool:
        """True ise arayuz 'ORNEK TARIFE' rozeti gostermek zorundadir."""
        return bool(self.freight and self.freight.is_synthetic_tariff)

    @property
    def is_low_confidence(self) -> bool:
        """Hasar tahmininin yarisindan fazlasi onselden geliyorsa veri zayif."""
        return self.damage_prior_weight > 0.5


class Decision(BaseModel):
    """Bir siparis icin nihai karar ve tam gerekce agaci."""

    model_config = ConfigDict(frozen=True)

    order_id: str
    zone: ZoneClass
    cart_value_try: float

    selected: CarrierEvaluation
    ranked: list[CarrierEvaluation] = Field(description="Uygun adaylar, skora gore sirali")
    rejected: list[CarrierEvaluation] = Field(
        default_factory=list, description="Kisitlardan gecemeyen firmalar"
    )

    rationale: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    # ---- karar kalitesi olculeri --------------------------------------------

    @property
    def runner_up(self) -> CarrierEvaluation | None:
        return self.ranked[1] if len(self.ranked) > 1 else None

    @property
    def margin_try(self) -> float:
        """Kazananla ikincinin arasindaki fark.

        Kucuk bir marj, kararin parametre degisimlerine duyarli oldugunu gosterir;
        duyarlilik analizinde bu siparisler once kayar.
        """
        runner_up = self.runner_up
        return money(runner_up.score_try - self.selected.score_try) if runner_up else 0.0

    @property
    def margin_pct(self) -> float:
        if not self.runner_up or self.selected.score_try <= 0:
            return 0.0
        return self.margin_try / self.selected.score_try

    @property
    def cheapest_freight(self) -> CarrierEvaluation | None:
        """En dusuk nakliye faturasi veren uygun firma -- mevcut sistemin secimi."""
        eligible = [e for e in self.ranked if e.freight]
        return min(eligible, key=lambda e: e.freight_try) if eligible else None

    @property
    def overrode_cheapest_freight(self) -> bool:
        """Motor, en ucuz nakliyeyi reddetti mi. Demo'nun can alici sorusu."""
        cheapest = self.cheapest_freight
        return cheapest is not None and cheapest.carrier != self.selected.carrier

    @property
    def savings_vs_cheapest_freight_try(self) -> float:
        """En ucuz nakliyeyi secseydik ne kadar fazla odeyecektik (toplam maliyette).

        Negatif cikamaz: motor skoru minimize ettigi icin secilen her zaman en
        dusuk skorludur. Sifir ise motor zaten en ucuz nakliyeyi secmistir.
        """
        cheapest = self.cheapest_freight
        if cheapest is None or cheapest.carrier == self.selected.carrier:
            return 0.0
        return money(cheapest.expected_total_try - self.selected.expected_total_try)


def build_rationale(decision_parts: dict) -> list[str]:
    """Karar gerekcesini insan diliyle yazar.

    `decision_parts` sozlugu `selector` tarafindan hazirlanir; bu fonksiyon
    yalnizca metne cevirir, karar vermez.
    """
    selected: CarrierEvaluation = decision_parts["selected"]
    cheapest: CarrierEvaluation | None = decision_parts.get("cheapest_freight")
    rejected: list[CarrierEvaluation] = decision_parts.get("rejected", [])
    lines: list[str] = []

    components = selected.components
    assert components is not None
    lines.append(
        f"Secilen: {selected.display_name} — beklenen toplam maliyet "
        f"{components.expected_total_try:.2f} TL "
        f"({components.freight_try:.2f} TL nakliye + "
        f"{components.hidden_cost_try:.2f} TL faturada gorunmeyen)."
    )

    lines.append(
        f"Koli plani: {selected.parcel_count} koli "
        f"({'+'.join(selected.box_codes)}), {selected.chargeable_desi:g} ucretli desi."
    )

    # En ucuz nakliye neden reddedildi -- projenin varlik gerekcesi.
    if cheapest is not None and cheapest.carrier != selected.carrier:
        gap = cheapest.expected_total_try - selected.expected_total_try
        freight_diff = selected.freight_try - cheapest.freight_try
        reason_bits = []
        if cheapest.damage_probability > selected.damage_probability * 1.2:
            reason_bits.append(
                f"hasar olasiligi %{cheapest.damage_probability * 100:.2f} "
                f"(secilen: %{selected.damage_probability * 100:.2f})"
            )
        if (
            cheapest.delay
            and selected.delay
            and cheapest.delay.probability_late > selected.delay.probability_late * 1.2
        ):
            reason_bits.append(
                f"gecikme olasiligi %{cheapest.delay.probability_late * 100:.0f} "
                f"(secilen: %{selected.delay.probability_late * 100:.0f})"
            )
        detail = "; ".join(reason_bits) if reason_bits else "gizli maliyetleri daha yuksek"

        lines.append(
            f"En ucuz nakliye {cheapest.display_name} idi "
            f"({cheapest.freight_try:.2f} TL, {freight_diff:.2f} TL daha ucuz) "
            f"ama secilmedi: {detail}. "
            f"Toplamda {gap:.2f} TL daha pahaliya gelirdi."
        )

    if selected.contaminating_boxes == 0 and selected.plan_strategy == "sivilar_ayri":
        lines.append(
            "Sepette hem sivi hem emici urun var; sivilar ayri koliye alindi. "
            "Bir koli daha aciliyor ama sizinti kaynakli yan hasar riski ortadan kalkiyor."
        )
    elif selected.contaminating_boxes > 0:
        lines.append(
            f"{selected.contaminating_boxes} kolide sivi ve emici urun bir arada; "
            "ayirmanin ek nakliye maliyeti, azalttigi yan hasar riskinden yuksek cikti."
        )

    for evaluation in rejected:
        lines.append(
            f"{evaluation.display_name} elendi: {', '.join(evaluation.ineligibility_reasons)}."
        )

    return lines


def build_warnings(selected: CarrierEvaluation, eligible_count: int) -> list[str]:
    """Karara guveni etkileyen uyarilar."""
    warnings: list[str] = []

    if selected.is_low_confidence:
        warnings.append(
            f"{selected.display_name} icin bu bolge/urun kombinasyonunda gecmis veri zayif "
            f"(tahminin %{selected.damage_prior_weight * 100:.0f}'i onselden geliyor). "
            "Hasar tahmini genis bir belirsizlik tasiyor."
        )

    if selected.uses_synthetic_tariff:
        warnings.append(
            "ORNEK TARIFE: bu fiyat sentetik veriden geliyor, gercek sozlesme fiyati degil."
        )

    if eligible_count == 1:
        warnings.append("Bu siparis icin yalnizca tek firma uygun; karsilastirma yapilamadi.")

    return warnings
