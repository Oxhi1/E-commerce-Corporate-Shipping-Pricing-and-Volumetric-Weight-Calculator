/**
 * Grafik bileşenleri — bağımlılıksız SVG.
 *
 * Recharts/D3 yerine elle SVG: grafik sayısı az, biçimler basit ve renk/kontrast
 * kuralları HTML raporuyla birebir aynı kalıyor. Bir grafik kütüphanesi kendi
 * varsayılan paletini getirir ve doğrulanmış paletin üzerine yazardı.
 *
 * Her grafiğin yanında **görünür değer etiketi** var; açık temada bazı kategorik
 * renkler yüzeye karşı 3:1 kontrastın altında kaldığı için bu zorunlu (renk tek
 * başına bilgi taşımamalı). Sayfalar ayrıca tam veri tablosunu gösterir.
 */

import type { ReactNode } from "react";

const LABEL_WIDTH = 190;
const ROW_HEIGHT = 32;
const BAR_HEIGHT = 19;

export interface Segment {
  label: string;
  value: number;
  colorVar: string;
}

export interface StackedRow {
  name: string;
  segments: Segment[];
  emphasis?: boolean;
}

export function Legend({ items }: { items: { label: string; colorVar: string }[] }) {
  return (
    <ul className="legend">
      {items.map((item) => (
        <li key={item.label}>
          <span className="swatch" style={{ background: `var(${item.colorVar})` }} />
          {item.label}
        </li>
      ))}
    </ul>
  );
}

/**
 * Yatay yığın çubuk grafiği.
 *
 * Segmentler arasında 2px yüzey boşluğu var ve çubuğun dış ucu yuvarlatılmış;
 * ikisi de `clipPath` ile sağlanıyor, böylece kenarlar kesişmiyor.
 */
export function StackedBarChart({
  rows,
  width = 640,
  format = (v) => v.toFixed(0),
  idPrefix,
}: {
  rows: StackedRow[];
  width?: number;
  format?: (value: number) => string;
  idPrefix: string;
}) {
  if (rows.length === 0) return null;

  const totals = rows.map((row) => row.segments.reduce((sum, s) => sum + s.value, 0));
  const maximum = Math.max(...totals, 1);
  const plotWidth = width - LABEL_WIDTH - 82;
  const height = rows.length * ROW_HEIGHT + 6;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} height={height} className="chart" role="img">
      {rows.map((row, rowIndex) => {
        const y = rowIndex * ROW_HEIGHT + 3;
        const total = totals[rowIndex] ?? 0;
        const barWidth = Math.max(2, (total / maximum) * plotWidth);
        const clipId = `${idPrefix}-clip-${rowIndex}`;
        let offset = 0;

        return (
          <g key={row.name}>
            <clipPath id={clipId}>
              <rect x={LABEL_WIDTH} y={y} width={barWidth} height={BAR_HEIGHT} rx={4} />
            </clipPath>
            <text
              x={LABEL_WIDTH - 10}
              y={y + BAR_HEIGHT - 5}
              textAnchor="end"
              className="row-label"
              style={row.emphasis ? { fontWeight: 700, fill: "var(--text-primary)" } : undefined}
            >
              {row.name}
            </text>
            <g clipPath={`url(#${clipId})`}>
              {row.segments.map((segment) => {
                if (segment.value <= 0) return null;
                const segmentWidth = (segment.value / maximum) * plotWidth;
                const x = LABEL_WIDTH + offset;
                offset += segmentWidth;
                return (
                  <g key={segment.label}>
                    <rect
                      x={x}
                      y={y}
                      width={segmentWidth}
                      height={BAR_HEIGHT}
                      fill={`var(${segment.colorVar})`}
                    >
                      <title>{`${row.name} — ${segment.label}: ${format(segment.value)}`}</title>
                    </rect>
                    {/* Segmentler arası 2px yüzey boşluğu */}
                    <rect
                      x={LABEL_WIDTH + offset - 1}
                      y={y}
                      width={2}
                      height={BAR_HEIGHT}
                      fill="var(--surface-1)"
                    />
                  </g>
                );
              })}
            </g>
            <text
              x={LABEL_WIDTH + barWidth + 8}
              y={y + BAR_HEIGHT - 5}
              className="value-label"
            >
              {format(total)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/**
 * Nokta + güven aralığı grafiği.
 *
 * Aralığı sıfırı kapsayan karşılaştırmalar nötr renkte ve "anlamsız" etiketiyle
 * çizilir — okuyucu istatistiksel olarak doğrulanmamış bir farkı kazanç sanmasın.
 */
export function IntervalChart({
  rows,
  width = 640,
}: {
  rows: { name: string; mean: number; low: number; high: number }[];
  width?: number;
}) {
  if (rows.length === 0) return null;

  const minimum = Math.min(0, ...rows.map((r) => r.low)) * 1.15;
  const maximum = Math.max(0, ...rows.map((r) => r.high)) * 1.15;
  const span = maximum - minimum || 1;
  const plotWidth = width - LABEL_WIDTH - 110;
  const height = rows.length * ROW_HEIGHT + 24;

  const xOf = (value: number) => LABEL_WIDTH + ((value - minimum) / span) * plotWidth;
  const zeroX = xOf(0);

  return (
    <svg viewBox={`0 0 ${width} ${height}`} height={height} className="chart" role="img">
      <line x1={zeroX} y1={0} x2={zeroX} y2={height - 20} className="zero-line" />
      <text x={zeroX} y={height - 5} textAnchor="middle" className="axis-label">
        0 TL (fark yok)
      </text>
      {rows.map((row, index) => {
        const y = index * ROW_HEIGHT + 3 + BAR_HEIGHT / 2;
        const significant = !(row.low <= 0 && 0 <= row.high);
        const color = significant ? "var(--accent)" : "var(--muted-mark)";
        return (
          <g key={row.name}>
            <text x={LABEL_WIDTH - 10} y={y + 4} textAnchor="end" className="row-label">
              {row.name}
            </text>
            <line
              x1={xOf(row.low)}
              y1={y}
              x2={xOf(row.high)}
              y2={y}
              stroke={color}
              strokeWidth={2}
              strokeLinecap="round"
            />
            {[row.low, row.high].map((bound, i) => (
              <line
                key={i}
                x1={xOf(bound)}
                y1={y - 5}
                x2={xOf(bound)}
                y2={y + 5}
                stroke={color}
                strokeWidth={2}
              />
            ))}
            <circle
              cx={xOf(row.mean)}
              cy={y}
              r={5}
              fill={color}
              stroke="var(--surface-1)"
              strokeWidth={2}
            >
              <title>{`${row.name}: ${row.mean.toFixed(2)} TL [${row.low.toFixed(2)}, ${row.high.toFixed(2)}]`}</title>
            </circle>
            <text
              x={Math.max(xOf(row.high), xOf(row.mean)) + 10}
              y={y + 4}
              className="value-label"
            >
              {row.mean > 0 ? "+" : ""}
              {row.mean.toFixed(1)}
              {significant ? "" : " (anlamsız)"}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/** Basit maliyet dökümü şelalesi — kalemler ve toplam. */
export function CostWaterfall({
  lines,
  total,
}: {
  lines: { label: string; amount_try: number }[];
  total: number;
}) {
  const maximum = Math.max(...lines.map((l) => Math.abs(l.amount_try)), 1);
  return (
    <div className="stack" style={{ gap: 6 }}>
      {lines.map((line) => (
        <div key={line.label} style={{ display: "grid", gridTemplateColumns: "150px 1fr 90px", gap: 10, alignItems: "center" }}>
          <span style={{ fontSize: 13, color: "var(--text-secondary)" }}>{line.label}</span>
          <div style={{ background: "var(--surface-2)", borderRadius: 4, height: 14 }}>
            <div
              style={{
                width: `${(Math.abs(line.amount_try) / maximum) * 100}%`,
                height: "100%",
                borderRadius: 4,
                background: line.amount_try < 0 ? "var(--good)" : "var(--accent)",
              }}
            />
          </div>
          <span className="num" style={{ fontSize: 13, textAlign: "right", fontWeight: 600 }}>
            {line.amount_try.toFixed(2)}
          </span>
        </div>
      ))}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "150px 1fr 90px",
          gap: 10,
          borderTop: "2px solid var(--border-strong)",
          paddingTop: 7,
          marginTop: 3,
          fontWeight: 700,
        }}
      >
        <span style={{ fontSize: 13 }}>TOPLAM</span>
        <span />
        <span className="num" style={{ fontSize: 13, textAlign: "right" }}>
          {total.toFixed(2)}
        </span>
      </div>
    </div>
  );
}

export function Stat({
  label,
  value,
  note,
  tone,
}: {
  label: string;
  value: ReactNode;
  note?: ReactNode;
  tone?: "good" | "critical" | "warning";
}) {
  const color =
    tone === "good"
      ? "var(--good)"
      : tone === "critical"
        ? "var(--critical)"
        : tone === "warning"
          ? "var(--warning)"
          : undefined;
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value" style={color ? { color } : undefined}>
        {value}
      </div>
      {note && <div className="stat-note">{note}</div>}
    </div>
  );
}
