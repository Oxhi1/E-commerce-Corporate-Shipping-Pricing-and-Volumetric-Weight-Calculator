/**
 * Karar açıklaması sekmesi.
 *
 * Motorun en kritik yüzü. Depoda etiket basacak personel bugüne kadar "en ucuzu
 * seç" kuralıyla çalıştı; sistem ondan pahalı görünen bir firmayı seçmesini
 * istiyorsa gerekçesini göstermek zorunda. Bu sayfa, gerekçeyi hem cümle olarak
 * hem de kalem kalem sayı olarak veriyor.
 */

import { formatPct, formatTry } from "../api/client";
import type { CarrierEvaluation, DecisionResponse } from "../api/types";
import { CostWaterfall, Legend, StackedBarChart } from "../components/charts";

const COST_SEGMENTS = [
  { key: "freight_try", label: "Nakliye", colorVar: "--cost-1" },
  { key: "damage_try", label: "Hasar", colorVar: "--cost-2" },
  { key: "delay_try", label: "Gecikme", colorVar: "--cost-3" },
  { key: "packaging_try", label: "Ambalaj", colorVar: "--cost-4" },
] as const;

function segmentsOf(evaluation: CarrierEvaluation) {
  return COST_SEGMENTS.map((segment) => ({
    label: segment.label,
    value: evaluation[segment.key] ?? 0,
    colorVar: segment.colorVar,
  }));
}

export function DecisionPage({ decision }: { decision: DecisionResponse }) {
  const { selected } = decision;

  return (
    <div className="stack">
      <div className="card">
        <div className="card-header">
          <h2>
            {selected.display_name} seçildi
          </h2>
          <div className="row" style={{ gap: 6 }}>
            {decision.overrode_cheapest_freight && (
              <span className="badge badge--good">En ucuz nakliye reddedildi</span>
            )}
            {selected.is_low_confidence && (
              <span className="badge badge--critical">Veri zayıf</span>
            )}
          </div>
        </div>

        <div className="stat-row" style={{ marginTop: 12 }}>
          <div className="stat">
            <div className="stat-label">Beklenen toplam maliyet</div>
            <div className="hero-value" style={{ fontSize: 34 }}>
              {formatTry(selected.expected_total_try)} TL
            </div>
            <div className="stat-note">
              {formatTry(selected.freight_try)} TL nakliye +{" "}
              {formatTry(selected.hidden_cost_try)} TL faturada görünmeyen
            </div>
          </div>
          <div className="stat">
            <div className="stat-label">Bu karar kazandırdı</div>
            <div
              className="stat-value"
              style={{ color: decision.savings_vs_cheapest_freight_try > 0 ? "var(--good)" : undefined }}
            >
              {formatTry(decision.savings_vs_cheapest_freight_try)} TL
            </div>
            <div className="stat-note">
              en ucuz nakliye seçilseydi ödenecek fazla
            </div>
          </div>
          <div className="stat">
            <div className="stat-label">İkinciye marj</div>
            <div className="stat-value">{formatTry(decision.margin_try)} TL</div>
            <div className="stat-note">
              {formatPct(decision.margin_pct)} · dar marj = parametrelere duyarlı karar
            </div>
          </div>
          <div className="stat">
            <div className="stat-label">Koli planı</div>
            <div className="stat-value">{selected.parcel_count} koli</div>
            <div className="stat-note">
              {selected.box_codes.join(" + ")} · {selected.chargeable_desi.toFixed(0)} ücretli desi
            </div>
          </div>
        </div>
      </div>

      <div className="card">
        <h2>Gerekçe</h2>
        <p className="card-note">
          Motor asla çıplak bir firma adı döndürmez; gerekçe gösteremeyen bir karar
          ilk itirazda devre dışı bırakılır.
        </p>
        <ul style={{ paddingLeft: 18, margin: 0, color: "var(--text-secondary)", fontSize: 14 }}>
          {decision.rationale.map((line, index) => (
            <li key={index} style={{ marginBottom: 7 }}>
              {line}
            </li>
          ))}
        </ul>

        {decision.warnings.length > 0 && (
          <div className="stack" style={{ gap: 8, marginTop: 14 }}>
            {decision.warnings.map((warning, index) => (
              <div key={index} className="callout callout--warning">
                {warning}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card">
        <h2>Adayların maliyet karşılaştırması</h2>
        <p className="card-note">
          Mevcut sistemin gördüğü tek kalem <strong>nakliye</strong>. Sıralama,
          yalnızca nakliyeye bakıldığında çoğu zaman tersine döner.
        </p>
        <Legend items={COST_SEGMENTS.map((s) => ({ label: s.label, colorVar: s.colorVar }))} />
        <StackedBarChart
          idPrefix="decision"
          rows={decision.ranked.map((evaluation) => ({
            name: evaluation.display_name,
            segments: segmentsOf(evaluation),
            emphasis: evaluation.carrier === selected.carrier,
          }))}
          format={(value) => `${value.toFixed(0)} TL`}
        />

        <div className="table-wrap" style={{ marginTop: 12 }}>
          <table>
            <caption>
              Tüm adaylar ve elenen firmalar · seçilen satır vurgulu
            </caption>
            <thead>
              <tr>
                <th>Firma</th>
                <th>Koli</th>
                <th>Desi</th>
                <th>Nakliye</th>
                <th>Hasar</th>
                <th>Gecikme</th>
                <th>Ambalaj</th>
                <th>TOPLAM</th>
                <th>P(hasar)</th>
                <th>P(gecikme)</th>
                <th>Ort. gün</th>
              </tr>
            </thead>
            <tbody>
              {decision.ranked.map((evaluation) => (
                <tr
                  key={evaluation.carrier}
                  className={evaluation.carrier === selected.carrier ? "is-selected" : undefined}
                >
                  <td>
                    {evaluation.display_name}
                    {evaluation.carrier === decision.cheapest_freight_carrier && (
                      <span className="badge badge--neutral" style={{ marginLeft: 6 }}>
                        en ucuz nakliye
                      </span>
                    )}
                  </td>
                  <td className="num">{evaluation.parcel_count}</td>
                  <td className="num">{evaluation.chargeable_desi.toFixed(0)}</td>
                  <td className="num">{formatTry(evaluation.freight_try)}</td>
                  <td className="num">{formatTry(evaluation.damage_try)}</td>
                  <td className="num">{formatTry(evaluation.delay_try)}</td>
                  <td className="num">{formatTry(evaluation.packaging_try)}</td>
                  <td className="num" style={{ fontWeight: 700 }}>
                    {formatTry(evaluation.expected_total_try)}
                  </td>
                  <td className="num">
                    {formatPct(evaluation.damage_probability, 2)}
                    {evaluation.is_low_confidence && (
                      <span title="Bu hücrede geçmiş veri zayıf; tahmin geniş bir belirsizlik taşıyor">
                        {" "}
                        ⚠
                      </span>
                    )}
                  </td>
                  <td className="num">
                    {evaluation.delay ? formatPct(evaluation.delay.probability_late, 0) : "—"}
                  </td>
                  <td className="num">
                    {evaluation.delay ? evaluation.delay.expected_days.toFixed(1) : "—"}
                  </td>
                </tr>
              ))}
              {decision.rejected.map((evaluation) => (
                <tr key={evaluation.carrier} className="is-rejected">
                  <td>{evaluation.display_name}</td>
                  <td colSpan={10} style={{ textAlign: "left" }}>
                    Elendi: {evaluation.ineligibility_reasons.join(", ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h2>Seçilen firmanın maliyet dökümü</h2>
        <p className="card-note">
          Hasar kalemi, kolideki ürünlerin değeri × hasar olasılığı; sıvı ile emici
          ürün aynı kolideyse yan hasar da eklenir. Gecikme kalemi çağrı merkezi,
          iade riski, telafi ve müşteri kaybını içerir.
        </p>
        <CostWaterfall
          lines={selected.cost_lines}
          total={selected.expected_total_try ?? 0}
        />

        {selected.damage_loss_try > 0 && (
          <p className="card-note" style={{ marginTop: 14, marginBottom: 0 }}>
            En riskli kolide hasar gerçekleşirse zarar{" "}
            <strong>{formatTry(selected.damage_loss_try)} TL</strong>; bu olayın
            olasılığı {formatPct(selected.damage_probability, 2)}
            {selected.damage_probability_raw != null && (
              <> (ham geçmiş oran {formatPct(selected.damage_probability_raw, 2)},
                tahminin %{(selected.damage_prior_weight * 100).toFixed(0)}'i önselden)</>
            )}
            .
          </p>
        )}
      </div>
    </div>
  );
}
