/**
 * Koli içi yerleşimin izometrik 3B görselleştirmesi.
 *
 * Neden Three.js değil?
 *   Görselleştirilen şey eksen hizalı dikdörtgenler prizmasından ibaret.
 *   İzometrik projeksiyon + ressam algoritması (arkadan öne çizim) bu iş için
 *   yeterli, ~150 satır tutuyor ve WebGL bağımlılığı getirmiyor. SVG olduğu için
 *   her ölçekte keskin, yazdırılabilir ve ekran okuyucuya `<title>` ile anlamlı.
 *
 * Renkler ürünün **risk sınıfını** taşır (tekstil / kırılabilir / sıvı / cihaz),
 * kimliğini değil — bu, sıvı bir ürünün emici ürünlerin yanında durduğunu
 * bakışta görünür kılar. Renk tek başına bilgi taşımasın diye her ürün ayrıca
 * hover ile adlandırılır ve altta tam liste verilir.
 */

import type { PackedBox, Placement } from "../api/types";

/** İzometrik izdüşüm: x sağa-aşağı, y sola-aşağı, z yukarı. */
const ISO_X = { x: 0.866, y: 0.5 };
const ISO_Y = { x: -0.866, y: 0.5 };

const RISK_COLOR: Record<string, string> = {
  yumusak: "var(--risk-soft)",
  kirilabilir: "var(--risk-fragile)",
  sivi: "var(--risk-liquid)",
  cihaz: "var(--risk-appliance)",
};

const RISK_LABEL: Record<string, string> = {
  yumusak: "Tekstil",
  kirilabilir: "Kırılabilir",
  sivi: "Sıvı",
  cihaz: "Cihaz",
};

interface Point {
  x: number;
  y: number;
}

function project(x: number, y: number, z: number, scale: number): Point {
  return {
    x: (x * ISO_X.x + y * ISO_Y.x) * scale,
    y: (x * ISO_X.y + y * ISO_Y.y - z) * scale,
  };
}

const toPath = (points: Point[]): string =>
  points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(" ") + " Z";

/**
 * Bir prizmanın görünen üç yüzünü çizer.
 *
 * Yüzler farklı parlaklıkta: üst yüz açık, ön yüz orta, yan yüz koyu. Bu,
 * hacmi tek renkli bir siluete indirgemeden derinlik hissi verir.
 */
function Cuboid({
  placement,
  scale,
  color,
}: {
  placement: Placement;
  scale: number;
  color: string;
}) {
  const { x, y, z, dx, dy, dz } = placement;
  const p = (px: number, py: number, pz: number) => project(px, py, pz, scale);

  const top = [p(x, y, z + dz), p(x + dx, y, z + dz), p(x + dx, y + dy, z + dz), p(x, y + dy, z + dz)];
  const front = [p(x, y + dy, z), p(x + dx, y + dy, z), p(x + dx, y + dy, z + dz), p(x, y + dy, z + dz)];
  const side = [p(x + dx, y, z), p(x + dx, y + dy, z), p(x + dx, y + dy, z + dz), p(x + dx, y, z + dz)];

  const label =
    `${placement.name} · ${RISK_LABEL[placement.risk_category] ?? placement.risk_category}` +
    ` · ${placement.dx.toFixed(0)}×${placement.dy.toFixed(0)}×${placement.dz.toFixed(0)} cm`;

  return (
    <g className="cuboid">
      <title>{label}</title>
      <path d={toPath(side)} fill={color} fillOpacity={0.62} stroke="var(--surface-1)" strokeWidth={1} />
      <path d={toPath(front)} fill={color} fillOpacity={0.82} stroke="var(--surface-1)" strokeWidth={1} />
      <path d={toPath(top)} fill={color} fillOpacity={1} stroke="var(--surface-1)" strokeWidth={1} />
    </g>
  );
}

/** Kolinin tel kafes sınırları — ürünlerin kutunun neresinde durduğunu gösterir. */
function BoxFrame({ l, w, h, scale }: { l: number; w: number; h: number; scale: number }) {
  const p = (x: number, y: number, z: number) => project(x, y, z, scale);
  const edges: [Point, Point][] = [
    [p(0, 0, 0), p(l, 0, 0)],
    [p(l, 0, 0), p(l, w, 0)],
    [p(l, w, 0), p(0, w, 0)],
    [p(0, w, 0), p(0, 0, 0)],
    [p(0, 0, 0), p(0, 0, h)],
    [p(l, 0, 0), p(l, 0, h)],
    [p(l, w, 0), p(l, w, h)],
    [p(0, w, 0), p(0, w, h)],
    [p(0, 0, h), p(l, 0, h)],
    [p(l, 0, h), p(l, w, h)],
    [p(l, w, h), p(0, w, h)],
    [p(0, w, h), p(0, 0, h)],
  ];
  return (
    <g>
      {edges.map(([a, b], index) => (
        <line
          key={index}
          x1={a.x}
          y1={a.y}
          x2={b.x}
          y2={b.y}
          stroke="var(--border-strong)"
          strokeWidth={1}
          strokeDasharray="4 3"
        />
      ))}
    </g>
  );
}

export function BoxViewer({ box, height = 260 }: { box: PackedBox; height?: number }) {
  const { inner_length_cm: l, inner_width_cm: w, inner_height_cm: h } = box;

  // Ölçek: izometrik izdüşümün sınırlayıcı kutusunu hesaplayıp görünüme sığdır.
  const corners = [
    project(0, 0, 0, 1),
    project(l, 0, 0, 1),
    project(l, w, 0, 1),
    project(0, w, 0, 1),
    project(0, 0, h, 1),
    project(l, 0, h, 1),
    project(l, w, h, 1),
    project(0, w, h, 1),
  ];
  const minX = Math.min(...corners.map((c) => c.x));
  const maxX = Math.max(...corners.map((c) => c.x));
  const minY = Math.min(...corners.map((c) => c.y));
  const maxY = Math.max(...corners.map((c) => c.y));

  const pad = 12;
  const scale = (height - 2 * pad) / (maxY - minY);
  const width = (maxX - minX) * scale + 2 * pad;

  // Ressam algoritması: arkadaki prizma önce çizilir. İzometrikte "arkalık"
  // ölçüsü (x + y + z) toplamıdır; küçük olan arkadadır.
  const ordered = [...box.placements].sort(
    (a, b) => a.x + a.y + a.z - (b.x + b.y + b.z),
  );

  return (
    <svg
      viewBox={`${minX * scale - pad} ${minY * scale - pad} ${width} ${height}`}
      width="100%"
      height={height}
      role="img"
      aria-label={`${box.box_code} kolisinin içindeki ${box.placements.length} ürünün yerleşimi`}
      style={{ display: "block", overflow: "visible" }}
    >
      <BoxFrame l={l} w={w} h={h} scale={scale} />
      {ordered.map((placement, index) => (
        <Cuboid
          key={`${placement.sku}-${index}`}
          placement={placement}
          scale={scale}
          color={RISK_COLOR[placement.risk_category] ?? "var(--muted-mark)"}
        />
      ))}
    </svg>
  );
}

export function RiskLegend() {
  return (
    <ul className="legend">
      {Object.entries(RISK_LABEL).map(([key, label]) => (
        <li key={key}>
          <span className="swatch" style={{ background: RISK_COLOR[key] }} />
          {label}
        </li>
      ))}
    </ul>
  );
}
