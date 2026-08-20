"""Ek ucret kalemleri ve uygulanma sirasi.

Sira neden onemli?
    Yakit farkinin hacim indiriminden once mi sonra mi uygulandigi, 1000 TL'lik bir
    faturada ~8 TL fark yaratir. Yilda 200 bin gonderide bu 1.6 milyon TL'dir.
    Gercek sozlesmelerde bu sira pazarlik konusudur; bu yuzden motorda gomulu bir
    formul degil, asagida acikca yazilmis ve degistirilebilir bir sira olarak durur.

Uygulanan sira (`SURCHARGE_ORDER`):
    1. taban tarife           -- desi kademesi x bolge
    2. asgari ucret tabani    -- max(taban, min_charge), **parca basina**
    3. hacim indirimi         -- indirimli taban
    4. yakit farki            -- indirimli taban uzerinden (indirimden SONRA)
    5. kapida odeme           -- sabit, gonderi basina bir kez
    6. sigorta                -- beyan degeri uzerinden, gonderi basina bir kez
    7. KDV                    -- yukaridakilerin toplami uzerinden

3. ve 4. adimin sirasi kritiktir: yakit farki indirimli tutar uzerinden
hesaplanir. Ters sira firmanin lehinedir ve sozlesmede acikca belirtilmediyse
lehte yorum yapmiyoruz.
"""

from __future__ import annotations

from typing import Final

from .schema import Surcharges

#: Boru hattinin okunabilir kaydi. Kod bu sirayi izler; degistirirken ikisini
#: birlikte guncelleyin (testler sirayi dogrular).
SURCHARGE_ORDER: Final[tuple[str, ...]] = (
    "base_tariff",
    "min_charge_floor",
    "volume_discount",
    "fuel_surcharge",
    "cod_fee",
    "insurance_fee",
    "vat",
)


def apply_min_charge(base_try: float, min_charge_try: float) -> tuple[float, bool]:
    """Asgari ucret tabanini uygular. `(ucret, taban_devreye_girdi_mi)` doner.

    Asgari ucret **parca basina** uygulanir -- iki parcaya bolunen bir gonderide
    iki kez devreye girer. Bu, PTT'nin 50 desi siniri gibi kisitlarin gercek
    maliyetini gorunur kilan ayrintidir.
    """
    if base_try < min_charge_try:
        return min_charge_try, True
    return base_try, False


def apply_volume_discount(base_try: float, discount_pct: float) -> float:
    """Sozlesme hacim indirimini taban ucrete uygular."""
    return base_try * (1.0 - discount_pct)


def fuel_surcharge(discounted_base_try: float, surcharges: Surcharges) -> float:
    """Yakit farki -- indirim uygulandiktan SONRAKI taban uzerinden."""
    return discounted_base_try * surcharges.fuel_pct


def cod_fee(surcharges: Surcharges, *, is_cod: bool) -> float:
    """Kapida odeme hizmet bedeli. Gonderi basina bir kez, parca sayisindan bagimsiz."""
    return surcharges.cod_fee if is_cod else 0.0


def insurance_fee(surcharges: Surcharges, declared_value_try: float) -> float:
    """Sigorta bedeli. Muafiyet limiti ustundeki tutarin yuzdesi."""
    return surcharges.insurance.fee_for(declared_value_try)


def vat(subtotal_try: float, surcharges: Surcharges) -> float:
    """KDV -- diger tum kalemlerin toplami uzerinden, en son."""
    return subtotal_try * surcharges.vat_pct
