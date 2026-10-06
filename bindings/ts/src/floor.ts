// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

import { CodecConfig, Operator } from "./config.js";
import { hex, ID_U64, ID_UTF8, isUint8Array, kindName } from "./convert.js";
import { Diff } from "./diff.js";
import { InvalidInput } from "./errors.js";
import { scoped } from "./module.js";
import { NONE, call, rt, type Runtime } from "./runtime.js";

const FLOOR_VERSION = "semq-floor/1";
const FLOOR_VERSION_2 = "semq-floor/2";
const KEYS = [
  "version",
  "config",
  "id_kind",
  "reference_id",
  "nulls",
  "changed_rows",
  "total_rows",
  "hamming",
] as const;
const KEYS_2 = [...KEYS, "max_hamming"] as const;
/** Operator ABI value and parameter name, by report name. */
const OPERATORS = new Map<string, { code: Operator; parameter: "bins" | "sectors" | "scale" }>([
  ["orbit", { code: Operator.Orbit, parameter: "scale" }],
  ["phase", { code: Operator.Phase, parameter: "sectors" }],
  ["quant", { code: Operator.Quant, parameter: "bins" }],
]);

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
 * A floor from {@link Floor.measure} also records `maxHamming`, the largest
 * hamming of any changed row of any null, for the per-row check of
 * {@link Diff.evaluate}.
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
   * `hamming <= config.unitsPerRow`, and `hamming <= maxHamming <=
   * config.unitsPerRow` when `maxHamming` is given; anything else is
   * InvalidInput. Without `maxHamming` the floor does not record it.
   */
  constructor(fields: {
    config: CodecConfig;
    idKind: "u64" | "utf8";
    referenceId: Uint8Array;
    nulls: number;
    changedRows: number;
    totalRows: number;
    hamming: number;
    maxHamming?: number;
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
    const maxHamming = fields.maxHamming === undefined ? undefined : count(fields.maxHamming, "maxHamming");
    this.r = r;
    this.ptr = scoped(r.w, (a) => {
      const cfg = config.write(a);
      const rid = a.u8(referenceId);
      const out = a.alloc(4);
      const kind = idKind === "u64" ? ID_U64 : ID_UTF8;
      const counts = [BigInt(nulls), BigInt(changedRows), BigInt(totalRows), BigInt(hamming)] as const;
      call(r, "floor", (err) =>
        maxHamming === undefined
          ? r.core.floorCreate(cfg, kind, rid, ...counts, out, err)
          : r.core.floorCreateWithMax(cfg, kind, rid, ...counts, BigInt(maxHamming), out, err),
      );
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
   * `encoder` or `encoder_revision`.
   */
  static measure(nullDiffs: Diff[]): Floor {
    const r = rt();
    if (!Array.isArray(nullDiffs) || nullDiffs.length === 0) {
      throw new InvalidInput("measure needs at least one null diff");
    }
    for (const d of nullDiffs) if (!(d instanceof Diff)) throw new InvalidInput("measure takes Diff values");
    const handles = Uint32Array.from(nullDiffs, (d) => d.handle);
    const ptr = scoped(r.w, (a) => {
      const arr = a.u32(handles);
      const out = a.alloc(4);
      call(r, "measure", (err) => r.core.floorMeasure(arr, nullDiffs.length, out, err));
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
   * changed a row); `undefined` for a floor that does not record it, one
   * built without `maxHamming` or read from `semq-floor/1`. */
  get maxHamming(): number | undefined {
    const v = this.r.core.floorMaxHamming(this.handle);
    return v === NONE ? undefined : Number(v);
  }

  /** True when `other` has the same eight fields. */
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
      this.maxHamming === other.maxHamming
    );
  }

  /** The report form: the config as in diff reports, the reference id as
   * lowercase hex, counts as numbers. `semq-floor/2` with `max_hamming` when
   * the floor records it, `semq-floor/1` otherwise. */
  asDict():
    | {
        version: typeof FLOOR_VERSION;
        config: Record<string, string | number>;
        id_kind: "u64" | "utf8";
        reference_id: string;
        nulls: number;
        changed_rows: number;
        total_rows: number;
        hamming: number;
      }
    | {
        version: typeof FLOOR_VERSION_2;
        config: Record<string, string | number>;
        id_kind: "u64" | "utf8";
        reference_id: string;
        nulls: number;
        changed_rows: number;
        total_rows: number;
        hamming: number;
        max_hamming: number;
      } {
    const fields = {
      config: this.config.asDict(),
      id_kind: this.idKind,
      reference_id: hex(this.referenceId),
      nulls: this.nulls,
      changed_rows: this.changedRows,
      total_rows: this.totalRows,
      hamming: this.hamming,
    };
    const maxHamming = this.maxHamming;
    return maxHamming === undefined
      ? { version: FLOOR_VERSION, ...fields }
      : { version: FLOOR_VERSION_2, ...fields, max_hamming: maxHamming };
  }

  /**
   * The inverse of {@link Floor.asDict}, strictly: version `semq-floor/1` or
   * `semq-floor/2`, exactly the keys of that version, `id_kind` `"u64"` or
   * `"utf8"`, `reference_id` 64 hex characters, counts as integers. Anything
   * else is InvalidInput.
   */
  static fromDict(data: unknown): Floor {
    if (!isRecord(data) || (data.version !== FLOOR_VERSION && data.version !== FLOOR_VERSION_2)) {
      throw new InvalidInput(`floor.version must be "${FLOOR_VERSION}" or "${FLOOR_VERSION_2}"`);
    }
    const keys = data.version === FLOOR_VERSION ? KEYS : KEYS_2;
    if (!hasExactKeys(data, keys)) {
      throw new InvalidInput(`floor must have exactly the keys ${keys.join(", ")}`);
    }
    const idKind = data.id_kind;
    if (idKind !== "u64" && idKind !== "utf8") throw new InvalidInput('floor.id_kind must be "u64" or "utf8"');
    const rid = data.reference_id;
    if (typeof rid !== "string" || !/^[0-9a-fA-F]{64}$/.test(rid)) {
      throw new InvalidInput("floor.reference_id must be 64 hex characters");
    }
    return new Floor({
      config: configFromDict(data.config),
      idKind,
      referenceId: unhex(rid),
      nulls: count(data.nulls, "nulls"),
      changedRows: count(data.changed_rows, "changed_rows"),
      totalRows: count(data.total_rows, "total_rows"),
      hamming: count(data.hamming, "hamming"),
      ...(data.version === FLOOR_VERSION ? {} : { maxHamming: count(data.max_hamming, "max_hamming") }),
    });
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

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function hasExactKeys(v: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(v).length === keys.length && keys.every((k) => Object.prototype.hasOwnProperty.call(v, k));
}

function unhex(s: string): Uint8Array {
  const out = new Uint8Array(s.length >>> 1);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(s.slice(2 * i, 2 * i + 2), 16);
  return out;
}

/** A config field on this surface: an integer in [0, 2^32), the ABI's u32. */
function u32(value: unknown, name: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0 || value > 0xffffffff) {
    throw new InvalidInput(`floor.${name} must be an integer in [0, 2^32)`);
  }
  return value;
}

/**
 * The report form of a config back into a CodecConfig, strictly. The host
 * checks the shape (exactly `operator`, `dim`, the operator's parameter and
 * `rule_revision`; a known operator name; u32 integers) and hands the four
 * fields to the core as a semq_config_t, so the core validates
 * every value, the rule revision included.
 */
function configFromDict(data: unknown): CodecConfig {
  if (!isRecord(data) || typeof data.operator !== "string") {
    throw new InvalidInput("floor.config must be a config report");
  }
  const operator = OPERATORS.get(data.operator);
  if (operator === undefined || !hasExactKeys(data, ["operator", "dim", operator.parameter, "rule_revision"])) {
    throw new InvalidInput("floor.config must be a config report");
  }
  return CodecConfig.fromFields(operator.code, u32(data.dim, "config.dim"),
    u32(data[operator.parameter], `config.${operator.parameter}`), u32(data.rule_revision, "config.rule_revision"));
}
