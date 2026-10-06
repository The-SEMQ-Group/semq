// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

import type { SemqWasm } from "./module.js";

/**
 * Typed wrappers over the 67 exports of the core, one per declaration in
 * include/semq.h. Nothing here decides bytes or verdicts.
 *
 * Boundary contract. Pointers, `uint32_t`, `int` and `float` cross as
 * numbers. Every `uint64_t` parameter and return value crosses as a bigint:
 * the module is linked with the Emscripten default `WASM_BIGINT` (on since
 * Emscripten 4.0), so i64 is never legalized into i32 pairs and
 * `getTempRet0` is not involved. Values that live in memory (ids, offsets,
 * digests, counts behind out-pointers) are moved with the heap helpers in
 * module.ts. {@link bindCore} probes one u64 call at load time so a module
 * built without bigint support fails loudly instead of corrupting arguments.
 */
export interface CoreExports {
  // CodecConfig
  configOrbit: (dim: number, scale: number, out: number, err: number) => number;
  configPhase: (dim: number, sectors: number, out: number, err: number) => number;
  configQuant: (dim: number, bins: number, out: number, err: number) => number;
  configValidate: (cfg: number, err: number) => number;
  configToBytes: (cfg: number, out: number) => void;
  configFromBytes: (bytes: number, out: number, err: number) => number;
  configBytesPerVector: (cfg: number) => number;
  configUnitsPerRow: (cfg: number) => number;
  configMaxMagnitude: (cfg: number) => number;
  configEqual: (a: number, b: number) => number;
  // Codec
  codecCreate: (cfg: number, out: number, err: number) => number;
  codecFree: (codec: number) => void;
  codecConfig: (codec: number) => number;
  codecBackend: (codec: number) => string;
  codecEncode: (
    codec: number,
    ids: number,
    vectors: number,
    manifest: number,
    nPairs: number,
    out: number,
    err: number,
  ) => number;
  codecDecode: (codec: number, enc: number, out: number, err: number) => number;
  codecUnpack: (codec: number, enc: number, out: number, err: number) => number;
  // Encoding
  encodingCreate: (
    cfg: number,
    ids: number,
    rows: number,
    manifest: number,
    nPairs: number,
    out: number,
    err: number,
  ) => number;
  encodingFree: (enc: number) => void;
  encodingConfig: (enc: number) => number;
  encodingIdKind: (enc: number) => number;
  encodingLen: (enc: number) => bigint;
  encodingRows: (enc: number, lenOut: number) => number;
  encodingIdsU64: (enc: number) => number;
  encodingIdsUtf8Offsets: (enc: number) => number;
  encodingIdsUtf8Bytes: (enc: number, lenOut: number) => number;
  encodingManifestLen: (enc: number) => number;
  encodingManifestPair: (enc: number, i: number, out: number, err: number) => number;
  encodingContentDigest: (enc: number, out: number) => void;
  encodingStateId: (enc: number, out: number) => void;
  encodingFindU64: (enc: number, id: bigint, indexOut: number, err: number) => number;
  encodingFindUtf8: (enc: number, id: number, len: bigint, indexOut: number, err: number) => number;
  encodingFileSize: (enc: number) => bigint;
  encodingSaveParts: (enc: number, parts: number) => number;
  encodingSave: (enc: number, out: number, cap: bigint, err: number) => number;
  encodingLoad: (buf: number, len: bigint, out: number, err: number) => number;
  encodingConcat: (parts: number, k: number, out: number, err: number) => number;
  encodingDiff: (reference: number, candidate: number, out: number, err: number) => number;
  // Diff
  diffFree: (diff: number) => void;
  diffConfig: (diff: number) => number;
  diffIdKind: (diff: number) => number;
  diffReferenceId: (diff: number, out: number) => void;
  diffCandidateId: (diff: number, out: number) => void;
  diffCount: (diff: number, list: number) => bigint;
  diffNUnchanged: (diff: number) => bigint;
  diffId: (
    diff: number,
    list: number,
    i: bigint,
    u64Out: number,
    bytesOut: number,
    lenOut: number,
    err: number,
  ) => number;
  diffHamming: (diff: number, i: bigint, out: number, err: number) => number;
  diffManifestChanges: (diff: number) => number;
  diffManifestChange: (diff: number, i: number, out: number, err: number) => number;
  diffUnitsU64: (
    diff: number,
    id: bigint,
    units: number,
    refSymbols: number,
    candSymbols: number,
    cap: bigint,
    count: number,
    err: number,
  ) => number;
  diffUnitsUtf8: (
    diff: number,
    id: number,
    len: bigint,
    units: number,
    refSymbols: number,
    candSymbols: number,
    cap: bigint,
    count: number,
    err: number,
  ) => number;
  // Floor
  floorCreate: (
    cfg: number,
    idKind: number,
    referenceId: number,
    nulls: bigint,
    changedRows: bigint,
    totalRows: bigint,
    hamming: bigint,
    out: number,
    err: number,
  ) => number;
  floorCreateWithMax: (
    cfg: number,
    idKind: number,
    referenceId: number,
    nulls: bigint,
    changedRows: bigint,
    totalRows: bigint,
    hamming: bigint,
    maxHamming: bigint,
    out: number,
    err: number,
  ) => number;
  floorFree: (floor: number) => void;
  floorMeasure: (diffs: number, k: number, out: number, err: number) => number;
  floorConfig: (floor: number) => number;
  floorIdKind: (floor: number) => number;
  floorReferenceId: (floor: number, out: number) => void;
  floorNulls: (floor: number) => bigint;
  floorChangedRows: (floor: number) => bigint;
  floorTotalRows: (floor: number) => bigint;
  floorHamming: (floor: number) => bigint;
  floorMaxHamming: (floor: number) => bigint;
  floorJsonSize: (floor: number) => bigint;
  floorSave: (floor: number, out: number, cap: bigint, err: number) => number;
  floorLoad: (buf: number, len: bigint, out: number, err: number) => number;
  diffWithin: (diff: number, floor: number, out: number, err: number) => number;
  // Gate evaluation
  gateOptionsCreate: (out: number, err: number) => number;
  gateOptionsFree: (options: number) => void;
  gateOptionsSetPerRow: (options: number, enabled: number) => void;
  diffEvaluate: (diff: number, floor: number, options: number, out: number, err: number) => number;
  verdictFree: (verdict: number) => void;
  verdictPassed: (verdict: number) => number;
  verdictReasons: (verdict: number) => number;
  verdictRowCount: (verdict: number) => bigint;
  verdictRow: (verdict: number, i: bigint) => bigint;
  // Build information and utilities
  coreVersion: () => string;
  buildId: () => string;
  backendName: (op: number) => string;
  statusName: (status: number) => string;
  sha256: (data: number, len: bigint, out: number) => void;
}

type Args = Array<number | bigint>;

/** Bind the typed {@link CoreExports} table over a loaded wasm module. */
export function bindCore(w: SemqWasm): CoreExports {
  const num = (name: string) => {
    const f = w.raw(name);
    return (...args: Args): number => f(...args) as number;
  };
  const big = (name: string) => {
    const f = w.raw(name);
    // WASM returns i64 as a signed BigInt; every uint64_t of the ABI is unsigned.
    return (...args: Args): bigint => BigInt.asUintN(64, f(...args) as bigint);
  };
  const str = (name: string) => {
    const f = w.raw(name);
    return (...args: Args): string => w.utf8(f(...args) as number);
  };
  const nil = (name: string) => {
    const f = w.raw(name);
    return (...args: Args): void => {
      f(...args);
    };
  };

  const core: CoreExports = {
    configOrbit: num("semq_config_orbit"),
    configPhase: num("semq_config_phase"),
    configQuant: num("semq_config_quant"),
    configValidate: num("semq_config_validate"),
    configToBytes: nil("semq_config_to_bytes"),
    configFromBytes: num("semq_config_from_bytes"),
    configBytesPerVector: num("semq_config_bytes_per_vector"),
    configUnitsPerRow: num("semq_config_units_per_row"),
    configMaxMagnitude: num("semq_config_max_magnitude"),
    configEqual: num("semq_config_equal"),
    codecCreate: num("semq_codec_create"),
    codecFree: nil("semq_codec_free"),
    codecConfig: num("semq_codec_config"),
    codecBackend: str("semq_codec_backend"),
    codecEncode: num("semq_codec_encode"),
    codecDecode: num("semq_codec_decode"),
    codecUnpack: num("semq_codec_unpack"),
    encodingCreate: num("semq_encoding_create"),
    encodingFree: nil("semq_encoding_free"),
    encodingConfig: num("semq_encoding_config"),
    encodingIdKind: num("semq_encoding_id_kind"),
    encodingLen: big("semq_encoding_len"),
    encodingRows: num("semq_encoding_rows"),
    encodingIdsU64: num("semq_encoding_ids_u64"),
    encodingIdsUtf8Offsets: num("semq_encoding_ids_utf8_offsets"),
    encodingIdsUtf8Bytes: num("semq_encoding_ids_utf8_bytes"),
    encodingManifestLen: num("semq_encoding_manifest_len"),
    encodingManifestPair: num("semq_encoding_manifest_pair"),
    encodingContentDigest: nil("semq_encoding_content_digest"),
    encodingStateId: nil("semq_encoding_state_id"),
    encodingFindU64: num("semq_encoding_find_u64"),
    encodingFindUtf8: num("semq_encoding_find_utf8"),
    encodingFileSize: big("semq_encoding_file_size"),
    encodingSaveParts: num("semq_encoding_save_parts"),
    encodingSave: num("semq_encoding_save"),
    encodingLoad: num("semq_encoding_load"),
    encodingConcat: num("semq_encoding_concat"),
    encodingDiff: num("semq_encoding_diff"),
    diffFree: nil("semq_diff_free"),
    diffConfig: num("semq_diff_config"),
    diffIdKind: num("semq_diff_id_kind"),
    diffReferenceId: nil("semq_diff_reference_id"),
    diffCandidateId: nil("semq_diff_candidate_id"),
    diffCount: big("semq_diff_count"),
    diffNUnchanged: big("semq_diff_n_unchanged"),
    diffId: num("semq_diff_id"),
    diffHamming: num("semq_diff_hamming"),
    diffManifestChanges: num("semq_diff_manifest_changes"),
    diffManifestChange: num("semq_diff_manifest_change"),
    diffUnitsU64: num("semq_diff_units_u64"),
    diffUnitsUtf8: num("semq_diff_units_utf8"),
    floorCreate: num("semq_floor_create"),
    floorCreateWithMax: num("semq_floor_create_with_max"),
    floorFree: nil("semq_floor_free"),
    floorMeasure: num("semq_floor_measure"),
    floorConfig: num("semq_floor_config"),
    floorIdKind: num("semq_floor_id_kind"),
    floorReferenceId: nil("semq_floor_reference_id"),
    floorNulls: big("semq_floor_nulls"),
    floorChangedRows: big("semq_floor_changed_rows"),
    floorTotalRows: big("semq_floor_total_rows"),
    floorHamming: big("semq_floor_hamming"),
    floorMaxHamming: big("semq_floor_max_hamming"),
    floorJsonSize: big("semq_floor_json_size"),
    floorSave: num("semq_floor_save"),
    floorLoad: num("semq_floor_load"),
    diffWithin: num("semq_diff_within"),
    gateOptionsCreate: num("semq_gate_options_create"),
    gateOptionsFree: nil("semq_gate_options_free"),
    gateOptionsSetPerRow: nil("semq_gate_options_set_per_row"),
    diffEvaluate: num("semq_diff_evaluate"),
    verdictFree: nil("semq_verdict_free"),
    verdictPassed: num("semq_verdict_passed"),
    verdictReasons: num("semq_verdict_reasons"),
    verdictRowCount: big("semq_verdict_row_count"),
    verdictRow: big("semq_verdict_row"),
    coreVersion: str("semq_core_version"),
    buildId: str("semq_build_id"),
    backendName: str("semq_backend_name"),
    statusName: str("semq_status_name"),
    sha256: nil("semq_sha256"),
  };
  if (core.coreVersion().split(".")[0] !== "1") throw new Error("unsupported SEMQ ABI major");
  probeBigIntBoundary(w, core);
  return core;
}

/** A u64 argument must cross as bigint. A module that legalizes i64 rejects
 * the bigint with a TypeError; surface that as a build error. */
function probeBigIntBoundary(w: SemqWasm, core: CoreExports): void {
  const out = w.malloc(32);
  try {
    core.sha256(0, 0n, out);
  } catch (e) {
    throw new Error(
      "the SEMQ wasm module does not pass uint64_t values as bigint " +
        `(rebuild with the default WASM_BIGINT; npm run build:wasm): ${e instanceof Error ? e.message : String(e)}`,
      { cause: e },
    );
  } finally {
    w.free(out);
  }
}
