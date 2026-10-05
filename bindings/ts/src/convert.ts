// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

// Representation checks and conversions between JavaScript values and the
// C ABI. The host validates what only it can see (types, surrogates, bigint
// ranges); every rule about bytes stays in the core.

import { ABI } from "./layout.js";

import { InvalidInput, Native } from "./errors.js";
import type { Arena } from "./module.js";
import type { Runtime } from "./runtime.js";

export const ID_U64 = ABI.constants.SEMQ_ID_U64;
export const ID_UTF8 = ABI.constants.SEMQ_ID_UTF8;

export type IdKind = "u64" | "utf8";

export function kindName(kind: number): IdKind {
  return kind === ID_UTF8 ? "utf8" : "u64";
}

const encoder = new TextEncoder();
// `ignoreBOM` keeps a leading U+FEFF as the character it is: ids and manifest
// text are bytewise in the core, so "\ufeffx" and "x" are two ids. `fatal`
// refuses to substitute U+FFFD for bytes that are not UTF-8.
const decoder = new TextDecoder("utf-8", { ignoreBOM: true, fatal: true });

/** Decode text the core returned. The core validates every id and manifest
 * string it stores, so bytes that are not UTF-8 here are a defect, never
 * input: the failure is Native. */
export function text(r: Runtime, operation: string, bytes: Uint8Array): string {
  try {
    return decoder.decode(bytes);
  } catch {
    throw new Native("core returned text that is not UTF-8", {
      operation,
      coreVersion: r.core.coreVersion(),
      buildId: r.core.buildId(),
    });
  }
}

export function hex(bytes: Uint8Array): string {
  let out = "";
  for (const b of bytes) out += b.toString(16).padStart(2, "0");
  return out;
}

/** True when `s` has no lone surrogate (TextEncoder would otherwise replace
 * it with U+FFFD silently). */
export function isWellFormed(s: string): boolean {
  const native = (s as { isWellFormed?: () => boolean }).isWellFormed;
  if (typeof native === "function") return native.call(s);
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (c >= 0xd800 && c <= 0xdbff) {
      const d = i + 1 < s.length ? s.charCodeAt(i + 1) : 0;
      if (d < 0xdc00 || d > 0xdfff) return false;
      i++;
    } else if (c >= 0xdc00 && c <= 0xdfff) {
      return false;
    }
  }
  return true;
}

const U64_MAX = (1n << 64n) - 1n;

/** A u64 id must be a bigint in [0, 2^64). */
export function checkU64(id: unknown, what: string, row?: number): bigint {
  if (typeof id !== "bigint") throw new InvalidInput(`${what} must be a bigint`, { row });
  if (id < 0n || id > U64_MAX) throw new InvalidInput(`${what} is outside [0, 2^64)`, { row });
  return id;
}

/** A utf8 id must be a well-formed string; returns its UTF-8 bytes. */
export function checkUtf8(id: unknown, what: string, row?: number): Uint8Array {
  if (typeof id !== "string") throw new InvalidInput(`${what} must be a string`, { row });
  if (!isWellFormed(id)) throw new InvalidInput(`${what} contains a lone surrogate`, { row });
  return encoder.encode(id);
}

export function isUint8Array(v: unknown): v is Uint8Array {
  return v instanceof Uint8Array || Object.prototype.toString.call(v) === "[object Uint8Array]";
}

export function isFloat32Array(v: unknown): v is Float32Array {
  return v instanceof Float32Array || Object.prototype.toString.call(v) === "[object Float32Array]";
}

/**
 * Write a `semq_ids_t` (kind u32 @0, n u64 @8, u64 ptr @16, utf8_offsets
 * ptr @20, utf8_bytes ptr @24; 32 bytes) into the arena. The kind is
 * inferred from the first id and required when there are none.
 */
export function writeIds(a: Arena, ids: unknown, idKind: unknown): { ptr: number; n: number; kind: IdKind } {
  if (!Array.isArray(ids)) throw new InvalidInput("ids must be an array of bigint (u64) or string (utf8)");
  if (idKind !== undefined && idKind !== "u64" && idKind !== "utf8") {
    throw new InvalidInput('idKind must be "u64" or "utf8"');
  }
  const n = ids.length;
  let kind: IdKind;
  if (n === 0) {
    if (idKind === undefined) throw new InvalidInput("idKind is required for an empty encoding");
    kind = idKind;
  } else {
    const first: unknown = ids[0];
    const inferred = typeof first === "bigint" ? "u64" : typeof first === "string" ? "utf8" : undefined;
    if (inferred === undefined) {
      throw new InvalidInput("ids must be bigint (u64) or string (utf8)", { row: 0 });
    }
    if (idKind !== undefined && idKind !== inferred) {
      throw new InvalidInput(`ids are ${inferred} but idKind is ${idKind}`, { row: 0 });
    }
    kind = inferred;
  }

  const w = a.w;
  const s = a.alloc(ABI.ids.size);
  w.setU32(s + ABI.ids.kind, kind === "u64" ? ID_U64 : ID_UTF8);
  w.setU64(s + ABI.ids.n, BigInt(n));
  if (kind === "u64") {
    const values = new Array<bigint>(n);
    for (let i = 0; i < n; i++) values[i] = checkU64(ids[i], "u64 id", i);
    w.setU32(s + ABI.ids.u64, a.u64(values));
  } else {
    const chunks = new Array<Uint8Array>(n);
    const offsets = new Array<bigint>(n + 1);
    let total = 0;
    offsets[0] = 0n;
    for (let i = 0; i < n; i++) {
      const b = checkUtf8(ids[i], "utf8 id", i);
      chunks[i] = b;
      total += b.length;
      offsets[i + 1] = BigInt(total);
    }
    const blob = new Uint8Array(total);
    let at = 0;
    for (const c of chunks) {
      blob.set(c, at);
      at += c.length;
    }
    w.setU32(s + ABI.ids.utf8_offsets, a.u64(offsets));
    w.setU32(s + ABI.ids.utf8_bytes, a.u8(blob));
  }
  return { ptr: s, n, kind };
}

/** Write a `semq_pair_t[]` (key ptr @0, key_len @4, value ptr @8,
 * value_len @12; 16 bytes each) from a string-to-string record. */
export function writeManifest(a: Arena, manifest: unknown): { ptr: number; n: number } {
  if (manifest === undefined || manifest === null) return { ptr: 0, n: 0 };
  if (typeof manifest !== "object" || Array.isArray(manifest)) {
    throw new InvalidInput("manifest must be an object of string to string");
  }
  const entries = Object.entries(manifest as Record<string, unknown>);
  if (entries.length === 0) return { ptr: 0, n: 0 };
  const w = a.w;
  const pairs = a.alloc(ABI.pair.size * entries.length);
  for (let i = 0; i < entries.length; i++) {
    const [key, value] = entries[i]!;
    if (typeof value !== "string") {
      throw new InvalidInput("manifest keys and values must be strings", { field: i });
    }
    if (!isWellFormed(key) || !isWellFormed(value)) {
      throw new InvalidInput("manifest text contains a lone surrogate", { field: i });
    }
    const kb = encoder.encode(key);
    const vb = encoder.encode(value);
    const p = pairs + ABI.pair.size * i;
    w.setU32(p + ABI.pair.key, a.u8(kb));
    w.setU32(p + ABI.pair.key_len, kb.length);
    w.setU32(p + ABI.pair.value, a.u8(vb));
    w.setU32(p + ABI.pair.value_len, vb.length);
  }
  return { ptr: pairs, n: entries.length };
}
