"""Desi aritmetigi ve para yuvarlamasi.

Bu modul motorun en cok cagrilan ve en cok yanlis yapilan parcasi. Iki incelik var:

1. **Kayan nokta ve kademe siniri.** `33 x 22 x 11 / 3000` gibi bir hesap ikilik
   tabanda tam ifade edilemez; `2.0` olmasi gereken bir deger `2.0000000004` cikip
   yukari yuvarlanirsa musteri bir ust tarife kademesinden fatura alir. Tum
   yuvarlamalar bu yuzden `EPS` toleransi ile yapilir.

2. **Para icin bankaci yuvarlamasi yanlistir.** Python'un yerlesik `round()`
   fonksiyonu `round(2.675, 2) == 2.67` verir (bankaci yuvarlamasi). Fatura
   satirlarinda beklenen davranis yariyi yukari yuvarlamaktir; `money()` bunu
   `Decimal` ile yapar.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from .enums import RoundingRule

#: Turkiye'de kargo sektorunun standart desi bolen katsayisi (cm^3 -> desi).
DESI_DIVISOR: Final[int] = 3000

#: Kayan nokta karsilastirma toleransi. Tarife kademesi sinirinda kritik.
EPS: Final[float] = 1e-9


def volumetric_desi(length_cm: float, width_cm: float, height_cm: float) -> float:
    """Hacimsel desi: `(en x boy x yukseklik) / 3000`, santimetre cinsinden.

    >>> volumetric_desi(30, 20, 10)
    2.0
    """
    if length_cm <= 0 or width_cm <= 0 or height_cm <= 0:
        raise ValueError(f"Boyutlar pozitif olmali: {length_cm}x{width_cm}x{height_cm}")
    return (length_cm * width_cm * height_cm) / DESI_DIVISOR


def ceil_to_step(value: float, step: float = 1.0) -> float:
    """`value`'yu `step`'in bir ust katina yuvarlar (EPS toleransli).

    >>> ceil_to_step(2.0000000004)
    2.0
    >>> ceil_to_step(2.01)
    3.0
    """
    return math.ceil(value / step - EPS) * step


def half_up_to_step(value: float, step: float = 1.0) -> float:
    """`value`'yu en yakin `step` katina, yarisi yukari olacak sekilde yuvarlar.

    >>> half_up_to_step(2.5)
    3.0
    >>> half_up_to_step(2.49)
    2.0
    """
    return math.floor(value / step + 0.5 + EPS) * step


def apply_rounding(value: float, rule: RoundingRule, step: float = 1.0) -> float:
    """Firma sozlesmesindeki yuvarlama kuralini uygular."""
    match rule:
        case RoundingRule.CEIL:
            return ceil_to_step(value, step)
        case RoundingRule.HALF_UP:
            return half_up_to_step(value, step)
        case RoundingRule.NONE:
            return value
    raise ValueError(f"Bilinmeyen yuvarlama kurali: {rule}")


def chargeable_desi(
    volumetric: float,
    weight_kg: float,
    rule: RoundingRule = RoundingRule.CEIL,
    step: float = 1.0,
) -> float:
    """Ucretli desi: hacimsel desi ile fiili agirligin buyugu, sonra yuvarlanmis.

    Kargo firmalari `max(hacim, agirlik)` uzerinden fatura keser -- 40 desilik ama
    2 kg gelen bir yorgan da, 2 desilik ama 8 kg gelen bir deterjan kolisi de
    dogru fiyatlansin diye.

    >>> chargeable_desi(volumetric=2.0, weight_kg=3.5)
    4.0
    >>> chargeable_desi(volumetric=7.2, weight_kg=1.0)
    8.0
    """
    if weight_kg < 0:
        raise ValueError(f"Agirlik negatif olamaz: {weight_kg}")
    return apply_rounding(max(volumetric, weight_kg), rule, step)


def money(value: float, places: int = 2) -> float:
    """Para tutarini kurusa yuvarlar (yarisi yukari).

    Motorun ici boyunca `float` kullaniyoruz; `Decimal` numpy ile vektorlestirmeyi
    imkansiz kilar ve Monte Carlo kosusunu yavaslatir. Bunun yerine para yalnizca
    *sunum ve fatura sinirlarinda* bu fonksiyonla sabitlenir.
    Bkz. docs/adr/0002-para-tipi.md
    """
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(repr(value)).quantize(quantum, rounding=ROUND_HALF_UP))
