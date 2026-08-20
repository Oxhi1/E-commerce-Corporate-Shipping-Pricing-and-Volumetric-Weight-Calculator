/**
 * Uygulama kabuğu.
 *
 * Sekmeler arasında **tek bir sipariş** paylaşılır: sepeti kurup "şimdi karara
 * bakalım" demek sunumun akışını taşıyor. Sipariş her değiştiğinde ilgili sekme
 * verisini yeniden çeker; istekler yarışırsa son gelen değil **son gönderilen**
 * kazanır (bkz. `requestId`), aksi halde hızlı tıklamalarda eski cevap ekranda kalır.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "./api/client";
import type {
  Carrier,
  City,
  DecisionResponse,
  LabelResponse,
  PackResponse,
  Product,
} from "./api/types";
import { OrderBuilder, PRESETS, toOrderIn, type OrderState } from "./components/OrderBuilder";
import { DecisionPage } from "./pages/DecisionPage";
import { LabelPage } from "./pages/LabelPage";
import { PackingPage } from "./pages/PackingPage";
import { RiskPage } from "./pages/RiskPage";
import { SimulationPage } from "./pages/SimulationPage";
import type { RiskHeatmap } from "./api/types";

type TabId = "packing" | "decision" | "label" | "risk" | "simulation" | "carriers";

const TABS: { id: TabId; label: string }[] = [
  { id: "packing", label: "Sanal kutulama" },
  { id: "decision", label: "Karar ve gerekçe" },
  { id: "label", label: "Etiket" },
  { id: "risk", label: "Risk haritası" },
  { id: "simulation", label: "Simülasyon" },
  { id: "carriers", label: "Firmalar ve tarifeler" },
];

const DEFAULT_ORDER: OrderState =
  PRESETS[1]?.state ?? {
    lines: [{ sku: "HV-003", quantity: 2 }],
    cityPlate: 34,
    isCod: false,
    isRural: false,
    clv: 0,
  };

export default function App() {
  const [tab, setTab] = useState<TabId>("packing");
  const [order, setOrder] = useState<OrderState>(DEFAULT_ORDER);

  const [products, setProducts] = useState<Product[]>([]);
  const [cities, setCities] = useState<City[]>([]);
  const [carriers, setCarriers] = useState<Carrier[]>([]);
  const [bootError, setBootError] = useState<string | null>(null);

  const [pack, setPack] = useState<PackResponse | null>(null);
  const [decision, setDecision] = useState<DecisionResponse | null>(null);
  const [label, setLabel] = useState<LabelResponse | null>(null);
  const [risk, setRisk] = useState<RiskHeatmap | null>(null);
  const [orderError, setOrderError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const requestId = useRef(0);

  useEffect(() => {
    Promise.all([api.products(), api.cities(), api.carriers()])
      .then(([loadedProducts, loadedCities, loadedCarriers]) => {
        setProducts(loadedProducts);
        setCities(loadedCities);
        setCarriers(loadedCarriers);
      })
      .catch((error: unknown) =>
        setBootError(
          error instanceof Error
            ? `Backend'e ulaşılamadı: ${error.message}. ` +
              "\`uvicorn desi_engine.api.main:app --reload\` çalışıyor mu?"
            : String(error),
        ),
      );
  }, []);

  const refresh = useCallback(async () => {
    if (order.lines.length === 0) {
      setPack(null);
      setDecision(null);
      setLabel(null);
      setOrderError(null);
      return;
    }

    const current = ++requestId.current;
    setLoading(true);
    setOrderError(null);
    const payload = toOrderIn(order);

    try {
      const [packResult, decisionResult, labelResult] = await Promise.all([
        api.pack(payload),
        api.decide(payload),
        api.label(payload),
      ]);
      if (current !== requestId.current) return; // daha yeni bir istek var
      setPack(packResult);
      setDecision(decisionResult);
      setLabel(labelResult);
    } catch (error) {
      if (current !== requestId.current) return;
      setOrderError(
        error instanceof ApiError
          ? `${error.status}: ${error.message}`
          : error instanceof Error
            ? error.message
            : String(error),
      );
      setPack(null);
      setDecision(null);
      setLabel(null);
    } finally {
      if (current === requestId.current) setLoading(false);
    }
  }, [order]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (tab === "risk" && risk === null) {
      api.riskHeatmap().then(setRisk).catch(() => setRisk(null));
    }
  }, [tab, risk]);

  if (bootError) {
    return (
      <div className="app-main">
        <div className="error-box">{bootError}</div>
      </div>
    );
  }

  const needsOrder = tab === "packing" || tab === "decision" || tab === "label";

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-title-row">
          <h1>Özdilek · Desi ve Kargo Karar Motoru</h1>
          <span className="subtitle">
            Çok firmalı fiyatlama · sanal kutulama · Bayesçi risk · Monte Carlo
          </span>
          <span className="badge badge--synthetic">ÖRNEK TARİFE</span>
        </div>
        <nav className="tabs" role="tablist">
          {TABS.map((item) => (
            <button
              key={item.id}
              role="tab"
              aria-selected={tab === item.id}
              className="tab"
              onClick={() => setTab(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>
      </header>

      <main className="app-main">
        <div className="callout callout--warning" style={{ marginBottom: 18 }}>
          Bu kurulum <strong>sentetik tarife</strong> ve <strong>sentetik geçmiş
          sevkiyat verisi</strong> kullanır. Büyüklük mertebeleri gerçekçidir ama
          rakamlar gerçek Özdilek sözleşme fiyatları değildir.
        </div>

        {tab === "simulation" ? (
          <SimulationPage />
        ) : tab === "risk" ? (
          risk ? (
            <RiskPage data={risk} />
          ) : (
            <div className="card empty-state">
              <span className="spinner" /> Risk modeli yükleniyor…
            </div>
          )
        ) : tab === "carriers" ? (
          <CarriersPage carriers={carriers} cities={cities} />
        ) : (
          <div className="layout-split">
            <OrderBuilder
              state={order}
              onChange={setOrder}
              products={products}
              cities={cities}
            />

            <div className="stack">
              {orderError && <div className="error-box">{orderError}</div>}
              {loading && !orderError && (
                <div className="card empty-state">
                  <span className="spinner" /> Hesaplanıyor…
                </div>
              )}
              {!loading && !orderError && needsOrder && order.lines.length === 0 && (
                <div className="card empty-state">
                  Başlamak için soldan bir ürün ekleyin veya hazır senaryo seçin.
                </div>
              )}
              {!loading && !orderError && tab === "packing" && pack && <PackingPage data={pack} />}
              {!loading && !orderError && tab === "decision" && decision && (
                <DecisionPage decision={decision} />
              )}
              {!loading && !orderError && tab === "label" && label && <LabelPage data={label} />}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

function CarriersPage({ carriers, cities }: { carriers: Carrier[]; cities: City[] }) {
  const cityName = (plate: number) =>
    cities.find((city) => city.plate === plate)?.name ?? String(plate);

  return (
    <div className="stack">
      <div className="card">
        <h2>Çalışılan kargo firmaları</h2>
        <p className="card-note">
          Firmalar bilinçli olarak farklı takas noktalarına yerleştirildi: en ucuz
          olan en yavaş, en hızlı olan en pahalı. Hiçbiri her yerde iyi ya da her
          yerde kötü değil — bu yüzden doğru cevap bölgeye ve ürüne göre değişiyor.
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Firma</th>
                <th>Asgari ücret</th>
                <th>Azami desi/parça</th>
                <th>SLA · şehir içi</th>
                <th>SLA · bölge içi</th>
                <th>SLA · bölgeler arası</th>
                <th>SLA · uzak</th>
                <th>Hizmet vermediği iller</th>
                <th>Tarife kaynağı</th>
              </tr>
            </thead>
            <tbody>
              {carriers.map((carrier) => (
                <tr key={carrier.code}>
                  <td>{carrier.display_name}</td>
                  <td className="num">{carrier.min_charge_try.toFixed(2)} TL</td>
                  <td className="num">{carrier.max_desi_per_parcel}</td>
                  <td className="num">{carrier.sla_days["sehir_ici"]} gün</td>
                  <td className="num">{carrier.sla_days["bolge_ici"]} gün</td>
                  <td className="num">{carrier.sla_days["bolgeler_arasi"]} gün</td>
                  <td className="num">{carrier.sla_days["uzak"]} gün</td>
                  <td style={{ textAlign: "left", whiteSpace: "normal" }}>
                    {carrier.unserved_plates.length === 0
                      ? "—"
                      : carrier.unserved_plates.map(cityName).join(", ")}
                  </td>
                  <td>
                    <span
                      className={`badge ${carrier.is_synthetic_tariff ? "badge--synthetic" : "badge--good"}`}
                    >
                      {carrier.is_synthetic_tariff ? "ÖRNEK" : "SÖZLEŞME"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h2>Firma notları</h2>
        <div className="stack" style={{ gap: 10 }}>
          {carriers.map((carrier) => (
            <div key={carrier.code} style={{ fontSize: 13.5 }}>
              <strong>{carrier.display_name}</strong>{" "}
              <span style={{ color: "var(--text-secondary)" }}>{carrier.note}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
