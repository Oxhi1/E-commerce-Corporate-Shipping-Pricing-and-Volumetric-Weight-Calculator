"""Code 128-B barkod kodlayicisi ve SVG cizici.

Neden elle kodlanıyor?
    Etiketin kendisi ZPL olarak yaziciya gidiyor ve barkodu **yazici** uretiyor
    (`^BC` komutu). Ama arayuzde etiketi onizlemek gerekiyor ve onizlemenin
    gercek barkodu gostermesi lazim -- dekoratif cizgiler degil. Harici bir
    kutuphane eklemek yerine standart Code 128-B tablosu buraya kondu; boylece
    hem bagimlilik yok hem de kodlama seffaf.

DURUSTLUK NOTU
    Uretilen SVG, Code 128 spesifikasyonunun standart genislik tablosundan
    ciziliyor ve yapisal olarak dogrulaniyor (modul sayilari, saglama toplami,
    baslangic/bitis desenleri -- bkz. `tests/test_labels.py`). Ancak **fiziksel
    bir okuyucuyla test edilmedi**. Uretimde basilacak barkod her zaman ZPL
    ciktisidir; SVG yalnizca ekran onizlemesidir.
"""

from __future__ import annotations

from typing import Final

#: Code 128 desen tablosu. Her giris alti (bazen yedi) rakamdan olusur ve
#: sirayla cubuk/bosluk genisliklerini (modul cinsinden) verir. Toplam 11 modul
#: (bitis deseni 13).
_PATTERNS: Final[tuple[str, ...]] = (
    "212222",
    "222122",
    "222221",
    "121223",
    "121322",
    "131222",
    "122213",
    "122312",
    "132212",
    "221213",
    "221312",
    "231212",
    "112232",
    "122132",
    "122231",
    "113222",
    "123122",
    "123221",
    "223211",
    "221132",
    "221231",
    "213212",
    "223112",
    "312131",
    "311222",
    "321122",
    "321221",
    "312212",
    "322112",
    "322211",
    "212123",
    "212321",
    "232121",
    "111323",
    "131123",
    "131321",
    "112313",
    "132113",
    "132311",
    "211313",
    "231113",
    "231311",
    "112133",
    "112331",
    "132131",
    "113123",
    "113321",
    "133121",
    "313121",
    "211331",
    "231131",
    "213113",
    "213311",
    "213131",
    "311123",
    "311321",
    "331121",
    "312113",
    "312311",
    "332111",
    "314111",
    "221411",
    "431111",
    "111224",
    "111422",
    "121124",
    "121421",
    "141122",
    "141221",
    "112214",
    "112412",
    "122114",
    "122411",
    "142112",
    "142211",
    "241211",
    "221114",
    "413111",
    "241112",
    "134111",
    "111242",
    "121142",
    "121241",
    "114212",
    "124112",
    "124211",
    "411212",
    "421112",
    "421211",
    "212141",
    "214121",
    "412121",
    "111143",
    "111341",
    "131141",
    "114113",
    "114311",
    "411113",
    "411311",
    "113141",
    "114131",
    "311141",
    "411131",
    "211412",
    "211214",
    "211232",
    "2331112",
)

#: Code Set B baslangic karakterinin deger karsiligi.
START_B: Final[int] = 104

#: Bitis deseni tablonun son girisi.
STOP: Final[int] = 106

#: Code Set B'de kodlanabilen karakter araligi (ASCII 32-126).
_MIN_ORD: Final[int] = 32
_MAX_ORD: Final[int] = 126

#: Barkodun iki yanindaki sessiz alan (modul). Standart en az 10 modul ister.
QUIET_ZONE_MODULES: Final[int] = 10


class BarcodeError(ValueError):
    """Veri Code 128-B ile kodlanamiyor."""


def encode_values(data: str) -> list[int]:
    """Metni Code 128-B deger dizisine cevirir (baslangic, veri, saglama, bitis).

    Saglama toplami: `(baslangic + SUM(i * deger_i)) mod 103`, `i` 1'den baslar.
    """
    if not data:
        raise BarcodeError("Barkod verisi bos olamaz")

    values: list[int] = [START_B]
    for character in data:
        code = ord(character)
        if not _MIN_ORD <= code <= _MAX_ORD:
            raise BarcodeError(f"'{character}' Code 128-B ile kodlanamaz (ASCII 32-126 disinda)")
        values.append(code - _MIN_ORD)

    checksum = START_B
    for index, value in enumerate(values[1:], start=1):
        checksum += index * value
    values.append(checksum % 103)
    values.append(STOP)
    return values


def encode_modules(data: str) -> list[int]:
    """Metni modul genislikleri dizisine cevirir.

    Donen listede tek indisler bosluk, cift indisler cubuk genisligidir
    (0'dan baslayarak cubuk). Toplam modul sayisi
    `11 * (karakter + 3) + 2` olmali.
    """
    widths: list[int] = []
    for value in encode_values(data):
        widths.extend(int(digit) for digit in _PATTERNS[value])
    return widths


def to_svg(
    data: str,
    *,
    module_width: float = 1.6,
    height: float = 54.0,
    show_text: bool = True,
) -> str:
    """Barkodu bagimsiz bir SVG olarak cizer.

    Renk kullanilmaz: barkod siyah-beyaz olmak zorunda. `currentColor` yerine
    sabit siyah tercih edildi -- koyu temada ters cevrilirse okuyucular okuyamaz.
    """
    widths = encode_modules(data)
    total_modules = sum(widths) + 2 * QUIET_ZONE_MODULES
    svg_width = total_modules * module_width
    text_height = 16.0 if show_text else 0.0
    svg_height = height + text_height

    bars: list[str] = []
    position = QUIET_ZONE_MODULES * module_width
    for index, width in enumerate(widths):
        span = width * module_width
        if index % 2 == 0:  # cift indis = cubuk
            bars.append(
                f'<rect x="{position:.2f}" y="0" width="{span:.2f}" '
                f'height="{height:.2f}" fill="#000000"/>'
            )
        position += span

    text = ""
    if show_text:
        text = (
            f'<text x="{svg_width / 2:.2f}" y="{svg_height - 3:.2f}" '
            f'text-anchor="middle" font-family="ui-monospace, monospace" '
            f'font-size="12" fill="#000000" letter-spacing="1.5">{data}</text>'
        )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {svg_width:.2f} '
        f'{svg_height:.2f}" width="{svg_width:.0f}" height="{svg_height:.0f}" '
        f'role="img" aria-label="Barkod {data}">'
        f'<rect width="{svg_width:.2f}" height="{svg_height:.2f}" fill="#ffffff"/>'
        f"{''.join(bars)}{text}</svg>"
    )
