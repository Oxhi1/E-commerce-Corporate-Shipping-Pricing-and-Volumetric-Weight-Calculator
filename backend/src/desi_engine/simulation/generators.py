"""Sentetik siparis uretimi.

Rastgele urun secmek yeterli degil: gercek sepetler **iliskilidir**. Banyo
havlusu alan musteri bornoz da alir, zeytinyagi alan musteri nevresim de alabilir
(hipermarket sepeti) ama porselen takim ve deterjan ayni sepette nadiren bulusur.
Bagimsiz cekilis bu yapiyi yok eder ve kontaminasyon riskini gercekte oldugundan
cok daha seyrek uretir -- yani projenin en ilginc senaryosunu gormezden gelir.

Cozum: **sepet arketipleri**. Once bir alisveris niyeti secilir (banyo yenileme,
yatak odasi, temizlik alisverisi...), sonra urunler o niyetin kategorilerinden
cekilir.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Final

import numpy as np

from ..domain.enums import ProductCategory
from ..domain.models import Address, Cart, CartLine, Order, Product
from ..tariff.zones import ProvinceRegistry


@dataclass(frozen=True, slots=True)
class BasketArchetype:
    """Bir alisveris niyeti ve ondan cikan urun kategorileri."""

    name: str
    weight: float
    categories: tuple[ProductCategory, ...]
    min_lines: int = 1
    max_lines: int = 4


#: Ozdilek profiline uygun sepet arketipleri.
BASKET_ARCHETYPES: Final[tuple[BasketArchetype, ...]] = (
    BasketArchetype(
        "banyo_yenileme",
        weight=0.24,
        categories=(ProductCategory.TOWEL, ProductCategory.BATHROBE, ProductCategory.PERSONAL_CARE),
        min_lines=1,
        max_lines=4,
    ),
    BasketArchetype(
        "yatak_odasi",
        weight=0.22,
        categories=(ProductCategory.BEDDING, ProductCategory.BLANKET),
        min_lines=1,
        max_lines=3,
    ),
    BasketArchetype(
        "mutfak",
        weight=0.14,
        categories=(ProductCategory.KITCHENWARE, ProductCategory.SMALL_APPLIANCE),
        min_lines=1,
        max_lines=3,
    ),
    BasketArchetype(
        "temizlik",
        weight=0.13,
        categories=(ProductCategory.DETERGENT, ProductCategory.PERSONAL_CARE),
        min_lines=1,
        max_lines=4,
    ),
    BasketArchetype(
        "ev_dekorasyon",
        weight=0.12,
        categories=(ProductCategory.HOME_DECOR, ProductCategory.CURTAIN, ProductCategory.TOWEL),
        min_lines=1,
        max_lines=3,
    ),
    # Kritik arketip: hipermarket sepeti. Gida sivisi ile tekstili bir araya
    # getiren tek arketip bu; kontaminasyon senaryosunun kaynagi.
    BasketArchetype(
        "hipermarket",
        weight=0.15,
        categories=(
            ProductCategory.FOOD_LIQUID,
            ProductCategory.DETERGENT,
            ProductCategory.TOWEL,
            ProductCategory.BEDDING,
        ),
        min_lines=2,
        max_lines=5,
    ),
)


@dataclass(frozen=True, slots=True)
class OrderGeneratorConfig:
    """Siparis akisinin sekli."""

    origin_plate: int = 16
    cod_share: float = 0.22
    """Kapida odeme orani. Turkiye e-ticaretinde hala yuksek."""

    rural_share: float = 0.08
    new_customer_share: float = 0.35
    """CLV'si sifir sayilan musteri orani -- ilk siparisini veren musteriler."""

    clv_log_mean: float = 7.9
    clv_log_sigma: float = 0.65
    """Musteri yasam boyu degerinin log-normal parametreleri (~2700 TL medyan)."""

    max_quantity_per_line: int = 3
    archetypes: tuple[BasketArchetype, ...] = BASKET_ARCHETYPES


class OrderGenerator:
    """Tekrarlanabilir sentetik siparis akisi uretir.

    Ayni tohumla ayni siparisler cikar. Bu, politikalarin **birebir ayni** siparis
    akisi uzerinde yaristirilmasini mumkun kilar (bkz. `runner.py`, ortak rastgele
    sayilar); yaristirmanin adil olmasinin on kosulu budur.
    """

    def __init__(
        self,
        products: dict[str, Product],
        provinces: ProvinceRegistry,
        config: OrderGeneratorConfig | None = None,
    ) -> None:
        self.products = products
        self.provinces = provinces
        self.config = config or OrderGeneratorConfig()

        self._by_category: dict[ProductCategory, list[Product]] = {}
        for product in products.values():
            self._by_category.setdefault(product.category, []).append(product)

        missing = {
            category
            for archetype in self.config.archetypes
            for category in archetype.categories
            if category not in self._by_category
        }
        if missing:
            raise ValueError(
                f"Katalogda su kategorilerde urun yok: {sorted(c.value for c in missing)}"
            )

        self._archetype_probs = np.array([a.weight for a in self.config.archetypes])
        self._archetype_probs /= self._archetype_probs.sum()

        weights = provinces.population_weights()
        self._plates = np.array(list(weights))
        self._plate_probs = np.array([weights[p] for p in self._plates])
        self._plate_probs /= self._plate_probs.sum()

    # ---- uretim -------------------------------------------------------------

    def generate(self, count: int, rng: np.random.Generator) -> list[Order]:
        return list(self.stream(count, rng))

    def stream(self, count: int, rng: np.random.Generator) -> Iterator[Order]:
        """Siparisleri tek tek uretir -- buyuk kosularda bellegi sisirmemek icin."""
        for index in range(count):
            yield self._make_order(f"SIM-{index:07d}", rng)

    def _make_order(self, order_id: str, rng: np.random.Generator) -> Order:
        archetype = self.config.archetypes[
            int(rng.choice(len(self.config.archetypes), p=self._archetype_probs))
        ]
        cart = Cart(lines=self._make_lines(archetype, rng))

        plate = int(rng.choice(self._plates, p=self._plate_probs))
        province = self.provinces.get(plate)

        return Order(
            order_id=order_id,
            cart=cart,
            address=Address(
                city_plate=plate,
                city_name=province.name,
                region=province.region,
                is_rural=bool(rng.random() < self.config.rural_share),
            ),
            is_cod=bool(rng.random() < self.config.cod_share),
            customer_clv_try=self._draw_clv(rng),
            origin_plate=self.config.origin_plate,
        )

    def _make_lines(self, archetype: BasketArchetype, rng: np.random.Generator) -> list[CartLine]:
        line_count = int(rng.integers(archetype.min_lines, archetype.max_lines + 1))

        pool: list[Product] = []
        for category in archetype.categories:
            pool.extend(self._by_category[category])

        line_count = min(line_count, len(pool))
        chosen_indexes = rng.choice(len(pool), size=line_count, replace=False)

        return [
            CartLine(
                product=pool[int(index)],
                # Adet dagilimi carpik: cogu satir tek adet, bazilari 2-3.
                quantity=int(
                    rng.choice(
                        range(1, self.config.max_quantity_per_line + 1),
                        p=_quantity_probs(self.config.max_quantity_per_line),
                    )
                ),
            )
            for index in chosen_indexes
        ]

    def _draw_clv(self, rng: np.random.Generator) -> float:
        """Musteri yasam boyu degeri.

        Musterilerin bir kismi ilk siparisini veriyor; onlarin CLV'si sifir
        sayilir. Herkese pozitif CLV atamak, churn maliyetini butun siparislere
        yayarak motorun her yerde pahali firma secmesine yol acardi.
        """
        if rng.random() < self.config.new_customer_share:
            return 0.0
        return float(rng.lognormal(mean=self.config.clv_log_mean, sigma=self.config.clv_log_sigma))


def _quantity_probs(max_quantity: int) -> np.ndarray:
    """Adet dagilimi: 1 adet baskin, yuksek adetler hizla seyreliyor."""
    weights = np.array([1.0 / (index + 1) ** 2 for index in range(max_quantity)])
    return weights / weights.sum()
