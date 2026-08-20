"""Gecikme maliyeti `Z_k(L)` -- gec teslimatin parasal karsiligi.

Gec teslimat hicbir muhasebe kaleminde "nakliye gideri" olarak gorunmez, ama
para maliyeti gercektir ve genellikle nakliye farkindan buyuktur:

    * musteri arar                      -> cagri merkezi maliyeti
    * bir kismi siparisi reddeder       -> iade nakliyesi + stok geri alimi
    * bir kismi bir daha gelmez         -> musteri yasam boyu degeri kaybi
    * kalanlar memnuniyetsiz            -> kupon/indirim ile telafi

Model iki bilesenden olusur:

    Z = P(gecikme) * (cagri + p_iade * iade_maliyeti + p_churn * CLV)
      + E[(T - vaat)+] * gun_basi_telafi

Ilk terim gecikmenin **olup olmamasina** bagli sabit maliyetleri, ikincisi
gecikmenin **suresine** bagli maliyeti temsil eder. Bir gun geciken siparisle
bes gun geciken siparis ayni sey degildir.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from ..domain.enums import CarrierCode, ZoneClass
from ..domain.units import money
from .delivery_time import DeliveryTimeEstimator, FittedDelivery


@dataclass(frozen=True, slots=True)
class DelayCostParams:
    """Gecikme maliyeti kalemleri. Duyarlilik analizinin ana parametreleri."""

    call_center_cost_try: float = 35.0
    """Gec kalan her gonderi ortalama bir sikayet cagrisi uretir."""

    return_probability_if_late: float = 0.09
    """Gec teslimatta siparisin reddedilme / iade edilme olasiligi."""

    return_cost_try: float = 165.0
    """Iade nakliyesi + depoya kabul + stok duzeltme."""

    goodwill_per_day_try: float = 22.0
    """Gecikme basina gun basi telafi (kupon, indirim, itibar)."""

    churn_probability_if_late: float = 0.06
    """Gec teslimat yasayan musterinin kaybedilme olasiligi.
    Hasardaki (%18) orandan dusuk -- gec gelmek, kirik gelmekten daha affedilir."""

    max_charged_lateness_days: float = 10.0
    """Gun basi telafinin tavani. Sinirsiz birakilirsa log-normal kuyrugu
    tek bir uc ornekle butun kariri belirleyebilir."""


class DelayCost(BaseModel):
    """Bir gonderi icin beklenen gecikme maliyeti ve dokumu."""

    model_config = ConfigDict(frozen=True)

    promised_days: int
    expected_days: float
    p95_days: float
    probability_late: float
    expected_lateness_days: float

    call_center_try: float
    return_try: float
    churn_try: float
    goodwill_try: float
    total_try: float

    estimate_source: str
    observations: int

    def explain_lines(self) -> list[tuple[str, float]]:
        lines = [
            ("Cagri merkezi", self.call_center_try),
            ("Iade riski", self.return_try),
            ("Musteri kaybi", self.churn_try),
            ("Gecikme telafisi", self.goodwill_try),
        ]
        return [(label, amount) for label, amount in lines if amount > 0]


class DelayCostModel:
    """Teslimat dagilimi + maliyet parametreleri -> beklenen gecikme maliyeti."""

    def __init__(
        self, estimator: DeliveryTimeEstimator, params: DelayCostParams | None = None
    ) -> None:
        self.estimator = estimator
        self.params = params or DelayCostParams()

    def expected_cost(
        self,
        carrier: CarrierCode,
        zone: ZoneClass,
        carrier_sla_days: int,
        *,
        customer_promise_days: int | None = None,
        is_rural: bool = False,
        customer_clv_try: float = 0.0,
    ) -> DelayCost:
        """`Z_k(L)`: bir firmanin bu teslimat icin beklenen gecikme maliyeti.

        `carrier_sla_days` firmanin sozlesmedeki vaadidir ve teslimat suresi
        dagiliminin **olcek capasi**dir -- firmanin ne kadar surede teslim
        ettigini belirler.

        `customer_promise_days` musteriye soylenen gundur ve gecikmenin olculdugu
        **esik**tir. Varsayilan olarak firma SLA'sina esittir. Ikisini ayirmak,
        "musteriye bir gun fazla soylesek ne kazanirdik" sorusunu sorulabilir
        kilar: dagilim degismez, yalnizca esik kayar.
        """
        threshold = customer_promise_days if customer_promise_days is not None else carrier_sla_days
        fit: FittedDelivery = self.estimator.estimate(
            carrier, zone, carrier_sla_days, is_rural=is_rural
        )

        p_late = fit.probability_late(threshold)
        lateness = min(fit.expected_lateness_days(threshold), self.params.max_charged_lateness_days)

        call_center = p_late * self.params.call_center_cost_try
        returns = p_late * self.params.return_probability_if_late * self.params.return_cost_try
        churn = p_late * self.params.churn_probability_if_late * customer_clv_try
        goodwill = lateness * self.params.goodwill_per_day_try

        return DelayCost(
            promised_days=threshold,
            expected_days=fit.mean_days,
            p95_days=fit.percentile(0.95),
            probability_late=p_late,
            expected_lateness_days=lateness,
            call_center_try=money(call_center),
            return_try=money(returns),
            churn_try=money(churn),
            goodwill_try=money(goodwill),
            total_try=money(call_center + returns + churn + goodwill),
            estimate_source=fit.source,
            observations=fit.observations,
        )
