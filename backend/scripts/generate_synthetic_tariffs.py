"""Sentetik kargo tarife dosyalarini uretir -> `data/carriers/*.yaml`.

Neden script?
    5 firma x 15 desi kademesi x 4 bolge = 300 fiyat. Elle yazmak hem hataya acik
    hem de "MNG'yi %3 ucuzlatalim, sonuc ne olur" gibi bir duyarlilik denemesini
    imkansiz kilar. Fiyatlar burada birkac parametreden deterministik uretilir;
    uretilen YAML dosyalari yine de elle duzenlenebilir dosyalardir.

Fiyat modeli (desi -> ucret):
    P(d, z) = base[z] + slope[z] * (d - 1) ** gamma

`gamma < 1` olcek ekonomisini temsil eder: 20 desilik bir koli, 1 desilik yirmi
kolinin toplamindan cok daha ucuzdur.

DIKKAT: Uretilen tum dosyalar `source: synthetic` tasir. Bunlar gercek Ozdilek
sozlesme fiyatlari DEGILDIR; buyukluk mertebesi gercekcidir, rakamlar uydurmadir.

Kullanim:
    python scripts/generate_synthetic_tariffs.py
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "carriers"

#: Tarife tablosunun desi kademeleri. Ustu `over_30_per_desi` ile fiyatlanir.
DESI_TIERS: list[int] = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 20, 25, 30]

ZONES: list[str] = ["sehir_ici", "bolge_ici", "bolgeler_arasi", "uzak"]

#: Olcek ekonomisi ussu. 1.0 = dogrusal fiyat, <1 = buyuk kolide birim fiyat duser.
GAMMA: float = 0.88


@dataclass(frozen=True)
class CarrierProfile:
    """Bir firmanin tarifesini ureten kompakt parametre seti."""

    code: str
    display_name: str
    price_index: float  # ARAS = 1.00 referansli genel fiyat seviyesi
    rounding: str
    min_charge: float
    fuel_pct: float
    cod_fee: float
    insurance_free_limit: float
    insurance_pct_above: float
    sla_days: dict[str, int]
    max_desi_per_parcel: int
    cutoff: str
    unserved_plates: list[int] = field(default_factory=list)
    volume_discounts: list[dict[str, float]] = field(default_factory=list)
    note: str = ""


#: ARAS referans alinarak kurulmus taban fiyat ve egimler (1 desi, TL, KDV haric).
BASE_TRY: dict[str, float] = {
    "sehir_ici": 68.00,
    "bolge_ici": 76.00,
    "bolgeler_arasi": 88.00,
    "uzak": 99.00,
}
SLOPE_TRY: dict[str, float] = {
    "sehir_ici": 6.20,
    "bolge_ici": 7.40,
    "bolgeler_arasi": 9.00,
    "uzak": 11.00,
}

# Firmalar bilincli olarak farkli takas noktalarina yerlestirildi; aksi halde
# karar motorunun secmesi gereken bir sey kalmazdi:
#   SURAT  -> en ucuz, ama yavas, hasarli ve dogu illerine hizmet vermiyor
#   YURTICI-> en pahali, ama en hizli ve en dusuk hasar
#   PTT    -> ucuz ve her yere gidiyor, ama yavas ve parca basi 50 desi siniri var
#   MNG    -> ucuza yakin, orta hiz, doguda hasar orani yuksek
#   ARAS   -> her metrikte ortada, guvenli varsayilan
CARRIERS: list[CarrierProfile] = [
    CarrierProfile(
        code="ARAS",
        display_name="Aras Kargo",
        price_index=1.00,
        rounding="ceil",
        min_charge=79.90,
        fuel_pct=0.085,
        cod_fee=24.00,
        insurance_free_limit=500.0,
        insurance_pct_above=0.004,
        sla_days={"sehir_ici": 1, "bolge_ici": 2, "bolgeler_arasi": 3, "uzak": 4},
        max_desi_per_parcel=100,
        cutoff="17:00",
        volume_discounts=[
            {"monthly_parcels_gte": 5000, "pct": 0.06},
            {"monthly_parcels_gte": 10000, "pct": 0.09},
        ],
        note="Dengeli profil; guvenli varsayilan.",
    ),
    CarrierProfile(
        code="MNG",
        display_name="MNG Kargo",
        price_index=0.92,
        rounding="ceil",
        min_charge=72.50,
        fuel_pct=0.095,
        cod_fee=27.00,
        insurance_free_limit=300.0,
        insurance_pct_above=0.005,
        sla_days={"sehir_ici": 1, "bolge_ici": 2, "bolgeler_arasi": 3, "uzak": 5},
        max_desi_per_parcel=120,
        cutoff="16:30",
        volume_discounts=[
            {"monthly_parcels_gte": 5000, "pct": 0.07},
            {"monthly_parcels_gte": 12000, "pct": 0.11},
        ],
        note="Ucuz ve genis kapasiteli; dogu bolgelerinde hasar orani yuksek.",
    ),
    CarrierProfile(
        code="YURTICI",
        display_name="Yurtici Kargo",
        price_index=1.12,
        rounding="half_up",
        min_charge=89.90,
        fuel_pct=0.075,
        cod_fee=22.00,
        insurance_free_limit=1000.0,
        insurance_pct_above=0.003,
        sla_days={"sehir_ici": 1, "bolge_ici": 2, "bolgeler_arasi": 2, "uzak": 3},
        max_desi_per_parcel=100,
        cutoff="17:30",
        volume_discounts=[
            {"monthly_parcels_gte": 4000, "pct": 0.05},
            {"monthly_parcels_gte": 9000, "pct": 0.08},
        ],
        note="En pahali, en hizli, en dusuk hasar. Degerli/kirilgan sepetlerin adayi.",
    ),
    CarrierProfile(
        code="SURAT",
        display_name="Surat Kargo",
        price_index=0.85,
        rounding="ceil",
        min_charge=66.00,
        fuel_pct=0.110,
        cod_fee=30.00,
        insurance_free_limit=250.0,
        insurance_pct_above=0.006,
        sla_days={"sehir_ici": 2, "bolge_ici": 3, "bolgeler_arasi": 4, "uzak": 6},
        max_desi_per_parcel=80,
        cutoff="16:00",
        # Uzak dogu illeri: Hakkari, Sirnak, Ardahan, Igdir, Bayburt, Tunceli
        unserved_plates=[30, 73, 75, 76, 69, 62],
        volume_discounts=[
            {"monthly_parcels_gte": 6000, "pct": 0.08},
            {"monthly_parcels_gte": 15000, "pct": 0.13},
        ],
        note="En ucuz teklif. Yavas, hasarli ve 6 ile hic hizmet vermiyor.",
    ),
    CarrierProfile(
        code="PTT",
        display_name="PTT Kargo",
        price_index=0.88,
        rounding="ceil",
        min_charge=69.00,
        fuel_pct=0.060,
        cod_fee=18.00,
        insurance_free_limit=500.0,
        insurance_pct_above=0.0035,
        sla_days={"sehir_ici": 2, "bolge_ici": 3, "bolgeler_arasi": 5, "uzak": 7},
        max_desi_per_parcel=50,
        cutoff="15:30",
        volume_discounts=[{"monthly_parcels_gte": 8000, "pct": 0.04}],
        note="Her yere gider (81 il, koy dahil) ama yavas ve parca basi 50 desi siniri var.",
    ),
]


def tier_price(desi: int, zone: str, index: float) -> float:
    """`P(d, z) = base + slope * (d-1)^gamma`, firma indeksiyle olceklenmis."""
    raw = BASE_TRY[zone] + SLOPE_TRY[zone] * ((desi - 1) ** GAMMA)
    return _to_pretty_price(raw * index)


def _to_pretty_price(value: float) -> float:
    """Gercek tarifelerdeki gibi 0.50 / 0.90 biten sayilara oturtur."""
    whole = math.floor(value)
    frac = value - whole
    if frac < 0.25:
        return whole + 0.00
    if frac < 0.70:
        return whole + 0.50
    return whole + 0.90


def build_tariff(profile: CarrierProfile) -> dict:
    """Bir firmanin tam tarife sozlugunu (YAML'e yazilacak yapiyi) uretir."""
    tiers = [
        {
            "up_to": desi,
            "zones": {zone: tier_price(desi, zone, profile.price_index) for zone in ZONES},
        }
        for desi in DESI_TIERS
    ]

    # 30 desi ustu birim fiyat: son iki kademe arasindaki marjinal maliyet.
    last, prev = DESI_TIERS[-1], DESI_TIERS[-2]
    over_30 = {
        zone: _to_pretty_price(
            (
                tier_price(last, zone, profile.price_index)
                - tier_price(prev, zone, profile.price_index)
            )
            / (last - prev)
        )
        for zone in ZONES
    }

    return {
        "carrier": profile.code,
        "display_name": profile.display_name,
        "source": "synthetic",
        "note": (
            "SENTETIK VERI -- gercek sozlesme fiyati degildir. "
            "scripts/generate_synthetic_tariffs.py tarafindan uretilmistir. " + profile.note
        ),
        "valid_from": "2026-01-01",
        "currency": "TRY",
        "rounding": profile.rounding,
        "desi_step": 1.0,
        "min_charge": profile.min_charge,
        "desi_tiers": tiers,
        "over_30_per_desi": over_30,
        "surcharges": {
            "fuel_pct": profile.fuel_pct,
            "cod_fee": profile.cod_fee,
            "insurance": {
                "free_limit": profile.insurance_free_limit,
                "pct_above": profile.insurance_pct_above,
            },
            "vat_pct": 0.20,
        },
        "volume_discounts": profile.volume_discounts,
        "service": {
            "sla_days": profile.sla_days,
            "rural_extra_days": 1,
            "cutoff": profile.cutoff,
        },
        "constraints": {
            "max_desi_per_parcel": profile.max_desi_per_parcel,
            "cod_supported": True,
            "unserved_plates": profile.unserved_plates,
        },
    }


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for profile in CARRIERS:
        tariff = build_tariff(profile)
        path = DATA_DIR / f"{profile.code.lower()}.yaml"
        header = (
            f"# {profile.display_name} -- SENTETIK tarife\n"
            f"# Uretici: scripts/generate_synthetic_tariffs.py (elle duzenlenebilir)\n"
            f"# Bu dosyadaki fiyatlar GERCEK SOZLESME FIYATI DEGILDIR.\n"
        )
        with path.open("w", encoding="utf-8") as handle:
            handle.write(header)
            yaml.safe_dump(tariff, handle, allow_unicode=True, sort_keys=False, width=100)
        print(f"yazildi: {path.relative_to(DATA_DIR.parent.parent)}")


if __name__ == "__main__":
    main()
