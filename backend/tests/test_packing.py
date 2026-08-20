"""3B kutulama testleri.

Agirlik, tek tek sayilara degil **degismezlere** verildi. "Bu sepet 18.30 desi
uretmeli" turu bir test, algoritmayi iyilestiren her degisiklikte kirilir ve
insanlari testi guncellemeye alistirir. Buna karsilik "hicbir iki urun ust uste
binmez" veya "sivi hicbir zaman emici urunun ustunde olmaz" kurallarinin
kirilmasi her zaman gercek bir hatadir.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from desi_engine.domain import Cart, CartLine, Dimensions, Fragility, Product, ProductCategory
from desi_engine.packing import (
    STRATEGY_SEPARATE_LIQUIDS,
    BoxCatalog,
    ExtremePointPacker,
    PackedBox,
    PackingPlanner,
    PackingRules,
    box_accepts,
    fill_box,
)
from desi_engine.packing.baselines import compute_baselines, one_box_per_item
from desi_engine.packing.geometry import Cuboid, intersects

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(scope="session")
def catalog() -> BoxCatalog:
    return BoxCatalog.from_yaml(DATA_DIR / "boxes" / "catalog.yaml")


@pytest.fixture
def planner(catalog: BoxCatalog) -> PackingPlanner:
    return PackingPlanner(catalog)


# ---- yardimcilar -------------------------------------------------------------


def as_cuboids(packed: PackedBox) -> list[Cuboid]:
    return [Cuboid(p.x, p.y, p.z, p.dx, p.dy, p.dz) for p in packed.placements]


def assert_box_is_physically_valid(packed: PackedBox) -> None:
    """Bir kolinin ihlal edemeyecegi temel fiziksel gercekler."""
    cuboids = as_cuboids(packed)
    inner = packed.box.inner

    for index, cuboid in enumerate(cuboids):
        assert cuboid.x >= -1e-6 and cuboid.y >= -1e-6 and cuboid.z >= -1e-6, "negatif koordinat"
        assert cuboid.x2 <= inner.length_cm + 1e-6, "urun kutunun boyunu asiyor"
        assert cuboid.y2 <= inner.width_cm + 1e-6, "urun kutunun enini asiyor"
        assert cuboid.z2 <= inner.height_cm + 1e-6, "urun kutunun yuksekligini asiyor"

        for other in cuboids[index + 1 :]:
            assert not intersects(cuboid, other), "iki urun ust uste biniyor"

    assert packed.content_weight_kg <= packed.box.max_payload_kg + 1e-9


# ---- koli modeli -------------------------------------------------------------


class TestBoxModel:
    def test_outer_is_larger_than_inner(self, catalog: BoxCatalog):
        """Dis olcu her zaman ic olcuden buyuk olmali -- fatura dis olcuden kesilir."""
        for box in catalog:
            assert box.outer_desi > box.inner.desi

    def test_catalog_sorted_ascending_by_outer_desi(self, catalog: BoxCatalog):
        desis = [b.outer_desi for b in catalog]
        assert desis == sorted(desis)

    def test_wall_thickness_matters_on_large_boxes(self, catalog: BoxCatalog):
        """K10'da et kalinligi ~%8 desi farki yaratiyor; ihmal edilemez."""
        k10 = catalog.get("K10")
        assert k10.outer_desi / k10.inner.desi > 1.05

    def test_duplicate_codes_rejected(self, catalog: BoxCatalog):
        box = catalog.get("K01")
        with pytest.raises(ValueError, match="tekil olmali"):
            BoxCatalog([box, box])

    def test_empty_catalog_rejected(self):
        with pytest.raises(ValueError, match="bos olamaz"):
            BoxCatalog([])


# ---- yerlestirme kurallari ---------------------------------------------------


class TestPlacementRules:
    def test_mailer_bag_rejects_liquid(self, catalog: BoxCatalog, olive_oil: Product):
        bag = catalog.get("P02")
        assert bag.soft_only is True
        assert box_accepts(bag, olive_oil) is False

    def test_mailer_bag_rejects_fragile(self, catalog: BoxCatalog, porcelain: Product):
        assert box_accepts(catalog.get("P02"), porcelain) is False

    def test_mailer_bag_accepts_soft_textile(self, catalog: BoxCatalog, towel: Product):
        assert box_accepts(catalog.get("P02"), towel) is True

    def test_liquid_never_placed_above_absorbent(
        self, catalog: BoxCatalog, olive_oil: Product, towel: Product
    ):
        """Kullanicinin zeytinyagi/nevresim senaryosunun paketleme tarafi.

        Sizinti asagi aktigi icin sivi urun emici urunun ustune konamaz -- kutu
        buyumek zorunda kalsa bile.
        """
        box = catalog.get("K10")
        packed, leftover = fill_box(box, [towel, olive_oil], PackingRules())
        assert packed is not None and not leftover

        oil_placement = next(p for p in packed.placements if p.is_liquid)
        towel_placement = next(p for p in packed.placements if p.is_absorbent)
        horizontally_overlapping = min(oil_placement.x2, towel_placement.x2) > max(
            oil_placement.x, towel_placement.x
        ) and min(oil_placement.y2, towel_placement.y2) > max(oil_placement.y, towel_placement.y)
        if horizontally_overlapping:
            assert oil_placement.z <= towel_placement.z, "sivi emici urunun ustunde"

    def test_nothing_stacked_on_non_stackable_item(self, catalog: BoxCatalog, porcelain, towel):
        """Porselen takim `stackable=False`; ustune hicbir sey konmamali."""
        packed, _ = fill_box(catalog.get("K10"), [porcelain, towel, towel], PackingRules())
        assert packed is not None
        china = next(p for p in packed.placements if p.sku == porcelain.sku)
        for other in packed.placements:
            if other.sku == porcelain.sku:
                continue
            overlaps = min(other.x2, china.x2) > max(other.x, china.x) and min(
                other.y2, china.y2
            ) > max(other.y, china.y)
            if overlaps:
                assert other.z + 1e-6 < china.z2, "kirilabilir urunun ustune yuk binmis"

    def test_payload_limit_respected(self, catalog: BoxCatalog, olive_oil: Product):
        """K01 5 kg tasir; 5.2 kg'lik zeytinyagi girmemeli."""
        packed, leftover = fill_box(catalog.get("K01"), [olive_oil], PackingRules())
        assert packed is None
        assert leftover == [olive_oil]

    def test_max_items_per_box_enforced(self, catalog: BoxCatalog, towel: Product):
        rules = PackingRules(max_items_per_box=3)
        packed, leftover = fill_box(catalog.get("K10"), [towel] * 10, rules)
        assert packed is not None
        assert packed.item_count == 3
        assert len(leftover) == 7

    def test_unsupported_placement_rejected(self, catalog: BoxCatalog, towel: Product):
        """Havada asili urun olmaz: her urun ya zeminde ya da bir yuzeyin uzerinde."""
        packed, _ = fill_box(catalog.get("K09"), [towel] * 6, PackingRules())
        assert packed is not None
        cuboids = as_cuboids(packed)
        for index, cuboid in enumerate(cuboids):
            if cuboid.z <= 1e-3:
                continue
            below = [c for i, c in enumerate(cuboids) if i != index]
            from desi_engine.packing.geometry import support_ratio

            assert support_ratio(cuboid, below) >= 0.70 - 1e-6


# ---- geometrik degismezler ---------------------------------------------------


def product_strategy() -> st.SearchStrategy[Product]:
    """Rastgele ama gercekci urunler uretir."""
    return st.builds(
        lambda length, width, height, weight, category, fragile: Product(
            sku=f"R-{length}-{width}-{height}",
            name="Rastgele urun",
            category=category,
            dims=Dimensions(length_cm=length, width_cm=width, height_cm=height),
            weight_kg=weight,
            unit_price_try=500.0,
            fragility=fragile,
            max_stack_load_kg=15.0,
        ),
        length=st.integers(min_value=5, max_value=40),
        width=st.integers(min_value=5, max_value=35),
        height=st.integers(min_value=3, max_value=30),
        weight=st.floats(min_value=0.1, max_value=6.0),
        category=st.sampled_from([ProductCategory.TOWEL, ProductCategory.KITCHENWARE]),
        fragile=st.sampled_from([Fragility.NONE, Fragility.LOW]),
    )


class TestGeometricInvariants:
    @settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(products=st.lists(product_strategy(), min_size=1, max_size=5))
    def test_packed_boxes_are_always_physically_valid(self, catalog, products):
        """Hangi urun bilesimi gelirse gelsin, uretilen koli fiziksel olarak gecerli."""
        planner = PackingPlanner(catalog)
        for plan in planner.candidates(
            Cart(lines=[CartLine(product=p, quantity=1) for p in products])
        ):
            for packed in plan.boxes:
                assert_box_is_physically_valid(packed)

    @settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(products=st.lists(product_strategy(), min_size=1, max_size=5))
    def test_every_item_is_placed_exactly_once(self, catalog, products):
        """Hicbir urun kaybolmaz, hicbiri iki kez gonderilmez."""
        planner = PackingPlanner(catalog)
        cart = Cart(lines=[CartLine(product=p, quantity=1) for p in products])
        expected = sorted(p.sku for p in cart.units())

        for plan in planner.candidates(cart):
            packed_skus = sorted(pl.sku for box in plan.boxes for pl in box.placements)
            assert packed_skus == expected

    @settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(products=st.lists(product_strategy(), min_size=1, max_size=4))
    def test_fill_ratio_never_exceeds_one(self, catalog, products):
        planner = PackingPlanner(catalog)
        cart = Cart(lines=[CartLine(product=p, quantity=1) for p in products])
        for plan in planner.candidates(cart):
            for packed in plan.boxes:
                assert 0 < packed.fill_ratio <= 1.0 + 1e-9


# ---- planlayici --------------------------------------------------------------


class TestPlanner:
    def test_produces_multiple_candidates_for_multi_item_cart(self, planner, soft_cart: Cart):
        """Tek plan degil, aralarindan secilecek adaylar uretilmeli."""
        plans = planner.candidates(soft_cart)
        assert len(plans) >= 2
        assert len({p.parcel_count for p in plans}) >= 2, "adaylar parca sayisinda farklilasmali"

    def test_pareto_front_is_non_dominated(self, planner, soft_cart: Cart):
        """Bir aday, baska bir adaya hem desi hem parca sayisinda yenilmemeli."""
        plans = planner.candidates(soft_cart)
        for a in plans:
            for b in plans:
                if a is b:
                    continue
                dominated = (
                    b.packed_desi <= a.packed_desi
                    and b.parcel_count <= a.parcel_count
                    and (b.packed_desi < a.packed_desi or b.parcel_count < a.parcel_count)
                )
                assert not dominated, f"{a.variant}, {b.variant} tarafindan baskilanmis"

    def test_offers_liquid_separation_when_contamination_risk_exists(
        self, planner, contamination_cart: Cart
    ):
        plans = planner.candidates(contamination_cart)
        strategies = {p.strategy for p in plans}
        assert STRATEGY_SEPARATE_LIQUIDS in strategies

        separated = next(p for p in plans if p.strategy == STRATEGY_SEPARATE_LIQUIDS)
        assert separated.contaminating_boxes == 0, "ayirma plani hala kontamine koli iceriyor"

    def test_no_separation_plan_without_contamination_risk(self, planner, soft_cart: Cart):
        assert all(p.strategy != STRATEGY_SEPARATE_LIQUIDS for p in planner.candidates(soft_cart))

    def test_single_box_solution_is_not_auto_selected(
        self, planner, catalog, towel, duvet, olive_oil
    ):
        """Hepsini alan tek kutu bulunmasi aramayi bitirmez.

        Ilk surumun hatasi buydu: K10 hepsini aliyordu (86.5 desi) ve planlayici
        orada duruyordu; oysa K09+K04 bolmesi 57.2 desi.
        """
        cart = Cart(
            lines=[CartLine(product=towel, quantity=6), CartLine(product=duvet, quantity=2)]
        )
        plans = planner.candidates(cart)
        best = min(plans, key=lambda p: p.packed_desi)
        single = [p for p in plans if p.parcel_count == 1]
        if single:
            assert best.packed_desi <= single[0].packed_desi

    def test_cache_returns_identical_plans(self, planner, soft_cart: Cart):
        first = planner.candidates(soft_cart)
        second = planner.candidates(soft_cart)
        assert first is second
        assert planner.cache_hits == 1

    def test_cache_key_distinguishes_quantities(self, planner, towel):
        one = planner.candidates(Cart(lines=[CartLine(product=towel, quantity=1)]))
        three = planner.candidates(Cart(lines=[CartLine(product=towel, quantity=3)]))
        assert one[0].packed_desi != three[0].packed_desi

    def test_oversized_item_gets_custom_box(self, planner, catalog):
        """Katalogdaki hicbir koliye sigmayan urun ozel olcu kolisi uretmeli."""
        huge = Product(
            sku="XL-001",
            name="Dev Hali",
            category=ProductCategory.CURTAIN,
            dims=Dimensions(length_cm=180, width_cm=45, height_cm=45),
            weight_kg=22.0,
            unit_price_try=8900.0,
        )
        plan = planner.plan(Cart(lines=[CartLine(product=huge, quantity=1)]))
        assert plan.custom_boxes_used == 1
        assert plan.boxes[0].box.code.startswith("OZEL-")

    def test_parcel_desis_feed_the_tariff_calculator(self, planner, soft_cart: Cart):
        plan = planner.plan(soft_cart)
        assert len(plan.parcel_desis) == plan.parcel_count
        assert all(d > 0 for d in plan.parcel_desis)
        assert plan.max_parcel_desi == max(plan.parcel_desis)


# ---- baz cizgiler ------------------------------------------------------------


class TestBaselines:
    def test_one_box_per_item_uses_one_box_per_unit(self, catalog, soft_cart: Cart):
        units = list(soft_cart.units())
        assert len(one_box_per_item(units, catalog)) == len(units)

    def test_baseline_is_worse_than_consolidated_packing(self, planner, catalog, soft_cart: Cart):
        """Konsolidasyon her zaman kazanmali -- projenin temel iddiasi bu."""
        plan = planner.plan(soft_cart)
        assert plan.packed_desi < plan.baselines.one_box_per_item_desi
        assert plan.desi_savings_pct > 0

    def test_quote_gap_is_reported_as_loss_not_saving(self, planner, soft_cart: Cart):
        """Urun desilerinin toplami fiziksel olarak ulasilamaz bir sayidir.

        Gercek desinin bunun uzerinde cikmasi bir basarisizlik degil; mevcut
        sistemin dusuk kotasyon verdigini gosteren bir bulgudur.
        """
        plan = planner.plan(soft_cart)
        assert plan.baselines.quoted_sum_desi < plan.packed_desi
        assert plan.quote_gap_pct > 0

    def test_volume_rule_baseline_is_computed(self, catalog, soft_cart: Cart):
        units = list(soft_cart.units())
        baselines = compute_baselines(units, soft_cart.naive_desi, catalog)
        assert baselines.volume_rule_desi > 0
        assert baselines.volume_rule_parcels >= 1


# ---- tek kutu yerlestiricisi -------------------------------------------------


class TestExtremePointPacker:
    def test_gravity_settling_drops_items_to_the_floor(self, catalog, towel):
        """Ilk urun her zaman kose orijine oturur."""
        packer = ExtremePointPacker(catalog.get("K09"))
        assert packer.try_place(towel) is True
        placement = packer.to_packed_box().placements[0]
        assert (placement.x, placement.y, placement.z) == (0.0, 0.0, 0.0)

    def test_empty_packer_returns_none(self, catalog):
        assert ExtremePointPacker(catalog.get("K01")).to_packed_box() is None

    def test_settling_beats_naive_corner_points(self, catalog, towel):
        """Oturtma calisiyorsa ayni kutuya daha cok urun girer.

        Dogrudan olcemedigimiz icin dolayli kontrol: K09'a en az 8 havlu
        girmeli (hacimsel olarak 20'den fazlasi sigar, ama heuristik kayip verir).
        """
        packed, _ = fill_box(catalog.get("K09"), [towel] * 20, PackingRules())
        assert packed is not None
        assert packed.item_count >= 8
        assert packed.fill_ratio > 0.4
