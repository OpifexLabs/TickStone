(() => {
  const chart = document.getElementById("time-chart");
  if (!chart) return;

  const NS = "http://www.w3.org/2000/svg";
  const typeButtons = [...document.querySelectorAll("[data-chart-type]")];
  const toggles = [...document.querySelectorAll("[data-series-id]")];
  const typeKey = "tickstone-time-chart-type";
  const seriesKey = "tickstone-time-chart-series";
  let data = null;
  let chartType = sessionStorage.getItem(typeKey) || "bar";
  if (!['bar', 'line'].includes(chartType)) chartType = "bar";

  const savedIds = (() => {
    try {
      const value = JSON.parse(sessionStorage.getItem(seriesKey) || "null");
      return Array.isArray(value) ? new Set(value.map(Number)) : null;
    } catch (_) { return null; }
  })();
  if (savedIds) toggles.forEach(input => { input.checked = savedIds.has(Number(input.dataset.seriesId)); });

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
    if (/^\d{4}-\d{2}-\d{2}$/.test(label)) return label.slice(5);
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
      empty.textContent = data.series.length ? "Välj minst en vana för att visa grafen." : "Ingen tidsaktivitet att visa ännu.";
      chart.append(empty);
      chart.setAttribute("aria-label", empty.textContent);
      return;
    }

    const width = Math.max(420, chart.clientWidth || 620);
    const height = 280;
    const margin = { top: 16, right: 12, bottom: 34, left: 44 };
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
    data.labels.forEach((label, index) => {
      const x = margin.left + bucketWidth * (index + 0.5);
      svg.append(node("text", { x, y: height - 10, "text-anchor": "middle", class: "time-axis-label" }, shortLabel(label)));
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
    chart.setAttribute("aria-label", `${chartType === "bar" ? "Stapeldiagram" : "Linjediagram"} över faktisk tid för ${series.map(item => item.name).join(", ")}. Totalt ${duration(total)}.`);
  }

  typeButtons.forEach(button => button.addEventListener("click", () => {
    chartType = button.dataset.chartType;
    sessionStorage.setItem(typeKey, chartType);
    draw();
  }));
  toggles.forEach(input => input.addEventListener("change", () => {
    sessionStorage.setItem(seriesKey, JSON.stringify(toggles.filter(item => item.checked).map(item => Number(item.dataset.seriesId))));
    draw();
  }));

  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(draw, 120);
  });

  const url = `/api/time-chart?period=${encodeURIComponent(chart.dataset.period)}&offset=${encodeURIComponent(chart.dataset.offset)}`;
  fetch(url, { headers: { Accept: "application/json" } })
    .then(response => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then(payload => { data = payload; draw(); })
    .catch(() => {
      chart.replaceChildren();
      const message = document.createElement("p");
      message.className = "chart-empty";
      message.textContent = "Tidsgrafen kunde inte laddas.";
      chart.append(message);
    });

  syncControls();
  window.setTimeout(() => { if (!document.hidden) window.location.reload(); }, 300000);
})();
