"""Amac fonksiyonu -- beklenen toplam sahiplenme maliyeti (TELC).

Kullanicinin onerdigi cekirdek:

    Secilen = argmin_k [ F_k(D) + R_k*S + Z_k(L) ]

Uygulanan hali, ayni fikrin olculebilir genislemesi:

    TELC_k = F_k(D, z, sigma)     nakliye (tarife + ek ucretler)
           + E[hasar maliyeti]    p_hat * Zarar(koli), yan hasar dahil
           + Z_k(L)               beklenen gecikme maliyeti
           + O_k                  ambalaj + operasyonel surtunme

    Skor_k = TELC_k + lambda * (CVaR_95(hasar) - E[hasar])

Kuyruk riski terimi hakkinda
    Beklenen deger, "nadiren cok kotu" ile "sik sik biraz kotu"yu ayni sayiya
    indirger. 3870 TL'lik bir sepette %5 hasar olasiligi ile %0.5 olasilikta
    on kat zarar ayni beklenen maliyeti verir, ama isletme icin ayni sey degildir.
    `lambda > 0` verildiginde motor kuyrugu da fiyatlar.

    Hasar maliyeti iki noktali bir dagilim oldugu icin CVaR kapali formda cikar:

        CVaR_alpha = min(1, p / alpha) * Zarar

    `p >= alpha` ise en kotu %alpha dilimin tamami hasar olaylarindan olusur;
    `p < alpha` ise dilimin bir kismini saglam gonderiler doldurur. Kapali form
    onemli: Monte Carlo'da her siparis x her firma x her plan icin cagriliyor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from ..domain.units import money

#: CVaR guven seviyesi. %95 = "en kotu 20 gonderiden biri".
CVAR_ALPHA: Final[float] = 0.05


@dataclass(frozen=True, slots=True)
class ObjectiveParams:
    """Amac fonksiyonunun agirliklari."""

    risk_aversion_lambda: float = 0.0
    """0 = risk-notr (saf beklenen deger). Buyudukce kuyruk riskinden kacinilir.
    Duyarlilik analizinde oynatilan en onemli parametrelerden biri."""

    include_packaging_cost: bool = True
    """Ambalaj malzemesi maliyeti hesaba katilsin mi. Firmadan bagimsiz gorunur
    ama degildir: parca siniri dusuk bir firma daha fazla koli zorlar."""

    operational_cost_try: dict[str, float] = None  # type: ignore[assignment]
    """Firma basina operasyonel surtunme (`O_k`): zayif API entegrasyonu, elle
    veri girisi, sube teslim zorunlulugu gibi kalemler. Varsayilan: hepsi sifir."""

    def friction_for(self, carrier: str) -> float:
        if not self.operational_cost_try:
            return 0.0
        return self.operational_cost_try.get(carrier, 0.0)


class CostComponents(BaseModel):
    """TELC'in kalemleri. Arayuzdeki waterfall grafiginin veri kaynagi."""

    model_config = ConfigDict(frozen=True)

    freight_try: float = Field(description="F_k -- tarife + ek ucretler + KDV")
    damage_try: float = Field(description="Beklenen hasar maliyeti (yan hasar dahil)")
    delay_try: float = Field(description="Z_k -- beklenen gecikme maliyeti")
    packaging_try: float = Field(description="Ambalaj malzemesi")
    friction_try: float = Field(default=0.0, description="O_k -- operasyonel surtunme")
    tail_premium_try: float = Field(
        default=0.0, description="lambda * (CVaR - beklenen): kuyruk riski primi"
    )

    @property
    def expected_total_try(self) -> float:
        """Kuyruk primi haric beklenen toplam maliyet -- gercek para beklentisi."""
        return money(
            self.freight_try
            + self.damage_try
            + self.delay_try
            + self.packaging_try
            + self.friction_try
        )

    @property
    def score_try(self) -> float:
        """Siralamada kullanilan skor. `lambda = 0` iken beklenen toplama esittir."""
        return money(self.expected_total_try + self.tail_premium_try)

    @property
    def hidden_cost_try(self) -> float:
        """Nakliye disi maliyetler.

        Mevcut sistemin gormedigi kisim tam olarak bu; sunumda "faturada olmayan
        ama odenen" kalem olarak gosterilir.
        """
        return money(self.damage_try + self.delay_try + self.packaging_try + self.friction_try)

    def explain_lines(self) -> list[tuple[str, float]]:
        lines = [
            ("Nakliye", self.freight_try),
            ("Beklenen hasar", self.damage_try),
            ("Beklenen gecikme", self.delay_try),
            ("Ambalaj", self.packaging_try),
            ("Operasyonel surtunme", self.friction_try),
            ("Kuyruk riski primi", self.tail_premium_try),
        ]
        return [(label, amount) for label, amount in lines if abs(amount) > 1e-9]


def conditional_value_at_risk(
    probability: float, loss_try: float, alpha: float = CVAR_ALPHA
) -> float:
    """Iki noktali hasar dagiliminin CVaR'i: `min(1, p/alpha) * Zarar`.

    Turetim: gonderi `p` olasilikla `Zarar` kadar, `1-p` olasilikla 0 maliyet
    uretir. En kotu `alpha` dilimin beklenen degeri:

        p >= alpha  ->  dilim tamamen hasar olaylarindan olusur  ->  Zarar
        p <  alpha  ->  [p*Zarar + (alpha-p)*0] / alpha           ->  (p/alpha)*Zarar
    """
    if alpha <= 0:
        raise ValueError("alpha pozitif olmali")
    return min(1.0, probability / alpha) * loss_try


def tail_premium(
    probability: float, loss_try: float, lambda_: float, alpha: float = CVAR_ALPHA
) -> float:
    """Kuyruk riski primi: `lambda * (CVaR - beklenen deger)`.

    Beklenen degerin uzerine eklenen *ek* ceza. `lambda = 0` iken sifirdir,
    dolayisiyla risk-notr mod ozel bir kod yolu gerektirmez.
    """
    if lambda_ <= 0:
        return 0.0
    excess = conditional_value_at_risk(probability, loss_try, alpha) - probability * loss_try
    return money(lambda_ * max(0.0, excess))
