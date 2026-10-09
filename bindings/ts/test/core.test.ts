// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

// The public surface against the specification examples: canonical config
// form, digests, the file image, the input contract, concat, diff, floor
// and build information. Expected values match tests/unit/test_core.c.

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

import { beforeAll, describe, expect, it } from "vitest";

import {
  Codec,
  CodecConfig,
  Diff,
  Encoding,
  Floor,
  FormatError,
  Incompatible,
  IntegrityError,
  InvalidInput,
  Native,
  Operator,
  buildInfo,
  load,
} from "../src/index.js";

const hex = (u8: Uint8Array): string => Array.from(u8, (b) => b.toString(16).padStart(2, "0")).join("");
const bytes = (...v: number[]): Uint8Array => Uint8Array.from(v);

/** Run `fn`, return what it throws. */
function capture(fn: () => unknown): unknown {
  try {
    fn();
  } catch (e) {
    return e;
  }
  throw new Error("expected a throw");
}

const EMPTY_CONTENT = "4528e8a0422f5cde968847e021c85b4e6e78ce68da9e92b2981c62dd48f78f4a";
const EMPTY_STATE = "ef4d1522eb158aa9b6b83cd5d51f80ea2cc59ac3aeb45b69a1c28c99375b55b9";
const EMPTY_IMAGE =
  "53454d51020002040000000400000000000000000000000000000000000000004528e8a0422f5cde968847e021c85b4e6e78ce68da9e92b2981c62dd48f78f4aef4d1522eb158aa9b6b83cd5d51f80ea2cc59ac3aeb45b69a1c28c99375b55b9";

it("raises Native before the runtime is loaded", () => {
  const e = capture(() => CodecConfig.quant(4, 4));
  expect(e).toBeInstanceOf(Native);
  expect((e as Native).operation).toBe("load");
  expect((e as Native).coreVersion).toBe("unavailable");
});

describe("core", () => {
  beforeAll(async () => {
    await load();
  });

  const quant44 = (): CodecConfig => CodecConfig.quant(4, 4);
  const empty = (config = quant44()): Encoding =>
    new Encoding({ ids: [], rows: new Uint8Array(0), config, idKind: "u64" });

  // ---- CodecConfig --------------------------------------------------------

  describe("CodecConfig", () => {
    it("has the canonical form, equality and derived quantities", () => {
      const c = quant44();
      expect(hex(c.toBytes())).toBe("02040000000400000000000000");
      const back = CodecConfig.fromBytes(c.toBytes());
      expect(back.equals(c)).toBe(true);
      expect(c.equals(CodecConfig.quant(4, 3))).toBe(false);
      expect(c.operator).toBe(Operator.Quant);
      expect(c.dim).toBe(4);
      expect(c.bins).toBe(4);
      expect(c.ruleRevision).toBe(0);
      expect(c.bytesPerVector).toBe(2);
      expect(c.unitsPerRow).toBe(4);
      expect(c.maxMagnitude).toBe(1.0);
      expect(c.asDict()).toEqual({ operator: "quant", dim: 4, bins: 4, rule_revision: 0 });
      expect(String(c)).toBe("CodecConfig.quant(dim=4, bins=4)");

      expect(CodecConfig.phase(8, 16).bytesPerVector).toBe(2);
      expect(CodecConfig.phase(8, 16).unitsPerRow).toBe(4);
      expect(CodecConfig.phase(8, 17).bytesPerVector).toBe(4);
      const o = CodecConfig.orbit(5);
      expect(o.scale).toBe(50);
      expect(o.bytesPerVector).toBe(5);
      expect(o.unitsPerRow).toBe(5);
      expect(o.asDict()).toEqual({ operator: "orbit", dim: 5, scale: 50, rule_revision: 0 });
      expect(CodecConfig.phase(6, 17).sectors).toBe(17);
      expect(CodecConfig.quant(1024, 64).bytesPerVector).toBe(896);
      expect(CodecConfig.quant(3, 4).bytesPerVector).toBe(2);
      expect(CodecConfig.orbit(8, 1 << 30).scale).toBe(1 << 30);
    });

    it("refuses the parameter of another operator", () => {
      expect(() => quant44().scale).toThrow(InvalidInput);
      expect(() => quant44().sectors).toThrow(InvalidInput);
      expect(() => CodecConfig.orbit(4).bins).toThrow(InvalidInput);
      expect(() => CodecConfig.orbit(4).maxMagnitude).toThrow(InvalidInput);
    });

    it("rejects out-of-range parameters with the field", () => {
      expect((capture(() => CodecConfig.quant(4, 1)) as InvalidInput).field).toBe(2);
      expect(() => CodecConfig.quant(4, 65)).toThrow(InvalidInput);
      expect((capture(() => CodecConfig.quant(0, 4)) as InvalidInput).field).toBe(1);
      expect(() => CodecConfig.quant(65537, 4)).toThrow(InvalidInput);
      expect(() => CodecConfig.phase(7, 16)).toThrow(InvalidInput);
      expect(() => CodecConfig.phase(6, 16)).toThrow(InvalidInput);
      expect(() => CodecConfig.phase(8, 1)).toThrow(InvalidInput);
      expect(() => CodecConfig.phase(8, 257)).toThrow(InvalidInput);
      expect(() => CodecConfig.orbit(8, 0)).toThrow(InvalidInput);
      expect(() => CodecConfig.orbit(8, (1 << 30) + 1)).toThrow(InvalidInput);
      expect(() => CodecConfig.quant(4.5, 4)).toThrow(InvalidInput);
      expect(() => CodecConfig.quant(-1, 4)).toThrow(InvalidInput);
      expect(() => CodecConfig.fromBytes(bytes(3, 4, 0, 0, 0, 4, 0, 0, 0, 0, 0, 0, 0))).toThrow(InvalidInput);
      const rev = capture(() => CodecConfig.fromBytes(bytes(2, 4, 0, 0, 0, 4, 0, 0, 0, 1, 0, 0, 0)));
      expect(rev).toBeInstanceOf(InvalidInput);
      expect((rev as InvalidInput).field).toBe(3);
      expect(() => CodecConfig.fromBytes(new Uint8Array(12))).toThrow(InvalidInput);
    });
  });

  // ---- digests and the file image ----------------------------------------

  describe("Encoding identities", () => {
    it("matches the specification examples for the empty encoding", () => {
      const e = empty();
      expect(e.length).toBe(0);
      expect(e.idKind).toBe("u64");
      expect(hex(e.contentDigest)).toBe(EMPTY_CONTENT);
      expect(hex(e.stateId)).toBe(EMPTY_STATE);
      const img = e.toBytes();
      expect(img.length).toBe(96);
      expect(hex(img)).toBe(EMPTY_IMAGE);
      const back = Encoding.fromBytes(img);
      expect(back.length).toBe(0);
      expect(back.idKind).toBe("u64");
      expect(back.ids).toEqual([]);
      expect(back.rows.length).toBe(0);
      expect(back.config.equals(quant44())).toBe(true);
    });

    it("matches the specification examples for one row with a manifest", () => {
      const e = new Encoding({ ids: [7n], rows: bytes(0x07, 0x07), config: quant44(), manifest: { encoder: "x" } });
      expect(hex(e.contentDigest)).toBe("1a3d8e8bfbf3429525d0bc11e18a17b75ea49af40b6b441f6863444f71230489");
      expect(hex(e.stateId)).toBe("07d119f5a0a76de95bd4b41110d6005e6fc38cfc398421dd15df2be68adf9f85");
      expect(e.manifest).toEqual({ encoder: "x" });
      expect(e.get(7n)).toEqual(bytes(0x07, 0x07));
      expect(e.get(8n)).toBeUndefined();
      expect(() => e.get("7")).toThrow(InvalidInput);
      expect(e.row(0)).toEqual(bytes(0x07, 0x07));
      expect(() => e.row(1)).toThrow(InvalidInput);
      const back = Encoding.fromBytes(e.toBytes());
      expect(back.stateId).toEqual(e.stateId);
      expect(back.manifest).toEqual({ encoder: "x" });
      expect([...back]).toEqual([[7n, bytes(0x07, 0x07)]]);
    });

    it("keeps the manifest in canonical order and inside stateId only", () => {
      const a = new Encoding({ ids: [1n], rows: bytes(0, 0), config: quant44(), manifest: { b: "2", a: "1" } });
      const b = new Encoding({ ids: [1n], rows: bytes(0, 0), config: quant44() });
      expect(Object.keys(a.manifest)).toEqual(["a", "b"]);
      expect(a.contentDigest).toEqual(b.contentDigest);
      expect(a.stateId).not.toEqual(b.stateId);
    });

    it("keeps a manifest key named __proto__ as an own property", async () => {
      // JSON.parse creates an own property; a literal { __proto__: ... } would not.
      const manifest = JSON.parse('{"__proto__": "a", "k": "v"}') as Record<string, string>;
      expect(Object.hasOwn(manifest, "__proto__")).toBe(true);
      const e = new Encoding({ ids: [1n], rows: bytes(0, 0), config: quant44(), manifest });
      const got = e.manifest;
      expect(Object.hasOwn(got, "__proto__")).toBe(true);
      expect(Object.getPrototypeOf(got)).toBe(Object.prototype);
      expect(Object.entries(got)).toEqual([
        ["__proto__", "a"],
        ["k", "v"],
      ]);
      expect(JSON.stringify(got)).toBe('{"__proto__":"a","k":"v"}');
      const back = Encoding.fromBytes(e.toBytes());
      expect(back.stateId).toEqual(e.stateId);
      expect(Object.entries(back.manifest)).toEqual(Object.entries(got));
      const rebuilt = new Encoding({ ids: [1n], rows: bytes(0, 0), config: quant44(), manifest: back.manifest });
      expect(rebuilt.stateId).toEqual(e.stateId);
      const without = new Encoding({ ids: [1n], rows: bytes(0, 0), config: quant44(), manifest: { k: "v" } });
      expect(without.stateId).not.toEqual(e.stateId);
      const codec = await Codec.create(quant44());
      const encoded = codec.encode({ ids: [1n], vectors: Float32Array.from([1, 0, 0, 0]), manifest });
      expect(Object.entries(encoded.manifest)).toEqual(Object.entries(got));
      codec.dispose();
    });

    it("rejects non-canonical rows, duplicates and bad representations", () => {
      const c = quant44();
      const padding = capture(() => new Encoding({ ids: [1n], rows: bytes(0x07, 0x17), config: c }));
      expect(padding).toBeInstanceOf(InvalidInput);
      expect((padding as InvalidInput).row).toBe(0);
      expect((padding as InvalidInput).field).toBeUndefined();
      const sector = capture(() => new Encoding({ ids: [1n], rows: bytes(0x90), config: CodecConfig.phase(4, 8) }));
      expect((sector as InvalidInput).field).toBe(1);
      const dup = capture(() => new Encoding({ ids: [5n, 9n, 5n], rows: new Uint8Array(6), config: c }));
      expect(dup).toBeInstanceOf(InvalidInput);
      expect((dup as InvalidInput).row).toBe(2);
      expect(() => new Encoding({ ids: [1n], rows: new Uint8Array(3), config: c })).toThrow(InvalidInput);
      expect(() => new Encoding({ ids: [], rows: new Uint8Array(0), config: c })).toThrow(InvalidInput);
      expect(() => new Encoding({ ids: [1n], rows: [7, 7] as never, config: c })).toThrow(InvalidInput);
      expect(() => new Encoding({ ids: [1] as never, rows: bytes(0, 0), config: c })).toThrow(InvalidInput);
      expect(() => new Encoding({ ids: [1n], rows: bytes(0, 0), config: c, idKind: "utf8" })).toThrow(InvalidInput);
      expect(() => new Encoding({ ids: [1n], rows: bytes(0, 0), config: {} as never })).toThrow(InvalidInput);
      expect(() => Encoding.fromBytes("not bytes" as never)).toThrow(InvalidInput);
      const man = capture(() => new Encoding({ ids: [1n], rows: bytes(0, 0), config: c, manifest: { k: 1 as never } }));
      expect((man as InvalidInput).field).toBe(0);
      const lone = capture(() => new Encoding({ ids: [1n], rows: bytes(0, 0), config: c, manifest: { k: "\ud800" } }));
      expect(lone).toBeInstanceOf(InvalidInput);
    });
  });

  // ---- Codec ----------------------------------------------------------------

  describe("Codec", () => {
    const vectors = Float32Array.from([0.5, 0.5, 0.5, 0.5, -0.5, -0.5, -0.5, -0.5, 1, 0, 0, 0]);

    it("sorts ids, maps symbols and decodes representatives", async () => {
      const codec = await Codec.create(quant44());
      expect(codec.config.equals(quant44())).toBe(true);
      expect(codec.backend).not.toBe("");
      const e = codec.encode({ ids: [3n, 1n, 2n], vectors });
      expect(e.ids).toEqual([1n, 2n, 3n]);
      expect(e.length).toBe(3);
      expect(Array.from(codec.unpack(e))).toEqual([2, 2, 2, 2, 7, 4, 4, 4, 6, 6, 6, 6]);
      const rep = codec.decode(e);
      expect(rep.length).toBe(12);
      expect(rep[0]).toBe(-0.625);
      expect(rep[4]).toBe(0.875);
      expect(rep[5]).toBe(0.125);
      expect(rep[8]).toBe(0.625);
      const e2 = codec.encode({ ids: [3n, 1n, 2n], vectors });
      expect(e2.stateId).toEqual(e.stateId);
      expect([...e].map(([id]) => id)).toEqual([1n, 2n, 3n]);
      codec.dispose();
      codec.dispose();
      expect(() => codec.encode({ ids: [1n], vectors: vectors.subarray(0, 4) })).toThrow(InvalidInput);
    });

    it("runs the three operators and refuses cross-config use", async () => {
      const co = await Codec.create(CodecConfig.orbit(4, 50));
      const cp = await Codec.create(CodecConfig.phase(4, 16));
      const v = Float32Array.from([0.5, 0.5, -0.5, 0.5]);
      const eo = co.encode({ ids: [1n], vectors: v });
      const ep = cp.encode({ ids: [1n], vectors: v });
      expect(Array.from(co.unpack(eo))).toEqual([7, 7, 16, 7]);
      expect(Array.from(cp.unpack(ep))).toEqual([10, 14]); // 45 degrees starts sector 10, 135 degrees starts sector 14
      const rep = co.decode(eo);
      expect(rep[0]).toBeCloseTo(0.14, 6);
      expect(rep[2]).toBeCloseTo(-0.14, 6);
      expect(() => co.decode(ep)).toThrow(Incompatible);
      expect(() => co.unpack(ep)).toThrow(Incompatible);
    });

    it("canonicalizes subnormals", async () => {
      const codec = await Codec.create(quant44());
      const a = codec.encode({ ids: [1n], vectors: Float32Array.from([1, 1e-40, -1e-41, 0]) });
      const b = codec.encode({ ids: [1n], vectors: Float32Array.from([1, 0, 0, 0]) });
      expect(a.contentDigest).toEqual(b.contentDigest);
    });

    it("rejects rows and representations with the row index", async () => {
      const codec = await Codec.create(quant44());
      const ids = [1n, 2n];
      const v = Float32Array.from([1, 0, 0, 0, 0, 1, 0, 0]);
      v[6] = NaN;
      const nan = capture(() => codec.encode({ ids, vectors: v }));
      expect(nan).toBeInstanceOf(InvalidInput);
      expect((nan as InvalidInput).row).toBe(1);
      expect((nan as InvalidInput).field).toBe(2);
      v[6] = 0;
      v[0] = 0.9;
      const norm = capture(() => codec.encode({ ids, vectors: v }));
      expect(norm).toBeInstanceOf(InvalidInput);
      expect((norm as InvalidInput).row).toBe(0);
      v[0] = 1;
      const edge = Float32Array.from([1, 0.03125, 0, 0]);
      expect(codec.encode({ ids: [1n], vectors: edge }).length).toBe(1);
      edge[1] = 0.0316;
      expect(() => codec.encode({ ids: [1n], vectors: edge })).toThrow(InvalidInput);
      const dup = capture(() => codec.encode({ ids: [4n, 4n], vectors: v }));
      expect((dup as InvalidInput).row).toBe(1);
      expect(codec.encode({ ids: [], vectors: new Float32Array(0), idKind: "u64" }).length).toBe(0);
      expect(() => codec.encode({ ids: [], vectors: new Float32Array(0) })).toThrow(InvalidInput);
      expect(() => codec.encode({ ids, vectors: v.subarray(0, 7) })).toThrow(InvalidInput);
      expect(() => codec.encode({ ids, vectors: Float64Array.from(v) as never })).toThrow(InvalidInput);
      expect(() => codec.encode({ ids, vectors: Array.from(v) as never })).toThrow(InvalidInput);
      const num = capture(() => codec.encode({ ids: [1, 2] as never, vectors: v }));
      expect(num).toBeInstanceOf(InvalidInput);
      expect((num as InvalidInput).row).toBe(0);
      const mixed = capture(() => codec.encode({ ids: [1n, "2"] as never, vectors: v }));
      expect((mixed as InvalidInput).row).toBe(1);
      const lone = capture(() => codec.encode({ ids: ["a", "\ud800"], vectors: v }));
      expect(lone).toBeInstanceOf(InvalidInput);
      expect((lone as InvalidInput).row).toBe(1);
      const big = capture(() => codec.encode({ ids: [1n, 1n << 64n], vectors: v }));
      expect(big).toBeInstanceOf(InvalidInput);
      expect((big as InvalidInput).row).toBe(1);
      const neg = capture(() => codec.encode({ ids: [-1n, 1n], vectors: v }));
      expect((neg as InvalidInput).row).toBe(0);
      const emptyId = capture(() => codec.encode({ ids: ["a", ""], vectors: v }));
      expect((emptyId as InvalidInput).row).toBe(1);
      expect(() => codec.encode({ ids, vectors: v, idKind: "u32" as never })).toThrow(InvalidInput);
      expect(() => codec.encode({ ids, vectors: v, manifest: ["x"] as never })).toThrow(InvalidInput);
      expect(() => codec.decode({} as never)).toThrow(InvalidInput);
    });

    it("keeps u64 precision up to 2^64 - 1", async () => {
      const codec = await Codec.create(quant44());
      const max = (1n << 64n) - 1n;
      const e = codec.encode({ ids: [max, 0n, 1n << 53n], vectors });
      expect(e.ids).toEqual([0n, 1n << 53n, max]);
      expect(e.get(max)).toEqual(e.row(2));
      const back = Encoding.fromBytes(e.toBytes());
      expect(back.ids).toEqual([0n, 1n << 53n, max]);
      const d = empty().diff(e);
      expect(d.added).toEqual([0n, 1n << 53n, max]);
      expect(d.asDict().added).toEqual(["0", "9007199254740992", "18446744073709551615"]);
    });
  });

  // ---- file reader ------------------------------------------------------------

  describe("Encoding.fromBytes", () => {
    const sample = (): Encoding =>
      new Encoding({ ids: [10n, 20n], rows: bytes(0x07, 0x07, 0x24, 0x01), config: quant44() });

    /** Recompute both footer digests of an image with an empty manifest. */
    const refreshFooter = (img: Uint8Array): void => {
      const len = img.length;
      const content = createHash("sha256")
        .update(img.subarray(6, len - 64 - 4))
        .digest();
      img.set(content, len - 64);
      const state = createHash("sha256")
        .update(content)
        .update(img.subarray(len - 64 - 4, len - 64))
        .digest();
      img.set(state, len - 32);
    };

    it("detects corruption, truncation and structural faults", () => {
      const img = sample().toBytes();
      expect(img.length).toBe(28 + 16 + 4 + 4 + 64);

      let copy = img.slice();
      copy[28 + 16]! ^= 0x01;
      const content = capture(() => Encoding.fromBytes(copy));
      expect(content).toBeInstanceOf(IntegrityError);
      expect((content as IntegrityError).which).toBe("content");

      expect(() => Encoding.fromBytes(img.subarray(0, img.length - 1))).toThrow(FormatError);
      const trailing = new Uint8Array(img.length + 1);
      trailing.set(img);
      expect(() => Encoding.fromBytes(trailing)).toThrow(FormatError);

      copy = img.slice();
      copy[4] = 1;
      const v1 = capture(() => Encoding.fromBytes(copy));
      expect(v1).toBeInstanceOf(FormatError);
      expect((v1 as FormatError).section).toBe(0);
      copy[4] = 3;
      expect(() => Encoding.fromBytes(copy)).toThrow(FormatError);
      copy = img.slice();
      copy[0] = "X".charCodeAt(0);
      expect(() => Encoding.fromBytes(copy)).toThrow(FormatError);

      copy = img.slice();
      copy[25] = 0x01;
      const sizes = capture(() => Encoding.fromBytes(copy));
      expect((sizes as FormatError).section).toBe(2);

      copy = img.slice();
      copy[28] = 30;
      refreshFooter(copy);
      const order = capture(() => Encoding.fromBytes(copy));
      expect(order).toBeInstanceOf(FormatError);
      expect((order as FormatError).section).toBe(3);

      copy = img.slice();
      copy[28 + 16 + 1]! |= 0x10;
      refreshFooter(copy);
      const rows = capture(() => Encoding.fromBytes(copy));
      expect(rows).toBeInstanceOf(FormatError);
      expect((rows as FormatError).section).toBe(6);
      expect((rows as FormatError).row).toBe(0);

      copy = img.slice();
      const other = empty().toBytes();
      copy.set(other.subarray(other.length - 64), copy.length - 64);
      expect((capture(() => Encoding.fromBytes(copy)) as IntegrityError).which).toBe("content");

      const withMan = new Encoding({
        ids: [10n, 20n],
        rows: bytes(0x07, 0x07, 0x24, 0x01),
        config: quant44(),
        manifest: { k: "v" },
      }).toBytes();
      withMan[withMan.length - 64 - 1] = "w".charCodeAt(0);
      const state = capture(() => Encoding.fromBytes(withMan));
      expect(state).toBeInstanceOf(IntegrityError);
      expect((state as IntegrityError).which).toBe("state");
    });

    it("sorts utf8 ids bytewise and round-trips them", () => {
      const e = new Encoding({ ids: ["b", "a", "ab"], rows: bytes(1, 0, 2, 0, 3, 0), config: quant44() });
      expect(e.idKind).toBe("utf8");
      expect(e.ids).toEqual(["a", "ab", "b"]);
      expect(Array.from(e.rows)).toEqual([2, 0, 3, 0, 1, 0]);
      expect(e.get("ab")).toEqual(bytes(3, 0));
      expect(e.get("zz")).toBeUndefined();
      expect(() => e.get(1n)).toThrow(InvalidInput);
      expect(() => e.get("\udc00")).toThrow(InvalidInput);
      const back = Encoding.fromBytes(e.toBytes());
      expect(back.stateId).toEqual(e.stateId);
      expect([...back]).toEqual([
        ["a", bytes(2, 0)],
        ["ab", bytes(3, 0)],
        ["b", bytes(1, 0)],
      ]);
      const unicode = new Encoding({ ids: ["é", "😀", "z"], rows: bytes(0, 0, 0, 0, 0, 0), config: quant44() });
      expect(unicode.ids).toEqual(["z", "é", "😀"]);
      expect(Encoding.fromBytes(unicode.toBytes()).ids).toEqual(["z", "é", "😀"]);
    });

    it("keeps a leading U+FEFF in ids and manifest text", () => {
      const e = new Encoding({ ids: ["x", "\ufeffx"], rows: bytes(1, 0, 2, 0), config: quant44() });
      expect(e.ids).toEqual(["x", "\ufeffx"]);
      expect(e.get("x")).toEqual(bytes(1, 0));
      expect(e.get("\ufeffx")).toEqual(bytes(2, 0));
      expect([...e]).toEqual([
        ["x", bytes(1, 0)],
        ["\ufeffx", bytes(2, 0)],
      ]);
      const back = Encoding.fromBytes(e.toBytes());
      expect(back.ids).toEqual(["x", "\ufeffx"]);
      // The accessors reproduce the state: no two ids collapsed into one.
      const rebuilt = new Encoding({ ids: back.ids, rows: back.rows, config: back.config, manifest: back.manifest });
      expect(rebuilt.stateId).toEqual(e.stateId);
      const changed = new Encoding({ ids: ["x", "\ufeffx"], rows: bytes(1, 0, 3, 0), config: quant44() });
      const d = e.diff(changed);
      expect(d.changed).toEqual([["\ufeffx", 1]]);
      expect(d.units("\ufeffx")).toEqual([[0, 2, 3]]);
      expect(d.units("x")).toEqual([]);
      expect(d.asDict().changed).toEqual([["\ufeffx", 1]]);
      const m = new Encoding({
        ids: [1n],
        rows: bytes(0, 0),
        config: quant44(),
        manifest: { "\ufeffk": "\ufeffv", k: "v" },
      });
      expect(Object.entries(m.manifest)).toEqual([
        ["k", "v"],
        ["\ufeffk", "\ufeffv"],
      ]);
      const n = new Encoding({ ids: [1n], rows: bytes(0, 0), config: quant44(), manifest: { "\ufeffk": "w", k: "v" } });
      expect(m.diff(n).manifestChanges).toEqual({ "\ufeffk": ["\ufeffv", "w"] });
    });
  });

  // ---- concat ---------------------------------------------------------------

  describe("concat", () => {
    it("is order independent with the empty encoding as neutral element", () => {
      const c = quant44();
      const ids = [1n, 2n, 3n];
      const rows = bytes(0x07, 0x07, 0x24, 0x01, 0x11, 0x02);
      const whole = new Encoding({ ids, rows, config: c });
      const parts = ids.map((id, i) => new Encoding({ ids: [id], rows: rows.slice(2 * i, 2 * i + 2), config: c }));
      const [p0, p1, p2] = parts as [Encoding, Encoding, Encoding];
      expect(p0.concat(p1, p2).stateId).toEqual(whole.stateId);
      expect(p2.concat(p0, p1).stateId).toEqual(whole.stateId);
      expect(whole.concat(empty()).stateId).toEqual(whole.stateId);
      expect(empty().concat(whole).stateId).toEqual(whole.stateId);
      const overlap = capture(() => whole.concat(p1));
      expect(overlap).toBeInstanceOf(InvalidInput);
      expect((overlap as InvalidInput).field).toBe(1);
      const m = new Encoding({ ids: [3n], rows: rows.slice(4, 6), config: c, manifest: { encoder: "x" } });
      expect(() => p0.concat(m)).toThrow(InvalidInput);
      const other = new Encoding({ ids: [3n], rows: rows.slice(2, 4), config: CodecConfig.quant(4, 3) });
      expect(() => p0.concat(other)).toThrow(Incompatible);
      const utf = new Encoding({ ids: ["a"], rows: rows.slice(0, 2), config: c });
      expect(() => p0.concat(utf)).toThrow(Incompatible);
      expect(() => p0.concat({} as never)).toThrow(InvalidInput);
    });
  });

  // ---- diff, within, measure ------------------------------------------------

  describe("Diff", () => {
    let c: CodecConfig;
    beforeAll(() => {
      c = quant44();
    });
    const refIds = [1n, 2n, 3n];
    const refRows = bytes(0x07, 0x07, 0x24, 0x01, 0x11, 0x02);
    const refMan = { encoder: "m1", note: "a" };
    const reference = (): Encoding => new Encoding({ ids: refIds, rows: refRows, config: c, manifest: refMan });
    const candidate = (): Encoding =>
      new Encoding({
        ids: [2n, 3n, 4n],
        rows: bytes(0x24, 0x01, 0x11, 0x06, 0x00, 0x00),
        config: c,
        manifest: { encoder: "m1", run: "7" },
      });

    it("lists ids, units and manifest changes and outlives its encodings", () => {
      const ref = reference();
      const cand = candidate();
      const d = ref.diff(cand);
      expect(d).toBeInstanceOf(Diff);
      expect(d.idKind).toBe("u64");
      expect(d.config.equals(c)).toBe(true);
      expect(d.referenceId).toEqual(ref.stateId);
      expect(d.candidateId).toEqual(cand.stateId);
      expect(d.added).toEqual([4n]);
      expect(d.removed).toEqual([1n]);
      expect(d.changed).toEqual([[3n, 1]]);
      expect(d.nUnchanged).toBe(1);
      expect(d.units(3n)).toEqual([[3, 1, 3]]);
      expect(d.units(2n)).toEqual([]);
      expect(() => d.units(1n)).toThrow(InvalidInput);
      expect(() => d.units("3")).toThrow(InvalidInput);
      expect(d.manifestChanges).toEqual({ note: ["a", null], run: [null, "7"] });
      ref.dispose();
      cand.dispose();
      expect(() => ref.rows).toThrow(InvalidInput);
      expect(d.units(3n)).toEqual([[3, 1, 3]]);
      const wide = new Floor({
        config: c,
        idKind: "u64",
        referenceId: d.referenceId,
        nulls: 1,
        changedRows: 4,
        totalRows: 4,
        hamming: 4,
      });
      expect(d.within(wide)).toBe(false);
      expect(() => d.within({} as never)).toThrow(InvalidInput);
      expect(d.asDict()).toEqual({
        reference_id: hex(d.referenceId),
        candidate_id: hex(d.candidateId),
        id_kind: "u64",
        config: { operator: "quant", dim: 4, bins: 4, rule_revision: 0 },
        added: ["4"],
        removed: ["1"],
        changed: [["3", 1]],
        n_unchanged: 1,
        manifest_changes: { note: ["a", null], run: [null, "7"] },
      });
      expect(JSON.parse(JSON.stringify(d.asDict())).added).toEqual(["4"]);
      d.dispose();
      d.dispose();
      expect(() => d.added).toThrow(InvalidInput);
    });

    it("short-circuits identical states and refuses mixed kinds", () => {
      const same = reference().diff(reference());
      expect(same.nUnchanged).toBe(3);
      expect(same.changed).toEqual([]);
      expect(same.added).toEqual([]);
      expect(same.manifestChanges).toEqual({});
      const other = new Encoding({ ids: ["a"], rows: refRows.slice(0, 2), config: c });
      expect(() => reference().diff(other)).toThrow(Incompatible);
      expect(() => reference().diff(new Encoding({ ids: [1n], rows: bytes(0, 0), config: CodecConfig.quant(4, 3) }))).toThrow(
        Incompatible,
      );
      expect(() => reference().diff({} as never)).toThrow(InvalidInput);
    });

    it("renders utf8 ids as strings in the report", () => {
      const a = new Encoding({ ids: ["a", "b"], rows: bytes(1, 0, 2, 0), config: c });
      const b = new Encoding({ ids: ["b", "c"], rows: bytes(3, 0, 4, 0), config: c });
      const d = a.diff(b);
      expect(d.idKind).toBe("utf8");
      expect(d.added).toEqual(["c"]);
      expect(d.removed).toEqual(["a"]);
      expect(d.changed).toEqual([["b", 1]]);
      expect(d.units("b")).toEqual([[0, 2, 3]]);
      expect(() => d.units(1n)).toThrow(InvalidInput);
      const report = d.asDict();
      expect(report.added).toEqual(["c"]);
      expect(report.removed).toEqual(["a"]);
      expect(report.changed).toEqual([["b", 1]]);
      expect(report.id_kind).toBe("utf8");
      expect(report.reference_id).toMatch(/^[0-9a-f]{64}$/);
      expect(report.candidate_id).toMatch(/^[0-9a-f]{64}$/);
      expect(report.n_unchanged).toBe(0);
      expect(report.manifest_changes).toEqual({});
    });

    it("reports a change to a manifest key named __proto__", () => {
      const withProto = (value: string): Encoding =>
        new Encoding({
          ids: [1n],
          rows: bytes(0, 0),
          config: c,
          manifest: JSON.parse(`{"__proto__": "${value}"}`) as Record<string, string>,
        });
      const d = withProto("a").diff(withProto("b"));
      const changes = d.manifestChanges;
      expect(Object.hasOwn(changes, "__proto__")).toBe(true);
      expect(Object.getPrototypeOf(changes)).toBe(Object.prototype);
      expect(Object.entries(changes)).toEqual([["__proto__", ["a", "b"]]]);
      const report = JSON.parse(JSON.stringify(d.asDict())) as { manifest_changes: Record<string, unknown> };
      expect(Object.entries(report.manifest_changes)).toEqual([["__proto__", ["a", "b"]]]);
    });
  });

  describe("Floor", () => {
    /** Pack quant symbols LSB-first at `bits` per unit into `bpv` bytes. */
    const packQuant = (symbols: number[], bits: number, bpv: number): Uint8Array => {
      const out = new Uint8Array(bpv);
      let pos = 0;
      for (const s of symbols) {
        for (let b = 0; b < bits; b++, pos++) if ((s >> b) & 1) out[pos >> 3]! |= 1 << (pos & 7);
      }
      return out;
    };

    /** quant(16, 4): `n` rows of symbol `base`; the first `nChanged` rows have
     * their first `flip` units at `base + 1`. */
    const rowsWithChanges = (
      n: number,
      nChanged: number,
      flip: number,
      base: number,
      manifest?: Record<string, string>,
    ): Encoding => {
      const config = CodecConfig.quant(16, 4);
      const bpv = config.bytesPerVector;
      expect(bpv).toBe(6);
      const ids: bigint[] = [];
      const rows = new Uint8Array(n * bpv);
      for (let i = 0; i < n; i++) {
        const sym = new Array<number>(16).fill(base);
        if (i < nChanged) for (let u = 0; u < flip; u++) sym[u] = base + 1;
        ids.push(BigInt(i));
        rows.set(packQuant(sym, 3, bpv), i * bpv);
      }
      return new Encoding({ ids, rows, config, manifest });
    };

    /** The constructor fields of a floor bound to `reference`. */
    const fields = (reference: Encoding, nulls: number, changedRows: number, totalRows: number, hamming: number) => ({
      config: reference.config,
      idKind: reference.idKind,
      referenceId: reference.stateId,
      nulls,
      changedRows,
      totalRows,
      hamming,
    });

    const REPORT_KEYS = [
      "version",
      "config",
      "id_kind",
      "reference_id",
      "nulls",
      "changed_rows",
      "total_rows",
      "hamming",
    ];

    it("validates construction", () => {
      const a0 = rowsWithChanges(4, 0, 0, 4);
      const ok = fields(a0, 1, 1, 4, 16);
      const f = new Floor(ok);
      expect(f).toBeInstanceOf(Floor);
      expect([f.nulls, f.changedRows, f.totalRows, f.hamming]).toEqual([1, 1, 4, 16]);
      expect(f.config.equals(a0.config)).toBe(true);
      expect(f.idKind).toBe("u64");
      expect(f.referenceId).toEqual(a0.stateId);
      expect(new Floor({ ...ok, changedRows: 0, hamming: 0 }).hamming).toBe(0);
      expect(new Floor({ ...ok, idKind: "utf8" }).idKind).toBe("utf8");
      const rejected: Array<[string, Record<string, unknown>]> = [
        ["changedRows exceeds totalRows", { changedRows: 5 }],
        ["totalRows zero", { totalRows: 0 }],
        ["nulls zero", { nulls: 0 }],
        ["hamming exceeds unitsPerRow", { hamming: 17 }],
        ["negative count", { changedRows: -1 }],
        ["float count", { changedRows: 1.5 }],
        ["bigint count", { changedRows: 1n }],
        ["string count", { changedRows: "1" }],
        ["bool count", { changedRows: true }],
        ["unsafe count", { changedRows: Number.MAX_SAFE_INTEGER + 1 }],
        ["unknown idKind", { idKind: "unknown" }],
        ["short referenceId", { referenceId: new Uint8Array(31) }],
        ["hex referenceId", { referenceId: hex(a0.stateId) }],
        ["config report", { config: { operator: "quant", dim: 16, bins: 4, rule_revision: 0 } }],
        ["missing config", { config: undefined }],
      ];
      for (const [label, patch] of rejected) {
        expect(() => new Floor({ ...ok, ...patch }), label).toThrow(InvalidInput);
      }
      expect(() => new Floor(undefined as never)).toThrow(InvalidInput);
      expect(() => new Floor(null as never)).toThrow(InvalidInput);
      expect(() => new Floor(7 as never)).toThrow(InvalidInput);
    });

    it("measures the envelope of nulls of one reference and checks within exactly", () => {
      const a0 = rowsWithChanges(100, 0, 0, 4);
      const da = a0.diff(rowsWithChanges(100, 1, 1, 4));
      const d2 = a0.diff(rowsWithChanges(100, 2, 1, 4));
      expect(da.changed).toEqual([[0n, 1]]);
      expect(da.nUnchanged).toBe(99);
      const fa = Floor.measure([da]);
      expect(fa).toBeInstanceOf(Floor);
      expect([fa.nulls, fa.changedRows, fa.totalRows, fa.hamming]).toEqual([1, 1, 100, 1]);
      expect(fa.config.equals(a0.config)).toBe(true);
      expect(fa.idKind).toBe("u64");
      expect(fa.referenceId).toEqual(a0.stateId);
      expect([fa.maxHamming, fa.distinctNulls]).toEqual([undefined, undefined]);
      expect(fa.equals(new Floor(fields(a0, 1, 1, 100, 1)))).toBe(true);
      // With perRow the floor also records its per-row data.
      const perRow = Floor.measure([da], { perRow: true });
      expect([perRow.maxHamming, perRow.distinctNulls]).toEqual([1, 1]);
      expect(perRow.equals(fa)).toBe(false);
      expect(Floor.measure([da, da], { perRow: true }).distinctNulls).toBe(1);
      expect(Floor.measure([da, d2], { perRow: true }).distinctNulls).toBe(2);
      expect(() => Floor.measure([da], null as never)).toThrow(InvalidInput);
      expect(da.within(fa)).toBe(true);
      expect(d2.within(fa)).toBe(false);
      const f2 = Floor.measure([da, d2]);
      expect([f2.nulls, f2.changedRows, f2.totalRows, f2.hamming]).toEqual([2, 2, 100, 1]);
      expect(f2.equals(new Floor(fields(a0, 2, 2, 100, 1)))).toBe(true);
      expect(f2.equals(fa)).toBe(false);
      expect(f2.equals({} as never)).toBe(false);
      expect(da.within(f2)).toBe(true);
      expect(d2.within(f2)).toBe(true);
      expect(d2.within(new Floor(fields(a0, 1, 2, 100, 1)))).toBe(true);
      expect(d2.within(new Floor(fields(a0, 1, 1, 100, 1)))).toBe(false);
      expect(() => Floor.measure([])).toThrow(InvalidInput);
      expect(() => Floor.measure([{} as never])).toThrow(InvalidInput);
      expect(() => Floor.measure(da as never)).toThrow(InvalidInput);
      expect(() => da.within({} as never)).toThrow(InvalidInput);
      expect(String(f2)).toBe("Floor(2 of 100 rows, hamming 1, from 2 nulls)");
    });

    it("is bound to the config, the id kind and the reference", () => {
      const a0 = rowsWithChanges(100, 0, 0, 4);
      const b0 = rowsWithChanges(1, 0, 0, 4);
      const da = a0.diff(rowsWithChanges(100, 1, 1, 4));
      const db = b0.diff(rowsWithChanges(1, 1, 10, 4));
      const fa = Floor.measure([da]);
      const fb = Floor.measure([db]);
      expect([fb.nulls, fb.changedRows, fb.totalRows, fb.hamming]).toEqual([1, 1, 1, 10]);
      expect(db.within(fb)).toBe(true);
      const mixed = capture(() => Floor.measure([da, db]));
      expect(mixed).toBeInstanceOf(Incompatible);
      expect((mixed as Incompatible).field).toBe(1);
      expect(() => db.within(fa)).toThrow(Incompatible);
      expect(() => da.within(fb)).toThrow(Incompatible);
      expect(() => da.within(new Floor({ ...fields(a0, 1, 1, 100, 1), config: CodecConfig.quant(16, 3) }))).toThrow(
        Incompatible,
      );
      expect(() => da.within(new Floor({ ...fields(a0, 1, 1, 100, 1), idKind: "utf8" }))).toThrow(Incompatible);
    });

    it("never admits removed rows, no common rows or an encoder change", () => {
      const a0 = rowsWithChanges(100, 0, 0, 4);
      const wide = new Floor(fields(a0, 1, 100, 100, 16));
      const removed = a0.diff(rowsWithChanges(99, 0, 0, 4));
      expect(removed.removed).toEqual([99n]);
      expect(removed.within(wide)).toBe(false);
      const rejected = capture(() => Floor.measure([removed]));
      expect(rejected).toBeInstanceOf(InvalidInput);
      expect((rejected as InvalidInput).field).toBe(0);
      const added = a0.diff(rowsWithChanges(101, 0, 0, 4));
      expect(added.added).toEqual([100n]);
      expect(added.within(new Floor(fields(a0, 1, 0, 100, 0)))).toBe(true);
      expect(() => Floor.measure([added])).toThrow(InvalidInput);
      const e = new Encoding({ ids: [], rows: new Uint8Array(0), config: CodecConfig.quant(16, 4), idKind: "u64" });
      const de = e.diff(e);
      expect(de.within(new Floor(fields(e, 1, 1, 1, 16)))).toBe(false);
      expect(() => Floor.measure([de])).toThrow(InvalidInput);
      const m1 = rowsWithChanges(100, 0, 0, 4, { encoder: "m1" });
      const dm = m1.diff(rowsWithChanges(100, 0, 0, 4, { encoder: "m2" }));
      expect(dm.changed).toEqual([]);
      expect(dm.manifestChanges).toEqual({ encoder: ["m1", "m2"] });
      const fm = Floor.measure([m1.diff(rowsWithChanges(100, 0, 0, 4, { encoder: "m1" }))]);
      expect([fm.nulls, fm.changedRows, fm.totalRows, fm.hamming]).toEqual([1, 0, 100, 0]);
      expect(dm.within(fm)).toBe(false);
      expect(dm.within(new Floor(fields(m1, 1, 100, 100, 16)))).toBe(false);
      const encoder = capture(() => Floor.measure([dm]));
      expect(encoder).toBeInstanceOf(InvalidInput);
      expect((encoder as InvalidInput).field).toBe(0);
    });

    it("evaluates every check and lists the rows above max_hamming", () => {
      // 200 rows; the null changes rows 0..99 by 2 units. The candidate
      // changes rows 0..98 by 2 and row 150 by 10: its p99 ignores row 150,
      // so it is within the floor, and only the per-row check catches it.
      const base = rowsWithChanges(200, 0, 0, 4);
      const nullDiff = base.diff(rowsWithChanges(200, 100, 2, 4));
      const floor = Floor.measure([nullDiff], { perRow: true });
      expect([floor.hamming, floor.maxHamming, floor.distinctNulls]).toEqual([2, 2, 1]);
      const config = base.config;
      const rows = new Uint8Array(200 * config.bytesPerVector);
      for (let i = 0; i < 200; i++) {
        const flip = i < 99 ? 2 : i === 150 ? 10 : 0;
        const sym = Array.from({ length: 16 }, (_, u) => (u < flip ? 5 : 4));
        rows.set(packQuant(sym, 3, config.bytesPerVector), i * config.bytesPerVector);
      }
      const ids = Array.from({ length: 200 }, (_, i) => BigInt(i));
      const hidden = base.diff(new Encoding({ ids, rows, config }));
      expect(hidden.within(floor)).toBe(true);
      expect(hidden.evaluate(floor)).toEqual({ passed: true, reasons: [], rows: [] });
      expect(hidden.evaluate(floor, { perRow: true })).toEqual({ passed: false, reasons: ["row_above_max"], rows: [150n] });
      // Every failed check is named, not only the first.
      const tight = Floor.fromDict({ ...new Floor(fields(base, 1, 1, 200, 1)).asDict(), max_hamming: 1 });
      const all = hidden.evaluate(tight, { perRow: true });
      expect(all.reasons).toEqual(["changed_ratio", "hamming", "row_above_max"]);
      expect(all.rows.length).toBe(100);
      // A floor without per-row data refuses the per-row check and keeps its plain verdict.
      const v1 = Floor.measure([nullDiff]);
      expect(hidden.evaluate(v1).passed).toBe(true);
      expect(() => hidden.evaluate(v1, { perRow: true })).toThrow(Incompatible);
      expect(() => hidden.evaluate({} as never)).toThrow(InvalidInput);
    });

    it("round-trips the report form strictly", () => {
      const a0 = rowsWithChanges(100, 0, 0, 4);
      const f = Floor.measure([a0.diff(rowsWithChanges(100, 1, 1, 4))], { perRow: true });
      const d = f.asDict();
      expect(Object.keys(d)).toEqual([...REPORT_KEYS, "max_hamming", "distinct_nulls"]);
      expect(Object.keys(d.config)).toEqual(["operator", "dim", "bins", "rule_revision"]);
      expect(d).toEqual({
        version: "semq-floor/1",
        config: { operator: "quant", dim: 16, bins: 4, rule_revision: 0 },
        id_kind: "u64",
        reference_id: hex(a0.stateId),
        nulls: 1,
        changed_rows: 1,
        total_rows: 100,
        hamming: 1,
        max_hamming: 1,
        distinct_nulls: 1,
      });
      expect(f.toJson()).toBe(JSON.stringify(d));
      expect(Floor.fromJson(f.toJson()).equals(f)).toBe(true);
      expect(Floor.fromJson(new TextEncoder().encode(f.toJson())).equals(f)).toBe(true);
      // Unknown keys are ignored. Without the per-row keys, as SEMQ 1.0 saved
      // it and as measure without perRow writes it, the floor reads, records
      // none, and writes back without them.
      expect(Floor.fromDict({ ...d, extra: [1, { a: null }] }).equals(f)).toBe(true);
      const without: Record<string, unknown> = { ...d };
      delete without.max_hamming;
      delete without.distinct_nulls;
      const old = Floor.fromDict(without);
      expect([old.maxHamming, old.distinctNulls]).toEqual([undefined, undefined]);
      expect(old.asDict()).toEqual(without);
      expect(old.toJson()).toBe(Floor.measure([a0.diff(rowsWithChanges(100, 1, 1, 4))]).toJson());
      expect(old.equals(f)).toBe(false);
      expect(() => Floor.fromJson("\ud800")).toThrow(InvalidInput);
      expect(() => Floor.fromJson(1 as never)).toThrow(InvalidInput);
      expect(() => Floor.fromDict(undefined)).toThrow(InvalidInput);
      expect(() => Floor.fromDict({ nulls: 1n })).toThrow(InvalidInput);
      const back = Floor.fromDict(JSON.parse(JSON.stringify(d)));
      expect(back.equals(f)).toBe(true);
      expect(back.asDict()).toEqual(d);
      expect(a0.diff(rowsWithChanges(100, 1, 1, 4)).within(back)).toBe(true);
      expect(Floor.fromDict({ ...d, reference_id: d.reference_id.toUpperCase() }).equals(f)).toBe(true);
      for (const config of [CodecConfig.phase(16, 8), CodecConfig.orbit(16)]) {
        const g = new Floor({
          config,
          idKind: "utf8",
          referenceId: a0.stateId,
          nulls: 3,
          changedRows: 0,
          totalRows: 7,
          hamming: 0,
        });
        const h = Floor.fromDict(g.asDict());
        expect(h.equals(g)).toBe(true);
        expect(h.config.equals(config)).toBe(true);
        expect(h.idKind).toBe("utf8");
      }
      const reject = (patch: Record<string, unknown>, label: string): void => {
        const doc: Record<string, unknown> = { ...d, ...patch };
        for (const k of Object.keys(patch)) if (patch[k] === undefined) delete doc[k];
        expect(() => Floor.fromDict(doc), label).toThrow(InvalidInput);
      };
      reject({ hamming: undefined }, "missing key");
      reject({ version: "semq-floor/2" }, "other version");
      reject({ max_hamming: null }, "null max_hamming");
      reject({ max_hamming: 0 }, "max_hamming below hamming");
      reject({ max_hamming: 17 }, "max_hamming exceeds units");
      reject({ distinct_nulls: 0 }, "distinct_nulls zero");
      reject({ distinct_nulls: 2 }, "distinct_nulls above nulls");
      reject({ distinct_nulls: "1" }, "string distinct_nulls");
      reject({ version: 1 }, "version type");
      reject({ nulls: true }, "bool count");
      reject({ nulls: 1.5 }, "float count");
      reject({ nulls: "1" }, "string count");
      reject({ nulls: -1 }, "negative count");
      reject({ nulls: null }, "null count");
      reject({ nulls: 0 }, "nulls zero");
      reject({ changed_rows: 101 }, "changed exceeds total");
      reject({ total_rows: 0 }, "total zero");
      reject({ hamming: 17 }, "hamming exceeds units");
      reject({ reference_id: d.reference_id.slice(1) }, "short reference id");
      reject({ reference_id: `${d.reference_id.slice(1)}g` }, "non-hex reference id");
      reject({ reference_id: a0.stateId }, "binary reference id");
      reject({ id_kind: "unknown" }, "unknown id kind");
      reject({ id_kind: 0 }, "id kind type");
      reject({ config: { operator: "quant", dim: 16, sectors: 4, rule_revision: 0 } }, "wrong parameter");
      reject({ config: { operator: "quant", dim: 16, bins: 4, rule_revision: 1 } }, "rule revision");
      const revision = capture(() =>
        Floor.fromDict({ ...d, config: { operator: "quant", dim: 16, bins: 4, rule_revision: 1 } }),
      );
      expect(revision).toBeInstanceOf(InvalidInput);
      expect((revision as InvalidInput).message).toMatch(/rule revision/);
      expect((revision as InvalidInput).field).toBe(3);
      reject({ config: { operator: "quant", dim: 16, bins: 4, rule_revision: 2 ** 32 } }, "rule revision u32");
      reject({ config: { operator: "quant", dim: 2 ** 32, bins: 4, rule_revision: 0 } }, "dim u32");
      reject({ config: { operator: "quant", dim: 16, bins: 4 } }, "missing rule revision");
      reject({ config: { operator: "quant", dim: 16, bins: 4, sectors: 4, rule_revision: 0 } }, "parameter of another operator");
      reject({ config: { operator: "cube", dim: 16, bins: 4, rule_revision: 0 } }, "unknown operator");
      reject({ config: { operator: "constructor", dim: 16, bins: 4, rule_revision: 0 } }, "prototype operator");
      reject({ config: { operator: "quant", dim: 16, bins: 99, rule_revision: 0 } }, "bins out of range");
      reject({ config: { operator: "quant", dim: "16", bins: 4, rule_revision: 0 } }, "dim type");
      reject({ config: "quant" }, "config type");
      reject({ config: null }, "config null");
      for (const doc of [undefined, null, 1, "x", [], {}, JSON.stringify(d)]) {
        expect(() => Floor.fromDict(doc)).toThrow(InvalidInput);
      }
    });

    it("disposes the handle", () => {
      const a0 = rowsWithChanges(4, 0, 0, 4);
      const d = a0.diff(rowsWithChanges(4, 0, 0, 4));
      const f = Floor.measure([d]);
      expect(d.within(f)).toBe(true);
      f.dispose();
      f.dispose();
      expect(() => f.nulls).toThrow(InvalidInput);
      expect(() => f.config).toThrow(InvalidInput);
      expect(() => f.referenceId).toThrow(InvalidInput);
      expect(() => f.asDict()).toThrow(InvalidInput);
      expect(() => d.within(f)).toThrow(InvalidInput);
      expect(Floor.measure([d])).toBeInstanceOf(Floor);
      d.dispose();
      expect(() => Floor.measure([d])).toThrow(InvalidInput);
    });

    it("uses nearest-rank p99", () => {
      const config = CodecConfig.quant(128, 4);
      const bpv = config.bytesPerVector;
      expect(bpv).toBe(48);
      const n = 101;
      const ids: bigint[] = [];
      const base = new Uint8Array(n * bpv);
      const cand = new Uint8Array(n * bpv);
      for (let i = 0; i < n; i++) {
        const sym = new Array<number>(128).fill(4);
        ids.push(BigInt(i));
        base.set(packQuant(sym, 3, bpv), i * bpv);
        for (let u = 0; u < i + 1; u++) sym[u] = 5;
        cand.set(packQuant(sym, 3, bpv), i * bpv);
      }
      const d = new Encoding({ ids, rows: base, config }).diff(new Encoding({ ids, rows: cand, config }));
      const f = Floor.measure([d]);
      expect([f.nulls, f.changedRows, f.totalRows, f.hamming]).toEqual([1, 101, 101, 100]);
    });
  });

  // ---- build info -------------------------------------------------------------

  it("reports build information", () => {
    const info = buildInfo();
    const pkg = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
    expect(info.sdkVersion).toBe(pkg.version);
    expect(info.coreVersion).not.toBe("");
    expect(info.buildId).not.toBe("");
    expect(info.backend.orbit).not.toBe("");
    expect(info.backend.phase).not.toBe("");
    expect(info.backend.quant).not.toBe("");
  });

  it("exports exactly the documented root symbols", async () => {
    const mod = await import("../src/index.js");
    expect(Object.keys(mod).sort()).toEqual(
      [
        "Codec",
        "CodecConfig",
        "Diff",
        "Encoding",
        "Floor",
        "FormatError",
        "Incompatible",
        "IntegrityError",
        "InvalidInput",
        "Native",
        "Operator",
        "Unsupported",
        "buildInfo",
        "load",
      ].sort(),
    );
    expect(Operator.Orbit).toBe(0);
    expect(Operator.Phase).toBe(1);
    expect(Operator.Quant).toBe(2);
  });
});
