// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

import { CodecConfig } from "./config.js";
import { isFloat32Array, writeIds, writeManifest } from "./convert.js";
import { Encoding } from "./encoding.js";
import { InvalidInput } from "./errors.js";
import { scoped } from "./module.js";
import { call, getRuntime, type Runtime } from "./runtime.js";

/**
 * An immutable encoder for one {@link CodecConfig}. {@link Codec.create} is
 * the one asynchronous point of the package: it loads the wasm module on
 * first use. Call {@link Codec.dispose} when done; a finalizer frees the
 * native handle otherwise.
 */
export class Codec {
  private ptr: number;
  private readonly r: Runtime;
  private readonly cfg: CodecConfig;

  private constructor(r: Runtime, ptr: number, config: CodecConfig) {
    this.r = r;
    this.ptr = ptr;
    this.cfg = config;
    r.codecs.register(this, ptr, this);
  }

  /** A codec for `CodecConfig.quant(dim, bins)`: sign and magnitude bin per coordinate. Loads the module if needed. */
  static async quant(dim: number, bins: number): Promise<Codec> {
    await getRuntime();
    return Codec.create(CodecConfig.quant(dim, bins));
  }

  /** A codec for `CodecConfig.phase(dim, sectors)`: angular sector per coordinate pair. Loads the module if needed. */
  static async phase(dim: number, sectors: number): Promise<Codec> {
    await getRuntime();
    return Codec.create(CodecConfig.phase(dim, sectors));
  }

  /** A codec for `CodecConfig.orbit(dim, scale)`: one discrete symbol per coordinate. Loads the module if needed. */
  static async orbit(dim: number, scale = 50): Promise<Codec> {
    await getRuntime();
    return Codec.create(CodecConfig.orbit(dim, scale));
  }

  /** The constructor. Loads the runtime when it is not loaded yet. */
  static async create(config: CodecConfig): Promise<Codec> {
    if (!(config instanceof CodecConfig)) throw new InvalidInput("Codec.create takes a CodecConfig");
    const r = await getRuntime();
    return scoped(r.w, (a) => {
      const cfg = config.write(a);
      const out = a.alloc(4);
      call(r, "codec", (err) => r.core.codecCreate(cfg, out, err));
      return new Codec(r, r.w.getU32(out), config);
    });
  }

  get config(): CodecConfig {
    return this.cfg;
  }

  /** The kernel the core runs for this operator on this host ("scalar" in wasm). */
  get backend(): string {
    return this.r.core.codecBackend(this.handle);
  }

  /**
   * Encode `n` unit-norm float32 rows (`vectors.length === n * dim`,
   * row-major) under `ids`. `u64` ids are `bigint[]`, `utf8` ids `string[]`;
   * `idKind` is inferred from the first id and required when `n = 0`.
   * Row errors carry the input row index.
   */
  encode(input: {
    ids: bigint[] | string[];
    vectors: Float32Array;
    manifest?: Record<string, string>;
    idKind?: "u64" | "utf8";
  }): Encoding {
    const h = this.handle;
    const r = this.r;
    if (input === null || typeof input !== "object") {
      throw new InvalidInput("encode takes { ids, vectors, manifest?, idKind? }");
    }
    return scoped(r.w, (a) => {
      const ids = writeIds(a, input.ids, input.idKind);
      const vectors: unknown = input.vectors;
      if (!isFloat32Array(vectors)) throw new InvalidInput("vectors must be a Float32Array of n * dim values");
      const dim = this.cfg.dim;
      if (vectors.length !== ids.n * dim) {
        throw new InvalidInput(`vectors has ${vectors.length} values, expected ${ids.n} * ${dim}`);
      }
      const vec = a.f32(vectors);
      const man = writeManifest(a, input.manifest);
      const out = a.alloc(4);
      call(r, "encode", (err) => r.core.codecEncode(h, ids.ptr, vec, man.ptr, man.n, out, err));
      return Encoding.fromHandle(r, r.w.getU32(out));
    });
  }

  /** Representatives, `n * dim` float32, row `i` for `encoding.ids[i]`. Not normalized. */
  decode(encoding: Encoding): Float32Array {
    const h = this.handle;
    const r = this.r;
    if (!(encoding instanceof Encoding)) throw new InvalidInput("decode takes an Encoding");
    const count = encoding.length * this.cfg.dim;
    return scoped(r.w, (a) => {
      const out = a.alloc(count * 4);
      call(r, "decode", (err) => r.core.codecDecode(h, encoding.handle, out, err));
      return r.w.readF32(out, count);
    });
  }

  /** Symbols, `n * unitsPerRow` bytes, one per unit. */
  unpack(encoding: Encoding): Uint8Array {
    const h = this.handle;
    const r = this.r;
    if (!(encoding instanceof Encoding)) throw new InvalidInput("unpack takes an Encoding");
    const count = encoding.length * this.cfg.unitsPerRow;
    return scoped(r.w, (a) => {
      const out = a.alloc(count);
      call(r, "unpack", (err) => r.core.codecUnpack(h, encoding.handle, out, err));
      return r.w.readU8(out, count);
    });
  }

  /** Release the native handle. Idempotent; later use raises InvalidInput. */
  dispose(): void {
    if (this.ptr === 0) return;
    this.r.codecs.unregister(this);
    this.r.core.codecFree(this.ptr);
    this.ptr = 0;
  }

  private get handle(): number {
    if (this.ptr === 0) throw new InvalidInput("codec is disposed");
    return this.ptr;
  }
}
