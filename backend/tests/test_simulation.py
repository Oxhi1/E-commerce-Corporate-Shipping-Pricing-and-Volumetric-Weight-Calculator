"""Monte Carlo simulasyonu testleri.

Simulasyonun kendisi bir olcum araci; olcum aracinin dogrulanmasi olculen seyden
daha kritik. Uc sey teminat altina aliniyor:

* **Tekrarlanabilirlik** -- ayni tohum, ayni sonuc. Yoksa hicbir bulgu
  dogrulanamaz.
* **Adil karsilastirma** -- tum politikalar birebir ayni siparisleri ve ayni
  sans cekilislerini gorur.
* **Istatistiksel durustluk** -- guven araligi sifiri kapsiyorsa rapor bunu
  "anlamsiz" olarak isaretler, sayiyi yuvarlayip gecmez.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from desi_engine.domain import CarrierCode, PolicyCode
from desi_engine.engine import build_engine
from desi_engine.simulation import (
    BASKET_ARCHETYPES,
    CheapestFreightPolicy,
    FastestPolicy,
    OrderGenerator,
    OrderGeneratorConfig,
    SimulationConfig,
    SimulationRunner,
    SingleCarrierPolicy,
    TotalCostPolicy,
    TrueWorld,
    calibration_curve,
    calibration_error,
    paired_bootstrap,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

#: Testlerde kullanilan kosu boyutu. Istatistiksel iddialar icin kucuk ama
#: yapisal dogrulamalar icin yeterli; tam kosu `scripts/run_simulation.py`.
TEST_ORDERS = 400


@pytest.fixture(scope="session")
def engine():
    return build_engine(DATA_DIR)


@pytest.fixture(scope="session")
def result(engine):
    return SimulationRunner(engine, SimulationConfig(n_orders=TEST_ORDERS, seed=7)).run()


# ---- siparis ureteci ---------------------------------------------------------


class TestOrderGenerator:
    @pytest.fixture
    def generator(self, engine) -> OrderGenerator:
        return OrderGenerator(engine.products, engine.provinces)

    def test_is_reproducible(self, generator):
        first = generator.generate(50, np.random.default_rng(1))
        second = generator.generate(50, np.random.default_rng(1))
        assert [o.address.city_plate for o in first] == [o.address.city_plate for o in second]
        assert [o.cart.total_value_try for o in first] == [o.cart.total_value_try for o in second]

    def test_different_seeds_give_different_streams(self, generator):
        first = generator.generate(50, np.random.default_rng(1))
        second = generator.generate(50, np.random.default_rng(2))
        assert [o.address.city_plate for o in first] != [o.address.city_plate for o in second]

    def test_destination_follows_population(self, generator):
        """Istanbul'a Bayburt'tan cok daha fazla siparis gitmeli."""
        orders = generator.generate(3000, np.random.default_rng(5))
        plates = [o.address.city_plate for o in orders]
        assert plates.count(34) > plates.count(69) * 10

    def test_produces_contamination_carts(self, generator):
        """Hipermarket arketipi sivi + emici sepetler uretmeli.

        Bagimsiz urun cekilisi bu senaryoyu neredeyse hic uretmezdi ve projenin
        en ilginc karar durumu simulasyonda hic gorulmezdi.
        """
        orders = generator.generate(600, np.random.default_rng(3))
        risky = [o for o in orders if o.cart.has_contamination_risk]
        assert len(risky) > 10, "kontaminasyon senaryosu neredeyse hic uretilmiyor"

    def test_some_customers_have_no_history(self, generator):
        """Ilk siparisini veren musterilerin CLV'si sifir olmali.

        Herkese pozitif CLV atamak churn maliyetini tum siparislere yayar ve
        motoru her yerde pahali firma secmeye iter.
        """
        orders = generator.generate(500, np.random.default_rng(4))
        clvs = [o.customer_clv_try for o in orders]
        assert any(c == 0.0 for c in clvs)
        assert any(c > 0.0 for c in clvs)

    def test_archetype_weights_sum_to_one(self):
        assert sum(a.weight for a in BASKET_ARCHETYPES) == pytest.approx(1.0)

    def test_rejects_catalog_missing_archetype_categories(self, engine):
        towels_only = {
            sku: product
            for sku, product in engine.products.items()
            if product.category.value == "havlu"
        }
        with pytest.raises(ValueError, match="kategorilerde urun yok"):
            OrderGenerator(towels_only, engine.provinces)

    def test_cod_share_is_respected(self, engine):
        generator = OrderGenerator(
            engine.products, engine.provinces, OrderGeneratorConfig(cod_share=0.5)
        )
        orders = generator.generate(1000, np.random.default_rng(9))
        share = sum(o.is_cod for o in orders) / len(orders)
        assert 0.44 < share < 0.56


# ---- gercek dunya ------------------------------------------------------------


class TestTrueWorld:
    @pytest.fixture
    def world(self, engine) -> TrueWorld:
        return TrueWorld.from_tariffs(engine.tariffs)

    def test_damage_rate_rises_with_distance_and_fragility(self, world):
        from desi_engine.domain import RiskCategory, ZoneClass

        near_soft = world.damage_rate(CarrierCode.ARAS, ZoneClass.SEHIR_ICI, RiskCategory.SOFT)
        far_fragile = world.damage_rate(CarrierCode.ARAS, ZoneClass.UZAK, RiskCategory.FRAGILE)
        assert far_fragile > near_soft * 5

    def test_on_time_rate_is_bounded(self, world):
        from desi_engine.domain import ZoneClass

        for carrier in CarrierCode:
            for zone in ZoneClass:
                for rural in (False, True):
                    rate = world.on_time_rate(carrier, zone, is_rural=rural)
                    assert 0.0 < rate < 1.0

    def test_distribution_matches_requested_on_time_rate(self, world):
        """Kurulus hedefiyle dagilimin urettigi olasilik tutarli olmali."""
        from desi_engine.domain import ZoneClass

        for carrier in (CarrierCode.YURTICI, CarrierCode.SURAT):
            for zone in (ZoneClass.BOLGE_ICI, ZoneClass.UZAK):
                sla = world._sla[(carrier, zone, False)]
                distribution = world.delivery_distribution(carrier, zone)
                expected_late = 1.0 - world.on_time_rate(carrier, zone)
                assert distribution.probability_late(sla) == pytest.approx(expected_late, abs=1e-6)

    def test_rural_is_slower(self, world):
        from desi_engine.domain import ZoneClass

        urban = world.delivery_distribution(CarrierCode.ARAS, ZoneClass.BOLGELER_ARASI)
        rural = world.delivery_distribution(
            CarrierCode.ARAS, ZoneClass.BOLGELER_ARASI, is_rural=True
        )
        assert rural.median_days > urban.median_days

    def test_cheap_carriers_have_regional_strengths(self, world):
        """Ucuz firmalar her yerde kotu olmamali.

        Aksi halde "hep pahaliyi sec" kurali motorla ayni sonucu verir ve proje
        bir sey ogretmez. PTT uzak bolgelerde, Surat sehir icinde guclu.
        """
        from desi_engine.domain import ZoneClass

        ptt_far = world.on_time_rate(CarrierCode.PTT, ZoneClass.UZAK)
        ptt_near = world.on_time_rate(CarrierCode.PTT, ZoneClass.BOLGELER_ARASI)
        assert ptt_far > ptt_near

        surat_local = world.on_time_rate(CarrierCode.SURAT, ZoneClass.SEHIR_ICI)
        surat_far = world.on_time_rate(CarrierCode.SURAT, ZoneClass.UZAK)
        assert surat_local > surat_far


# ---- politikalar -------------------------------------------------------------


class TestPolicies:
    @pytest.fixture
    def evaluations(self, engine):
        from desi_engine.domain import Address, Cart, CartLine, Order

        order = Order(
            order_id="P-001",
            cart=Cart(
                lines=[
                    CartLine(product=engine.product("GD-001"), quantity=1),
                    CartLine(product=engine.product("NV-002"), quantity=1),
                ]
            ),
            address=Address(city_plate=65, city_name="Van", region=engine.provinces.get(65).region),
            customer_clv_try=3000.0,
        )
        return engine.selector.evaluate_all(order)

    def test_cheapest_freight_policy_minimises_freight(self, evaluations):
        chosen = CheapestFreightPolicy().choose(evaluations, None)
        eligible = [e for e in evaluations if e.eligible]
        assert chosen.freight_try == min(e.freight_try for e in eligible)

    def test_fastest_policy_minimises_delivery_days(self, evaluations):
        chosen = FastestPolicy().choose(evaluations, None)
        eligible = [e for e in evaluations if e.eligible and e.delay]
        assert chosen.delay.expected_days == min(e.delay.expected_days for e in eligible)

    def test_total_cost_policy_minimises_score(self, evaluations):
        chosen = TotalCostPolicy().choose(evaluations, None)
        assert chosen.score_try == min(e.score_try for e in evaluations if e.eligible)

    def test_single_carrier_policy_prefers_its_carrier(self, evaluations):
        chosen = SingleCarrierPolicy(CarrierCode.MNG).choose(evaluations, None)
        assert chosen.carrier == CarrierCode.MNG.value

    def test_single_carrier_falls_back_when_unavailable(self, engine):
        """Tercih edilen firma hizmet vermiyorsa gonderi yine de yola cikmali."""
        from desi_engine.domain import Address, Cart, CartLine, Order

        order = Order(
            order_id="P-002",
            cart=Cart(lines=[CartLine(product=engine.product("HV-003"), quantity=1)]),
            address=Address(
                city_plate=30, city_name="Hakkari", region=engine.provinces.get(30).region
            ),
        )
        evaluations = engine.selector.evaluate_all(order)
        chosen = SingleCarrierPolicy(CarrierCode.SURAT).choose(evaluations, None)
        assert chosen is not None
        assert chosen.carrier != CarrierCode.SURAT.value

    def test_policy_returns_none_when_nothing_eligible(self):
        assert TotalCostPolicy().choose([], None) is None


# ---- istatistik --------------------------------------------------------------


class TestStatistics:
    def test_paired_bootstrap_detects_a_real_difference(self):
        rng = np.random.default_rng(2)
        baseline = rng.normal(400, 50, size=3000)
        treatment = baseline - 12.0 + rng.normal(0, 3, size=3000)

        comparison = paired_bootstrap(
            baseline, treatment, baseline_name="A", treatment_name="B", rng=rng
        )
        assert comparison.mean_difference == pytest.approx(12.0, abs=0.6)
        assert comparison.is_significant

    def test_paired_bootstrap_reports_no_difference_honestly(self):
        """Gercek bir fark yoksa rapor bunu soylemeli, sayiyi yuvarlamamali."""
        rng = np.random.default_rng(3)
        baseline = rng.normal(400, 50, size=2000)
        treatment = baseline + rng.normal(0, 50, size=2000)

        comparison = paired_bootstrap(
            baseline, treatment, baseline_name="A", treatment_name="B", rng=rng
        )
        assert not comparison.is_significant
        assert "ANLAMSIZ" in comparison.describe()

    def test_pairing_tightens_the_interval(self):
        """Eslestirme, siparis buyuklugu varyansini farktan cikarmali.

        Ortak rastgele sayilarin butun degeri bu: eslestirmeden yapilan bir
        bootstrap, gercek bir kazanci "anlamsiz" gosterebilir.
        """
        rng = np.random.default_rng(4)
        baseline = rng.normal(400, 120, size=1500)
        treatment = baseline - 8.0 + rng.normal(0, 5, size=1500)

        paired = paired_bootstrap(
            baseline,
            treatment,
            baseline_name="A",
            treatment_name="B",
            rng=np.random.default_rng(10),
        )
        shuffled = rng.permutation(treatment)
        unpaired = paired_bootstrap(
            baseline,
            shuffled,
            baseline_name="A",
            treatment_name="B",
            rng=np.random.default_rng(10),
        )
        assert (paired.ci_high - paired.ci_low) < (unpaired.ci_high - unpaired.ci_low)

    def test_rejects_mismatched_lengths(self):
        with pytest.raises(ValueError, match="ayni uzunlukta"):
            paired_bootstrap(np.zeros(5), np.zeros(6), baseline_name="A", treatment_name="B")

    def test_calibration_curve_is_perfect_for_honest_predictions(self):
        rng = np.random.default_rng(6)
        predicted = rng.uniform(0.01, 0.4, size=40_000)
        observed = (rng.random(40_000) < predicted).astype(float)
        assert calibration_error(calibration_curve(predicted, observed)) < 0.02

    def test_calibration_curve_detects_overconfidence(self):
        """Sistematik olarak iki kat abartan bir model yakalanmali."""
        rng = np.random.default_rng(6)
        truth = rng.uniform(0.01, 0.2, size=30_000)
        observed = (rng.random(30_000) < truth).astype(float)
        assert calibration_error(calibration_curve(truth * 2, observed)) > 0.05

    def test_calibration_handles_empty_input(self):
        assert calibration_curve(np.array([]), np.array([])) == []


# ---- uctan uca kosu ----------------------------------------------------------


class TestSimulationRun:
    def test_is_reproducible(self, engine):
        config = SimulationConfig(n_orders=200, seed=11)
        first = SimulationRunner(engine, config).run()
        second = SimulationRunner(engine, config).run()
        for code, summary in first.summaries.items():
            assert summary.total_cost_try == second.summaries[code].total_cost_try
            assert summary.damage_count == second.summaries[code].damage_count

    def test_all_policies_see_the_same_orders(self, result):
        """Ortak rastgele sayilarin on kosulu: ayni siparis kumesi.

        Politikalar farkli sayida siparis islerse eslestirilmis bootstrap
        gecersizlesir ve guven araliklari anlamini yitirir.
        """
        counts = {summary.orders for summary in result.summaries.values()}
        assert len(counts) == 1, f"politikalar farkli sayida siparis isledi: {counts}"

    def test_every_policy_is_reported(self, result):
        assert set(result.summaries) == set(PolicyCode)

    def test_no_orders_left_unserved(self, result):
        assert all(summary.unserved_orders == 0 for summary in result.summaries.values())

    def test_engine_beats_the_status_quo(self, result):
        """Projenin ana iddiasi: TELC, tek firma ve en-ucuz-nakliyeden ucuz."""
        telc = result.summaries[PolicyCode.P3_TELC].cost_per_order_try
        single = result.summaries[PolicyCode.P0_SINGLE_CARRIER].cost_per_order_try
        cheapest = result.summaries[PolicyCode.P1_CHEAPEST_FREIGHT].cost_per_order_try
        assert telc < single
        assert telc < cheapest

    def test_cheapest_freight_wins_on_freight_but_loses_overall(self, result):
        """En ucuz nakliye politikasi faturayi dusurur, toplam maliyeti yukseltir.

        Projenin en carpici bulgusu bu; testin kirilmasi ya modelin ya da
        anlatinin degistigi anlamina gelir.
        """
        cheapest = result.summaries[PolicyCode.P1_CHEAPEST_FREIGHT]
        telc = result.summaries[PolicyCode.P3_TELC]
        assert cheapest.freight_per_order_try < telc.freight_per_order_try
        assert cheapest.cost_per_order_try > telc.cost_per_order_try

    def test_fastest_policy_actually_delivers_fastest(self, result):
        fastest = result.summaries[PolicyCode.P2_FASTEST].mean_delivery_days
        assert fastest == min(s.mean_delivery_days for s in result.summaries.values())

    def test_comparisons_carry_confidence_intervals(self, result):
        assert result.comparisons
        for comparison in result.comparisons:
            assert comparison.ci_low <= comparison.mean_difference <= comparison.ci_high

    def test_headline_is_produced(self, result):
        assert "tasarruf" in result.headline()

    def test_calibration_is_reasonable(self, result):
        """Motorun hasar tahminleri gerceklesen frekansa yakin olmali."""
        assert result.calibration
        assert result.calibration_error < 0.05

    def test_capacity_constraint_spreads_the_volume(self, engine):
        """P4, hacmi P3'ten daha dengeli dagitmali.

        P3 kapasiteyi yok sayip en iyi firmaya yigar; gercek hayatta o firma
        "bugunluk yeter" der. Aradaki fark, kisiti yok saymanin maliyetidir.
        """
        result = SimulationRunner(
            engine, SimulationConfig(n_orders=600, seed=13, days=6, capacity_share=0.30)
        ).run()

        def concentration(code: PolicyCode) -> float:
            mix = result.summaries[code].carrier_mix
            return max(mix.values()) / sum(mix.values())

        assert concentration(PolicyCode.P4_TELC_CONSTRAINED) < concentration(PolicyCode.P3_TELC)

    def test_carrier_mix_uses_more_than_one_carrier(self, result):
        mix = result.summaries[PolicyCode.P3_TELC].carrier_mix
        assert len(mix) >= 3, f"motor yalnizca {list(mix)} kullaniyor"
