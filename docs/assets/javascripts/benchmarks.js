/*
 * Copyright (c) 2026 The SEMQ Group Inc.
 * Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
 */
/* Interactive view of the frozen quality.json results. The chart does not
   calculate benchmark metrics; it only displays the committed measurements. */
(() => {
  const NS = "http://www.w3.org/2000/svg";
  const WIDTH = 760;
  const HEIGHT = 410;
  const PLOT = { left: 66, right: 24, top: 20, bottom: 56 };
  const MODEL_NAMES = {
    e5_small: "e5-small-v2 · 384 dimensions",
    arctic_m: "snowflake-arctic-embed-m-v1.5 · 768 dimensions",
    mxbai_large: "mxbai-embed-large-v1 · 1024 dimensions"
  };
  const METHOD_NAMES = {
    semq_quant2: "SEMQ quant · 2 bits",
    semq_quant4: "SEMQ quant · 3 bits",
    semq_quant8: "SEMQ quant · 4 bits",
    semq_phase16: "SEMQ phase · 16 sectors",
    semq_orbit50: "SEMQ orbit · scale 50",
    faiss_pq2: "Faiss PQ · 2 bits",
    faiss_sq8: "Faiss SQ8",
    int4_block32: "INT4 · block 32",
    mrl256: "Matryoshka · 256 dimensions",
    mrl256_int8: "Matryoshka · 256 dimensions + int8"
  };

  function svgElement(name, attrs = {}) {
    const element = document.createElementNS(NS, name);
    for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, String(value));
    return element;
  }

  function node(name, className, text) {
    const element = document.createElement(name);
    element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function makeSelect(label, options, value) {
    const wrap = node("label", "semq-benchmark-explorer__control");
    wrap.append(node("span", "", label));
    const select = document.createElement("select");
    for (const [key, name] of options) {
      const option = document.createElement("option");
      option.value = key;
      option.textContent = name;
      select.append(option);
    }
    select.value = value;
    wrap.append(select);
    return { wrap, select };
  }

  function displayName(key) {
    return METHOD_NAMES[key] || key.replaceAll("_", " ").replace(/\b[a-z]/g, c => c.toUpperCase());
  }

  function measuredRows(data, model, dataset, filter) {
    const methods = data.results.table[model][dataset].methods;
    return Object.entries(methods).filter(([key, row]) =>
      key !== "fp32" && row.status === "measured" &&
      Number.isFinite(row.bits_per_dim) &&
      Number.isFinite(row.ndcg10_retained_pct) &&
      Number.isFinite(row.overlap10) &&
      (filter === "all" || (key.startsWith("semq_") === (filter === "semq")))
    ).map(([key, row]) => ({ key, ...row }));
  }

  function showDetail(detail, row) {
    detail.replaceChildren(
      node("strong", "", displayName(row.key)),
      node("span", "", `${row.bits_per_dim.toFixed(2)} total bits/dim · ${row.ndcg10_retained_pct.toFixed(1)}% FP32 nDCG@10 · ${row.overlap10.toFixed(1)}% top-10 overlap`)
    );
  }

  function draw(data, controls, chart, detail) {
    const model = controls.model.value;
    const dataset = controls.dataset.value;
    const metric = controls.metric.value;
    const rows = measuredRows(data, model, dataset, controls.filter.value);
    const selectedKey = controls.selection.value;
    controls.selection.replaceChildren();
    for (const row of [...rows].sort((a, b) => a.bits_per_dim - b.bits_per_dim || displayName(a.key).localeCompare(displayName(b.key)))) {
      const option = document.createElement("option");
      option.value = row.key;
      option.textContent = displayName(row.key);
      controls.selection.append(option);
    }
    const values = rows.map(row => row[metric]);
    const minimum = Math.max(0, Math.floor((Math.min(...values) - 5) / 10) * 10);
    const maximum = metric === "overlap10" ? 100 : Math.max(105, Math.ceil(Math.max(...values) / 10) * 10);
    const yBottom = HEIGHT - PLOT.bottom;
    const xRight = WIDTH - PLOT.right;
    const x = bits => PLOT.left + Math.log2(bits) / 5 * (xRight - PLOT.left);
    const y = value => yBottom - (value - minimum) / (maximum - minimum) * (yBottom - PLOT.top);
    const metricName = metric === "overlap10" ? "Top-10 overlap with FP32" : "nDCG@10 relative to FP32";
    chart.replaceChildren();
    chart.setAttribute("aria-label", `${metricName} against total bits per dimension, ${MODEL_NAMES[model]}, ${dataset === "scifact" ? "SciFact" : "FiQA"}`);

    for (let tick = minimum; tick <= maximum; tick += 10) {
      const line = svgElement("line", { x1: PLOT.left, x2: xRight, y1: y(tick), y2: y(tick), class: "semq-benchmark-explorer__grid" });
      chart.append(line);
      const label = svgElement("text", { x: PLOT.left - 10, y: y(tick) + 4, "text-anchor": "end", class: "semq-benchmark-explorer__tick" });
      label.textContent = `${tick}%`;
      chart.append(label);
    }
    if (minimum < 100 && maximum >= 100) {
      chart.append(svgElement("line", { x1: PLOT.left, x2: xRight, y1: y(100), y2: y(100), class: "semq-benchmark-explorer__reference" }));
    }
    for (const tick of [1, 2, 4, 8, 16, 32]) {
      const label = svgElement("text", { x: x(tick), y: yBottom + 23, "text-anchor": "middle", class: "semq-benchmark-explorer__tick" });
      label.textContent = String(tick);
      chart.append(label);
    }
    const axis = svgElement("text", { x: (PLOT.left + xRight) / 2, y: HEIGHT - 9, "text-anchor": "middle", class: "semq-benchmark-explorer__axis" });
    axis.textContent = "Total bits per dimension (codes + model) · log₂ scale";
    chart.append(axis);

    const highlight = key => {
      controls.selection.value = key;
      chart.querySelectorAll(".semq-benchmark-explorer__point").forEach(point => {
        point.classList.toggle("is-selected", point.dataset.method === key);
      });
      const row = rows.find(item => item.key === key);
      if (!row) return;
      showDetail(detail, row);
    };
    for (const row of rows) {
      const label = `${displayName(row.key)}: ${row.bits_per_dim.toFixed(2)} bits per dimension; ${row[metric].toFixed(1)}% ${metricName}`;
      const point = svgElement("circle", {
        cx: x(row.bits_per_dim), cy: y(row[metric]), r: 6,
        class: `semq-benchmark-explorer__point ${row.key.startsWith("semq_") ? "is-semq" : "is-comparison"}`,
        tabindex: "0", role: "button", "aria-label": label
      });
      point.dataset.method = row.key;
      const title = svgElement("title");
      title.textContent = label;
      point.append(title);
      point.addEventListener("mouseenter", () => highlight(row.key));
      point.addEventListener("focus", () => highlight(row.key));
      point.addEventListener("click", () => { controls.selection.value = row.key; highlight(row.key); });
      point.addEventListener("keydown", event => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          controls.selection.value = row.key;
          highlight(row.key);
        }
      });
      chart.append(point);
    }
    const defaultKey = rows.some(row => row.key === selectedKey) ? selectedKey :
      rows.some(row => row.key === "semq_quant4") ? "semq_quant4" : rows[0]?.key;
    controls.selection.value = defaultKey;
    if (defaultKey) highlight(defaultKey);
  }

  async function init(root) {
    if (root.dataset.ready) return;
    root.dataset.ready = "true";
    const status = root.querySelector(".semq-benchmark-explorer__status");
    try {
      const response = await fetch(new URL(root.dataset.source, document.baseURI));
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (!data.results?.table?.e5_small?.scifact?.methods) throw new Error("Unexpected benchmark data");
      const controls = {
        model: makeSelect("Embedding model", Object.entries(MODEL_NAMES), "e5_small"),
        dataset: makeSelect("Dataset", [["scifact", "SciFact"], ["fiqa", "FiQA"]], "scifact"),
        metric: makeSelect("Quality metric", [["ndcg10_retained_pct", "nDCG@10 relative to FP32"], ["overlap10", "Top-10 overlap with FP32"]], "ndcg10_retained_pct"),
        filter: makeSelect("Methods", [["all", "All measured formats"], ["semq", "SEMQ only"], ["comparison", "Comparisons only"]], "all"),
        selection: makeSelect("Highlight format", [], "")
      };
      const form = node("div", "semq-benchmark-explorer__controls");
      for (const control of Object.values(controls)) form.append(control.wrap);
      const chart = svgElement("svg", { viewBox: `0 0 ${WIDTH} ${HEIGHT}`, role: "group", class: "semq-benchmark-explorer__chart" });
      const detail = node("div", "semq-benchmark-explorer__detail");
      const legend = node("p", "semq-benchmark-explorer__legend");
      for (const [name, label] of [["semq", "SEMQ"], ["comparison", "Comparison"], ["reference", "FP32 reference"]]) {
        legend.append(node("span", `is-${name}`, label));
      }
      root.replaceChildren(form, chart, detail, legend);
      const selects = Object.fromEntries(Object.entries(controls).map(([key, item]) => [key, item.select]));
      for (const [key, control] of Object.entries(controls)) {
        control.select.addEventListener("change", () => {
          if (key === "selection") {
            chart.querySelectorAll(".semq-benchmark-explorer__point").forEach(point => {
              point.classList.toggle("is-selected", point.dataset.method === selects.selection.value);
            });
            const selected = measuredRows(data, selects.model.value, selects.dataset.value, selects.filter.value)
              .find(row => row.key === selects.selection.value);
            if (selected) showDetail(detail, selected);
          } else draw(data, selects, chart, detail);
        });
      }
      draw(data, selects, chart, detail);
    } catch (error) {
      status.textContent = "Interactive chart unavailable. Use the linked JSON for exact measurements and provenance.";
    }
  }

  function start() {
    document.querySelectorAll("[data-semq-benchmark-explorer]").forEach(init);
  }
  if (typeof document$ !== "undefined") document$.subscribe(start);
  else if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
