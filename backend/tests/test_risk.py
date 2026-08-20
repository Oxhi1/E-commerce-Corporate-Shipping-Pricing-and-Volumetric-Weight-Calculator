"""Bayesci hasar modeli ve hasar maliyeti testleri."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from desi_engine.domain import CarrierCode, RiskCategory, ZoneClass
from desi_engine.packing import BoxCatalog, PackingPlanner
from desi_engine.risk import (
    DamageCostModel,
    DamageCostParams,
    DamageRateEstimator,
    fit_concentration,
    posterior,
)
from desi_engine.simulation import TrueWorld
from desi_engine.tariff import TariffRepository

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(scope="session")
def history() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "history" / "shipments.csv")


@pytest.fixture(scope="session")
def estimator(history: pd.DataFrame) -> DamageRateEstimator:
    return DamageRateEstimator().fit(history)


@pytest.fixture(scope="session")
def true_world(tariffs: TariffRepository) -> TrueWorld:
    return TrueWorld.from_tariffs(tariffs)


# ---- Beta-Binom cekirdegi ----------------------------------------------------


class TestBetaPosterior:
    def test_mean_matches_shrinkage_formula(self):
        """Posterior ortalama tam olarak `(kappa*p + d) / (kappa + n)` olmali.

        Bu ozdeslik modelin tum anlatisinin dayanak noktasi; kayarsa "az veri
        varsa onsele yaslaniyoruz" cumlesi dogru olmaktan cikar.
        """
        post = posterior(observations=100, events=5, prior_mean=0.01, kappa=50.0)
        expected = (50.0 * 0.01 + 5) / (50.0 + 100)
        assert post.mean == pytest.approx(expected)

    def test_no_data_returns_prior(self):
        post = posterior(observations=0, events=0, prior_mean=0.012, kappa=200.0)
        assert post.mean == pytest.approx(0.012)
        assert post.shrinkage_weight == pytest.approx(1.0)

    def test_abundant_data_overwhelms_prior(self):
        post = posterior(observations=100_000, events=3_000, prior_mean=0.01, kappa=200.0)
        assert post.mean == pytest.approx(0.03, abs=1e-3)
        assert post.shrinkage_weight < 0.01

    def test_prior_weight_decreases_monotonically_with_data(self):
        weights = [
            posterior(n, int(n * 0.02), 0.01, kappa=100.0).shrinkage_weight
            for n in (1, 10, 100, 1000, 10_000)
        ]
        assert weights == sorted(weights, reverse=True)

    def test_credible_interval_brackets_the_mean(self):
        post = posterior(observations=50, events=2, prior_mean=0.01, kappa=100.0)
        low, high = post.credible_interval(0.90)
        assert low < post.mean < high

    def test_interval_narrows_as_data_grows(self):
        def width(n: int) -> float:
            low, high = posterior(n, int(n * 0.02), 0.01, kappa=100.0).credible_interval()
            return high - low

        assert width(20) > width(200) > width(2000)

    def test_upper_bound_exceeds_mean(self):
        """Riskten kacinan mod, tahminden daima daha kotumser olmali."""
        post = posterior(observations=30, events=0, prior_mean=0.01, kappa=100.0)
        assert post.upper_bound(0.95) > post.mean

    def test_upper_bound_penalises_ignorance_not_performance(self):
        """5 gonderide 0 hasar, 5000 gonderide 0 hasardan daha riskli sayilmali.

        Iki firmanin da ham orani %0. Ust guven siniri kullanildiginda az veriye
        sahip olan kayirilmaz -- "bilmiyoruz", "iyi" demek degildir.
        """
        sparse = posterior(observations=5, events=0, prior_mean=0.01, kappa=100.0)
        rich = posterior(observations=5000, events=0, prior_mean=0.01, kappa=100.0)
        assert sparse.raw_rate == rich.raw_rate == 0.0
        assert sparse.upper_bound(0.95) > rich.upper_bound(0.95)


class TestConcentrationFitting:
    def test_recovers_known_concentration(self):
        """Bilinen bir `kappa` ile uretilmis veriden ayni mertebede `kappa` cikmali."""
        rng = np.random.default_rng(7)
        true_kappa, prior_mean, cells = 120.0, 0.02, 400
        n = np.full(cells, 500)
        p = rng.beta(true_kappa * prior_mean, true_kappa * (1 - prior_mean), size=cells)
        d = rng.binomial(n, p)

        fitted = fit_concentration(n, d, np.full(cells, prior_mean))
        assert 0.4 * true_kappa < fitted < 2.5 * true_kappa

    def test_homogeneous_cells_yield_large_concentration(self):
        """Hucreler arasi gercek fark yoksa model onsele yaslanmali."""
        n = np.full(60, 400)
        d = np.full(60, 8)  # hepsi tam %2
        assert fit_concentration(n, d, np.full(60, 0.02)) > 1000

    def test_empty_input_returns_default(self):
        assert fit_concentration(np.array([]), np.array([]), np.array([])) > 0


# ---- hiyerarsik kestirici ----------------------------------------------------


class TestHierarchicalEstimator:
    def test_requires_fitting_first(self):
        with pytest.raises(RuntimeError, match="fit"):
            DamageRateEstimator().estimate(CarrierCode.ARAS, ZoneClass.UZAK, RiskCategory.SOFT)

    def test_rejects_missing_columns(self):
        with pytest.raises(ValueError, match="eksik sutun"):
            DamageRateEstimator().fit(pd.DataFrame({"carrier": ["ARAS"]}))

    def test_rejects_empty_history(self):
        with pytest.raises(ValueError, match="bos"):
            DamageRateEstimator().fit(
                pd.DataFrame(columns=["carrier", "zone", "risk_category", "damaged"])
            )

    def test_dense_cell_barely_shrinks(self, estimator: DamageRateEstimator):
        """Binlerce gozlemi olan hucre ham orana yakin kalmali."""
        post = estimator.estimate(CarrierCode.ARAS, ZoneClass.BOLGELER_ARASI, RiskCategory.SOFT)
        assert post.observations > 3000
        assert post.shrinkage_weight < 0.10
        assert post.mean == pytest.approx(post.raw_rate, abs=0.002)

    def test_sparse_cell_shrinks_hard(self, estimator: DamageRateEstimator):
        """Bir avuc gozlemi olan hucre ust katmanin ortalamasina cekilmeli."""
        post = estimator.estimate(CarrierCode.PTT, ZoneClass.SEHIR_ICI, RiskCategory.APPLIANCE)
        assert post.observations < 50
        assert post.shrinkage_weight > 0.80
        assert post.mean > 0.0, "ham oran %0 olsa da tahmin sifir olmamali"

    def test_zero_raw_rate_never_becomes_zero_estimate(self, estimator: DamageRateEstimator):
        """Hicbir hucre 'risksiz' ilan edilmemeli.

        Ham oranin sifir olmasi, o hucrede henuz hasar gorulmedigi anlamina gelir;
        hasar imkansiz oldugu anlamina gelmez. Sifir bir tahmin, karar motorunda
        o firmayi sonsuz cazip yapardi.
        """
        frame = estimator.heatmap_frame()
        zero_raw = frame[frame["raw_rate"] == 0.0]
        assert len(zero_raw) > 0, "veri setinde ham orani sifir hucre bulunmali"
        assert (zero_raw["shrunk_rate"] > 0).all()

    def test_shrinkage_beats_raw_rates_against_truth(
        self, estimator: DamageRateEstimator, true_world: TrueWorld
    ):
        """Modelin varlik gerekcesi: gercege ham oranlardan daha yakin olmali.

        Gercek oranlara yalnizca test erisebilir; motor onlari hicbir zaman gormez.
        """
        frame = estimator.heatmap_frame()
        truth = np.array(
            [
                true_world.damage_rate(
                    CarrierCode(row.carrier), ZoneClass(row.zone), RiskCategory(row.risk_category)
                )
                for row in frame.itertuples()
            ]
        )
        raw_error = np.abs(frame["raw_rate"].to_numpy() - truth).mean()
        shrunk_error = np.abs(frame["shrunk_rate"].to_numpy() - truth).mean()
        assert shrunk_error < raw_error

    def test_learns_carrier_regional_weakness(self, estimator: DamageRateEstimator):
        """MNG dogu bolgelerinde belirgin kotu; model bunu veriden bulmali."""
        mng_far = estimator.estimate(CarrierCode.MNG, ZoneClass.UZAK, RiskCategory.FRAGILE)
        mng_near = estimator.estimate(CarrierCode.MNG, ZoneClass.BOLGE_ICI, RiskCategory.FRAGILE)
        assert mng_far.mean > 2 * mng_near.mean

    def test_learns_ptt_strength_in_remote_regions(self, estimator: DamageRateEstimator):
        """PTT uzak bolgelerde MNG'den iyi -- ucuzluk siralamasinin tersine."""
        ptt = estimator.estimate(CarrierCode.PTT, ZoneClass.UZAK, RiskCategory.FRAGILE)
        mng = estimator.estimate(CarrierCode.MNG, ZoneClass.UZAK, RiskCategory.FRAGILE)
        assert ptt.mean < mng.mean

    def test_unseen_cell_falls_back_without_raising(self, history: pd.DataFrame):
        """Gecmiste hic gorulmemis hucre `KeyError` degil, zayif bir tahmin dondurmeli."""
        partial = history[history["carrier"] != "PTT"]
        estimator = DamageRateEstimator().fit(partial)
        post = estimator.estimate(CarrierCode.PTT, ZoneClass.UZAK, RiskCategory.FRAGILE)
        assert post.mean > 0
        assert post.shrinkage_weight == pytest.approx(1.0)

    def test_kappas_reported_per_level(self, estimator: DamageRateEstimator):
        kappas = estimator.kappas
        assert len(kappas) == 3
        assert all(value > 0 for value in kappas.values())


# ---- hasar maliyeti ----------------------------------------------------------


@pytest.fixture(scope="session")
def catalog() -> BoxCatalog:
    return BoxCatalog.from_yaml(DATA_DIR / "boxes" / "catalog.yaml")


class TestDamageCostModel:
    @pytest.fixture
    def model(self, estimator: DamageRateEstimator) -> DamageCostModel:
        return DamageCostModel(estimator)

    def test_dominant_category_is_most_fragile_item(self, model, catalog, towel, porcelain):
        """Icinde cam olan koli, yaninda havlu olsa bile cam kolisidir."""
        planner = PackingPlanner(catalog)
        from desi_engine.domain import Cart, CartLine

        cart = Cart(
            lines=[CartLine(product=towel, quantity=2), CartLine(product=porcelain, quantity=1)]
        )
        plan = planner.plan(cart)
        china_box = next(b for b in plan.boxes if any(p.sku == porcelain.sku for p in b.placements))
        assert model.dominant_category(china_box) is RiskCategory.FRAGILE

    def test_contamination_charged_only_when_liquid_meets_absorbent(
        self, model, catalog, planner_plans
    ):
        together, apart = planner_plans
        loss_together = model.loss_given_damage(together.boxes[0], 0.0)
        assert loss_together.contamination_try > 0

        for box in apart.boxes:
            assert model.loss_given_damage(box, 0.0).contamination_try == 0.0

    def test_separating_liquids_reduces_loss(self, model, planner_plans):
        """Kullanicinin senaryosunun sayisal karsiligi: ayirmak zarari dusurur."""
        together, apart = planner_plans
        loss_together = model.loss_given_damage(together.boxes[0], 0.0).total_try
        worst_apart = max(model.loss_given_damage(b, 0.0).total_try for b in apart.boxes)
        assert worst_apart < loss_together

    def test_fragile_items_lose_more_value_than_textiles(self, model):
        severity = model.params.severity
        assert severity[RiskCategory.FRAGILE] > severity[RiskCategory.SOFT]

    def test_churn_counted_once_across_multiple_parcels(self, model, planner_plans):
        """Iki kolisi de hasar gorse musteri bir kez kaybedilir.

        Koli basina churn eklemek cok parcali gonderileri haksiz cezalandirirdi.
        """
        _, apart = planner_plans
        assert apart.parcel_count >= 2
        clv = 5000.0
        total, _per_box = model.shipment_expected_cost(
            apart.boxes, CarrierCode.ARAS, ZoneClass.UZAK, clv
        )
        naive_sum = sum(
            model.expected_cost(b, CarrierCode.ARAS, ZoneClass.UZAK, clv).expected_try
            for b in apart.boxes
        )
        assert total < naive_sum

    def test_risk_aversion_raises_expected_cost(self, estimator, planner_plans):
        """Riskten kacinan mod daima daha yuksek maliyet uretmeli."""
        together, _ = planner_plans
        neutral = DamageCostModel(estimator, DamageCostParams())
        averse = DamageCostModel(estimator, DamageCostParams(risk_aversion_level=0.95))

        args = (together.boxes[0], CarrierCode.PTT, ZoneClass.UZAK, 1000.0)
        assert averse.expected_cost(*args).expected_try > neutral.expected_cost(*args).expected_try

    def test_low_confidence_flag_set_for_sparse_cells(self, model, planner_plans):
        together, _ = planner_plans
        result = model.expected_cost(together.boxes[0], CarrierCode.PTT, ZoneClass.SEHIR_ICI, 0.0)
        assert result.is_low_confidence is (result.prior_weight > 0.5)

    def test_explain_lines_sum_to_total(self, model, planner_plans):
        together, _ = planner_plans
        loss = model.loss_given_damage(together.boxes[0], 3000.0)
        assert sum(amount for _, amount in loss.explain_lines()) == pytest.approx(
            loss.total_try, abs=0.05
        )


@pytest.fixture
def planner_plans(catalog, contamination_cart):
    """Zeytinyagi + nevresim sepetinin 'birlikte' ve 'ayri' planlari."""
    planner = PackingPlanner(catalog)
    plans = planner.candidates(contamination_cart)
    together = next(p for p in plans if p.contaminating_boxes > 0)
    apart = next(p for p in plans if p.strategy == "sivilar_ayri")
    return together, apart
