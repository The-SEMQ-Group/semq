// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

// This file never calls load(): vitest gives it a fresh module registry, so
// the runtime starts unloaded here whatever core.test.ts did.
import { describe, expect, it } from "vitest";

import { Codec, CodecConfig, Encoding, Floor, InvalidInput } from "../src/index.js";

describe("the direct constructors", () => {
  // Runs first in a fresh module registry: nothing has called load() yet.
  it("load the module themselves and validate at once", async () => {
    const codec = await Codec.quant(4, 4);
    expect(codec.config.bins).toBe(4);
    codec.dispose();
    await expect(Codec.quant(4, 65)).rejects.toBeInstanceOf(InvalidInput);
    expect(() => CodecConfig.quant(4, 65)).toThrow(InvalidInput);
  });
});

describe("Encoding.equals", () => {
  it("compares state ids", async () => {
    const codec = await Codec.create(CodecConfig.quant(4, 4));
    const vectors = new Float32Array([1, 0, 0, 0, 0, 1, 0, 0]);
    const a = codec.encode({ ids: [1n, 2n], vectors, manifest: { encoder: "e" } });
    const b = codec.encode({ ids: [1n, 2n], vectors, manifest: { encoder: "e" } });
    const c = codec.encode({ ids: [1n, 2n], vectors, manifest: { encoder: "f" } });
    expect(a.equals(b)).toBe(true);
    expect(a.equals(Encoding.fromBytes(a.toBytes()))).toBe(true);
    expect(a.equals(c)).toBe(false);
    for (const e of [a, b, c]) e.dispose();
    codec.dispose();
  });
});

describe("direct constructors and readable summaries", () => {
  // The first lines a reader writes, and what the summaries say: the same
  // text every binding produces for this data.
  it("match the other bindings word for word", async () => {
    const vectors = new Float32Array([0.6, 0.8, 0, 0, 0, 0.6, 0.8, 0, 0, 0, 0.6, 0.8]);
    const ids = ["doc-1", "doc-2", "doc-3"];
    const manifest = { encoder: "example-encoder", encoder_revision: "1" };
    const codec = await Codec.quant(4, 4);
    expect(codec.config.equals(CodecConfig.quant(4, 4))).toBe(true);
    expect((await Codec.phase(4, 16)).config.sectors).toBe(16);
    expect((await Codec.orbit(4)).config.scale).toBe(50);
    const state = codec.encode({ ids, vectors, manifest });
    const reference = Encoding.fromBytes(state.toBytes());
    expect(String(reference)).toBe("Encoding(3 rows, quant(dim=4, bins=4), state_id 6e6f8a89bae4...)");
    const rebuilt = vectors.slice();
    rebuilt.set([0.8, 0, 0, 0.6], 8);
    const diff = reference.diff(codec.encode({ ids, vectors: rebuilt, manifest }));
    expect(String(diff)).toBe("1 of 3 rows changed: doc-3 (hamming 3). 0 added, 0 removed.");
    expect(String(reference.diff(codec.encode({ ids, vectors, manifest })))).toBe("0 of 3 rows changed. 0 added, 0 removed.");
    const other = codec.encode({ ids, vectors, manifest: { encoder: "other", encoder_revision: "1" } });
    expect(String(reference.diff(other))).toBe("0 of 3 rows changed. 0 added, 0 removed. Manifest changed: encoder.");
    const grown = codec.encode({ ids: [...ids, "doc-4"], vectors: new Float32Array([...vectors, 1, 0, 0, 0]), manifest });
    expect(String(reference.diff(grown))).toBe("0 of 3 rows changed. 1 added, 0 removed.");
    const floor = Floor.measure([1, 2, 3].map(() => reference.diff(codec.encode({ ids, vectors, manifest }))));
    expect(String(floor)).toBe("Floor(0 of 3 rows, hamming 0, from 3 nulls)");
    expect(diff.within(floor)).toBe(false);
  });
});
