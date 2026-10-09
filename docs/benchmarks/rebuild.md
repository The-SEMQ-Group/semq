---
title: Rebuild detection
---

# Rebuild detection

Re-embed the same corpus and SEMQ should stay quiet; change the model, the precision or the input and it should fail the gate, naming the rows that moved. These runs test that on 5,183 SciFact documents.

## Rebuild gate

A second encoding of 5,183 SciFact documents with `e5-small-v2`. The floor comes from three unchanged rebuilds; each candidate is compared with the same reference state. Bar length shows the share of rows with different symbols. The verdict also considers the floor and manifest.

<div class="semq-scenarios">
<div class="semq-scenario is-pass">
<div class="semq-scenario__head"><strong>GPU rebuild, different batch size</strong><span>0.10% · within floor</span></div>
<div class="semq-scenario__track"><span style="width:0.10%;min-width:2px"></span></div>
</div>
<div class="semq-scenario is-pass">
<div class="semq-scenario__head"><strong>CPU rebuild, one document per batch</strong><span>0.02% · within floor</span></div>
<div class="semq-scenario__track"><span style="width:0.02%;min-width:2px"></span></div>
</div>
<div class="semq-scenario is-fail">
<div class="semq-scenario__head"><strong>Previous encoder revision</strong><span>100% · outside floor</span></div>
<div class="semq-scenario__track"><span style="width:100.00%;min-width:2px"></span></div>
</div>
<div class="semq-scenario is-fail">
<div class="semq-scenario__head"><strong>Half precision</strong><span>51.0% · outside floor</span></div>
<div class="semq-scenario__track"><span style="width:50.96%;min-width:2px"></span></div>
</div>
<div class="semq-scenario is-fail">
<div class="semq-scenario__head"><strong>128-token truncation</strong><span>98.1% · outside floor</span></div>
<div class="semq-scenario__track"><span style="width:98.05%;min-width:2px"></span></div>
</div>
<div class="semq-scenario is-fail">
<div class="semq-scenario__head"><strong>CLS instead of mean pooling</strong><span>100% · outside floor</span></div>
<div class="semq-scenario__track"><span style="width:100.00%;min-width:2px"></span></div>
</div>
<div class="semq-scenario is-pass">
<div class="semq-scenario__head"><strong>Normalization moved after the model</strong><span>0% · within floor</span></div>
<div class="semq-scenario__track"><span style="width:0.00%;min-width:0px"></span></div>
</div>
</div>

The observed floor for quant with four bins was 5 of 5,183 rows and a hamming bound of 1, measured from 3 unchanged rebuilds. One corpus and model family cannot establish a general noise floor.

[Full rebuild measurements](../assets/benchmarks/summary/rebuild.json) · [Run the gate yourself](../guides/gate-a-rebuild.md)

## Why not something simpler?

The same runs checked with the tools a pipeline already has. A false alarm is a rebuild that changed nothing flagged as changed; a miss is a real change that passes.

| Check | False alarms on rebuilds | Real changes missed |
| --- | ---: | ---: |
| Hash of the FP32 bytes | 5 of 5 | 0 of 4 |
| `np.allclose`, default tolerances | 5 of 5 | 0 of 4 |
| Any row with cosine below 0.9999 | 0 of 5 | 1 of 4 (the precision) |
| Largest absolute difference, calibrated on the nulls | 0 of 5 | 0 of 4 |
| SEMQ diff against its floor | 0 of 5 | 0 of 4 |

Hashing the floats fails on every rebuild because GPUs and batch sizes change the last bits. A cosine threshold that ignores that noise also ignores a switch to half precision. A threshold on the largest difference can work, but it has to be calibrated on your own rebuilds, which is what the floor does, and it cannot say which rows moved.

??? note "What the experiment does and does not show"

    - What moves rows is the device, not the batch size: the three GPU runs flip the same few rows, and CPU runs with different batch sizes flip none. The held-out rebuild therefore resembles two of the floor's nulls.
    - Normalizing after the model instead of inside it moves no coordinate by more than 3e-8; every check except the float hash treats it as unchanged, and it is not counted as a real change above.
    - The previous model revision also changes the manifest, which alone fails the gate. It is caught by its rows too: scored with an unchanged manifest, as a pipeline that forgot to update it would, it still changes 100% of rows.
    - One corpus and one model family; the floor is an envelope of what was observed here, not a prediction for other pipelines.

Source: [`rebuild.json`](../assets/benchmarks/summary/rebuild.json), produced by `python -m benchmarks.rebuild`.

## False alarms and detection power

A larger pool: 28 rebuilds of the same corpus that change only the device, the batch size and the input order. Every rebuild gave different floats from the reference, but there were only 2 SEMQ states: 24 Apple GPU (MPS) rebuilds gave one state, with 5 rows changed (hamming at most 1); 4 CPU rebuilds gave the reference state.

Each of 2,000 draws holds out one rebuild, measures a floor from N of the others, and judges the held-out rebuild, then the same rebuild with one fault. Calibrated float checks take their threshold from the same N rebuilds. Intervals are 95% Clopper–Pearson.

### False alarms, 20 rebuilds in the floor

| Check | False alarms | 95% interval |
| --- | ---: | ---: |
| SEMQ floor, `within` | 0% | 0%–0.18% |
| SEMQ floor, per-row | 0% | 0%–0.18% |
| Largest absolute difference, calibrated | 0% | 0%–0.18% |
| Lowest row cosine, calibrated | 0% | 0%–0.18% |
| Hash of the FP32 bytes | 100% | 99.8%–100% |
| `np.allclose`, default tolerances | 100% | 99.8%–100% |
| Fixed tolerance of one bfloat16 spacing | 100% | 99.8%–100% |

### Detection, 20 rebuilds in the floor

Size is the median 1 − cosine between a changed row and the same row before the fault.

| Fault | Size | Floor, `within` | Floor, per-row | Largest difference, calibrated | Cosine, calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| Replace 1 document | 1.9e-01 | 100% | 100% | 100% | 100% |
| Replace 2 documents | 1.9e-01 | 100% | 100% | 100% | 100% |
| Replace 10 documents | 1.9e-01 | 100% | 100% | 100% | 100% |
| Cut the last 2% of one document | 1.4e-03 | 87.8% | 87.8% | 87.8% | 87.8% |
| Cut the last 10% of one document | 2.9e-03 | 96.0% | 96.0% | 96.0% | 96.0% |
| Cut the last 50% of one document | 1.5e-02 | 100% | 100% | 100% | 100% |
| Swap 1 word in one document | 7.6e-04 | 97.6% | 97.6% | 97.8% | 97.8% |
| Swap 3 words in one document | 3.3e-03 | 100% | 100% | 100% | 100% |
| Noise on every coordinate, 1× rebuild noise | 2.4e-14 | 39.6% | 39.6% | 43.1% | 54.2% |
| Noise on every coordinate, 4× rebuild noise | 3.7e-13 | 32.4% | 32.4% | 46.4% | 78.0% |
| Scale 1% of coordinates by 1 + 1e-4 | 4.0e-11 | 81.7% | 81.7% | 100% | 100% |
| Scale 1% of coordinates by 1 + 1e-3 | 4.0e-09 | 100% | 100% | 100% | 100% |
| Scale 10% of coordinates by 1 + 1e-4 | 4.3e-10 | 100% | 100% | 100% | 100% |

On content faults the floor and the calibrated float checks agree. In documents longer than the model's 512-token limit, a cut removes only text the model never reads, so that fault is not always a change. The numeric faults move rows by less than a quantization bin: the floor sees them only when a coordinate crosses a bin edge, while a calibrated float check sees any change above the rebuild noise.

### When the rebuild noise varies (synthetic)

The real rebuilds above gave one state per device, so the floor had nothing to vary. To see what happens when every rebuild differs, this pool is synthetic: each of its 40 nulls is an Apple GPU (MPS) rebuild plus Gaussian noise (σ = 4.5e-6 per coordinate), renormalized. Each changes 223 to 281 rows. The bound is the worst case for nulls produced the same way as the candidate.

| Nulls in the floor | `within` | Bound | Per-row | Bound |
| ---: | ---: | ---: | ---: | ---: |
| 3 | 27.6% | 50.0% | 29.9% | 75.0% |
| 5 | 18.8% | 33.3% | 21.3% | 50.0% |
| 10 | 10.3% | 18.2% | 13.0% | 27.3% |
| 20 | 5.9% | 9.5% | 8.6% | 14.3% |
| 39 | 3.2% | 5.0% | 5.9% | 7.5% |

A few replaced documents hide in that noise for `within`, which looks at the changed share and the p99 hamming. The per-row check catches them:

| Fault | SEMQ floor, `within` | SEMQ floor, per-row | Largest absolute difference, calibrated | Lowest row cosine, calibrated |
| --- | ---: | ---: | ---: | ---: |
| Replace 1 document | 5.9% | 100% | 100% | 100% |
| Replace 2 documents | 9.8% | 100% | 100% | 100% |

??? note "What the experiment does and does not show"

    - One corpus and one model. The pool varies the device, the batch size and the input order, nothing else.
    - The varying pool is synthetic. Real rebuilds here gave one state per device.
    - A float check calibrated on the same rebuilds as the floor matches it on content faults and wins on numeric faults below the bin width.
    - What SEMQ adds is the names of the rows that changed and a compact reference that any platform reads the same way.
    - Checks with a fixed tolerance reject every rebuild.
    - The draws resample one fixed pool. The intervals describe that pool, not the rebuilds of another pipeline.

Source: [`floor-power.json`](../assets/benchmarks/summary/floor-power.json), produced by `python -m benchmarks.floor_power`.

## Which rows changed?

Edit 1% of the corpus (52 documents cut to their first half and embedded again). Distribution drift, the check embedding monitors use, sees nothing; `diff` returns the 52 ids that changed and no others.

| Documents edited | Centroid distance | Domain classifier AUC | SEMQ diff |
| --- | ---: | ---: | ---: |
| 0.1% (5 rows) | 5.1e-09 · no drift | 0.40 · no drift | 5 ids · recall 1.000 |
| 1% (52 rows) | 4.0e-07 · no drift | 0.41 · no drift | 52 ids · recall 1.000 |
| 5% (259 rows) | 9.8e-06 · no drift | 0.43 · no drift | 258 ids · recall 0.996 |
| 10% (518 rows) | 3.9e-05 · no drift | 0.46 · no drift | 516 ids · recall 0.996 |
| 50% (2,592 rows) | 9.6e-04 · no drift | 0.71 · **drift** | 2,586 ids · recall 0.998 |

Drift checks follow Evidently's defaults (centroid distance with threshold 0.2, a domain classifier with ROC AUC threshold 0.55), re-implemented in numpy. They answer a different question, whether the distribution moved, and they only flag once half the corpus changed. From 5% up a few edited documents encode to the same quantized row as before, so `diff` misses them (recall below 1); it never reports a row that did not change.

Source: [`granularity.json`](../assets/benchmarks/summary/granularity.json), produced by `python -m benchmarks.granularity`.
