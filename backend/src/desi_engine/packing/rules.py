"""Paketleme kurallari: fiziksel ve operasyonel kisitlar.

Bu kurallar algoritmayi kasitli olarak kotulestirir -- kuralsiz bir paketleyici
her zaman daha az desi uretir. Ama kuralsiz paketlemenin urettigi koli gercek
dunyada patlar, sizar veya ezilir; tasarruf hasar maliyetiyle fazlasiyla geri
alinir. Buradaki her kural bir hasar modunu karsilar.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..domain.enums import Fragility
from ..domain.models import Product
from .boxes import Box
from .geometry import Cuboid, strictly_below, support_ratio, supporters


class Violation(StrEnum):
    """Bir yerlestirmenin neden reddedildigi. Hata ayiklama ve aciklama icin."""

    OUT_OF_BOUNDS = "kutu_disina_tasti"
    OVERLAP = "baska_urunle_cakisiyor"
    UNSUPPORTED = "yeterince_desteklenmiyor"
    STACK_LOAD = "alttaki_urunun_tasima_limiti_asildi"
    ON_NON_STACKABLE = "ustune_urun_konamayan_urunun_uzerinde"
    LIQUID_ABOVE_ABSORBENT = "sivi_urun_emici_urunun_uzerinde"
    PAYLOAD_LIMIT = "koli_tasima_limiti_asildi"
    BOX_REJECTS_ITEM = "koli_tipi_bu_urunu_kabul_etmiyor"


@dataclass(frozen=True, slots=True)
class PackingRules:
    """Kural seti. Duyarlilik analizinde gevsetilip sikistirilabilsin diye veri."""

    min_support_ratio: float = 0.70
    """Bir urunun tabaninin en az bu orani desteklenmeli. 1.0 fiziksel olarak en
    guvenli ama pratikte gereksiz kati; 0.70 sektorde yaygin bir esik."""

    forbid_liquid_above_absorbent: bool = True
    """Sivi urun, emici bir urunun uzerine konmaz. Kullanicinin zeytinyagi/nevresim
    senaryosunun paketleme tarafindaki karsiligi: sizinti asagi akar."""

    enforce_stack_load: bool = True
    """Alttaki urunlerin tasima kapasitesi kontrol edilsin mi."""

    max_items_per_box: int = 40
    """Operasyonel sinir: paketleme personelinin tek koliye koyabilecegi urun sayisi."""


def box_accepts(box: Box, product: Product) -> bool:
    """Bu koli tipi bu urunu alabilir mi.

    Kargo posetleri (`soft_only`) yalnizca yumusak tekstil icindir; kirilabilir
    veya sivi bir urun poset icinde tasinmaz.
    """
    if not box.soft_only:
        return True
    return product.fragility is Fragility.NONE and not product.is_liquid


def propagate_load(
    candidate: Cuboid,
    weight_kg: float,
    placed: list[Cuboid],
    placed_products: list[Product],
    carried_kg: list[float],
) -> list[float] | None:
    """Yeni urunun agirligini altindaki yigina dagitir.

    Fizik: A, B'nin uzerinde ve B de C'nin uzerindeyse, C hem A'yi hem B'yi tasir.
    Bu yuzden agirlik yalnizca dogrudan alttakine degil, yigin boyunca **asagi
    dogru yayilir**. Birden fazla destekleyici varsa yuk temas alaniyla orantili
    paylastirilir.

    Bu, gercek yuk dagilimin (rijitlik, agirlik merkezi) belgelenmis bir
    yaklasimidir; kolinin icini modellemek icin fazlasiyla yeterli.

    Yeni `carried_kg` listesini doner; herhangi bir limit asilirsa `None`.
    """
    updated = list(carried_kg)

    direct = supporters(candidate, placed)
    if not direct:
        return updated  # zeminde duruyor, hicbir urune yuk binmiyor

    total_contact = sum(area for _, area in direct)
    stack: list[tuple[int, float]] = [
        (index, weight_kg * area / total_contact) for index, area in direct
    ]

    while stack:
        index, amount = stack.pop()
        updated[index] += amount
        if updated[index] > placed_products[index].max_stack_load_kg + 1e-9:
            return None

        lower = supporters(placed[index], placed)
        if not lower:
            continue  # yuk zemine iniyor
        total_contact = sum(area for _, area in lower)
        stack.extend((idx, amount * area / total_contact) for idx, area in lower)

    return updated


def check_placement(
    candidate: Cuboid,
    product: Product,
    placed: list[Cuboid],
    placed_products: list[Product],
    carried_kg: list[float],
    rules: PackingRules,
) -> tuple[Violation | None, list[float]]:
    """Bir yerlestirmeyi tum kurallara karsi dogrular.

    `(ihlal_veya_None, guncellenmis_yuk_listesi)` doner. Ihlal varsa yuk listesi
    degistirilmemis haliyle geri gelir.
    """
    # 1. Destek: havada asili urun olmaz.
    if support_ratio(candidate, placed) + 1e-9 < rules.min_support_ratio:
        return Violation.UNSUPPORTED, carried_kg

    # 2. Ustune urun konamayan bir urunun uzerine konulamaz.
    for index, _area in supporters(candidate, placed):
        if not placed_products[index].stackable:
            return Violation.ON_NON_STACKABLE, carried_kg

    # 3. Sivi, emici urunun uzerinde olamaz -- sizinti asagi akar.
    if rules.forbid_liquid_above_absorbent and product.is_liquid:
        for index, other in enumerate(placed):
            if placed_products[index].is_absorbent and strictly_below(candidate, other):
                return Violation.LIQUID_ABOVE_ABSORBENT, carried_kg

    # 4. Istif yuku: alttaki urunlerin tasima kapasitesi.
    if rules.enforce_stack_load:
        updated = propagate_load(candidate, product.weight_kg, placed, placed_products, carried_kg)
        if updated is None:
            return Violation.STACK_LOAD, carried_kg
        return None, updated

    return None, carried_kg


def contamination_pairs(placements_products: list[Product], placed: list[Cuboid]) -> int:
    """Ayni kolide bulunan (sivi, emici) urun cifti sayisi.

    Kural sivinin *ustte* olmasini engelliyor ama ayni kutuda olmalarini
    engellemiyor -- bu bir maliyet karari, paketleme karari degil. Hasar modeli
    bu sayiyi yan hasar carpani olarak kullanir.
    """
    liquids = [i for i, p in enumerate(placements_products) if p.is_liquid]
    absorbents = [i for i, p in enumerate(placements_products) if p.is_absorbent]
    if not liquids or not absorbents:
        return 0
    return len(liquids) * len(absorbents)
