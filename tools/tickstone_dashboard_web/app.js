(() => {
  const chart = document.getElementById("time-chart");
  if (!chart) return;

  const REFRESH_INTERVAL_MS = 5 * 60 * 1000;
  const LIVE_REGION_NAMES = ["period-navigation", "highlights", "time-series", "habits", "heatmap", "insights", "sync-status"];
  const NS = "http://www.w3.org/2000/svg";
  const typeButtons = [...document.querySelectorAll("[data-chart-type]")];
  let toggles = [];
  const typeKey = "tickstone-time-chart-type";
  const seriesKey = "tickstone-time-chart-series";
  let data = null;
  let refreshInFlight = null;
  let chartType = sessionStorage.getItem(typeKey) || "bar";
  if (!['bar', 'line'].includes(chartType)) chartType = "bar";

  function savedSeriesIds() {
    try {
      const value = JSON.parse(sessionStorage.getItem(seriesKey) || "null");
      return Array.isArray(value) ? new Set(value.map(Number)) : null;
    } catch (_) { return null; }
  }

  function bindToggles() {
    toggles = [...document.querySelectorAll("[data-series-id]")];
    const savedIds = savedSeriesIds();
    if (savedIds) toggles.forEach(input => { input.checked = savedIds.has(Number(input.dataset.seriesId)); });
    toggles.forEach(input => input.addEventListener("change", () => {
      sessionStorage.setItem(seriesKey, JSON.stringify(toggles.filter(item => item.checked).map(item => Number(item.dataset.seriesId))));
      draw();
    }));
  }

  function node(name, attrs = {}, text = "") {
    const element = document.createElementNS(NS, name);
    Object.entries(attrs).forEach(([key, value]) => element.setAttribute(key, String(value)));
    if (text) element.textContent = text;
    return element;
  }

  function duration(seconds) {
    if (seconds < 60) return `${Math.round(seconds)} s`;
    if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.round((seconds % 3600) / 60);
    return minutes ? `${hours} h ${minutes} min` : `${hours} h`;
  }

  function shortLabel(label) {
    if (/^\d{4}-\d{2}-\d{2}$/.test(label)) {
      return data && data.period === "month" ? label.slice(8) : label.slice(5);
    }
    if (/^\d{4}-\d{2}$/.test(label)) return label.slice(2);
    return label;
  }

  function selectedSeries() {
    const selected = new Set(toggles.filter(input => input.checked).map(input => Number(input.dataset.seriesId)));
    return data ? data.series.filter(series => selected.has(series.id)) : [];
  }

  function syncControls() {
    typeButtons.forEach(button => {
      const active = button.dataset.chartType === chartType;
      button.classList.toggle("selected", active);
      button.setAttribute("aria-pressed", String(active));
    });
  }

  function draw() {
    syncControls();
    if (!data) return;
    const series = selectedSeries();
    chart.replaceChildren();
    if (!series.length) {
      const empty = document.createElement("p");
      empty.className = "chart-empty";
      empty.textContent = data.series.length ? "Select at least one habit to show the chart." : "No time activity to show yet.";
      chart.append(empty);
      chart.setAttribute("aria-label", empty.textContent);
      return;
    }

    const width = Math.max(420, chart.clientWidth || 620);
    const height = Math.round(parseFloat(getComputedStyle(chart).height)) || 162;
    const margin = { top: 10, right: 10, bottom: 27, left: 38 };
    const plotWidth = width - margin.left - margin.right;
    const plotHeight = height - margin.top - margin.bottom;
    const maximum = Math.max(1, ...series.flatMap(item => item.values));
    const tickCount = Math.max(1, Math.min(4, maximum));
    const svg = node("svg", { viewBox: `0 0 ${width} ${height}`, "aria-hidden": "true" });

    for (let index = 0; index <= tickCount; index += 1) {
      const value = maximum * index / tickCount;
      const y = margin.top + plotHeight - plotHeight * index / tickCount;
      svg.append(node("line", { x1: margin.left, y1: y, x2: width - margin.right, y2: y, class: "time-grid-line" }));
      svg.append(node("text", { x: margin.left - 7, y: y + 3, "text-anchor": "end", class: "time-axis-label" }, duration(value)));
    }

    const bucketWidth = plotWidth / Math.max(1, data.labels.length);
    const maximumLabels = Math.max(2, Math.floor(plotWidth / 38));
    const labelStep = Math.max(1, Math.ceil(data.labels.length / maximumLabels));
    data.labels.forEach((label, index) => {
      if (index % labelStep !== 0 && index !== data.labels.length - 1) return;
      const x = margin.left + bucketWidth * (index + 0.5);
      svg.append(node("text", { x, y: height - 8, "text-anchor": "middle", class: "time-axis-label" }, shortLabel(label)));
    });

    if (chartType === "bar") {
      const gap = Math.min(3, bucketWidth * 0.08);
      const barWidth = Math.max(2, Math.min(22, (bucketWidth - gap * (series.length + 1)) / series.length));
      data.labels.forEach((label, labelIndex) => {
        const totalWidth = series.length * barWidth + (series.length - 1) * gap;
        const start = margin.left + bucketWidth * (labelIndex + 0.5) - totalWidth / 2;
        series.forEach((item, seriesIndex) => {
          const value = item.values[labelIndex] || 0;
          const barHeight = plotHeight * value / maximum;
          const rect = node("rect", { x: start + seriesIndex * (barWidth + gap), y: margin.top + plotHeight - barHeight,
            width: barWidth, height: Math.max(value ? 2 : 0, barHeight), rx: 2, fill: item.color, class: "time-bar" });
          rect.append(node("title", {}, `${item.name} · ${label}: ${duration(value)}`));
          svg.append(rect);
        });
      });
    } else {
      series.forEach(item => {
        const points = item.values.map((value, index) => {
          const x = margin.left + bucketWidth * (index + 0.5);
          const y = margin.top + plotHeight - plotHeight * value / maximum;
          return { x, y, value, label: data.labels[index] };
        });
        svg.append(node("polyline", { points: points.map(point => `${point.x},${point.y}`).join(" "), stroke: item.color, class: "time-line" }));
        points.forEach(point => {
          const dot = node("circle", { cx: point.x, cy: point.y, r: 3.5, fill: item.color, class: "time-dot" });
          dot.append(node("title", {}, `${item.name} · ${point.label}: ${duration(point.value)}`));
          svg.append(dot);
        });
      });
    }

    chart.append(svg);
    const total = series.reduce((sum, item) => sum + item.values.reduce((part, value) => part + value, 0), 0);
    chart.setAttribute("aria-label", `${chartType === "bar" ? "Bar chart" : "Line chart"} of actual time for ${series.map(item => item.name).join(", ")}. Total ${duration(total)}.`);
  }

  typeButtons.forEach(button => button.addEventListener("click", () => {
    chartType = button.dataset.chartType;
    sessionStorage.setItem(typeKey, chartType);
    draw();
  }));
  bindToggles();

  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(draw, 120);
  });

  function chartUrl() {
    return `/api/time-chart?period=${encodeURIComponent(chart.dataset.period)}&offset=${encodeURIComponent(chart.dataset.offset)}`;
  }

  async function fetchChartData() {
    const response = await fetch(chartUrl(), { headers: { Accept: "application/json" }, cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  async function fetchDashboardDocument() {
    const url = `${window.location.pathname}${window.location.search}`;
    const response = await fetch(url, { headers: { Accept: "text/html" }, cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return new DOMParser().parseFromString(await response.text(), "text/html");
  }

  function patchLiveRegions(nextDocument) {
    let reboundToggles = false;
    LIVE_REGION_NAMES.forEach(name => {
      const selector = `[data-live-region="${name}"]`;
      const current = document.querySelector(selector);
      const incoming = nextDocument.querySelector(selector);
      if (!current || !incoming || current.innerHTML === incoming.innerHTML) return;
      current.innerHTML = incoming.innerHTML;
      if (name === "time-series") reboundToggles = true;
    });
    if (reboundToggles) bindToggles();
  }

  async function refreshDashboard() {
    if (refreshInFlight) return refreshInFlight;
    refreshInFlight = Promise.allSettled([fetchDashboardDocument(), fetchChartData()])
      .then(([pageResult, chartResult]) => {
        let refreshed = false;
        if (pageResult.status === "fulfilled") {
          patchLiveRegions(pageResult.value);
          refreshed = true;
        }
        if (chartResult.status === "fulfilled") {
          data = chartResult.value;
          draw();
          refreshed = true;
        }
        return refreshed;
      })
      .catch(() => false)
      .finally(() => { refreshInFlight = null; });
    return refreshInFlight;
  }

  fetchChartData()
    .then(payload => { data = payload; draw(); })
    .catch(() => {
      chart.replaceChildren();
      const message = document.createElement("p");
      message.className = "chart-empty";
      message.textContent = "The time chart could not be loaded.";
      chart.append(message);
    });

  syncControls();
  window.tickstoneDashboard = Object.freeze({ refresh: refreshDashboard });
  window.setInterval(refreshDashboard, REFRESH_INTERVAL_MS);
})();
