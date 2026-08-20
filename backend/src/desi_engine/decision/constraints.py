"""Uygunluk kisitlari -- `K_uygun` kumesini belirler.

Maliyet karsilastirmasi ancak **uygulanabilir** secenekler arasinda anlamlidir.
Hakkari'ye 40 TL'ye gonderdigini iddia eden bir firma, oraya hic gitmiyorsa
karsilastirmaya girmemeli; girerse motor her seferinde onu secer ve depoda
elle duzeltilir -- sistemin guvenilirligi orada biter.

Elenen firmalar sessizce atilmaz; her elemenin makine-okunur bir gerekcesi olur
ve arayuzde "neden bu firma listede yok" sorusuna cevap verir.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import time
from enum import StrEnum

from ..domain.enums import CarrierCode
from ..domain.models import Order
from ..packing.packer import PackingPlan
from ..tariff.schema import Tariff


class Ineligibility(StrEnum):
    """Bir firmanin neden degerlendirmeye alinamadigi."""

    UNSERVED_CITY = "il_hizmet_disi"
    COD_UNSUPPORTED = "kapida_odeme_desteklenmiyor"
    PARCEL_DESI_LIMIT = "parca_desi_siniri_asildi"
    DAILY_CAPACITY = "gunluk_kapasite_dolu"
    CUTOFF_MISSED = "cikis_saati_gecti"


#: Insan tarafindan okunur aciklamalar -- arayuzde ve karar gerekcesinde kullanilir.
INELIGIBILITY_LABELS: dict[Ineligibility, str] = {
    Ineligibility.UNSERVED_CITY: "Bu ile hizmet vermiyor",
    Ineligibility.COD_UNSUPPORTED: "Kapida odeme desteklemiyor",
    Ineligibility.PARCEL_DESI_LIMIT: "Koli, firmanin parca basi desi sinirini asiyor",
    Ineligibility.DAILY_CAPACITY: "Bugunku kapasitesi dolu",
    Ineligibility.CUTOFF_MISSED: "Bugunku son cikis saati gecti",
}


@dataclass(frozen=True, slots=True)
class Eligibility:
    """Bir firmanin bu siparis icin uygunluk sonucu."""

    carrier: CarrierCode
    reasons: tuple[Ineligibility, ...] = ()

    @property
    def is_eligible(self) -> bool:
        return not self.reasons

    def describe(self) -> str:
        if self.is_eligible:
            return "Uygun"
        return "; ".join(INELIGIBILITY_LABELS[reason] for reason in self.reasons)


@dataclass
class CapacityLedger:
    """Gun icinde firmalara verilen gonderi sayisini tutar.

    Gercek hayatta kargo firmalarinin gunluk alim kapasitesi vardir; motor tum
    gonderileri en iyi firmaya yiginca o firma "bugunluk yeter" der. P4
    politikasi bu kisiti dikkate alir, P3 almaz -- ikisi arasindaki fark,
    kapasiteyi yok saymanin maliyetini gosterir.

    Kapasite tanimlanmamis bir firma sinirsiz kabul eder.
    """

    daily_limits: dict[CarrierCode, int] = field(default_factory=dict)
    _used: dict[CarrierCode, int] = field(default_factory=lambda: defaultdict(int))

    def remaining(self, carrier: CarrierCode) -> int | None:
        limit = self.daily_limits.get(carrier)
        if limit is None:
            return None
        return max(0, limit - self._used[carrier])

    def has_room(self, carrier: CarrierCode, parcels: int = 1) -> bool:
        remaining = self.remaining(carrier)
        return remaining is None or remaining >= parcels

    def consume(self, carrier: CarrierCode, parcels: int = 1) -> None:
        self._used[carrier] += parcels

    def reset(self) -> None:
        self._used.clear()

    @property
    def usage(self) -> dict[CarrierCode, int]:
        return dict(self._used)


def check_eligibility(
    tariff: Tariff,
    order: Order,
    plan: PackingPlan,
    *,
    ledger: CapacityLedger | None = None,
    order_time: time | None = None,
) -> Eligibility:
    """Bir firmanin bu siparis + koli plani icin uygunlugunu denetler.

    Uygunluk **plana baglidir**: PTT parca basina 50 desi kabul ediyorsa, tek
    koliye sikistirilmis 60 desilik bir plan icin uygun degildir ama iki koliye
    bolunmus ayni sepet icin uygundur. Bu yuzden denetim her (firma, plan)
    ciftinde ayri ayri yapilir.
    """
    reasons: list[Ineligibility] = []

    if not tariff.serves(order.address.city_plate):
        reasons.append(Ineligibility.UNSERVED_CITY)

    if order.is_cod and not tariff.constraints.cod_supported:
        reasons.append(Ineligibility.COD_UNSUPPORTED)

    if plan.max_parcel_desi > tariff.constraints.max_desi_per_parcel:
        reasons.append(Ineligibility.PARCEL_DESI_LIMIT)

    if ledger is not None and not ledger.has_room(tariff.carrier, plan.parcel_count):
        reasons.append(Ineligibility.DAILY_CAPACITY)

    if order_time is not None and order_time > _parse_cutoff(tariff.service.cutoff):
        reasons.append(Ineligibility.CUTOFF_MISSED)

    return Eligibility(carrier=tariff.carrier, reasons=tuple(reasons))


def _parse_cutoff(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))
