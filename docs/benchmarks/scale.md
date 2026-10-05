---
title: Scale and portability
---

# Scale and portability

What the state operations cost at a million rows, and whether every platform produces the same bytes. The timings used one arm64 CPU with the `neon` backend and include Python and process memory; they are not a cross-machine speed comparison.

<div class="semq-evidence-stats">
<div><strong>798k</strong><span>quant encodes per second · 768 dimensions</span></div>
<div><strong>49 ms</strong><span>diff · 1M rows, 1% changed</span></div>
<div><strong>1.1 s</strong><span>full gate · 1M rows</span></div>
<div><strong>296 MB</strong><span><code>.semq</code> file · 1M rows</span></div>
</div>

## A million rows

| Operation | Seconds | What is timed |
| --- | ---: | --- |
| concat | 0.195 | Encoding.concat of 10 parts |
| diff | 0.049 | Encoding.diff against a copy with 1 row in 100 changed |
| encode | 1.471 | Codec.encode per chunk plus one Encoding.concat; vector generation excluded |
| floor | 0.015 | Floor.measure over 3 null diffs (diffs built untimed) |
| gate | 1.081 | load reference, three nulls and candidate; diff nulls; Floor.measure; diff candidate; Diff.within |
| load | 0.240 | Encoding.load from a path (file in the OS page cache) |
| save | 0.186 | Encoding.save to a path (atomic write with fsync) |

## The same bytes everywhere

The CI identity fixture encodes 1,000 real SciFact vectors under all five configurations on 4 native host targets and WebAssembly. Each job compares `content_digest`, `state_id` and the saved-file hash with committed values. It tests byte identity, not equal throughput.

[Throughput measurements](../assets/benchmarks/summary/speed.json) · [Scale measurements](../assets/benchmarks/summary/scale.json) · [CI matrix and expected identities](../assets/benchmarks/summary/reproducibility.json)
