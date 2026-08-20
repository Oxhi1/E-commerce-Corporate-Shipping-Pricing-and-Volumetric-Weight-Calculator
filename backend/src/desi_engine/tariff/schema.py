"""Kargo tarife dosyasinin sematik karsiligi (`data/carriers/*.yaml`).

Sema yalnizca ayristirmaz, ayni zamanda **dogrular**. En degerli dogrulama fiyat
monotonlugu: bir tarifede ust desi kademesinin fiyati alt kademeden ucuz olamaz.
Elle duzenlenmis bir tarife dosyasinda tek bir yanlis rakam, karar motorunun
sistematik olarak yanlis firma secmesine yol acar ve bunu fark etmek neredeyse
imkansizdir -- yukleme aninda patlamasi cok daha iyidir.
"""

from __future__ import annotations

from datetime import date
from itertools import pairwise
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..domain.enums import CarrierCode, RoundingRule, TariffSourceKind, ZoneClass

Pct = Annotated[float, Field(ge=0, le=1)]
NonNegTry = Annotated[float, Field(ge=0)]

ALL_ZONES: frozenset[ZoneClass] = frozenset(ZoneClass)


class InsuranceRule(BaseModel):
    """Sigorta ucreti: muafiyet limiti ustundeki tutarin yuzdesi."""

    model_config = ConfigDict(frozen=True)

    free_limit: NonNegTry = Field(description="Bu tutara kadar sigorta ucretsiz")
    pct_above: Pct = Field(description="Limitin ustundeki kisma uygulanan oran")

    def fee_for(self, declared_value_try: float) -> float:
        return max(0.0, declared_value_try - self.free_limit) * self.pct_above


class Surcharges(BaseModel):
    """Taban tarifenin uzerine binen ek ucretler."""

    model_config = ConfigDict(frozen=True)

    fuel_pct: Pct = Field(description="Yakit farki -- taban ucret uzerinden")
    cod_fee: NonNegTry = Field(description="Kapida odeme hizmet bedeli")
    insurance: InsuranceRule
    vat_pct: Pct = Field(default=0.20, description="KDV")


class DesiTier(BaseModel):
    """Tek bir desi kademesi ve bolgelere gore fiyatlari."""

    model_config = ConfigDict(frozen=True)

    up_to: Annotated[float, Field(gt=0)] = Field(
        description="Bu desiye kadar (dahil) gecerli fiyat"
    )
    zones: dict[ZoneClass, NonNegTry]

    @model_validator(mode="after")
    def _all_zones_present(self) -> Self:
        missing = ALL_ZONES - self.zones.keys()
        if missing:
            raise ValueError(
                f"{self.up_to} desi kademesinde eksik bolge: {sorted(z.value for z in missing)}"
            )
        return self


class VolumeDiscount(BaseModel):
    """Aylik gonderi adedine bagli sozlesme indirimi."""

    model_config = ConfigDict(frozen=True)

    monthly_parcels_gte: Annotated[int, Field(ge=0)]
    pct: Pct


class ServiceLevel(BaseModel):
    """Firmanin sozlesmede vaat ettigi teslimat suresi.

    Bunlar **vaatler**, gerceklesme degil. Gercek teslimat suresi dagilimi
    simulasyon dunyasinda tutulur ve motor onu bilmez -- gecmis veriden tahmin eder.
    """

    model_config = ConfigDict(frozen=True)

    sla_days: dict[ZoneClass, Annotated[int, Field(ge=1, le=30)]]
    rural_extra_days: Annotated[int, Field(ge=0, le=10)] = 1
    cutoff: str = Field(pattern=r"^\d{2}:\d{2}$", description="Ayni gun cikis icin son saat")

    @model_validator(mode="after")
    def _all_zones_present(self) -> Self:
        missing = ALL_ZONES - self.sla_days.keys()
        if missing:
            raise ValueError(f"SLA'da eksik bolge: {sorted(z.value for z in missing)}")
        return self

    def promised_days(self, zone: ZoneClass, *, is_rural: bool = False) -> int:
        return self.sla_days[zone] + (self.rural_extra_days if is_rural else 0)


class CarrierConstraints(BaseModel):
    """Firmanin uygunluk kisitlari. `K_uygun` kumesini bunlar belirler."""

    model_config = ConfigDict(frozen=True)

    max_desi_per_parcel: Annotated[float, Field(gt=0)]
    cod_supported: bool = True
    unserved_plates: list[int] = Field(
        default_factory=list, description="Hizmet verilmeyen il plaka kodlari"
    )


class Tariff(BaseModel):
    """Bir kargo firmasinin tam sozlesme tarifesi."""

    model_config = ConfigDict(frozen=True)

    carrier: CarrierCode
    display_name: str
    source: TariffSourceKind
    note: str = ""
    valid_from: date
    currency: str = "TRY"

    rounding: RoundingRule
    desi_step: Annotated[float, Field(gt=0)] = 1.0
    min_charge: NonNegTry

    desi_tiers: list[DesiTier] = Field(min_length=1)
    over_30_per_desi: dict[ZoneClass, NonNegTry] = Field(
        description="Son kademenin ustunde desi basi birim fiyat"
    )

    surcharges: Surcharges
    volume_discounts: list[VolumeDiscount] = Field(default_factory=list)
    service: ServiceLevel
    constraints: CarrierConstraints

    # ---- dogrulamalar -------------------------------------------------------

    @model_validator(mode="after")
    def _tiers_sorted_and_monotone(self) -> Self:
        bounds = [tier.up_to for tier in self.desi_tiers]
        if bounds != sorted(bounds) or len(set(bounds)) != len(bounds):
            raise ValueError(
                f"{self.carrier}: desi kademeleri artan ve tekil olmali, bulunan: {bounds}"
            )

        for zone in ZoneClass:
            prices = [tier.zones[zone] for tier in self.desi_tiers]
            for lower, upper in pairwise(prices):
                if upper < lower:
                    raise ValueError(
                        f"{self.carrier}/{zone.value}: fiyat desi arttikca dusuyor "
                        f"({lower} -> {upper}). Tarife dosyasinda yazim hatasi olabilir."
                    )
        return self

    @model_validator(mode="after")
    def _over_top_zones_present(self) -> Self:
        missing = ALL_ZONES - self.over_30_per_desi.keys()
        if missing:
            raise ValueError(
                f"{self.carrier}: over_30_per_desi eksik bolge: {sorted(z.value for z in missing)}"
            )
        return self

    @model_validator(mode="after")
    def _discounts_sorted(self) -> Self:
        thresholds = [d.monthly_parcels_gte for d in self.volume_discounts]
        if thresholds != sorted(thresholds):
            raise ValueError(f"{self.carrier}: hacim indirimleri artan esige gore siralanmali")
        return self

    # ---- sorgular -----------------------------------------------------------

    @property
    def is_synthetic(self) -> bool:
        """Arayuzde 'ORNEK TARIFE' rozeti gosterilip gosterilmeyecegini belirler."""
        return self.source is TariffSourceKind.SYNTHETIC

    @property
    def top_tier_desi(self) -> float:
        """Tablonun bittigi desi. Bunun ustu `over_30_per_desi` ile fiyatlanir."""
        return self.desi_tiers[-1].up_to

    def base_price(self, chargeable_desi: float, zone: ZoneClass) -> float:
        """Ek ucretler ve asgari ucret uygulanmadan onceki taban tarife bedeli."""
        for tier in self.desi_tiers:
            if chargeable_desi <= tier.up_to:
                return tier.zones[zone]
        # Tablonun ustu: son kademe + asan desi basina birim fiyat.
        top = self.desi_tiers[-1]
        excess = chargeable_desi - top.up_to
        return top.zones[zone] + excess * self.over_30_per_desi[zone]

    def volume_discount_pct(self, monthly_parcels: int) -> float:
        """Aylik hacme karsilik gelen en yuksek indirim orani."""
        applicable = [
            d.pct for d in self.volume_discounts if monthly_parcels >= d.monthly_parcels_gte
        ]
        return max(applicable, default=0.0)

    def serves(self, city_plate: int) -> bool:
        return city_plate not in self.constraints.unserved_plates
