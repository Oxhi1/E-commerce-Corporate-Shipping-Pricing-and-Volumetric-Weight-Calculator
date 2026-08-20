/**
 * Monte Carlo simülasyon paneli.
 *
 * Yönetime gösterilecek sayı burada üretiliyor. Sunumun dürüstlük noktası:
 * tasarruf **her zaman güven aralığıyla** birlikte veriliyor ve aralık sıfırı
 * kapsıyorsa "anlamsız" olarak işaretleniyor. Yuvarlanmış tek bir yüzde,
 * gürültüyü kazanç gibi gösterebilirdi.
 */

import { useEffect, useRef, useState } from "react";

import { api, formatPct, formatTry, isSimulationResult } from "../api/client";
import type { SimulationResult } from "../api/types";
import { IntervalChart, Legend, StackedBarChart } from "../components/charts";

const CARRIER_COLORS = [
  "--carrier-1",
  "--carrier-2",
  "--carrier-3",
  "--carrier-4",
  "--carrier-5",
];
const CARRIER_ORDER = ["ARAS", "MNG", "YURTICI", "SURAT", "PTT"];

const COST_SEGMENTS = [
  { label: "Nakliye", colorVar: "--cost-1" },
  { label: "Diğer (gizli maliyet)", colorVar: "--cost-2" },
];

export function SimulationPage() {
  const [orders, setOrders] = useState(3000);
  const [seed, setSeed] = useState(42);
  const [lambda, setLambda] = useState(0);

  const [state, setState] = useState<"idle" | "running" | "done" | "failed">("idle");
  const [message, setMessage] = useState("");
  const [result, setResult] = useState<SimulationResult | null>(null);
  const pollRef = useRef<number | null>(null);

  // Bileşen kaldırıldığında yoklamayı durdur; aksi halde arka planda çalışmaya
  // devam eder ve sekme değiştirildiğinde gereksiz istek üretir.
  useEffect(() => () => {
    if (pollRef.current) window.clearInterval(pollRef.current);
  }, []);

  const start = async () => {
    setState("running");
    setMessage("Simülasyon başlatılıyor…");
    setResult(null);
    try {
      const started = await api.startSimulation({
        n_orders: orders,
        seed,
        risk_aversion_lambda: lambda,
      });
      if (pollRef.current) window.clearInterval(pollRef.current);
      pollRef.current = window.setInterval(async () => {
        try {
          const status = await api.simulationStatus(started.run_id);
          if (isSimulationResult(status)) {
            if (pollRef.current) window.clearInterval(pollRef.current);
            setResult(status);
            setState("done");
            setMessage("");
          } else if (status.state === "failed") {
            if (pollRef.current) window.clearInterval(pollRef.current);
            setState("failed");
            setMessage(status.message);
          } else {
            setMessage(status.message || "Çalışıyor…");
          }
        } catch (error) {
          if (pollRef.current) window.clearInterval(pollRef.current);
          setState("failed");
          setMessage(error instanceof Error ? error.message : String(error));
        }
      }, 1500);
    } catch (error) {
      setState("failed");
      setMessage(error instanceof Error ? error.message : String(error));
    }
  };

  return (
    <div className="stack">
      <div className="card">
        <h2>Monte Carlo politika karşılaştırması</h2>
        <p className="card-note">
          Beş politika <strong>birebir aynı sipariş akışında ve aynı şans
          çekilişleriyle</strong> yarıştırılır (ortak rastgele sayılar). Motor
          gerçek hasar olasılıklarını görmez; yalnızca geçmiş veriden kestirir ve
          gerçek hayattaki gibi yanılabilir.
        </p>

        <div className="row" style={{ alignItems: "flex-end" }}>
          <div className="field">
            <label htmlFor="orders">Sipariş sayısı</label>
            <input
              id="orders"
              type="number"
              min={100}
              max={50000}
              step={500}
              value={orders}
              onChange={(event) => setOrders(Number(event.target.value))}
            />
          </div>
          <div className="field">
            <label htmlFor="seed">Tohum</label>
            <input
              id="seed"
              type="number"
              value={seed}
              onChange={(event) => setSeed(Number(event.target.value))}
            />
          </div>
          <div className="field">
            <label htmlFor="lambda">Riskten kaçınma λ</label>
            <input
              id="lambda"
              type="number"
              min={0}
              max={5}
              step={0.5}
              value={lambda}
              onChange={(event) => setLambda(Number(event.target.value))}
            />
          </div>
          <button className="button button--primary" onClick={start} disabled={state === "running"}>
            {state === "running" ? "Çalışıyor…" : "Simülasyonu çalıştır"}
          </button>
        </div>

        <p className="card-note" style={{ marginTop: 10, marginBottom: 0 }}>
          Yaklaşık 12 ms/sipariş — 3.000 sipariş ~35 saniye sürer. Aynı tohum her
          zaman aynı sonucu verir.
        </p>

        {state === "running" && (
          <div className="row" style={{ marginTop: 12 }}>
            <span className="spinner" /> <span style={{ fontSize: 13.5 }}>{message}</span>
          </div>
        )}
        {state === "failed" && (
          <div className="error-box" style={{ marginTop: 12 }}>
            {message}
          </div>
        )}
      </div>

      {result && <SimulationResultView result={result} />}
    </div>
  );
}

function SimulationResultView({ result }: { result: SimulationResult }) {
  const best = result.comparisons.reduce<(typeof result.comparisons)[number] | null>(
    (winner, candidate) =>
      winner == null || candidate.mean_difference > winner.mean_difference ? candidate : winner,
    null,
  );

  return (
    <>
      <div className="card">
        <div className="stat-label">Sipariş başına en yüksek tasarruf</div>
        <div className="hero-value" style={{ color: best?.is_significant ? "var(--good)" : undefined }}>
          {best ? `${best.mean_difference > 0 ? "+" : ""}${formatTry(best.mean_difference)} TL` : "—"}
        </div>
        <p className="card-note" style={{ marginTop: 8, marginBottom: 0 }}>
          {result.headline}
        </p>
        <p className="card-note" style={{ marginBottom: 0 }}>
          {result.n_orders.toLocaleString("tr-TR")} sipariş · tohum {result.seed} ·{" "}
          {result.elapsed_seconds.toFixed(1)} sn · kalibrasyon hatası (ECE){" "}
          {result.calibration_error.toFixed(4)}
        </p>
      </div>

      <div className="card">
        <h2>Tasarruf ve belirsizliği</h2>
        <p className="card-note">
          Nokta ortalama farkı, çubuk %95 güven aralığı (eşleştirilmiş bootstrap).
          Aralığı sıfırı kapsayan karşılaştırmalar nötr renkte ve "anlamsız" etiketli.
        </p>
        <IntervalChart
          rows={result.comparisons.map((comparison) => ({
            name: `${comparison.treatment.split(" ")[0]} vs ${comparison.baseline.split(" ")[0]}`,
            mean: comparison.mean_difference,
            low: comparison.ci_low,
            high: comparison.ci_high,
          }))}
        />
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Karşılaştırma</th>
                <th>Ortalama fark</th>
                <th>%95 alt</th>
                <th>%95 üst</th>
                <th>Göreli</th>
                <th>Sonuç</th>
              </tr>
            </thead>
            <tbody>
              {result.comparisons.map((comparison) => (
                <tr key={`${comparison.baseline}-${comparison.treatment}`}>
                  <td>
                    {comparison.treatment.split(" ")[0]} vs {comparison.baseline.split(" ")[0]}
                  </td>
                  <td className="num">{formatTry(comparison.mean_difference)} TL</td>
                  <td className="num">{formatTry(comparison.ci_low)}</td>
                  <td className="num">{formatTry(comparison.ci_high)}</td>
                  <td className="num">{formatPct(comparison.relative_saving, 2)}</td>
                  <td>
                    <span
                      className={`badge ${comparison.is_significant ? "badge--good" : "badge--neutral"}`}
                    >
                      {comparison.is_significant ? "anlamlı" : "ANLAMSIZ"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h2>Politika karşılaştırması</h2>
        <p className="card-note">
          Dikkat: <strong>P1 (en ucuz nakliye)</strong> faturayı düşürüyor ama toplam
          maliyeti yükseltiyor — hasar ve gecikme kalemleri nakliye tasarrufunu
          fazlasıyla geri alıyor.
        </p>
        <Legend items={COST_SEGMENTS} />
        <StackedBarChart
          idPrefix="policy"
          rows={result.summaries.map((summary) => ({
            name: `${summary.policy} ${summary.label}`,
            emphasis: summary.policy === "P3",
            segments: [
              {
                label: "Nakliye",
                value: summary.freight_per_order_try,
                colorVar: "--cost-1",
              },
              {
                label: "Diğer (gizli maliyet)",
                value: summary.cost_per_order_try - summary.freight_per_order_try,
                colorVar: "--cost-2",
              },
            ],
          }))}
          format={(value) => `${value.toFixed(0)} TL`}
        />

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Politika</th>
                <th>TL/sipariş</th>
                <th>Nakliye</th>
                <th>Gizli pay</th>
                <th>Hasar</th>
                <th>Gecikme</th>
                <th>Ort. gün</th>
                <th>Ort. koli</th>
                <th>Ort. desi</th>
              </tr>
            </thead>
            <tbody>
              {result.summaries.map((summary) => (
                <tr key={summary.policy} className={summary.policy === "P3" ? "is-selected" : undefined}>
                  <td>
                    {summary.policy} {summary.label}
                  </td>
                  <td className="num" style={{ fontWeight: 700 }}>
                    {formatTry(summary.cost_per_order_try)}
                  </td>
                  <td className="num">{formatTry(summary.freight_per_order_try)}</td>
                  <td className="num">{formatPct(summary.hidden_cost_share)}</td>
                  <td className="num">{formatPct(summary.damage_rate, 2)}</td>
                  <td className="num">{formatPct(summary.late_rate)}</td>
                  <td className="num">{summary.mean_delivery_days.toFixed(2)}</td>
                  <td className="num">{summary.mean_parcels.toFixed(2)}</td>
                  <td className="num">{summary.mean_chargeable_desi.toFixed(1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h2>Firma dağılımı</h2>
        <p className="card-note">
          Motor tek bir firmaya kilitlenmiyor. P4'ün dağılımı P3'ten daha dengeli,
          çünkü günlük kapasite limitlerini dikkate alıyor.
        </p>
        <Legend
          items={CARRIER_ORDER.map((code, index) => ({
            label: code,
            colorVar: CARRIER_COLORS[index] ?? "--muted-mark",
          }))}
        />
        <StackedBarChart
          idPrefix="mix"
          rows={result.summaries.map((summary) => ({
            name: `${summary.policy} ${summary.label}`,
            segments: CARRIER_ORDER.map((code, index) => ({
              label: code,
              value: summary.carrier_mix[code] ?? 0,
              colorVar: CARRIER_COLORS[index] ?? "--muted-mark",
            })),
          }))}
          format={(value) => value.toLocaleString("tr-TR")}
        />
      </div>

      <div className="card">
        <h2>Model kalibrasyonu</h2>
        <p className="card-note">
          Motorun "%2 hasar olasılığı" dediği gönderilerin gerçekten yaklaşık %2'si
          hasar görmeli. Doğru firmayı seçen ama kalibre olmayan bir model,
          maliyetleri yanlış büyüklükte tahmin eder ve tasarruf raporunu güvenilmez
          kılar. ECE: <strong>{result.calibration_error.toFixed(4)}</strong>
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Tahmin aralığı</th>
                <th>Gönderi</th>
                <th>Ort. tahmin</th>
                <th>Gerçekleşen</th>
                <th>Sapma</th>
              </tr>
            </thead>
            <tbody>
              {result.calibration.map((bin, index) => (
                <tr key={index}>
                  <td>
                    {formatPct(bin.lower, 2)} – {formatPct(bin.upper, 2)}
                  </td>
                  <td className="num">{bin.count.toLocaleString("tr-TR")}</td>
                  <td className="num">{formatPct(bin.predicted_mean, 3)}</td>
                  <td className="num">{formatPct(bin.observed_rate, 3)}</td>
                  <td className="num">
                    {formatPct(Math.abs(bin.predicted_mean - bin.observed_rate), 3)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
