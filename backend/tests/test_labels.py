"""Barkod kodlayicisi ve etiket uretimi testleri.

Barkod fiziksel bir okuyucuyla test edilemedigi icin agirlik **yapisal
dogrulamada**: modul sayilari, saglama toplami aritmetigi, baslangic/bitis
desenleri. Bunlar Code 128 spesifikasyonundan dogrudan turetilebilir ve
kodlayicidaki bir hatayi yakalar.
"""

from __future__ import annotations

import pytest

from desi_engine.domain import Address, Cart, CartLine, Order, Region
from desi_engine.labels import (
    BarcodeError,
    build_labels,
    encode_modules,
    encode_values,
    to_html_preview,
    to_svg,
    to_zpl,
)
from desi_engine.labels.barcode import QUIET_ZONE_MODULES, START_B, STOP


class TestCode128:
    def test_starts_with_code_set_b_and_ends_with_stop(self):
        values = encode_values("ABC123")
        assert values[0] == START_B
        assert values[-1] == STOP

    def test_checksum_matches_specification(self):
        """Saglama: `(baslangic + SUM(i * deger_i)) mod 103`."""
        values = encode_values("OZDILEK")
        payload = values[1:-2]
        expected = (START_B + sum(i * v for i, v in enumerate(payload, start=1))) % 103
        assert values[-2] == expected

    def test_value_mapping_is_ascii_minus_32(self):
        # 'A' = 65 -> 33, '0' = 48 -> 16
        assert encode_values("A0")[1:3] == [33, 16]

    def test_module_count_follows_the_formula(self):
        """Toplam modul = 11 * (karakter + 3) + 2.

        +3: baslangic, saglama, bitis. +2: bitis deseninin fazladan iki modulu.
        """
        for data in ("A", "ABC", "ARS12345678901"):
            assert sum(encode_modules(data)) == 11 * (len(data) + 3) + 2

    def test_rejects_characters_outside_code_set_b(self):
        with pytest.raises(BarcodeError, match="kodlanamaz"):
            encode_values("Turkce-ıçğ")

    def test_rejects_empty_data(self):
        with pytest.raises(BarcodeError, match="bos olamaz"):
            encode_values("")

    def test_svg_includes_quiet_zones(self):
        svg = to_svg("ARS12345678901", module_width=2.0)
        # Ilk cubuk, sessiz alan kadar iceriden baslamali.
        assert f'x="{QUIET_ZONE_MODULES * 2.0:.2f}"' in svg

    def test_svg_is_black_on_white_regardless_of_theme(self):
        """Barkod tema degisiminde ters cevrilmemeli -- okuyucular okuyamaz."""
        svg = to_svg("TEST123")
        assert "currentColor" not in svg
        assert 'fill="#000000"' in svg
        assert 'fill="#ffffff"' in svg

    def test_svg_is_well_formed(self):
        from xml.etree import ElementTree

        ElementTree.fromstring(to_svg("ARS00000000042"))


class TestShippingLabel:
    @pytest.fixture
    def decision_and_order(self, engine):
        order = Order(
            order_id="LBL-001",
            cart=Cart(
                lines=[
                    CartLine(product=engine.product("GD-001"), quantity=1),
                    CartLine(product=engine.product("NV-002"), quantity=1),
                ]
            ),
            address=Address(city_plate=65, city_name="Van", region=Region.DOGU_ANADOLU),
            is_cod=True,
            customer_clv_try=4500.0,
        )
        return order, engine.selector.decide(order)

    def test_one_label_per_parcel(self, decision_and_order):
        order, decision = decision_and_order
        labels = build_labels(order, decision)
        assert len(labels) == decision.selected.parcel_count
        assert [label.parcel_index for label in labels] == list(range(1, len(labels) + 1))

    def test_tracking_numbers_are_unique_and_deterministic(self, decision_and_order):
        order, decision = decision_and_order
        first = [label.tracking_number for label in build_labels(order, decision)]
        second = [label.tracking_number for label in build_labels(order, decision)]
        assert first == second
        assert len(set(first)) == len(first)

    def test_tracking_prefix_matches_carrier(self, decision_and_order):
        order, decision = decision_and_order
        label = build_labels(order, decision)[0]
        assert label.tracking_number.startswith(("ARS", "MNG", "YK", "SRT", "PTT"))

    def test_cod_amount_charged_on_first_parcel_only(self, decision_and_order):
        """Her koliye tutar yazmak kuryenin birden fazla tahsilat yapmasina yol acar."""
        order, decision = decision_and_order
        labels = build_labels(order, decision)
        assert labels[0].cod_amount_try == pytest.approx(order.cart.total_value_try)
        assert all(label.cod_amount_try == 0.0 for label in labels[1:])

    def test_label_carries_the_decision_rationale(self, decision_and_order):
        """Etiket ayni zamanda denetim kaydi: 'bu koli neden bu firmayla gitti'."""
        order, decision = decision_and_order
        label = build_labels(order, decision)[0]
        assert decision.selected.display_name in label.decision_note
        if decision.overrode_cheapest_freight:
            assert "en ucuz nakliye reddedildi" in label.decision_note

    def test_zpl_has_valid_envelope(self, decision_and_order):
        order, decision = decision_and_order
        zpl = to_zpl(build_labels(order, decision)[0])
        assert zpl.strip().startswith("^XA")
        assert zpl.strip().endswith("^XZ")
        assert "^BCN,120,Y,N,N" in zpl

    def test_zpl_contains_the_tracking_number(self, decision_and_order):
        order, decision = decision_and_order
        label = build_labels(order, decision)[0]
        assert label.tracking_number in to_zpl(label)

    def test_synthetic_tariff_is_stamped_on_the_label(self, decision_and_order):
        """Sentetik fiyatla basilan bir etiket kendini ele vermeli."""
        order, decision = decision_and_order
        label = build_labels(order, decision)[0]
        assert label.is_synthetic_tariff
        assert "ORNEK TARIFE" in to_zpl(label)
        assert "ORNEK TARIFE" in to_html_preview(label)

    def test_html_preview_embeds_a_real_barcode(self, decision_and_order):
        order, decision = decision_and_order
        preview = to_html_preview(build_labels(order, decision)[0])
        assert "<svg" in preview
        assert "shipping-label" in preview
