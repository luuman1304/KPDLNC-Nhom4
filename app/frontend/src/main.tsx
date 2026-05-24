import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { AlertTriangle, BarChart3, Download, Play, Upload } from "lucide-react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ForecastResponse, SalesRecord, getOverview, getSampleCsv, parseCsv, postForecast } from "./lib/api";
import "./styles.css";

type ModelName = "A0" | "B1" | "C";

function App() {
  const [overview, setOverview] = useState<any>(null);
  const [records, setRecords] = useState<SalesRecord[]>([]);
  const [model, setModel] = useState<ModelName>("C");
  const [result, setResult] = useState<ForecastResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    getOverview().then(setOverview).catch((err) => setError(String(err)));
    getSampleCsv().then((csv) => setRecords(parseCsv(csv))).catch(() => undefined);
  }, []);

  const chartData = useMemo(() => {
    const history = records.map((r) => ({ date: r.date, actual: r.sales, forecast: null }));
    const forecast = result?.forecast.map((p) => ({ date: p.date, actual: null, forecast: p.forecast })) ?? [];
    return [...history, ...forecast];
  }, [records, result]);

  async function runForecast() {
    setLoading(true);
    setError("");
    try {
      const response = await postForecast(model, records);
      setResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  function onFileChange(file: File | null) {
    if (!file) return;
    file.text().then((text) => {
      setRecords(parseCsv(text));
      setResult(null);
    });
  }

  function exportForecast() {
    if (!result) return;
    const rows = ["date,horizon,forecast,model,cluster_id"];
    for (const p of result.forecast) {
      rows.push(`${p.date},${p.horizon},${p.forecast},${result.model_name},${result.cluster.cluster_id}`);
    }
    const blob = new Blob([rows.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "forecast.csv";
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <main>
      <header className="topbar">
        <div>
          <p className="eyebrow">Cluster-aware demand forecasting</p>
          <h1>Hệ thống dự báo nhu cầu bán lẻ</h1>
        </div>
        <div className={`mode ${overview?.artifact_mode === "production" ? "production" : "demo"}`}>
          {overview?.artifact_mode ?? "loading"}
        </div>
      </header>

      <section className="metrics">
        <Metric title="Horizon" value="28 ngày" />
        <Metric title="Mô hình mặc định" value="C" />
        <Metric title="Số cụm" value="K=3" />
        <Metric title="Dữ liệu hiện tại" value={`${records.length} ngày`} />
      </section>

      {overview?.warnings?.length ? (
        <div className="notice">
          <AlertTriangle size={18} />
          <span>{overview.warnings[0]}</span>
        </div>
      ) : null}

      <section className="workspace">
        <aside className="panel input-panel">
          <div className="panel-title">
            <Upload size={18} />
            <h2>Nhập dữ liệu</h2>
          </div>
          <p className="muted">Upload CSV theo template hoặc dùng sample có sẵn.</p>
          <label className="file-button">
            Upload CSV
            <input type="file" accept=".csv" onChange={(e) => onFileChange(e.target.files?.[0] ?? null)} />
          </label>
          <a className="secondary" href="http://127.0.0.1:8000/api/input-template">
            <Download size={16} />
            Tải template
          </a>

          <div className="model-select">
            <label>Mô hình</label>
            <select value={model} onChange={(e) => setModel(e.target.value as ModelName)}>
              <option value="A0">A0 - Global LightGBM</option>
              <option value="B1">B1 - Global + cluster label</option>
              <option value="C">C - Cluster-specific LightGBM</option>
            </select>
          </div>
          <button className="primary" onClick={runForecast} disabled={loading || records.length === 0}>
            <Play size={16} />
            {loading ? "Đang dự báo..." : "Chạy dự báo"}
          </button>
          {error ? <pre className="error">{error}</pre> : null}
        </aside>

        <section className="panel chart-panel">
          <div className="panel-title">
            <BarChart3 size={18} />
            <h2>Doanh số lịch sử và dự báo</h2>
          </div>
          <ResponsiveContainer width="100%" height={360}>
            <LineChart data={chartData} margin={{ top: 16, right: 20, left: 0, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} />
              <YAxis />
              <Tooltip />
              <Line type="monotone" dataKey="actual" stroke="#2563eb" dot={false} strokeWidth={2} connectNulls={false} />
              <Line type="monotone" dataKey="forecast" stroke="#dc2626" dot={false} strokeWidth={2} connectNulls={false} />
            </LineChart>
          </ResponsiveContainer>
        </section>
      </section>

      {result ? (
        <section className="results">
          <div className="panel">
            <h2>Cụm nhu cầu</h2>
            <div className="cluster-id">Cluster {result.cluster.cluster_id}</div>
            <h3>{result.cluster.cluster_name}</h3>
            <p>{result.cluster.interpretation}</p>
            <dl>
              <div><dt>Mean sales</dt><dd>{result.cluster.mean_sales.toFixed(3)}</dd></div>
              <div><dt>Zero-sales ratio</dt><dd>{result.cluster.zero_sales_ratio.toFixed(3)}</dd></div>
              <div><dt>ADI</dt><dd>{result.cluster.adi.toFixed(3)}</dd></div>
              <div><dt>CV²</dt><dd>{result.cluster.cv2.toFixed(3)}</dd></div>
            </dl>
          </div>

          <div className="panel">
            <h2>Cảnh báo</h2>
            <ul className="warnings">
              {result.warnings.map((warning) => <li key={warning}>{warning}</li>)}
            </ul>
          </div>

          <div className="panel table-panel">
            <div className="table-head">
              <h2>Bảng forecast</h2>
              <button className="secondary" onClick={exportForecast}>
                <Download size={16} />
                Export CSV
              </button>
            </div>
            <table>
              <thead>
                <tr><th>Ngày</th><th>Horizon</th><th>Forecast</th></tr>
              </thead>
              <tbody>
                {result.forecast.map((row) => (
                  <tr key={row.horizon}>
                    <td>{row.date}</td>
                    <td>{row.horizon}</td>
                    <td>{row.forecast.toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </main>
  );
}

function Metric({ title, value }: { title: string; value: string }) {
  return (
    <div className="metric-card">
      <span>{title}</span>
      <strong>{value}</strong>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);

