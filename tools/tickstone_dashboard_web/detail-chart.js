(() => {
  const chart = document.getElementById("detail-chart");
  if (!chart) return;

  const NS = "http://www.w3.org/2000/svg";
  const typeButtons = [...document.querySelectorAll("[data-detail-chart-type]")];
  const modeButtons = [...document.querySelectorAll("[data-chart-mode]")];
  const valueKind = chart.dataset.valueKind;
  const yLabel = chart.dataset.yLabel;
  const chartModes = JSON.parse(chart.dataset.chartModes || "{}");
  const typeStorageKey = `tickstone-detail-chart-type-${chart.dataset.habitId}`;
  const modeStorageKey = `tickstone-detail-chart-mode-${chart.dataset.habitId}`;
  let chartType = sessionStorage.getItem(typeStorageKey) || "bar";
  let chartMode = sessionStorage.getItem(modeStorageKey) || "day";
  if (!["bar", "line"].includes(chartType)) chartType = "bar";
  if (!["day", "week", "month"].includes(chartMode) || !chartModes[chartMode]) chartMode = "day";

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
    typeButtons.forEach(button => {
      const active = button.dataset.detailChartType === chartType;
      button.classList.toggle("selected", active);
      button.setAttribute("aria-pressed", String(active));
    });
    modeButtons.forEach(button => {
      const active = button.dataset.chartMode === chartMode;
      button.classList.toggle("selected", active);
      button.setAttribute("aria-pressed", String(active));
    });
  }

  function draw() {
    syncButtons();
    const points = chartModes[chartMode] || [];
    if (!points.length) {
      chart.textContent = "Ingen aktivitet ännu.";
      return;
    }
    const width = Math.max(420, chart.clientWidth || 760);
    const height = Math.max(180, Math.round(chart.clientHeight || 220));
    const margin = { top: 16, right: 14, bottom: 34, left: 58 };
    const plotWidth = width - margin.left - margin.right;
    const plotHeight = height - margin.top - margin.bottom;
    const maximum = Math.max(1, ...points.map(point => Number(point.value) || 0));
    const tickCount = valueKind === "count" ? Math.max(1, Math.min(4, maximum)) : 4;
    const bucketWidth = plotWidth / points.length;
    const svg = node("svg", { viewBox: `0 0 ${width} ${height}`, "aria-hidden": "true" });

    for (let index = 0; index <= tickCount; index += 1) {
      const value = maximum * index / tickCount;
      const y = margin.top + plotHeight - plotHeight * index / tickCount;
      svg.append(node("line", { x1: margin.left, y1: y, x2: width - margin.right, y2: y, class: "grid-line" }));
      svg.append(node("text", { x: margin.left - 8, y: y + 4, "text-anchor": "end", class: "axis-label" }, formatValue(value)));
    }

    const maximumLabels = Math.max(2, Math.floor(plotWidth / 52));
    const labelStep = Math.max(1, Math.ceil(points.length / maximumLabels));
    points.forEach((point, index) => {
      if (index % labelStep !== 0 && index !== points.length - 1) return;
      const x = margin.left + bucketWidth * (index + 0.5);
      svg.append(node("text", { x, y: height - 10, "text-anchor": "middle", class: "axis-label" }, shortLabel(point.label)));
    });

    const peakIndex = points.reduce((best, point, index) => point.value >= points[best].value ? index : best, 0);
    if (chartType === "bar") {
      const barWidth = Math.max(5, Math.min(42, bucketWidth * 0.55));
      points.forEach((point, index) => {
        const barHeight = plotHeight * point.value / maximum;
        const x = margin.left + bucketWidth * (index + 0.5) - barWidth / 2;
        const rect = node("rect", { x, y: margin.top + plotHeight - barHeight, width: barWidth,
          height: Math.max(point.value ? 2 : 0, barHeight), rx: 3,
          class: `chart-bar${index === peakIndex && point.value ? " peak" : ""}` });
        rect.append(node("title", {}, `${point.label}: ${formatValue(point.value)}`));
        svg.append(rect);
      });
    } else {
      const positions = points.map((point, index) => ({ ...point,
        x: margin.left + bucketWidth * (index + 0.5),
        y: margin.top + plotHeight - plotHeight * point.value / maximum }));
      svg.append(node("polyline", { points: positions.map(point => `${point.x},${point.y}`).join(" "), class: "chart-line" }));
      positions.forEach(point => {
        const dot = node("circle", { cx: point.x, cy: point.y, r: 3.8, class: "chart-dot" });
        dot.append(node("title", {}, `${point.label}: ${formatValue(point.value)}`));
        svg.append(dot);
      });
    }
    chart.replaceChildren(svg);
    chart.setAttribute("aria-label", `${chartType === "bar" ? "Stapeldiagram" : "Linjediagram"}. ${yLabel}, ${chartMode}. Högsta värde ${formatValue(maximum)}.`);
  }

  typeButtons.forEach(button => button.addEventListener("click", () => {
    chartType = button.dataset.detailChartType;
    sessionStorage.setItem(typeStorageKey, chartType);
    draw();
  }));
  modeButtons.forEach(button => button.addEventListener("click", () => {
    chartMode = button.dataset.chartMode;
    sessionStorage.setItem(modeStorageKey, chartMode);
    draw();
  }));

  document.querySelectorAll(".habit-day:not(.future)").forEach(button => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".habit-day.selected").forEach(item => item.classList.remove("selected"));
      button.classList.add("selected");
      const target = document.getElementById("habit-day-detail");
      const events = JSON.parse(button.dataset.events || "[]");
      const heading = document.createElement("strong");
      heading.textContent = button.dataset.day;
      const summary = document.createElement("span");
      const sessionCount = Number(button.dataset.sessions || 0);
      summary.textContent = `${button.dataset.display || "0"} totalt · ${sessionCount} ${sessionCount === 1 ? "session" : "sessioner"}`;
      const list = document.createElement("ul");
      events.forEach(event => {
        const item = document.createElement("li");
        item.textContent = `${event.time} · ${event.display} · ${event.source}`;
        list.append(item);
      });
      target.replaceChildren(heading, summary, list);
    });
  });

  document.querySelectorAll(".read-only-log-action").forEach(button => button.addEventListener("click", () => {
    button.title = "Dashboarden är skrivskyddad; råloggen kan inte ändras här.";
  }));

  if (window.matchMedia("(max-width: 760px)").matches) {
    document.querySelectorAll("details.mobile-collapsible").forEach(section => section.removeAttribute("open"));
  }

  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(draw, 120);
  });
  draw();
})();
