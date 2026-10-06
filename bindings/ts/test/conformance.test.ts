// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

// The conformance vectors through the public surface: one test per case of
// tests/conformance/NN-name/manifest.json, mirroring the Python host runner
// case by case. Cases a host cannot execute (a duplicate manifest key, the
// FP rounding mode) are skipped as unsupported, as the vector document allows.

import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { beforeAll, describe, expect, it } from "vitest";

import {
  Codec,
  CodecConfig,
  type Diff,
  Encoding,
  Floor,
  FormatError,
  Incompatible,
  IntegrityError,
  InvalidInput,
  Native,
  Unsupported,
  load,
} from "../src/index.js";

// SEMQ_CONFORMANCE_DIR points at the vectors when a published package is
// tested outside the checkout; there, missing vectors are a failure.
const EXPLICIT = process.env.SEMQ_CONFORMANCE_DIR;
const ROOT = EXPLICIT ?? join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "tests", "conformance");
const AVAILABLE = existsSync(join(ROOT, "00-sha256-fips", "manifest.json"));
if (EXPLICIT !== undefined && !AVAILABLE) {
  throw new Error(`no conformance vectors under SEMQ_CONFORMANCE_DIR=${EXPLICIT}`);
}

const ERRORS = { InvalidInput, Incompatible, FormatError, IntegrityError, Unsupported, Native } as const;

// Manifest records are untyped JSON; `any` keeps each case readable.
/* eslint-disable @typescript-eslint/no-explicit-any */
type Any = Record<string, any>;

interface Expected {
  error?: keyof typeof ERRORS;
  row?: number | null;
  field?: number | null;
  which?: "content" | "state" | null;
}

interface Case {
  id: string;
  input: Any;
  expect: Any & Expected;
}

const hex = (u8: Uint8Array): string => Array.from(u8, (b) => b.toString(16).padStart(2, "0")).join("");
const unhex = (s: string): Uint8Array => new Uint8Array(Buffer.from(s, "hex"));
// `ignoreBOM` keeps a leading U+FEFF: the vectors carry ids and manifest
// text that start with one, and it is a character, not a byte-order mark.
const strict = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true });

function cases(name: string): Case[] {
  if (!AVAILABLE) return [];
  return (JSON.parse(readFileSync(join(ROOT, name, "manifest.json"), "utf8")) as { cases: Case[] }).cases;
}

function file(vector: string, name: string): Uint8Array {
  return new Uint8Array(readFileSync(join(ROOT, vector, name)));
}

/** A little-endian `.f32` file into a fresh, aligned Float32Array, bit-exact. */
function f32File(vector: string, name: string): Float32Array {
  const buf = readFileSync(join(ROOT, vector, name));
  const out = new Float32Array(buf.byteLength >>> 2);
  const bits = new Int32Array(out.buffer);
  const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  for (let i = 0; i < bits.length; i++) bits[i] = view.getInt32(4 * i, true);
  return out;
}

/** Big-endian hex bit patterns into float32 values. */
function f32FromHex(words: string[]): Float32Array {
  const out = new Float32Array(words.length);
  const bits = new Int32Array(out.buffer);
  words.forEach((w, i) => {
    bits[i] = parseInt(w, 16) | 0;
  });
  return out;
}

/** The float32 bit patterns as signed int32, for ulp distances. */
const bitsOf = (f: Float32Array): Int32Array => new Int32Array(f.buffer, f.byteOffset, f.length);

function configOf(spec: Any): CodecConfig {
  const p1: number = spec.bins ?? spec.sectors ?? spec.scale ?? spec.parameter;
  switch (spec.operator) {
    case "quant":
      return CodecConfig.quant(spec.dim, p1);
    case "phase":
      return CodecConfig.phase(spec.dim, p1);
    case "orbit":
      return CodecConfig.orbit(spec.dim, p1);
    default:
      throw new Error(`unknown operator ${spec.operator}`);
  }
}

const idsOf = (spec: Any): bigint[] | string[] =>
  spec.kind === "u64" ? (spec.values as string[]).map(BigInt) : [...(spec.values as string[])];

const range = (n: number): bigint[] => Array.from({ length: n }, (_, i) => BigInt(i));

const nullDiffs = (vector: string, pairs: string[][]): Diff[] =>
  pairs.map(([a, b]) => Encoding.fromBytes(file(vector, a!)).diff(Encoding.fromBytes(file(vector, b!))));

function assertError(e: unknown, want: Expected): void {
  expect(e).toBeInstanceOf(ERRORS[want.error!]);
  const got = e as { row?: number; field?: number; section?: number; which?: string };
  if (want.row != null) expect(got.row).toBe(want.row);
  if (want.field != null) expect(got.field ?? got.section).toBe(want.field);
  if (want.which != null) expect(got.which).toBe(want.which);
}

/** The floor's report form equals `want`, key order included, and `want`
 * constructs the same floor. */
function expectFloorReport(floor: Floor, want: Any): void {
  const got = JSON.parse(JSON.stringify(floor.asDict())) as Record<string, unknown>;
  expect(got).toEqual(want);
  expect(Object.keys(got)).toEqual(Object.keys(want));
  expect(Object.keys(got.config as object)).toEqual(Object.keys(want.config));
  expect(Floor.fromDict(want).equals(floor)).toBe(true);
}

/** Call fn; when the case expects an error, assert it; otherwise return the value. */
function runExpecting<T>(want: Expected, fn: () => T): T | undefined {
  if (want.error === undefined) return fn();
  let thrown: unknown;
  try {
    fn();
  } catch (e) {
    thrown = e;
  }
  if (thrown === undefined) throw new Error(`expected ${want.error}, nothing was thrown`);
  assertError(thrown, want);
  return undefined;
}

// ---------------------------------------------------------------------------

describe.skipIf(!AVAILABLE)("conformance", () => {
  beforeAll(async () => {
    await load();
  });

  describe("00-sha256-fips", () => {
    for (const { id, input: i, expect: e } of cases("00-sha256-fips")) {
      it(id, () => {
        const msg: string = "ascii" in i ? i.ascii : (i.repeat as string).repeat(i.count);
        // The host has no SHA-256 entry point; the identity contract is pinned
        // through state ids. node:crypto is the platform reference here.
        expect(createHash("sha256").update(msg, "ascii").digest("hex")).toBe(e.digest);
      });
    }
  });

  describe("01-config-canonical", () => {
    for (const { id, input: i, expect: e } of cases("01-config-canonical")) {
      it(id, () => {
        const cfg = runExpecting(e, () => configOf(i));
        if (cfg !== undefined) {
          expect(hex(cfg.toBytes())).toBe(e.bytes);
          expect(CodecConfig.fromBytes(cfg.toBytes()).equals(cfg)).toBe(true);
        }
      });
    }
  });

  describe("02-config-derived", () => {
    for (const { id, input: i, expect: e } of cases("02-config-derived")) {
      it(id, () => {
        const cfg = configOf(i);
        expect(cfg.bytesPerVector).toBe(e.bytes_per_vector);
        expect(cfg.unitsPerRow).toBe(e.units_per_row);
        if (i.operator === "quant") {
          const view = new DataView(new ArrayBuffer(4));
          view.setFloat32(0, cfg.maxMagnitude); // big-endian bit pattern
          expect(hex(new Uint8Array(view.buffer))).toBe(e.max_magnitude_bits);
        }
      });
    }
  });

  describe("03-encode", () => {
    for (const { id, input: i, expect: e } of cases("03-encode")) {
      it(id, async () => {
        const codec = await Codec.create(configOf(i.config));
        const [n, dim] = i.shape as [number, number];
        const vectors = f32File("03-encode", i.vectors_file);
        expect(vectors.length).toBe(n * dim);
        const enc = codec.encode({ ids: range(n), vectors });
        expect(enc.rows).toEqual(file("03-encode", e.rows_file));
        expect(codec.unpack(enc)).toEqual(file("03-encode", e.symbols_file));
      });
    }
  });

  describe("04-encode-rejects", () => {
    for (const { id, input: i, expect: e } of cases("04-encode-rejects")) {
      it(id, async () => {
        const cfg = configOf(i.config);
        const codec = await Codec.create(cfg);
        if ("host" in i) {
          // Representation checks the host performs before the core.
          if (id === "float64-input") {
            runExpecting(e, () => codec.encode({ ids: [1n], vectors: new Float64Array(cfg.dim) as never }));
          } else if (id === "wrong-width") {
            runExpecting(e, () => codec.encode({ ids: [1n], vectors: new Float32Array(cfg.dim - 1) }));
          } else {
            throw new Error(`unknown host case ${id}`);
          }
          return;
        }
        const kind = i.ids.kind as "u64" | "utf8";
        const ids = i.ids.values.length ? idsOf(i.ids) : [];
        if (id === "empty-without-kind") {
          runExpecting(e, () => codec.encode({ ids: [], vectors: new Float32Array(0) }));
          return;
        }
        const vectors = f32FromHex(i.vectors_f32).subarray(0, ids.length * cfg.dim);
        const enc = runExpecting(e, () => codec.encode({ ids, vectors, idKind: kind }));
        if (enc !== undefined) expect(hex(enc.contentDigest)).toBe(e.content_digest);
      });
    }
  });

  describe("05-decode", () => {
    for (const { id, input: i, expect: e } of cases("05-decode")) {
      it(id, async () => {
        const cfg = configOf(i.config);
        const codec = await Codec.create(cfg);
        const n: number = i.shape[0];
        const rows = file("05-decode", i.rows_file);
        expect(rows.length).toBe(n * cfg.bytesPerVector);
        const enc = new Encoding({ ids: range(n), rows, config: cfg });
        const got = bitsOf(codec.decode(enc));
        const want = bitsOf(f32File("05-decode", e.representatives_file));
        expect(got.length).toBe(want.length);
        let worst = 0;
        for (let k = 0; k < got.length; k++) worst = Math.max(worst, Math.abs(got[k]! - want[k]!));
        expect(worst).toBeLessThanOrEqual(e.tolerance_ulp);
      });
    }
  });

  describe("06-ids-canonical", () => {
    for (const { id, input: i, expect: e } of cases("06-ids-canonical")) {
      it(id, () => {
        const config = CodecConfig.quant(4, 4);
        const zeros = (n: number): Uint8Array => new Uint8Array(n * config.bytesPerVector);
        if (id === "utf8-too-long") {
          runExpecting(e, () => new Encoding({ ids: ["x".repeat(i.length)], rows: zeros(1), config }));
          return;
        }
        if (id === "lone-surrogate") {
          runExpecting(e, () => new Encoding({ ids: ["\ud800"], rows: zeros(1), config }));
          return;
        }
        const spec = i.ids;
        if ("values_hex" in spec) {
          // The host only accepts strings; bytes that are not UTF-8 cannot be
          // represented, so they are rejected on decoding, before the core.
          let ids: string[];
          try {
            ids = (spec.values_hex as string[]).map((h) => strict.decode(unhex(h)));
          } catch {
            expect(e.error).toBe("InvalidInput");
            return;
          }
          runExpecting(e, () => new Encoding({ ids, rows: zeros(ids.length), config }));
          return;
        }
        const ids = idsOf(spec);
        const enc = new Encoding({ ids, rows: zeros(ids.length), config, idKind: spec.kind });
        expect((enc.ids as Array<bigint | string>).map(String)).toEqual(e.sorted);
        const image = enc.toBytes();
        expect(hex(image.subarray(28, 28 + e.ids_section.length / 2))).toBe(e.ids_section);
      });
    }
  });

  describe("07-manifest-canonical", () => {
    for (const { id, input: i, expect: e } of cases("07-manifest-canonical")) {
      // Non-ASCII inputs travel as hex; bytes that are not UTF-8 cannot become
      // a string, so the host rejects them before the core.
      let raw: Array<[string, string]> | undefined;
      try {
        raw =
          i.pairs ??
          (i.pairs_hex as string[][]).map(([k, v]): [string, string] => [
            strict.decode(unhex(k!)),
            strict.decode(unhex(v!)),
          ]);
      } catch {
        raw = undefined;
      }
      // A Record cannot carry a duplicate key; the host has no way to send
      // one, so the core's rejection is exercised by the C tests.
      const duplicate = raw !== undefined && new Set(raw.map(([k]) => k)).size !== raw.length;
      it.skipIf(duplicate)(id, () => {
        if (raw === undefined) {
          expect(e.error).toBe("InvalidInput");
          return;
        }
        const pairs: Record<string, string> = Object.fromEntries(raw);
        const config = CodecConfig.quant(4, 4);
        const enc = runExpecting(
          e,
          () => new Encoding({ ids: [], rows: new Uint8Array(0), config, manifest: pairs, idKind: "u64" }),
        );
        if (enc !== undefined) {
          const image = enc.toBytes();
          expect(hex(image.subarray(28, image.length - 64))).toBe(e.manifest_section);
          expect(hex(enc.stateId)).toBe(e.state_id);
          expect(enc.manifest).toEqual(pairs);
        }
      });
    }
  });

  describe("08-digests", () => {
    for (const { id, input: i, expect: e } of cases("08-digests")) {
      it(id, async () => {
        if ("file" in i) {
          const enc = Encoding.fromBytes(file("08-digests", i.file));
          expect(enc.config.equals(configOf(i.config))).toBe(true);
          expect(hex(enc.contentDigest)).toBe(e.content_digest);
          expect(hex(enc.stateId)).toBe(e.state_id);
          return;
        }
        const codec = await Codec.create(configOf(i.config));
        const dim = codec.config.dim;
        const vectors = f32File("08-digests", i.vectors_file);
        for (const order of i.orders as string[][]) {
          const ids = order.map(BigInt);
          const rows = new Float32Array(ids.length * dim);
          ids.forEach((v, k) => rows.set(vectors.subarray((Number(v) - 1) * dim, Number(v) * dim), k * dim));
          expect(hex(codec.encode({ ids, vectors: rows }).stateId)).toBe(e.state_id);
        }
      });
    }
  });

  describe("09-file", () => {
    for (const { id, input: i, expect: e } of cases("09-file")) {
      it(id, () => {
        let buf = file("09-file", i.file);
        if ("mutate" in i) {
          const m = i.mutate;
          switch (m.kind) {
            case "xor_byte":
              buf[m.at]! ^= m.value;
              break;
            case "set_byte":
              buf[m.at] = m.value;
              break;
            case "truncate":
              buf = buf.slice(0, m.at);
              break;
            case "append_byte": {
              const longer = new Uint8Array(buf.length + 1);
              longer.set(buf);
              longer[buf.length] = m.value;
              buf = longer;
              break;
            }
            default:
              throw new Error(`unknown mutation ${m.kind}`);
          }
        }
        const enc = runExpecting(e, () => Encoding.fromBytes(buf));
        if (enc !== undefined) {
          expect(buf.length).toBe(e.file_size);
          expect(hex(enc.stateId)).toBe(e.state_id);
          expect(enc.length).toBe(e.n);
          expect(enc.idKind).toBe(e.id_kind);
          expect(enc.toBytes()).toEqual(buf);
        }
      });
    }
  });

  describe("10-concat", () => {
    for (const { id, input: i, expect: e } of cases("10-concat")) {
      it(id, () => {
        const parts = (i.files as string[]).map((f) => Encoding.fromBytes(file("10-concat", f)));
        const result = runExpecting(e, () => parts[0]!.concat(...parts.slice(1)));
        if (result !== undefined) {
          expect(hex(result.stateId)).toBe(e.state_id);
          expect(result.length).toBe(e.n);
        }
      });
    }
  });

  describe("11-diff", () => {
    for (const { id, input: i, expect: e } of cases("11-diff")) {
      it(id, () => {
        const ref = Encoding.fromBytes(file("11-diff", i.reference));
        const cand = Encoding.fromBytes(file("11-diff", i.candidate));
        const d = runExpecting(e, () => ref.diff(cand));
        if (d !== undefined) {
          expect(d.asDict()).toEqual(e.report);
          if ("units_of" in i) expect(d.units(BigInt(i.units_of))).toEqual(e.units);
        }
      });
    }
  });

  describe("12-floor", () => {
    for (const { id, input: i, expect: e } of cases("12-floor")) {
      it(id, () => {
        if ("null_diffs" in i) {
          const diffs = nullDiffs("12-floor", i.null_diffs);
          const floor = runExpecting(e, () => Floor.measure(diffs));
          if (floor !== undefined) {
            expectFloorReport(floor, e.floor);
            for (const d of diffs) expect(d.within(floor)).toBe(true);
          }
          return;
        }
        const ref = Encoding.fromBytes(file("12-floor", i.reference));
        const d = ref.diff(Encoding.fromBytes(file("12-floor", i.candidate)));
        // The `floor-*` cases are rejected by `fromDict` before the floor is applied.
        const verdict = runExpecting(e, () => d.evaluate(Floor.fromDict(i.floor), { perRow: i.per_row === true }));
        if (verdict !== undefined) {
          const floor = Floor.fromDict(i.floor);
          expect(floor.asDict()).toEqual(i.floor);
          expect({ ...verdict, rows: verdict.rows.map(String) }).toEqual(e.evaluate);
          expect(d.within(floor)).toBe(e.within);
        }
      });
    }
  });

  describe("13-report", () => {
    for (const { id, input: i, expect: e } of cases("13-report")) {
      it(id, () => {
        if ("report" in e) {
          const ref = Encoding.fromBytes(file("13-report", i.reference));
          const d = ref.diff(Encoding.fromBytes(file("13-report", i.candidate)));
          expect(JSON.parse(JSON.stringify(d.asDict()))).toEqual(e.report);
          return;
        }
        expectFloorReport(Floor.measure(nullDiffs("13-report", i.null_diffs)), e.floor);
      });
    }
  });

  describe("15-fp-environment", () => {
    for (const { id, input: i, expect: e } of cases("15-fp-environment")) {
      if ("rounding_mode" in i) {
        // unsupported: the host cannot set the FP rounding mode.
        it.skip(id, () => {});
        continue;
      }
      it(id, async () => {
        const codec = await Codec.create(configOf(i.config));
        const enc = codec.encode({ ids: idsOf(i.ids), vectors: f32FromHex(i.vectors_f32) });
        expect(hex(enc.contentDigest)).toBe(e.content_digest);
      });
    }
  });
});
