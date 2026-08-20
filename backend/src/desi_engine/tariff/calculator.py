"""Nakliye ucreti hesaplayicisi -- `F_k(D, z, sigma)`.

Cikti her zaman **kalem kalem dokumlu**. Karar motoru "MNG 142.30 TL" demez;
"142.30 = 98.50 taban + 9.36 yakit + 11.42 sigorta + 23.72 KDV" der. Bu, hem
demo'nun can damari hem de bir yoneticinin sisteme guvenmesinin tek yolu.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ..domain.enums import ZoneClass
from ..domain.units import money
from . import surcharges as sc
from .schema import Tariff


class ParcelCharge(BaseModel):
    """Tek bir kolinin ucret dokumu (KDV ve gonderi bazli ucretler haric)."""

    model_config = ConfigDict(frozen=True)

    chargeable_desi: float
    base_before_min: float
    min_charge_applied: bool
    base_after_min: float
    volume_discount_try: float
    discounted_base: float
    fuel_try: float

    @property
    def parcel_total(self) -> float:
        return self.discounted_base + self.fuel_try


class FreightQuote(BaseModel):
    """Bir firmanin bir gonderi icin tam nakliye teklifi."""

    model_config = ConfigDict(frozen=True)

    carrier: str
    display_name: str
    is_synthetic_tariff: bool = Field(
        description="True ise arayuz 'ORNEK TARIFE' rozeti gostermek zorundadir"
    )
    zone: ZoneClass
    parcels: list[ParcelCharge] = Field(min_length=1)

    volume_discount_pct: float
    cod_try: float
    insurance_try: float
    subtotal_before_vat: float
    vat_try: float
    total_try: float

    @property
    def parcel_count(self) -> int:
        return len(self.parcels)

    @property
    def total_chargeable_desi(self) -> float:
        return sum(p.chargeable_desi for p in self.parcels)

    def explain_lines(self) -> list[tuple[str, float]]:
        """Arayuzdeki dokum tablosu / waterfall grafigi icin (etiket, tutar) listesi."""
        base = sum(p.base_after_min for p in self.parcels)
        discount = -sum(p.volume_discount_try for p in self.parcels)
        fuel = sum(p.fuel_try for p in self.parcels)
        lines = [
            (f"Taban tarife ({self.parcel_count} koli, {self.total_chargeable_desi:g} desi)", base),
        ]
        if discount:
            lines.append((f"Hacim indirimi (%{self.volume_discount_pct * 100:g})", discount))
        lines.append(("Yakit farki", fuel))
        if self.cod_try:
            lines.append(("Kapida odeme", self.cod_try))
        if self.insurance_try:
            lines.append(("Sigorta", self.insurance_try))
        lines.append(("KDV", self.vat_try))
        return lines


class FreightCalculator:
    """`SURCHARGE_ORDER` sirasini uygulayan ucret hesaplayicisi.

    Durumsuzdur ve tarifeyi disaridan alir; ayni ornek tum firmalar icin kullanilir.
    """

    def __init__(self, monthly_parcel_volume: int = 0) -> None:
        """`monthly_parcel_volume`: hacim indirimi kademesini belirleyen aylik adet."""
        self.monthly_parcel_volume = monthly_parcel_volume

    def price_parcel(
        self,
        tariff: Tariff,
        chargeable_desi: float,
        zone: ZoneClass,
        discount_pct: float,
    ) -> ParcelCharge:
        """Tek koliyi fiyatlar: adim 1-4 (`SURCHARGE_ORDER`)."""
        base_before_min = tariff.base_price(chargeable_desi, zone)
        base_after_min, min_applied = sc.apply_min_charge(base_before_min, tariff.min_charge)
        discounted = sc.apply_volume_discount(base_after_min, discount_pct)
        fuel = sc.fuel_surcharge(discounted, tariff.surcharges)

        return ParcelCharge(
            chargeable_desi=chargeable_desi,
            base_before_min=money(base_before_min),
            min_charge_applied=min_applied,
            base_after_min=money(base_after_min),
            volume_discount_try=money(base_after_min - discounted),
            discounted_base=money(discounted),
            fuel_try=money(fuel),
        )

    def quote(
        self,
        tariff: Tariff,
        parcel_desis: list[float],
        zone: ZoneClass,
        declared_value_try: float,
        *,
        is_cod: bool = False,
    ) -> FreightQuote:
        """Cok kolili bir gonderinin tam teklifini uretir.

        Koli basina ucretler (taban, asgari ucret, indirim, yakit) her koli icin
        ayri hesaplanir; gonderi basina ucretler (kapida odeme, sigorta) bir kez
        eklenir; KDV en sona uygulanir.
        """
        if not parcel_desis:
            raise ValueError("En az bir koli gerekli")

        discount_pct = tariff.volume_discount_pct(self.monthly_parcel_volume)
        parcels = [self.price_parcel(tariff, desi, zone, discount_pct) for desi in parcel_desis]

        freight = sum(p.parcel_total for p in parcels)
        cod = sc.cod_fee(tariff.surcharges, is_cod=is_cod)
        insurance = sc.insurance_fee(tariff.surcharges, declared_value_try)

        subtotal = freight + cod + insurance
        vat_try = sc.vat(subtotal, tariff.surcharges)

        return FreightQuote(
            carrier=tariff.carrier.value,
            display_name=tariff.display_name,
            is_synthetic_tariff=tariff.is_synthetic,
            zone=zone,
            parcels=parcels,
            volume_discount_pct=discount_pct,
            cod_try=money(cod),
            insurance_try=money(insurance),
            subtotal_before_vat=money(subtotal),
            vat_try=money(vat_try),
            total_try=money(subtotal + vat_try),
        )
