# Changelog

Notable changes to the SEMQ SDK, organized using
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The SDK follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html); see
[Compatibility and migration](docs/compatibility.md) for what each version
guarantees. Use the [API reference](docs/reference/index.md) for the current
surface.

## [Unreleased]

### Added

- **`Diff.evaluate(floor, options)`**, a verdict that names every failed
  check (`reasons`) instead of a single boolean. With no options it agrees
  with `within`. Options are off by default, so a new one never changes an
  existing verdict. Python `diff.evaluate(floor, per_row=...)`, Rust
  `diff.evaluate(&floor, &GateOptions::new().per_row(...))`, Go
  `d.Evaluate(f, semq.GateOptions{PerRow: ...})`, TypeScript
  `diff.evaluate(floor, { perRow })`; C `semq_diff_evaluate(diff, floor,
  checks, ...)` with `semq_check_t` flags and `semq_verdict_t`. An unknown
  flag is `InvalidInput`.
- **Per-row check.** `per_row` also fails the verdict when any changed row
  has a hamming distance above the floor's `max_hamming`, the largest of any
  changed row of any null, and lists those rows. The p99 check ignores the
  most changed 1% of rows; this one ignores none. `semq diff --floor F
  --per-row` applies it from the command line.
- **Floors with per-row data.** `Floor.measure(nulls, per_row=True)` (Rust
  `Floor::measure_for`, Go `MeasureFloorFor`, TypeScript
  `Floor.measure(nulls, { perRow: true })`, C `semq_floor_measure_for`,
  CLI `semq floor --per-row`) also records `max_hamming` and
  `distinct_nulls`, the number of distinct null states (two nulls are the
  same when their candidates have the same `content_digest`). Both are
  optional keys of the floor JSON, with accessors in every binding (C
  `semq_floor_max_hamming`, `semq_floor_distinct_nulls`). `measure` and
  the constructors record neither.
- **The floor JSON is written and read by the core** (`semq_floor_save`,
  `semq_floor_load`), so every binding applies the same rules. Rust
  `Floor::to_json` and `Floor::from_json`, Go `json.Marshal(floor)` and
  `semq.LoadFloor`, TypeScript `floor.toJson()` and `Floor.fromJson`; Python
  `save`, `load`, `as_dict` and `from_dict` now call the core.
- `semq diff --per-row` warns on stderr when the floor's nulls were not all
  the same state and there are fewer than 20 of them. With `N` such nulls,
  each check can reject an unchanged rebuild with probability up to
  `1/(N+1)`; the warning does not change the exit code. The
  [gate guide](docs/guides/gate-a-rebuild.md) explains the bound.

### Changed

- Reading floor JSON ignores keys it does not know, at the top level and
  inside `config`, so a floor saved by a later version with an added key
  still reads. Known keys stay strict, and `18446744073709551615` is
  reserved in `max_hamming` and `distinct_nulls`. `version` remains
  `semq-floor/1`; it changes only when the meaning of a key changes.
  `measure` writes the same bytes as SEMQ 1.0, so its floors read in every
  version. SEMQ 1.0 rejects a floor that carries `max_hamming` or
  `distinct_nulls`: upgrade the readers before writing floors with
  `per_row`.
- Go `FloorReport.UnmarshalJSON` and `FloorFromReport` read through the
  core, and so check every value, not only the shape. `FloorReport` keeps
  its 1.0 fields and drops the per-row data; read a floor with per-row data
  with `LoadFloor` (Rust `Floor::from_json`).
- `semq diff --floor --json` adds a `verdict` object next to `within`.

## [1.0.0] - 2026-10-05

First public release.

### Added

- **A core built around states with an identity.** The C library owns every
  rule that determines bytes or verdicts, and the Python, Rust, Go and
  TypeScript/WebAssembly bindings are thin wrappers over its 67-function ABI.
  Five types and one service: `CodecConfig` (`quant(dim, bins)`,
  `phase(dim, sectors)`, `orbit(dim, scale)`, a 13-byte canonical form),
  `Codec` (`encode`, `decode`, `unpack`), `Encoding` (sorted `u64` or `utf8`
  ids, canonical rows, a manifest, `content_digest` and `state_id`;
  `save`/`load`, `concat`, `diff`), `Diff` (`added`, `removed`, `changed`
  with hamming distances, `manifest_changes`, `units`, `within`, `as_dict`),
  `Floor` (`measure` from null diffs; bound to the config, id kind and
  reference it was measured against, with the number of nulls, a versioned
  schema for `floor.json`, and a verdict that fails on a changed `encoder` or
  `encoder_revision`) and `BuildInfo`. Six errors cover every failure:
  `InvalidInput`, `Incompatible`, `FormatError`, `IntegrityError`,
  `Unsupported`, `Native`.
- Direct constructors in every binding: `Codec.quant(dim, bins)`, `phase` and
  `orbit` (Rust `Codec::quant`, Go `NewQuantCodec`, TypeScript
  `await Codec.quant`) build the codec and its config in one call; `CodecConfig`
  remains for files and floors. In TypeScript they load the wasm module first,
  so they need no prior `await load()`.
- A one-line, human-readable form of `Encoding`, `Diff` and `Floor`, identical
  in every binding: Python `str()`, Rust `Display`, Go `String()`, TypeScript
  `toString()`. A `Diff` reads `1 of 3 rows changed: doc-3 (hamming 3). 0 added,
  0 removed.` Encodings compare by `state_id`: Python `==`, Rust `PartialEq`,
  TypeScript `Encoding.equals(other)`.
- The `.semq` file format, version 2: config, ids, rows, manifest and two
  SHA-256 identities, validated in a fixed order before any allocation
  proportional to a declared size.
- The input contract: unit-norm finite float32 rows with subnormals
  canonicalized to zero, so the bytes do not depend on the flush-to-zero
  state; the round-to-nearest mode is required.
- Three operators. `quant` uses the derived range `2 / sqrt(dim)`. `phase`
  packs nibbles when `sectors <= 16`, and its angle polynomial stays within
  0.04° of `atan`, keeping neighbouring inputs in order across the 45°
  diagonal. `orbit` fixes its alphabet at 19, with `scale` in `[1, 2^30]`.
- SIMD kernels: AVX2 and AVX-512 are selected only when the CPU and the
  operating system both support them, and every backend produces the same
  bytes as the scalar kernel.
- A known-answer self-test: before creating a codec, the core checks the
  selected kernel against the scalar kernel's bytes for fixed rows, and
  SHA-256 against a known digest, and refuses to create the codec if either
  differs.
- The `semq` command: `show`, `diff [--floor]`, `floor [--min-nulls N]`
  (three null rebuilds by default), `version`, with exit codes `0`/`1`/`2`.
- Conformance vectors under `tests/conformance/`, generated by the core's
  test binary, cross-checked by an independent pure-Python reference for the
  non-kernel contracts, executed by every host, and gated in CI on every
  architecture (`tools/conformance.py`).
- Two reference pages that state the contracts exactly: the core contracts
  (input rows, operator rules, diff, floor and the two report schemas) and
  the file format byte by byte.
- Packaging: the static archive needs only libc and libm; the Rust crates
  bundle the core sources for static linking; the Go module carries the core
  too and cgo compiles it, so `go get` needs only a C compiler; the Python package ships one wheel per platform for Python 3.11 and
  newer, is tested on 3.11 to 3.14, and depends only on `cffi` and `numpy`.
- Reader fuzzing, allocation-failure cleanup tests, compiled ABI and layout
  checks, and artifact consumers that install the packages without a
  checkout.
- Licensing: the SDK is licensed under the PolyForm Noncommercial License
  1.0.0. Every package ships `LICENSE.md` and `NOTICE`, and the npm package
  also ships `THIRD_PARTY_LICENSES` for the Emscripten runtime it bundles.

[Unreleased]: https://github.com/The-SEMQ-Group/semq/commits/main
[1.0.0]: https://github.com/The-SEMQ-Group/semq/releases/tag/v1.0.0
