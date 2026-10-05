---
description: Turn float32 embeddings into verifiable vector states. Compare rebuilds by id and gate unexpected changes.
search:
  boost: 2
hide:
  - toc
  - navigation
---

<div class="semq-home">
  <section class="semq-hero" aria-labelledby="semq-hero-title">
    <div class="semq-hero__copy">
      <p class="semq-eyebrow">SEMQ / SDK DOCUMENTATION</p>
      <h1 id="semq-hero-title">Inspect changes between embedding rebuilds.</h1>
      <p class="semq-lead">Encode unit-norm float32 vectors as deterministic symbolic rows. Save a <code>.semq</code> state, compare versions by id, and gate changes against variation measured in your pipeline. A hash of the floats says whether the bytes changed; SEMQ says whether the state did, and where.</p>
      <div class="semq-actions">
        <a class="md-button md-button--primary" href="quickstart/">Run the quickstart <span aria-hidden="true">→</span></a>
        <a class="md-button" href="reference/contracts/">Read the contracts</a>
      </div>
      <p class="semq-hero__note">C core <span aria-hidden="true">/</span> Python · Rust · Go · TypeScript/WASM <span aria-hidden="true">/</span> <a href="benchmarks/scale/">Cross-platform bytes</a></p>
    </div>
    <figure class="semq-hero__figure" aria-label="Schematic transition from continuous coordinates to a discrete symbolic state">
      <div class="semq-hero__visual" data-geometry>
        <img class="semq-hero__fallback" src="assets/images/state-field.svg" alt="" width="520" height="340">
        <canvas class="semq-hero__canvas" width="520" height="340" aria-hidden="true"></canvas>
      </div>
    </figure>
  </section>

  <section class="semq-section semq-demo" data-semq-demo aria-labelledby="semq-demo-title">
    <div class="semq-section-heading">
      <div>
        <p class="semq-eyebrow">INTERACTIVE EXAMPLE / 01</p>
        <h2 id="semq-demo-title">Same corpus. What moved?</h2>
        <p>Switch the candidate to see how a state diff separates unchanged rows, changed symbols, and new ids.</p>
      </div>
      <a class="semq-text-link" href="concepts/#diff-and-floor">How diff works <span aria-hidden="true">→</span></a>
    </div>
    <div class="semq-switches" role="group" aria-label="Candidate scenario">
      <button type="button" class="semq-switch is-active" data-scenario="same" aria-pressed="true">No change</button>
      <button type="button" class="semq-switch" data-scenario="changed" aria-pressed="false">One row changed</button>
      <button type="button" class="semq-switch" data-scenario="added" aria-pressed="false">One id added</button>
    </div>
    <div class="semq-comparison">
      <div class="semq-state-card">
        <div class="semq-state-card__top"><span>REFERENCE</span><code>55d5acf0caf9…</code></div>
        <div class="semq-row"><span>101</span><code>b6 0d</code><i aria-label="unchanged">=</i></div>
        <div class="semq-row"><span>102</span><code>b2 0d</code><i aria-label="unchanged">=</i></div>
        <div class="semq-row"><span>103</span><code>96 0d</code><i aria-label="unchanged">=</i></div>
      </div>
      <div class="semq-compare-arrow" aria-hidden="true">→</div>
      <div class="semq-state-card">
        <div class="semq-state-card__top"><span>CANDIDATE</span><code data-candidate-id>55d5acf0caf9…</code></div>
        <div data-candidate-rows>
          <div class="semq-row"><span>101</span><code>b6 0d</code><i aria-label="unchanged">=</i></div>
          <div class="semq-row"><span>102</span><code>b2 0d</code><i aria-label="unchanged">=</i></div>
          <div class="semq-row"><span>103</span><code>96 0d</code><i aria-label="unchanged">=</i></div>
        </div>
      </div>
    </div>
    <div class="semq-result" role="status" aria-live="polite" aria-atomic="true">
      <span class="semq-result__mark" data-result-mark aria-hidden="true">=</span>
      <div><strong data-result-title>Identical states</strong><p data-result-detail>0 changed · 0 added · 0 removed. The state ids match.</p></div>
    </div>
    <p class="semq-demo__caption">A fixed walkthrough of actual <code>quant(dim=4, bins=4)</code> output. The controls select precomputed results; encoding runs in the SDK, not in this page. <a href="quickstart/">Run the same example yourself.</a></p>
  </section>

  <section class="semq-section" aria-labelledby="semq-flow-title">
    <div class="semq-section-heading"><div><p class="semq-eyebrow">WORKFLOW / 02</p><h2 id="semq-flow-title">From vectors to a verdict.</h2></div></div>
    <div class="semq-steps">
      <div class="semq-step"><span class="semq-step__number">01</span><h3>Encode a state</h3><p>Give SEMQ unit-norm float32 vectors, stable ids, a codec rule, and a manifest. Save the result as <code>.semq</code>.</p><a href="quickstart/">Run the quickstart →</a></div>
      <div class="semq-step"><span class="semq-step__number">02</span><h3>Measure normal variation</h3><p>Compare rebuilds that changed nothing on purpose. A <code>Floor</code> captures the variation you actually observed.</p><a href="guides/gate-a-rebuild/">Measure a floor →</a></div>
      <div class="semq-step"><span class="semq-step__number">03</span><h3>Gate the candidate</h3><p>Diff by id to find changed symbolic rows. Use <code>within</code> for the gate and inspect the changes when it fails.</p><a href="reference/cli/">See CLI commands →</a></div>
    </div>
  </section>

  <section class="semq-section" aria-labelledby="semq-paths-title">
    <div class="semq-section-heading"><div><p class="semq-eyebrow">DOCUMENTATION MAP / 03</p><h2 id="semq-paths-title">Choose what you need.</h2></div></div>
    <div class="semq-paths">
      <a href="quickstart/"><span>LEARN</span><strong>Run the quickstart</strong><small>A runnable tutorial in four languages.</small><b aria-hidden="true">↗</b></a>
      <a href="guides/"><span>DO</span><strong>Solve a task</strong><small>Gate a rebuild or choose a codec.</small><b aria-hidden="true">↗</b></a>
      <a href="concepts/"><span>UNDERSTAND</span><strong>Understand the model</strong><small>Identities, manifests, diffs, and floors.</small><b aria-hidden="true">↗</b></a>
      <a href="reference/"><span>LOOK UP</span><strong>Check the contract</strong><small>APIs, CLI, bytes, and error rules.</small><b aria-hidden="true">↗</b></a>
    </div>
  </section>

</div>
