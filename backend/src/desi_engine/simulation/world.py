"""Simulasyonun "gercek dunyasi" -- motorun **bilmedigi** dogru parametreler.

Bu ayrim projenin metodolojik omurgasi. `TrueWorld` her firmanin her bolgedeki
gercek hasar olasiligini ve gercek teslimat suresi dagilimini tutar. Karar motoru
bu nesneye asla erisemez; yalnizca ondan uretilmis **gozlenmis gecmis veriyi**
gorur ve parametreleri oradan tahmin eder.

Bu ayrim olmasaydi simulasyon kendi cevabini kopyalardi: motor gercek hasar
oranini bilseydi her zaman dogru firmayi secerdi ve "%X tasarruf" sonucu, modelin
degil kurgunun eseri olurdu. Ayrim sayesinde motor da gercek hayattaki gibi
belirsizlikle calisiyor -- az veriye sahip oldugu hucrelerde yanilabiliyor.

Buradaki sayilar sentetiktir ama buyukluk mertebeleri sektor gozlemlerine yakin
tutulmustur (kargo hasar oranlari tipik olarak binde 3 ile yuzde 2 arasinda).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

import numpy as np

from ..domain.enums import CarrierCode, RiskCategory, ZoneClass

#: Firma bazli taban hasar orani (bolgeler_arasi, yumusak tekstil referansi).
#: Fiyat siralamasiyla ters iliski kasitli: ucuz firma daha cok hasar yapar.
BASE_DAMAGE_RATE: Final[dict[CarrierCode, float]] = {
    CarrierCode.YURTICI: 0.0035,
    CarrierCode.ARAS: 0.0060,
    CarrierCode.PTT: 0.0080,
    CarrierCode.MNG: 0.0100,
    CarrierCode.SURAT: 0.0170,
}

#: Bolge carpani: uzun mesafe = daha cok aktarma = daha cok hasar.
ZONE_DAMAGE_FACTOR: Final[dict[ZoneClass, float]] = {
    ZoneClass.SEHIR_ICI: 0.70,
    ZoneClass.BOLGE_ICI: 0.85,
    ZoneClass.BOLGELER_ARASI: 1.00,
    ZoneClass.UZAK: 1.80,
}

#: Urun tipi carpani.
CATEGORY_DAMAGE_FACTOR: Final[dict[RiskCategory, float]] = {
    RiskCategory.SOFT: 0.50,
    RiskCategory.APPLIANCE: 1.40,
    RiskCategory.LIQUID: 1.90,
    RiskCategory.FRAGILE: 2.40,
}

#: Firmaya ozgu bolgesel zayifliklar -- karar motorunun kesfetmesi gereken asil
#: yapi bu. Duz carpanlar olsaydi "hep en iyi firmayi sec" yeterdi; bu terimler
#: sayesinde dogru cevap bolgeye ve urune gore degisiyor.
CARRIER_ZONE_QUIRK: Final[dict[tuple[CarrierCode, ZoneClass], float]] = {
    # MNG dogu illerinde belirgin sekilde kotu -- ucuzluguna ragmen kacinilmali.
    (CarrierCode.MNG, ZoneClass.UZAK): 1.90,
    # Surat sehir ici dagitimda aslinda fena degil; zayifligi uzun mesafede.
    (CarrierCode.SURAT, ZoneClass.SEHIR_ICI): 0.55,
    (CarrierCode.SURAT, ZoneClass.UZAK): 1.45,
    # PTT uzak bolgelerde guclu: kendi sube agi var, aktarma sayisi dusuk.
    (CarrierCode.PTT, ZoneClass.UZAK): 0.60,
    # Yurtici sehir ici kurye agiyla neredeyse hatasiz.
    (CarrierCode.YURTICI, ZoneClass.SEHIR_ICI): 0.50,
}

#: Firmanin kendi SLA vaadini tutma orani (bolgeler_arasi referansi).
#:
#: Dagilim bu orandan **turetilir**, tersi degil. Onceki surumde "medyan =
#: vaat x hiz_katsayisi" kullaniliyordu; 1 gunluk vaatlerde medyan 1'in altina
#: dusuyor, ornekler `max(deger, 1.0)` ile kirpiliyor ve dagilim tam 1.0'da
#: yigiliyordu. Kirpilmis veriye uydurulan log-normal mu'yu yukari itip her firma
#: icin %80 gecikme olasiligi uretiyordu -- gercekci degil.
#:
#: Bu parametrizasyon hem daha dogru hem de lojistik yoneticisinin dogrudan
#: dogrulayabilecegi bir sayi: "Aras sehir ici gonderilerin yuzde kacini
#: zamaninda teslim ediyor?"
CARRIER_ON_TIME_RATE: Final[dict[CarrierCode, float]] = {
    CarrierCode.YURTICI: 0.93,
    CarrierCode.ARAS: 0.88,
    CarrierCode.MNG: 0.80,
    CarrierCode.PTT: 0.68,
    CarrierCode.SURAT: 0.62,
}

#: Bolgeye gore **gecikme orani** carpani (basari degil, basarisizlik olceklenir).
ZONE_LATE_FACTOR: Final[dict[ZoneClass, float]] = {
    ZoneClass.SEHIR_ICI: 0.80,
    ZoneClass.BOLGE_ICI: 0.90,
    ZoneClass.BOLGELER_ARASI: 1.00,
    ZoneClass.UZAK: 1.60,
}

#: Firmaya ozgu bolgesel hiz avantajlari -- `CARRIER_ZONE_QUIRK`'in hiz karsiligi.
#:
#: Bu tablo olmadan ucuz firmalar (Surat, PTT) hicbir bolgede guclu olmuyor ve
#: karar motoru en ucuz nakliyeyi neredeyse her zaman reddediyordu. Gercek hayatta
#: boyle degil: ucuz bir firma, kendi guclu oldugu koridorda hem ucuz hem iyidir.
#: Bu terimler olmadan "her zaman pahali olani sec" kurali motorla ayni sonucu
#: verirdi ve proje bir sey ogretmezdi.
CARRIER_ZONE_SPEED_QUIRK: Final[dict[tuple[CarrierCode, ZoneClass], float]] = {
    # PTT uzak bolgelerde kendi sube agini kullaniyor: aktarma yok, gecikme az.
    # Hasar tarafindaki gucuyle ayni sebep.
    (CarrierCode.PTT, ZoneClass.UZAK): 0.45,
    # Surat sehir ici kurye agi guclu -- zayifligi uzun mesafede ortaya cikiyor.
    (CarrierCode.SURAT, ZoneClass.SEHIR_ICI): 0.50,
    (CarrierCode.SURAT, ZoneClass.BOLGE_ICI): 0.75,
    # MNG sehir ici dagitimda iddiali.
    (CarrierCode.MNG, ZoneClass.SEHIR_ICI): 0.70,
    # Yurtici uzak bolgelerde avantajini kaybediyor: oralarda kendi agi yok.
    (CarrierCode.YURTICI, ZoneClass.UZAK): 1.35,
}

RURAL_LATE_FACTOR: Final[float] = 1.50

#: Teslimat suresi dagiliminin log-olcekli standart sapmasi (degiskenlik).
CARRIER_TIME_SIGMA: Final[dict[CarrierCode, float]] = {
    CarrierCode.YURTICI: 0.22,
    CarrierCode.ARAS: 0.28,
    CarrierCode.MNG: 0.34,
    CarrierCode.PTT: 0.42,
    CarrierCode.SURAT: 0.45,
}

#: Uzak ve kirsal teslimatlarda degiskenlik artar -- kuyruk kalinlasir.
ZONE_SIGMA_PENALTY: Final[dict[ZoneClass, float]] = {
    ZoneClass.SEHIR_ICI: 0.00,
    ZoneClass.BOLGE_ICI: 0.03,
    ZoneClass.BOLGELER_ARASI: 0.08,
    ZoneClass.UZAK: 0.18,
}

RURAL_SIGMA_PENALTY: Final[float] = 0.12

#: Gecikme oraninin alt ve ust siniri. %0 gecikme gercekci degil (hicbir firma
#: kusursuz degildir), %85 ustu ise o firmayla hic calisilmayacagi anlamina gelir.
MIN_LATE_RATE: Final[float] = 0.02
MAX_LATE_RATE: Final[float] = 0.85


@dataclass(frozen=True, slots=True)
class DeliveryDistribution:
    """Teslimat suresinin log-normal dagilimi (gun cinsinden, surekli).

    `T` **surekli** transit suresidir; gonderi `ceil(T)`. gunde teslim edilir.
    Dolayisiyla `T = 0.7` "vaat edilen ilk gun icinde teslim" demektir ve
    `T > vaat` tam olarak "gec kaldi" anlamina gelir. Bu tanim sayesinde
    kirpmaya gerek kalmiyor ve dagilim temiz kaliyor.
    """

    mu: float
    sigma: float

    @classmethod
    def from_on_time_rate(
        cls, promised_days: float, on_time_rate: float, sigma: float
    ) -> DeliveryDistribution:
        """Vaat + hedeflenen zamaninda teslim oranindan dagilimi kurar.

        `P(T <= vaat) = hedef` kosulundan:
            (ln(vaat) - mu) / sigma = Phi^-1(hedef)
            mu = ln(vaat) - sigma * Phi^-1(hedef)
        """
        z = float(_standard_normal_ppf(on_time_rate))
        return cls(mu=float(np.log(promised_days) - sigma * z), sigma=sigma)

    @property
    def median_days(self) -> float:
        return float(np.exp(self.mu))

    @property
    def mean_days(self) -> float:
        return float(np.exp(self.mu + self.sigma**2 / 2))

    def probability_late(self, promised_days: float) -> float:
        """Kurulusta hedeflenen orani geri verir -- tutarlilik denetimi icin."""
        from scipy.stats import norm

        return float(norm.sf((np.log(promised_days) - self.mu) / self.sigma))

    def sample(self, rng: np.random.Generator, size: int | None = None) -> float | np.ndarray:
        return rng.lognormal(mean=self.mu, sigma=self.sigma, size=size)


def _standard_normal_ppf(probability: float) -> float:
    from scipy.stats import norm

    return float(norm.ppf(probability))


class TrueWorld:
    """Gercek -- ama motora kapali -- dunya parametreleri."""

    def __init__(self, sla_lookup: dict[tuple[CarrierCode, ZoneClass, bool], int]) -> None:
        """`sla_lookup`: `(firma, bolge, kirsal_mi)` -> vaat edilen gun.

        Anahtarda **kirsallik da bulunmak zorunda**. Ilk surumde yalnizca
        `(firma, bolge)` vardi ve kirsal teslimat taban SLA'ya gore kuruluyordu;
        oysa gecmis veriye kirsalin +1 gunluk vaadi yaziliyordu. Sonuc tersine
        donuyordu: kirsal gonderiler ayni surede teslim edilip daha genis bir
        vaatle olculdugu icin *daha az* gecikmis gorunuyordu. Kirsal teslimatin
        hem daha yavas hem daha degisken olmasi gerekiyor.
        """
        self._sla = sla_lookup

    @classmethod
    def from_tariffs(cls, tariffs) -> TrueWorld:
        """Tarife deposundan tam SLA tablosunu (kirsal dahil) kurar."""
        return cls(
            {
                (tariff.carrier, zone, is_rural): tariff.service.promised_days(
                    zone, is_rural=is_rural
                )
                for tariff in tariffs
                for zone in ZoneClass
                for is_rural in (False, True)
            }
        )

    # ---- hasar --------------------------------------------------------------

    def damage_rate(self, carrier: CarrierCode, zone: ZoneClass, category: RiskCategory) -> float:
        """Bir gonderinin hasar gorme olasiligi (gercek deger).

        Carpimsal model: taban x bolge x kategori x firmaya-ozgu-sapma.
        """
        rate = (
            BASE_DAMAGE_RATE[carrier]
            * ZONE_DAMAGE_FACTOR[zone]
            * CATEGORY_DAMAGE_FACTOR[category]
            * CARRIER_ZONE_QUIRK.get((carrier, zone), 1.0)
        )
        return min(rate, 0.35)

    def sample_damage(
        self,
        carrier: CarrierCode,
        zone: ZoneClass,
        category: RiskCategory,
        rng: np.random.Generator,
    ) -> bool:
        return bool(rng.random() < self.damage_rate(carrier, zone, category))

    # ---- teslimat suresi ----------------------------------------------------

    def on_time_rate(
        self, carrier: CarrierCode, zone: ZoneClass, *, is_rural: bool = False
    ) -> float:
        """Firmanin bu bolgede vaadini tutma orani.

        Bolge ve kirsallik, basari oranini degil **gecikme oranini** olcekler:
        %93 basarili bir firma uzak bolgede %88.8'e duser (gecikme %7 -> %11.2),
        %62 basarili bir firma %39.2'ye. Basari oranini dogrudan olceklemek
        kotu firmalari yeterince cezalandirmazdi.
        """
        late_rate = 1.0 - CARRIER_ON_TIME_RATE[carrier]
        late_rate *= ZONE_LATE_FACTOR[zone]
        late_rate *= CARRIER_ZONE_SPEED_QUIRK.get((carrier, zone), 1.0)
        if is_rural:
            late_rate *= RURAL_LATE_FACTOR
        return 1.0 - min(max(late_rate, MIN_LATE_RATE), MAX_LATE_RATE)

    def delivery_distribution(
        self, carrier: CarrierCode, zone: ZoneClass, *, is_rural: bool = False
    ) -> DeliveryDistribution:
        promised = self._sla[(carrier, zone, is_rural)]
        sigma = CARRIER_TIME_SIGMA[carrier] + ZONE_SIGMA_PENALTY[zone]
        if is_rural:
            sigma += RURAL_SIGMA_PENALTY
        return DeliveryDistribution.from_on_time_rate(
            promised_days=promised,
            on_time_rate=self.on_time_rate(carrier, zone, is_rural=is_rural),
            sigma=sigma,
        )

    def sample_delivery_days(
        self,
        carrier: CarrierCode,
        zone: ZoneClass,
        rng: np.random.Generator,
        *,
        is_rural: bool = False,
    ) -> float:
        return float(self.delivery_distribution(carrier, zone, is_rural=is_rural).sample(rng))

    # ---- tanilama -----------------------------------------------------------

    def damage_rate_table(self) -> dict[tuple[str, str, str], float]:
        """Tum gercek hasar oranlari -- yalnizca kalibrasyon raporu icin.

        Karar motoru bu tabloyu asla cagirmaz; simulasyon sonunda motorun
        tahminlerinin gercege ne kadar yakin oldugunu olcmek icin kullanilir.
        """
        return {
            (carrier.value, zone.value, category.value): self.damage_rate(carrier, zone, category)
            for carrier in CarrierCode
            for zone in ZoneClass
            for category in RiskCategory
        }


@dataclass(frozen=True, slots=True)
class HistoricalMix:
    """Gecmiste hangi firmaya ne kadar is verildigi.

    Kasitli olarak **dengesiz**: sirket bugune kadar agirlikli olarak ARAS ve MNG
    kullanmis. Sonuc olarak SURAT x uzak x kirilabilir gibi hucrelerde elde bir
    avuc gonderi var. Bayesci shrinkage tam olarak bu durum icin gerekli --
    dengeli bir veri setinde ham oranlar da is gorurdu ve model gereksiz gorunurdu.
    """

    weights: dict[CarrierCode, float] = field(
        default_factory=lambda: {
            CarrierCode.ARAS: 0.45,
            CarrierCode.MNG: 0.25,
            CarrierCode.YURTICI: 0.15,
            CarrierCode.SURAT: 0.10,
            CarrierCode.PTT: 0.05,
        }
    )

    def probabilities(self) -> tuple[list[CarrierCode], np.ndarray]:
        carriers = list(self.weights)
        probs = np.array([self.weights[c] for c in carriers], dtype=float)
        return carriers, probs / probs.sum()
