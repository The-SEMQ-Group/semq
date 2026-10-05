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
Changed manifest keys are listed on stderr; `within` is computed by the core. Add `--json` for
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
print(diff.units(0)[:3])  # the first units of row 0 that moved: (unit, before, after)
```

## What the verdict means

`within` is true only if the candidate removed no rows, shares at least one
row with the reference, changed no more than the floor's ratio of the shared
rows, its p99 hamming is at most the floor's, and neither `encoder` nor
`encoder_revision` changed. Added rows do not affect it; they are listed so
you can judge them. The floor is an envelope of what you observed, taken
component-wise over the nulls; it does not estimate the probability of the
next rebuild.

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
- [Core contracts](../reference/contracts.md): the exact definitions of `diff`, `within` and `measure`.
