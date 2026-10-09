// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

import { CodecConfig } from "./config.js";
import { hex, ID_U64, ID_UTF8, isUint8Array, isWellFormed, kindName, text } from "./convert.js";
import { checksOf, Diff, type GateOptions } from "./diff.js";
import { InvalidInput } from "./errors.js";
import { scoped } from "./module.js";
import { NONE, call, rt, type Runtime } from "./runtime.js";

// The schema version, named in the public type of `asDict`.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
const FLOOR_VERSION = "semq-floor/1";
const encoder = new TextEncoder();

/**
 * An envelope of observed variation, `(changedRows, totalRows, hamming)`
 * measured from `nulls` null diffs, bound to the config, the id kind and the
 * reference state those nulls were taken against.
 *
 * A diff is within the floor when it removes no rows, shares at least one
 * row with its reference, changes at most `changedRows / totalRows` of the
 * shared rows, its p99 hamming does not exceed `hamming`, and it changes
 * neither `encoder` nor `encoder_revision`. Applying a floor to a diff of
 * another config, id kind or reference throws `Incompatible`. No
 * probabilistic coverage is claimed.
 *
 * `Floor.measure(diffs, { perRow: true })` also records the per-row data
 * the per-row check of {@link Diff.evaluate} needs: `maxHamming`, the
 * largest hamming of any changed row of any null, and `distinctNulls`.
 * Without it the JSON form is the one SEMQ 1.0 reads.
 * The JSON form ({@link Floor.toJson}, {@link Floor.fromJson},
 * {@link Floor.asDict}, {@link Floor.fromDict}) is written and read by the
 * core, with the same rules in every binding.
 *
 * Owns a native handle: call {@link Floor.dispose} when done, or let the
 * finalizer free it.
 */
export class Floor {
  private ptr: number;
  private r: Runtime;
  private cfg?: CodecConfig;

  /**
   * A floor from its fields. `referenceId` is the `stateId` of the reference
   * (32 bytes); counts are numbers. The core validates the rest: `nulls >= 1`,
   * `totalRows >= 1`, `changedRows <= totalRows` and
   * `hamming <= config.unitsPerRow`; anything else is InvalidInput. The
   * floor has no per-row data: that comes only from {@link Floor.measure}
   * or {@link Floor.fromJson}.
   */
  constructor(fields: {
    config: CodecConfig;
    idKind: "u64" | "utf8";
    referenceId: Uint8Array;
    nulls: number;
    changedRows: number;
    totalRows: number;
    hamming: number;
  }) {
    const r = rt();
    if (fields === null || typeof fields !== "object") {
      throw new InvalidInput("Floor takes { config, idKind, referenceId, nulls, changedRows, totalRows, hamming }");
    }
    const { config, idKind, referenceId } = fields;
    if (!(config instanceof CodecConfig)) throw new InvalidInput("floor.config must be a CodecConfig");
    if (idKind !== "u64" && idKind !== "utf8") throw new InvalidInput('floor.idKind must be "u64" or "utf8"');
    if (!isUint8Array(referenceId) || referenceId.length !== 32) {
      throw new InvalidInput("floor.referenceId must be a Uint8Array of 32 bytes");
    }
    const nulls = count(fields.nulls, "nulls");
    const changedRows = count(fields.changedRows, "changedRows");
    const totalRows = count(fields.totalRows, "totalRows");
    const hamming = count(fields.hamming, "hamming");
    this.r = r;
    this.ptr = scoped(r.w, (a) => {
      const cfg = config.write(a);
      const rid = a.u8(referenceId);
      const out = a.alloc(4);
      const kind = idKind === "u64" ? ID_U64 : ID_UTF8;
      const counts = [BigInt(nulls), BigInt(changedRows), BigInt(totalRows), BigInt(hamming)] as const;
      call(r, "floor", (err) => r.core.floorCreate(cfg, kind, rid, ...counts, out, err));
      return r.w.getU32(out);
    });
    r.floors.register(this, this.ptr, this);
  }

  /** @internal Adopt a handle the core created (`measure`). */
  static fromHandle(r: Runtime, ptr: number): Floor {
    const f = Object.create(Floor.prototype) as Floor;
    f.r = r;
    f.ptr = ptr;
    r.floors.register(f, ptr, f);
    return f;
  }

  /**
   * The envelope of one or more null diffs of one reference; every input is
   * within the result. `Incompatible` when the nulls differ in config, id
   * kind or reference (`field` is the offending index); `InvalidInput` when
   * one is not a null: rows added or removed, none in common, or a change to
   * `encoder` or `encoder_revision`. The floor records no per-row data.
   */
  static measure(nullDiffs: Diff[]): Floor;
  /**
   * {@link Floor.measure} that also records what the checks in `options`
   * need: with `{ perRow: true }`, `maxHamming` and `distinctNulls` for the
   * per-row check. SEMQ 1.0 cannot read a floor saved with them.
   */
  static measure(nullDiffs: Diff[], options: GateOptions): Floor;
  static measure(nullDiffs: Diff[], options: GateOptions = {}): Floor {
    const r = rt();
    const checks = checksOf(options, "measure");
    if (!Array.isArray(nullDiffs) || nullDiffs.length === 0) {
      throw new InvalidInput("measure needs at least one null diff");
    }
    for (const d of nullDiffs) if (!(d instanceof Diff)) throw new InvalidInput("measure takes Diff values");
    const handles = Uint32Array.from(nullDiffs, (d) => d.handle);
    const ptr = scoped(r.w, (a) => {
      const arr = a.u32(handles);
      const out = a.alloc(4);
      call(r, "measure", (err) => r.core.floorMeasureFor(arr, nullDiffs.length, checks, out, err));
      return r.w.getU32(out);
    });
    return Floor.fromHandle(r, ptr);
  }

  /** @internal */
  get handle(): number {
    if (this.ptr === 0) throw new InvalidInput("floor is disposed");
    return this.ptr;
  }

  /** Release the native handle. Idempotent; later use raises InvalidInput. */
  dispose(): void {
    if (this.ptr === 0) return;
    this.r.floors.unregister(this);
    this.r.core.floorFree(this.ptr);
    this.ptr = 0;
  }

  get config(): CodecConfig {
    const h = this.handle;
    if (!this.cfg) this.cfg = CodecConfig.fromPointer(this.r, this.r.core.floorConfig(h));
    return this.cfg;
  }

  get idKind(): "u64" | "utf8" {
    return kindName(this.r.core.floorIdKind(this.handle));
  }

  /** `stateId` of the reference the nulls were taken against (32 bytes). */
  get referenceId(): Uint8Array {
    const h = this.handle;
    const r = this.r;
    return scoped(r.w, (a) => {
      const out = a.alloc(32);
      r.core.floorReferenceId(h, out);
      return r.w.readU8(out, 32);
    });
  }

  /** How many null diffs the floor was measured from. */
  get nulls(): number {
    return Number(this.r.core.floorNulls(this.handle));
  }

  get changedRows(): number {
    return Number(this.r.core.floorChangedRows(this.handle));
  }

  get totalRows(): number {
    return Number(this.r.core.floorTotalRows(this.handle));
  }

  get hamming(): number {
    return Number(this.r.core.floorHamming(this.handle));
  }

  /** The largest hamming of any changed row of any null (`0` when no null
   * changed a row); `undefined` for a floor without per-row data: one from
   * the constructor, from `measure` without `perRow`, or read from JSON
   * without it. */
  get maxHamming(): number | undefined {
    const v = this.r.core.floorMaxHamming(this.handle);
    return v === NONE ? undefined : Number(v);
  }

  /** How many of the nulls were distinct states, from `1` to `nulls`: two
   * nulls are the same when their candidates have the same `contentDigest`.
   * With `1` the per-row check adds no false alarm; when the nulls vary,
   * each check can reject an unchanged rebuild with probability up to
   * `1 / (nulls + 1)`. `undefined` for a floor without per-row data. */
  get distinctNulls(): number | undefined {
    const v = this.r.core.floorDistinctNulls(this.handle);
    return v === NONE ? undefined : Number(v);
  }

  /** True when `other` has the same nine fields. */
  equals(other: Floor): boolean {
    return (
      other instanceof Floor &&
      this.config.equals(other.config) &&
      this.idKind === other.idKind &&
      hex(this.referenceId) === hex(other.referenceId) &&
      this.nulls === other.nulls &&
      this.changedRows === other.changedRows &&
      this.totalRows === other.totalRows &&
      this.hamming === other.hamming &&
      this.maxHamming === other.maxHamming &&
      this.distinctNulls === other.distinctNulls
    );
  }

  /** The floor's JSON form, written by the core: the floor schema with
   * `max_hamming` and `distinct_nulls` when the floor records them, keys in schema order, no
   * whitespace. The same text in every binding. */
  toJson(): string {
    const h = this.handle;
    const r = this.r;
    const n = Number(r.core.floorJsonSize(h));
    return scoped(r.w, (a) => {
      const out = a.alloc(Math.max(n, 1));
      call(r, "save", (err) => r.core.floorSave(h, out, BigInt(n), err));
      return text(r, "save", r.w.readU8(out, n));
    });
  }

  /**
   * Read a floor from its JSON form, by the core's rules: the schema's keys
   * strictly (each at most once, integer counts, `max_hamming` and
   * `distinct_nulls` optional), other keys ignored, and the construction
   * rules. Anything else is InvalidInput.
   */
  static fromJson(json: string | Uint8Array): Floor {
    const r = rt();
    let bytes: Uint8Array;
    if (typeof json === "string") {
      if (!isWellFormed(json)) throw new InvalidInput("floor is not valid UTF-8");
      bytes = encoder.encode(json);
    } else if (isUint8Array(json)) {
      bytes = json;
    } else {
      throw new InvalidInput("fromJson takes a string or a Uint8Array");
    }
    const ptr = scoped(r.w, (a) => {
      const buf = a.u8(bytes);
      const out = a.alloc(4);
      call(r, "load", (err) => r.core.floorLoad(buf, BigInt(bytes.length), out, err));
      return r.w.getU32(out);
    });
    return Floor.fromHandle(r, ptr);
  }

  /** The floor schema as a plain object (`JSON.parse` of {@link Floor.toJson}):
   * the config as in diff reports, the reference id as lowercase hex,
   * counts as numbers. */
  asDict(): {
    version: typeof FLOOR_VERSION;
    config: Record<string, string | number>;
    id_kind: "u64" | "utf8";
    reference_id: string;
    nulls: number;
    changed_rows: number;
    total_rows: number;
    hamming: number;
    max_hamming?: number;
    distinct_nulls?: number;
  } {
    return JSON.parse(this.toJson()) as ReturnType<Floor["asDict"]>;
  }

  /**
   * The inverse of {@link Floor.asDict}, by the core's rules
   * ({@link Floor.fromJson} of `JSON.stringify(data)`). Anything else is
   * InvalidInput.
   */
  static fromDict(data: unknown): Floor {
    let json: string | undefined;
    try {
      json = JSON.stringify(data);
    } catch (e) {
      throw new InvalidInput(`floor is not a JSON value: ${String(e)}`);
    }
    if (json === undefined) throw new InvalidInput("floor is not a JSON value");
    return Floor.fromJson(json);
  }

  /** `Floor(1 of 3 rows, hamming 1, from 3 nulls)`; the same text in every binding. */
  toString(): string {
    return `Floor(${this.changedRows} of ${this.totalRows} rows, hamming ${this.hamming}, from ${this.nulls} nulls)`;
  }
}

/** Counts are numbers on this surface: an integer in [0, 2^53). */
function count(value: unknown, name: string): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) {
    throw new InvalidInput(`floor.${name} must be an integer in [0, 2^53)`);
  }
  return value;
}
