/**
 * Sipariş kurucu — tüm sekmelerin paylaştığı sol panel.
 *
 * Sepet, varış ili ve müşteri değeri tek yerde tutulur; sekme değiştirmek
 * sepeti sıfırlamaz. Demo sırasında "aynı sepetle şimdi karara bakalım"
 * geçişinin akıcı olması için önemli.
 */

import { useMemo, useState } from "react";

import { formatTry } from "../api/client";
import type { City, OrderIn, Product } from "../api/types";

export interface OrderState {
  lines: { sku: string; quantity: number }[];
  cityPlate: number;
  isCod: boolean;
  isRural: boolean;
  clv: number;
}

/** Hazır senaryolar — sunumda tek tıkla anlamlı bir sepete geçmek için. */
export const PRESETS: { name: string; note: string; state: OrderState }[] = [
  {
    name: "Banyo seti",
    note: "Tamamı tekstil · konsolidasyonun en çok kazandırdığı sepet",
    state: {
      lines: [
        { sku: "HV-003", quantity: 4 },
        { sku: "BR-001", quantity: 1 },
      ],
      cityPlate: 34,
      isCod: false,
      isRural: false,
      clv: 1800,
    },
  },
  {
    name: "Zeytinyağı + nevresim → Van",
    note: "Sıvı ile emici ürün bir arada · motorun en ucuz nakliyeyi reddettiği senaryo",
    state: {
      lines: [
        { sku: "GD-001", quantity: 1 },
        { sku: "NV-002", quantity: 1 },
      ],
      cityPlate: 65,
      isCod: true,
      isRural: false,
      clv: 4500,
    },
  },
  {
    name: "Porselen → Hakkari",
    note: "Kırılabilir + Sürat'ın hizmet vermediği il · kısıt eleme örneği",
    state: {
      lines: [
        { sku: "MT-002", quantity: 1 },
        { sku: "MT-001", quantity: 2 },
      ],
      cityPlate: 30,
      isCod: false,
      isRural: false,
      clv: 6200,
    },
  },
  {
    name: "Hacimli tekstil",
    note: "Koli bölme kararının (Pareto cephesi) en belirgin olduğu sepet",
    state: {
      lines: [
        { sku: "HV-003", quantity: 6 },
        { sku: "NV-002", quantity: 2 },
        { sku: "BT-002", quantity: 1 },
      ],
      cityPlate: 25,
      isCod: false,
      isRural: true,
      clv: 2400,
    },
  },
];

export function toOrderIn(state: OrderState): OrderIn {
  return {
    lines: state.lines,
    city_plate: state.cityPlate,
    is_cod: state.isCod,
    is_rural: state.isRural,
    customer_clv_try: state.clv,
    order_id: "UI-001",
  };
}

export function OrderBuilder({
  state,
  onChange,
  products,
  cities,
}: {
  state: OrderState;
  onChange: (next: OrderState) => void;
  products: Product[];
  cities: City[];
}) {
  const [pendingSku, setPendingSku] = useState("");

  const bySku = useMemo(
    () => new Map(products.map((product) => [product.sku, product])),
    [products],
  );

  const cartValue = state.lines.reduce((sum, line) => {
    const product = bySku.get(line.sku);
    return sum + (product ? product.unit_price_try * line.quantity : 0);
  }, 0);

  const cartWeight = state.lines.reduce((sum, line) => {
    const product = bySku.get(line.sku);
    return sum + (product ? product.weight_kg * line.quantity : 0);
  }, 0);

  const hasLiquid = state.lines.some((line) => bySku.get(line.sku)?.is_liquid);
  const hasAbsorbent = state.lines.some((line) => bySku.get(line.sku)?.is_absorbent);

  const addLine = (sku: string) => {
    if (!sku) return;
    const existing = state.lines.find((line) => line.sku === sku);
    onChange({
      ...state,
      lines: existing
        ? state.lines.map((line) =>
            line.sku === sku ? { ...line, quantity: Math.min(99, line.quantity + 1) } : line,
          )
        : [...state.lines, { sku, quantity: 1 }],
    });
    setPendingSku("");
  };

  const setQuantity = (sku: string, delta: number) =>
    onChange({
      ...state,
      lines: state.lines
        .map((line) =>
          line.sku === sku ? { ...line, quantity: line.quantity + delta } : line,
        )
        .filter((line) => line.quantity > 0),
    });

  const removeLine = (sku: string) =>
    onChange({ ...state, lines: state.lines.filter((line) => line.sku !== sku) });

  return (
    <div className="card stack">
      <div>
        <h2>Sipariş</h2>
        <p className="card-note">
          Sepeti, varış ilini ve müşteri değerini burada kurun. Tüm sekmeler aynı
          siparişi kullanır.
        </p>
      </div>

      <div className="field">
        <label htmlFor="preset">Hazır senaryo</label>
        <select
          id="preset"
          value=""
          onChange={(event) => {
            const preset = PRESETS.find((p) => p.name === event.target.value);
            if (preset) onChange(preset.state);
          }}
        >
          <option value="">Seçiniz…</option>
          {PRESETS.map((preset) => (
            <option key={preset.name} value={preset.name}>
              {preset.name}
            </option>
          ))}
        </select>
      </div>

      <div className="field">
        <label htmlFor="product">Ürün ekle</label>
        <select
          id="product"
          value={pendingSku}
          onChange={(event) => addLine(event.target.value)}
        >
          <option value="">Katalogdan seç…</option>
          {products.map((product) => (
            <option key={product.sku} value={product.sku}>
              {product.name} — {formatTry(product.unit_price_try)} TL
            </option>
          ))}
        </select>
      </div>

      <div>
        {state.lines.length === 0 ? (
          <p className="empty-state" style={{ padding: "18px 0" }}>
            Sepet boş.
          </p>
        ) : (
          state.lines.map((line) => {
            const product = bySku.get(line.sku);
            return (
              <div className="cart-line" key={line.sku}>
                <div className="cart-line-name">
                  <div>{product?.name ?? line.sku}</div>
                  <div className="cart-line-meta">
                    {product
                      ? `${product.length_cm}×${product.width_cm}×${product.height_cm} cm · ${product.weight_kg} kg · ${product.desi.toFixed(2)} desi`
                      : line.sku}
                  </div>
                </div>
                <div className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
                  <button
                    className="icon-button"
                    onClick={() => setQuantity(line.sku, -1)}
                    aria-label={`${product?.name ?? line.sku} adedini azalt`}
                  >
                    −
                  </button>
                  <span className="num" style={{ minWidth: 18, textAlign: "center" }}>
                    {line.quantity}
                  </span>
                  <button
                    className="icon-button"
                    onClick={() => setQuantity(line.sku, 1)}
                    aria-label={`${product?.name ?? line.sku} adedini artır`}
                  >
                    +
                  </button>
                </div>
                <button
                  className="icon-button"
                  onClick={() => removeLine(line.sku)}
                  aria-label={`${product?.name ?? line.sku} satırını kaldır`}
                >
                  ×
                </button>
              </div>
            );
          })
        )}
      </div>

      {hasLiquid && hasAbsorbent && (
        <div className="callout callout--warning">
          Sepette hem <strong>sıvı</strong> hem <strong>emici</strong> ürün var.
          Motor, sıvıları ayrı koliye alan bir alternatif plan da üretecek —
          ek nakliye maliyetiyle yan hasar riskini karşılaştıracak.
        </div>
      )}

      <div className="field">
        <label htmlFor="city">Varış ili</label>
        <select
          id="city"
          value={state.cityPlate}
          onChange={(event) => onChange({ ...state, cityPlate: Number(event.target.value) })}
        >
          {cities.map((city) => (
            <option key={city.plate} value={city.plate}>
              {String(city.plate).padStart(2, "0")} {city.name}
              {city.is_remote ? " (uzak)" : ""}
            </option>
          ))}
        </select>
      </div>

      <div className="field">
        <label htmlFor="clv">Müşteri yaşam boyu değeri (TL)</label>
        <input
          id="clv"
          type="number"
          min={0}
          step={100}
          value={state.clv}
          onChange={(event) => onChange({ ...state, clv: Number(event.target.value) })}
        />
      </div>

      <div className="row">
        <label className="check">
          <input
            type="checkbox"
            checked={state.isCod}
            onChange={(event) => onChange({ ...state, isCod: event.target.checked })}
          />
          Kapıda ödeme
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={state.isRural}
            onChange={(event) => onChange({ ...state, isRural: event.target.checked })}
          />
          Kırsal adres
        </label>
      </div>

      <div className="stat-row">
        <div className="stat">
          <div className="stat-label">Sepet tutarı</div>
          <div className="stat-value" style={{ fontSize: 19 }}>
            {formatTry(cartValue)} TL
          </div>
        </div>
        <div className="stat">
          <div className="stat-label">Ağırlık</div>
          <div className="stat-value" style={{ fontSize: 19 }}>
            {cartWeight.toFixed(2)} kg
          </div>
        </div>
      </div>
    </div>
  );
}
