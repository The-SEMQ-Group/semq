// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

// Generated at build time by scripts/build-wasm.sh (gitignored). @ts-ignore,
// not @ts-expect-error: once the module is built there is no error to expect.
// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-ignore
import createSemqModule from "./wasm/semq.mjs";

/** A raw wasm export: pointers, i32 and float values cross as numbers, i64
 * values as bigint. See native.ts for the boundary contract. */
export type RawExport = (...args: Array<number | bigint>) => number | bigint | undefined;

/** The subset of the Emscripten runtime the binding relies on. */
export interface EmscriptenModule {
  _malloc(size: number): number;
  _free(ptr: number): void;
  UTF8ToString(ptr: number): string;
  HEAPU8: Uint8Array;
  HEAPU32: Uint32Array;
  HEAPF32: Float32Array;
  [rawExport: `_${string}`]: unknown;
}

/**
 * A loaded SEMQ WebAssembly instance plus the helpers that move values across
 * the wasm heap. The heap can grow on any allocation, and growth replaces the
 * `HEAP*` views, so every helper reads the view from the module at the moment
 * it needs it and never keeps one across an allocation.
 */
export class SemqWasm {
  private constructor(private readonly m: EmscriptenModule) {}

  /** Instantiate the wasm module. */
  static async load(): Promise<SemqWasm> {
    const m = (await createSemqModule()) as EmscriptenModule;
    return new SemqWasm(m);
  }

  /** A raw wasm export by name (without the leading underscore). */
  raw(name: string): RawExport {
    const fn = this.m[`_${name}`];
    if (typeof fn !== "function") {
      throw new Error(`missing wasm export _${name}`);
    }
    return fn as RawExport;
  }

  /** Read a NUL-terminated C string at ptr. */
  utf8(ptr: number): string {
    return this.m.UTF8ToString(ptr);
  }

  /** Allocate `bytes` on the wasm heap; 0 for an empty request. Out of memory
   * is a RangeError, the host's native error for allocation failure. */
  malloc(bytes: number): number {
    // wasm32 has a 32-bit size_t: reject a request the core would truncate.
    if (!Number.isInteger(bytes) || bytes < 0 || bytes > 0xffffffff) {
      throw new RangeError(`wasm allocation of ${bytes} bytes is out of range for a 32-bit heap`);
    }
    if (bytes === 0) return 0;
    const p = this.m._malloc(bytes);
    if (p === 0) {
      throw new RangeError(`wasm out of memory: could not allocate ${bytes} bytes`);
    }
    return p;
  }

  free(ptr: number): void {
    if (ptr !== 0) this.m._free(ptr);
  }

  zero(ptr: number, bytes: number): void {
    if (bytes !== 0) this.m.HEAPU8.fill(0, ptr, ptr + bytes);
  }

  // --- scalars ---

  getU32(ptr: number): number {
    return this.m.HEAPU32[ptr >>> 2]!;
  }

  setU32(ptr: number, value: number): void {
    this.m.HEAPU32[ptr >>> 2] = value;
  }

  getU64(ptr: number): bigint {
    return new DataView(this.m.HEAPU8.buffer).getBigUint64(ptr, true);
  }

  setU64(ptr: number, value: bigint): void {
    new DataView(this.m.HEAPU8.buffer).setBigUint64(ptr, value, true);
  }

  // --- writers: allocate, then copy a JS array in. 0 for an empty input
  // (the core accepts NULL wherever a length of 0 accompanies it) ---

  writeU8(values: ArrayLike<number>): number {
    if (values.length === 0) return 0;
    const p = this.malloc(values.length);
    this.m.HEAPU8.set(values, p);
    return p;
  }

  writeU32(values: ArrayLike<number>): number {
    if (values.length === 0) return 0;
    const p = this.malloc(values.length * 4);
    this.m.HEAPU32.set(values, p >>> 2);
    return p;
  }

  writeF32(values: ArrayLike<number>): number {
    if (values.length === 0) return 0;
    const p = this.malloc(values.length * 4);
    this.m.HEAPF32.set(values, p >>> 2);
    return p;
  }

  writeU64(values: ArrayLike<bigint>): number {
    if (values.length === 0) return 0;
    const p = this.malloc(values.length * 8);
    const view = new DataView(this.m.HEAPU8.buffer);
    for (let i = 0; i < values.length; i++) view.setBigUint64(p + 8 * i, values[i]!, true);
    return p;
  }

  // --- readers: copy out of the heap, never a view into it ---

  readU8(ptr: number, n: number): Uint8Array {
    return n === 0 ? new Uint8Array(0) : this.m.HEAPU8.slice(ptr, ptr + n);
  }

  readU32(ptr: number, n: number): Uint32Array {
    return n === 0 ? new Uint32Array(0) : this.m.HEAPU32.slice(ptr >>> 2, (ptr >>> 2) + n);
  }

  readF32(ptr: number, n: number): Float32Array {
    return n === 0 ? new Float32Array(0) : this.m.HEAPF32.slice(ptr >>> 2, (ptr >>> 2) + n);
  }

  readU64(ptr: number, n: number): bigint[] {
    const view = new DataView(this.m.HEAPU8.buffer);
    const out = new Array<bigint>(n);
    for (let i = 0; i < n; i++) out[i] = view.getBigUint64(ptr + 8 * i, true);
    return out;
  }
}

/** Temporary wasm allocations for one call, freed together by {@link scoped}. */
export class Arena {
  private readonly owned: number[] = [];

  constructor(readonly w: SemqWasm) {}

  private track(p: number): number {
    if (p !== 0) this.owned.push(p);
    return p;
  }

  /** Zero-filled scratch of `bytes`. */
  alloc(bytes: number): number {
    const p = this.track(this.w.malloc(bytes));
    this.w.zero(p, bytes);
    return p;
  }

  u8(values: ArrayLike<number>): number {
    return this.track(this.w.writeU8(values));
  }

  u32(values: ArrayLike<number>): number {
    return this.track(this.w.writeU32(values));
  }

  f32(values: ArrayLike<number>): number {
    return this.track(this.w.writeF32(values));
  }

  u64(values: ArrayLike<bigint>): number {
    return this.track(this.w.writeU64(values));
  }

  release(): void {
    while (this.owned.length > 0) this.w.free(this.owned.pop()!);
  }
}

/** Run `fn` with an {@link Arena} that is released when it returns or throws. */
export function scoped<T>(w: SemqWasm, fn: (a: Arena) => T): T {
  const a = new Arena(w);
  try {
    return fn(a);
  } finally {
    a.release();
  }
}
