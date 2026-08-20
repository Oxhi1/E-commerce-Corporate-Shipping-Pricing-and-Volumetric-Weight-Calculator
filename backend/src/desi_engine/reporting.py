"""Simulasyon sonuclarindan bagimsiz (self-contained) HTML rapor uretir.

Grafikler harici kutuphane olmadan, satir ici SVG olarak ciziliyor: rapor tek bir
dosya olarak e-postayla gonderilebilsin, sunum makinesinde internet olmasa da
acilsin diye.

Renk secimi keyfi degil -- `dataviz` yonergesinin dogrulanmis kategorik paletinden
alindi ve `validate_palette.js` ile hem acik hem koyu temada denetlendi. Acik
temada uc renk yuzeye karsi 3:1 kontrastin altinda kaliyor; bu yuzden **her
grafikte gorunur deger etiketleri ve altinda tam veri tablosu** var (yonergenin
"relief" kurali). Renk hicbir yerde tek basina bilgi tasimiyor.
"""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .simulation.runner import SimulationResult

# ---- tasarim jetonlari -------------------------------------------------------

#: Maliyet bilesenleri (yigin grafik). Dogrulanmis kategorik paletin 1-4. yuvasi.
COST_COLORS_LIGHT = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100")
COST_COLORS_DARK = ("#3987e5", "#d95926", "#199e70", "#c98500")
COST_LABELS = ("Nakliye", "Hasar", "Gecikme", "Ambalaj")

#: Kargo firmalari (yigin grafik). Ayni paletin 1-5. yuvasi.
CARRIER_ORDER = ("ARAS", "MNG", "YURTICI", "SURAT", "PTT")
CARRIER_COLORS_LIGHT = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4")
CARRIER_COLORS_DARK = ("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181")

CHART_WIDTH = 720
ROW_HEIGHT = 34
BAR_HEIGHT = 20
LABEL_WIDTH = 210


def _esc(value: object) -> str:
    return html.escape(str(value))


# ---- SVG yapi taslari --------------------------------------------------------


def _stacked_bar_chart(
    rows: list[tuple[str, list[float]]],
    labels: tuple[str, ...],
    color_var_prefix: str,
    *,
    unit: str = "TL",
    value_format: str = "{:,.0f}",
) -> str:
    """Yatay yigin cubuk grafigi.

    Segmentler arasinda 2px yuzey boslugu var (yonergenin ayirici kurali) ve
    cubugun dis ucu yuvarlatilmis; ikisi de `clipPath` ile saglaniyor.
    """
    if not rows:
        return ""

    maximum = max(sum(values) for _, values in rows) or 1.0
    plot_width = CHART_WIDTH - LABEL_WIDTH - 90
    height = len(rows) * ROW_HEIGHT + 8

    parts = [
        f'<svg viewBox="0 0 {CHART_WIDTH} {height}" width="100%" height="{height}" '
        f'role="img" class="chart">'
    ]

    for index, (name, values) in enumerate(rows):
        y = index * ROW_HEIGHT + 4
        total = sum(values)
        bar_width = max(2.0, total / maximum * plot_width)
        clip_id = f"clip-{color_var_prefix}-{index}"

        parts.append(
            f'<clipPath id="{clip_id}">'
            f'<rect x="{LABEL_WIDTH}" y="{y}" width="{bar_width:.2f}" height="{BAR_HEIGHT}" '
            f'rx="4"/></clipPath>'
        )
        parts.append(
            f'<text x="{LABEL_WIDTH - 10}" y="{y + BAR_HEIGHT - 5}" '
            f'text-anchor="end" class="row-label">{_esc(name)}</text>'
        )
        parts.append(f'<g clip-path="url(#{clip_id})">')

        offset = 0.0
        for slot, value in enumerate(values):
            if value <= 0:
                continue
            segment = value / maximum * plot_width
            parts.append(
                f'<rect x="{LABEL_WIDTH + offset:.2f}" y="{y}" '
                f'width="{segment:.2f}" height="{BAR_HEIGHT}" '
                f'fill="var(--{color_var_prefix}-{slot + 1})">'
                f"<title>{_esc(name)} — {_esc(labels[slot])}: "
                f"{value_format.format(value)} {unit}</title></rect>"
            )
            # 2px yuzey boslugu: bir sonraki segmentin sol kenarina cizilir.
            offset += segment
            parts.append(
                f'<rect x="{LABEL_WIDTH + offset - 1:.2f}" y="{y}" width="2" '
                f'height="{BAR_HEIGHT}" fill="var(--surface-1)"/>'
            )

        parts.append("</g>")
        parts.append(
            f'<text x="{LABEL_WIDTH + bar_width + 8:.2f}" y="{y + BAR_HEIGHT - 5}" '
            f'class="value-label">{value_format.format(total)}</text>'
        )

    parts.append("</svg>")
    return "".join(parts)


def _legend(labels: tuple[str, ...], color_var_prefix: str) -> str:
    items = "".join(
        f'<li><span class="swatch" style="background:var(--{color_var_prefix}-{i + 1})"></span>'
        f"{_esc(label)}</li>"
        for i, label in enumerate(labels)
    )
    return f'<ul class="legend">{items}</ul>'


def _interval_chart(rows: list[tuple[str, float, float, float]]) -> str:
    """Nokta + guven araligi grafigi (tasarruf karsilastirmalari).

    Vurgu formu: tek renk + notr. Sifir cizgisi referans; araligi sifiri kapsayan
    karsilastirmalar notr renkte cizilir ve "anlamsiz" olarak etiketlenir --
    okuyucu, istatistiksel olarak dogrulanmamis bir kazanci kazanç sanmasin diye.
    """
    if not rows:
        return ""

    lows = [low for _, _, low, _ in rows]
    highs = [high for _, _, _, high in rows]
    minimum = min(0.0, min(lows)) * 1.15
    maximum = max(0.0, max(highs)) * 1.15
    span = (maximum - minimum) or 1.0

    plot_width = CHART_WIDTH - LABEL_WIDTH - 90
    height = len(rows) * ROW_HEIGHT + 26

    def x_of(value: float) -> float:
        return LABEL_WIDTH + (value - minimum) / span * plot_width

    zero_x = x_of(0.0)
    parts = [
        f'<svg viewBox="0 0 {CHART_WIDTH} {height}" width="100%" height="{height}" '
        f'role="img" class="chart">',
        f'<line x1="{zero_x:.1f}" y1="0" x2="{zero_x:.1f}" y2="{height - 22}" class="zero-line"/>',
        f'<text x="{zero_x:.1f}" y="{height - 6}" text-anchor="middle" class="axis-label">'
        f"0 TL (fark yok)</text>",
    ]

    for index, (name, mean, low, high) in enumerate(rows):
        y = index * ROW_HEIGHT + 4 + BAR_HEIGHT / 2
        significant = not (low <= 0.0 <= high)
        color = "var(--accent)" if significant else "var(--muted-mark)"

        parts.append(
            f'<text x="{LABEL_WIDTH - 10}" y="{y + 4}" text-anchor="end" '
            f'class="row-label">{_esc(name)}</text>'
        )
        parts.append(
            f'<line x1="{x_of(low):.1f}" y1="{y:.1f}" x2="{x_of(high):.1f}" y2="{y:.1f}" '
            f'stroke="{color}" stroke-width="2" stroke-linecap="round"/>'
        )
        for bound in (low, high):
            parts.append(
                f'<line x1="{x_of(bound):.1f}" y1="{y - 5:.1f}" '
                f'x2="{x_of(bound):.1f}" y2="{y + 5:.1f}" stroke="{color}" stroke-width="2"/>'
            )
        parts.append(
            f'<circle cx="{x_of(mean):.1f}" cy="{y:.1f}" r="5" fill="{color}" '
            f'stroke="var(--surface-1)" stroke-width="2">'
            f"<title>{_esc(name)}: {mean:+.2f} TL "
            f"[{low:+.2f}, {high:+.2f}]</title></circle>"
        )
        suffix = "" if significant else "  (anlamsiz)"
        parts.append(
            f'<text x="{max(x_of(high), x_of(mean)) + 10:.1f}" y="{y + 4:.1f}" '
            f'class="value-label">{mean:+.1f}{suffix}</text>'
        )

    parts.append("</svg>")
    return "".join(parts)


def _calibration_chart(bins) -> str:
    """Tahmin edilen hasar olasiligi vs gerceklesen frekans.

    Kosegen mukemmel kalibrasyon. Noktalar kosegenin ustundeyse model gercekten
    olandan az hasar tahmin ediyor (fazla iyimser), altindaysa fazla kotumser.
    """
    if not bins:
        return "<p class='note'>Kalibrasyon verisi uretilemedi.</p>"

    size = 300
    pad = 42
    limit = (
        max(max(b.predicted_mean for b in bins), max(b.observed_rate for b in bins), 1e-4) * 1.15
    )

    def coord(value: float) -> tuple[float, float]:
        return pad + value / limit * (size - pad - 12), size - pad - value / limit * (
            size - pad - 12
        )

    parts = [
        f'<svg viewBox="0 0 {size + 130} {size}" width="100%" height="{size}" '
        f'role="img" class="chart">',
        f'<line x1="{pad}" y1="{size - pad}" x2="{size - 12}" y2="{size - pad}" class="axis"/>',
        f'<line x1="{pad}" y1="12" x2="{pad}" y2="{size - pad}" class="axis"/>',
        f'<line x1="{pad}" y1="{size - pad}" x2="{coord(limit)[0]:.1f}" '
        f'y2="{coord(limit)[1]:.1f}" class="reference-line"/>',
        f'<text x="{size / 2}" y="{size - 8}" text-anchor="middle" class="axis-label">'
        f"Tahmin edilen hasar olasiligi</text>",
        f'<text x="12" y="{size / 2}" text-anchor="middle" class="axis-label" '
        f'transform="rotate(-90 12 {size / 2})">Gerceklesen oran</text>',
        f'<text x="{coord(limit)[0] - 6:.1f}" y="{coord(limit)[1] + 14:.1f}" '
        f'class="axis-label reference-label">mukemmel kalibrasyon</text>',
    ]

    points = [coord(b.predicted_mean)[0] for b in bins], [coord(b.observed_rate)[1] for b in bins]
    path = " ".join(
        f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}"
        for i, (x, y) in enumerate(zip(points[0], points[1], strict=True))
    )
    parts.append(f'<path d="{path}" fill="none" stroke="var(--accent)" stroke-width="2"/>')

    for bucket, x, y in zip(bins, points[0], points[1], strict=True):
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="var(--accent)" '
            f'stroke="var(--surface-1)" stroke-width="2">'
            f"<title>tahmin %{bucket.predicted_mean * 100:.2f} — "
            f"gerceklesen %{bucket.observed_rate * 100:.2f} "
            f"({bucket.count:,} gonderi)</title></circle>"
        )

    parts.append("</svg>")
    return "".join(parts)


# ---- tablolar ----------------------------------------------------------------


def _table(headers: list[str], rows: list[list[str]], caption: str = "") -> str:
    head = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{_esc(cell)}</td>" for cell in row) + "</tr>" for row in rows
    )
    cap = f"<caption>{_esc(caption)}</caption>" if caption else ""
    return f"<table>{cap}<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


# ---- rapor ------------------------------------------------------------------


def build_html_report(result: SimulationResult) -> str:
    """Tam raporu HTML metni olarak uretir."""
    summaries = list(result.summaries.values())

    cost_rows = [
        (
            f"{s.policy_code.value} {s.label}",
            [
                s.freight_try / s.orders,
                s.damage_try / s.orders,
                s.delay_try / s.orders,
                s.packaging_try / s.orders,
            ],
        )
        for s in summaries
    ]

    interval_rows = [
        (
            c.treatment.split(" ", 1)[0] + " vs " + c.baseline.split(" ", 1)[0],
            c.mean_difference,
            c.ci_low,
            c.ci_high,
        )
        for c in result.comparisons
    ]

    carrier_rows = [
        (
            f"{s.policy_code.value} {s.label}",
            [s.carrier_mix.get(code, 0) for code in CARRIER_ORDER],
        )
        for s in summaries
    ]

    best = max(result.comparisons, key=lambda c: c.mean_difference, default=None)
    hero_value = f"{best.mean_difference:+.2f} TL" if best else "—"
    hero_note = best.describe() if best else "Karsilastirma uretilemedi."

    summary_table = _table(
        [
            "Politika",
            "TL/siparis",
            "Nakliye",
            "Gizli maliyet payi",
            "Hasar %",
            "Gec %",
            "Ort. gun",
            "Ort. koli",
            "Ort. desi",
        ],
        [
            [
                f"{s.policy_code.value} {s.label}",
                f"{s.cost_per_order_try:,.2f}",
                f"{s.freight_per_order_try:,.2f}",
                f"%{s.hidden_cost_share * 100:.1f}",
                f"%{s.damage_rate * 100:.2f}",
                f"%{s.late_rate * 100:.1f}",
                f"{s.mean_delivery_days:.2f}",
                f"{s.mean_parcels:.2f}",
                f"{s.mean_chargeable_desi:.1f}",
            ]
            for s in summaries
        ],
        "Politika karsilastirma ozeti",
    )

    comparison_table = _table(
        [
            "Karsilastirma",
            "Ortalama fark (TL/siparis)",
            "%95 G.A. alt",
            "%95 G.A. ust",
            "Goreli",
            "Sonuc",
        ],
        [
            [
                f"{c.treatment.split(' ', 1)[0]} vs {c.baseline.split(' ', 1)[0]}",
                f"{c.mean_difference:+.2f}",
                f"{c.ci_low:+.2f}",
                f"{c.ci_high:+.2f}",
                f"%{c.relative_saving * 100:+.2f}",
                "anlamli" if c.is_significant else "ANLAMSIZ",
            ]
            for c in result.comparisons
        ],
        "Eslestirilmis bootstrap sonuclari",
    )

    calibration_table = _table(
        ["Tahmin araligi", "Gonderi", "Ort. tahmin", "Gerceklesen"],
        [
            [
                f"%{b.lower * 100:.2f} – %{b.upper * 100:.2f}",
                f"{b.count:,}",
                f"%{b.predicted_mean * 100:.3f}",
                f"%{b.observed_rate * 100:.3f}",
            ]
            for b in result.calibration
        ],
        "Kalibrasyon kovalari",
    )

    carrier_table = _table(
        ["Politika", *CARRIER_ORDER],
        [
            [
                f"{s.policy_code.value} {s.label}",
                *[f"{s.carrier_mix.get(code, 0):,}" for code in CARRIER_ORDER],
            ]
            for s in summaries
        ],
        "Firma dagilimi (gonderi adedi)",
    )

    generated = datetime.now().strftime("%d.%m.%Y %H:%M")

    return f"""<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ozdilek Desi Motoru — Simulasyon Raporu</title>
<style>
{_STYLES}
</style>
</head>
<body>
<main class="viz-root">

<header>
  <p class="eyebrow">Ozdilek · Cok Firmali Kargo Fiyatlama ve Desi Motoru</p>
  <h1>Simulasyon Raporu</h1>
  <p class="meta">{result.n_orders:,} siparis · tohum {result.seed} ·
     {result.elapsed_seconds:.1f} sn · uretim {generated}</p>
  <p class="warning-banner">ORNEK TARIFE — bu rapor sentetik tarife ve sentetik
     gecmis sevkiyat verisiyle uretilmistir. Rakamlar gercek Ozdilek sozlesme
     fiyatlari degildir; buyukluk mertebesi gercekci, degerler uydurmadir.</p>
</header>

<section class="hero">
  <p class="hero-label">Siparis basina en yuksek tasarruf</p>
  <p class="hero-value">{hero_value}</p>
  <p class="hero-note">{_esc(hero_note)}</p>
</section>

<section>
  <h2>Siparis basina maliyet, kalemlerine ayrilmis</h2>
  <p class="lead">Mevcut sistemin gordugu tek kalem <strong>nakliye</strong>.
     Hasar, gecikme ve ambalaj faturada gorunmez ama odenir. Politikalarin
     siralamasi, yalnizca nakliyeye bakildiginda tersine doner.</p>
  {_legend(COST_LABELS, "cost")}
  {_stacked_bar_chart(cost_rows, COST_LABELS, "cost")}
  {summary_table}
</section>

<section>
  <h2>Tasarruf ve belirsizligi</h2>
  <p class="lead">Nokta ortalama farki, cubuk %95 guven araligi.
     Politikalar <strong>ayni siparis akisinda ve ayni sans cekilisleriyle</strong>
     kosturuldu (ortak rastgele sayilar); aralik eslestirilmis bootstrap ile
     hesaplandi. Araligi sifiri kapsayan karsilastirmalar notr renkte ve
     "anlamsiz" olarak isaretli.</p>
  {_interval_chart(interval_rows)}
  {comparison_table}
</section>

<section>
  <h2>Model kalibrasyonu</h2>
  <p class="lead">Motorun "%2 hasar olasiligi" dedigi gonderilerin gercekten
     yaklasik %2'si hasar gormeli. Beklenen kalibrasyon hatasi (ECE):
     <strong>{result.calibration_error:.4f}</strong>. Dogru firmayi secen ama
     kalibre olmayan bir model, maliyetleri yanlis buyuklukte tahmin eder ve
     tasarruf raporunu guvenilmez kilar.</p>
  {_calibration_chart(result.calibration)}
  {calibration_table}
</section>

<section>
  <h2>Firma dagilimi</h2>
  <p class="lead">Motor tek bir firmaya kilitlenmiyor; sepet icerigi, varis ili ve
     musteri degeri degistikce kazanan da degisiyor. P4'un dagilimi P3'ten daha
     dengeli, cunku gunluk kapasite limitlerini dikkate aliyor.</p>
  {_legend(CARRIER_ORDER, "carrier")}
  {
        _stacked_bar_chart(
            carrier_rows, CARRIER_ORDER, "carrier", unit="gonderi", value_format="{:,.0f}"
        )
    }
  {carrier_table}
</section>

<footer>
  <p>Paketleme onbellegi isabet orani %{result.packing_cache_hit_rate * 100:.1f}.
     Ayni tohumla yeniden kosuldugunda bu rapor birebir ayni sayilari uretir.</p>
</footer>

</main>
</body>
</html>
"""


_STYLES = """
*, *::before, *::after { box-sizing: border-box; }
body { margin: 0; }

.viz-root {
  color-scheme: light;
  --surface-0: #f4f4f2;
  --surface-1: #fcfcfb;
  --border: #dedcd6;
  --text-primary: #0b0b0b;
  --text-secondary: #52514e;
  --text-muted: #7a7873;
  --accent: #2a78d6;
  --muted-mark: #9b9992;
  --warning-bg: #fff4e5;
  --warning-border: #eb6834;
  --cost-1: #2a78d6; --cost-2: #eb6834; --cost-3: #1baf7a; --cost-4: #eda100;
  --carrier-1: #2a78d6; --carrier-2: #eb6834; --carrier-3: #1baf7a;
  --carrier-4: #eda100; --carrier-5: #e87ba4;

  max-width: 860px;
  margin: 0 auto;
  padding: 32px 20px 64px;
  background: var(--surface-1);
  color: var(--text-primary);
  font: 15px/1.6 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
}

@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) .viz-root {
    color-scheme: dark;
    --surface-0: #111110;
    --surface-1: #1a1a19;
    --border: #3a3936;
    --text-primary: #ffffff;
    --text-secondary: #c3c2b7;
    --text-muted: #8f8e86;
    --accent: #3987e5;
    --muted-mark: #6b6a64;
    --warning-bg: #2e2317;
    --warning-border: #d95926;
    --cost-1: #3987e5; --cost-2: #d95926; --cost-3: #199e70; --cost-4: #c98500;
    --carrier-1: #3987e5; --carrier-2: #d95926; --carrier-3: #199e70;
    --carrier-4: #c98500; --carrier-5: #d55181;
  }
}
:root[data-theme="dark"] .viz-root {
  color-scheme: dark;
  --surface-0: #111110;
  --surface-1: #1a1a19;
  --border: #3a3936;
  --text-primary: #ffffff;
  --text-secondary: #c3c2b7;
  --text-muted: #8f8e86;
  --accent: #3987e5;
  --muted-mark: #6b6a64;
  --warning-bg: #2e2317;
  --warning-border: #d95926;
  --cost-1: #3987e5; --cost-2: #d95926; --cost-3: #199e70; --cost-4: #c98500;
  --carrier-1: #3987e5; --carrier-2: #d95926; --carrier-3: #199e70;
  --carrier-4: #c98500; --carrier-5: #d55181;
}

.eyebrow { font-size: 13px; letter-spacing: .04em; text-transform: uppercase;
  color: var(--text-muted); margin: 0 0 4px; }
h1 { font-size: 30px; line-height: 1.2; margin: 0 0 6px; letter-spacing: -.02em; }
h2 { font-size: 20px; margin: 0 0 6px; letter-spacing: -.01em; }
.meta { color: var(--text-secondary); margin: 0 0 16px; font-size: 14px; }
.lead { color: var(--text-secondary); margin: 0 0 16px; max-width: 68ch; }
.note { color: var(--text-muted); font-size: 14px; }

.warning-banner {
  background: var(--warning-bg);
  border-left: 3px solid var(--warning-border);
  padding: 10px 14px; margin: 0; border-radius: 0 6px 6px 0;
  font-size: 14px; color: var(--text-secondary);
}

section { margin-top: 44px; }

.hero { background: var(--surface-0); border: 1px solid var(--border);
  border-radius: 10px; padding: 22px 24px; margin-top: 28px; }
.hero-label { margin: 0; font-size: 13px; text-transform: uppercase;
  letter-spacing: .04em; color: var(--text-muted); }
.hero-value { margin: 4px 0 8px; font-size: 52px; line-height: 1;
  font-weight: 650; letter-spacing: -.03em; color: var(--text-primary); }
.hero-note { margin: 0; color: var(--text-secondary); font-size: 14px; }

.legend { display: flex; flex-wrap: wrap; gap: 6px 18px; list-style: none;
  padding: 0; margin: 0 0 10px; font-size: 13px; color: var(--text-secondary); }
.legend li { display: flex; align-items: center; gap: 7px; }
.swatch { width: 11px; height: 11px; border-radius: 3px; flex: none; }

.chart { display: block; margin-bottom: 14px; overflow: visible; }
.chart text { font: 12px/1 ui-sans-serif, system-ui, sans-serif; }
.row-label { fill: var(--text-secondary); }
.value-label { fill: var(--text-primary); font-weight: 600; }
.axis-label { fill: var(--text-muted); font-size: 11px; }
.axis { stroke: var(--border); stroke-width: 1; }
.zero-line { stroke: var(--text-muted); stroke-width: 1; stroke-dasharray: 3 3; }
.reference-line { stroke: var(--muted-mark); stroke-width: 1.5; stroke-dasharray: 4 4; }
.reference-label { fill: var(--muted-mark); }

table { width: 100%; border-collapse: collapse; font-size: 13.5px;
  margin-top: 14px; overflow-x: auto; display: block; }
caption { text-align: left; color: var(--text-muted); font-size: 12.5px;
  padding-bottom: 6px; }
th, td { padding: 7px 10px; text-align: right; border-bottom: 1px solid var(--border);
  white-space: nowrap; }
th:first-child, td:first-child { text-align: left; }
thead th { color: var(--text-muted); font-weight: 600; font-size: 12.5px;
  border-bottom-width: 2px; }
tbody tr:last-child td { border-bottom: none; }

footer { margin-top: 48px; padding-top: 16px; border-top: 1px solid var(--border);
  color: var(--text-muted); font-size: 13px; }
"""


def write_html_report(result: SimulationResult, path: Path) -> Path:
    """Raporu diske yazar ve yolunu doner."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_html_report(result), encoding="utf-8")
    return path
