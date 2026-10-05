# Retrieval quality in detail

Explore frozen evaluations on SciFact and FiQA. Select a dataset, model and scoring profile.
Each point represents one measured format at its **total bits per dimension**,
including stored scales, codebooks and rotations. The source report for the
selected run contains every exact value and method configuration.

**nDCG@10** measures relevance against available judgments; **Overlap@10**
measures preservation of FP32 neighbors. The Δ nDCG interval is a paired
query-bootstrap interval against FP32. An interval crossing zero does not
establish equivalence; these intervals exclude dataset, model and training-seed
variation and have no multiple-comparison correction.

The scoring profiles answer different questions. **Normalized direction** uses
cosine on decoded rows, **raw reconstruction** uses inner products without
renormalization, and **native estimators** use a backend's own scoring. Do not
combine their rankings. No method uses rescoring.


<div class="semq-detail-explorer" data-semq-detail-explorer data-files="[&quot;fiqa-arctic-c606294.json&quot;, &quot;fiqa-e5-c606294.json&quot;, &quot;fiqa-mxbai-c606294.json&quot;, &quot;scifact-arctic-c606294.json&quot;, &quot;scifact-e5-c606294.json&quot;, &quot;scifact-mxbai-c606294.json&quot;]">
  <p role="status">Loading verified reports…</p>
</div>

Exact measurements and provenance in the frozen reports:

[fiqa · snowflake-arctic-embed-m-v1.5](../assets/benchmarks/fiqa-arctic-c606294.json) · [fiqa · e5-small-v2](../assets/benchmarks/fiqa-e5-c606294.json) · [fiqa · mxbai-embed-large-v1](../assets/benchmarks/fiqa-mxbai-c606294.json) · [scifact · snowflake-arctic-embed-m-v1.5](../assets/benchmarks/scifact-arctic-c606294.json) · [scifact · e5-small-v2](../assets/benchmarks/scifact-e5-c606294.json) · [scifact · mxbai-embed-large-v1](../assets/benchmarks/scifact-mxbai-c606294.json)

## What these runs show

- **Sensitivity varies with the inputs:** 2-bit SEMQ quant's mean nDCG difference from FP32 ranges from -0.0681 to -0.0040. These runs do not isolate a cause.

## FP32 baseline check

This sanity check compares FP32 nDCG@10 with pinned model-card values. The model cards do not pin dataset revisions, so a difference is not evidence of a reproduction failure.

<div class="semq-evidence-stats">
<div><strong>37.47 / 37.43</strong><span>fiqa · e5-small-v2 · this run / model card · <a href="https://huggingface.co/intfloat/e5-small-v2/blob/ffb93f3bd4047442299a41ebb6fa998a38507c52/README.md">source</a></span></div>
<div><strong>68.75 / 68.85</strong><span>scifact · e5-small-v2 · this run / model card · <a href="https://huggingface.co/intfloat/e5-small-v2/blob/ffb93f3bd4047442299a41ebb6fa998a38507c52/README.md">source</a></span></div>
</div>

## Scope and verification

FP32 per-query nDCG was checked against `pytrec-eval-terrier` on identical rankings in both common profiles (absolute tolerance `1e-12`). This checks the shared metric and stored FP32 values, not each codec or the tie policy. Compact reports retain the source revision, input hashes, verification results, storage breakdowns and paired comparisons.

The [benchmark overview](../benchmarks/index.md) covers speed, scale, rebuild variation and cross-platform identity. The [reproduction guide](benchmark-datasets.md) describes the datasets, preprocessing and evaluation commands.
