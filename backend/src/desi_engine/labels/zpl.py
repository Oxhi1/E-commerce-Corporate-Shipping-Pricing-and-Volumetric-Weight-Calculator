"""Kargo etiketi uretimi -- ZPL II ve HTML onizleme.

Kullanicinin 4. maddesi: "Algoritma saniyeler icinde kararini verir ve depodaki
yazicidan dogrudan kazanan kargo firmasinin barkodu cikar. Paketleme personeli
dusunmez, sadece etiketi yapistirir."

Etiket, karar zincirinin son halkasi ve ayni zamanda **denetim kaydi**: uzerinde
yalnizca barkod degil, kararin ozeti de var (secilen firma, koli sirasi, desi).
Bir sikayet geldiginde "bu koli neden bu firmayla gitti" sorusunun cevabi
etiketten okunabiliyor.

ZPL, Zebra yazicilarin standart dilidir ve sektorde fiili standarttir. Cikti
gercek bir yaziciya gonderilebilir; bu projede dosyaya yaziliyor.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Final

from pydantic import BaseModel, ConfigDict

from ..decision.explain import Decision
from ..domain.models import Order
from .barcode import to_svg

#: 10x15 cm etiket, 203 dpi (8 nokta/mm) -- sektorde en yaygin kargo etiketi.
LABEL_WIDTH_DOTS: Final[int] = 812
LABEL_HEIGHT_DOTS: Final[int] = 1218

#: Firma basina takip numarasi on eki. Gercek firmalarin formatlari farklidir;
#: bunlar sentetik ve yalnizca bicimsel olarak gercekcidir.
TRACKING_PREFIX: Final[dict[str, str]] = {
    "ARAS": "ARS",
    "MNG": "MNG",
    "YURTICI": "YK",
    "SURAT": "SRT",
    "PTT": "PTT",
}


class ShippingLabel(BaseModel):
    """Tek bir koli icin etiket."""

    model_config = ConfigDict(frozen=True)

    order_id: str
    carrier: str
    carrier_display: str
    tracking_number: str
    parcel_index: int
    parcel_count: int

    recipient_city: str
    recipient_plate: int
    zone: str
    chargeable_desi: float
    gross_weight_kg: float
    box_code: str
    is_cod: bool
    cod_amount_try: float

    decision_note: str
    """Kararin tek satirlik ozeti -- etiketin denetim kaydi islevi."""

    is_synthetic_tariff: bool

    @property
    def barcode_svg(self) -> str:
        return to_svg(self.tracking_number)


def make_tracking_number(order_id: str, carrier: str, parcel_index: int) -> str:
    """Deterministik, bicimsel olarak gercekci takip numarasi.

    Deterministik olmasi onemli: ayni siparis iki kez islendiginde ayni numara
    cikar, boylece simulasyon tekrarlanabilir kalir ve testler sabitlenebilir.
    """
    digest = hashlib.sha256(f"{order_id}|{carrier}|{parcel_index}".encode()).hexdigest()
    serial = int(digest[:12], 16) % 10**11
    return f"{TRACKING_PREFIX.get(carrier, 'KRG')}{serial:011d}"


def build_labels(order: Order, decision: Decision) -> list[ShippingLabel]:
    """Karardan, koli basina bir etiket uretir."""
    selected = decision.selected
    if selected.freight is None:
        raise ValueError(f"{order.order_id}: secilen firmanin ucret teklifi yok")

    parcels = selected.freight.parcels
    cod_amount = order.cart.total_value_try if order.is_cod else 0.0
    note = f"{selected.display_name} secildi — beklenen toplam {selected.expected_total_try:.0f} TL"
    if decision.overrode_cheapest_freight:
        note += (
            f" (en ucuz nakliye reddedildi, "
            f"{decision.savings_vs_cheapest_freight_try:.0f} TL kazanc)"
        )

    return [
        ShippingLabel(
            order_id=order.order_id,
            carrier=selected.carrier,
            carrier_display=selected.display_name,
            tracking_number=make_tracking_number(order.order_id, selected.carrier, index),
            parcel_index=index + 1,
            parcel_count=len(parcels),
            recipient_city=order.address.city_name,
            recipient_plate=order.address.city_plate,
            zone=decision.zone.value,
            chargeable_desi=parcel.chargeable_desi,
            gross_weight_kg=0.0,
            box_code=selected.box_codes[index] if index < len(selected.box_codes) else "—",
            is_cod=order.is_cod,
            # Kapida odeme tutari yalnizca ilk koliye yazilir; her koliye yazmak
            # kuryenin tutari birden fazla kez tahsil etmesine yol acardi.
            cod_amount_try=cod_amount if index == 0 else 0.0,
            decision_note=note,
            is_synthetic_tariff=selected.uses_synthetic_tariff,
        )
        for index, parcel in enumerate(parcels)
    ]


def to_zpl(label: ShippingLabel) -> str:
    """Etiketi ZPL II koduna cevirir (10x15 cm, 203 dpi).

    `^BCN,120,Y,N,N` = Code 128, 120 nokta yukseklik, insan-okunur metin acik.
    Barkodu yazici kendi kodlar; onizlemedeki SVG ile ayni veriyi tasir.
    """
    cod_line = (
        f"^FO30,880^A0N,34,34^FDKAPIDA ODEME: {label.cod_amount_try:,.2f} TL^FS"
        if label.is_cod and label.cod_amount_try > 0
        else ""
    )
    synthetic_line = (
        "^FO30,1150^A0N,22,22^FD*** ORNEK TARIFE - GERCEK SOZLESME DEGIL ***^FS"
        if label.is_synthetic_tariff
        else ""
    )

    return f"""^XA
^PW{LABEL_WIDTH_DOTS}
^LL{LABEL_HEIGHT_DOTS}
^CI28
^FO30,30^A0N,56,56^FD{label.carrier_display}^FS
^FO30,95^GB750,3,3^FS

^FO30,125^A0N,30,30^FDSiparis: {label.order_id}^FS
^FO30,165^A0N,30,30^FDKoli {label.parcel_index}/{label.parcel_count}   Kutu: {label.box_code}^FS

^FO30,225^A0N,44,44^FDALICI^FS
^FO30,275^A0N,38,38^FD{label.recipient_plate:02d} {label.recipient_city}^FS
^FO30,320^A0N,28,28^FDBolge: {label.zone}^FS

^FO30,380^GB750,2,2^FS
^FO30,405^A0N,32,32^FDUcretli desi: {label.chargeable_desi:g}^FS

^FO60,470^BY3
^BCN,120,Y,N,N
^FD{label.tracking_number}^FS

{cod_line}
^FO30,960^GB750,2,2^FS
^FO30,985^A0N,24,24^FD{label.decision_note}^FS
^FO30,1020^A0N,22,22^FDOlusturma: {datetime.now():%d.%m.%Y %H:%M}^FS
{synthetic_line}
^XZ
"""


def to_html_preview(label: ShippingLabel) -> str:
    """Etiketin arayuzde gosterilecek HTML onizlemesi.

    ZPL bir yazici dilidir, tarayicida gorunmez. Bu onizleme ayni verileri ayni
    yerlesimle gosterir; personel etiketi basmadan once kontrol edebilir.
    """
    cod_block = (
        f'<div class="label-cod">KAPIDA ODEME: {label.cod_amount_try:,.2f} TL</div>'
        if label.is_cod and label.cod_amount_try > 0
        else ""
    )
    synthetic_block = (
        '<div class="label-synthetic">ORNEK TARIFE — gercek sozlesme degil</div>'
        if label.is_synthetic_tariff
        else ""
    )

    return f"""<div class="shipping-label">
  <div class="label-carrier">{label.carrier_display}</div>
  <div class="label-meta">
    <span>Siparis {label.order_id}</span>
    <span>Koli {label.parcel_index}/{label.parcel_count}</span>
    <span>Kutu {label.box_code}</span>
  </div>
  <div class="label-recipient">
    <div class="label-section-title">ALICI</div>
    <div class="label-city">{label.recipient_plate:02d} {label.recipient_city}</div>
    <div class="label-zone">Bolge: {label.zone} · Ucretli desi: {label.chargeable_desi:g}</div>
  </div>
  <div class="label-barcode">{label.barcode_svg}</div>
  {cod_block}
  <div class="label-note">{label.decision_note}</div>
  {synthetic_block}
</div>"""
