"""Desi aritmetigi ve para yuvarlamasi testleri.

Bu modul kucuk ama motorun en kritik parcasi: buradaki bir hata her siparise
yansiyan sistematik bir fiyat hatasidir.
"""

from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from desi_engine.domain import Dimensions, RoundingRule, chargeable_desi, money, volumetric_desi
from desi_engine.domain.units import DESI_DIVISOR, apply_rounding, ceil_to_step, half_up_to_step


class TestVolumetricDesi:
    @pytest.mark.parametrize(
        ("dims", "expected"),
        [
            ((30, 20, 10), 2.0),  # 6000 / 3000
            ((30, 22, 16), 3.52),
            ((10, 10, 10), 1000 / DESI_DIVISOR),
            ((1, 1, 1), 1 / DESI_DIVISOR),
        ],
    )
    def test_golden_cases(self, dims, expected):
        assert volumetric_desi(*dims) == pytest.approx(expected)

    @pytest.mark.parametrize("bad", [(0, 10, 10), (10, -1, 10), (10, 10, 0)])
    def test_rejects_nonpositive(self, bad):
        with pytest.raises(ValueError, match="pozitif"):
            volumetric_desi(*bad)

    def test_order_does_not_matter(self):
        assert volumetric_desi(30, 20, 10) == volumetric_desi(10, 30, 20)


class TestRounding:
    def test_ceil_tolerates_float_noise(self):
        """`2.0` olmasi gereken bir deger kayan nokta gurultusuyle 3'e yuvarlanmamali.

        Bu tolerans olmasa, kademe sinirindaki bir koli bir ust tarifeden
        faturalanirdi -- fark eden olmadan.
        """
        assert ceil_to_step(2.0 + 4e-10) == 2.0
        assert ceil_to_step(2.0000001) == 3.0
        assert ceil_to_step(2.01) == 3.0

    @pytest.mark.parametrize(
        ("value", "expected"), [(2.5, 3.0), (2.49, 2.0), (2.51, 3.0), (3.0, 3.0)]
    )
    def test_half_up(self, value, expected):
        assert half_up_to_step(value) == expected

    def test_half_step(self):
        assert ceil_to_step(2.1, step=0.5) == 2.5
        assert half_up_to_step(2.24, step=0.5) == 2.0
        assert half_up_to_step(2.25, step=0.5) == 2.5

    def test_none_rule_is_identity(self):
        assert apply_rounding(2.3456, RoundingRule.NONE) == 2.3456


class TestChargeableDesi:
    def test_weight_wins_for_dense_items(self):
        """2 desilik ama 3.5 kg gelen bir deterjan kolisi agirliktan fiyatlanir."""
        assert chargeable_desi(volumetric=2.0, weight_kg=3.5) == 4.0

    def test_volume_wins_for_bulky_items(self):
        """40 desilik ama 2 kg gelen bir yorgan hacimden fiyatlanir."""
        assert chargeable_desi(volumetric=40.0, weight_kg=2.0) == 40.0

    def test_half_up_rule(self):
        assert chargeable_desi(7.4, 0.5, RoundingRule.HALF_UP) == 7.0
        assert chargeable_desi(7.5, 0.5, RoundingRule.HALF_UP) == 8.0

    def test_rejects_negative_weight(self):
        with pytest.raises(ValueError, match="negatif"):
            chargeable_desi(1.0, -0.5)

    @given(
        volumetric=st.floats(min_value=0.01, max_value=500, allow_nan=False),
        weight=st.floats(min_value=0.0, max_value=100, allow_nan=False),
    )
    def test_never_below_either_input(self, volumetric, weight):
        """Ucretli desi ne hacimden ne agirliktan kucuk olabilir (CEIL kuralinda)."""
        result = chargeable_desi(volumetric, weight, RoundingRule.CEIL)
        assert result >= volumetric - 1e-9
        assert result >= weight - 1e-9

    @given(
        volumetric=st.floats(min_value=0.01, max_value=500, allow_nan=False),
        weight=st.floats(min_value=0.0, max_value=100, allow_nan=False),
    )
    def test_ceil_result_is_integral(self, volumetric, weight):
        result = chargeable_desi(volumetric, weight, RoundingRule.CEIL, step=1.0)
        assert result == math.floor(result)


class TestMoney:
    def test_half_up_not_bankers_rounding(self):
        """Yerlesik `round()` bankaci yuvarlamasi yapar; fatura icin yanlistir."""
        assert money(2.675) == 2.68
        assert round(2.675, 2) == 2.67  # karsilastirma: istemedigimiz davranis
        assert money(0.125) == 0.13

    def test_leaves_exact_values_alone(self):
        assert money(129.00) == 129.00
        assert money(0.0) == 0.0


class TestDimensions:
    def test_rotations_deduplicated_for_cube(self):
        cube = Dimensions(length_cm=10, width_cm=10, height_cm=10)
        assert len(list(cube.rotations())) == 1

    def test_rotations_full_set_for_distinct_dims(self):
        box = Dimensions(length_cm=30, width_cm=20, height_cm=10)
        assert len(list(box.rotations())) == 6

    def test_rotations_preserve_volume(self):
        box = Dimensions(length_cm=31, width_cm=17, height_cm=9)
        assert all(r.volume_cm3 == pytest.approx(box.volume_cm3) for r in box.rotations())

    def test_fits_within_requires_rotation(self):
        tall = Dimensions(length_cm=5, width_cm=5, height_cm=40)
        flat_box = Dimensions(length_cm=45, width_cm=10, height_cm=10)
        assert tall.fits_within(flat_box) is True
        assert tall.fits_within(flat_box, allow_rotation=False) is False

    def test_does_not_fit(self):
        big = Dimensions(length_cm=60, width_cm=50, height_cm=40)
        small = Dimensions(length_cm=30, width_cm=20, height_cm=10)
        assert big.fits_within(small) is False
