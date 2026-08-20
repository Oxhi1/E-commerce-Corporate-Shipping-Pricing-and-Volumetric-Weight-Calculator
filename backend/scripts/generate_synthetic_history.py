"""Sentetik gecmis sevkiyat verisi uretir -> `data/history/shipments.csv`.

Bu dosya motorun **tek bilgi kaynagi**. Hasar oranlarini ve teslimat sureleri
dagilimini buradan tahmin eder; `TrueWorld` icindeki gercek parametrelere asla
erisemez.

Veri kasitli olarak dengesiz uretilir:

* Firma dagilimi carpik (ARAS %45, PTT %5) -- sirket bugune kadar birkac firmayla
  calismis. Sonuc: bazi (firma, bolge, kategori) hucrelerinde bir avuc gonderi.
* Bolge dagilimi il nufuslarina agirlikli -- Istanbul'a giden binlerce gonderi
  varken Bayburt'a giden onlarca.

Iki carpiklik birlesince en kritik hucreler (uzak bolge x kirilabilir urun x az
kullanilan firma) neredeyse bos kaliyor. Hiyerarsik shrinkage'in varlik sebebi
tam olarak bu; dengeli bir veri setinde ham oranlar da is gorurdu.

Kullanim:
    python scripts/generate_synthetic_history.py [--shipments 60000] [--seed 42]
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from desi_engine.domain.enums import RiskCategory
from desi_engine.simulation.world import HistoricalMix, TrueWorld
from desi_engine.tariff import ProvinceRegistry, TariffRepository

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUTPUT = DATA / "history" / "shipments.csv"

#: Gecmis siparislerin urun tipi dagilimi -- Ozdilek profiline uygun olarak
#: agirlikli tekstil.
CATEGORY_MIX: dict[RiskCategory, float] = {
    RiskCategory.SOFT: 0.62,
    RiskCategory.LIQUID: 0.16,
    RiskCategory.FRAGILE: 0.14,
    RiskCategory.APPLIANCE: 0.08,
}

RURAL_SHARE: float = 0.08
ORIGIN_PLATE: int = 16  # Bursa dagitim merkezi


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shipments", type=int, default=60_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--origin", type=int, default=ORIGIN_PLATE)
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)

    tariffs = TariffRepository(DATA / "carriers")
    provinces = ProvinceRegistry.from_csv(DATA / "zones" / "tr_iller.csv")

    world = TrueWorld.from_tariffs(tariffs)

    carriers, carrier_probs = HistoricalMix().probabilities()
    categories = list(CATEGORY_MIX)
    category_probs = np.array([CATEGORY_MIX[c] for c in categories])
    category_probs /= category_probs.sum()

    plate_weights = provinces.population_weights()
    plates = np.array(list(plate_weights))
    plate_probs = np.array([plate_weights[p] for p in plates])
    plate_probs /= plate_probs.sum()

    # Vektorlestirilmis cekilis: 60 bin satir icin dongu yerine tek seferde.
    n = args.shipments
    carrier_idx = rng.choice(len(carriers), size=n, p=carrier_probs)
    category_idx = rng.choice(len(categories), size=n, p=category_probs)
    dest_plates = rng.choice(plates, size=n, p=plate_probs)
    rural_flags = rng.random(n) < RURAL_SHARE
    declared_values = np.round(rng.lognormal(mean=6.9, sigma=0.75, size=n), 2)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    damaged_count = 0

    with OUTPUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "shipment_id",
                "carrier",
                "dest_plate",
                "zone",
                "risk_category",
                "is_rural",
                "declared_value_try",
                "promised_days",
                "delivery_days",
                "damaged",
            ]
        )

        for i in range(n):
            carrier = carriers[carrier_idx[i]]
            category = categories[category_idx[i]]
            plate = int(dest_plates[i])
            is_rural = bool(rural_flags[i])

            tariff = tariffs.get(carrier)
            if not tariff.serves(plate):
                # Hizmet vermedigi ile gonderi cikmaz -- gercek veride de yok.
                continue

            zone = provinces.zone_class(args.origin, plate)
            promised = tariff.service.promised_days(zone, is_rural=is_rural)
            days = world.sample_delivery_days(carrier, zone, rng, is_rural=is_rural)
            damaged = world.sample_damage(carrier, zone, category, rng)
            damaged_count += damaged

            writer.writerow(
                [
                    f"H{i:07d}",
                    carrier.value,
                    plate,
                    zone.value,
                    category.value,
                    int(is_rural),
                    declared_values[i],
                    promised,
                    round(days, 2),
                    int(damaged),
                ]
            )

    size_mb = OUTPUT.stat().st_size / 1_048_576
    print(f"yazildi: {OUTPUT.relative_to(ROOT)}  ({size_mb:.1f} MB)")
    print(f"  {n:,} gonderi denendi, {damaged_count:,} hasar ({damaged_count / n:.3%})")


if __name__ == "__main__":
    main()
