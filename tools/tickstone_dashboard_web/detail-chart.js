(() => {
  const chart = document.getElementById("detail-chart");
  if (!chart) return;

  const NS = "http://www.w3.org/2000/svg";
  const buttons = [...document.querySelectorAll("[data-detail-chart-type]")];
  const points = [...chart.querySelectorAll(".detail-point")].map(point => ({
    label: point.dataset.label,
    value: Number(point.dataset.value) || 0,
  }));
  const valueKind = chart.dataset.valueKind;
  const yLabel = chart.dataset.yLabel;
  const storageKey = `tickstone-detail-chart-type-${chart.dataset.habitId}`;
  let chartType = sessionStorage.getItem(storageKey) || "bar";
  if (!["bar", "line"].includes(chartType)) chartType = "bar";

  function node(name, attrs = {}, text = "") {
    const element = document.createElementNS(NS, name);
    Object.entries(attrs).forEach(([key, value]) => element.setAttribute(key, String(value)));
    if (text) element.textContent = text;
    return element;
  }

  function formatValue(value) {
    if (valueKind === "count") return `${Math.round(value)} st`;
    if (value < 60) return `${Math.round(value)} s`;
    if (value < 3600) return `${Math.round(value / 60)} min`;
    const hours = value / 3600;
    return `${Number.isInteger(hours) ? hours : hours.toFixed(1)} h`;
  }

  function shortLabel(label) {
    if (/^\d{4}-\d{2}-\d{2}$/.test(label)) return label.slice(5);
    if (/^\d{4}-\d{2}$/.test(label)) return label.slice(2);
    return label;
  }

  function syncButtons() {
    buttons.forEach(button => {
      const active = button.dataset.detailChartType === chartType;
      button.classList.toggle("selected", active);
      button.setAttribute("aria-pressed", String(active));
    });
  }

  function draw() {
    syncButtons();
    if (!points.length) return;
    const width = Math.max(420, chart.clientWidth || 760);
    const height = Math.max(220, Math.round(chart.clientHeight || 270));
    const margin = { top: 18, right: 18, bottom: 38, left: 64 };
    const plotWidth = width - margin.left - margin.right;
    const plotHeight = height - margin.top - margin.bottom;
    const maximum = Math.max(1, ...points.map(point => point.value));
    const tickCount = valueKind === "count" ? Math.min(4, Math.max(1, Math.ceil(maximum))) : 4;
    const bucketWidth = plotWidth / points.length;
    const svg = node("svg", { viewBox: `0 0 ${width} ${height}`, "aria-hidden": "true" });

    svg.append(node("text", {
      x: 14, y: margin.top + plotHeight / 2,
      transform: `rotate(-90 14 ${margin.top + plotHeight / 2})`,
      "text-anchor": "middle", class: "detail-axis-title",
    }, yLabel));

    for (let index = 0; index <= tickCount; index += 1) {
      const value = maximum * index / tickCount;
      const y = margin.top + plotHeight - plotHeight * index / tickCount;
      svg.append(node("line", { x1: margin.left, y1: y, x2: width - margin.right, y2: y, class: "detail-grid-line" }));
      svg.append(node("text", { x: margin.left - 9, y: y + 4, "text-anchor": "end", class: "detail-axis-label" }, formatValue(value)));
    }

    const maximumLabels = Math.max(2, Math.floor(plotWidth / 48));
    const labelStep = Math.max(1, Math.ceil(points.length / maximumLabels));
    points.forEach((point, index) => {
      if (index % labelStep !== 0 && index !== points.length - 1) return;
      const x = margin.left + bucketWidth * (index + 0.5);
      svg.append(node("text", { x, y: height - 12, "text-anchor": "middle", class: "detail-axis-label" }, shortLabel(point.label)));
    });

    if (chartType === "bar") {
      const barWidth = Math.max(5, Math.min(38, bucketWidth * 0.55));
      points.forEach((point, index) => {
        const barHeight = plotHeight * point.value / maximum;
        const x = margin.left + bucketWidth * (index + 0.5) - barWidth / 2;
        const rect = node("rect", { x, y: margin.top + plotHeight - barHeight, width: barWidth,
          height: Math.max(point.value ? 2 : 0, barHeight), rx: 3, class: "detail-bar" });
        rect.append(node("title", {}, `${point.label}: ${formatValue(point.value)}`));
        svg.append(rect);
      });
    } else {
      const positions = points.map((point, index) => ({
        ...point,
        x: margin.left + bucketWidth * (index + 0.5),
        y: margin.top + plotHeight - plotHeight * point.value / maximum,
      }));
      svg.append(node("polyline", { points: positions.map(point => `${point.x},${point.y}`).join(" "), class: "detail-line" }));
      positions.forEach(point => {
        const dot = node("circle", { cx: point.x, cy: point.y, r: 4, class: "detail-dot" });
        dot.append(node("title", {}, `${point.label}: ${formatValue(point.value)}`));
        svg.append(dot);
      });
    }

    chart.replaceChildren(svg);
    chart.setAttribute("aria-label", `${chartType === "bar" ? "Stapeldiagram" : "Linjediagram"}. ${yLabel} per kalenderperiod. Högsta värde ${formatValue(maximum)}.`);
  }

  buttons.forEach(button => button.addEventListener("click", () => {
    chartType = button.dataset.detailChartType;
    sessionStorage.setItem(storageKey, chartType);
    draw();
  }));

  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(draw, 120);
  });

  draw();
})();
