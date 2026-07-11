(() => {
  const chart = document.getElementById("timeline-chart");
  if (!chart) return;

  const toggles = document.getElementById("timeline-series");
  const rangeButtons = [...document.querySelectorAll("[data-range]")];
  const NS = "http://www.w3.org/2000/svg";
  let currentRange = sessionStorage.getItem("tickstone-chart-range") || "week";
  let payload = null;
  let selected = new Set(JSON.parse(sessionStorage.getItem("tickstone-chart-series") || "[]"));
  let selectionInitialized = selected.size > 0;

  const svgNode = (name, attributes = {}) => {
    const node = document.createElementNS(NS, name);
    Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
    return node;
  };

  const shortLabel = (label, range) => {
    if (range === "year") {
      const months = ["Jan", "Feb", "Mar", "Apr", "Maj", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dec"];
      return months[Number(label.slice(-2)) - 1];
    }
    return String(Number(label.slice(-2)));
  };

  const renderToggles = () => {
    toggles.querySelectorAll(".series-toggle").forEach((node) => node.remove());
    if (!selectionInitialized) {
      payload.series.slice(0, 4).forEach((series) => selected.add(series.id));
      selectionInitialized = true;
    }
    payload.series.forEach((series) => {
      const label = document.createElement("label");
      label.className = "series-toggle";
      label.style.setProperty("--series-color", series.color);
      const input = document.createElement("input");
      input.type = "checkbox";
      input.value = String(series.id);
      input.checked = selected.has(series.id);
      input.addEventListener("change", () => {
        if (input.checked) selected.add(series.id); else selected.delete(series.id);
        sessionStorage.setItem("tickstone-chart-series", JSON.stringify([...selected]));
        renderChart();
      });
      const dot = document.createElement("span");
      dot.className = "series-dot";
      dot.setAttribute("aria-hidden", "true");
      const text = document.createElement("span");
      text.textContent = series.name;
      label.append(input, dot, text);
      toggles.append(label);
    });
  };

  const renderChart = () => {
    chart.replaceChildren();
    const visible = payload.series.filter((series) => selected.has(series.id));
    if (!visible.length) {
      const empty = document.createElement("p");
      empty.className = "chart-empty";
      empty.textContent = "Välj minst en habit för att visa grafen.";
      chart.append(empty);
      chart.setAttribute("aria-label", "Ingen habit vald i linjegrafen");
      return;
    }
    const width = 920, height = 300;
    const margin = {top: 22, right: 18, bottom: 42, left: 34};
    const innerWidth = width - margin.left - margin.right;
    const innerHeight = height - margin.top - margin.bottom;
    const maximum = Math.max(1, ...visible.flatMap((series) => series.values));
    const svg = svgNode("svg", {viewBox: `0 0 ${width} ${height}`, role: "presentation", "aria-hidden": "true"});

    const tickCount = Math.min(4, maximum);
    for (let step = 0; step <= tickCount; step += 1) {
      const y = margin.top + innerHeight * step / tickCount;
      svg.append(svgNode("line", {x1: margin.left, y1: y, x2: width - margin.right, y2: y, class: "chart-grid"}));
      const axis = svgNode("text", {x: margin.left - 8, y: y + 3, "text-anchor": "end", class: "chart-axis-label"});
      axis.textContent = String(Math.round(maximum * (tickCount - step) / tickCount));
      svg.append(axis);
    }

    const labelEvery = payload.labels.length > 20 ? 5 : payload.labels.length > 12 ? 3 : 1;
    payload.labels.forEach((label, index) => {
      if (index % labelEvery !== 0 && index !== payload.labels.length - 1) return;
      const x = margin.left + (payload.labels.length === 1 ? innerWidth / 2 : innerWidth * index / (payload.labels.length - 1));
      const text = svgNode("text", {x, y: height - 17, "text-anchor": "middle", class: "chart-axis-label"});
      text.textContent = shortLabel(label, payload.range);
      svg.append(text);
    });

    visible.forEach((series) => {
      const points = series.values.map((value, index) => {
        const x = margin.left + (series.values.length === 1 ? innerWidth / 2 : innerWidth * index / (series.values.length - 1));
        const y = margin.top + innerHeight - value / maximum * innerHeight;
        return {x, y, value, label: payload.labels[index]};
      });
      const path = svgNode("polyline", {points: points.map((point) => `${point.x},${point.y}`).join(" "),
        class: "chart-line", stroke: series.color});
      svg.append(path);
      points.forEach((point) => {
        const circle = svgNode("circle", {cx: point.x, cy: point.y, r: 4, fill: series.color, class: "chart-point"});
        const title = svgNode("title");
        title.textContent = `${series.name}, ${point.label}: ${point.value} aktivitetstillfällen`;
        circle.append(title);
        svg.append(circle);
      });
    });
    chart.append(svg);
    chart.setAttribute("aria-label", `${visible.map((series) => series.name).join(", ")}. ${payload.range}. Linjegraf över aktivitetstillfällen.`);
  };

  const loadRange = async (range) => {
    rangeButtons.forEach((button) => {
      const active = button.dataset.range === range;
      button.classList.toggle("selected", active);
      button.setAttribute("aria-pressed", String(active));
    });
    chart.replaceChildren();
    const loading = document.createElement("p");
    loading.className = "chart-loading";
    loading.textContent = "Laddar utveckling…";
    chart.append(loading);
    try {
      const response = await fetch(`/api/timeline?range=${encodeURIComponent(range)}`, {headers: {Accept: "application/json"}});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      payload = await response.json();
      currentRange = range;
      sessionStorage.setItem("tickstone-chart-range", range);
      renderToggles();
      renderChart();
    } catch (_) {
      chart.replaceChildren();
      const error = document.createElement("p");
      error.className = "chart-empty";
      error.textContent = "Grafen kunde inte laddas just nu.";
      chart.append(error);
    }
  };

  rangeButtons.forEach((button) => button.addEventListener("click", () => loadRange(button.dataset.range)));
  loadRange(currentRange).catch(() => {});

  window.setTimeout(() => {
    if (!document.hidden) window.location.reload();
  }, 300000);
})();
