export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000/api";

export type SalesRecord = {
  item_id: string;
  store_id: string;
  state_id: string;
  category_id: string;
  department_id: string;
  date: string;
  sales: number;
  sell_price?: number | null;
  event_name?: string | null;
  event_type?: string | null;
  snap?: number | null;
};

export type ForecastResponse = {
  request_id: string;
  artifact_mode: string;
  model_name: "A0" | "B1" | "C";
  model_label: string;
  forecast_horizon: number;
  forecast: { date: string; horizon: number; forecast: number }[];
  cluster: {
    cluster_id: number;
    cluster_name: string;
    mean_sales: number;
    zero_sales_ratio: number;
    adi: number;
    cv2: number;
    interpretation: string;
  };
  warnings: string[];
  history: SalesRecord[];
};

export async function getOverview() {
  const res = await fetch(`${API_BASE}/overview`);
  if (!res.ok) throw new Error("Không tải được overview");
  return res.json();
}

export async function getSampleCsv() {
  const res = await fetch(`${API_BASE}/sample-series`);
  if (!res.ok) throw new Error("Không tải được sample CSV");
  return res.text();
}

export async function postForecast(modelName: "A0" | "B1" | "C", records: SalesRecord[]) {
  const res = await fetch(`${API_BASE}/forecast`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model_name: modelName, forecast_horizon: 28, records }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text);
  }
  return (await res.json()) as ForecastResponse;
}

export function parseCsv(text: string): SalesRecord[] {
  const lines = text.trim().split(/\r?\n/);
  const headers = lines[0].split(",").map((h) => h.trim());
  return lines.slice(1).filter(Boolean).map((line) => {
    const values = line.split(",");
    const row = Object.fromEntries(headers.map((h, idx) => [h, values[idx]?.trim() ?? ""]));
    return {
      item_id: row.item_id,
      store_id: row.store_id,
      state_id: row.state_id,
      category_id: row.category_id,
      department_id: row.department_id,
      date: row.date,
      sales: Number(row.sales || 0),
      sell_price: row.sell_price ? Number(row.sell_price) : null,
      event_name: row.event_name || null,
      event_type: row.event_type || null,
      snap: row.snap ? Number(row.snap) : 0,
    };
  });
}

