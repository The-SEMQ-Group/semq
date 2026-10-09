---
search:
  boost: 1.25
---

# TypeScript API

The `@semq/sdk` package runs the C core in WebAssembly, for Node
and browsers. For a complete program, use the [quickstart](../quickstart.md);
the [TypeDoc reference](typescript-api/index.html) lists every package member.

## Conventions

- Loading the wasm module is the one asynchronous step. `await Codec.create(config)`
  performs it, and so does `await load()` for code that starts from
  `CodecConfig`, `Encoding.fromBytes` or `Floor`. Every other call is
  synchronous and throws `Native` when made before the runtime is loaded.
- `u64` ids are `bigint` (`1n`); `utf8` ids are `string`. A `number` id, a
  bigint outside `[0, 2^64)` and a string with a lone surrogate throw
  `InvalidInput`. `vectors` is a `Float32Array` of `n * dim` unit-norm values.
- Accessors return copies. `Encoding`, `Diff`, `Floor` and `Codec` own native
  memory: call `dispose()` when done; a finalizer frees what is left.
- Out of memory throws `RangeError`.

## Surface

| Symbol | Contract |
| --- | --- |
| `CodecConfig.quant(dim, bins)`, `.phase(dim, sectors)`, `.orbit(dim, scale = 50)`, `.fromBytes(u8)` | Constructors |
| `config.toBytes()`, `operator`, `dim`, `bins \| sectors \| scale`, `ruleRevision`, `bytesPerVector`, `unitsPerRow`, `maxMagnitude`, `equals(other)`, `asDict()` | Accessors; a getter of the wrong operator throws `InvalidInput` |
| `Operator.Orbit`, `Operator.Phase`, `Operator.Quant` | The operator values `0`, `1`, `2` |
| `await Codec.quant(dim, bins)`, `await Codec.phase(dim, sectors)`, `await Codec.orbit(dim, scale?)`, `await Codec.create(config)` | `config`, `backend`, `encode({ ids, vectors, manifest?, idKind? })`, `decode(e)`, `unpack(e)`, `dispose()` |
| `new Encoding({ ids, rows, config, manifest?, idKind? })`, `Encoding.fromBytes(u8)` | Constructors from canonical rows or a file image |
| `encoding.toBytes()`, `config`, `idKind`, `length`, `ids`, `rows`, `row(i)`, `get(id)`, `manifest`, `contentDigest`, `stateId`, `equals(other)`, `concat(...others)`, `diff(candidate)`, `[Symbol.iterator]`, `dispose()` | Access and verbs; `equals` compares `stateId` |
| `diff.referenceId`, `candidateId`, `idKind`, `config`, `added`, `removed`, `changed`, `nUnchanged`, `manifestChanges`, `units(id)`, `within(floor)`, `evaluate(floor, { perRow })`, `asDict()`, `dispose()` | `asDict()` returns the [report schema](contracts.md#report-schema); `within` and `evaluate` throw `Incompatible` when the floor was measured against another config, id kind or reference; `evaluate` returns a `Verdict` (`passed`, `reasons`, `rows`), and `perRow` needs a floor with per-row data |
| `new Floor({ config, idKind, referenceId, nulls, changedRows, totalRows, hamming })`, `Floor.measure(diffs, { perRow? })`, `Floor.fromDict(d)` | Constructors; `referenceId` is the reference's `stateId` (32 bytes), counts are numbers, and the core validates the fields at construction. Only `measure` with `perRow` and `fromJson`/`fromDict` give a floor with per-row data |
| `floor.config`, `idKind`, `referenceId`, `nulls`, `changedRows`, `totalRows`, `hamming`, `maxHamming`, `distinctNulls`, `equals(other)`, `toJson()`, `asDict()`, `dispose()`; `Floor.fromJson(json)` | `toJson`/`fromJson` are the [floor schema](contracts.md#floor-schema), written and read by the core; `asDict()` is its parsed object (`max_hamming` and `distinct_nulls` only when recorded) and `fromDict` its inverse by the same rules |
| `buildInfo()`, `BuildInfo` | `sdkVersion`, `coreVersion`, `backend: { orbit, phase, quant }`, `buildId` |
| `InvalidInput`, `Incompatible`, `FormatError`, `IntegrityError`, `Unsupported`, `Native` | Errors; see [TypeScript errors](typescript-errors.md) |
| `load()` | Load the wasm module without creating a `Codec` |

Node applications read and write `.semq` files with `node:fs`; browsers
store the `Uint8Array` from `toBytes()` where they choose.

## Next steps

- [Run the quickstart](../quickstart.md).
- [Handle errors](typescript-errors.md).
