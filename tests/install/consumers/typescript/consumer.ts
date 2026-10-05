// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

import { strict as assert } from "node:assert";
import { readFileSync, writeFileSync } from "node:fs";
import { buildInfo, Codec, CodecConfig, Encoding, Floor, load } from "@semq/sdk";

await load();
console.log("loaded core:", buildInfo());
for (const [operator, config] of [
  ["quant", CodecConfig.quant(4, 4)],
  ["phase", CodecConfig.phase(4, 8)],
  ["orbit", CodecConfig.orbit(4, 50)],
] as const) {
  const codec = await Codec.create(config);
  for (const kind of ["u64", "utf8"] as const) {
    const ids: bigint[] | string[] = kind === "u64" ? [2n, 1n] : ["doc-2", "doc-1"];
    const vectors = new Float32Array([1, 0, 0, 0, 0, 1, 0, 0]);
    const manifest = { encoder: "artifact" };
    const state = codec.encode({ ids, vectors, manifest });
    const path = `${operator}-${kind}.semq`;
    writeFileSync(path, state.toBytes());
    const restored = Encoding.fromBytes(readFileSync(path));
    assert.deepEqual(state.stateId, restored.stateId);
    assert.equal(restored.length, 2);
    const nullDiff = restored.diff(state);
    const floor = Floor.measure([nullDiff]);
    const back = Floor.fromDict(floor.asDict());
    assert.equal(nullDiff.within(back), true);
    vectors[0] = -1;
    const candidate = codec.encode({ ids, vectors, manifest });
    const diff = restored.diff(candidate);
    assert.equal(diff.changed.length, 1);
    assert.equal(diff.changed[0]![0], ids[0]);
    assert.equal(diff.within(floor), false);
    console.log(operator, kind, "encode/restore/diff/floor OK");
    for (const handle of [diff, candidate, back, floor, nullDiff, restored, state]) handle.dispose();
  }
  codec.dispose();
}
