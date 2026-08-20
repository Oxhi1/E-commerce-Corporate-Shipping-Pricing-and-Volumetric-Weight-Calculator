/**
 * Backend istemcisi.
 *
 * Hata yonetimi bilincli olarak sade ama **sessiz degil**: bir istek basarisiz
 * olursa gerekce metniyle birlikte firlatilir ve arayuzde gosterilir. Bos bir
 * tabloyla "sanki veri yokmus gibi" davranmak, demo sirasinda hatayi gizler.
 */

import type {
  Carrier,
  City,
  DecisionResponse,
  LabelResponse,
  OrderIn,
  PackResponse,
  Product,
  RiskHeatmap,
  SimulationResult,
  SimulationStatus,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
      else if (body.detail) detail = JSON.stringify(body.detail);
    } catch {
      // Cevap JSON degilse durum metniyle yetin.
    }
    throw new ApiError(detail, response.status);
  }
  return (await response.json()) as T;
}

const post = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  products: () => request<Product[]>("/catalog/products"),
  cities: () => request<City[]>("/catalog/cities"),
  carriers: () => request<Carrier[]>("/carriers"),

  pack: (order: OrderIn) => post<PackResponse>("/pack", order),
  decide: (order: OrderIn) => post<DecisionResponse>("/decide", order),
  label: (order: OrderIn) => post<LabelResponse>("/label", order),

  riskHeatmap: () => request<RiskHeatmap>("/risk/heatmap"),

  startSimulation: (body: {
    n_orders: number;
    seed: number;
    risk_aversion_lambda?: number;
  }) => post<SimulationStatus>("/simulate", body),

  simulationStatus: (runId: string) =>
    request<SimulationResult | SimulationStatus>(`/simulate/${runId}`),
};

/** Cevabin tamamlanmis bir kosu mu yoksa durum bildirimi mi oldugunu ayirir. */
export function isSimulationResult(
  value: SimulationResult | SimulationStatus,
): value is SimulationResult {
  return "summaries" in value;
}

export const formatTry = (value: number | null | undefined): string =>
  value == null
    ? "—"
    : new Intl.NumberFormat("tr-TR", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }).format(value);

export const formatPct = (value: number, digits = 1): string =>
  `%${(value * 100).toFixed(digits)}`;
