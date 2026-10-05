// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

import { ABI } from "./layout.js";

import { FormatError, Incompatible, IntegrityError, InvalidInput, Native, Unsupported } from "./errors.js";
import { SemqWasm } from "./module.js";
import { bindCore, type CoreExports } from "./native.js";

/** `SEMQ_NONE`: "no row" / "no field" in error reports and index lookups. */
export const NONE = 0xffffffffffffffffn;

/** sizeof(semq_error_t) on wasm32: status u32 @0, which u32 @4, row u64 @8,
 * field u64 @16, message char[128] @24. */
const ERROR_BYTES = ABI.error.size;

/** The loaded wasm instance, the typed core table, one scratch error struct
 * (the core keeps no state and never re-enters JavaScript, so one is enough),
 * and the finalizers that free handles dropped without `dispose()`. */
export interface Runtime {
  w: SemqWasm;
  core: CoreExports;
  err: number;
  codecs: FinalizationRegistry<number>;
  encodings: FinalizationRegistry<number>;
  diffs: FinalizationRegistry<number>;
  floors: FinalizationRegistry<number>;
}

let pending: Promise<Runtime> | undefined;
let ready: Runtime | undefined;

/** Load the wasm module once and cache it. */
export function getRuntime(): Promise<Runtime> {
  if (!pending) {
    pending = SemqWasm.load()
      .then((w) => {
        const core = bindCore(w);
        const r: Runtime = {
          w,
          core,
          err: w.malloc(ERROR_BYTES),
          codecs: new FinalizationRegistry<number>((p) => core.codecFree(p)),
          encodings: new FinalizationRegistry<number>((p) => core.encodingFree(p)),
          diffs: new FinalizationRegistry<number>((p) => core.diffFree(p)),
          floors: new FinalizationRegistry<number>((p) => core.floorFree(p)),
        };
        ready = r;
        return r;
      })
      .catch((e: unknown) => {
        pending = undefined;
        throw new Native(
          `could not load the SEMQ wasm module: ${e instanceof Error ? e.message : String(e)}`,
          { operation: "load" },
        );
      });
  }
  return pending;
}

/**
 * Load the wasm module so the synchronous surface (`CodecConfig`,
 * `Encoding.fromBytes`, `new Encoding`, `new Floor`, `buildInfo`) can be
 * used before any `Codec` exists. Idempotent; `Codec.create` loads too.
 */
export async function load(): Promise<void> {
  await getRuntime();
}

/** The loaded runtime, for the synchronous surface. */
export function rt(): Runtime {
  if (!ready) {
    throw new Native("the SEMQ runtime is not loaded: await load() or Codec.create() first", {
      operation: "load",
    });
  }
  return ready;
}

/**
 * Run one core call with the scratch error struct reset, and map a non-OK
 * status to the host error. `operation` names the verb for Unsupported and
 * Native reports.
 */
export function call(r: Runtime, operation: string, f: (err: number) => number): void {
  const { w, err } = r;
  w.setU32(err + ABI.error.status, 0);
  w.setU32(err + ABI.error.which, 0);
  w.setU64(err + ABI.error.row, NONE);
  w.setU64(err + ABI.error.field, NONE);
  w.setU32(err + ABI.error.message, 0);
  const status = f(err);
  if (status !== 0) throw errorFor(r, status, operation);
}

function errorFor(r: Runtime, status: number, operation: string): Error {
  const { w, err, core } = r;
  const message = w.utf8(err + ABI.error.message) || core.statusName(status);
  const which = w.getU32(err + ABI.error.which);
  const row = index(w.getU64(err + ABI.error.row));
  const field = index(w.getU64(err + ABI.error.field));
  switch (status) {
    case ABI.constants.SEMQ_ERR_INVALID_INPUT:
      return new InvalidInput(message, { row, field });
    case ABI.constants.SEMQ_ERR_INCOMPATIBLE:
      return new Incompatible(message, { field });
    case ABI.constants.SEMQ_ERR_FORMAT:
      return new FormatError(message, { row, section: field });
    case ABI.constants.SEMQ_ERR_INTEGRITY:
      return new IntegrityError(message, {
        which: which === ABI.constants.SEMQ_WHICH_CONTENT ? "content" : which === ABI.constants.SEMQ_WHICH_STATE ? "state" : undefined,
      });
    case ABI.constants.SEMQ_ERR_UNSUPPORTED:
      return new Unsupported(message, { operation });
    case ABI.constants.SEMQ_ERR_NOMEM:
      return new RangeError(message);
    default:
      return new Native(message, {
        operation,
        status,
        row,
        field,
        coreVersion: core.coreVersion(),
        buildId: core.buildId(),
      });
  }
}

function index(value: bigint): number | undefined {
  return value === NONE ? undefined : Number(value);
}
