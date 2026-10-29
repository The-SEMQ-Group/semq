# Gate a rebuild

**Goal:** decide whether a rebuilt embedding corpus changed more than a
rebuild changes on its own, using a floor measured from null rebuilds.

**Prerequisites:** the Python package installed (it provides the `semq`
command), a reference state, at least three null rebuilds of the same corpus,
and the candidate to judge. All must use the same `CodecConfig` and id kind.

## 1. Produce the states

Encode each corpus with the same configuration and ids, declaring the
encoder in the manifest:

```python
import numpy as np
from semq import Codec

rng = np.random.default_rng(0)
vectors = rng.standard_normal((100, 16)).astype(np.float64)
vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
vectors = vectors.astype(np.float32)
ids = np.arange(100, dtype=np.uint64)
manifest = {"encoder": "example-encoder", "encoder_revision": "1"}

codec = Codec.quant(dim=16, bins=4)
codec.encode(vectors, ids=ids, manifest=manifest).save("reference.semq")

# Null rebuilds: the same corpus through the same encoder, with the noise a
# real rebuild has. Here one coordinate of one row moves slightly in each.
for k, row in enumerate((7, 21, 42), start=1):
    null = vectors.copy()
    null[row, 3] += np.float32(0.02)
    null[row] /= np.linalg.norm(null[row])
    codec.encode(null, ids=ids, manifest=manifest).save(f"null-{k}.semq")

# The candidate to judge: rows 0 and 1 changed direction.
candidate = vectors.copy()
candidate[0] = -candidate[0]
candidate[1] = -candidate[1]
codec.encode(candidate, ids=ids, manifest=manifest).save("candidate.semq")
```

The coordinate perturbations above only make this example runnable. For a CI
gate, produce each null state by independently rebuilding the unchanged corpus
with the same encoder and production settings. Synthetic perturbations do not
establish the rebuild noise floor.

Vary only what a production rebuild may vary. The
[rebuild benchmarks](../benchmarks/rebuild.md) vary the device (CPU or GPU),
the batch size and the input order, and keep the model revision, dtype,
maximum length and pooling fixed. A null that changes one of those widens the
floor by that change, and the gate can then pass it.

## 2. Measure the floor

```sh
semq floor reference.semq null-1.semq null-2.semq null-3.semq > floor.json
cat floor.json
```

`floor.json` records the three counts (`changed_rows`, `total_rows`,
`hamming`: the floor takes the worst ratio and the largest p99 hamming over
the nulls) and where they were measured: the config, the id kind, the
reference's `state_id` and how many nulls went in. The floor applies only to
diffs against that reference; measure a new one when the reference changes.
`semq floor` requires three nulls by default because one null only shows what
that rebuild happened to do; `--min-nulls N` lowers the requirement
explicitly. It exits `2` and prints nothing on stdout when an input is not a
valid null diff (rows added or removed, the encoder keys changed, or a null
of another reference).

## 3. Gate the candidate

```sh
semq diff reference.semq candidate.semq --floor floor.json
echo "exit $?"
```

Exit `0` means the candidate is within the floor. Exit `1` means it is not;
a changed `encoder` or `encoder_revision` is never within. Exit `2` means the
gate could not be evaluated (invalid file, invalid floor, or a floor measured
against another reference, config or id kind).
Changed manifest keys are listed on stderr; the verdict is computed by the core. Add `--json` for
the complete report; without `--floor`, `semq diff` is a report and always
exits `0`.

The same verdict is available in code:

```python
from semq import Encoding, Floor

reference = Encoding.load("reference.semq")
floor = Floor.measure([reference.diff(Encoding.load(f"null-{k}.semq")) for k in (1, 2, 3)])
floor.save("floor.json")  # the same file `semq floor` writes
print(floor)
diff = reference.diff(Encoding.load("candidate.semq"))
print(diff)
print(diff.within(floor))
print(diff.evaluate(floor).reasons)  # every failed check, not only the first
print(diff.units(0)[:3])  # the first units of row 0 that moved: (unit, before, after)
```

## 4. Check every row

The p99 check ignores the most changed 1% of rows, so a few rows with a
large change can pass. The per-row check also fails the verdict when any
changed row moved more than any row of any null did. It needs a floor
measured for it:

```sh
semq floor reference.semq null-1.semq null-2.semq null-3.semq --per-row > floor-per-row.json
semq diff reference.semq candidate.semq --floor floor-per-row.json --per-row
echo "exit $?"
```

With `--per-row`, `semq floor` also records `max_hamming`, the largest
hamming of any changed row of any null, and `distinct_nulls`, how many of
the nulls were different states (two nulls are the same state when their
candidates have the same `content_digest`). When the gate fails, stderr
lists the rows above `max_hamming`. `semq diff --per-row` exits `2` on a
floor without these keys, such as one from `semq floor` without `--per-row`
or one saved by SEMQ 1.0. SEMQ 1.0 cannot read a floor written with
`--per-row`; a floor written without it reads in every version.

In code:

```python
from semq import Encoding, Floor

reference = Encoding.load("reference.semq")
nulls = [reference.diff(Encoding.load(f"null-{k}.semq")) for k in (1, 2, 3)]
floor = Floor.measure(nulls, per_row=True)
print(floor.max_hamming, floor.distinct_nulls)
verdict = reference.diff(Encoding.load("candidate.semq")).evaluate(floor, per_row=True)
print(verdict.passed, verdict.reasons, verdict.rows)  # the rows above max_hamming
```

### How many nulls

Each check compares one statistic of the candidate with the largest value
of that statistic among the nulls. If an unchanged rebuild
and the `N` nulls are exchangeable (produced the same way, so that any order
of the `N + 1` is equally likely), the unchanged rebuild is above all `N`
nulls with probability at most `1/(N+1)`, so each statistic rejects it with
probability at most `1/(N+1)`. `within` uses two statistics, the changed
ratio and the p99 hamming, so it rejects an unchanged rebuild with
probability at most `2/(N+1)`. The per-row check adds a third, for at most `3/(N+1)`: 75% with 3 nulls, about 14% with 20. In
practice it adds less, because hamming distances are integers and a tie with
the largest null does not fail. When every null rebuild gave the same rows
(`distinct_nulls` is `1`), the rebuild is deterministic: an unchanged
rebuild gives those rows again, so the per-row check adds no false alarm. When the nulls vary, measure the floor
from at least 20 nulls; `semq diff --per-row` prints a warning on stderr
below that, without changing the exit code.

The benchmarks [measure both checks](../benchmarks/rebuild.md#false-alarms-and-detection-power)
on SciFact rebuilds: false alarms against the bounds above, and how often
each check catches a changed document. The false alarms of `within` by the
number of nulls, over 2,000 draws each, with 95% Clopper–Pearson intervals:

| Nulls `N` | Bound `2/(N+1)` | Real rebuilds | Synthetic varying noise |
| ---: | ---: | ---: | ---: |
| 3 | 50% | 8.7% (7.5–10.0%) | 27.1% (25.2–29.1%) |
| 5 | 33% | 2.8% (2.1–3.6%) | 18.4% (16.7–20.1%) |
| 10 | 18% | 0% (0–0.18%) | 10.1% (8.8–11.5%) |
| 20 | 9.5% | 0% (0–0.18%) | 5.5% (4.5–6.5%) |

The real pool is 28 rebuilds of one corpus that changed only the device, the
batch size and the input order; the synthetic pool adds noise so that every
null changes hundreds of rows. The draws resample one pool, so the intervals
describe that pool, not every future rebuild. A count of zero is not a rate
of zero: with 2,000 draws its interval still reaches 0.18%.

For a CI gate, measure the floor from at least 20 null rebuilds. With 3, the
gate failed 8.7% of unchanged real rebuilds; with 10 and with 20, none. With
20 the bound is 9.5% for any exchangeable rebuilds, whatever the noise, and
both pools stayed at or below 5.5%.

## Read a diff

A row's hamming distance is between `0` and the config's `units_per_row`:
`dim` for quant and orbit, `dim / 2` for phase. Counts compare only within one
configuration; divide by `units_per_row` to compare across configurations.

The p99 is a nearest-rank percentile: with `m` changed rows it is the `k`-th
smallest hamming, `k = m - floor(m / 100)`. Below 100 changed rows `k = m`, so
the p99 is the largest hamming of any changed row. The floor's `hamming` is
the largest per-null p99 and its `max_hamming` the largest hamming of any
null row, so `hamming <= max_hamming`. A candidate with fewer than 100 changed
rows that passes `within` therefore also passes the per-row check; per-row
adds information only from 100 changed rows up. The definitions are in the
[core contracts](../reference/contracts.md#floor), and
[`test_floor_checks.py`](https://github.com/The-SEMQ-Group/semq/blob/main/tests/property/test_floor_checks.py)
checks both directions.

Read the changed-row count and the hamming together. In the
[rebuild benchmark](../benchmarks/rebuild.md) (quant with 4 bins, 384
dimensions, 5,183 rows), null rebuilds changed at most 2 rows by 1 symbol.
Half precision changed 2,653 rows with a p99 of 4: many rows, few symbols
each. CLS pooling and 128-token truncation changed 100% and 98% of rows with
p99s of 247 and 183. In the synthetic pool, 2 replaced documents moved 260 and
267 symbols while 241 noisy rows moved 1 or 2. These come from one corpus and
one model: they show the patterns to look for, not thresholds.

## What the verdict means

`within` is true only if the candidate removed no rows, shares at least one
row with the reference, changed no more than the floor's ratio of the shared
rows, its p99 hamming is at most the floor's, and neither `encoder` nor
`encoder_revision` changed. Added rows do not affect it; they are listed so
you can judge them. The floor is an envelope of what you observed, taken
component-wise over the nulls; it does not estimate the probability of the
next rebuild. The bound in step 4 holds only if the nulls and the candidate
are exchangeable: it comes from how you produce them, not from the floor.

## Encode a large corpus in batches

For a corpus that does not fit in memory as one float32 matrix, encode
bounded batches and join the resulting states once with `concat`. Every batch must use the
same config, id kind and manifest, with distinct ids:

```python
import numpy as np
from semq import Codec

codec = Codec.quant(dim=16, bins=4)
manifest = {"encoder": "example-encoder", "encoder_revision": "1"}
ids = np.arange(100, dtype=np.uint64)
vectors = np.zeros((100, 16), dtype=np.float32)
vectors[np.arange(100), np.arange(100) % 16] = 1.0
source_batches = (
    (ids[start:start + 20], vectors[start:start + 20])
    for start in range(0, len(ids), 20)
)
parts = [
    codec.encode(batch_vectors, ids=batch_ids, manifest=manifest)
    for batch_ids, batch_vectors in source_batches
]
state = parts[0].concat(*parts[1:])
state.save("reference.semq")
assert state == codec.encode(vectors, ids=ids, manifest=manifest)
```

The compressed parts still occupy memory until `concat` finishes. The host
may encode batches concurrently with a shared `Codec`; keep the number of
in-flight batches bounded. One `concat` call avoids rebuilding the state and
rehashing it for every batch. The same ids, vectors and manifest produce the
same state as a single `encode` call.

## Next steps

- [CLI reference](../reference/cli.md): every command, option and exit code.
- [Core contracts](../reference/contracts.md): the exact definitions of `diff`, `within`, `evaluate` and `measure`.
