"""Hasar maliyeti -- `R_k * S` teriminin gercekci hali.

Kullanicinin onerdigi model hasar maliyetini `R_k * S` olarak yaziyordu: hasar
olasiligi carpi sepet tutari. Dogru iskelet, ama iki noktada eksik:

1. **Hasar, sepetin tamamini goturmez.** Ezilen bir havlu %100 zarar degildir;
   outlet'te satilabilir. Kirilan bir porselen takim %100'dur. Zarar, urun
   tipine gore degisen bir *siddet* katsayisiyla olculmeli.

2. **Hasar, sepetten fazlasini goturur.** Patlayan bir sise zeytinyagi yalnizca
   kendi degerini degil, yanindaki nevresimi de goturur; ustune yeniden
   gonderim, elleçleme, cagri merkezi ve -- en pahalisi -- musteri kaybi biner.
   Kullanicinin "4 TL'lik kargo tasarrufu" ornegi tam olarak bu kalemi isaret
   ediyordu.

Bu yuzden model:

    Zarar(koli) = SUM_i deger_i * siddet_i                   dogrudan
                + kontaminasyon * SUM_j emici_deger_j        yan hasar
                + yeniden_gonderim + elleçleme + cagri       lojistik
                + churn_olasiligi * CLV                      musteri kaybi

    Beklenen maliyet = P(hasar) * Zarar(koli)

`R_k * S`, `siddet = 1`, yan hasar ve lojistik kalemleri sifir alindiginda bu
modelin ozel halidir.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict

from ..domain.enums import CarrierCode, RiskCategory, ZoneClass
from ..domain.units import money
from ..packing.boxes import PackedBox
from .hierarchy import DamageRateEstimator

#: Hasar olayi gerceklestiginde urunun degerinin ne kadarinin kaybedildigi.
#: Tekstil kismen kurtarilabilir (outlet, temizleme); cam ve porselen kurtarilamaz.
DEFAULT_SEVERITY: dict[RiskCategory, float] = {
    RiskCategory.SOFT: 0.35,
    RiskCategory.APPLIANCE: 0.80,
    RiskCategory.LIQUID: 0.85,
    RiskCategory.FRAGILE: 0.95,
}


@dataclass(frozen=True, slots=True)
class DamageCostParams:
    """Hasar maliyeti kalemleri. Duyarlilik analizinde oynatilan parametreler."""

    severity: dict[RiskCategory, float] = field(default_factory=lambda: dict(DEFAULT_SEVERITY))

    contamination_spread: float = 0.85
    """Kolideki sivi zarar gordugunde sizintinin emici urunlere ulasma olasiligi.
    Yuksek cunku bir koli kapali bir hacimdir; sizan sivinin gidecek baska yeri yok."""

    reship_freight_try: float = 120.0
    """Yerine yenisini gondermenin nakliye maliyeti (iade + yeni sevkiyat)."""

    handling_cost_try: float = 45.0
    """Depo elleçleme, yeniden paketleme, stok duzeltme."""

    call_center_cost_try: float = 35.0
    """Sikayet cagrisi + takip. Hasarli her gonderi en az bir cagri uretir."""

    churn_probability: float = 0.18
    """Hasar yasayan musterinin bir daha alisveris yapmama olasiligi."""

    risk_aversion_level: float | None = None
    """`None` ise posterior ortalama kullanilir (risk-notr). 0.95 gibi bir deger
    verilirse posterior ust guven siniri kullanilir: az veriye sahip firmalar
    otomatik olarak riskli sayilir ve "bilmiyoruz" durumu firmanin lehine islemez."""


class DamageLoss(BaseModel):
    """Bir hasar olayi gerceklestiginde olusacak zararin dokumu."""

    model_config = ConfigDict(frozen=True)

    direct_goods_try: float
    contamination_try: float
    reship_try: float
    handling_try: float
    call_center_try: float
    churn_try: float
    total_try: float

    def explain_lines(self) -> list[tuple[str, float]]:
        lines = [
            ("Hasarli urun degeri", self.direct_goods_try),
            ("Yan hasar (sizinti)", self.contamination_try),
            ("Yeniden gonderim", self.reship_try),
            ("Elleçleme", self.handling_try),
            ("Cagri merkezi", self.call_center_try),
            ("Musteri kaybi (CLV)", self.churn_try),
        ]
        return [(label, amount) for label, amount in lines if amount > 0]


class ExpectedDamageCost(BaseModel):
    """Bir koli icin beklenen hasar maliyeti ve arkasindaki belirsizlik."""

    model_config = ConfigDict(frozen=True)

    probability: float
    probability_raw: float
    probability_upper_95: float
    prior_weight: float
    dominant_category: RiskCategory
    loss: DamageLoss
    expected_try: float

    @property
    def is_low_confidence(self) -> bool:
        """Tahminin yarisindan fazlasi onselden geliyorsa bu hucreyi az taniyoruz.

        Arayuz bu bayragi gorununce uyari isareti gosterir; karar hala verilir ama
        gerekcesinde "veri zayif" notu yer alir.
        """
        return self.prior_weight > 0.5


class DamageCostModel:
    """Hasar olasiligini zarar fonksiyonuyla birlestirip beklenen maliyeti verir."""

    def __init__(
        self, estimator: DamageRateEstimator, params: DamageCostParams | None = None
    ) -> None:
        self.estimator = estimator
        self.params = params or DamageCostParams()

    # ---- olasilik -----------------------------------------------------------

    @staticmethod
    def dominant_category(box: PackedBox) -> RiskCategory:
        """Kolinin risk sinifi: icindeki **en kirilgan** urunun sinifi.

        "Bir kolinin kirilganligi, icindeki en kirilgan urun kadardir." Icinde cam
        olan bir koli, yaninda havlu olsa bile cam kolisi gibi tasinir ve oyle
        hasar gorur. Ortalama almak bu gercegi gizlerdi.
        """
        order = [
            RiskCategory.SOFT,
            RiskCategory.APPLIANCE,
            RiskCategory.LIQUID,
            RiskCategory.FRAGILE,
        ]
        present = {p.risk_category for p in box.placements}
        return max(present, key=order.index)

    # ---- zarar --------------------------------------------------------------

    def loss_given_damage(self, box: PackedBox, customer_clv_try: float) -> DamageLoss:
        """Hasar olayi gerceklestiginde olusacak toplam zarar."""
        severity = self.params.severity

        direct = sum(p.value_try * severity[p.risk_category] for p in box.placements)

        # Yan hasar: yalnizca kolide hem sivi hem emici urun varsa.
        # Emici urunun `direct` icinde zaten sayilan kismi cikarilir -- ayni zarari
        # iki kez yazmamak icin.
        contamination = 0.0
        has_liquid = any(p.is_liquid for p in box.placements)
        if has_liquid:
            contamination = self.params.contamination_spread * sum(
                p.value_try * (1.0 - severity[p.risk_category])
                for p in box.placements
                if p.is_absorbent
            )

        churn = self.params.churn_probability * customer_clv_try
        total = (
            direct
            + contamination
            + self.params.reship_freight_try
            + self.params.handling_cost_try
            + self.params.call_center_cost_try
            + churn
        )

        return DamageLoss(
            direct_goods_try=money(direct),
            contamination_try=money(contamination),
            reship_try=money(self.params.reship_freight_try),
            handling_try=money(self.params.handling_cost_try),
            call_center_try=money(self.params.call_center_cost_try),
            churn_try=money(churn),
            total_try=money(total),
        )

    # ---- beklenen maliyet ---------------------------------------------------

    def expected_cost(
        self,
        box: PackedBox,
        carrier: CarrierCode,
        zone: ZoneClass,
        customer_clv_try: float = 0.0,
    ) -> ExpectedDamageCost:
        """Bir koli icin beklenen hasar maliyeti."""
        category = self.dominant_category(box)
        post = self.estimator.estimate(carrier, zone, category)

        level = self.params.risk_aversion_level
        probability = post.mean if level is None else post.upper_bound(level)

        loss = self.loss_given_damage(box, customer_clv_try)

        return ExpectedDamageCost(
            probability=probability,
            probability_raw=post.raw_rate,
            probability_upper_95=post.upper_bound(0.95),
            prior_weight=post.shrinkage_weight,
            dominant_category=category,
            loss=loss,
            expected_try=money(probability * loss.total_try),
        )

    def shipment_expected_cost(
        self,
        boxes: list[PackedBox],
        carrier: CarrierCode,
        zone: ZoneClass,
        customer_clv_try: float = 0.0,
    ) -> tuple[float, list[ExpectedDamageCost]]:
        """Cok kolili bir gonderinin toplam beklenen hasar maliyeti.

        Musteri kaybi kalemi **yalnizca bir kez** sayilir: musteri, iki kolisi
        birden hasar gorse de bir kez kaybedilir. Koli basina churn eklemek
        cok parcali gonderileri haksiz yere cezalandirirdi.
        """
        per_box = [self.expected_cost(box, carrier, zone, 0.0) for box in boxes]
        goods_and_logistics = sum(item.expected_try for item in per_box)

        # Gonderi duzeyinde en az bir hasar olma olasiligi.
        p_any_damage = 1.0 - _product(1.0 - item.probability for item in per_box)
        churn_cost = p_any_damage * self.params.churn_probability * customer_clv_try

        return money(goods_and_logistics + churn_cost), per_box


def _product(values) -> float:
    result = 1.0
    for value in values:
        result *= value
    return result
