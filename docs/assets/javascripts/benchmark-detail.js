/* One explorer for the six frozen, verified retrieval reports. */
(() => {
  const NS = "http://www.w3.org/2000/svg";
  const W = 760, H = 410;
  const M = { left: 67, right: 22, top: 22, bottom: 56 };
  const MODELS = {
    "intfloat/e5-small-v2": "e5-small-v2 · 384 dimensions",
    "Snowflake/snowflake-arctic-embed-m-v1.5": "snowflake-arctic-embed-m-v1.5 · 768 dimensions",
    "mixedbread-ai/mxbai-embed-large-v1": "mxbai-embed-large-v1 · 1024 dimensions"
  };
  const PROFILES = [
    ["direction_scoring", "Normalized direction · cosine"],
    ["quality", "Raw reconstruction · inner product"],
    ["method_scoring", "Native estimator"]
  ];
  const METRICS = [
    ["ndcg", "nDCG@10"], ["overlap", "Top-10 overlap with FP32"],
    ["delta", "Δ nDCG@10 versus FP32"]
  ];

  function element(name, className, text) {
    const value = document.createElement(name);
    value.className = className;
    if (text !== undefined) value.textContent = text;
    return value;
  }

  function svg(name, attrs = {}) {
    const value = document.createElementNS(NS, name);
    for (const [key, item] of Object.entries(attrs)) value.setAttribute(key, String(item));
    return value;
  }

  function select(label, options, current) {
    const wrap = element("label", "semq-benchmark-explorer__control");
    wrap.append(element("span", "", label));
    const input = document.createElement("select");
    for (const [key, title] of options) {
      const option = document.createElement("option");
      option.value = key;
      option.textContent = title;
      input.append(option);
    }
    input.value = current;
    wrap.append(input);
    return { wrap, input };
  }

  function methodName(method) {
    const name = method.method.name;
    if (name === "semq_quant") return `SEMQ quant · ${method.method.bits} bits`;
    if (name === "semq_phase") return `SEMQ phase · ${method.method.sectors} sectors`;
    if (name === "semq_orbit") return `SEMQ orbit · scale ${method.method.scale}`;
    return method.id.replaceAll("_", " ").replace(/\b[a-z]/g, c => c.toUpperCase());
  }

  function score(method, profile) {
    const section = method[profile];
    if (section.status !== "measured") return null;
    const quality = profile === "quality" ? section : section.quality;
    const result = quality?.retrieval?.["10"];
    return result?.ndcg_status === "measured" ? result : null;
  }

  function measured(methods, profile, metric, group) {
    return methods.map(method => ({ method, result: score(method, profile) }))
      .filter(({ method, result }) => result &&
        (group === "all" || method.id.startsWith("semq_") === (group === "semq")))
      .map(({ method, result }) => ({
        method, result,
        bits: method.storage.effective_bits_per_dimension,
        value: (metric === "delta" ? result.ndcg_delta : result[metric]) * 100,
        interval: result.ndcg_delta_interval
      }));
  }

  function showDetail(container, item) {
    const storage = item.method.storage;
    const interval = item.interval?.status === "measured"
      ? ` · 95% paired interval [${item.interval.lower.toFixed(4)}, ${item.interval.upper.toFixed(4)}]`
      : "";
    container.replaceChildren(
      element("strong", "", methodName(item.method)),
      element("span", "", `${storage.effective_bits_per_dimension.toFixed(3)} total bits/dim ` +
        `(${storage.code_bits_per_dimension.toFixed(3)} code + ${storage.model_bits_per_dimension.toFixed(3)} model) · ` +
        `nDCG@10 ${item.result.ndcg.toFixed(4)} · overlap ${item.result.overlap.toFixed(3)} · ` +
        `Δ nDCG ${item.result.ndcg_delta.toFixed(4)}${interval}`)
    );
  }

  function draw(report, controls, chart, detail) {
    const profile = controls.profile.value;
    const metric = controls.metric.value;
    const rows = measured(report.methods, profile, metric, controls.group.value);
    const previous = controls.method.value;
    controls.method.replaceChildren();
    for (const row of [...rows].sort((a, b) => a.bits - b.bits || methodName(a.method).localeCompare(methodName(b.method)))) {
      const option = document.createElement("option");
      option.value = row.method.id;
      option.textContent = methodName(row.method);
      controls.method.append(option);
    }
    chart.replaceChildren();
    if (!rows.length) {
      detail.textContent = "No measured result for this combination.";
      return;
    }
    const values = rows.flatMap(row => metric === "delta" && row.interval?.status === "measured"
      ? [row.value, row.interval.lower * 100, row.interval.upper * 100] : [row.value]);
    const low = Math.floor((Math.min(...values) - (metric === "delta" ? 1 : 2)) / 5) * 5;
    const high = Math.ceil((Math.max(...values) + (metric === "delta" ? 1 : 2)) / 5) * 5;
    const bottom = H - M.bottom, right = W - M.right;
    const x = bits => M.left + Math.log2(bits) / 5 * (right - M.left);
    const y = value => bottom - (value - low) / (high - low) * (bottom - M.top);
    const title = METRICS.find(([key]) => key === metric)[1];
    chart.setAttribute("aria-label", `${title} versus total bits per dimension`);
    for (let tick = low; tick <= high; tick += 5) {
      chart.append(svg("line", { x1: M.left, x2: right, y1: y(tick), y2: y(tick), class: "semq-benchmark-explorer__grid" }));
      const text = svg("text", { x: M.left - 9, y: y(tick) + 4, "text-anchor": "end", class: "semq-benchmark-explorer__tick" });
      text.textContent = `${tick}${metric === "delta" ? " pp" : "%"}`;
      chart.append(text);
    }
    if (metric === "delta" && low <= 0 && high >= 0) {
      chart.append(svg("line", { x1: M.left, x2: right, y1: y(0), y2: y(0), class: "semq-benchmark-explorer__reference" }));
    }
    for (const tick of [1, 2, 4, 8, 16, 32]) {
      const text = svg("text", { x: x(tick), y: bottom + 23, "text-anchor": "middle", class: "semq-benchmark-explorer__tick" });
      text.textContent = String(tick);
      chart.append(text);
    }
    const axis = svg("text", { x: (M.left + right) / 2, y: H - 9, "text-anchor": "middle", class: "semq-benchmark-explorer__axis" });
    axis.textContent = "Total bits per dimension (code + model) · log₂ scale";
    chart.append(axis);
    const highlight = id => {
      controls.method.value = id;
      chart.querySelectorAll(".semq-benchmark-explorer__point").forEach(point =>
        point.classList.toggle("is-selected", point.dataset.method === id));
      const selected = rows.find(row => row.method.id === id);
      if (selected) showDetail(detail, selected);
    };
    for (const row of rows) {
      if (metric === "delta" && row.interval?.status === "measured") {
        chart.append(svg("line", {
          x1: x(row.bits), x2: x(row.bits),
          y1: y(row.interval.lower * 100), y2: y(row.interval.upper * 100),
          class: "semq-detail-explorer__interval"
        }));
      }
      const label = `${methodName(row.method)}: ${row.bits.toFixed(3)} total bits per dimension; ${row.value.toFixed(2)} ${metric === "delta" ? "nDCG points" : "percent"}`;
      const point = svg("circle", {
        cx: x(row.bits), cy: y(row.value), r: 6, tabindex: 0, role: "button",
        "aria-label": label,
        class: `semq-benchmark-explorer__point ${row.method.id.startsWith("semq_") ? "is-semq" : "is-comparison"}`
      });
      point.dataset.method = row.method.id;
      const tooltip = svg("title");
      tooltip.textContent = label;
      point.append(tooltip);
      point.addEventListener("mouseenter", () => highlight(row.method.id));
      point.addEventListener("focus", () => highlight(row.method.id));
      point.addEventListener("click", () => highlight(row.method.id));
      point.addEventListener("keydown", event => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          highlight(row.method.id);
        }
      });
      chart.append(point);
    }
    highlight(rows.some(row => row.method.id === previous) ? previous :
      rows.some(row => row.method.id === "semq_quant4") ? "semq_quant4" : rows[0].method.id);
  }

  async function init(root) {
    if (root.dataset.ready) return;
    root.dataset.ready = "true";
    const status = root.querySelector("[role=status]");
    try {
      const files = JSON.parse(root.dataset.files);
      const reports = await Promise.all(files.map(async filename => {
        const response = await fetch(new URL(`../../assets/benchmarks/${filename}`, document.baseURI));
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return { filename, data: await response.json() };
      }));
      const byRun = new Map(reports.map(item => {
        const prep = item.data.dataset.preparation;
        return [`${prep.dataset}|${prep.model.repo}`, item];
      }));
      const datasets = [...new Set(reports.map(item => item.data.dataset.preparation.dataset))].sort();
      const models = [...new Set(reports.map(item => item.data.dataset.preparation.model.repo))]
        .sort((a, b) => (MODELS[a] || a).localeCompare(MODELS[b] || b));
      const controls = {
        dataset: select("Dataset", datasets.map(key => [key, key === "scifact" ? "SciFact" : "FiQA"]), "scifact"),
        model: select("Embedding model", models.map(key => [key, MODELS[key] || key]), models.find(key => key.includes("e5-small")) || models[0]),
        profile: select("Scoring profile", PROFILES, "direction_scoring"),
        metric: select("Metric", METRICS, "delta"),
        group: select("Methods", [["all", "All measured formats"], ["semq", "SEMQ only"], ["comparison", "Comparisons only"]], "all"),
        method: select("Highlight format", [], "")
      };
      const form = element("div", "semq-benchmark-explorer__controls");
      for (const control of Object.values(controls)) form.append(control.wrap);
      const chart = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "group", class: "semq-benchmark-explorer__chart" });
      const detail = element("div", "semq-benchmark-explorer__detail");
      const source = element("p", "semq-detail-explorer__source");
      const link = element("a", "", "Download selected report and provenance");
      source.append(link);
      const note = element("p", "semq-size-explorer__note", "Whiskers show 95% paired query-bootstrap intervals for Δ nDCG; they do not include model or dataset variability.");
      root.replaceChildren(form, chart, detail, note, source);
      const inputs = Object.fromEntries(Object.entries(controls).map(([key, control]) => [key, control.input]));
      const render = () => {
        const selected = byRun.get(`${inputs.dataset.value}|${inputs.model.value}`);
        if (!selected) {
          detail.textContent = "This dataset and model combination was not measured.";
          chart.replaceChildren();
          source.hidden = true;
          return;
        }
        source.hidden = false;
        link.href = `../../assets/benchmarks/${selected.filename}`;
        draw(selected.data, inputs, chart, detail);
      };
      for (const [key, control] of Object.entries(controls)) {
        control.input.addEventListener("change", () => {
          if (key === "method") {
            chart.querySelectorAll(".semq-benchmark-explorer__point").forEach(point =>
              point.classList.toggle("is-selected", point.dataset.method === inputs.method.value));
            const selected = byRun.get(`${inputs.dataset.value}|${inputs.model.value}`);
            const row = measured(selected.data.methods, inputs.profile.value, inputs.metric.value, inputs.group.value)
              .find(item => item.method.id === inputs.method.value);
            if (row) showDetail(detail, row);
          } else render();
        });
      }
      render();
    } catch (error) {
      status.textContent = "Interactive report unavailable. Download the frozen reports from the repository.";
    }
  }

  function start() {
    document.querySelectorAll("[data-semq-detail-explorer]").forEach(init);
  }
  if (typeof document$ !== "undefined") document$.subscribe(start);
  else if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
