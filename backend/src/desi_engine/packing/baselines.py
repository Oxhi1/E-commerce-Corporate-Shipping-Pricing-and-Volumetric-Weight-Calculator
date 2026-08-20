"""Karsilastirma baz cizgileri -- "ne kadar kazandik" sorusunun paydasi.

Bu modul projenin durustluk sigortasi. Ilk tasarimda tasarruf, "sepetteki
urunlerin desilerinin toplami"na kiyasla olculuyordu. O sayi **fiziksel olarak
ulasilamaz**: hicbir gonderi kolisiz gitmez ve her koli icindekinden buyuktur.
Ona kiyasla olculen bir "tasarruf" her zaman negatif cikar ve hicbir sey anlatmaz.

Uc farkli baz cizgi ayri ayri raporlanir:

`quoted_sum_desi`
    Mevcut sistemin *kotasyon* rakami: urun desilerinin duz toplami. Fiziksel
    degil, ama sirketin bugun musteriye ve butceye soyledigi sayi bu. Gercek
    fatura bunun uzerinde cikarsa aradaki farki sirket cebinden odemektedir --
    bu bir tasarruf firsati degil, gizli bir zarar kalemidir ve oyle raporlanir.

`one_box_per_item_desi`
    Konsolidasyon mantigi olmayan bir depo ne yapar: her urun kendi en kucuk
    kolisinde. Gercek, ulasilabilir ve yaygin bir operasyon bicimi. Motorun
    tasarruf iddiasinin **asil paydasi** budur.

`volume_rule_desi`
    Excel mantigi: "urunlerin hacmini topla, o hacme sigan en kucuk kutuyu sec".
    Geometriyi hesaba katmadigi icin sectigi kutu cogu zaman gercekte yetmez;
    o durumda operasyon bir ust kutuya gecer. Bu baz cizgi o davranisi taklit eder.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ..domain.models import Product
from .boxes import Box, BoxCatalog, PackedBox
from .extreme_point import fill_box
from .rules import PackingRules


class BaselineDesis(BaseModel):
    """Bir sepet icin hesaplanmis tum baz cizgiler (ucretli desi vekili cinsinden)."""

    model_config = ConfigDict(frozen=True)

    quoted_sum_desi: float
    one_box_per_item_desi: float
    one_box_per_item_parcels: int
    volume_rule_desi: float
    volume_rule_parcels: int


def one_box_per_item(
    units: list[Product], catalog: BoxCatalog, rules: PackingRules | None = None
) -> list[PackedBox]:
    """Her urunu kendi en kucuk kolisine koyar -- konsolidasyonsuz depo davranisi."""
    rules = rules or PackingRules()
    packed_boxes: list[PackedBox] = []

    for unit in units:
        allow_bags = not unit.is_liquid and unit.fragility.value == "yok"
        for box in catalog.usable(allow_soft_only=allow_bags):
            packed, leftover = fill_box(box, [unit], rules)
            if packed is not None and not leftover:
                packed_boxes.append(packed)
                break
        else:
            # Katalogdaki hicbir kutuya sigmiyor: baz cizgi icin en buyugu kullan.
            # (Motorun kendisi bu durumda ozel olcu kolisi uretir; baz cizginin
            # o kadar akilli olmasi beklenmez.)
            packed, _ = fill_box(catalog.largest, [unit], rules)
            if packed is not None:
                packed_boxes.append(packed)

    return packed_boxes


def volume_rule_box(units: list[Product], catalog: BoxCatalog) -> Box:
    """Hacim toplamina gore kutu secer -- geometriyi yok sayan Excel kurali."""
    needed = sum(u.effective_dims.volume_cm3 for u in units)
    for box in catalog.usable(allow_soft_only=False):
        if box.inner_volume_cm3 >= needed:
            return box
    return catalog.largest


def compute_baselines(
    units: list[Product],
    quoted_sum_desi: float,
    catalog: BoxCatalog,
    rules: PackingRules | None = None,
) -> BaselineDesis:
    """Tum baz cizgileri tek seferde hesaplar."""
    rules = rules or PackingRules()

    per_item = one_box_per_item(units, catalog, rules)
    per_item_desi = sum(b.billable_proxy_desi for b in per_item)

    # Hacim kurali: sectigi kutuyu dene; gercekte yetmezse bir ust kutuya gec.
    chosen = volume_rule_box(units, catalog)
    usable = catalog.usable(allow_soft_only=False)
    start = usable.index(chosen) if chosen in usable else 0

    volume_boxes: list[PackedBox] = []
    for box in usable[start:]:
        packed, leftover = fill_box(box, units, rules)
        if packed is not None and not leftover:
            volume_boxes = [packed]
            break
    if not volume_boxes:
        # En buyuk kutuya bile sigmadi: her urun ayri koli davranisina duser.
        volume_boxes = per_item

    return BaselineDesis(
        quoted_sum_desi=quoted_sum_desi,
        one_box_per_item_desi=per_item_desi,
        one_box_per_item_parcels=len(per_item),
        volume_rule_desi=sum(b.billable_proxy_desi for b in volume_boxes),
        volume_rule_parcels=len(volume_boxes),
    )
