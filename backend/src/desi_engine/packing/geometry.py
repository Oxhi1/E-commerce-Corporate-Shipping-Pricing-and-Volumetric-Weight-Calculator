"""Yerlestirme icin saf geometrik yuklemler.

Arama dongusunde yuz binlerce kez cagrildigi icin burada Pydantic modeli degil,
hafif bir `NamedTuple` kullaniliyor; `Placement` nesneleri yalnizca nihai sonuc
uretilirken olusturulur.
"""

from __future__ import annotations

from typing import Final, NamedTuple

#: Geometrik karsilastirma toleransi (cm). Yan yana duran iki urunun kayan nokta
#: gurultusu yuzunden "cakisiyor" gorunmesini engeller.
EPS: Final[float] = 1e-6


class Cuboid(NamedTuple):
    """Eksen hizali dikdortgenler prizmasi: konum + olcu."""

    x: float
    y: float
    z: float
    dx: float
    dy: float
    dz: float

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
    def footprint_cm2(self) -> float:
        return self.dx * self.dy

    @property
    def volume_cm3(self) -> float:
        return self.dx * self.dy * self.dz


def overlap_length(a1: float, a2: float, b1: float, b2: float) -> float:
    """Iki aralik arasindaki ortusme uzunlugu (ortusmuyorsa 0)."""
    return max(0.0, min(a2, b2) - max(a1, b1))


def intersects(a: Cuboid, b: Cuboid) -> bool:
    """Iki prizmanin hacimsel olarak cakisip cakismadigi.

    Yalnizca yuzey teması cakisma sayilmaz -- `EPS` bunun icin.
    """
    return (
        overlap_length(a.x, a.x2, b.x, b.x2) > EPS
        and overlap_length(a.y, a.y2, b.y, b.y2) > EPS
        and overlap_length(a.z, a.z2, b.z, b.z2) > EPS
    )


def fits_inside(
    item: Cuboid, container_dx: float, container_dy: float, container_dz: float
) -> bool:
    """Prizmanin kutu sinirlari icinde kalip kalmadigi."""
    return (
        item.x >= -EPS
        and item.y >= -EPS
        and item.z >= -EPS
        and item.x2 <= container_dx + EPS
        and item.y2 <= container_dy + EPS
        and item.z2 <= container_dz + EPS
    )


def contact_area_xy(upper: Cuboid, lower: Cuboid) -> float:
    """`upper`'in tabani ile `lower`'in ust yuzu arasindaki temas alani (cm^2).

    Yalnizca `lower`'in ust yuzu `upper`'in tabani ile ayni yukseklikteyse
    (tolerans dahilinde) sifirdan buyuk doner.
    """
    if abs(lower.z2 - upper.z) > 1e-3:
        return 0.0
    return overlap_length(upper.x, upper.x2, lower.x, lower.x2) * overlap_length(
        upper.y, upper.y2, lower.y, lower.y2
    )


def support_ratio(candidate: Cuboid, placed: list[Cuboid]) -> float:
    """Adayin tabaninin ne kadarlik oraninin desteklendigi (0..1).

    Zeminde duran bir urun (z ~ 0) tam desteklidir. Aksi halde, tam altindaki
    urunlerin ust yuzleriyle olan temas alanlari toplanir. Yerlesim algoritmasi
    cakismaya izin vermedigi icin bu alanlar ayriktir; toplam guvenle bolunebilir.
    """
    if candidate.z <= 1e-3:
        return 1.0
    footprint = candidate.footprint_cm2
    if footprint <= 0:
        return 0.0
    supported = sum(contact_area_xy(candidate, lower) for lower in placed)
    return min(1.0, supported / footprint)


def supporters(candidate: Cuboid, placed: list[Cuboid]) -> list[tuple[int, float]]:
    """Adayi tasiyan urunlerin `(indeks, temas_alani)` listesi.

    Zeminde duran urun icin bos liste doner -- yuk zemine biner, hicbir urune degil.
    """
    if candidate.z <= 1e-3:
        return []
    found = [
        (index, area)
        for index, lower in enumerate(placed)
        if (area := contact_area_xy(candidate, lower)) > EPS
    ]
    return found


def strictly_below(candidate: Cuboid, other: Cuboid) -> bool:
    """`other`, `candidate`'in tamamen altinda ve yatayda onunla ortusuyor mu.

    Sivi bir urunun emici bir urunun uzerine konmasini engelleyen kural bunu
    kullanir: sizinti dikey olarak asagi akar, bu yuzden yatay ortusme yeterlidir.
    """
    if other.z2 > candidate.z + 1e-3:
        return False
    return (
        overlap_length(candidate.x, candidate.x2, other.x, other.x2) > EPS
        and overlap_length(candidate.y, candidate.y2, other.y, other.y2) > EPS
    )
