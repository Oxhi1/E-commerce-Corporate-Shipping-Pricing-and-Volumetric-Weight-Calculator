/**
 * Sanal kutulama sekmesi.
 *
 * Sunumun en akılda kalıcı parçası: "desi tasarrufu" soyut bir yüzde olmaktan
 * çıkıp kolinin içindeki gerçek yerleşim olarak görünür hale geliyor.
 *
 * Baz çizgiler kasıtlı olarak üç ayrı satır: "ürün desilerinin toplamı" fiziksel
 * olarak ulaşılamaz bir sayı ve ona kıyasla tasarruf iddia etmek dürüst olmaz.
 * Tasarruf, gerçekten uygulanabilir bir alternatife (her ürün ayrı koli) kıyasla
 * ölçülür; kotasyon toplamıyla fark ise ayrı bir kalem olarak — bir kazanç değil,
 * mevcut sistemin düşük fiyat verdiğini gösteren bir bulgu olarak — raporlanır.
 */

import { useState } from "react";

import type { PackResponse } from "../api/types";
import { BoxViewer, RiskLegend } from "../components/BoxViewer";

export function PackingPage({ data }: { data: PackResponse }) {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const plan = data.plans[Math.min(selectedIndex, data.plans.length - 1)];
  if (!plan) return null;

  const { baselines } = data;

  return (
    <div className="stack">
      <div className="card">
        <h2>Baz çizgiler</h2>
        <p className="card-note">
          "Ne kadar kazandık" sorusunun paydası. Üçü de ayrı ayrı gösteriliyor
          çünkü hangisine kıyasladığınız sonucu tamamen değiştirir.
        </p>
        <div className="stat-row">
          <div className="stat">
            <div className="stat-label">Kotasyon toplamı</div>
            <div className="stat-value" style={{ fontSize: 21 }}>
              {baselines.quoted_sum_desi.toFixed(1)} desi
            </div>
            <div className="stat-note">Ürün desilerinin toplamı — fiziksel olarak ulaşılamaz</div>
          </div>
          <div className="stat">
            <div className="stat-label">Her ürün ayrı koli</div>
            <div className="stat-value" style={{ fontSize: 21 }}>
              {baselines.one_box_per_item_desi.toFixed(1)} desi
            </div>
            <div className="stat-note">
              {baselines.one_box_per_item_parcels} koli — gerçek operasyonel baz çizgi
            </div>
          </div>
          <div className="stat">
            <div className="stat-label">Hacim kuralı</div>
            <div className="stat-value" style={{ fontSize: 21 }}>
              {baselines.volume_rule_desi.toFixed(1)} desi
            </div>
            <div className="stat-note">
              {baselines.volume_rule_parcels} koli — geometriyi yok sayan Excel mantığı
            </div>
          </div>
          <div className="stat">
            <div className="stat-label">Motorun planı</div>
            <div className="stat-value" style={{ fontSize: 21, color: "var(--good)" }}>
              {plan.packed_desi.toFixed(1)} desi
            </div>
            <div className="stat-note">
              {plan.parcel_count} koli — %{(plan.desi_savings_pct * 100).toFixed(1)} tasarruf
            </div>
          </div>
        </div>

        {plan.quote_gap_pct > 0 && (
          <div className="callout callout--warning" style={{ marginTop: 14 }}>
            <strong>Kotasyon açığı: %{(plan.quote_gap_pct * 100).toFixed(1)}.</strong>{" "}
            Mevcut sistem ürün desilerini toplayarak fiyat veriyor, kargo firması
            ise kolinin desisinden kesiyor. Bu fark bir tasarruf fırsatı değil;
            her siparişte sessizce cepten ödenen bir kalem.
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-header">
          <h2>Aday koli planları</h2>
          <span className="badge badge--neutral">{data.plans.length} aday</span>
        </div>
        <p className="card-note">
          Planlayıcı tek bir plan değil, (desi, parça sayısı) düzleminde
          <strong> Pareto-optimal</strong> birkaç aday üretir. Asgari ücret parça
          başına uygulandığı için "en az desi" her zaman en ucuz değildir; hangisinin
          kazandığını tarifeyi bilen karar motoru söyler.
        </p>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Strateji / varyant</th>
                <th>Koli</th>
                <th>Desi</th>
                <th>Tasarruf</th>
                <th>Ort. dolgu</th>
                <th>Kontamine koli</th>
                <th>Ambalaj</th>
                <th>Kutular</th>
              </tr>
            </thead>
            <tbody>
              {data.plans.map((candidate, index) => (
                <tr
                  key={`${candidate.strategy}-${candidate.variant}`}
                  className={index === selectedIndex ? "is-selected" : undefined}
                  onClick={() => setSelectedIndex(index)}
                  style={{ cursor: "pointer" }}
                >
                  <td>
                    {candidate.strategy} / {candidate.variant}
                  </td>
                  <td className="num">{candidate.parcel_count}</td>
                  <td className="num">{candidate.packed_desi.toFixed(2)}</td>
                  <td className="num">
                    %{(candidate.desi_savings_pct * 100).toFixed(1)}
                  </td>
                  <td className="num">%{(candidate.mean_fill_ratio * 100).toFixed(0)}</td>
                  <td className="num">
                    {candidate.contaminating_boxes > 0 ? (
                      <span className="badge badge--critical">
                        {candidate.contaminating_boxes}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="num">{candidate.packaging_cost_try.toFixed(2)} TL</td>
                  <td>{candidate.boxes.map((box) => box.box_code).join(" + ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <h2>Koli içi yerleşim</h2>
          <span className="badge badge--neutral">
            {plan.strategy} / {plan.variant}
          </span>
        </div>
        <p className="card-note">
          İzometrik görünüm; renkler ürünün risk sınıfını gösterir. Ürünün üzerine
          gelince adı ve ölçüleri görünür.
        </p>
        <RiskLegend />

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
            gap: 18,
          }}
        >
          {plan.boxes.map((box, index) => (
            <div key={`${box.box_code}-${index}`}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  fontSize: 13,
                  marginBottom: 6,
                }}
              >
                <strong>
                  Koli {index + 1}: {box.box_code}
                </strong>
                <span style={{ color: "var(--text-muted)" }}>
                  {box.outer_desi.toFixed(1)} desi · %{(box.fill_ratio * 100).toFixed(0)} dolu
                </span>
              </div>
              <div
                style={{
                  background: "var(--surface-0)",
                  border: "1px solid var(--border)",
                  borderRadius: "var(--radius-sm)",
                  padding: 8,
                }}
              >
                <BoxViewer box={box} />
              </div>
              <ul
                style={{
                  margin: "8px 0 0",
                  paddingLeft: 18,
                  fontSize: 12.5,
                  color: "var(--text-secondary)",
                }}
              >
                {box.placements.map((placement, i) => (
                  <li key={`${placement.sku}-${i}`}>
                    {placement.name}
                    {placement.is_liquid && " · sıvı"}
                    {placement.is_absorbent && " · emici"}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
