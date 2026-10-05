// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

import { execFileSync } from "node:child_process";
import { readFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import ts from "typescript";
import { beforeAll, expect, it, vi } from "vitest";
import { CodecConfig, Encoding, Floor, load } from "../src/index.js";

beforeAll(async () => { await load(); });

it("adapts Floor JSON fields without writing the binary config form", () => {
  const enc = new Encoding({ ids: [1n], rows: new Uint8Array(2), config: CodecConfig.quant(4, 4) });
  const diff = enc.diff(enc);
  const floor = Floor.measure([diff]);
  const spy = vi.spyOn(CodecConfig, "fromBytes").mockImplementation(() => { throw new Error("binary parser called"); });
  try {
    const back = Floor.fromDict(floor.asDict());
    expect(back.equals(floor)).toBe(true);
    back.dispose();
  } finally {
    spy.mockRestore(); floor.dispose(); diff.dispose(); enc.dispose();
  }
});

it("emits a public API with no pointer adoption or native runtime parameters", () => {
  const out = mkdtempSync(join(tmpdir(), "semq-declarations-"));
  try {
    execFileSync(process.execPath, [resolve("node_modules/typescript/bin/tsc"), "-p", "tsconfig.json",
      "--emitDeclarationOnly", "--outDir", out]);
    for (const name of ["config", "codec", "encoding", "diff", "floor"]) {
      const source = ts.createSourceFile(`${name}.d.ts`, readFileSync(join(out, `${name}.d.ts`), "utf8"), ts.ScriptTarget.Latest, true);
      for (const statement of source.statements) {
        if (!ts.isClassDeclaration(statement)) continue;
        for (const member of statement.members) {
          const modifiers = ts.canHaveModifiers(member) ? ts.getModifiers(member) : undefined;
          if (modifiers?.some((m) => m.kind === ts.SyntaxKind.PrivateKeyword)) continue;
          expect(member.getText(source)).not.toMatch(/\b(?:fromHandle|fromPointer|handle|Runtime|Arena)\b/);
        }
      }
    }
  } finally { rmSync(out, { recursive: true, force: true }); }
}, 30000);

it("rejects another ABI major before allocating native resources", async () => {
  const { rt } = await import("../src/runtime.js");
  const { bindCore } = await import("../src/native.js");
  const w = rt().w;
  const version = vi.spyOn(w, "utf8").mockReturnValue("2.0.0");
  const allocate = vi.spyOn(w, "malloc").mockImplementation(() => { throw new Error("allocation before ABI admission"); });
  try {
    expect(() => bindCore(w)).toThrow("unsupported SEMQ ABI major");
    expect(allocate).not.toHaveBeenCalled();
  } finally { version.mockRestore(); allocate.mockRestore(); }
});
