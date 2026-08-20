"""Ortak test fikstur'leri."""

from __future__ import annotations

from pathlib import Path

import pytest

from desi_engine.domain import (
    Address,
    Cart,
    CartLine,
    Dimensions,
    Fragility,
    Order,
    Product,
    ProductCategory,
    Region,
)
from desi_engine.tariff import ProvinceRegistry, TariffRepository

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(scope="session")
def data_dir() -> Path:
    return DATA_DIR


@pytest.fixture(scope="session")
def tariffs() -> TariffRepository:
    return TariffRepository(DATA_DIR / "carriers")


@pytest.fixture(scope="session")
def provinces() -> ProvinceRegistry:
    return ProvinceRegistry.from_csv(DATA_DIR / "zones" / "tr_iller.csv")


@pytest.fixture(scope="session")
def engine():
    """Tam kurulu motor. Oturum kapsamli: gecmis veriyi okuyup modelleri egitmek
    pahali ve tum testler icin ayni sonucu veriyor."""
    from desi_engine.engine import build_engine

    return build_engine(DATA_DIR)


# ---- referans urunler --------------------------------------------------------
# Elle kurulmus, katalogdan bagimsiz urunler: katalog degisince testler kirilmasin.


@pytest.fixture
def towel() -> Product:
    return Product(
        sku="T-TEST",
        name="Test Havlusu",
        category=ProductCategory.TOWEL,
        dims=Dimensions(length_cm=32, width_cm=24, height_cm=11),
        weight_kg=0.62,
        unit_price_try=329.0,
        is_absorbent=True,
        compressibility=0.18,
    )


@pytest.fixture
def duvet() -> Product:
    return Product(
        sku="D-TEST",
        name="Test Nevresim",
        category=ProductCategory.BEDDING,
        dims=Dimensions(length_cm=42, width_cm=32, height_cm=14),
        weight_kg=1.95,
        unit_price_try=1890.0,
        is_absorbent=True,
        compressibility=0.22,
    )


@pytest.fixture
def olive_oil() -> Product:
    """Sizinti kaynagi: kullanicinin zeytinyagi senaryosunun test karsiligi."""
    return Product(
        sku="O-TEST",
        name="Test Zeytinyagi 5L",
        category=ProductCategory.FOOD_LIQUID,
        dims=Dimensions(length_cm=20, width_cm=14, height_cm=28),
        weight_kg=5.2,
        unit_price_try=1980.0,
        fragility=Fragility.MEDIUM,
        is_liquid=True,
        stackable=False,
        max_stack_load_kg=0.0,
    )


@pytest.fixture
def porcelain() -> Product:
    return Product(
        sku="P-TEST",
        name="Test Porselen Takim",
        category=ProductCategory.KITCHENWARE,
        dims=Dimensions(length_cm=44, width_cm=34, height_cm=24),
        weight_kg=9.8,
        unit_price_try=3490.0,
        fragility=Fragility.HIGH,
        stackable=False,
        max_stack_load_kg=0.0,
    )


# ---- referans sepetler -------------------------------------------------------


@pytest.fixture
def soft_cart(towel, duvet) -> Cart:
    """Yalnizca tekstil -- kutulamadan en cok kazanci bu sepet saglar."""
    return Cart(lines=[CartLine(product=towel, quantity=4), CartLine(product=duvet, quantity=1)])


@pytest.fixture
def contamination_cart(olive_oil, duvet) -> Cart:
    """Zeytinyagi + nevresim: yan hasar senaryosunun referans sepeti."""
    return Cart(
        lines=[CartLine(product=olive_oil, quantity=1), CartLine(product=duvet, quantity=1)]
    )


@pytest.fixture
def van_address() -> Address:
    return Address(city_plate=65, city_name="Van", region=Region.DOGU_ANADOLU)


@pytest.fixture
def istanbul_address() -> Address:
    return Address(city_plate=34, city_name="İstanbul", region=Region.MARMARA)


@pytest.fixture
def van_order(contamination_cart, van_address) -> Order:
    """Kabul kriteri #2'nin siparisi: Van'a giden zeytinyagi + nevresim."""
    return Order(
        order_id="TEST-VAN-001",
        cart=contamination_cart,
        address=van_address,
        customer_clv_try=4500.0,
    )
