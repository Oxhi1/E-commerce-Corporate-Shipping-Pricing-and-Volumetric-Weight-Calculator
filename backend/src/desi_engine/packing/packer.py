"""Sanal kutulama planlayicisi -- sepetten koli planina.

Bu modul kullanicinin 1. maddesini uygular: "3 desi havlu + 4 desi deterjan
7 desi yapmaz". Urun desileri toplanmaz; urunler gercek olculeriyle standart
kolilere yerlestirilir ve fatura kolinin **dis** desisi uzerinden hesaplanir.

Uc tasarim karari one cikiyor:

1. **"Hepsi tek koliye sigiyor" en ucuz demek degildir.**
   Ilk surumde planlayici, hepsini alan ilk kutuyu bulunca duruyordu. Ornek bir
   sepette bu K10'u seciyordu (86.5 desi); oysa K09 + K04 bolmesi 57.2 desi.
   Artik tek koli yalnizca *bir aday*, otomatik kazanan degil.

2. **En az desi de tek basina dogru amac degil.**
   Asgari ucret **parca basina** uygulanir. 5 koliye bolerek 56 desiye inmek,
   2 koliyle 57 desiden pahaliya gelebilir. Parca sayisi ile desi arasindaki
   takasi tarifeyi bilmeden cozemeyiz -- planlayici tarifeyi bilmez.

3. **Sivi ayrimi bir paketleme kurali degil, bir maliyet karari.**
   Zeytinyagini nevresimden ayirmak bir koli daha demek. Buna paketleyici karar
   veremez; hasar maliyetini bilmiyor.

(2) ve (3) ayni sonuca cikiyor: planlayici **tek bir plan degil, birkac iyi aday
plan** uretir; hangisinin ucuz oldugunu tarifeyi ve hasar modelini bilen karar
motoru soyler.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from ..domain.models import Cart, Dimensions, Product
from .baselines import BaselineDesis, compute_baselines
from .boxes import Box, BoxCatalog, PackedBox
from .extreme_point import fill_box
from .rules import PackingRules

#: Katalog disi urun icin uretilen ozel olcu kolisinin kenar payi (cm, tek kenar).
CUSTOM_BOX_CLEARANCE_CM: Final[float] = 2.0

STRATEGY_TOGETHER: Final[str] = "birlikte"
STRATEGY_SEPARATE_LIQUIDS: Final[str] = "sivilar_ayri"

#: Bir sepet icin uretilecek azami aday plan sayisi. Karar motoru her adayi her
#: firmaya karsi fiyatlayacagi icin bu sayi dogrudan hesap maliyetini belirler.
MAX_PLANS_PER_CART: Final[int] = 4

#: Pareto spektrumu taranirken denenecek azami kutu boyutu tavani sayisi.
#: Katalogun tamamini taramak kaliteyi kayda deger olcude artirmiyor ama
#: paketleme suresini yaklasik iki katina cikariyor.
MAX_SIZE_CAPS: Final[int] = 5


class PackingError(RuntimeError):
    """Sepet hicbir sekilde paketlenemedi."""


@dataclass(frozen=True, slots=True)
class GroupPacking:
    """Bir urun grubunun tek bir paketleme varyanti."""

    boxes: tuple[PackedBox, ...]
    custom_used: int

    @property
    def total_desi(self) -> float:
        return sum(b.billable_proxy_desi for b in self.boxes)

    @property
    def parcel_count(self) -> int:
        return len(self.boxes)

    @property
    def fingerprint(self) -> tuple[str, ...]:
        """Ayni kutu bilesimini uretmis varyantlari elemek icin."""
        return tuple(sorted(b.box.code for b in self.boxes))


class PackingPlan(BaseModel):
    """Bir sepet icin tam koli plani."""

    model_config = ConfigDict(frozen=True)

    strategy: str
    variant: str = Field(description="Ayni strateji icindeki varyantin adi")
    boxes: list[PackedBox] = Field(min_length=1)
    baselines: BaselineDesis
    custom_boxes_used: int = 0

    # ---- temel olculer ------------------------------------------------------

    @property
    def parcel_count(self) -> int:
        return len(self.boxes)

    @property
    def parcel_desis(self) -> list[float]:
        """Her kolinin dis desisi -- tarife hesaplayicisinin girdisi."""
        return [b.outer_desi for b in self.boxes]

    @property
    def parcel_gross_weights(self) -> list[float]:
        return [b.gross_weight_kg for b in self.boxes]

    @property
    def packed_desi(self) -> float:
        """Toplam ucretli desi vekili (firma yuvarlama kurali uygulanmadan)."""
        return sum(b.billable_proxy_desi for b in self.boxes)

    @property
    def max_parcel_desi(self) -> float:
        """En buyuk kolinin dis desisi -- firmalarin parca basi siniriyla kiyaslanir."""
        return max(b.outer_desi for b in self.boxes)

    @property
    def packaging_cost_try(self) -> float:
        return sum(b.box.unit_cost_try for b in self.boxes)

    @property
    def mean_fill_ratio(self) -> float:
        return sum(b.fill_ratio for b in self.boxes) / len(self.boxes)

    @property
    def contaminating_boxes(self) -> int:
        """Ayni kolide hem sivi hem emici urun bulunan koli sayisi.

        Hasar modelinin yan hasar carpanini tetikleyen sayi budur.
        """
        return sum(
            1
            for b in self.boxes
            if any(p.is_liquid for p in b.placements) and any(p.is_absorbent for p in b.placements)
        )

    # ---- baz cizgiye gore olculer -------------------------------------------

    @property
    def desi_savings_pct(self) -> float:
        """Gercek operasyonel baz cizgiye (her urun ayri koli) kiyasla tasarruf.

        Raporda one cikan sayi budur, cunku karsilastirilan iki durum da fiziksel
        olarak gerceklestirilebilir.
        """
        baseline = self.baselines.one_box_per_item_desi
        if baseline <= 0:
            return 0.0
        return (baseline - self.packed_desi) / baseline

    @property
    def savings_vs_volume_rule_pct(self) -> float:
        """Hacim toplami kuralina (Excel mantigi) kiyasla tasarruf."""
        baseline = self.baselines.volume_rule_desi
        if baseline <= 0:
            return 0.0
        return (baseline - self.packed_desi) / baseline

    @property
    def quote_gap_pct(self) -> float:
        """Kotasyon acigi: gercek desi, mevcut sistemin tahmininden ne kadar fazla.

        **Pozitif deger bir tasarruf degil, gizli bir zarardir**: sirket urun
        desilerini toplayarak fiyat veriyor ama kargo firmasi kolinin desisinden
        kesiyor. Aradaki fark her siparişte sessizce kaybediliyor.
        """
        quoted = self.baselines.quoted_sum_desi
        if quoted <= 0:
            return 0.0
        return (self.packed_desi - quoted) / quoted


class PackingPlanner:
    """Sepetleri aday koli planlarina cevirir ve sonuclari onbellekler."""

    def __init__(
        self,
        catalog: BoxCatalog,
        rules: PackingRules | None = None,
        *,
        cache_size: int = 8192,
    ) -> None:
        self.catalog = catalog
        self.rules = rules or PackingRules()
        self._cache: dict[tuple, list[PackingPlan]] = {}
        self._cache_size = cache_size
        self.cache_hits = 0
        self.cache_misses = 0

        # Koli-doldurma onbellegi, **siparisler arasinda** paylasilir.
        #
        # Sepet duzeyindeki onbellek Monte Carlo'da yalnizca ~%32 isabet veriyor:
        # 48 urunluk katalogdan uretilen sepet bilesimi cok fazla. Ama ayni urun
        # *alt kumeleri* surekli tekrar ediyor -- "2 havlu K04'e nasil yerlesir"
        # sorusunun cevabi sepetten bagimsiz ve degismez. Bu seviyede onbellek
        # tutmak isabet oranini cok yukari cikariyor.
        self._fill_cache: dict[tuple, tuple[PackedBox | None, tuple[Product, ...]]] = {}
        self._fill_cache_size = cache_size * 16

    # ---- genel arayuz -------------------------------------------------------

    def candidates(self, cart: Cart) -> list[PackingPlan]:
        """Degerlendirmeye deger tum aday planlari uretir (en fazla `MAX_PLANS_PER_CART`)."""
        key = self._signature(cart)
        cached = self._cache.get(key)
        if cached is not None:
            self.cache_hits += 1
            return cached

        self.cache_misses += 1
        units = list(cart.units())
        baselines = compute_baselines(units, cart.naive_desi, self.catalog, self.rules)

        plans = self._plans_for_strategy(STRATEGY_TOGETHER, [units], baselines)

        if cart.has_contamination_risk:
            liquids = [u for u in units if u.is_liquid]
            others = [u for u in units if not u.is_liquid]
            plans += self._plans_for_strategy(
                STRATEGY_SEPARATE_LIQUIDS, [liquids, others], baselines
            )

        if not plans:
            raise PackingError("Sepet icin hicbir gecerli koli plani uretilemedi")

        plans = self._dedupe(plans)[:MAX_PLANS_PER_CART]

        if len(self._cache) >= self._cache_size:
            self._cache.clear()
        self._cache[key] = plans
        return plans

    def plan(self, cart: Cart) -> PackingPlan:
        """En az desi ureten tek plani doner.

        Yalnizca desi olcutune bakar; gercek secim karar motorunundur.
        """
        return min(self.candidates(cart), key=lambda p: p.packed_desi)

    @property
    def cache_hit_rate(self) -> float:
        total = self.cache_hits + self.cache_misses
        return self.cache_hits / total if total else 0.0

    # ---- plan uretimi -------------------------------------------------------

    def _plans_for_strategy(
        self, strategy: str, groups: list[list[Product]], baselines: BaselineDesis
    ) -> list[PackingPlan]:
        """Bir strateji icin varyant basina bir plan uretir.

        Her grup icin ayni olcute gore en iyi varyant secilir; boylece
        "her grupta en az desi" ve "her grupta en az parca" planlari olusur.
        Varyantlarin tum kombinasyonlarini denemek kombinatorik olarak patlar ve
        pratikte kayda deger bir kazanc getirmez.
        """
        variants_per_group = [self._pack_variants(group) for group in groups if group]
        if not variants_per_group or any(not v for v in variants_per_group):
            return []

        def build(variant_name: str, chosen: list[GroupPacking]) -> PackingPlan:
            return PackingPlan(
                strategy=strategy,
                variant=variant_name,
                boxes=[box for gp in chosen for box in gp.boxes],
                baselines=baselines,
                custom_boxes_used=sum(gp.custom_used for gp in chosen),
            )

        # Tek grup: Pareto cephesinin her noktasi ayri bir aday plandir.
        if len(variants_per_group) == 1:
            return [
                build(f"{gp.parcel_count}_koli", [gp])
                for gp in variants_per_group[0][:MAX_PLANS_PER_CART]
            ]

        # Cok grup (sivilar ayri): tum kombinasyonlar kombinatorik olarak patlar.
        # Her grupta ayni olcute gore en iyiyi secip iki uc plani uretiyoruz.
        criteria = {
            "en_az_desi": lambda gp: (gp.total_desi, gp.parcel_count),
            "en_az_parca": lambda gp: (gp.parcel_count, gp.total_desi),
        }
        return [
            build(name, [min(variants, key=key) for variants in variants_per_group])
            for name, key in criteria.items()
        ]

    @staticmethod
    def _dedupe(plans: list[PackingPlan]) -> list[PackingPlan]:
        """Ayni kutu bilesimini ureten planlari eler, desiye gore siralar."""
        seen: set[tuple] = set()
        unique: list[PackingPlan] = []
        for plan in sorted(plans, key=lambda p: (p.packed_desi, p.parcel_count)):
            key = (plan.strategy, tuple(sorted(b.box.code for b in plan.boxes)))
            if key in seen:
                continue
            seen.add(key)
            unique.append(plan)
        return unique

    # ---- varyant uretimi ----------------------------------------------------

    def _pack_variants(self, units: list[Product]) -> list[GroupPacking]:
        """Bir urun grubu icin Pareto-optimal paketleme varyantlari uretir.

        Iki acgozlu olcut ("en az desi", "en cok urun") tek baslarina spektrumun
        yalnizca iki ucunu buluyordu: cok sayida kucuk koli (dusuk desi, yuksek
        parca) veya tek dev koli (tek parca, yuksek desi). Ornek bir sepette
        gercekten iyi olan orta cozum -- K09 + K04 -- ikisinde de cikmiyordu.

        Cozum: acgozlu algoritmayi **kutu boyutu tavani** degistirerek defalarca
        kosturmak. Tavan kucukse cok parcali/az desili, buyukse az parcali/cok
        desili planlar cikar; arada tum ara cozumler uretilir. Sonra (desi, parca)
        duzleminde baskin olmayanlar -- Pareto cephesi -- secilir.

        Maliyet, `fill_box` sonuclarinin `_fill_cache` ile onbelleklenmesiyle
        karsilaniyor; hem tavanlarin cogu hem de farkli sepetler ayni ara
        sonuclari yeniden kullaniyor.
        """
        if not units:
            return []

        # Buyukten kucuge: FFD'nin klasik on kosulu. Buyuk urun once yerlesirse
        # kucukler kalan bosluklara sizabilir; tersi mumkun degil.
        ordered = sorted(units, key=lambda p: p.effective_dims.volume_cm3, reverse=True)
        allow_bags = not any(p.is_liquid or p.fragility.value != "yok" for p in ordered)
        usable = self.catalog.usable(allow_soft_only=allow_bags)

        variants: list[GroupPacking] = []
        for cap in self._size_caps(ordered, usable):
            for prefer_fewer in (False, True):
                variants.append(self._greedy(ordered, cap, prefer_fewer_parcels=prefer_fewer))

        return self._pareto_front(variants)

    def _size_caps(self, units: list[Product], usable: tuple[Box, ...]) -> list[tuple[Box, ...]]:
        """Denenecek kutu boyutu tavanlari.

        Bir tavan ancak gruptaki **her** urunu tek basina alabiliyorsa gecerlidir;
        aksi halde acgozlu algoritma gereksiz yere ozel olcu kolisi uretirdi.

        Gecerli tavanlarin tamami denenmez. 13 kutuluk katalogda bu, grup basina
        26 acgozlu kosu demek olurdu ve profil, kosu suresinin %89'unun burada
        gectigini gosterdi. Bunun yerine spektrumdan `MAX_SIZE_CAPS` nokta esit
        araliklarla orneklenir; en kucuk ve en buyuk tavan her zaman dahildir --
        Pareto cephesinin iki ucunu onlar belirliyor.
        """
        feasible = [
            usable[: index + 1]
            for index, box in enumerate(usable)
            if all(u.effective_dims.fits_within(box.inner) for u in units)
        ]
        if not feasible:
            # Hicbir katalog kutusu en buyuk urunu alamiyor: tum katalogla dene,
            # ozel olcu kolisi uretimi `_greedy` icinde devreye girer.
            return [usable]
        if len(feasible) <= MAX_SIZE_CAPS:
            return feasible

        step = (len(feasible) - 1) / (MAX_SIZE_CAPS - 1)
        picked = {round(index * step) for index in range(MAX_SIZE_CAPS)}
        return [feasible[index] for index in sorted(picked)]

    @staticmethod
    def _pareto_front(variants: list[GroupPacking]) -> list[GroupPacking]:
        """(toplam desi, parca sayisi) duzleminde baskin olmayan varyantlar.

        Bir varyant, baska bir varyant her iki olcutte de ondan iyi (veya birinde
        esit digerinde iyi) ise elenir. Kalanlar arasindaki secim tarifeye bagli
        oldugu icin karar motoruna birakilir.
        """
        unique: dict[tuple[str, ...], GroupPacking] = {}
        for variant in variants:
            unique.setdefault(variant.fingerprint, variant)

        candidates = sorted(unique.values(), key=lambda v: (v.total_desi, v.parcel_count))
        front: list[GroupPacking] = []
        best_parcels = float("inf")
        for variant in candidates:
            # Desiye gore sirali ilerliyoruz; bir varyant ancak parca sayisini da
            # dusuruyorsa cepheye girer.
            if variant.parcel_count < best_parcels:
                front.append(variant)
                best_parcels = variant.parcel_count
        return front

    def _fill_cached(
        self, box: Box, items: tuple[Product, ...]
    ) -> tuple[PackedBox | None, tuple[Product, ...]]:
        """`fill_box` sonucunu (kutu, urun dizisi) anahtariyla onbellekler.

        Yerlestirme deterministik oldugu icin ayni girdi her zaman ayni sonucu
        verir; onbellek siparisler arasinda guvenle paylasilabilir. Ayni urun
        dizisi hem farkli boyut tavanlarinda hem farkli sepetlerde tekrar tekrar
        geliyor -- spektrum taramasinin maliyetini bu tasiyor.
        """
        key = (box.code, tuple(p.sku for p in items))
        cached = self._fill_cache.get(key)
        if cached is None:
            packed, leftover = fill_box(box, list(items), self.rules)
            cached = (packed, tuple(leftover))
            if len(self._fill_cache) >= self._fill_cache_size:
                self._fill_cache.clear()
            self._fill_cache[key] = cached
        return cached

    def _greedy(
        self, units: list[Product], usable: tuple[Box, ...], *, prefer_fewer_parcels: bool
    ) -> GroupPacking:
        """Acgozlu bolme, verilen kutu kumesiyle.

        `prefer_fewer_parcels=False`: sevk edilen hacim basina en az desi.
        `prefer_fewer_parcels=True`: her turda en cok urunu alan kutu.
        """
        remaining: tuple[Product, ...] = tuple(units)
        boxes: list[PackedBox] = []
        custom_used = 0

        while remaining:
            best = self._best_box_for(remaining, usable, prefer_fewer_parcels)
            if best is None:
                oversized = remaining[0]
                packed, leftover = fill_box(
                    self._custom_box_for(oversized), list(remaining), self.rules
                )
                if packed is None:
                    raise PackingError(f"{oversized.sku} ozel koliye de yerlestirilemedi")
                custom_used += 1
                boxes.append(packed)
                remaining = tuple(leftover)
                continue

            packed, remaining = best
            boxes.append(packed)

        return GroupPacking(boxes=tuple(boxes), custom_used=custom_used)

    def _best_box_for(
        self,
        remaining: tuple[Product, ...],
        usable: tuple[Box, ...],
        prefer_fewer_parcels: bool,
    ) -> tuple[PackedBox, tuple[Product, ...]] | None:
        best: tuple[tuple[float, float], PackedBox, tuple[Product, ...]] | None = None

        for box in usable:
            packed, leftover = self._fill_cached(box, remaining)
            if packed is None:
                continue
            shipped_volume = sum(p.volume_cm3 for p in packed.placements)
            if shipped_volume <= 0:
                continue

            desi_per_volume = packed.billable_proxy_desi / shipped_volume
            score = (
                (-packed.item_count, desi_per_volume)
                if prefer_fewer_parcels
                else (desi_per_volume, -packed.item_count)
            )
            if best is None or score < best[0]:
                best = (score, packed, leftover)

        if best is None:
            return None
        return best[1], best[2]

    def _custom_box_for(self, product: Product) -> Box:
        """Katalog disi bir urun icin olcusune gore ozel koli uretir."""
        dims = product.effective_dims
        clearance = 2 * CUSTOM_BOX_CLEARANCE_CM
        return Box(
            code=f"OZEL-{product.sku}",
            name=f"Ozel olcu koli ({product.name})",
            inner=Dimensions(
                length_cm=dims.length_cm + clearance,
                width_cm=dims.width_cm + clearance,
                height_cm=dims.height_cm + clearance,
            ),
            wall_cm=0.7,
            tare_kg=0.9,
            max_payload_kg=max(product.weight_kg * 1.5, 5.0),
            unit_cost_try=45.0,  # ozel ambalaj pahali ve is emri gerektirir
        )

    # ---- onbellek anahtari --------------------------------------------------

    @staticmethod
    def _signature(cart: Cart) -> tuple:
        """Sepetin paketleme acisindan kimligi: (sku, adet) coklu kumesi.

        Monte Carlo'da 50 bin siparis ayni katalogdan uretildigi icin bu anahtar
        cok yuksek isabet orani veriyor; paketleme motorun en pahali parcasi
        oldugundan onbellek simulasyon suresini bir buyukluk mertebesi dusuruyor.
        """
        return tuple(sorted((line.product.sku, line.quantity) for line in cart.lines))
