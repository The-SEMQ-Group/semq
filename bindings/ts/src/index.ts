// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

/**
 * SEMQ: deterministic symbolic encoding of float32 vectors, for browsers and
 * Node, over the shared C core compiled to WebAssembly.
 *
 * Five types and one service, backed by a core that owns every rule:
 *
 * - {@link CodecConfig}: the rule (`quant`, `phase` or `orbit`).
 * - {@link Codec}: encodes unit-norm float32 vectors into an {@link Encoding}.
 * - {@link Encoding}: ids, canonical rows, a manifest and two identities;
 *   `toBytes`/`fromBytes`, `concat` and `diff`.
 * - {@link Diff}: added, removed and changed ids with hamming distances.
 * - {@link Floor}: the envelope of variation observed in null diffs of one
 *   reference, with `asDict()` and `Floor.fromDict()` for its report form.
 * - {@link BuildInfo} from {@link buildInfo}.
 *
 * Errors: {@link InvalidInput}, {@link Incompatible}, {@link FormatError},
 * {@link IntegrityError}, {@link Unsupported}, {@link Native}. Out of memory
 * is a `RangeError`.
 *
 * Loading the wasm module is the one asynchronous step. `await Codec.create(config)`
 * performs it; so does {@link load}, for code that needs `CodecConfig`,
 * `Encoding.fromBytes` or `Floor` before it has a Codec. Everything else is
 * synchronous and raises {@link Native} when called before the runtime is
 * loaded.
 *
 * @module @semq/sdk
 */

export { buildInfo, type BuildInfo } from "./build.js";
export { Codec } from "./codec.js";
export { CodecConfig, Operator } from "./config.js";
export { Diff, type GateOptions, type Reason, type Verdict } from "./diff.js";
export { Encoding } from "./encoding.js";
export { FormatError, Incompatible, IntegrityError, InvalidInput, Native, Unsupported } from "./errors.js";
export { Floor } from "./floor.js";
export { load } from "./runtime.js";
