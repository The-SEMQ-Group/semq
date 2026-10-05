# Core contracts

The rules that decide bytes and verdicts live in the C core, and every
binding is a thin layer over it. This page states those rules exactly: what
`encode` accepts, how each operator maps a float to a symbol, what `diff`
reports, and when a candidate is `within` a floor. They are pinned by the
[conformance vectors](https://github.com/The-SEMQ-Group/semq/tree/main/tests/conformance),
which CI regenerates on every architecture and every binding runs. The byte
layouts they produce are on the [file format](file-format.md) page.

**What is byte-identical.** For the same float32 input, the same ids, the
same manifest and the same config, `encode`, `unpack`, `diff`, the two
digests and `save`/`load` produce identical bytes on every CPU, operating
system and binding, as long as construction and encoding run with
round-to-nearest-even. Codec construction rejects other modes before
computing cached quantities; the core never changes the mode. No
floating-point value takes part in an identity or a verdict. `decode` is
outside this promise: its representatives may differ across platforms by
one unit in the last place for quant and orbit and by four for phase.

## Input rows

`encode` takes float32 vectors of shape `[n, dim]`, contiguous and
row-major. A float64 array is rejected with `InvalidInput`, never cast. The
core then applies four steps to every row:

1. **Subnormals.** Every coordinate with `|x| < 2^-126`, including both
   zeros, becomes `+0.0`. The result therefore does not depend on the
   flush-to-zero state of the process.
2. **Finiteness.** A NaN or an infinity is `InvalidInput` with the row and
   the coordinate.
3. **Norm.** `s = Σ (double)x_i × (double)x_i`, accumulated in binary64 in
   index order (each square of a float32 is exact in binary64). The row is
   accepted when `|s - 1| <= 2^-10`; otherwise `InvalidInput` with the row.
   No square root is taken.
4. **Rounding mode.** Once per call, the process must be in round-to-nearest
   mode; otherwise `Unsupported`. The core never changes the mode.

## Operators

Every operator turns a unit (one coordinate, or one coordinate pair for
phase) into one symbol. `decode` returns a representative per unit; it is
not normalized, and re-encoding it without the norm check gives the same
row back.

### orbit

`scale` in `1..2^30`, default 50; the alphabet is fixed at 19 symbols.

- `p = (double)x × (double)scale`, then `m = round_half_even(p)`, computed
  without relying on the rounding mode: `f = floor(p)`, `r = p - f`;
  `m = f + 1` when `r > 0.5`, `m = f` when `r < 0.5`, and on a tie `m = f`
  when `f` is even, else `f + 1`. With an admitted row and `scale <= 2^30`,
  `|m| < 2^31` always holds.
- Digital root: for `a = |m| > 0`, `d = 1 + ((a - 1) mod 9)`, in `1..9`.
- Symbol: `0` when `m = 0`; `d` when `m > 0`; `9 + d` when `m < 0`.

Representative: `sign × d / scale` in binary64, cast to float32 (`0.0` for
symbol 0).

### phase

`dim` even, `sectors` in `2..256`, and `dim` a multiple of 4 when
`sectors <= 16`. A unit is the pair `(x, y) = (x_2j, x_2j+1)`.

- Angle. With `ax = |x|` and `ay = |y|` in binary64: a zero pair has angle
  `0`. Otherwise the first-octant angle is `P(ay / ax)` when `ax >= ay` and
  `π/2 - P(ax / ay)` when `ax < ay`, where
  `P(t) = ((c5 × t² + c3) × t² + c1) × t` is evaluated in binary64 with
  the two inner steps as fused multiply-adds and the final product unfused,
  with `c1 = 0.9947660466480732`, `c3 = -0.28543420102605926`,
  `c5 = 0.07606631777543432`, `π = 3.141592653589793238462643383279502884`.
  Then `θ = π - φ` when `x < 0`, and `θ = -θ` when `y < 0`.
- Sector: `raw = (θ + π) × (sectors / (2π))` in binary64, the quotient
  computed first; `raw` is clamped below at `0`, truncated to an integer,
  and clamped above at `sectors - 1`.

`P` is the minimax odd quintic for `atan` on `[0, 1]` under the constraint
`P(1) = π/4`, which holds to the bit in binary64: the two octants meet
without a jump and the angle is monotone across the diagonal. Its error
against `atan` is at most `7.04 × 10⁻⁴` rad (0.04°), reached at three
interior points, and its slope stays above `0.518`. `P` is the rule, not the
exact angle: an input within that error of a sector boundary may land in
the neighbouring sector of the exact `atan2`, and every backend reproduces
these bits.

Representative: the unit direction whose encoder angle is the midpoint of
the sector, `-π + (sector + 0.5) × 2π / sectors`. It is found by inverting
`P` on `[0, 1]` by bisection, reflecting the quadrant as above and
normalizing `(ax, ay)`, which is the one place the platform `libm` is used.

### quant

`bins` in `2..64`. The range is `M = max_magnitude = (float)(2.0 /
sqrt((double)dim))`.

- `sign = 1` when `x >= +0.0`, else `0` (after step 1 there is no `-0.0`).
- `m = |x|` in float32.
- When `m >= M`, `bin = bins - 1`. Otherwise `t = (m × (float)bins) / M`,
  both operations in float32 without fused contraction, and
  `bin = min(floor(t), bins - 1)`.
- Symbol: `sign × bins + bin`.

Representative: `c = (bin + 0.5) × M / bins` in binary64, with the sign of
the unit, cast to float32.

## Encoding

An Encoding is immutable: `config`, `id_kind`, sorted `ids`, one canonical
row per id, `manifest`, `content_digest` and `state_id`.

- `Codec.encode` builds one from vectors. `id_kind` is inferred from the
  first id and must be given when there are no rows.
- `Encoding(ids, rows, config, manifest, id_kind)` builds one from rows you
  already hold: it sorts the pairs by id, rejects a duplicate id (naming the
  first repeated row), checks the row width and canonicity, validates the
  manifest, copies the rows once and computes both digests.
- `load` always copies and validates in the order the
  [file format](file-format.md#how-a-file-is-read) page describes.
- `concat(*others)` needs the same config and id kind (else `Incompatible`)
  and the same manifest with pairwise-disjoint ids (else `InvalidInput`). It
  is commutative and associative, and the empty Encoding of the same config,
  kind and manifest is its neutral element.
- `diff(candidate)` needs the same config and id kind (else
  `Incompatible`). When both `content_digest` are equal the row lists are
  empty without a scan; `manifest_changes` is still computed.
- Two Encodings are equal when their `state_id` is equal.

## Diff

- `added`: ids only in the candidate; `removed`: ids only in the reference;
  both in id order.
- `changed`: the ids present in both with different rows, each with its
  hamming distance: the number of units whose symbol differs, compared per
  symbol and never per byte.
- `n_unchanged`: the ids present in both with identical rows.
- `manifest_changes`: each key whose value differs or exists on one side
  only, with its value before and after (absent is `null`).
- `units(id)`: for a changed id, the units that moved with both symbols;
  `InvalidInput` when the id is absent from either side.

A Diff keeps the rows it needs until it is released, even if the caller
drops its Encodings.

### Report schema

```
{
  "reference_id":     hex64,
  "candidate_id":     hex64,
  "id_kind":          "u64" | "utf8",
  "config":           { "operator": "quant" | "phase" | "orbit", "dim": int,
                        "bins" | "sectors" | "scale": int, "rule_revision": int },
  "added":            [id, ...],
  "removed":          [id, ...],
  "changed":          [[id, hamming], ...],
  "n_unchanged":      int,
  "manifest_changes": { key: [before | null, after | null], ... }
}
```

`u64` ids are decimal strings, because JavaScript cannot hold integers above
`2^53` exactly; `utf8` ids are JSON strings; counts are JSON integers;
digests are lowercase hex; there are no floats. The keys and values are the
contract, not the JSON text: each binding serializes with its standard
library, and vector 13 compares structure and values.

## Floor

A floor is the envelope of variation seen in rebuilds that changed nothing
on purpose, bound to where it was measured: `config`, `id_kind`,
`reference_id` (the `state_id` of the reference every null was taken
against), `nulls` (how many null diffs went in), `changed_rows`,
`total_rows` and `hamming`.

**Construction.** Every rule is checked when a floor is built or loaded, not
when it is applied: the config is valid, `id_kind` is `u64` or `utf8`,
`nulls >= 1`, `total_rows >= 1`, `changed_rows <= total_rows`, and
`hamming <= units_per_row` of the config. Otherwise `InvalidInput`.

**`Floor.measure(null_diffs)`.** Every null must share the config, the id
kind and the reference of the first (else `Incompatible`, naming the index),
and must be a valid null: rows in common, nothing added or removed, no
change to `encoder` or `encoder_revision` (else `InvalidInput`, naming the
index). Then `(changed_rows, total_rows)` is the pair
`(len(changed), n_common)` with the largest ratio among the nulls, compared
exactly by cross-multiplication; `hamming` is the largest per-null p99 of
the hamming distances; `nulls` is the count of nulls.

`p99` of `m` integers is `0` when `m = 0`, and otherwise the `k`-th smallest
with `k = m - floor(m / 100)`: nearest rank, with no product that can
overflow.

**`diff.within(floor)`.** The floor must match the diff's config, id kind
and reference; otherwise `Incompatible`. With `n_common = n_unchanged +
len(changed)`, the diff is within the floor when all of these hold:

1. `n_common > 0`;
2. `removed` is empty;
3. `len(changed) × floor.total_rows <= floor.changed_rows × n_common`,
   compared exactly, never in floating point;
4. the p99 of the hamming distances over `changed` is at most
   `floor.hamming` (`0` when nothing changed);
5. `manifest_changes` contains neither `encoder` nor `encoder_revision`.

Added rows and other manifest changes do not affect the verdict. Every null
used to measure a floor is within it. The envelope is taken component by
component, so the ratio may come from one null and the hamming from
another, and the floor can be looser than any single null observed. It
describes what was observed; it makes no probabilistic claim about the next
rebuild. The core accepts a single null; the `semq` command asks for three
by default, because one null only shows what that rebuild happened to do.

### Floor schema

```
{
  "version":      "semq-floor/1",
  "config":       { "operator": "quant" | "phase" | "orbit", "dim": int,
                    "bins" | "sectors" | "scale": int, "rule_revision": int },
  "id_kind":      "u64" | "utf8",
  "reference_id": hex64,
  "nulls":        int,
  "changed_rows": int,
  "total_rows":   int,
  "hamming":      int
}
```

Keys in this order, counts as JSON integers, the config as in the report
schema. Bindings write it from a floor and read it back strictly: exactly
these keys, this `version`, integers only (no booleans, floats or numeric
strings) and a 64-character hex `reference_id`; any deviation is
`InvalidInput`.
