// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

import { ABI } from "./layout.js";

import { CodecConfig } from "./config.js";
import { checkU64, checkUtf8, hex, isUint8Array, kindName, text, writeIds, writeManifest } from "./convert.js";
import { Diff } from "./diff.js";
import { InvalidInput } from "./errors.js";
import { scoped } from "./module.js";
import { NONE, call, rt, type Runtime } from "./runtime.js";

/**
 * An immutable set of ids with one canonical row each, a manifest and two
 * identities. `contentDigest` identifies the rows under the rule; `stateId`
 * adds the manifest. Equality of two Encodings is equality of `stateId`.
 * Every accessor returns a copy; the rows live in wasm memory until
 * {@link Encoding.dispose} or the finalizer runs.
 */
export class Encoding {
  private r!: Runtime;
  private ptr!: number;
  private cfg?: CodecConfig;

  /**
   * Build from rows the caller already holds: `rows.length === n * bytesPerVector`,
   * in the order of `ids`. The core sorts by id, rejects duplicates and
   * non-canonical rows, copies the rows once and computes both digests.
   * `idKind` is required when there are no ids.
   */
  constructor(init: {
    ids: bigint[] | string[];
    rows: Uint8Array;
    config: CodecConfig;
    manifest?: Record<string, string>;
    idKind?: "u64" | "utf8";
  }) {
    const r = rt();
    if (init === null || typeof init !== "object") {
      throw new InvalidInput("Encoding takes { ids, rows, config, manifest?, idKind? }");
    }
    const config = init.config;
    if (!(config instanceof CodecConfig)) throw new InvalidInput("config must be a CodecConfig");
    scoped(r.w, (a) => {
      const ids = writeIds(a, init.ids, init.idKind);
      const rows: unknown = init.rows;
      if (!isUint8Array(rows)) throw new InvalidInput("rows must be a Uint8Array of n * bytesPerVector bytes");
      const bpv = config.bytesPerVector;
      if (rows.length !== ids.n * bpv) {
        throw new InvalidInput(`rows has ${rows.length} bytes, expected ${ids.n} * ${bpv}`);
      }
      const rowsPtr = a.u8(rows);
      const man = writeManifest(a, init.manifest);
      const cfg = config.write(a);
      const out = a.alloc(4);
      call(r, "encoding", (err) => r.core.encodingCreate(cfg, ids.ptr, rowsPtr, man.ptr, man.n, out, err));
      this.attach(r, r.w.getU32(out));
    });
  }

  /** @internal Wrap a handle the core just returned. */
  static fromHandle(r: Runtime, ptr: number): Encoding {
    const e = Object.create(Encoding.prototype) as Encoding;
    e.attach(r, ptr);
    return e;
  }

  private attach(r: Runtime, ptr: number): void {
    this.r = r;
    this.ptr = ptr;
    this.cfg = undefined;
    r.encodings.register(this, ptr, this);
  }

  // ---- persistence ------------------------------------------------------

  /** Parse a complete file image. Validates framing, sizes, ids, manifest,
   * both digests and row canonicity; always copies. */
  static fromBytes(data: Uint8Array): Encoding {
    const r = rt();
    if (!isUint8Array(data)) throw new InvalidInput("fromBytes takes a Uint8Array");
    return scoped(r.w, (a) => {
      const buf = a.u8(data);
      const out = a.alloc(4);
      call(r, "load", (err) => r.core.encodingLoad(buf, BigInt(data.length), out, err));
      return Encoding.fromHandle(r, r.w.getU32(out));
    });
  }

  /** The file image. */
  toBytes(): Uint8Array {
    const h = this.handle;
    const r = this.r;
    const size = Number(r.core.encodingFileSize(h));
    return scoped(r.w, (a) => {
      const out = a.alloc(size);
      call(r, "save", (err) => r.core.encodingSave(h, out, BigInt(size), err));
      return r.w.readU8(out, size);
    });
  }

  /** Release the native handle. Idempotent; later use raises InvalidInput.
   * A Diff built from this Encoding stays valid. */
  dispose(): void {
    if (this.ptr === 0) return;
    this.r.encodings.unregister(this);
    this.r.core.encodingFree(this.ptr);
    this.ptr = 0;
  }

  /** @internal */
  get handle(): number {
    if (this.ptr === 0) throw new InvalidInput("encoding is disposed");
    return this.ptr;
  }

  // ---- access -----------------------------------------------------------

  get config(): CodecConfig {
    if (!this.cfg) this.cfg = CodecConfig.fromPointer(this.r, this.r.core.encodingConfig(this.handle));
    return this.cfg;
  }

  get idKind(): "u64" | "utf8" {
    return kindName(this.r.core.encodingIdKind(this.handle));
  }

  /** Number of rows. */
  get length(): number {
    return Number(this.r.core.encodingLen(this.handle));
  }

  /** Canonical rows in id order, `n * bytesPerVector` bytes (a copy). */
  get rows(): Uint8Array {
    const h = this.handle;
    const r = this.r;
    return scoped(r.w, (a) => {
      const lenOut = a.alloc(8);
      const ptr = r.core.encodingRows(h, lenOut);
      return r.w.readU8(ptr, Number(r.w.getU64(lenOut)));
    });
  }

  /** Row `i` in id order (a copy). */
  row(i: number): Uint8Array {
    const h = this.handle;
    const r = this.r;
    const n = this.length;
    if (!Number.isInteger(i) || i < 0 || i >= n) throw new InvalidInput(`row index ${i} is outside [0, ${n})`);
    const bpv = this.config.bytesPerVector;
    return scoped(r.w, (a) => {
      const lenOut = a.alloc(8);
      const ptr = r.core.encodingRows(h, lenOut);
      return r.w.readU8(ptr + i * bpv, bpv);
    });
  }

  /** Sorted ids: `bigint[]` for `u64`, `string[]` for `utf8` (a copy). */
  get ids(): bigint[] | string[] {
    const h = this.handle;
    const r = this.r;
    const n = this.length;
    if (this.idKind === "u64") return r.w.readU64(r.core.encodingIdsU64(h), n);
    return scoped(r.w, (a) => {
      const lenOut = a.alloc(8);
      const bytes = r.core.encodingIdsUtf8Bytes(h, lenOut);
      const blob = r.w.readU8(bytes, Number(r.w.getU64(lenOut)));
      const offsets = r.w.readU64(r.core.encodingIdsUtf8Offsets(h), n + 1);
      const out = new Array<string>(n);
      for (let i = 0; i < n; i++) out[i] = text(r, "ids", blob.subarray(Number(offsets[i]), Number(offsets[i + 1])));
      return out;
    });
  }

  /** Manifest pairs in canonical (bytewise key) order, as a plain object
   * whose every key is an own property (a key named `__proto__` included). */
  get manifest(): Record<string, string> {
    const h = this.handle;
    const r = this.r;
    const n = r.core.encodingManifestLen(h);
    return scoped(r.w, (a) => {
      const pair = a.alloc(ABI.pair.size);
      const entries = new Array<[string, string]>(n);
      for (let i = 0; i < n; i++) {
        call(r, "manifest", (err) => r.core.encodingManifestPair(h, i, pair, err));
        entries[i] = [
          text(r, "manifest", r.w.readU8(r.w.getU32(pair + ABI.pair.key), r.w.getU32(pair + ABI.pair.key_len))),
          text(r, "manifest", r.w.readU8(r.w.getU32(pair + ABI.pair.value), r.w.getU32(pair + ABI.pair.value_len))),
        ];
      }
      return Object.fromEntries(entries);
    });
  }

  /** SHA-256 identity of the rows under the rule (32 bytes). */
  get contentDigest(): Uint8Array {
    const h = this.handle;
    const r = this.r;
    return scoped(r.w, (a) => {
      const out = a.alloc(32);
      r.core.encodingContentDigest(h, out);
      return r.w.readU8(out, 32);
    });
  }

  /** Identity of rows plus manifest (32 bytes). */
  get stateId(): Uint8Array {
    const h = this.handle;
    const r = this.r;
    return scoped(r.w, (a) => {
      const out = a.alloc(32);
      r.core.encodingStateId(h, out);
      return r.w.readU8(out, 32);
    });
  }

  /** True when `other` has the same `stateId`: the same rows under the same rule, with the same manifest. */
  equals(other: Encoding): boolean {
    if (!(other instanceof Encoding)) return false;
    const mine = this.stateId;
    const theirs = other.stateId;
    for (let i = 0; i < 32; i++) if (mine[i] !== theirs[i]) return false;
    return true;
  }

  /** `Encoding(3 rows, quant(dim=4, bins=4), state_id 40c3aa20252d...)`; the same text in every binding. */
  toString(): string {
    return `Encoding(${this.length} rows, ${this.config.summary()}, state_id ${hex(this.stateId).slice(0, 12)}...)`;
  }

  private find(id: bigint | string): number | undefined {
    const h = this.handle;
    const r = this.r;
    return scoped(r.w, (a) => {
      const index = a.alloc(8);
      if (this.idKind === "u64") {
        const v = checkU64(id, "id of a u64 encoding");
        call(r, "get", (err) => r.core.encodingFindU64(h, v, index, err));
      } else {
        const b = checkUtf8(id, "id of a utf8 encoding");
        const p = a.u8(b);
        call(r, "get", (err) => r.core.encodingFindUtf8(h, p, BigInt(b.length), index, err));
      }
      const i = r.w.getU64(index);
      return i === NONE ? undefined : Number(i);
    });
  }

  /** The row of `id` (a copy), or `undefined` when absent. InvalidInput for
   * an id of the wrong kind. */
  get(id: bigint | string): Uint8Array | undefined {
    const i = this.find(id);
    return i === undefined ? undefined : this.row(i);
  }

  /** `[id, row]` pairs in canonical order. */
  *[Symbol.iterator](): IterableIterator<[bigint | string, Uint8Array]> {
    const ids: Array<bigint | string> = this.ids;
    const rows = this.rows;
    const bpv = this.config.bytesPerVector;
    for (let i = 0; i < ids.length; i++) yield [ids[i]!, rows.slice(i * bpv, (i + 1) * bpv)];
  }

  // ---- verbs ------------------------------------------------------------

  /** Merge with Encodings of the same config, kind and manifest and disjoint
   * ids. Commutative and associative; the empty Encoding is neutral. */
  concat(...others: Encoding[]): Encoding {
    const r = this.r;
    const parts = [this, ...others];
    for (const p of parts) if (!(p instanceof Encoding)) throw new InvalidInput("concat takes Encodings");
    const handles = Uint32Array.from(parts, (p) => p.handle);
    return scoped(r.w, (a) => {
      const arr = a.u32(handles);
      const out = a.alloc(4);
      call(r, "concat", (err) => r.core.encodingConcat(arr, parts.length, out, err));
      return Encoding.fromHandle(r, r.w.getU32(out));
    });
  }

  /** `this` is the reference, `candidate` the state under review. */
  diff(candidate: Encoding): Diff {
    const h = this.handle;
    const r = this.r;
    if (!(candidate instanceof Encoding)) throw new InvalidInput("diff takes an Encoding");
    const c = candidate.handle;
    return scoped(r.w, (a) => {
      const out = a.alloc(4);
      call(r, "diff", (err) => r.core.encodingDiff(h, c, out, err));
      return Diff.fromHandle(r, r.w.getU32(out));
    });
  }
}
