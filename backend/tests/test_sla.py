"""Teslimat suresi kestirimi ve gecikme maliyeti testleri."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from desi_engine.domain import CarrierCode, ZoneClass
from desi_engine.sla import DelayCostModel, DelayCostParams, DeliveryTimeEstimator, FittedDelivery

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(scope="session")
def history() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "history" / "shipments.csv")


@pytest.fixture(scope="session")
def delivery(history: pd.DataFrame) -> DeliveryTimeEstimator:
    return DeliveryTimeEstimator().fit(history)


# ---- log-normal matematigi ---------------------------------------------------


class TestFittedDelivery:
    @pytest.fixture
    def fit(self) -> FittedDelivery:
        return FittedDelivery(mu=np.log(3.0), sigma=0.35, observations=500, source="hucre")

    def test_median_is_exp_mu(self, fit):
        assert fit.median_days == pytest.approx(3.0)

    def test_mean_exceeds_median_for_skewed_distribution(self, fit):
        """Log-normal saga carpiktir: ortalama medyandan buyuk olmali."""
        assert fit.mean_days > fit.median_days

    def test_percentiles_are_ordered(self, fit):
        assert fit.percentile(0.50) < fit.percentile(0.90) < fit.percentile(0.99)

    def test_probability_late_decreases_with_generous_promise(self, fit):
        assert fit.probability_late(2) > fit.probability_late(3) > fit.probability_late(6)

    def test_probability_late_at_median_is_half(self, fit):
        assert fit.probability_late(3.0) == pytest.approx(0.5, abs=1e-6)

    def test_expected_lateness_matches_monte_carlo(self, fit):
        """Kapali form ile ornekleme ayni sonucu vermeli.

        Kapali formu Monte Carlo'da milyonlarca kez cagirdigimiz icin kullaniyoruz;
        dogrulugunu bir kez ornekleme ile teyit etmek yeterli.
        """
        rng = np.random.default_rng(11)
        draws = rng.lognormal(fit.mu, fit.sigma, size=400_000)
        for promised in (2.0, 3.0, 5.0):
            empirical = np.maximum(draws - promised, 0.0).mean()
            assert fit.expected_lateness_days(promised) == pytest.approx(empirical, rel=0.03)

    def test_expected_lateness_never_negative(self, fit):
        assert fit.expected_lateness_days(100) >= 0.0

    def test_higher_variance_means_more_lateness_at_same_median(self):
        """Ayni medyan, daha genis dagilim -> daha fazla beklenen gecikme.

        Guvenilirlik hizdan bagimsiz bir degerdir; model bunu yakalamali.
        """
        steady = FittedDelivery(mu=np.log(3), sigma=0.20, observations=500, source="hucre")
        erratic = FittedDelivery(mu=np.log(3), sigma=0.60, observations=500, source="hucre")
        assert erratic.expected_lateness_days(4) > steady.expected_lateness_days(4)


# ---- kestirici ---------------------------------------------------------------


@pytest.fixture(scope="session")
def sla_lookup(tariffs) -> dict[tuple[str, str], int]:
    return {
        (tariff.carrier.value, zone.value): days
        for tariff in tariffs
        for zone, days in tariff.service.sla_days.items()
    }


def sla_of(tariffs, carrier: CarrierCode, zone: ZoneClass) -> int:
    return tariffs.get(carrier).service.promised_days(zone)


class TestDeliveryTimeEstimator:
    def test_requires_fitting_first(self):
        with pytest.raises(RuntimeError, match="fit"):
            DeliveryTimeEstimator().estimate(CarrierCode.ARAS, ZoneClass.UZAK, 4)

    def test_rejects_missing_columns(self):
        with pytest.raises(ValueError, match="eksik sutun"):
            DeliveryTimeEstimator().fit(pd.DataFrame({"carrier": ["ARAS"]}))

    def test_far_zones_take_longer(self, delivery, tariffs):
        near = delivery.estimate(
            CarrierCode.ARAS,
            ZoneClass.SEHIR_ICI,
            sla_of(tariffs, CarrierCode.ARAS, ZoneClass.SEHIR_ICI),
        )
        far = delivery.estimate(
            CarrierCode.ARAS, ZoneClass.UZAK, sla_of(tariffs, CarrierCode.ARAS, ZoneClass.UZAK)
        )
        assert far.median_days > near.median_days

    def test_learns_carrier_speed_ordering(self, delivery, tariffs):
        """Yurtici en hizli, Surat en yavas -- model bunu veriden bulmali."""
        zone = ZoneClass.BOLGELER_ARASI
        fast = delivery.estimate(
            CarrierCode.YURTICI, zone, sla_of(tariffs, CarrierCode.YURTICI, zone)
        ).median_days
        slow = delivery.estimate(
            CarrierCode.SURAT, zone, sla_of(tariffs, CarrierCode.SURAT, zone)
        ).median_days
        assert fast < slow

    def test_learns_who_keeps_their_promise(self, delivery, tariffs):
        """Yurtici vaadini tutar, PTT tutmaz -- ikisi de sozlesmede 'gun' yaziyor.

        Motorun vaade degil gerceklesene bakmasinin sebebi bu.
        """
        zone = ZoneClass.UZAK
        results = {}
        for carrier in (CarrierCode.YURTICI, CarrierCode.PTT):
            sla = sla_of(tariffs, carrier, zone)
            results[carrier] = delivery.estimate(carrier, zone, sla).probability_late(sla)
        assert results[CarrierCode.YURTICI] < results[CarrierCode.PTT]

    def test_overshoot_is_scale_free(self, delivery):
        """Asim dagilimi gun olceginden bagimsiz olmali.

        Bu ozellik olmasa bolgeler arasi havuzlama yanlis olurdu: 1 gunluk sehir
        ici hucresi, 4 gunluk uzak bolge hucreleriyle ayni ortalamaya cekilir ve
        gecikme olasiligi sistematik olarak abartilirdi.
        """
        overshoot = delivery.overshoot(CarrierCode.YURTICI, ZoneClass.SEHIR_ICI)
        one_day = overshoot.at_sla(1)
        four_day = overshoot.at_sla(4)
        assert one_day.probability_late(1) == pytest.approx(four_day.probability_late(4))
        assert four_day.median_days == pytest.approx(4 * one_day.median_days)

    def test_estimated_late_rates_track_reality(self, delivery, history, tariffs):
        """Kestirilen gecikme olasiligi, gecmiste gerceklesen oranla tutarli olmali."""
        realized = history.assign(late=history.delivery_days > history.promised_days)
        grouped = (
            realized[~realized.is_rural.astype(bool)]
            .groupby(["carrier", "zone"])["late"]
            .agg(["mean", "size"])
        )

        for (carrier, zone), row in grouped.iterrows():
            if row["size"] < 300:
                continue  # seyrek hucrelerde shrinkage bilincli olarak sapar
            sla = sla_of(tariffs, CarrierCode(carrier), ZoneClass(zone))
            predicted = delivery.estimate(
                CarrierCode(carrier), ZoneClass(zone), sla
            ).probability_late(sla)
            assert abs(predicted - row["mean"]) < 0.07, f"{carrier}/{zone}"

    def test_rural_is_slower_than_urban(self, delivery, tariffs):
        """Kirsal teslimat hem daha yavas hem daha sik gecikmeli olmali.

        Her hucre **kendi** SLA capasina oturtulmali; kirsalin vaadi bir gun
        fazladir. Ilk surumde dunya modeli kirsali taban SLA'ya gore kuruyor ama
        gecmis veriye kirsal vaadini yaziyordu; sonuc tersine donuyor ve kirsal
        gonderiler daha *az* gecikmis gorunuyordu.
        """
        zone = ZoneClass.BOLGELER_ARASI
        for carrier in CarrierCode:
            tariff = tariffs.get(carrier)
            urban_sla = tariff.service.promised_days(zone)
            rural_sla = tariff.service.promised_days(zone, is_rural=True)

            urban = delivery.estimate(carrier, zone, urban_sla, is_rural=False)
            rural = delivery.estimate(carrier, zone, rural_sla, is_rural=True)

            assert rural.median_days > urban.median_days, carrier
            assert rural.probability_late(rural_sla) > urban.probability_late(urban_sla), carrier

    def test_unseen_cell_falls_back_to_carrier_level(self, history):
        partial = history[history["zone"] != "uzak"]
        estimator = DeliveryTimeEstimator().fit(partial)
        fit = estimator.estimate(CarrierCode.ARAS, ZoneClass.UZAK, 4)
        assert fit.median_days > 0
        assert fit.source in {"firma", "genel"}

    def test_summary_frame_covers_all_carriers(self, delivery, sla_lookup):
        frame = delivery.summary_frame(sla_lookup)
        assert set(frame["carrier"]) == {c.value for c in CarrierCode}
        assert (frame["p95_days"] >= frame["median_days"]).all()


# ---- gecikme maliyeti --------------------------------------------------------


class TestDelayCostModel:
    @pytest.fixture
    def model(self, delivery) -> DelayCostModel:
        return DelayCostModel(delivery)

    def test_slow_carrier_costs_more_than_fast_one(self, model, tariffs):
        zone = ZoneClass.UZAK
        fast = model.expected_cost(
            CarrierCode.YURTICI, zone, tariffs.get(CarrierCode.YURTICI).service.promised_days(zone)
        )
        slow = model.expected_cost(
            CarrierCode.SURAT, zone, tariffs.get(CarrierCode.SURAT).service.promised_days(zone)
        )
        assert slow.total_try > fast.total_try

    def test_generous_customer_promise_lowers_cost(self, model):
        """Firma ayni hizda teslim ediyor ama musteriye daha rahat gun soyleniyor.

        Dagilim degismez (firma SLA'si sabit), yalnizca gecikmenin olculdugu esik
        kayar. "Musteriye bir gun fazla soylesek ne kazanirdik" sorusunun cevabi.
        """
        tight = model.expected_cost(CarrierCode.MNG, ZoneClass.UZAK, 5, customer_promise_days=3)
        loose = model.expected_cost(CarrierCode.MNG, ZoneClass.UZAK, 5, customer_promise_days=9)
        assert loose.total_try < tight.total_try
        assert loose.probability_late < tight.probability_late
        assert tight.expected_days == pytest.approx(loose.expected_days)

    def test_clv_only_affects_churn_line(self, model):
        without = model.expected_cost(CarrierCode.MNG, ZoneClass.UZAK, 5, customer_clv_try=0)
        with_clv = model.expected_cost(CarrierCode.MNG, ZoneClass.UZAK, 5, customer_clv_try=8000)
        assert without.churn_try == 0.0
        assert with_clv.churn_try > 0
        assert with_clv.call_center_try == without.call_center_try

    def test_lateness_charge_is_capped(self, delivery):
        """Log-normal kuyrugu tek bir uc ornekle karari belirlememeli."""
        params = DelayCostParams(max_charged_lateness_days=2.0, goodwill_per_day_try=100.0)
        model = DelayCostModel(delivery, params)
        result = model.expected_cost(CarrierCode.SURAT, ZoneClass.UZAK, 1)
        assert result.goodwill_try <= 2.0 * 100.0 + 1e-6

    def test_explain_lines_sum_to_total(self, model):
        result = model.expected_cost(
            CarrierCode.SURAT, ZoneClass.UZAK, 4, is_rural=True, customer_clv_try=6000
        )
        assert sum(amount for _, amount in result.explain_lines()) == pytest.approx(
            result.total_try, abs=0.05
        )

    def test_reports_estimate_provenance(self, model):
        result = model.expected_cost(CarrierCode.ARAS, ZoneClass.BOLGE_ICI, 2)
        assert result.estimate_source in {"hucre", "firma", "genel"}
        assert result.observations > 0
