"""Il kayitlari ve tarife bolgesi siniflandirmasi.

Bolge sinifi (`ZoneClass`) tarife matrisinin sutun eksenidir; yanlis siniflandirma
dogrudan yanlis fiyat demektir. Sinif elle yazilmis bir il->bolge tablosundan degil,
uc veriden **turetilir**: ayni il mi, uzak il mi, ve iki il arasindaki gercek
buyuk cember mesafesi. Boylece cikis deposu Bursa'dan Istanbul'a tasinsa bile
siniflandirma kendini gunceller.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Final

from ..domain.enums import Region, ZoneClass

#: Ortalama Dunya yaricapi (km).
EARTH_RADIUS_KM: Final[float] = 6371.0

#: Bu mesafenin uzerindeki gonderiler -- ayni cografi bolgede olmasalar bile --
#: `UZAK` sayilir. Turkiye'nin dogu-bati ekseni ~1600 km oldugundan 900 km,
#: "ulkenin obur ucu" sezgisine karsilik gelir.
FAR_DISTANCE_KM: Final[float] = 900.0


@dataclass(frozen=True, slots=True)
class Province:
    """Bir il ve tarife/SLA icin gereken nitelikleri."""

    plate: int
    name: str
    region: Region
    population: int
    lat: float
    lon: float
    is_remote: bool

    def __str__(self) -> str:
        return f"{self.plate:02d} {self.name}"


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Iki koordinat arasindaki buyuk cember mesafesi, kilometre."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


class ProvinceRegistry:
    """81 ilin kaydi; bolge siniflandirmasi ve mesafe sorgulari."""

    def __init__(self, provinces: dict[int, Province]) -> None:
        if not provinces:
            raise ValueError("Il kaydi bos olamaz")
        self._by_plate = provinces

    # ---- kurulum ------------------------------------------------------------

    @classmethod
    def from_csv(cls, path: Path) -> ProvinceRegistry:
        """`data/zones/tr_iller.csv` dosyasindan yukler."""
        provinces: dict[int, Province] = {}
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                plate = int(row["plate"])
                provinces[plate] = Province(
                    plate=plate,
                    name=row["name"],
                    region=Region(row["region"]),
                    population=int(row["population"]),
                    lat=float(row["lat"]),
                    lon=float(row["lon"]),
                    is_remote=row["is_remote"] == "1",
                )
        return cls(provinces)

    # ---- sorgular -----------------------------------------------------------

    def __len__(self) -> int:
        return len(self._by_plate)

    def __iter__(self):
        return iter(self._by_plate.values())

    def get(self, plate: int) -> Province:
        try:
            return self._by_plate[plate]
        except KeyError:
            raise KeyError(f"Bilinmeyen il plaka kodu: {plate}") from None

    @cached_property
    def plates(self) -> tuple[int, ...]:
        return tuple(sorted(self._by_plate))

    @cached_property
    def total_population(self) -> int:
        return sum(p.population for p in self._by_plate.values())

    def population_weights(self) -> dict[int, float]:
        """Plaka -> nufus payi. Simulasyonda siparis dagitmak icin kullanilir.

        Gercek e-ticaret talebi nufusla tam orantili degil (Istanbul'un payi
        nufus payindan yuksektir) ama nufus, duz dagitmaktan cok daha gercekci
        ve savunulabilir bir yaklasimdir.
        """
        total = self.total_population
        return {p.plate: p.population / total for p in self._by_plate.values()}

    def distance_km(self, origin_plate: int, dest_plate: int) -> float:
        origin, dest = self.get(origin_plate), self.get(dest_plate)
        return haversine_km(origin.lat, origin.lon, dest.lat, dest.lon)

    def zone_class(self, origin_plate: int, dest_plate: int) -> ZoneClass:
        """Cikis ve varis iline gore tarife bolge sinifini belirler.

        Sirasiyla:
          1. Ayni il                              -> SEHIR_ICI
          2. Varis ili 'uzak' isaretli             -> UZAK
          3. Ayni cografi bolge                    -> BOLGE_ICI
          4. Mesafe > 900 km                       -> UZAK
          5. Diger                                 -> BOLGELER_ARASI
        """
        if origin_plate == dest_plate:
            return ZoneClass.SEHIR_ICI

        origin, dest = self.get(origin_plate), self.get(dest_plate)
        if dest.is_remote:
            return ZoneClass.UZAK
        if origin.region is dest.region:
            return ZoneClass.BOLGE_ICI
        if self.distance_km(origin_plate, dest_plate) > FAR_DISTANCE_KM:
            return ZoneClass.UZAK
        return ZoneClass.BOLGELER_ARASI
