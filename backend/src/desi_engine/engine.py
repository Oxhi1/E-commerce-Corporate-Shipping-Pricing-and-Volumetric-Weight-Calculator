"""Motorun birlestirilmesi -- tek cagriyla calisir hale getirme.

Her bilesen kendi basina bagimsiz ve test edilebilir; ama CLI, API, simulasyon ve
testler ayni sekilde kurulmus bir motora ihtiyac duyuyor. Bu modul o kurulumu tek
bir yerde toplar. Kurulum mantiginin dort ayri yerde kopyalanmasi, zamanla dort
farkli davranan motor demek olurdu.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import pandas as pd

from .adapters.files import (
    CsvProductCatalogSource,
    CsvShipmentHistorySource,
    FileTariffSource,
)
from .decision.objective import ObjectiveParams
from .decision.selector import CarrierSelector
from .domain.models import Product
from .packing.boxes import BoxCatalog
from .packing.packer import PackingPlanner
from .packing.rules import PackingRules
from .risk.damage_cost import DamageCostModel, DamageCostParams
from .risk.hierarchy import DamageRateEstimator
from .sla.delay_cost import DelayCostModel, DelayCostParams
from .sla.delivery_time import DeliveryTimeEstimator
from .tariff.calculator import FreightCalculator
from .tariff.loader import TariffRepository
from .tariff.zones import ProvinceRegistry

#: Ozdilek'in aylik gonderi hacmi varsayimi -- sozlesme indirim kademesini belirler.
DEFAULT_MONTHLY_PARCEL_VOLUME: int = 7_000

#: Varsayilan cikis deposu: Bursa (Ozdilek merkezi).
DEFAULT_ORIGIN_PLATE: int = 16


@dataclass(frozen=True, slots=True)
class EngineConfig:
    """Motor kurulum ayarlari."""

    data_dir: Path
    monthly_parcel_volume: int = DEFAULT_MONTHLY_PARCEL_VOLUME
    origin_plate: int = DEFAULT_ORIGIN_PLATE
    packing_rules: PackingRules | None = None
    objective: ObjectiveParams | None = None
    damage_params: DamageCostParams | None = None
    delay_params: DelayCostParams | None = None


class Engine:
    """Kurulu ve calismaya hazir karar motoru.

    Pahali islemler (gecmis veriyi okuma, model egitimi) `cached_property` ile
    ilk erisimde yapilir. Boylece yalnizca fiyatlama isteyen bir cagri, hasar
    modelini egitmek zorunda kalmaz.
    """

    def __init__(self, config: EngineConfig) -> None:
        self.config = config
        self.data_dir = config.data_dir

    # ---- veri kaynaklari ----------------------------------------------------

    @cached_property
    def tariff_source(self) -> FileTariffSource:
        return FileTariffSource(self.data_dir / "carriers")

    @cached_property
    def tariffs(self) -> TariffRepository:
        return self.tariff_source.repository

    @cached_property
    def provinces(self) -> ProvinceRegistry:
        return ProvinceRegistry.from_csv(self.data_dir / "zones" / "tr_iller.csv")

    @cached_property
    def box_catalog(self) -> BoxCatalog:
        return BoxCatalog.from_yaml(self.data_dir / "boxes" / "catalog.yaml")

    @cached_property
    def products(self) -> dict[str, Product]:
        return CsvProductCatalogSource(self.data_dir / "catalog" / "products.csv").load()

    @cached_property
    def history(self) -> pd.DataFrame:
        return CsvShipmentHistorySource(self.data_dir / "history" / "shipments.csv").load()

    # ---- modeller -----------------------------------------------------------

    @cached_property
    def planner(self) -> PackingPlanner:
        return PackingPlanner(self.box_catalog, self.config.packing_rules)

    @cached_property
    def calculator(self) -> FreightCalculator:
        return FreightCalculator(monthly_parcel_volume=self.config.monthly_parcel_volume)

    @cached_property
    def damage_estimator(self) -> DamageRateEstimator:
        return DamageRateEstimator().fit(self.history)

    @cached_property
    def delivery_estimator(self) -> DeliveryTimeEstimator:
        return DeliveryTimeEstimator().fit(self.history)

    @cached_property
    def damage_model(self) -> DamageCostModel:
        return DamageCostModel(self.damage_estimator, self.config.damage_params)

    @cached_property
    def delay_model(self) -> DelayCostModel:
        return DelayCostModel(self.delivery_estimator, self.config.delay_params)

    @cached_property
    def selector(self) -> CarrierSelector:
        return CarrierSelector(
            tariffs=self.tariffs,
            provinces=self.provinces,
            planner=self.planner,
            calculator=self.calculator,
            damage_model=self.damage_model,
            delay_model=self.delay_model,
            params=self.config.objective,
        )

    # ---- kolaylik -----------------------------------------------------------

    def product(self, sku: str) -> Product:
        try:
            return self.products[sku]
        except KeyError:
            raise KeyError(f"Katalogda bulunmayan SKU: {sku}") from None

    @property
    def uses_synthetic_tariffs(self) -> bool:
        """Yuklu tarifelerden herhangi biri sentetikse arayuz uyari gostermeli."""
        return bool(self.tariffs.synthetic_carriers())


def build_engine(data_dir: Path | str, **overrides) -> Engine:
    """Varsayilan ayarlarla motor kurar.

    >>> engine = build_engine("data")
    >>> decision = engine.selector.decide(order)
    """
    return Engine(EngineConfig(data_dir=Path(data_dir), **overrides))
