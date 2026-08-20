"""Cekirdek alan modelleri: urun, sepet, adres, siparis.

Hepsi Pydantic v2. Deger nesneleri (`Dimensions`, `Product`) `frozen` -- paketleme
algoritmasi bunlari sozluk anahtari ve set uyesi olarak kullaniyor, ayrica yanlislikla
mutasyona ugramalari sessiz hatalara yol acar.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from .enums import Fragility, ProductCategory, Region, RiskCategory
from .units import volumetric_desi

PositiveCm = Annotated[float, Field(gt=0, le=500, description="santimetre")]
NonNegTry = Annotated[float, Field(ge=0, description="Turk Lirasi")]

#: Katalog kategorisinden risk sinifina indirgeme.
#: Risk modeli 11 kategori yerine 4 sinifla calisir -- bkz. `RiskCategory` docstring.
CATEGORY_RISK_MAP: dict[ProductCategory, RiskCategory] = {
    ProductCategory.TOWEL: RiskCategory.SOFT,
    ProductCategory.BEDDING: RiskCategory.SOFT,
    ProductCategory.BATHROBE: RiskCategory.SOFT,
    ProductCategory.BLANKET: RiskCategory.SOFT,
    ProductCategory.CURTAIN: RiskCategory.SOFT,
    ProductCategory.HOME_DECOR: RiskCategory.FRAGILE,
    ProductCategory.KITCHENWARE: RiskCategory.FRAGILE,
    ProductCategory.DETERGENT: RiskCategory.LIQUID,
    ProductCategory.FOOD_LIQUID: RiskCategory.LIQUID,
    ProductCategory.PERSONAL_CARE: RiskCategory.LIQUID,
    ProductCategory.SMALL_APPLIANCE: RiskCategory.APPLIANCE,
}


class Dimensions(BaseModel):
    """Bir dikdortgenler prizmasinin olculeri, santimetre."""

    model_config = ConfigDict(frozen=True)

    length_cm: PositiveCm
    width_cm: PositiveCm
    height_cm: PositiveCm

    @property
    def volume_cm3(self) -> float:
        return self.length_cm * self.width_cm * self.height_cm

    @computed_field  # type: ignore[prop-decorator]
    @property
    def desi(self) -> float:
        """Bu hacmin desi karsiligi (agirlik hesaba katilmadan)."""
        return volumetric_desi(self.length_cm, self.width_cm, self.height_cm)

    def as_tuple(self) -> tuple[float, float, float]:
        return (self.length_cm, self.width_cm, self.height_cm)

    def rotations(self) -> Iterator[Dimensions]:
        """Eksen hizali 6 dondurmeyi uretir; simetrik olculerde tekrarlari eler.

        Kup bir urun icin 6 degil 1 varyant doner -- paketleme dongusunde bos yere
        6 kez ayni yerlesimi denemekten kurtarir.
        """
        length, width, height = self.as_tuple()
        seen: set[tuple[float, float, float]] = set()
        for candidate in (
            (length, width, height),
            (length, height, width),
            (width, length, height),
            (width, height, length),
            (height, length, width),
            (height, width, length),
        ):
            if candidate in seen:
                continue
            seen.add(candidate)
            yield Dimensions(length_cm=candidate[0], width_cm=candidate[1], height_cm=candidate[2])

    def fits_within(self, container: Dimensions, *, allow_rotation: bool = True) -> bool:
        """Bu olcunun `container` icine (herhangi bir dondurmeyle) sigip sigmadigi."""
        candidates = self.rotations() if allow_rotation else iter((self,))
        return any(
            rot.length_cm <= container.length_cm
            and rot.width_cm <= container.width_cm
            and rot.height_cm <= container.height_cm
            for rot in candidates
        )


class Product(BaseModel):
    """Katalog urunu. Fiziksel olculer + hasar modelinin ihtiyac duydugu nitelikler."""

    model_config = ConfigDict(frozen=True)

    sku: str
    name: str
    category: ProductCategory
    dims: Dimensions
    weight_kg: Annotated[float, Field(gt=0, le=100)]
    unit_price_try: NonNegTry

    fragility: Fragility = Fragility.NONE

    is_liquid: bool = Field(
        default=False,
        description="Sizinti kaynagi olabilir -- ayni kolideki emici urunler icin yan hasar riski",
    )
    is_absorbent: bool = Field(
        default=False,
        description="Sizintidan zarar gorur (tekstil). Yan hasarin *kurbani* tarafi.",
    )
    stackable: bool = Field(default=True, description="Uzerine baska urun konabilir mi")
    max_stack_load_kg: Annotated[float, Field(ge=0)] = 20.0
    compressibility: Annotated[float, Field(ge=0, le=0.35)] = Field(
        default=0.0,
        description="Yumusak tekstilin en kucuk boyutunda sikisabilecegi oran (0.15 = %15)",
    )

    @model_validator(mode="after")
    def _check_liquid_consistency(self) -> Self:
        if self.is_liquid and self.is_absorbent:
            raise ValueError(f"{self.sku}: bir urun hem sivi hem emici olamaz")
        return self

    @property
    def risk_category(self) -> RiskCategory:
        return CATEGORY_RISK_MAP[self.category]

    @property
    def effective_dims(self) -> Dimensions:
        """Paketlemede kullanilacak olculer.

        Iki duzeltme uygulanir:
        - **Sikisma**: havlu/nevresim gibi yumusak urunler en kucuk boyutlarinda
          `compressibility` orani kadar ezilir.
        - **Dolgu payi**: kirilabilir urunler cevrelerinde bosluk ister; bu bosluk
          gercekte kolinin icinde yer kapladigi icin olcuye eklenir.
        """
        length, width, height = self.dims.as_tuple()
        if self.compressibility > 0:
            smallest = min(length, width, height)
            shrunk = smallest * (1.0 - self.compressibility)
            # yalnizca en kucuk boyutu kucult, digerlerini koru
            dims = [length, width, height]
            dims[dims.index(smallest)] = shrunk
            length, width, height = dims
        padding = _PADDING_CM[self.fragility]
        return Dimensions(
            length_cm=length + 2 * padding,
            width_cm=width + 2 * padding,
            height_cm=height + 2 * padding,
        )


#: Kirilganlik sinifina gore urun basina kenar dolgu payi (cm, tek kenar).
_PADDING_CM: dict[Fragility, float] = {
    Fragility.NONE: 0.0,
    Fragility.LOW: 0.5,
    Fragility.MEDIUM: 1.5,
    Fragility.HIGH: 3.0,
}


class CartLine(BaseModel):
    """Sepet satiri: bir urun ve adedi."""

    model_config = ConfigDict(frozen=True)

    product: Product
    quantity: Annotated[int, Field(ge=1, le=99)]

    @property
    def line_value_try(self) -> float:
        return self.product.unit_price_try * self.quantity

    @property
    def line_weight_kg(self) -> float:
        return self.product.weight_kg * self.quantity


class Cart(BaseModel):
    """Musteri sepeti."""

    lines: list[CartLine] = Field(min_length=1)

    def units(self) -> Iterator[Product]:
        """Satirlari tek tek urun kopyalarina acar -- paketleme algoritmasinin girdisi."""
        for line in self.lines:
            yield from (line.product for _ in range(line.quantity))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_value_try(self) -> float:
        """Sepet tutari `S`. Hasar maliyeti modelinin taban degeri."""
        return sum(line.line_value_try for line in self.lines)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_weight_kg(self) -> float:
        return sum(line.line_weight_kg for line in self.lines)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def naive_desi(self) -> float:
        """Mevcut durumun baz cizgisi: her urunun desisi ayri hesaplanip toplanir.

        Kasitli olarak **iyimser** bir baz cizgi: gercek hayatta cogu sistem her
        kalemi ayri ayri yukari yuvarlayip toplar, bu da daha yuksek bir sayi verir.
        Burada yuvarlamayi yapmiyoruz -- boylece "desi tasarrufu" iddiamiz baz cizgiyi
        kabartarak degil, gercek paketleme kazancindan geliyor.
        """
        return sum(max(unit.dims.desi, unit.weight_kg) for unit in self.units())

    @property
    def contains_liquid(self) -> bool:
        return any(line.product.is_liquid for line in self.lines)

    @property
    def contains_absorbent(self) -> bool:
        return any(line.product.is_absorbent for line in self.lines)

    @property
    def has_contamination_risk(self) -> bool:
        """Ayni sepette hem sizabilecek hem sizintidan zarar gorecek urun var mi.

        Kullanicinin zeytinyagi + nevresim senaryosu tam olarak bu bayragi tetikler.
        Kutulama bunlari ayirmaya calisir; ayiramazsa hasar maliyeti buyur.
        """
        return self.contains_liquid and self.contains_absorbent


class Address(BaseModel):
    """Teslimat adresi. Tarife bolgesi ve SLA icin gerekli asgari alanlar."""

    model_config = ConfigDict(frozen=True)

    city_plate: Annotated[int, Field(ge=1, le=81, description="Il plaka kodu")]
    city_name: str
    region: Region
    district: str | None = None
    is_rural: bool = Field(
        default=False,
        description="Koy/belde -- teslimat suresini uzatir, bazi firmalar hizmet vermez",
    )


class Order(BaseModel):
    """Fiyatlanacak siparis."""

    order_id: str
    cart: Cart
    address: Address
    is_cod: bool = Field(default=False, description="Kapida odeme")
    customer_clv_try: NonNegTry = Field(
        default=0.0,
        description="Musteri yasam boyu degeri -- churn maliyetinin carpani",
    )
    origin_plate: int = Field(default=16, description="Cikis deposu il plakasi (16 = Bursa)")
