"""Tarife semasi, bolge siniflandirmasi ve ucret hesaplayicisi testleri."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from desi_engine.domain import CarrierCode, ZoneClass
from desi_engine.tariff import (
    FreightCalculator,
    ProvinceRegistry,
    Tariff,
    TariffLoadError,
    TariffRepository,
)
from desi_engine.tariff.surcharges import SURCHARGE_ORDER

# ---- veri dosyalarinin butunlugu ---------------------------------------------


class TestRealDataFiles:
    def test_all_five_carriers_load(self, tariffs: TariffRepository):
        assert set(tariffs.carriers) == set(CarrierCode)

    def test_every_shipped_tariff_is_flagged_synthetic(self, tariffs: TariffRepository):
        """Depoya konan ornek tarifelerin hepsi sentetik olarak isaretli olmali.

        Bu bir bicimsellik degil: arayuz 'ORNEK TARIFE' rozetini bu bayraga gore
        gosteriyor. Bayrak dusuk kalirsa uydurma fiyatlar gercek sozlesme fiyati
        gibi sunulur.
        """
        assert set(tariffs.synthetic_carriers()) == set(CarrierCode)

    def test_all_81_provinces_present(self, provinces: ProvinceRegistry):
        assert len(provinces) == 81
        assert provinces.plates == tuple(range(1, 82))

    def test_population_weights_sum_to_one(self, provinces: ProvinceRegistry):
        assert sum(provinces.population_weights().values()) == pytest.approx(1.0)

    def test_carriers_are_actually_differentiated(self, tariffs: TariffRepository):
        """Firmalar farkli takas noktalarinda olmali; hepsi ayni olsa karar motoru
        gereksizlesir ve simulasyon hicbir sey ogretmez."""
        prices = {t.carrier: t.base_price(10, ZoneClass.UZAK) for t in tariffs}
        assert max(prices.values()) / min(prices.values()) > 1.15

        slas = {t.carrier: t.service.sla_days[ZoneClass.UZAK] for t in tariffs}
        assert len(set(slas.values())) >= 3


# ---- sema dogrulamalari ------------------------------------------------------


def _minimal_tariff_dict(**overrides) -> dict:
    zones = {z.value: 100.0 for z in ZoneClass}
    base = {
        "carrier": "ARAS",
        "display_name": "Test",
        "source": "synthetic",
        "valid_from": "2026-01-01",
        "rounding": "ceil",
        "min_charge": 50.0,
        "desi_tiers": [
            {"up_to": 1, "zones": dict(zones)},
            {"up_to": 5, "zones": {z.value: 150.0 for z in ZoneClass}},
        ],
        "over_30_per_desi": {z.value: 5.0 for z in ZoneClass},
        "surcharges": {
            "fuel_pct": 0.1,
            "cod_fee": 20.0,
            "insurance": {"free_limit": 500.0, "pct_above": 0.005},
            "vat_pct": 0.20,
        },
        "service": {
            "sla_days": {z.value: 2 for z in ZoneClass},
            "rural_extra_days": 1,
            "cutoff": "17:00",
        },
        "constraints": {"max_desi_per_parcel": 100, "cod_supported": True, "unserved_plates": []},
    }
    return base | overrides


class TestSchemaValidation:
    def test_rejects_non_monotone_prices(self):
        """Ust kademe alt kademeden ucuz olamaz -- elle duzenlemede en sik hata."""
        bad = _minimal_tariff_dict(
            desi_tiers=[
                {"up_to": 1, "zones": {z.value: 150.0 for z in ZoneClass}},
                {"up_to": 5, "zones": {z.value: 100.0 for z in ZoneClass}},
            ]
        )
        with pytest.raises(ValidationError, match="fiyat desi arttikca dusuyor"):
            Tariff.model_validate(bad)

    def test_rejects_unsorted_tiers(self):
        bad = _minimal_tariff_dict(
            desi_tiers=[
                {"up_to": 5, "zones": {z.value: 100.0 for z in ZoneClass}},
                {"up_to": 1, "zones": {z.value: 150.0 for z in ZoneClass}},
            ]
        )
        with pytest.raises(ValidationError, match="artan ve tekil"):
            Tariff.model_validate(bad)

    def test_rejects_missing_zone(self):
        bad = _minimal_tariff_dict(
            desi_tiers=[{"up_to": 1, "zones": {"sehir_ici": 100.0, "bolge_ici": 110.0}}]
        )
        with pytest.raises(ValidationError, match="eksik bolge"):
            Tariff.model_validate(bad)

    def test_rejects_unsorted_volume_discounts(self):
        bad = _minimal_tariff_dict(
            volume_discounts=[
                {"monthly_parcels_gte": 9000, "pct": 0.08},
                {"monthly_parcels_gte": 4000, "pct": 0.05},
            ]
        )
        with pytest.raises(ValidationError, match="artan esige"):
            Tariff.model_validate(bad)

    def test_accepts_valid_tariff(self):
        assert Tariff.model_validate(_minimal_tariff_dict()).carrier is CarrierCode.ARAS

    def test_loader_wraps_errors_with_filename(self, tmp_path):
        bad_file = tmp_path / "bozuk.yaml"
        bad_file.write_text("carrier: ARAS\n", encoding="utf-8")
        with pytest.raises(TariffLoadError, match=r"bozuk\.yaml"):
            from desi_engine.tariff import load_tariff_file

            load_tariff_file(bad_file)

    def test_repository_rejects_empty_directory(self, tmp_path):
        with pytest.raises(TariffLoadError, match="bulunamadi"):
            TariffRepository(tmp_path)


# ---- taban fiyat arama -------------------------------------------------------


class TestBasePrice:
    @pytest.fixture
    def tariff(self) -> Tariff:
        return Tariff.model_validate(_minimal_tariff_dict())

    def test_tier_boundary_is_inclusive(self, tariff: Tariff):
        """`up_to: 1` tam 1.0 desiyi kapsar; 1.01 bir ust kademeye gecer."""
        assert tariff.base_price(1.0, ZoneClass.SEHIR_ICI) == 100.0
        assert tariff.base_price(1.01, ZoneClass.SEHIR_ICI) == 150.0

    def test_above_top_tier_is_linear(self, tariff: Tariff):
        """Tablonun ustunde: son kademe + asan desi x birim fiyat."""
        assert tariff.base_price(5, ZoneClass.SEHIR_ICI) == 150.0
        assert tariff.base_price(8, ZoneClass.SEHIR_ICI) == 150.0 + 3 * 5.0

    def test_monotone_over_real_tariffs(self, tariffs: TariffRepository):
        for tariff in tariffs:
            for zone in ZoneClass:
                prices = [tariff.base_price(d, zone) for d in range(1, 60)]
                assert prices == sorted(prices), f"{tariff.carrier}/{zone} monoton degil"

    def test_volume_discount_picks_highest_applicable_tier(self, tariffs: TariffRepository):
        aras = tariffs.get(CarrierCode.ARAS)
        assert aras.volume_discount_pct(0) == 0.0
        assert aras.volume_discount_pct(4999) == 0.0
        assert aras.volume_discount_pct(5000) == 0.06
        assert aras.volume_discount_pct(50000) == 0.09


# ---- ucret hesaplayicisi -----------------------------------------------------


class TestFreightCalculator:
    @pytest.fixture
    def calc(self) -> FreightCalculator:
        return FreightCalculator(monthly_parcel_volume=0)

    def test_min_charge_floor_applies(self, calc, tariffs):
        """1 desilik bir gonderide ARAS'in taban tarifesi (68.00) asgari ucretin
        (79.90) altinda kalir; taban devreye girmeli."""
        aras = tariffs.get(CarrierCode.ARAS)
        quote = calc.quote(aras, [1.0], ZoneClass.SEHIR_ICI, declared_value_try=0.0)
        parcel = quote.parcels[0]
        assert parcel.base_before_min == 68.00
        assert parcel.min_charge_applied is True
        assert parcel.base_after_min == 79.90

    def test_min_charge_applies_per_parcel(self, calc, tariffs):
        """Iki parcaya bolunen gonderide asgari ucret iki kez devreye girer.

        PTT'nin 50 desi parca siniri gibi kisitlarin gercek maliyeti buradan gelir.
        """
        aras = tariffs.get(CarrierCode.ARAS)
        one = calc.quote(aras, [1.0], ZoneClass.SEHIR_ICI, 0.0)
        two = calc.quote(aras, [1.0, 1.0], ZoneClass.SEHIR_ICI, 0.0)
        assert two.total_try == pytest.approx(2 * one.total_try, rel=1e-9)

    def test_surcharge_order_fuel_after_discount(self, tariffs):
        """Yakit farki indirimli taban uzerinden hesaplanmali, indirimsiz uzerinden degil."""
        aras = tariffs.get(CarrierCode.ARAS)
        calc = FreightCalculator(monthly_parcel_volume=10000)  # %9 indirim
        quote = calc.quote(aras, [10.0], ZoneClass.BOLGE_ICI, 0.0)
        parcel = quote.parcels[0]

        assert quote.volume_discount_pct == 0.09
        expected_fuel = parcel.discounted_base * aras.surcharges.fuel_pct
        assert parcel.fuel_try == pytest.approx(expected_fuel, abs=0.01)
        # Indirimsiz taban uzerinden hesaplansaydi belirgin olarak yuksek olurdu.
        assert parcel.fuel_try < parcel.base_after_min * aras.surcharges.fuel_pct

    def test_documented_order_matches_implementation(self):
        assert SURCHARGE_ORDER == (
            "base_tariff",
            "min_charge_floor",
            "volume_discount",
            "fuel_surcharge",
            "cod_fee",
            "insurance_fee",
            "vat",
        )

    def test_insurance_only_above_free_limit(self, calc, tariffs):
        aras = tariffs.get(CarrierCode.ARAS)  # muafiyet 500, ustu %0.4
        under = calc.quote(aras, [5.0], ZoneClass.BOLGE_ICI, declared_value_try=400.0)
        over = calc.quote(aras, [5.0], ZoneClass.BOLGE_ICI, declared_value_try=1500.0)
        assert under.insurance_try == 0.0
        assert over.insurance_try == pytest.approx((1500 - 500) * 0.004, abs=0.01)

    def test_cod_charged_once_regardless_of_parcels(self, calc, tariffs):
        aras = tariffs.get(CarrierCode.ARAS)
        quote = calc.quote(aras, [5.0, 5.0, 5.0], ZoneClass.BOLGE_ICI, 0.0, is_cod=True)
        assert quote.cod_try == aras.surcharges.cod_fee

    def test_vat_applied_last_on_everything(self, calc, tariffs):
        aras = tariffs.get(CarrierCode.ARAS)
        quote = calc.quote(aras, [8.0], ZoneClass.UZAK, 2000.0, is_cod=True)
        assert quote.vat_try == pytest.approx(quote.subtotal_before_vat * 0.20, abs=0.01)
        assert quote.total_try == pytest.approx(quote.subtotal_before_vat + quote.vat_try, abs=0.01)

    def test_explain_lines_sum_to_total(self, tariffs):
        """Dokum satirlarinin toplami genel toplama esit olmali -- arayuzdeki
        waterfall grafigi bu ozdeslige dayaniyor."""
        calc = FreightCalculator(monthly_parcel_volume=10000)
        aras = tariffs.get(CarrierCode.ARAS)
        quote = calc.quote(aras, [12.0, 7.0], ZoneClass.UZAK, 3000.0, is_cod=True)
        assert sum(amount for _, amount in quote.explain_lines()) == pytest.approx(
            quote.total_try, abs=0.05
        )

    def test_rejects_empty_parcel_list(self, calc, tariffs):
        with pytest.raises(ValueError, match="En az bir koli"):
            calc.quote(tariffs.get(CarrierCode.ARAS), [], ZoneClass.SEHIR_ICI, 0.0)

    @given(desi=st.floats(min_value=0.1, max_value=200, allow_nan=False))
    def test_total_never_below_min_charge(self, tariffs, desi):
        calc = FreightCalculator(monthly_parcel_volume=0)
        aras = tariffs.get(CarrierCode.ARAS)
        quote = calc.quote(aras, [desi], ZoneClass.SEHIR_ICI, 0.0)
        assert quote.total_try >= aras.min_charge


# ---- bolge siniflandirmasi ---------------------------------------------------


class TestZoneClassification:
    def test_same_city_is_local(self, provinces):
        assert provinces.zone_class(16, 16) is ZoneClass.SEHIR_ICI

    def test_same_region_is_intra_region(self, provinces):
        assert provinces.zone_class(16, 34) is ZoneClass.BOLGE_ICI  # Bursa -> Istanbul

    def test_different_region_is_inter_region(self, provinces):
        assert provinces.zone_class(16, 6) is ZoneClass.BOLGELER_ARASI  # Bursa -> Ankara

    def test_remote_flag_forces_far_zone(self, provinces):
        """Hakkari (30) 'uzak' isaretli; mesafe hesabina bakilmadan UZAK olmali."""
        assert provinces.zone_class(16, 30) is ZoneClass.UZAK
        assert provinces.zone_class(65, 30) is ZoneClass.UZAK  # yakin komsu olsa bile

    def test_long_distance_is_far_even_without_flag(self, provinces):
        """Gaziantep uzak isaretli degil ama Bursa'dan 800 km -- esik altinda kaliyor;
        Van 1245 km -- ustunde."""
        assert provinces.zone_class(16, 27) is ZoneClass.BOLGELER_ARASI
        assert provinces.zone_class(16, 65) is ZoneClass.UZAK

    def test_classification_follows_origin(self, provinces):
        """Cikis deposu degisince siniflandirma da degismeli -- tablo degil, turetim."""
        assert provinces.zone_class(16, 35) is ZoneClass.BOLGELER_ARASI  # Bursa -> Izmir
        assert provinces.zone_class(45, 35) is ZoneClass.BOLGE_ICI  # Manisa -> Izmir

    def test_distance_is_symmetric(self, provinces):
        assert provinces.distance_km(16, 65) == pytest.approx(provinces.distance_km(65, 16))

    def test_unknown_plate_raises(self, provinces):
        with pytest.raises(KeyError, match="Bilinmeyen il"):
            provinces.get(99)

    def test_surat_does_not_serve_remote_east(self, tariffs):
        surat = tariffs.get(CarrierCode.SURAT)
        assert surat.serves(34) is True
        assert surat.serves(30) is False  # Hakkari
        assert surat.serves(73) is False  # Sirnak

    def test_ptt_serves_everywhere(self, tariffs, provinces):
        ptt = tariffs.get(CarrierCode.PTT)
        assert all(ptt.serves(plate) for plate in provinces.plates)
