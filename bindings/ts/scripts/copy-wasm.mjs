// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
import { copyFile, mkdir } from "node:fs/promises";

const source = new URL("../src/wasm/", import.meta.url);
const destination = new URL("../dist/wasm/", import.meta.url);
await mkdir(destination, { recursive: true });
for (const name of ["semq.mjs", "semq.wasm"]) {
  await copyFile(new URL(name, source), new URL(name, destination));
}
