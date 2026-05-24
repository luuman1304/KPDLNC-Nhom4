const API_BASE = `${window.location.origin}/api`;
let records = [];
let lastResult = null;
let batchResult = null;
let selectedSeriesKey = null;
let sampleRecords = [];

const $ = (id) => document.getElementById(id);

async function init() {
  try {
    const overview = await fetch(`${API_BASE}/overview`).then((r) => r.json());
    $("mode").textContent = overview.artifact_mode;
    if (overview.warnings?.length) {
      $("notice").textContent = overview.warnings[0];
      $("notice").classList.remove("hidden");
    }
  } catch {
    $("mode").textContent = "offline";
    $("notice").textContent = "Backend chưa chạy tại http://127.0.0.1:8000.";
    $("notice").classList.remove("hidden");
  }
  await loadSamplePreview();
  drawChart();
}

function parseCsv(text) {
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

async function loadSamplePreview() {
  try {
    const response = await fetch(`${API_BASE}/sample-series`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const csv = await response.text();
    sampleRecords = parseCsv(csv);
    renderSampleInfo(sampleRecords);
  } catch (err) {
    $("sampleInfo").innerHTML = `<p class="sample-error">Không đọc được thông tin sample: ${err.message ?? String(err)}</p>`;
  }
}

function renderSampleInfo(rows) {
  if (!rows.length) {
    $("sampleInfo").innerHTML = "";
    $("sampleInfo").classList.add("hidden");
    return;
  }
  const first = rows[0];
  const last = rows[rows.length - 1];
  const previewRows = rows.slice(0, 5)
    .map((r) => `<tr><td>${r.date}</td><td>${r.item_id}</td><td>${r.store_id}</td><td>${r.sales}</td><td>${r.sell_price ?? ""}</td></tr>`)
    .join("");
  $("sampleInfo").innerHTML = `
    <div class="sample-summary">
      <strong>Sample gồm ${rows.length} dòng</strong>
      <span>${first.item_id} | ${first.store_id} | ${first.category_id}/${first.department_id}</span>
      <span>Khoảng ngày: ${first.date} đến ${last.date}</span>
      <span>Bấm “Tải sample CSV” để tải file, sau đó upload lại nếu muốn chạy dự báo bằng sample.</span>
    </div>
    <table class="sample-table">
      <thead><tr><th>Ngày</th><th>Item</th><th>Store</th><th>Sales</th><th>Price</th></tr></thead>
      <tbody>${previewRows}</tbody>
    </table>
  `;
  $("sampleInfo").classList.add("hidden");
}

async function runForecast() {
  $("error").classList.add("hidden");
  const modelName = $("model").value;
  if (!records.length) {
    $("error").textContent = "Bạn cần upload file CSV trước khi chạy dự báo. Có thể tải sample CSV rồi upload lại để thử.";
    $("error").classList.remove("hidden");
    return;
  }
  try {
    const response = await fetch(`${API_BASE}/forecast-batch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_name: modelName, forecast_horizon: 28, records }),
    });
    if (!response.ok) throw new Error(await response.text());
    batchResult = await response.json();
    const firstSuccess = batchResult.series.find((s) => s.status === "success");
    selectedSeriesKey = firstSuccess?.series_key ?? batchResult.series[0]?.series_key ?? selectedSeriesKey;
    lastResult = firstSuccess?.result ?? null;
    renderSeriesTable();
    renderSelectedSeries();
    drawChart();
    renderHistoryTable();
  } catch (err) {
    $("error").textContent = err.message ?? String(err);
    $("error").classList.remove("hidden");
  }
}

function renderSelectedSeries() {
  const selected = getSelectedSeriesResult();
  if (!selected || selected.status !== "success" || !selected.result) {
    $("results").classList.add("hidden");
    lastResult = null;
    return;
  }
  const result = selected.result;
  lastResult = result;
  $("results").classList.remove("hidden");
  $("clusterBadge").textContent = `Cluster ${result.cluster.cluster_id}`;
  $("clusterName").textContent = result.cluster.cluster_name;
  $("clusterText").textContent = result.cluster.interpretation;
  $("meanSales").textContent = result.cluster.mean_sales.toFixed(3);
  $("zeroRatio").textContent = result.cluster.zero_sales_ratio.toFixed(3);
  $("adi").textContent = result.cluster.adi.toFixed(3);
  $("cv2").textContent = result.cluster.cv2.toFixed(3);
  $("warnings").innerHTML = result.warnings.map((w) => `<li>${w}</li>`).join("");
  const totalForecast = result.forecast.reduce((sum, r) => sum + Number(r.forecast || 0), 0);
  const avgForecast = totalForecast / Math.max(1, result.forecast.length);
  $("forecastSummary").innerHTML = `
    <div><span>Tổng forecast ${result.forecast.length} ngày</span><strong>${formatNumber(totalForecast)} sản phẩm</strong></div>
    <div><span>Trung bình forecast/ngày</span><strong>${formatNumber(avgForecast)} sản phẩm/ngày</strong></div>
    <p>Forecast là số lượng bán kỳ vọng theo từng ngày. Tổng ${result.forecast.length} ngày được tính bằng cách cộng toàn bộ các dòng dự báo.</p>
  `;
  $("forecastTable").innerHTML = result.forecast
    .map((r) => `<tr><td>${r.date}</td><td>D+${r.horizon}</td><td>${Number(r.forecast).toFixed(3)}</td></tr>`)
    .join("");
}

function renderSeriesTable() {
  const grouped = summarizeInputSeries();
  if (!grouped.length && !batchResult?.series?.length) {
    $("seriesSection").classList.add("hidden");
    $("seriesTable").innerHTML = "";
    $("seriesSummary").textContent = "";
    return;
  }
  const rows = batchResult?.series?.length ? batchResult.series : grouped;
  const successCount = batchResult ? batchResult.n_success : 0;
  $("seriesSummary").textContent = batchResult
    ? `${batchResult.n_series} chuỗi | Thành công: ${successCount} | Lỗi: ${batchResult.n_failed}`
    : `${rows.length} chuỗi nhận diện từ file upload`;
  $("seriesTable").innerHTML = rows.map((s) => {
    const result = s.result;
    const clusterText = result ? `Cluster ${result.cluster.cluster_id}` : "-";
    const statusText = s.status === "success" ? "Đã forecast" : s.status === "failed" ? "Lỗi" : "Chưa chạy";
    const selectedClass = s.series_key === selectedSeriesKey ? " selected-row" : "";
    const disabledClass = s.status === "failed" ? " failed-row" : "";
    return `<tr class="series-row${selectedClass}${disabledClass}" data-series-key="${encodeURIComponent(s.series_key)}">
      <td>${s.item_id}</td><td>${s.store_id}</td><td>${s.category_id}/${s.department_id}</td>
      <td>${s.n_records}</td><td>${formatNumber(s.total_sales)}</td><td>${formatNumber(s.zero_sales_ratio_input)}</td>
      <td>${clusterText}</td><td>${statusText}</td>
    </tr>`;
  }).join("");
  $("seriesSection").classList.remove("hidden");
  document.querySelectorAll(".series-row").forEach((row) => {
    row.addEventListener("click", () => {
      selectedSeriesKey = decodeURIComponent(row.dataset.seriesKey);
      renderSeriesTable();
      renderSelectedSeries();
      drawChart();
      renderHistoryTable();
    });
  });
}

function summarizeInputSeries() {
  const groups = new Map();
  for (const r of records) {
    const key = seriesKey(r);
    if (!groups.has(key)) {
      groups.set(key, {
        series_key: key,
        item_id: r.item_id,
        store_id: r.store_id,
        state_id: r.state_id,
        category_id: r.category_id,
        department_id: r.department_id,
        n_records: 0,
        total_sales: 0,
        zero_count: 0,
        zero_sales_ratio_input: 0,
        status: "pending",
        result: null,
      });
    }
    const group = groups.get(key);
    group.n_records += 1;
    group.total_sales += Number(r.sales || 0);
    if (Number(r.sales || 0) === 0) group.zero_count += 1;
  }
  return Array.from(groups.values()).map((g) => ({
    ...g,
    total_sales: Number(g.total_sales.toFixed(6)),
    mean_sales_input: g.n_records ? g.total_sales / g.n_records : 0,
    zero_sales_ratio_input: g.n_records ? g.zero_count / g.n_records : 0,
  }));
}

function seriesKey(record) {
  return [record.item_id, record.store_id, record.state_id, record.category_id, record.department_id].join("|");
}

function getSelectedSeriesResult() {
  if (!batchResult?.series?.length) return null;
  return batchResult.series.find((s) => s.series_key === selectedSeriesKey) ?? batchResult.series[0];
}

function getSelectedRecords() {
  if (!selectedSeriesKey) return records;
  return records.filter((r) => seriesKey(r) === selectedSeriesKey);
}

function drawChart() {
  const canvas = $("chart");
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const selectedRecords = getSelectedRecords().sort((a, b) => String(a.date).localeCompare(String(b.date)));
  const actual = selectedRecords.map((r) => Number(r.sales));
  const forecast = lastResult ? lastResult.forecast.map((r) => Number(r.forecast)) : [];
  const actualDates = selectedRecords.map((r) => r.date);
  const forecastDates = lastResult ? lastResult.forecast.map((r) => r.date) : [];
  const allDates = [...actualDates, ...forecastDates];
  const allValues = [...actual, ...forecast, 1];
  const maxRaw = Math.max(...allValues);
  const maxValue = niceMax(maxRaw * 1.18);
  const left = 74, right = 28, top = 36, bottom = 78;
  const width = canvas.width - left - right;
  const height = canvas.height - top - bottom;
  const total = Math.max(1, allDates.length - 1);
  const x = (i) => left + (i / total) * width;
  const y = (v) => top + height - (v / maxValue) * height;

  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.strokeStyle = "#d0d5dd";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(left, top);
  ctx.lineTo(left, top + height);
  ctx.lineTo(left + width, top + height);
  ctx.stroke();

  drawGridAndAxes();
  if (!actual.length) {
    ctx.fillStyle = "#667085";
    ctx.font = "16px system-ui";
    ctx.textAlign = "center";
    ctx.fillText("Upload file CSV để hiển thị doanh số lịch sử và chạy dự báo.", left + width / 2, top + height / 2);
    ctx.textAlign = "left";
    return;
  }

  plotLine(actual, 0, "#2563eb", "Actual");
  plotLine(forecast, actual.length, "#dc2626", "Forecast");
  drawBoundary();
  drawLegend();
  drawValueNotes();

  function drawGridAndAxes() {
    ctx.font = "12px system-ui";
    ctx.fillStyle = "#667085";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    const ticks = 5;
    for (let i = 0; i <= ticks; i++) {
      const value = (maxValue / ticks) * i;
      const py = y(value);
      ctx.strokeStyle = i === 0 ? "#98a2b3" : "#eef2f7";
      ctx.beginPath();
      ctx.moveTo(left, py);
      ctx.lineTo(left + width, py);
      ctx.stroke();
      ctx.fillText(formatNumber(value), left - 10, py);
    }
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    const labelCount = Math.min(6, allDates.length);
    for (let i = 0; i < labelCount; i++) {
      const idx = Math.round((allDates.length - 1) * (i / Math.max(1, labelCount - 1)));
      const px = x(idx);
      ctx.fillText(shortDate(allDates[idx]), px, top + height + 13);
    }
    ctx.font = "13px system-ui";
    ctx.fillStyle = "#344054";
    ctx.fillText("Thời gian (ngày)", left + width / 2, canvas.height - 22);
    ctx.save();
    ctx.translate(22, top + height / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText("Doanh số / số lượng bán", 0, 0);
    ctx.restore();
  }

  function plotLine(values, offset, color) {
    if (!values.length) return;
    ctx.strokeStyle = color;
    ctx.lineWidth = 2.4;
    ctx.beginPath();
    values.forEach((v, idx) => {
      const px = x(offset + idx);
      const py = y(v);
      if (idx === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    });
    ctx.stroke();
    ctx.fillStyle = color;
    values.forEach((v, idx) => {
      if (idx % Math.max(1, Math.ceil(values.length / 12)) !== 0 && idx !== values.length - 1) return;
      ctx.beginPath();
      ctx.arc(x(offset + idx), y(v), 3, 0, Math.PI * 2);
      ctx.fill();
    });
  }

  function drawLegend() {
    const items = [
      ["Actual", "#2563eb"],
      ["Forecast", "#dc2626"],
    ];
    ctx.font = "13px system-ui";
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    items.forEach(([label, color], idx) => {
      const lx = left + 12 + idx * 112;
      const ly = top - 16;
      ctx.strokeStyle = color;
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.moveTo(lx, ly);
      ctx.lineTo(lx + 28, ly);
      ctx.stroke();
      ctx.fillStyle = "#344054";
      ctx.fillText(label, lx + 36, ly);
    });
  }

  function drawBoundary() {
    if (!actual.length || !forecast.length) return;
    const bx = x(actual.length - 0.5);
    ctx.setLineDash([5, 5]);
    ctx.strokeStyle = "#98a2b3";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(bx, top);
    ctx.lineTo(bx, top + height);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "#667085";
    ctx.font = "12px system-ui";
    ctx.textAlign = "center";
    ctx.fillText("Bắt đầu forecast", bx, top + 12);
  }

  function drawValueNotes() {
    ctx.font = "12px system-ui";
    ctx.textAlign = "left";
    const lastActual = actual[actual.length - 1];
    ctx.fillStyle = "#2563eb";
    ctx.fillText(`Actual cuối: ${formatNumber(lastActual)}`, left + width - 230, top + 18);
    if (forecast.length) {
      const firstForecast = forecast[0];
      const lastForecast = forecast[forecast.length - 1];
      ctx.fillStyle = "#dc2626";
      ctx.fillText(`Forecast D+1: ${formatNumber(firstForecast)} | D+28: ${formatNumber(lastForecast)}`, left + width - 230, top + 36);
    }
  }
}

function niceMax(value) {
  if (!Number.isFinite(value) || value <= 0) return 1;
  const pow = Math.pow(10, Math.floor(Math.log10(value)));
  const scaled = value / pow;
  const nice = scaled <= 2 ? 2 : scaled <= 5 ? 5 : 10;
  return nice * pow;
}

function formatNumber(value) {
  if (!Number.isFinite(value)) return "0";
  if (Math.abs(value) >= 100) return String(Math.round(value));
  return value.toFixed(value >= 10 ? 1 : 2).replace(/\\.00$/, "");
}

function shortDate(dateText) {
  if (!dateText) return "";
  const parts = dateText.split("-");
  return parts.length === 3 ? `${parts[2]}/${parts[1]}` : dateText;
}

function exportCsv() {
  if (!batchResult && !lastResult) return;
  const rows = ["item_id,store_id,date,horizon,forecast,model,cluster_id"];
  const resultRows = batchResult?.series?.filter((s) => s.status === "success" && s.result) ?? [{ result: lastResult }];
  for (const series of resultRows) {
    const result = series.result;
    if (!result) continue;
    const historyFirst = result.history?.[0] ?? {};
    for (const p of result.forecast) {
      rows.push(`${historyFirst.item_id ?? ""},${historyFirst.store_id ?? ""},${p.date},${p.horizon},${p.forecast},${result.model_name},${result.cluster.cluster_id}`);
    }
  }
  const blob = new Blob([rows.join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "forecast.csv";
  a.click();
  URL.revokeObjectURL(url);
}

function renderHistoryTable() {
  const selectedRecords = getSelectedRecords().sort((a, b) => String(a.date).localeCompare(String(b.date)));
  if (!selectedRecords.length) {
    $("historySection").classList.add("hidden");
    $("historyTable").innerHTML = "";
    $("historySummary").textContent = "";
    return;
  }
  const totalSales = selectedRecords.reduce((sum, r) => sum + Number(r.sales || 0), 0);
  const avgSales = totalSales / selectedRecords.length;
  const first = selectedRecords[0];
  const last = selectedRecords[selectedRecords.length - 1];
  const seriesCount = summarizeInputSeries().length;
  $("historySummary").textContent = `${first.item_id} | ${first.store_id} | ${selectedRecords.length} ngày | ${first.date} - ${last.date} | Tổng sales: ${formatNumber(totalSales)} | TB/ngày: ${formatNumber(avgSales)}${seriesCount > 1 ? ` | ${seriesCount} chuỗi trong file` : ""}`;
  $("historyTable").innerHTML = selectedRecords
    .map((r) => `<tr><td>${r.date}</td><td>${r.item_id}</td><td>${r.store_id}</td><td>${formatNumber(r.sales)}</td><td>${r.sell_price ?? ""}</td><td>${r.snap}</td></tr>`)
    .join("");
  $("historySection").classList.remove("hidden");
}

$("fileInput").addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  records = parseCsv(await file.text());
  lastResult = null;
  batchResult = null;
  const groups = summarizeInputSeries();
  selectedSeriesKey = groups[0]?.series_key ?? null;
  $("recordCount").textContent = `${records.length} dòng`;
  $("results").classList.add("hidden");
  $("notice").textContent = `Đã load ${records.length} dòng từ file ${file.name}. Chọn mô hình và bấm Chạy dự báo.`;
  $("notice").classList.remove("hidden");
  renderSeriesTable();
  drawChart();
  renderHistoryTable();
});
$("runForecast").addEventListener("click", runForecast);
$("exportCsv").addEventListener("click", exportCsv);

init();
