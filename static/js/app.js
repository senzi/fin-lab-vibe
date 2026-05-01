const charts = {};
let dashboard = null;

const fmtMoney = (value) => value == null ? "--" : `$${Number(value).toLocaleString(undefined, {maximumFractionDigits: 2})}`;
const fmtPct = (value) => value == null ? "--" : `${Number(value).toFixed(2)}%`;
const fmtNum = (value) => value == null ? "--" : Number(value).toLocaleString(undefined, {maximumFractionDigits: Math.abs(value) > 100 ? 1 : 2});

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Request failed: ${response.status}`);
  return response.json();
}

function destroyChart(id) {
  if (charts[id]) {
    charts[id].destroy();
    delete charts[id];
  }
}

function lineData(points) {
  return (points || []).map((point) => ({ x: point.date, y: point.value }));
}

function renderCards(targetId, cards) {
  const target = document.getElementById(targetId);
  target.innerHTML = cards.map((card) => `
    <article class="metric-card ${card.accent ? "accent" : ""}">
      <div class="metric-label">${card.label}</div>
      <div class="metric-value">${card.value}</div>
      <div class="metric-delta">${card.delta || ""}</div>
    </article>
  `).join("");
}

function renderRank(targetId, rows) {
  const max = Math.max(...rows.map((row) => Number(row.value) || 0), 1);
  document.getElementById(targetId).innerHTML = rows.map((row) => {
    const width = Math.max(8, ((Number(row.value) || 0) / max) * 100);
    return `
      <div class="rank-row">
        <span>${row.rank}</span>
        <span class="ticker"><i class="dot" style="background:${row.color}"></i>${row.symbol}</span>
        <span class="bar"><i class="fill" style="width:${width}%;background:${row.color}"></i></span>
        <strong>${row.display}</strong>
      </div>
    `;
  }).join("");
}

function renderCrossCharts(data) {
  destroyChart("crossChart");
  charts.crossChart = new Chart(document.getElementById("crossChart"), {
    type: "line",
    data: {
      datasets: [
        { label: "金价 GLD", data: lineData(data.cross_asset.series.gold), borderColor: "#f6c744", backgroundColor: "rgba(246,199,68,.12)", fill: true, tension: .35, pointRadius: 0, yAxisID: "y" },
        { label: "TIPS 实际利率", data: lineData(data.cross_asset.series.real_yield), borderColor: "#ff9500", borderDash: [8, 7], tension: .35, pointRadius: 0, yAxisID: "y1" },
        { label: "波动率", data: lineData(data.cross_asset.series.volatility), borderColor: "#bdbdbd", tension: .35, pointRadius: 0, yAxisID: "y1" },
      ],
    },
    options: chartOptions({ leftLabel: "GLD $", rightLabel: "Real Yield % / Vol %" }),
  });

  destroyChart("baseChart");
  const base = data.cross_asset.series.base100;
  charts.baseChart = new Chart(document.getElementById("baseChart"), {
    type: "line",
    data: {
      datasets: [
        { label: "Gold", data: lineData(base.Gold), borderColor: "#5470c6", tension: .35, pointRadius: 0 },
        { label: "Vol", data: lineData(base.Vol), borderColor: "#91cc75", tension: .35, pointRadius: 0 },
        { label: "Real Rate", data: lineData(base["Real Rate"]), borderColor: "#ffb347", borderDash: [8, 5], tension: .35, pointRadius: 0 },
      ],
    },
    options: chartOptions({ leftLabel: "Base 100" }),
  });
}

function renderMacroCharts(data) {
  destroyChart("tenYearChart");
  charts.tenYearChart = new Chart(document.getElementById("tenYearChart"), {
    type: "line",
    data: {
      datasets: [{ label: "10Y", data: lineData(data.macro.series.dgs10), borderColor: "#2f80ed", backgroundColor: "rgba(47,128,237,.12)", fill: true, tension: .35, pointRadius: 0 }],
    },
    options: chartOptions({ leftLabel: "%" }),
  });

  destroyChart("curveChart");
  charts.curveChart = new Chart(document.getElementById("curveChart"), {
    type: "line",
    data: {
      labels: data.macro.series.yield_curve.map((p) => p.label),
      datasets: [{ label: "Yield", data: data.macro.series.yield_curve.map((p) => p.value), borderColor: "#2f80ed", backgroundColor: "rgba(47,128,237,.12)", fill: true, tension: .2, pointRadius: 6, pointBackgroundColor: "#fff", pointBorderWidth: 4 }],
    },
    options: chartOptions({ leftLabel: "%" }),
  });
}

function renderValuationCharts(data) {
  renderRank("forwardRank", data.valuation.forward_pe_rank);
  renderRank("percentileRank", data.valuation.pe_percentile_rank);

  destroyChart("ytdChart");
  charts.ytdChart = new Chart(document.getElementById("ytdChart"), {
    type: "bar",
    data: {
      labels: data.valuation.ytd.map((row) => row.symbol),
      datasets: [{ label: "YTD", data: data.valuation.ytd.map((row) => row.value), backgroundColor: data.valuation.ytd.map((row) => row.color) }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: gridScales("%"),
    },
  });

  destroyChart("matrixChart");
  charts.matrixChart = new Chart(document.getElementById("matrixChart"), {
    type: "bubble",
    data: {
      datasets: data.valuation.matrix.map((row) => ({
        label: row.symbol,
        data: [{ x: row.x, y: row.y, r: row.r }],
        backgroundColor: `${row.color}cc`,
      })),
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { color: "#dedede", borderDash: [6, 6] }, title: { display: true, text: "TTM PE" } },
        y: { grid: { color: "#dedede", borderDash: [6, 6] }, title: { display: true, text: "ROE %" } },
      },
    },
  });
}

function chartOptions({ leftLabel = "", rightLabel = "" }) {
  const scales = {
    x: { type: "category", grid: { display: false }, ticks: { maxTicksLimit: 9, color: "#778193", font: { size: 14 } } },
    y: { grid: { color: "#dedede", borderDash: [6, 6] }, ticks: { color: "#778193", font: { size: 14 } }, title: { display: Boolean(leftLabel), text: leftLabel } },
  };
  if (rightLabel) {
    scales.y1 = { position: "right", grid: { drawOnChartArea: false }, ticks: { color: "#ff9500", font: { size: 14 } }, title: { display: true, text: rightLabel } };
  }
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { intersect: false, mode: "index" },
    plugins: {
      legend: { labels: { usePointStyle: true, boxWidth: 8, font: { size: 16 } } },
      tooltip: { backgroundColor: "#111827", padding: 14, titleFont: { size: 18 }, bodyFont: { size: 16 } },
    },
    scales,
  };
}

function gridScales(suffix = "") {
  return {
    x: { grid: { color: "#dedede", borderDash: [6, 6] }, ticks: { callback: (value) => `${value}${suffix}` } },
    y: { grid: { display: false } },
  };
}

function renderDashboard(data) {
  dashboard = data;
  renderCards("crossCards", data.cross_asset.cards);
  document.getElementById("crossComment").textContent = data.cross_asset.commentary;
  renderCrossCharts(data);

  document.getElementById("regimeText").textContent = data.macro.regime;
  document.getElementById("regimeCopy").textContent = data.macro.regime === "Risk-On" ? "风险偏好较高，权益资产更受青睐。" : "市场进入防御状态，现金流和久期风险需要更仔细。";
  renderCards("macroCards", data.macro.cards);
  renderMacroCharts(data);
  renderValuationCharts(data);
}

function renderStock(stock, withGenerated = false) {
  const metrics = [
    ["Beta 系数", fmtNum(stock.metrics.beta)],
    ["TTM PE", fmtNum(stock.metrics.trailing_pe)],
    ["Forward PE", fmtNum(stock.metrics.forward_pe)],
    ["P/S", fmtNum(stock.metrics.price_to_sales)],
    ["P/B", fmtNum(stock.metrics.price_to_book)],
    ["P/FCF", fmtNum(stock.metrics.price_to_fcf)],
    ["ROE", fmtPct(stock.metrics.roe)],
    ["距52周高点", fmtPct(stock.distance_to_52w_high)],
    ["距52周低点", fmtPct(stock.distance_to_52w_low)],
  ];
  document.getElementById("stockResult").innerHTML = `
    <div class="stock-hero">
      <div>
        <small>${stock.name}</small>
        <h2>${stock.symbol}</h2>
        <p>${stock.sector} · ${stock.industry}</p>
      </div>
      <div class="stock-price">
        ${fmtMoney(stock.price)}
        <div class="metric-delta">${stock.change_1m == null ? "" : `↗ ${fmtPct(stock.change_1m)} 1M`}</div>
      </div>
    </div>
    <div class="stock-metrics">
      ${metrics.map(([label, value]) => `<div class="mini-card"><span>${label}</span><strong>${value}</strong></div>`).join("")}
    </div>
    <div class="summary">
      <strong>估值展望</strong><br>
      ${stock.summary}
      ${withGenerated ? `<div class="qwen"><strong>Qwen（本地）</strong><br>* 估值信号：${stock.summary}<br>* 风险提示：高估值、高 Beta 或接近高位时，优先控制仓位和回撤。</div>` : ""}
    </div>
  `;
}

async function loadDashboard(period = "6mo") {
  document.getElementById("crossCards").innerHTML = '<div class="loading">正在加载市场数据...</div>';
  const data = await getJson(`/api/dashboard?period=${period}`);
  renderDashboard(data);
}

async function loadStock(symbol, generated = false) {
  document.getElementById("stockResult").innerHTML = '<div class="loading panel">正在查询个股...</div>';
  const stock = await getJson(`/api/stock/${encodeURIComponent(symbol)}`);
  renderStock(stock, generated);
}

document.querySelectorAll("[data-period]").forEach((button) => {
  button.addEventListener("click", async () => {
    document.querySelectorAll("[data-period]").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    await loadDashboard(button.dataset.period);
  });
});

document.getElementById("stockForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  await loadStock(document.getElementById("symbolInput").value);
});

document.getElementById("summaryBtn").addEventListener("click", async () => {
  await loadStock(document.getElementById("symbolInput").value, true);
});

loadDashboard().catch((error) => {
  document.body.insertAdjacentHTML("afterbegin", `<div class="notice">数据加载失败：${error.message}</div>`);
});
loadStock("USAR").catch(() => {});
