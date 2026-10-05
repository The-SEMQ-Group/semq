/* A fixed, inspectable walkthrough. Values are produced by the SDK's
   quant(dim=4, bins=4) codec; this page does not encode vectors. */
(() => {
  const scenarios = {
    same: {
      stateId: "55d5acf0caf9…",
      rows: [["101", "b6 0d", "same"], ["102", "b2 0d", "same"], ["103", "96 0d", "same"]],
      mark: "=", title: "Identical states",
      detail: "0 changed · 0 added · 0 removed. The state ids match."
    },
    changed: {
      stateId: "60b59322791b…",
      rows: [["101", "b6 0d", "same"], ["102", "3c 09", "changed"], ["103", "96 0d", "same"]],
      mark: "≠", title: "One row changed",
      detail: "id 102 changed by 4 symbols · 0 added · 0 removed. The state id changed."
    },
    added: {
      stateId: "aa5dba3ccd17…",
      rows: [["101", "b6 0d", "same"], ["102", "b2 0d", "same"], ["103", "96 0d", "same"], ["104", "e4 09", "added"]],
      mark: "+", title: "One id added",
      detail: "0 changed · id 104 added · 0 removed. The state id changed."
    }
  };

  function render(root, key) {
    const scenario = scenarios[key];
    if (!scenario) return;
    const container = root.querySelector("[data-candidate-rows]");
    container.replaceChildren(...scenario.rows.map(([id, bytes, status]) => {
      const row = document.createElement("div");
      row.className = `semq-row${status === "same" ? "" : ` is-${status}`}`;
      const idText = document.createElement("span");
      idText.textContent = id;
      const code = document.createElement("code");
      code.textContent = bytes;
      const marker = document.createElement("i");
      marker.textContent = { same: "=", changed: "≠", added: "+" }[status];
      marker.setAttribute("aria-label", { same: "unchanged", changed: "changed", added: "added" }[status]);
      row.append(idText, code, marker);
      return row;
    }));
    root.querySelector("[data-candidate-id]").textContent = scenario.stateId;
    root.querySelector("[data-result-mark]").textContent = scenario.mark;
    root.querySelector("[data-result-title]").textContent = scenario.title;
    root.querySelector("[data-result-detail]").textContent = scenario.detail;
    root.querySelectorAll("[data-scenario]").forEach(button => {
      const active = button.dataset.scenario === key;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  }

  function init() {
    document.querySelectorAll("[data-semq-demo]").forEach(root => {
      if (root.dataset.ready === "true") return;
      root.dataset.ready = "true";
      root.addEventListener("click", event => {
        const button = event.target.closest("[data-scenario]");
        if (button && root.contains(button)) render(root, button.dataset.scenario);
      });
    });
  }

  if (typeof document$ !== "undefined") document$.subscribe(init);
  else if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
