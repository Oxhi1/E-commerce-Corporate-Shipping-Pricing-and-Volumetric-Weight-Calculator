/**
 * Risk ısı haritası sekmesi — Bayesçi modelin ne yaptığını gösteren sayfa.
 *
 * Tasarımın merkezinde **ham oran ile shrinkage'lı tahminin yan yana** durması
 * var. Modelin değeri ancak ikisi karşılaştırılınca görünüyor: 5 gönderide 0
 * hasar gören bir hücrenin ham oranı %0'dır ve karar motorunda o firmayı sonsuz
 * cazip yapardı; model onu üst katmanın ortalamasına çekiyor.
 *
 * Isı haritası ardışık (sequential) tek hue kullanır — büyüklük gösteriyor,
 * kimlik değil. Renk tek başına bilgi taşımasın diye her hücrede sayı yazılı.
 */

import { useMemo, useState } from "react";

import { formatPct } from "../api/client";
import type { RiskCell, RiskHeatmap } from "../api/types";

const ZONES = ["sehir_ici", "bolge_ici", "bolgeler_arasi", "uzak"] as const;
const ZONE_LABEL: Record<string, string> = {
  sehir_ici: "Şehir içi",
  bolge_ici: "Bölge içi",
  bolgeler_arasi: "Bölgeler arası",
  uzak: "Uzak",
};
const CATEGORY_LABEL: Record<string, string> = {
  yumusak: "Tekstil",
  kirilabilir: "Kırılabilir",
  sivi: "Sıvı",
  cihaz: "Cihaz",
};

/**
 * Ardışık ramp: açık → koyu, tek hue. Değer arttıkça koyulaşır.
 * `oklch` ile tanımlı; açık ve koyu temada aynı algısal adımları veriyor.
 */
function heatColor(value: number, maximum: number): string {
  const t = maximum > 0 ? Math.min(1, value / maximum) : 0;
  const lightness = 0.96 - 0.5 * t;
  const chroma = 0.02 + 0.14 * t;
  return `oklch(${lightness.toFixed(3)} ${chroma.toFixed(3)} 28)`;
}

export function RiskPage({ data }: { data: RiskHeatmap }) {
  const [category, setCategory] = useState("kirilabilir");
  const [mode, setMode] = useState<"shrunk" | "raw">("shrunk");

  const carriers = useMemo(
    () => [...new Set(data.cells.map((cell) => cell.carrier))].sort(),
    [data.cells],
  );

  const filtered = data.cells.filter((cell) => cell.risk_category === category);
  const lookup = new Map(filtered.map((cell) => [`${cell.carrier}|${cell.zone}`, cell]));

  const values = filtered
    .map((cell) => (mode === "raw" ? cell.raw_rate : cell.shrunk_rate))
    .filter((value): value is number => value != null);
  const maximum = Math.max(...values, 0.001);

  const cellValue = (cell: RiskCell | undefined): number | null =>
    cell == null ? null : mode === "raw" ? cell.raw_rate : cell.shrunk_rate;

  return (
    <div className="stack">
      <div className="card">
        <h2>Bayesçi hasar modeli</h2>
        <p className="card-note">
          Hasar oranı <strong>(firma × bölge × ürün tipi)</strong> kırılımında 80
          hücrede tahmin ediliyor. En yoğun hücrede binlerce gönderi var, en
          seyrekte bir avuç. Ham oranlar bu yüzden kullanılamaz: 5 gönderide 0 hasar
          "risksiz" demek değil, "hiçbir şey bilmiyoruz" demektir.
        </p>

        <div className="stat-row">
          <div className="stat">
            <div className="stat-label">Genel hasar oranı</div>
            <div className="stat-value" style={{ fontSize: 22 }}>
              {formatPct(data.global_rate, 3)}
            </div>
            <div className="stat-note">{data.total_shipments.toLocaleString("tr-TR")} gönderi</div>
          </div>
          {Object.entries(data.kappas).map(([level, kappa]) => (
            <div className="stat" key={level}>
              <div className="stat-label">κ · {level}</div>
              <div className="stat-value" style={{ fontSize: 22 }}>
                {kappa.toFixed(0)}
              </div>
              <div className="stat-note">önsel, bu kadar gönderiye denk sayılıyor</div>
            </div>
          ))}
        </div>

        <div className="callout" style={{ marginTop: 14 }}>
          <strong>κ nasıl okunur:</strong> bir hücrede κ kadar gönderi varsa tahminin
          yarısı önselden, yarısı veriden gelir. κ elle seçilmiyor — hücreler arası
          gerçek farklılık ne kadarsa marjinal olabilirlik onu buluyor.
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <h2>Isı haritası</h2>
          <div className="row" style={{ gap: 8 }}>
            <select value={category} onChange={(event) => setCategory(event.target.value)}>
              {Object.entries(CATEGORY_LABEL).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
            <div className="row" style={{ gap: 0 }}>
              <button
                className="button"
                aria-pressed={mode === "raw"}
                style={mode === "raw" ? { borderColor: "var(--accent)", color: "var(--accent)" } : undefined}
                onClick={() => setMode("raw")}
              >
                Ham oran
              </button>
              <button
                className="button"
                aria-pressed={mode === "shrunk"}
                style={mode === "shrunk" ? { borderColor: "var(--accent)", color: "var(--accent)" } : undefined}
                onClick={() => setMode("shrunk")}
              >
                Shrinkage'lı
              </button>
            </div>
          </div>
        </div>

        <p className="card-note">
          İki modu karşılaştırın: ham oranda birçok hücre %0 görünür (o hücrede
          henüz hasar görülmemiş), shrinkage'lı tahminde hiçbiri sıfır değildir.
        </p>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Firma</th>
                {ZONES.map((zone) => (
                  <th key={zone} style={{ textAlign: "center" }}>
                    {ZONE_LABEL[zone]}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {carriers.map((carrier) => (
                <tr key={carrier}>
                  <td>{carrier}</td>
                  {ZONES.map((zone) => {
                    const cell = lookup.get(`${carrier}|${zone}`);
                    const value = cellValue(cell);
                    return (
                      <td
                        key={zone}
                        className="num"
                        style={{
                          textAlign: "center",
                          background: value == null ? undefined : heatColor(value, maximum),
                          color: "#0b0b0b",
                          fontWeight: 600,
                        }}
                        title={
                          cell
                            ? `${cell.shipments} gönderi, ${cell.damages} hasar · ` +
                              `%90 aralık [${formatPct(cell.ci_low, 2)}, ${formatPct(cell.ci_high, 2)}] · ` +
                              `tahminin %${(cell.prior_weight * 100).toFixed(0)}'i önselden`
                            : undefined
                        }
                      >
                        {value == null ? "—" : formatPct(value, 2)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h2>Hücre ayrıntıları</h2>
        <p className="card-note">
          "Önsel ağırlığı" yüksek satırlar, motorun az şey bildiği hücreler.
          Karar hâlâ verilir ama gerekçede "veri zayıf" uyarısı çıkar.
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Firma</th>
                <th>Bölge</th>
                <th>Gönderi</th>
                <th>Hasar</th>
                <th>Ham oran</th>
                <th>Shrinkage'lı</th>
                <th>%90 alt</th>
                <th>%90 üst</th>
                <th>Riskten kaçınan (%95 üst)</th>
                <th>Önsel ağırlığı</th>
              </tr>
            </thead>
            <tbody>
              {[...filtered]
                .sort((a, b) => a.prior_weight - b.prior_weight)
                .map((cell) => (
                  <tr key={`${cell.carrier}-${cell.zone}`}>
                    <td>{cell.carrier}</td>
                    <td>{ZONE_LABEL[cell.zone] ?? cell.zone}</td>
                    <td className="num">{cell.shipments.toLocaleString("tr-TR")}</td>
                    <td className="num">{cell.damages}</td>
                    <td className="num">
                      {cell.raw_rate == null ? "—" : formatPct(cell.raw_rate, 2)}
                    </td>
                    <td className="num" style={{ fontWeight: 600 }}>
                      {formatPct(cell.shrunk_rate, 2)}
                    </td>
                    <td className="num">{formatPct(cell.ci_low, 2)}</td>
                    <td className="num">{formatPct(cell.ci_high, 2)}</td>
                    <td className="num">{formatPct(cell.upper_95, 2)}</td>
                    <td className="num">
                      {cell.prior_weight > 0.5 ? (
                        <span className="badge badge--critical">
                          %{(cell.prior_weight * 100).toFixed(0)}
                        </span>
                      ) : (
                        `%${(cell.prior_weight * 100).toFixed(0)}`
                      )}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
