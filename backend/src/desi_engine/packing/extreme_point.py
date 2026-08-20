"""Tek kutuya 3B yerlestirme: kose noktalari + yercekimi oturtmasi.

Yontem, Crainic ve ark. (2008) "Extreme Point" ailesinin pratik bir varyantidir:

  * Her yerlestirilen urun, uzak koselerinde uc yeni **aday nokta** uretir:
    (x+dx, y, z), (x, y+dy, z), (x, y, z+dz).
  * Ham kose noktalari tek baslarina bosluk birakir. Bu yuzden her aday, secilmeden
    once **oturtulur**: once z ekseninde asagi (yercekimi), sonra y ve x ekseninde
    geriye/sola kaydirilir; carpana kadar. Iki tur yapilir cunku y/x kaymasi
    urunu yeni bir yuzeyin ustune getirebilir ve z yeniden dusebilir.
  * Uygun yerlesimler arasindan "en alt, en arka, en sol" olan secilir (BLB).

Oturtma adimi olmadan tipik dolgu orani ~%45'te kaliyor; oturtma ile ~%65-75'e
cikiyor. Fatura desi uzerinden kesildigi icin bu fark dogrudan paraya donusuyor.

Sinirlar (bilincli): tam projeksiyon tabanli EP degil, urunler eksen hizali ve
yalnizca 90 derecelik dondurmelere izin veriliyor, urunler dikdortgen prizma
olarak modelleniyor. Yumusak tekstil icin bu son varsayim iyimserdir; `Product.
compressibility` bunu kismen telafi eder.
"""

from __future__ import annotations

from functools import lru_cache

from ..domain.models import Product
from .boxes import Box, PackedBox, Placement
from .geometry import EPS, Cuboid
from .rules import PackingRules, box_accepts, check_placement


@lru_cache(maxsize=8192)
def rotation_triples(dims: tuple[float, float, float]) -> tuple[tuple[float, float, float], ...]:
    """Bir olcunun eksen hizali benzersiz dondurmeleri, duz demet olarak.

    `Dimensions.rotations()` her cagrida alti Pydantic nesnesi uretiyor. Profil,
    150 siparislik bir kosuda 247 bin cagri gosterdi -- yerlestirme dongusunun en
    sicak noktalarindan biri. Burada sonuc olcuye gore onbellekleniyor ve duz
    demet olarak donuyor; katalogdaki urun sayisi sinirli oldugu icin isabet
    orani neredeyse tam.
    """
    length, width, height = dims
    seen: dict[tuple[float, float, float], None] = {}
    for candidate in (
        (length, width, height),
        (length, height, width),
        (width, length, height),
        (width, height, length),
        (height, length, width),
        (height, width, length),
    ):
        seen.setdefault(candidate, None)
    return tuple(seen)


#: Aday nokta listesinin ust siniri. Cok sayida kucuk urunde liste kombinatorik
#: olarak buyuyor; en dusuk (z, y, x) noktalari zaten en iyi adaylar oldugu icin
#: budama pratikte kaliteyi dusurmuyor ama arama suresini sabit tutuyor.
MAX_CANDIDATE_POINTS: int = 96


class ExtremePointPacker:
    """Tek bir koliyi doldurur. Urunler cagrildiklari sirada yerlestirilir."""

    def __init__(self, box: Box, rules: PackingRules | None = None) -> None:
        self.box = box
        self.rules = rules or PackingRules()
        self._inner = box.inner.as_tuple()

        self._placed: list[Cuboid] = []
        # Sicak dongu icin duz sinir demetleri: (x, y, z, x2, y2, z2).
        # `Cuboid.x2` bir property; oturtma dongusunde milyonlarca kez cagrilinca
        # tek basina olculebilir bir maliyet oluyor. Bu liste `_placed` ile
        # senkron tutulur ve yalnizca geometri taramalarinda kullanilir.
        self._bounds: list[tuple[float, float, float, float, float, float]] = []
        self._products: list[Product] = []
        self._carried_kg: list[float] = []
        self._points: list[tuple[float, float, float]] = [(0.0, 0.0, 0.0)]
        self._content_weight = 0.0

    # ---- durum --------------------------------------------------------------

    @property
    def item_count(self) -> int:
        return len(self._placed)

    @property
    def content_weight_kg(self) -> float:
        return self._content_weight

    @property
    def is_empty(self) -> bool:
        return not self._placed

    # ---- yerlestirme --------------------------------------------------------

    def try_place(self, product: Product) -> bool:
        """Urunu koliye yerlestirmeyi dener. Basarili olursa `True`."""
        if not box_accepts(self.box, product):
            return False
        if self.item_count >= self.rules.max_items_per_box:
            return False
        if self._content_weight + product.weight_kg > self.box.max_payload_kg + 1e-9:
            return False

        best: tuple[tuple[float, float, float], Cuboid, list[float]] | None = None
        dims = product.effective_dims

        for point in self._points:
            px, py, pz = point
            for dx, dy, dz in rotation_triples(dims.as_tuple()):
                x, y, z = self._settle(px, py, pz, dx, dy, dz)
                if not self._is_free(x, y, z, dx, dy, dz):
                    continue

                candidate = Cuboid(x, y, z, dx, dy, dz)
                violation, carried = check_placement(
                    candidate,
                    product,
                    self._placed,
                    self._products,
                    self._carried_kg,
                    self.rules,
                )
                if violation is not None:
                    continue

                score = (z + dz, y + dy, x + dx)
                if best is None or score < best[0]:
                    best = (score, candidate, carried)

        if best is None:
            return False

        _, placement, carried = best
        self._commit(placement, product, carried)
        return True

    def _commit(self, cuboid: Cuboid, product: Product, carried: list[float]) -> None:
        self._placed.append(cuboid)
        self._bounds.append(
            (
                cuboid.x,
                cuboid.y,
                cuboid.z,
                cuboid.x + cuboid.dx,
                cuboid.y + cuboid.dy,
                cuboid.z + cuboid.dz,
            )
        )
        self._products.append(product)
        self._carried_kg = [*carried, 0.0]
        self._content_weight += product.weight_kg
        self._refresh_points(cuboid)

    # ---- geometri sicak yolu ------------------------------------------------
    #
    # Asagidaki dort metot, kosu suresinin buyuk kismini tuketiyor (150 siparislik
    # bir profilde 1.7 milyon cagri). Bu yuzden `Cuboid` property'leri yerine duz
    # float aritmetigi kullaniyorlar ve eksen basina ayri yazilmislar -- indeksleme
    # ve demet olusturma maliyetini kaldirmak icin. Okunabilirlikten bilincli bir
    # odun; davranis `tests/test_packing.py` degismezleriyle korunuyor.

    def _is_free(self, x: float, y: float, z: float, dx: float, dy: float, dz: float) -> bool:
        """Aday kutu icinde mi ve hicbir urunle cakismiyor mu."""
        inner_x, inner_y, inner_z = self._inner
        x2, y2, z2 = x + dx, y + dy, z + dz
        if x < -EPS or y < -EPS or z < -EPS:
            return False
        if x2 > inner_x + EPS or y2 > inner_y + EPS or z2 > inner_z + EPS:
            return False

        for bx, by, bz, bx2, by2, bz2 in self._bounds:
            if (
                bx2 > x + EPS
                and x2 > bx + EPS
                and by2 > y + EPS
                and y2 > by + EPS
                and bz2 > z + EPS
                and z2 > bz + EPS
            ):
                return False
        return True

    def _settle(
        self, x: float, y: float, z: float, dx: float, dy: float, dz: float
    ) -> tuple[float, float, float]:
        """Adayi once asagi, sonra geriye, sonra sola kaydirir. Iki tur.

        Iki tur gerekli: y veya x kaymasi urunu yeni bir yuzeyin ustune getirebilir
        ve z yeniden dusebilir.
        """
        for _ in range(2):
            z = self._rest_z(x, y, z, dx, dy)
            y = self._rest_y(x, y, z, dx, dy, dz)
            x = self._rest_x(x, y, z, dx, dy, dz)
        return x, y, z

    def _rest_z(self, x: float, y: float, z: float, dx: float, dy: float) -> float:
        """Yercekimi: x-y duzleminde ortusen en yuksek yuzeye kadar dus."""
        x2, y2 = x + dx, y + dy
        resting = 0.0
        for bx, by, _bz, bx2, by2, bz2 in self._bounds:
            if bx2 <= x + EPS or x2 <= bx + EPS:
                continue
            if by2 <= y + EPS or y2 <= by + EPS:
                continue
            if bz2 <= z + EPS and bz2 > resting:
                resting = bz2
        return resting

    def _rest_y(self, x: float, y: float, z: float, dx: float, dy: float, dz: float) -> float:
        x2, z2 = x + dx, z + dz
        resting = 0.0
        for bx, _by, bz, bx2, by2, bz2 in self._bounds:
            if bx2 <= x + EPS or x2 <= bx + EPS:
                continue
            if bz2 <= z + EPS or z2 <= bz + EPS:
                continue
            if by2 <= y + EPS and by2 > resting:
                resting = by2
        return resting

    def _rest_x(self, x: float, y: float, z: float, dx: float, dy: float, dz: float) -> float:
        y2, z2 = y + dy, z + dz
        resting = 0.0
        for _bx, by, bz, bx2, by2, bz2 in self._bounds:
            if by2 <= y + EPS or y2 <= by + EPS:
                continue
            if bz2 <= z + EPS or z2 <= bz + EPS:
                continue
            if bx2 <= x + EPS and bx2 > resting:
                resting = bx2
        return resting

    def _refresh_points(self, placed: Cuboid) -> None:
        """Yeni urunun urettigi aday noktalari ekler, kullanilamazlari eler."""
        new_points = [
            (placed.x2, placed.y, placed.z),
            (placed.x, placed.y2, placed.z),
            (placed.x, placed.y, placed.z2),
        ]
        candidates = set(self._points) | set(new_points)

        # Bir urunun ici kalan noktalar kullanilamaz.
        alive = [
            point
            for point in candidates
            if not any(self._point_inside(point, other) for other in self._placed)
        ]
        alive.sort(key=lambda p: (p[2], p[1], p[0]))
        self._points = alive[:MAX_CANDIDATE_POINTS]

    @staticmethod
    def _point_inside(point: tuple[float, float, float], cuboid: Cuboid) -> bool:
        x, y, z = point
        return (
            cuboid.x - EPS < x < cuboid.x2 - EPS
            and cuboid.y - EPS < y < cuboid.y2 - EPS
            and cuboid.z - EPS < z < cuboid.z2 - EPS
        )

    # ---- sonuc --------------------------------------------------------------

    def to_packed_box(self) -> PackedBox | None:
        """Doldurulmus koliyi doner; hicbir urun yerlesmediyse `None`."""
        if self.is_empty:
            return None
        placements = [
            Placement(
                sku=product.sku,
                name=product.name,
                x=cuboid.x,
                y=cuboid.y,
                z=cuboid.z,
                dx=cuboid.dx,
                dy=cuboid.dy,
                dz=cuboid.dz,
                weight_kg=product.weight_kg,
                value_try=product.unit_price_try,
                risk_category=product.risk_category,
                is_liquid=product.is_liquid,
                is_absorbent=product.is_absorbent,
                max_stack_load_kg=product.max_stack_load_kg,
            )
            for cuboid, product in zip(self._placed, self._products, strict=True)
        ]
        return PackedBox(box=self.box, placements=placements)


def fill_box(
    box: Box, products: list[Product], rules: PackingRules | None = None
) -> tuple[PackedBox | None, list[Product]]:
    """Verilen urunleri siraya gore koliye doldurur.

    `(dolu_koli_veya_None, sigmayan_urunler)` doner. Sigmayan bir urun sonraki
    urunlerin denenmesini engellemez -- kucuk bir urun buyugun sigmadigi bosluga
    girebilir.
    """
    packer = ExtremePointPacker(box, rules)
    leftover: list[Product] = []
    for product in products:
        if not packer.try_place(product):
            leftover.append(product)
    return packer.to_packed_box(), leftover
