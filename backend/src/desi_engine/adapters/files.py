"""Dosya tabanli veri kaynaklari (CSV / YAML).

Sentetik demo verisi de, Ozdilek'in gercek sozlesme dosyalari da ayni okuyuculardan
gecer -- ikisi arasindaki fark dosyanin **icerigi**, kodun yolu degil. Tarifelerde
bu ayrim `source: synthetic | contract` alaniyla tasinir ve arayuze kadar gider.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from ..domain.enums import CarrierCode, Fragility, ProductCategory
from ..domain.models import Dimensions, Product
from ..tariff.loader import TariffRepository
from ..tariff.schema import Tariff

#: Urun katalogu CSV'sinde beklenen sutunlar.
PRODUCT_COLUMNS: frozenset[str] = frozenset(
    {
        "sku",
        "name",
        "category",
        "length_cm",
        "width_cm",
        "height_cm",
        "weight_kg",
        "unit_price_try",
        "fragility",
        "is_liquid",
        "is_absorbent",
        "stackable",
        "max_stack_load_kg",
        "compressibility",
    }
)


class FileTariffSource:
    """`data/carriers/*.yaml` dosyalarindan tarife okur."""

    def __init__(self, directory: Path) -> None:
        self._repository = TariffRepository(directory)

    def available_carriers(self) -> tuple[CarrierCode, ...]:
        return self._repository.carriers

    def load(self, carrier: CarrierCode) -> Tariff:
        return self._repository.get(carrier)

    @property
    def repository(self) -> TariffRepository:
        """Altta yatan depo -- yeniden yukleme ve toplu erisim icin."""
        return self._repository


class CsvProductCatalogSource:
    """`data/catalog/products.csv` dosyasindan urun katalogu okur."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Product]:
        with self.path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = PRODUCT_COLUMNS - set(reader.fieldnames or [])
            if missing:
                raise ValueError(
                    f"{self.path.name}: urun katalogunda eksik sutun: {sorted(missing)}"
                )
            products = [_row_to_product(row, self.path.name) for row in reader]

        catalog = {product.sku: product for product in products}
        if len(catalog) != len(products):
            raise ValueError(f"{self.path.name}: SKU'lar tekil olmali")
        return catalog


class CsvShipmentHistorySource:
    """`data/history/shipments.csv` dosyasindan gecmis sevkiyat okur."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> pd.DataFrame:
        if not self.path.exists():
            raise FileNotFoundError(
                f"{self.path} bulunamadi. Once "
                "`python scripts/generate_synthetic_history.py` calistirin."
            )
        return pd.read_csv(self.path)


def _row_to_product(row: dict[str, str], filename: str) -> Product:
    try:
        return Product(
            sku=row["sku"].strip(),
            name=row["name"].strip(),
            category=ProductCategory(row["category"].strip()),
            dims=Dimensions(
                length_cm=float(row["length_cm"]),
                width_cm=float(row["width_cm"]),
                height_cm=float(row["height_cm"]),
            ),
            weight_kg=float(row["weight_kg"]),
            unit_price_try=float(row["unit_price_try"]),
            fragility=Fragility(row["fragility"].strip()),
            is_liquid=row["is_liquid"] == "1",
            is_absorbent=row["is_absorbent"] == "1",
            stackable=row["stackable"] == "1",
            max_stack_load_kg=float(row["max_stack_load_kg"]),
            compressibility=float(row["compressibility"]),
        )
    except (ValueError, KeyError) as exc:
        raise ValueError(f"{filename}: '{row.get('sku', '?')}' satiri okunamadi -- {exc}") from exc
