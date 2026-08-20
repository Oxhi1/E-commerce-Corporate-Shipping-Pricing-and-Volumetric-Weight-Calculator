"""Koli yerlesiminin bagimsiz SVG cizimi (izometrik).

Arayuzdeki 3B gorunumun Python karsiligi. Neden ikisi de var:

* Arayuz sürümü (`frontend/src/components/BoxViewer.tsx`) etkilesimli -- urunun
  uzerine gelince adi cikiyor, plan degistirilince yeniden ciziliyor.
* Bu surum, arayuzu calistirmadan **dosyaya** cikti uretmek icin. Staj raporuna
  veya sunuma gorsel koymanin en kisa yolu; `desi pack --render` bunu kullanir.

Neden Three.js/matplotlib degil: gorsellestirilen sey eksen hizali dikdortgenler
prizmasindan ibaret. Izometrik izdusum + ressam algoritmasi (arkadan one cizim)
bu is icin yeterli ve hicbir bagimlilik gerektirmiyor. SVG oldugu icin her
olcekte keskin ve rapora dogrudan gomulebiliyor.

PNG uretilmiyor -- raster cikti Pillow veya matplotlib gerektirirdi. SVG'yi PNG'ye
cevirmek isteyen bir tarayicidan veya `rsvg-convert`'ten gecirebilir.
"""

from __future__ import annotations

from typing import Final

from .boxes import PackedBox, Placement

#: Izometrik izdusum vektorleri: x saga-asagi, y sola-asagi, z yukari.
_ISO_X: Final[tuple[float, float]] = (0.866, 0.5)
_ISO_Y: Final[tuple[float, float]] = (-0.866, 0.5)

#: Risk sinifina gore renk. Kimlik degil **risk** tasiyor: sivi bir urunun emici
#: urunlerin yaninda durdugu bakista gorunsun diye.
RISK_COLORS: Final[dict[str, str]] = {
    "yumusak": "#2a78d6",
    "kirilabilir": "#eb6834",
    "sivi": "#1baf7a",
    "cihaz": "#eda100",
}
RISK_LABELS: Final[dict[str, str]] = {
    "yumusak": "Tekstil",
    "kirilabilir": "Kirilabilir",
    "sivi": "Sivi",
    "cihaz": "Cihaz",
}

_PADDING: Final[float] = 16.0
_LEGEND_HEIGHT: Final[float] = 26.0


def _project(x: float, y: float, z: float, scale: float) -> tuple[float, float]:
    return (
        (x * _ISO_X[0] + y * _ISO_Y[0]) * scale,
        (x * _ISO_X[1] + y * _ISO_Y[1] - z) * scale,
    )


def _path(points: list[tuple[float, float]]) -> str:
    return (
        " ".join(
            f"{'M' if index == 0 else 'L'}{px:.2f},{py:.2f}"
            for index, (px, py) in enumerate(points)
        )
        + " Z"
    )


def _faces(placement: Placement, scale: float) -> tuple[str, str, str]:
    """Prizmanin gorunen uc yuzunu (yan, on, ust) cizer.

    Yuzler farkli opaklikta: ust acik, on orta, yan koyu. Bu, hacmi tek renkli bir
    silüete indirgemeden derinlik hissi veriyor.
    """
    x, y, z = placement.x, placement.y, placement.z
    dx, dy, dz = placement.dx, placement.dy, placement.dz
    point = lambda px, py, pz: _project(px, py, pz, scale)  # noqa: E731

    top = [
        point(x, y, z + dz),
        point(x + dx, y, z + dz),
        point(x + dx, y + dy, z + dz),
        point(x, y + dy, z + dz),
    ]
    front = [
        point(x, y + dy, z),
        point(x + dx, y + dy, z),
        point(x + dx, y + dy, z + dz),
        point(x, y + dy, z + dz),
    ]
    side = [
        point(x + dx, y, z),
        point(x + dx, y + dy, z),
        point(x + dx, y + dy, z + dz),
        point(x + dx, y, z + dz),
    ]
    return _path(side), _path(front), _path(top)


def render_box_svg(packed: PackedBox, height: float = 320.0) -> str:
    """Tek bir kolinin izometrik gorunumunu bagimsiz SVG olarak dondurur."""
    inner = packed.box.inner
    length, width, box_height = inner.length_cm, inner.width_cm, inner.height_cm

    corners = [
        _project(px, py, pz, 1.0)
        for px in (0.0, length)
        for py in (0.0, width)
        for pz in (0.0, box_height)
    ]
    min_x = min(c[0] for c in corners)
    max_x = max(c[0] for c in corners)
    min_y = min(c[1] for c in corners)
    max_y = max(c[1] for c in corners)

    plot_height = height - _LEGEND_HEIGHT - 2 * _PADDING
    scale = plot_height / (max_y - min_y)
    svg_width = (max_x - min_x) * scale + 2 * _PADDING

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{min_x * scale - _PADDING:.2f} {min_y * scale - _PADDING:.2f} '
        f'{svg_width:.2f} {height:.2f}" width="{svg_width:.0f}" height="{height:.0f}" '
        f'role="img" aria-label="{packed.box.code} kolisi, {packed.item_count} urun">',
        f'<rect x="{min_x * scale - _PADDING:.2f}" y="{min_y * scale - _PADDING:.2f}" '
        f'width="{svg_width:.2f}" height="{height:.2f}" fill="#fcfcfb"/>',
    ]

    # Kolinin tel kafesi -- urunlerin kutunun neresinde durdugunu gosterir.
    corner = lambda px, py, pz: _project(px, py, pz, scale)  # noqa: E731
    edges = [
        ((0, 0, 0), (length, 0, 0)),
        ((length, 0, 0), (length, width, 0)),
        ((length, width, 0), (0, width, 0)),
        ((0, width, 0), (0, 0, 0)),
        ((0, 0, 0), (0, 0, box_height)),
        ((length, 0, 0), (length, 0, box_height)),
        ((length, width, 0), (length, width, box_height)),
        ((0, width, 0), (0, width, box_height)),
        ((0, 0, box_height), (length, 0, box_height)),
        ((length, 0, box_height), (length, width, box_height)),
        ((length, width, box_height), (0, width, box_height)),
        ((0, width, box_height), (0, 0, box_height)),
    ]
    for start, end in edges:
        x1, y1 = corner(*start)
        x2, y2 = corner(*end)
        parts.append(
            f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
            f'stroke="#c6c4bc" stroke-width="1" stroke-dasharray="4 3"/>'
        )

    # Ressam algoritmasi: arkadaki prizma once cizilir. Izometrikte "arkalik"
    # olcusu (x + y + z) toplamidir; kucuk olan arkadadir.
    ordered = sorted(packed.placements, key=lambda p: p.x + p.y + p.z)
    for placement in ordered:
        color = RISK_COLORS.get(placement.risk_category.value, "#9b9992")
        side, front, top = _faces(placement, scale)
        label = (
            f"{placement.name} — "
            f"{RISK_LABELS.get(placement.risk_category.value, placement.risk_category.value)} — "
            f"{placement.dx:.0f}x{placement.dy:.0f}x{placement.dz:.0f} cm"
        )
        parts.append(f"<g><title>{_escape(label)}</title>")
        for path, opacity in ((side, 0.62), (front, 0.82), (top, 1.0)):
            parts.append(
                f'<path d="{path}" fill="{color}" fill-opacity="{opacity}" '
                f'stroke="#fcfcfb" stroke-width="1"/>'
            )
        parts.append("</g>")

    # Gosterge -- renk tek basina bilgi tasimasin diye etiketli.
    present = {p.risk_category.value for p in packed.placements}
    legend_y = max_y * scale + _PADDING * 0.4
    legend_x = min_x * scale
    for risk in sorted(present):
        parts.append(
            f'<rect x="{legend_x:.2f}" y="{legend_y - 8:.2f}" width="10" height="10" '
            f'rx="2" fill="{RISK_COLORS.get(risk, "#9b9992")}"/>'
            f'<text x="{legend_x + 15:.2f}" y="{legend_y + 1:.2f}" '
            f'font-family="ui-sans-serif, system-ui, sans-serif" font-size="11" '
            f'fill="#52514e">{_escape(RISK_LABELS.get(risk, risk))}</text>'
        )
        legend_x += 15 + len(RISK_LABELS.get(risk, risk)) * 6.5 + 14

    parts.append("</svg>")
    return "".join(parts)


def render_plan_svg(boxes: list[PackedBox], box_height: float = 320.0) -> str:
    """Bir planin tum kolilerini tek bir HTML parcasinda yan yana cizer."""
    cards = []
    for index, packed in enumerate(boxes, start=1):
        cards.append(
            f'<figure style="margin:0">'
            f'<figcaption style="font:13px ui-sans-serif,system-ui,sans-serif;'
            f'color:#52514e;margin-bottom:6px">'
            f"<strong>Koli {index}: {_escape(packed.box.code)}</strong> — "
            f"{packed.outer_desi:.1f} desi, {packed.gross_weight_kg:.2f} kg brut, "
            f"%{packed.fill_ratio * 100:.0f} dolu</figcaption>"
            f"{render_box_svg(packed, box_height)}"
            f"</figure>"
        )
    return (
        '<div style="display:flex;flex-wrap:wrap;gap:20px;align-items:flex-start">'
        + "".join(cards)
        + "</div>"
    )


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )
