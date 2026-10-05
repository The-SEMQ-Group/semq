# SDK benchmarks

One SDK-owned evaluation suite for SEMQ and external methods. This developer
package is not shipped in the SDK wheel and adds no runtime dependencies.

Start with the [benchmark protocol](../docs/guides/benchmark-protocol.md): it
specifies setup, input data, metric definitions, output contracts, and limits.
Use [SciFact and FiQA](../docs/guides/benchmark-datasets.md) for full-corpus,
labeled evaluations with pinned models and source revisions.
The [cost evaluation guide](../docs/guides/cost-evaluation.md) defines the optional
economic layer. It uses declared effective tariffs and never fetches prices.

| Location | Responsibility |
| --- | --- |
| `configs/` | Versioned, explicit workload and method configurations |
| `codecs.py` | Storage/reconstruction adapters, including native SEMQ and optional Faiss |
| `faiss_codecs.py` | Optional SQ, OPQ, RaBitQ and TurboQuant MSE adapters with persisted models and upstream scoring |
| `prepare_beir.py` | Pinned public sources, model inference, stable IDs and embedding provenance |
| `inputs.py` | Download exact versioned inputs and verify sizes and hashes before use |
| `relevance.py` | Sparse relevance validation and ranking evaluation |
| `metrics.py` | Pure ranking, quality, storage, and latency-summary definitions |
| `costs.py` | Explicit economic scenarios, tariff provenance, missing-input and requirement checks |
| `render.py` | Readable Markdown tables that preserve scoring profiles and unavailable metrics |
| `verify_ndcg.py` | Independent trec_eval check of FP32 per-query nDCG |
| `publish.py` | Verified compact reports and a generated MkDocs results page |
| `compare.py` | Compatible-run comparisons and informational change summaries |
| `../docs/assets/benchmarks/` | Versioned public reports without embeddings or per-query arrays |
| `../docs/assets/benchmarks/summary/` | The results behind the benchmark pages, one file per page section |
| `run.py` | Input validation, bounded query batches, provenance, and immutable run directories |
| `tests/` | Hand-checkable metrics, conversion boundaries, native agreement, and report semantics |
| `results/`, `data/` | Ignored local run artifacts and datasets |

The `codec_quality` workload measures reconstruction, ranking agreement and
storage. Optional method scoring is reported separately from reconstruction-based
scoring. Search latency, process memory and cross-runtime portability are not
measured by this workload. External methods use adapters to identified
implementations and optional benchmark dependencies.

CI validates tests, formatting and types on pull requests and pushes to `main`.
Only pushes to `main` run synthetic quality and illustrative cost scenarios,
with readable job summaries. JSON reports are retained as
workflow artifacts for 30 days. Quality and storage changes against the previous
successful `main` evaluation appear in the job summary; incompatible inputs,
protocols or environments are reported explicitly. There is no timing gate or
periodic schedule. Synthetic checks validate the benchmark machinery, not
production quality or cost savings.

Public-dataset evaluations are run explicitly from a clean checkout. See the
[publication instructions](../docs/guides/benchmark-datasets.md#4-verify-and-publish)
and [frozen results](../docs/guides/benchmark-results.md). CI checks that the
results page matches the versioned JSON reports; it does not refresh public
numbers automatically.
