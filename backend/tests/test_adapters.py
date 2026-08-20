"""Veri kaynagi adaptorleri ve sozlesme ice aktarimi testleri.

En kritik test `test_imported_tariff_is_marked_as_contract`: ice aktarilan
tarifenin `source` alani `contract` olmali. Bu bayrak arayuze kadar gidiyor ve
"ORNEK TARIFE" rozetini kaldiran tek sey o. Yanlis kalirsa gercek fiyatlar
sentetik gibi (veya tersi) sunulur.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from desi_engine.adapters import (
    ContractImportError,
    ContractMeta,
    CsvProductCatalogSource,
    CsvShipmentHistorySource,
    FileTariffSource,
    from_csv,
    from_excel,
    write_yaml,
)
from desi_engine.domain import CarrierCode, RoundingRule, TariffSourceKind, ZoneClass
from desi_engine.tariff import TariffRepository

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

MATRIX_CSV = """up_to_desi,sehir_ici,bolge_ici,bolgeler_arasi,uzak
1,62.00,70.00,81.00,92.00
2,68.00,77.00,89.00,101.00
5,86.00,98.00,114.00,130.00
10,112.00,129.00,152.00,175.00
30,178.00,208.00,249.00,293.00
"""


def make_meta(**overrides) -> ContractMeta:
    base = {
        "carrier": CarrierCode.ARAS,
        "display_name": "Aras Kargo",
        "valid_from": date(2026, 1, 1),
        "min_charge": 74.50,
        "rounding": RoundingRule.CEIL,
        "fuel_pct": 0.08,
        "cod_fee": 22.0,
        "insurance_free_limit": 500.0,
        "insurance_pct_above": 0.004,
        "vat_pct": 0.20,
        "over_top_tier_per_desi": {zone.value: 6.0 for zone in ZoneClass},
        "sla_days": {"sehir_ici": 1, "bolge_ici": 2, "bolgeler_arasi": 3, "uzak": 4},
        "cutoff": "17:00",
        "max_desi_per_parcel": 100.0,
        "note": "2026 yili sozlesmesi",
    }
    return ContractMeta(**(base | overrides))


class TestFileSources:
    def test_tariff_source_exposes_all_carriers(self):
        source = FileTariffSource(DATA_DIR / "carriers")
        assert set(source.available_carriers()) == set(CarrierCode)
        assert source.load(CarrierCode.ARAS).display_name == "Aras Kargo"

    def test_product_catalog_loads(self):
        products = CsvProductCatalogSource(DATA_DIR / "catalog" / "products.csv").load()
        assert len(products) >= 40
        assert products["HV-003"].category.value == "havlu"

    def test_product_catalog_rejects_missing_columns(self, tmp_path):
        broken = tmp_path / "urunler.csv"
        broken.write_text("sku,name\nX-1,Test\n", encoding="utf-8")
        with pytest.raises(ValueError, match="eksik sutun"):
            CsvProductCatalogSource(broken).load()

    def test_history_source_reports_missing_file_with_a_fix(self, tmp_path):
        """Hata mesaji ne yapilacagini soylemeli -- 'dosya yok' tek basina yetmez."""
        with pytest.raises(FileNotFoundError, match="generate_synthetic_history"):
            CsvShipmentHistorySource(tmp_path / "yok.csv").load()


class TestContractImport:
    @pytest.fixture
    def matrix_path(self, tmp_path) -> Path:
        path = tmp_path / "aras_2026.csv"
        path.write_text(MATRIX_CSV, encoding="utf-8")
        return path

    def test_imports_a_matrix_into_a_valid_tariff(self, matrix_path):
        tariff = from_csv(matrix_path, make_meta())
        assert tariff.carrier is CarrierCode.ARAS
        assert len(tariff.desi_tiers) == 5
        assert tariff.base_price(1, ZoneClass.SEHIR_ICI) == 62.00
        assert tariff.base_price(7, ZoneClass.UZAK) == 175.00

    def test_imported_tariff_is_marked_as_contract(self, matrix_path):
        """Ice aktarilan tarife sentetik sayilmamali.

        `is_synthetic` arayuzdeki 'ORNEK TARIFE' rozetini kontrol ediyor; yanlis
        kalirsa gercek sozlesme fiyatlari uydurma gibi sunulur.
        """
        tariff = from_csv(matrix_path, make_meta())
        assert tariff.source is TariffSourceKind.CONTRACT
        assert tariff.is_synthetic is False

    def test_rows_are_sorted_regardless_of_file_order(self, tmp_path):
        shuffled = tmp_path / "karisik.csv"
        shuffled.write_text(
            "up_to_desi,sehir_ici,bolge_ici,bolgeler_arasi,uzak\n"
            "5,86,98,114,130\n1,62,70,81,92\n2,68,77,89,101\n",
            encoding="utf-8",
        )
        tariff = from_csv(shuffled, make_meta())
        assert [tier.up_to for tier in tariff.desi_tiers] == [1.0, 2.0, 5.0]

    def test_rejects_non_monotone_prices(self, tmp_path):
        """Ust kademe alt kademeden ucuz olamaz -- elle duzenlemede en sik hata."""
        broken = tmp_path / "bozuk.csv"
        broken.write_text(
            "up_to_desi,sehir_ici,bolge_ici,bolgeler_arasi,uzak\n1,90,90,90,90\n2,70,70,70,70\n",
            encoding="utf-8",
        )
        with pytest.raises(ContractImportError, match="dogrulamadan gecemedi"):
            from_csv(broken, make_meta())

    def test_rejects_missing_zone_column(self, tmp_path):
        broken = tmp_path / "eksik.csv"
        broken.write_text("up_to_desi,sehir_ici\n1,62\n", encoding="utf-8")
        with pytest.raises(ContractImportError, match="eksik sutun"):
            from_csv(broken, make_meta())

    def test_rejects_non_numeric_price(self, tmp_path):
        broken = tmp_path / "metin.csv"
        broken.write_text(
            "up_to_desi,sehir_ici,bolge_ici,bolgeler_arasi,uzak\n1,gorusulecek,70,81,92\n",
            encoding="utf-8",
        )
        with pytest.raises(ContractImportError, match="sayiya cevrilemeyen"):
            from_csv(broken, make_meta())

    def test_rejects_empty_matrix(self, tmp_path):
        empty = tmp_path / "bos.csv"
        empty.write_text("up_to_desi,sehir_ici,bolge_ici,bolgeler_arasi,uzak\n", encoding="utf-8")
        with pytest.raises(ContractImportError, match="bos"):
            from_csv(empty, make_meta())

    def test_excel_import_explains_how_to_install_the_dependency(self, tmp_path):
        """`openpyxl` yoksa hata mesaji cozumu soylemeli."""
        try:
            import openpyxl  # noqa: F401
        except ImportError:
            with pytest.raises(ContractImportError, match="excel"):
                from_excel(tmp_path / "yok.xlsx", make_meta())
        else:  # pragma: no cover - openpyxl kurulu ortamlarda
            pytest.skip("openpyxl kurulu; eksik bagimlilik yolu test edilemiyor")

    def test_round_trip_through_yaml_is_loadable_by_the_engine(self, matrix_path, tmp_path):
        """Ice aktarim -> YAML -> motor zinciri calismali.

        Ayri bir 'gercek veri modu' kodu yok: ice aktarim bir kez yapilir, motor
        bundan sonra her zamanki gibi dizindeki YAML'lari okur.
        """
        tariff = from_csv(matrix_path, make_meta())
        directory = tmp_path / "carriers"
        written = write_yaml(tariff, directory)
        assert written.name == "aras.yaml"

        reloaded = TariffRepository(directory)
        assert reloaded.get(CarrierCode.ARAS).is_synthetic is False
        assert reloaded.synthetic_carriers() == ()
        assert reloaded.get(CarrierCode.ARAS).base_price(1, ZoneClass.SEHIR_ICI) == 62.00
