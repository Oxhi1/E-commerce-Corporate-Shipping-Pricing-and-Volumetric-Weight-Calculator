"""Alan sozlugu: sabit kod listeleri.

Turkce degerler (`"havlu"`, `"sehir_ici"`) bilincli bir tercihtir -- veri dosyalari,
API cevaplari ve arayuz etiketleri ayni sozlugu kullansin diye. Tanimlayici adlar
(sinif ve uye adlari) Ingilizcedir.
"""

from __future__ import annotations

from enum import StrEnum


class CarrierCode(StrEnum):
    """Simulasyonda yaristirilan kargo firmalari."""

    ARAS = "ARAS"
    MNG = "MNG"
    YURTICI = "YURTICI"
    SURAT = "SURAT"
    PTT = "PTT"


class ZoneClass(StrEnum):
    """Tarife bolge sinifi. Fiyat matrisinin sutun eksenidir."""

    SEHIR_ICI = "sehir_ici"
    BOLGE_ICI = "bolge_ici"
    BOLGELER_ARASI = "bolgeler_arasi"
    UZAK = "uzak"


class Region(StrEnum):
    """Cografi bolge -- `ZoneClass` turetmek ve risk modelinde kirilim icin."""

    MARMARA = "marmara"
    EGE = "ege"
    AKDENIZ = "akdeniz"
    IC_ANADOLU = "ic_anadolu"
    KARADENIZ = "karadeniz"
    DOGU_ANADOLU = "dogu_anadolu"
    GUNEYDOGU_ANADOLU = "guneydogu_anadolu"


class ProductCategory(StrEnum):
    """Katalog kirilimi. Insan tarafindan okunur; risk modeli bunu kullanmaz."""

    TOWEL = "havlu"
    BEDDING = "nevresim"
    BATHROBE = "bornoz"
    BLANKET = "battaniye"
    CURTAIN = "perde"
    HOME_DECOR = "ev_dekor"
    KITCHENWARE = "mutfak"
    DETERGENT = "deterjan"
    FOOD_LIQUID = "gida_sivi"
    PERSONAL_CARE = "kisisel_bakim"
    SMALL_APPLIANCE = "kucuk_ev_aleti"


class RiskCategory(StrEnum):
    """Risk modelinin kirilimi -- kasitli olarak kaba.

    `ProductCategory` 11 degerli; onu dogrudan risk hucresi olarak kullanmak
    (firma x bolge x kategori) = 5 x 4 x 11 = 220 hucre demek olurdu ve cogu bos
    kalirdi. 4 risk sinifina indirgeyerek hucre basina dusen veriyi ~3 katina
    cikariyoruz. Bkz. docs/01-matematiksel-model.md
    """

    SOFT = "yumusak"  # tekstil: dayanikli, ezilir ama bozulmaz
    FRAGILE = "kirilabilir"  # cam, porselen, seramik
    LIQUID = "sivi"  # sizinti riski -- yan hasar kaynagi
    APPLIANCE = "cihaz"  # kucuk ev aleti: darbeye hassas, degerli


class Fragility(StrEnum):
    """Paketleme dolgu payini ve hasar siddetini belirler."""

    NONE = "yok"
    LOW = "dusuk"
    MEDIUM = "orta"
    HIGH = "yuksek"


class RoundingRule(StrEnum):
    """Ucretli desiye yuvarlama kurali. Firma sozlesmesine gore degisir.

    Kademe sinirinda bu kural tek basina fiyati degistirir; bu yuzden motorda
    sabit degil, tarife dosyasinda konfigure edilir.
    """

    CEIL = "ceil"  # yukari yuvarla (en yaygin)
    HALF_UP = "half_up"  # en yakina, 0.5 yukari
    NONE = "none"  # yuvarlama yok


class TariffSourceKind(StrEnum):
    """Tarifenin sentetik mi gercek sozlesme mi oldugunu isaretler.

    Arayuzde rozet olarak gosterilir. Uydurma fiyatlarin gercek sozlesme fiyati
    sanilmasi ciddi bir yanlis anlasilma riski oldugu icin bu alan zorunludur.
    """

    SYNTHETIC = "synthetic"
    CONTRACT = "contract"


class PolicyCode(StrEnum):
    """Monte Carlo'da yaristirilan karar politikalari."""

    P0_SINGLE_CARRIER = "P0"  # tek firma -- mevcut durum, baz cizgi
    P1_CHEAPEST_FREIGHT = "P1"  # en ucuz nakliye
    P2_FASTEST = "P2"  # en hizli teslimat
    P3_TELC = "P3"  # beklenen toplam sahiplenme maliyeti (bu motor)
    P4_TELC_CONSTRAINED = "P4"  # TELC + kapasite/taahhut kisitlari
