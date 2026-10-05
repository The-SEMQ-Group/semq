// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

// The TypeScript (wasm) host of the reproducibility fixture: encodes the
// 1,000 real embeddings of tests/reproducibility with every configuration of
// its expected.json and compares content_digest, state_id and the saved
// file's bytes. The other bindings run the same comparison.

import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { beforeAll, describe, expect, it } from "vitest";

import { Codec, CodecConfig, Encoding, load } from "../src/index.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "tests", "reproducibility");
const AVAILABLE = ["vectors.f32", "ids.json", "expected.json"].every((name) => existsSync(join(ROOT, name)));
if (!AVAILABLE) console.warn(`reproducibility fixture missing under ${ROOT}, skipped`);

interface Expected {
  manifest: Record<string, string>;
  id_kind: "utf8";
  configs: Record<
    string,
    {
      config: { operator: "quant" | "phase" | "orbit"; dim: number; parameter: number };
      content_digest: string;
      state_id: string;
      file_size: number;
      file_sha256: string;
    }
  >;
}

const hex = (u8: Uint8Array): string => Array.from(u8, (b) => b.toString(16).padStart(2, "0")).join("");
const json = <T>(name: string): T => JSON.parse(readFileSync(join(ROOT, name), "utf8")) as T;

/** The little-endian `.f32` file into a fresh, aligned Float32Array, bit-exact. */
function f32File(name: string): Float32Array {
  const buf = readFileSync(join(ROOT, name));
  const out = new Float32Array(buf.byteLength >>> 2);
  const bits = new Int32Array(out.buffer);
  const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  for (let i = 0; i < bits.length; i++) bits[i] = view.getInt32(4 * i, true);
  return out;
}

const EXPECTED: Expected = AVAILABLE ? json<Expected>("expected.json") : { manifest: {}, id_kind: "utf8", configs: {} };

describe.skipIf(!AVAILABLE)("reproducibility", () => {
  beforeAll(async () => {
    await load();
  });

  for (const [name, want] of Object.entries(EXPECTED.configs).sort(([a], [b]) => a.localeCompare(b))) {
    it(name, async () => {
      const ids = json<{ values: string[] }>("ids.json").values;
      const vectors = f32File("vectors.f32");
      const { operator, dim, parameter } = want.config;
      const codec = await Codec.create(CodecConfig[operator](dim, parameter));
      const state = codec.encode({ ids, vectors, manifest: EXPECTED.manifest, idKind: EXPECTED.id_kind });
      const data = state.toBytes();

      expect(hex(state.contentDigest)).toBe(want.content_digest);
      expect(hex(state.stateId)).toBe(want.state_id);
      expect(data.length).toBe(want.file_size);
      expect(createHash("sha256").update(data).digest("hex")).toBe(want.file_sha256);
      const loaded = Encoding.fromBytes(data);
      expect(hex(loaded.stateId)).toBe(want.state_id);

      loaded.dispose();
      state.dispose();
      codec.dispose();
    });
  }
});
