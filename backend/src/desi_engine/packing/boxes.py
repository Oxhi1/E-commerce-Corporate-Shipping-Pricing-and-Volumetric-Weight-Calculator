"""Koli modeli ve katalog yukleyicisi.

Kritik ayrim: **ic olcu** urunlerin sigacagi hacim, **dis olcu** kargo firmasinin
olcup faturaladigi hacimdir. Ikisi arasindaki fark oluklu mukavva et kalinligidir
ve buyuk kolilerde bir tarife kademesine denk gelebilir:

    K10 ic 80x60x50 -> 80.0 desi
    K10 dis 81.6x61.6x51.6 -> 86.5 desi     (+%8)

Yalnizca ic olcuyle hesap yapan bir motor her koliyi sistematik olarak ucuz
tahmin eder ve gercek fatura geldiginde tutmaz.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..domain.enums import RiskCategory
from ..domain.models import Dimensions
from ..domain.units import volumetric_desi


class Box(BaseModel):
    """Standart bir ambalaj kolisi (veya kargo poseti)."""

    model_config = ConfigDict(frozen=True)

    code: str
    name: str
    inner: Dimensions
    wall_cm: Annotated[float, Field(ge=0, le=5)]
    tare_kg: Annotated[float, Field(ge=0)]
    max_payload_kg: Annotated[float, Field(gt=0)]
    unit_cost_try: Annotated[float, Field(ge=0)]
    soft_only: bool = Field(
        default=False,
        description="Kargo poseti: kirilabilir veya sivi urun konamaz",
    )

    @property
    def outer(self) -> Dimensions:
        """Kargo firmasinin olctugu dis olcu."""
        pad = 2 * self.wall_cm
        return Dimensions(
            length_cm=self.inner.length_cm + pad,
            width_cm=self.inner.width_cm + pad,
            height_cm=self.inner.height_cm + pad,
        )

    @property
    def outer_desi(self) -> float:
        """Faturaya esas hacimsel desi."""
        return volumetric_desi(*self.outer.as_tuple())

    @property
    def inner_volume_cm3(self) -> float:
        return self.inner.volume_cm3

    def __str__(self) -> str:
        return f"{self.code} ({self.name})"


class BoxCatalog:
    """Depodaki ambalaj stogu. Dis desiye gore artan siralidir."""

    def __init__(self, boxes: list[Box]) -> None:
        if not boxes:
            raise ValueError("Koli katalogu bos olamaz")
        codes = [b.code for b in boxes]
        if len(set(codes)) != len(codes):
            raise ValueError(f"Koli kodlari tekil olmali: {codes}")
        # Artan dis desi: paketleyici "sigan en kucuk kutu"yu bu sirada arar.
        self._boxes = tuple(sorted(boxes, key=lambda b: b.outer_desi))

    @classmethod
    def from_yaml(cls, path: Path) -> BoxCatalog:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls([Box.model_validate(entry) for entry in raw["boxes"]])

    def __len__(self) -> int:
        return len(self._boxes)

    def __iter__(self):
        return iter(self._boxes)

    def get(self, code: str) -> Box:
        for box in self._boxes:
            if box.code == code:
                return box
        raise KeyError(f"Bilinmeyen koli kodu: {code}")

    @property
    def boxes(self) -> tuple[Box, ...]:
        return self._boxes

    def usable(self, *, allow_soft_only: bool) -> tuple[Box, ...]:
        """Bu icerik icin kullanilabilir kutular.

        `allow_soft_only=False` ise kargo posetleri elenir -- icerikte kirilabilir
        veya sivi urun var demektir.
        """
        if allow_soft_only:
            return self._boxes
        return tuple(b for b in self._boxes if not b.soft_only)

    @property
    def largest(self) -> Box:
        return self._boxes[-1]


class Placement(BaseModel):
    """Bir urunun koli icindeki konumu ve yonlenmis olculeri.

    Koordinat sistemi: kolinin ic hacminin sol-arka-alt kosesi orijin (0,0,0);
    x = uzunluk, y = genislik, z = yukseklik ekseni. Olculer urunun
    `effective_dims` degeridir (sikisma ve dolgu payi uygulanmis).
    """

    model_config = ConfigDict(frozen=True)

    sku: str
    name: str
    x: float
    y: float
    z: float
    dx: Annotated[float, Field(gt=0)]
    dy: Annotated[float, Field(gt=0)]
    dz: Annotated[float, Field(gt=0)]
    weight_kg: Annotated[float, Field(ge=0)]
    value_try: Annotated[float, Field(ge=0)] = 0.0
    risk_category: RiskCategory = RiskCategory.SOFT
    is_liquid: bool = False
    is_absorbent: bool = False
    max_stack_load_kg: float = 0.0

    @property
    def x2(self) -> float:
        return self.x + self.dx

    @property
    def y2(self) -> float:
        return self.y + self.dy

    @property
    def z2(self) -> float:
        return self.z + self.dz

    @property
    def volume_cm3(self) -> float:
        return self.dx * self.dy * self.dz

    @property
    def footprint_cm2(self) -> float:
        return self.dx * self.dy


class PackedBox(BaseModel):
    """Doldurulmus bir koli: kutu + icindeki yerlesimler."""

    model_config = ConfigDict(frozen=True)

    box: Box
    placements: list[Placement] = Field(min_length=1)

    @model_validator(mode="after")
    def _payload_within_limit(self) -> Self:
        if self.content_weight_kg > self.box.max_payload_kg + 1e-9:
            raise ValueError(
                f"{self.box.code}: icerik {self.content_weight_kg:.2f} kg, "
                f"tasima limiti {self.box.max_payload_kg} kg"
            )
        return self

    @property
    def content_weight_kg(self) -> float:
        return sum(p.weight_kg for p in self.placements)

    @property
    def gross_weight_kg(self) -> float:
        """Brut agirlik: icerik + ambalaj darasi. Ucretli desi hesabina giren agirlik."""
        return self.content_weight_kg + self.box.tare_kg

    @property
    def outer_desi(self) -> float:
        return self.box.outer_desi

    @property
    def billable_proxy_desi(self) -> float:
        """Firma bagimsiz ucretli desi vekili: `max(dis desi, brut agirlik)`.

        Paketleyici bunu minimize eder. Gercek ucretli desi firmanin yuvarlama
        kuralina bagli oldugu icin nihai deger fiyatlama aninda hesaplanir --
        paketleme karari firmadan bagimsiz kalsin diye.
        """
        return max(self.outer_desi, self.gross_weight_kg)

    @property
    def fill_ratio(self) -> float:
        """Ic hacmin ne kadarinin dolduruldugu. Paketleme kalitesinin gostergesi."""
        used = sum(p.volume_cm3 for p in self.placements)
        return used / self.box.inner_volume_cm3

    @property
    def item_count(self) -> int:
        return len(self.placements)
