"""Veri kaynagi sozlesmeleri -- **gercek veri yuvasi**.

Motorun cekirdegi (`domain`, `packing`, `tariff`, `risk`, `sla`, `decision`) hicbir
dosya okumaz. Tum giris burada tanimli uc protokolden gecer:

    TariffSource            kargo sozlesme tarifeleri
    ProductCatalogSource    urun katalogu (olcu, agirlik, fiyat, nitelikler)
    ShipmentHistorySource   gecmis sevkiyat kayitlari (hasar + teslimat suresi)

Bugun bu protokolleri sentetik CSV/YAML dosyalari karsiliyor. Ozdilek'in gercek
sozlesme fiyatlari veya ERP'den cekilen gercek sevkiyat gecmisi geldiginde
yapilacak tek is, ayni protokolu uygulayan yeni bir sinif yazmak; motorun
hicbir satiri degismez.

`typing.Protocol` kullanildi (soyut taban sinif degil): uygulayicilarin bu
modulden turemesi gerekmiyor, yalnizca dogru imzayi tasimasi yetiyor. Boylece
harici bir ERP istemcisi de -- bu paketi hic bilmeden -- gecerli bir kaynak olur.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import pandas as pd

from ..domain.enums import CarrierCode
from ..domain.models import Product
from ..tariff.schema import Tariff


@runtime_checkable
class TariffSource(Protocol):
    """Kargo firmasi sozlesme tarifelerinin kaynagi."""

    def available_carriers(self) -> tuple[CarrierCode, ...]:
        """Bu kaynakta tarifesi bulunan firmalar."""
        ...

    def load(self, carrier: CarrierCode) -> Tariff:
        """Bir firmanin dogrulanmis tarifesini doner."""
        ...


@runtime_checkable
class ProductCatalogSource(Protocol):
    """Urun katalogunun kaynagi."""

    def load(self) -> dict[str, Product]:
        """SKU -> `Product` eslemesi."""
        ...


@runtime_checkable
class ShipmentHistorySource(Protocol):
    """Gecmis sevkiyat kayitlarinin kaynagi.

    Donen tabloda su sutunlar bulunmali:
        carrier, zone, risk_category, is_rural, delivery_days, damaged
    Hasar modeli ilk dordunu, teslimat modeli son ikisini kullanir.
    """

    def load(self) -> pd.DataFrame: ...
