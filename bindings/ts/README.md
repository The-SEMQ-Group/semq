# TypeScript binding

The TypeScript package runs the shared C core in WebAssembly, for browsers and
Node. It exposes the same five types and one service as the other bindings,
and every rule that determines bytes or verdicts runs in the core: the
package validates JavaScript representations, maps errors and moves bytes.

Use the [installation guide](https://github.com/The-SEMQ-Group/semq/blob/main/docs/installation.md),
[quickstart](https://github.com/The-SEMQ-Group/semq/blob/main/docs/quickstart.md), and
[TypeScript API reference](https://github.com/The-SEMQ-Group/semq/blob/main/docs/reference/typescript.md) for application
code. This page covers the surface, building and testing the checkout.

## Surface

- `CodecConfig.quant(dim, bins)`, `.phase(dim, sectors)`, `.orbit(dim, scale = 50)`,
  `.fromBytes(u8)`; `toBytes()`, `operator`, `dim`, `bins | sectors | scale`,
  `ruleRevision`, `bytesPerVector`, `unitsPerRow`, `maxMagnitude` (quant),
  `equals`, `asDict`.
- `await Codec.create(config)`: `encode({ ids, vectors, manifest?, idKind? })`,
  `decode(e)`, `unpack(e)`, `config`, `backend`, `dispose()`. `ids` are
  `bigint[]` (`u64`) or `string[]` (`utf8`); `vectors` a `Float32Array` of
  `n * dim` unit-norm values.
- `Encoding`: `new Encoding({ ids, rows, config, manifest?, idKind? })`,
  `Encoding.fromBytes(u8)`, `toBytes()`, `config`, `idKind`, `length`,
  `ids`, `rows`, `row(i)`, `get(id)`, `manifest`, `contentDigest`, `stateId`,
  `concat(...others)`, `diff(candidate)`, iteration over `[id, row]`,
  `dispose()`. Accessors return copies.
- `Diff`: `referenceId`, `candidateId`, `idKind`, `config`, `added`,
  `removed`, `changed`, `nUnchanged`, `manifestChanges`, `units(id)`,
  `within(floor)`, `asDict()`, `dispose()`.
- `Floor`: `new Floor({ config, idKind, referenceId, nulls, changedRows, totalRows, hamming })`,
  `Floor.measure(diffs)`, `Floor.fromDict(d)`, the seven fields as getters,
  `asDict()`, `equals(other)`, `dispose()`. A floor is bound to the config,
  the id kind and the reference its nulls were measured against;
  `diff.within(floor)` throws `Incompatible` for any other diff.
- `buildInfo()` and the `BuildInfo` type.
- Errors: `InvalidInput`, `Incompatible`, `FormatError`, `IntegrityError`,
  `Unsupported`, `Native`. Out of memory is a `RangeError`.
- `load()`: loads the wasm module without creating a `Codec`.

Loading the wasm module is the only asynchronous step. `await Codec.create(config)`
performs it, and so does `await load()` for code that starts from
`CodecConfig`, `Encoding.fromBytes` or `Floor`. Every other call is
synchronous and raises `Native` when made before the runtime is loaded.

`uint64_t` values cross the wasm boundary as `bigint`; ids and counts that
live in memory go through typed heap helpers. `Encoding`, `Diff`, `Floor` and
`Codec` own native memory: call `dispose()` when done, or let the finalizer
free it.

## Prerequisites

Use Node.js 22, as in [CI](https://github.com/The-SEMQ-Group/semq/blob/main/.github/workflows/test.yml), npm, CMake, Ninja,
and an activated Emscripten toolchain with `emcc` and `emcmake` on `PATH`.
The package is currently private and consumed from the checkout; see
[package.json](https://github.com/The-SEMQ-Group/semq/blob/main/bindings/ts/package.json) for its entry point and commands.

## Build and test

From the repository root:

```sh
cd bindings/ts
npm ci
npm run build
npm run typecheck
npm run lint
npm test
```

`npm run build` compiles the WASM module and emits the TypeScript package into
`dist`. The WASM build stages its assets in `src/wasm`; `build:ts` copies them
to `dist/wasm` so the compiled package's relative asset imports resolve.

For changes limited to TypeScript, run `npm run build:ts`, `npm run typecheck`,
`npm run lint` and `npm test` after the WASM assets have been built. Rebuild WASM when changing
native code. The [build script](https://github.com/The-SEMQ-Group/semq/blob/main/bindings/ts/scripts/build-wasm.sh) selects the scalar backend
and disables OpenMP.

## Validate changes

Vitest runs `test/core.test.ts`: the canonical config form, the specification
digests and file image, the input contract, persistence and its failure
modes, `concat`, `diff`, `Floor.measure` and build information, with the
expected values of `tests/unit/test_core.c`.

## Related documentation

- [Contributor guide](https://github.com/The-SEMQ-Group/semq/blob/main/CONTRIBUTING.md).
- [CI workflow](https://github.com/The-SEMQ-Group/semq/blob/main/.github/workflows/test.yml).
