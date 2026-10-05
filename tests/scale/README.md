# Scale tests

This opt-in suite exercises larger corpora and SIMD backend agreement. Keep its
workload-specific thresholds separate from application performance claims.

## Prerequisites

Install the checkout's Python SDK and test dependencies. The tests allocate up
to one million vectors and can take minutes; run on an otherwise idle machine
with enough memory for the corpus and its codes.

RSS measurements use `ps` on Linux/macOS. The helper returns zero on other
platforms, so those runs do not validate RSS growth.

## Run the suite

From the repository root:

```sh
python -m pytest tests/scale/ -m slow -v
```

For one workload:

```sh
python -m pytest tests/scale/test_encode_scaling.py -m slow -v -s
```

[pyproject.toml](../../pyproject.toml) excludes this directory from ordinary test
discovery. Naming the directory explicitly selects it; `-m slow` selects the
registered marker.

## Workloads and assertions

| Test file | What it checks |
| --- | --- |
| [test_encode_scaling.py](test_encode_scaling.py) | Encoding throughput from 10,000 to 1,000,000 rows; the largest case must retain at least one fifth of the smallest case's per-vector throughput. |
| [test_simd_differential_fuzz.py](test_simd_differential_fuzz.py) | Available SIMD backends match scalar fingerprints over adversarial input bundles. |

The assertions in the linked tests are authoritative. Timing thresholds are
regression checks for these workloads, not throughput guarantees for arbitrary
hardware or customer data.

## Read the output

Tests that record measurements write JSON to `tests/scale/results/`. A later
run overwrites the matching report. [conftest.py](conftest.py) adds Python,
OS, architecture, and recording time to each report.

The measurement helper records elapsed time and RSS before/after a block;
this is **not peak RSS**. Compare runs only after checking workload settings
and hardware.

## Related documentation

- [Contributor guide](../../CONTRIBUTING.md).
- [Conformance vectors](../conformance/README.md).
- [Docker architecture checks](../integration/cross_platform/README.md).
