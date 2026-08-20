"""Karar motoru testleri.

En onemli iki test burada:

* `test_rejects_cheapest_freight_when_hidden_costs_dominate` -- projenin varlik
  gerekcesi. Kullanicinin zeytinyagi/nevresim ornegi.
* `test_still_picks_cheapest_when_it_is_genuinely_best` -- aksi yondeki koruma.
  Her zaman pahali firmayi seciyorsa motor bir sey ogrenmiyor, sadece pahali
  bir onyargi tasiyor demektir.
"""

from __future__ import annotations

from datetime import time
from pathlib import Path

import pytest

from desi_engine.decision import (
    CapacityLedger,
    CarrierSelector,
    Ineligibility,
    NoEligibleCarrierError,
    ObjectiveParams,
    check_eligibility,
    conditional_value_at_risk,
    tail_premium,
)
from desi_engine.domain import (
    Address,
    CarrierCode,
    Cart,
    CartLine,
    Order,
    Region,
    ZoneClass,
)
from desi_engine.engine import build_engine

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(scope="session")
def engine():
    return build_engine(DATA_DIR)


@pytest.fixture
def selector(engine) -> CarrierSelector:
    return engine.selector


@pytest.fixture(scope="session")
def varied_orders(engine) -> list[Order]:
    """Icerik, varis ili ve musteri degeri bakimindan farklilasan referans siparisler.

    Tek bir siparisle karar davranisi olculemez: motorun ayrim yapip yapmadigi
    ancak farkli girdilerde farkli cevaplar verip vermediginden anlasilir.
    """
    cases = [
        ({"HV-001": 1}, 16, 0.0),  # tek ucuz havlu, sehir ici
        ({"HV-003": 4}, 34, 0.0),  # tekstil, bolge ici
        ({"NV-002": 1, "HV-004": 1}, 6, 1200.0),  # orta deger, bolgeler arasi
        ({"MT-002": 1}, 35, 3000.0),  # porselen, kirilabilir
        ({"GD-001": 1, "NV-002": 1}, 65, 4500.0),  # sivi + emici, uzak
        ({"EA-001": 1}, 27, 2000.0),  # kucuk ev aleti
        ({"DT-001": 2}, 21, 500.0),  # deterjan, guneydogu
        ({"BT-003": 1}, 55, 800.0),  # yorgan, hacimli
        ({"KB-001": 3, "HV-002": 2}, 7, 1500.0),  # karisik sepet
        ({"PR-003": 1}, 25, 2500.0),  # hali, buyuk ve agir
        # Hakkari: Surat hizmet vermiyor, PTT hem uygun hem en ucuz hem de bu
        # bolgede en guclu firma. Ucuz firmanin hakli olarak kazandigi durum.
        ({"HV-004": 1}, 30, 0.0),
    ]
    return [
        Order(
            order_id=f"V-{index:03d}",
            cart=Cart(
                lines=[
                    CartLine(product=engine.product(sku), quantity=qty) for sku, qty in skus.items()
                ]
            ),
            address=Address(
                city_plate=plate,
                city_name=str(plate),
                region=engine.provinces.get(plate).region,
            ),
            customer_clv_try=clv,
        )
        for index, (skus, plate, clv) in enumerate(cases)
    ]


def make_order(engine, skus_qty: dict[str, int], plate: int, region: Region, **kwargs) -> Order:
    return Order(
        order_id=kwargs.pop("order_id", "T-001"),
        cart=Cart(
            lines=[
                CartLine(product=engine.product(sku), quantity=qty) for sku, qty in skus_qty.items()
            ]
        ),
        address=Address(
            city_plate=plate, city_name=str(plate), region=region, **kwargs.pop("address", {})
        ),
        **kwargs,
    )


# ---- amac fonksiyonu matematigi ----------------------------------------------


class TestObjectiveMath:
    def test_cvar_equals_loss_when_probability_exceeds_alpha(self):
        """`p >= alpha` ise en kotu dilimin tamami hasar olaylarindan olusur."""
        assert conditional_value_at_risk(0.10, 1000.0, alpha=0.05) == 1000.0

    def test_cvar_scales_below_alpha(self):
        """`p < alpha` ise dilimin bir kismini saglam gonderiler doldurur."""
        assert conditional_value_at_risk(0.01, 1000.0, alpha=0.05) == pytest.approx(200.0)

    def test_cvar_never_below_expected_value(self):
        for probability in (0.001, 0.01, 0.05, 0.2, 0.9):
            cvar = conditional_value_at_risk(probability, 1000.0)
            assert cvar >= probability * 1000.0 - 1e-9

    def test_tail_premium_is_zero_when_risk_neutral(self):
        assert tail_premium(0.05, 5000.0, lambda_=0.0) == 0.0

    def test_tail_premium_grows_with_lambda(self):
        low = tail_premium(0.02, 5000.0, lambda_=0.5)
        high = tail_premium(0.02, 5000.0, lambda_=2.0)
        assert 0 < low < high

    def test_cost_components_split_visible_and_hidden(self):
        from desi_engine.decision import CostComponents

        components = CostComponents(
            freight_try=400.0, damage_try=50.0, delay_try=30.0, packaging_try=12.0
        )
        assert components.expected_total_try == pytest.approx(492.0)
        assert components.hidden_cost_try == pytest.approx(92.0)

    def test_score_equals_expected_total_when_risk_neutral(self):
        from desi_engine.decision import CostComponents

        components = CostComponents(
            freight_try=400.0, damage_try=50.0, delay_try=30.0, packaging_try=12.0
        )
        assert components.score_try == components.expected_total_try


# ---- uygunluk kisitlari ------------------------------------------------------


class TestEligibility:
    def test_carrier_not_serving_city_is_rejected(self, engine):
        """Surat Hakkari'ye (30) hizmet vermiyor."""
        order = make_order(engine, {"HV-003": 1}, 30, Region.DOGU_ANADOLU)
        plan = engine.planner.plan(order.cart)
        result = check_eligibility(engine.tariffs.get(CarrierCode.SURAT), order, plan)
        assert not result.is_eligible
        assert Ineligibility.UNSERVED_CITY in result.reasons

    def test_parcel_desi_limit_is_plan_dependent(self, engine):
        """PTT parca basina 50 desi kabul eder.

        Ayni sepet, tek koliye sikistirilmis planda PTT icin uygunsuz, iki koliye
        bolunmus planda uygun olabilir. Uygunluk bu yuzden (firma, plan) ciftinde
        denetlenir -- yalnizca firmada degil.
        """
        order = make_order(engine, {"BT-003": 4}, 34, Region.MARMARA)
        ptt = engine.tariffs.get(CarrierCode.PTT)
        plans = engine.planner.candidates(order.cart)

        verdicts = {
            plan.parcel_count: check_eligibility(ptt, order, plan).is_eligible for plan in plans
        }
        assert any(verdicts.values()) or all(
            plan.max_parcel_desi > ptt.constraints.max_desi_per_parcel for plan in plans
        )

    def test_cod_unsupported_carrier_rejected(self, engine):
        order = make_order(engine, {"HV-003": 1}, 34, Region.MARMARA, is_cod=True)
        plan = engine.planner.plan(order.cart)
        tariff = engine.tariffs.get(CarrierCode.ARAS).model_copy(
            update={
                "constraints": engine.tariffs.get(CarrierCode.ARAS).constraints.model_copy(
                    update={"cod_supported": False}
                )
            }
        )
        result = check_eligibility(tariff, order, plan)
        assert Ineligibility.COD_UNSUPPORTED in result.reasons

    def test_cutoff_blocks_late_orders(self, engine):
        order = make_order(engine, {"HV-003": 1}, 34, Region.MARMARA)
        plan = engine.planner.plan(order.cart)
        ptt = engine.tariffs.get(CarrierCode.PTT)  # cutoff 15:30
        assert check_eligibility(ptt, order, plan, order_time=time(14, 0)).is_eligible
        assert not check_eligibility(ptt, order, plan, order_time=time(16, 0)).is_eligible

    def test_ineligible_carrier_has_human_readable_reason(self, engine):
        order = make_order(engine, {"HV-003": 1}, 30, Region.DOGU_ANADOLU)
        plan = engine.planner.plan(order.cart)
        result = check_eligibility(engine.tariffs.get(CarrierCode.SURAT), order, plan)
        assert "hizmet vermiyor" in result.describe()


class TestCapacityLedger:
    def test_unlimited_when_no_limit_configured(self):
        ledger = CapacityLedger()
        assert ledger.has_room(CarrierCode.ARAS, parcels=10_000)

    def test_blocks_once_limit_reached(self):
        ledger = CapacityLedger(daily_limits={CarrierCode.YURTICI: 3})
        ledger.consume(CarrierCode.YURTICI, 2)
        assert ledger.has_room(CarrierCode.YURTICI, 1)
        ledger.consume(CarrierCode.YURTICI, 1)
        assert not ledger.has_room(CarrierCode.YURTICI, 1)

    def test_reset_frees_capacity(self):
        ledger = CapacityLedger(daily_limits={CarrierCode.YURTICI: 1})
        ledger.consume(CarrierCode.YURTICI)
        ledger.reset()
        assert ledger.has_room(CarrierCode.YURTICI)

    def test_capacity_pressure_changes_the_decision(self, engine, selector):
        """Tercih edilen firmanin kapasitesi dolunca motor ikinciye gecmeli."""
        order = make_order(engine, {"GD-001": 1, "NV-002": 1}, 65, Region.DOGU_ANADOLU)
        unconstrained = selector.decide(order)

        ledger = CapacityLedger(daily_limits={CarrierCode(unconstrained.selected.carrier): 0})
        constrained = selector.decide(order, ledger=ledger)
        assert constrained.selected.carrier != unconstrained.selected.carrier


# ---- karar davranisi ---------------------------------------------------------


class TestDecisionBehaviour:
    def test_rejects_cheapest_freight_when_hidden_costs_dominate(self, engine, selector):
        """Van'a giden zeytinyagi + nevresim: motor en ucuz nakliyeyi reddetmeli.

        Kullanicinin 3. maddesinin dogrudan sinavi ve projenin kabul kriteri.
        """
        order = make_order(
            engine,
            {"GD-001": 1, "NV-002": 1},
            65,
            Region.DOGU_ANADOLU,
            customer_clv_try=4500.0,
        )
        decision = selector.decide(order)

        assert decision.overrode_cheapest_freight, "en ucuz nakliye secilmemeliydi"
        assert decision.savings_vs_cheapest_freight_try > 0

        cheapest = decision.cheapest_freight
        assert cheapest is not None
        assert cheapest.freight_try < decision.selected.freight_try
        assert cheapest.expected_total_try > decision.selected.expected_total_try

    def test_override_is_justified_numerically_in_the_rationale(self, engine, selector):
        """Gerekce, reddedilen ucuz firmayi ve sayisal sebebini icermeli."""
        order = make_order(
            engine, {"GD-001": 1, "NV-002": 1}, 65, Region.DOGU_ANADOLU, customer_clv_try=4500.0
        )
        decision = selector.decide(order)
        text = " ".join(decision.rationale)

        assert "En ucuz nakliye" in text
        assert "secilmedi" in text
        assert "hasar olasiligi" in text or "gecikme olasiligi" in text

    def test_selection_is_not_a_constant(self, engine, selector, varied_orders):
        """Motor tek bir firmaya kilitlenmemeli.

        Bir onceki testin karsiti kadar onemli: her siparise ayni cevabi veren bir
        motor bir sey ogrenmiyor, sadece sabit bir onyargi tasiyor demektir.
        Sepet icerigi, varis ili ve musteri degeri degistikce kazanan da degismeli.
        """
        chosen = {selector.decide(order).selected.carrier for order in varied_orders}
        assert len(chosen) >= 3, f"yalnizca {chosen} secildi -- motor ayrim yapmiyor"

    def test_does_not_default_to_the_premium_carrier(self, selector, varied_orders):
        """En pahali firma (Yurtici) her zaman secilmemeli."""
        picks = [selector.decide(order).selected.carrier for order in varied_orders]
        premium_share = picks.count(CarrierCode.YURTICI.value) / len(picks)
        assert premium_share < 0.7, f"Yurtici payi %{premium_share * 100:.0f} -- pahaliya onyargi"

    def test_cheapest_freight_sometimes_wins(self, selector, varied_orders):
        """Bazi siparislerde en ucuz nakliye gercekten en iyi secimdir.

        Motor her zaman en ucuzu reddediyorsa, "gizli maliyet" terimleri sagduyuyu
        bastiriyor demektir; bu durumda parametreler fazla agresif olurdu.
        """
        decisions = [selector.decide(order) for order in varied_orders]
        assert any(not d.overrode_cheapest_freight for d in decisions)

    def test_override_never_costs_more_in_expectation(self, selector, varied_orders):
        """En ucuzu reddetmek her zaman beklenen toplamda kazanc saglamali.

        Skor minimize edildigi icin bu bir ozdeslik olmali; kirilmasi, siralama
        ile raporlanan tasarrufun farkli buyukluklerden hesaplandigini gosterir.
        """
        for order in varied_orders:
            decision = selector.decide(order)
            assert decision.savings_vs_cheapest_freight_try >= 0.0

    def test_selects_liquid_separation_for_contaminating_carts(self, engine, selector):
        order = make_order(engine, {"GD-001": 1, "NV-002": 1}, 65, Region.DOGU_ANADOLU)
        decision = selector.decide(order)
        assert decision.selected.contaminating_boxes == 0

    def test_ranking_is_sorted_by_score(self, engine, selector):
        order = make_order(engine, {"MT-002": 1, "HV-003": 2}, 21, Region.GUNEYDOGU_ANADOLU)
        decision = selector.decide(order)
        scores = [e.score_try for e in decision.ranked]
        assert scores == sorted(scores)
        assert decision.selected is decision.ranked[0]

    def test_margin_measures_gap_to_runner_up(self, engine, selector):
        order = make_order(engine, {"NV-002": 2}, 6, Region.IC_ANADOLU)
        decision = selector.decide(order)
        assert decision.margin_try == pytest.approx(
            decision.runner_up.score_try - decision.selected.score_try, abs=0.01
        )
        assert decision.margin_try >= 0

    def test_every_carrier_appears_exactly_once(self, engine, selector):
        order = make_order(engine, {"HV-003": 2}, 30, Region.DOGU_ANADOLU)
        decision = selector.decide(order)
        seen = [e.carrier for e in decision.ranked] + [e.carrier for e in decision.rejected]
        assert sorted(seen) == sorted(c.value for c in CarrierCode)

    def test_unserved_city_pushes_carrier_into_rejected_list(self, engine, selector):
        order = make_order(engine, {"HV-003": 1}, 30, Region.DOGU_ANADOLU)
        decision = selector.decide(order)
        assert CarrierCode.SURAT.value in {e.carrier for e in decision.rejected}

    def test_raises_when_no_carrier_can_serve(self, engine, selector):
        """Hicbir firma tasiyamiyorsa sessizce en yakinini secmek yerine patlamali.

        Operasyona dusmesi gereken bir durumu gizlemek, depoda hizmet verilmeyen
        bir ile etiket bastirmak demektir.
        """
        order = make_order(engine, {"HV-003": 1}, 34, Region.MARMARA)
        empty_ledger = CapacityLedger(daily_limits={c: 0 for c in CarrierCode})
        with pytest.raises(NoEligibleCarrierError, match="uygun firma yok"):
            selector.decide(order, ledger=empty_ledger)

    def test_synthetic_tariff_warning_is_always_present(self, engine, selector):
        order = make_order(engine, {"HV-003": 1}, 34, Region.MARMARA)
        decision = selector.decide(order)
        assert any("ORNEK TARIFE" in w for w in decision.warnings)

    def test_cost_components_sum_to_expected_total(self, engine, selector):
        order = make_order(engine, {"GD-001": 1, "NV-002": 1}, 65, Region.DOGU_ANADOLU)
        for evaluation in selector.decide(order).ranked:
            components = evaluation.components
            assert sum(a for _, a in components.explain_lines()) == pytest.approx(
                components.score_try, abs=0.05
            )


# ---- riskten kacinma ---------------------------------------------------------


class TestRiskAversion:
    def test_risk_aversion_raises_every_score(self, engine):
        order = make_order(engine, {"MT-002": 1}, 65, Region.DOGU_ANADOLU, customer_clv_try=6000.0)
        neutral = engine.selector.decide(order)

        averse_engine = build_engine(DATA_DIR, objective=ObjectiveParams(risk_aversion_lambda=1.5))
        averse = averse_engine.selector.decide(order)

        neutral_scores = {e.carrier: e.score_try for e in neutral.ranked}
        for evaluation in averse.ranked:
            assert evaluation.score_try >= neutral_scores[evaluation.carrier] - 1e-6

    def test_risk_aversion_leaves_expected_totals_untouched(self, engine):
        """Kuyruk primi bir skor duzeltmesidir, para beklentisi degil.

        Ikisi karisirsa 'ne kadar tasarruf ettik' raporu, gerceklesmeyecek bir
        primi tasarruf gibi gosterirdi.
        """
        order = make_order(engine, {"MT-002": 1}, 65, Region.DOGU_ANADOLU)
        neutral = {e.carrier: e.expected_total_try for e in engine.selector.decide(order).ranked}

        averse_engine = build_engine(DATA_DIR, objective=ObjectiveParams(risk_aversion_lambda=2.0))
        for evaluation in averse_engine.selector.decide(order).ranked:
            assert evaluation.expected_total_try == pytest.approx(
                neutral[evaluation.carrier], abs=0.01
            )


# ---- motor kurulumu ----------------------------------------------------------


class TestEngineAssembly:
    def test_loads_all_data_sources(self, engine):
        assert len(engine.tariffs) == 5
        assert len(engine.provinces) == 81
        assert len(engine.box_catalog) == 13
        assert len(engine.products) >= 40
        assert not engine.history.empty

    def test_unknown_sku_raises_clear_error(self, engine):
        with pytest.raises(KeyError, match="Katalogda bulunmayan SKU"):
            engine.product("YOK-999")

    def test_reports_synthetic_tariff_usage(self, engine):
        assert engine.uses_synthetic_tariffs is True

    def test_zone_resolution_matches_registry(self, engine, selector):
        order = make_order(engine, {"HV-003": 1}, 65, Region.DOGU_ANADOLU)
        assert selector.decide(order).zone is ZoneClass.UZAK
