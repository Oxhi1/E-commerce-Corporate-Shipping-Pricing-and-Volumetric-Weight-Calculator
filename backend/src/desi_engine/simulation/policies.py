"""Yaristirilan kargo secim politikalari.

Hepsi ayni girdi uzerinde calisir: bir siparis icin onceden hesaplanmis
`CarrierEvaluation` listesi. Boylece politikalar arasindaki tek fark **secim
kurali** olur -- fiyatlama, paketleme veya risk hesabi degil. Aksi halde "P3 daha
iyi" sonucu, karar kuralindan mi yoksa farkli bir hesaplamadan mi geldigi
anlasilamazdi.

    P0  Tek firma            mevcut durum, baz cizgi
    P1  En ucuz nakliye      "faturaya bak" kurali -- en yaygin pratik
    P2  En hizli teslimat    musteri memnuniyeti odakli uc nokta
    P3  TELC                 bu motor: beklenen toplam sahiplenme maliyeti
    P4  TELC + kapasite      gunluk alim limitleri dikkate alinmis hali
"""

from __future__ import annotations

from typing import Protocol

from ..decision.constraints import CapacityLedger
from ..decision.explain import CarrierEvaluation
from ..domain.enums import CarrierCode, PolicyCode


class Policy(Protocol):
    """Bir secim kurali."""

    code: PolicyCode
    label: str

    def choose(
        self, evaluations: list[CarrierEvaluation], ledger: CapacityLedger | None
    ) -> CarrierEvaluation | None:
        """Uygun adaylar arasindan birini secer. Hicbiri uygun degilse `None`."""
        ...


def _eligible(
    evaluations: list[CarrierEvaluation], ledger: CapacityLedger | None
) -> list[CarrierEvaluation]:
    """Kisitlardan gecen adaylar.

    Kapasite, maliyetleri degistirmedigi icin degerlendirme asamasinda degil
    burada uygulanir: ayni degerlendirme seti tum politikalarda yeniden kullanilir.
    """
    candidates = [e for e in evaluations if e.eligible]
    if ledger is None:
        return candidates
    return [e for e in candidates if ledger.has_room(CarrierCode(e.carrier), e.parcel_count)]


class SingleCarrierPolicy:
    """P0 -- her seyi tek firmaya ver. Sirketin bugunku hali.

    Tercih edilen firma o siparis icin uygun degilse (hizmet vermedigi bir il,
    asilan desi siniri) en ucuz uygun alternatife duser. Gercek hayatta da boyle
    olur: operasyon o gonderiyi bir sekilde yola cikarmak zorundadir.
    """

    code = PolicyCode.P0_SINGLE_CARRIER

    def __init__(self, carrier: CarrierCode = CarrierCode.ARAS) -> None:
        self.carrier = carrier
        self.label = f"Tek firma ({carrier.value})"

    def choose(self, evaluations, ledger):
        candidates = _eligible(evaluations, ledger)
        if not candidates:
            return None
        preferred = [e for e in candidates if e.carrier == self.carrier.value]
        if preferred:
            return preferred[0]
        return min(candidates, key=lambda e: e.freight_try)


class CheapestFreightPolicy:
    """P1 -- en dusuk nakliye faturasi. "Faturaya bak" kurali.

    Projenin asil rakibi bu. Yaygin, savunulmasi kolay ve gorunurde mantikli;
    motorun asmasi gereken cita.
    """

    code = PolicyCode.P1_CHEAPEST_FREIGHT
    label = "En ucuz nakliye"

    def choose(self, evaluations, ledger):
        candidates = _eligible(evaluations, ledger)
        return min(candidates, key=lambda e: e.freight_try) if candidates else None


class FastestPolicy:
    """P2 -- en dusuk beklenen teslimat suresi. Maliyete hic bakmaz.

    Ust sinir olarak duruyor: musteri memnuniyetini tek olcut alan bir isletmenin
    ne odeyecegini gosterir.
    """

    code = PolicyCode.P2_FASTEST
    label = "En hizli teslimat"

    def choose(self, evaluations, ledger):
        candidates = [e for e in _eligible(evaluations, ledger) if e.delay]
        if not candidates:
            return None
        return min(candidates, key=lambda e: e.delay.expected_days)


class TotalCostPolicy:
    """P3 -- beklenen toplam sahiplenme maliyeti. Bu motor."""

    code = PolicyCode.P3_TELC
    label = "Toplam maliyet (TELC)"

    def choose(self, evaluations, ledger):
        candidates = _eligible(evaluations, ledger)
        return min(candidates, key=lambda e: e.score_try) if candidates else None


class ConstrainedTotalCostPolicy:
    """P4 -- TELC + gunluk kapasite limitleri.

    P3 ile arasindaki fark, kapasiteyi yok saymanin maliyetini olcer: P3 tum
    gonderileri en iyi firmaya yigar, gercek hayatta o firma "bugunluk yeter" der.
    """

    code = PolicyCode.P4_TELC_CONSTRAINED
    label = "TELC + kapasite kisiti"

    def choose(self, evaluations, ledger):
        candidates = _eligible(evaluations, ledger)
        return min(candidates, key=lambda e: e.score_try) if candidates else None


def default_policies(single_carrier: CarrierCode = CarrierCode.ARAS) -> list[Policy]:
    """Raporda karsilastirilan standart politika seti."""
    return [
        SingleCarrierPolicy(single_carrier),
        CheapestFreightPolicy(),
        FastestPolicy(),
        TotalCostPolicy(),
        ConstrainedTotalCostPolicy(),
    ]
