// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

import { ABI } from "./layout.js";

import { CodecConfig } from "./config.js";
import { checkU64, checkUtf8, hex, kindName, text } from "./convert.js";
import { InvalidInput } from "./errors.js";
import { Floor } from "./floor.js";
import { scoped } from "./module.js";
import { call, type Runtime } from "./runtime.js";

const LIST_ADDED = ABI.constants.SEMQ_LIST_ADDED;
const LIST_REMOVED = ABI.constants.SEMQ_LIST_REMOVED;
const LIST_CHANGED = ABI.constants.SEMQ_LIST_CHANGED;
const CHECK_PER_ROW = ABI.constants.SEMQ_CHECK_PER_ROW;

/** A check that failed in a {@link Verdict}; the same names in every binding. */
export type Reason = "no_common_rows" | "removed_rows" | "changed_ratio" | "hamming" | "encoder" | "row_above_max";

/** The reasons by bit of `semq_reason_t`, in the order a verdict lists them. */
const REASONS: readonly Reason[] = ["no_common_rows", "removed_rows", "changed_ratio", "hamming", "encoder", "row_above_max"];

/** Which checks {@link Diff.evaluate} applies beyond those of {@link Diff.within}, and which data
 * {@link Floor.measure} records for them; every check is off by default. */
export interface GateOptions {
  /** Also fail when any changed row has a hamming above the floor's `maxHamming`, and list those rows.
   * Needs a floor from `Floor.measure(diffs, { perRow: true })`. */
  perRow?: boolean;
}

/** @internal The options as `semq_check_t` flags. */
export function checksOf(options: GateOptions, operation: string): number {
  if (options === null || typeof options !== "object") throw new InvalidInput(`${operation} options must be an object`);
  return options.perRow === true ? CHECK_PER_ROW : 0;
}

/** The result of {@link Diff.evaluate}. */
export interface Verdict {
  /** True iff no check failed. */
  passed: boolean;
  /** Every failed check, in the order `no_common_rows`, `removed_rows`,
   * `changed_ratio`, `hamming`, `encoder`, `row_above_max`. */
  reasons: Reason[];
  /** Ids of the changed rows above the floor's `maxHamming`, canonical order;
   * empty unless the per-row check ran. */
  rows: Array<bigint | string>;
}

/**
 * The result of `reference.diff(candidate)`. Keeps the rows it needs alive
 * until {@link Diff.dispose} or the finalizer runs, even after the caller
 * disposes its Encodings.
 */
export class Diff {
  private ptr: number;
  private readonly r: Runtime;
  private cfg?: CodecConfig;

  private constructor(r: Runtime, ptr: number) {
    this.r = r;
    this.ptr = ptr;
    r.diffs.register(this, ptr, this);
  }

  /** @internal */
  static fromHandle(r: Runtime, ptr: number): Diff {
    return new Diff(r, ptr);
  }

  /** @internal */
  get handle(): number {
    if (this.ptr === 0) throw new InvalidInput("diff is disposed");
    return this.ptr;
  }

  /** Release the native handle. Idempotent; later use raises InvalidInput. */
  /**
   * One sentence, the same text in every binding:
   * `1 of 3 rows changed: doc-3 (hamming 3). 0 added, 0 removed.`
   * Up to five changed ids are listed; changed manifest keys are named at the end.
   */
  toString(): string {
    const changed = this.changed;
    let text = `${changed.length} of ${changed.length + this.nUnchanged} rows changed`;
    if (changed.length) {
      text += `: ${changed.slice(0, 5).map(([id, h]) => `${id} (hamming ${h})`).join(", ")}`;
      if (changed.length > 5) text += `, and ${changed.length - 5} more`;
    }
    text += `. ${this.added.length} added, ${this.removed.length} removed.`;
    const keys = Object.keys(this.manifestChanges).sort();
    if (keys.length) text += ` Manifest changed: ${keys.join(", ")}.`;
    return text;
  }

  dispose(): void {
    if (this.ptr === 0) return;
    this.r.diffs.unregister(this);
    this.r.core.diffFree(this.ptr);
    this.ptr = 0;
  }

  get config(): CodecConfig {
    if (!this.cfg) this.cfg = CodecConfig.fromPointer(this.r, this.r.core.diffConfig(this.handle));
    return this.cfg;
  }

  get idKind(): "u64" | "utf8" {
    return kindName(this.r.core.diffIdKind(this.handle));
  }

  private digest(read: (diff: number, out: number) => void): Uint8Array {
    const h = this.handle;
    const r = this.r;
    return scoped(r.w, (a) => {
      const out = a.alloc(32);
      read(h, out);
      return r.w.readU8(out, 32);
    });
  }

  /** `stateId` of the reference (32 bytes). */
  get referenceId(): Uint8Array {
    return this.digest(this.r.core.diffReferenceId);
  }

  /** `stateId` of the candidate (32 bytes). */
  get candidateId(): Uint8Array {
    return this.digest(this.r.core.diffCandidateId);
  }

  private list(which: number): bigint[] | string[] {
    const h = this.handle;
    const r = this.r;
    const n = Number(r.core.diffCount(h, which));
    const u64 = this.idKind === "u64";
    return scoped(r.w, (a) => {
      const idOut = a.alloc(8);
      const bytesOut = a.alloc(4);
      const lenOut = a.alloc(8);
      const read = (i: number): void =>
        call(r, "diff", (err) => r.core.diffId(h, which, BigInt(i), idOut, bytesOut, lenOut, err));
      if (u64) {
        const out = new Array<bigint>(n);
        for (let i = 0; i < n; i++) {
          read(i);
          out[i] = r.w.getU64(idOut);
        }
        return out;
      }
      const out = new Array<string>(n);
      for (let i = 0; i < n; i++) {
        read(i);
        out[i] = text(r, "diff", r.w.readU8(r.w.getU32(bytesOut), Number(r.w.getU64(lenOut))));
      }
      return out;
    });
  }

  /** Ids only in the candidate, canonical order. */
  get added(): bigint[] | string[] {
    return this.list(LIST_ADDED);
  }

  /** Ids only in the reference, canonical order. */
  get removed(): bigint[] | string[] {
    return this.list(LIST_REMOVED);
  }

  /** `[id, hamming]` for ids on both sides with different rows, canonical
   * order; `hamming` counts units whose symbol differs. */
  get changed(): Array<[bigint | string, number]> {
    const h = this.handle;
    const r = this.r;
    const ids: Array<bigint | string> = this.list(LIST_CHANGED);
    return scoped(r.w, (a) => {
      const out = a.alloc(8);
      return ids.map((id, i): [bigint | string, number] => {
        call(r, "diff", (err) => r.core.diffHamming(h, BigInt(i), out, err));
        return [id, Number(r.w.getU64(out))];
      });
    });
  }

  /** Ids on both sides with identical rows. */
  get nUnchanged(): number {
    return Number(this.r.core.diffNUnchanged(this.handle));
  }

  /** `key -> [before | null, after | null]` for keys that differ or exist on
   * one side, as a plain object whose every key is an own property (a key
   * named `__proto__` included). */
  get manifestChanges(): Record<string, [string | null, string | null]> {
    const h = this.handle;
    const r = this.r;
    const n = r.core.diffManifestChanges(h);
    return scoped(r.w, (a) => {
      const ch = a.alloc(ABI.manifest_change.size);
      const entries = new Array<[string, [string | null, string | null]]>(n);
      const side = (has: number, ptr: number, len: number): string | null =>
        r.w.getU32(has) !== 0 ? text(r, "diff", r.w.readU8(r.w.getU32(ptr), r.w.getU32(len))) : null;
      for (let i = 0; i < n; i++) {
        call(r, "diff", (err) => r.core.diffManifestChange(h, i, ch, err));
        entries[i] = [
          text(r, "diff", r.w.readU8(r.w.getU32(ch + ABI.manifest_change.key), r.w.getU32(ch + ABI.manifest_change.key_len))),
          [side(ch + ABI.manifest_change.has_before, ch + ABI.manifest_change.before, ch + ABI.manifest_change.before_len), side(ch + ABI.manifest_change.has_after, ch + ABI.manifest_change.after, ch + ABI.manifest_change.after_len)],
        ];
      }
      return Object.fromEntries(entries);
    });
  }

  /**
   * `[unit, symbolReference, symbolCandidate]` for every unit of `id` that
   * differs. Empty for an identical row; InvalidInput when `id` is absent
   * from either side or of the wrong kind.
   */
  units(id: bigint | string): Array<[number, number, number]> {
    const h = this.handle;
    const r = this.r;
    const cap = this.config.unitsPerRow;
    return scoped(r.w, (a) => {
      const units = a.alloc(4 * cap);
      const ref = a.alloc(cap);
      const cand = a.alloc(cap);
      const count = a.alloc(8);
      if (this.idKind === "u64") {
        const v = checkU64(id, "id of a u64 diff");
        call(r, "units", (err) => r.core.diffUnitsU64(h, v, units, ref, cand, BigInt(cap), count, err));
      } else {
        const b = checkUtf8(id, "id of a utf8 diff");
        const p = a.u8(b);
        call(r, "units", (err) =>
          r.core.diffUnitsUtf8(h, p, BigInt(b.length), units, ref, cand, BigInt(cap), count, err),
        );
      }
      const n = Number(r.w.getU64(count));
      const us = r.w.readU32(units, n);
      const rs = r.w.readU8(ref, n);
      const cs = r.w.readU8(cand, n);
      const out = new Array<[number, number, number]>(n);
      for (let i = 0; i < n; i++) out[i] = [us[i]!, rs[i]!, cs[i]!];
      return out;
    });
  }

  /**
   * True iff the candidate is within `floor` (exact integer arithmetic in the
   * core). The floor must have been measured against this diff's config, id
   * kind and reference; otherwise `Incompatible`.
   */
  within(floor: Floor): boolean {
    const h = this.handle;
    const r = this.r;
    if (!(floor instanceof Floor)) throw new InvalidInput("within takes a Floor");
    const f = floor.handle;
    return scoped(r.w, (a) => {
      const out = a.alloc(4);
      call(r, "within", (err) => r.core.diffWithin(h, f, out, err));
      return r.w.getU32(out) !== 0;
    });
  }

  /**
   * The verdict of `floor` on this diff, with every check that failed.
   *
   * With no options, `passed` equals {@link Diff.within}. With
   * `perRow: true` the verdict also fails when any changed row has a hamming
   * above `floor.maxHamming`, and `rows` lists those ids. `Incompatible` for
   * a floor of another config, id kind or reference, and for the per-row
   * check on a floor without per-row data (from `Floor.measure` without
   * `perRow`, or saved by SEMQ 1.0).
   */
  evaluate(floor: Floor, options: GateOptions = {}): Verdict {
    const h = this.handle;
    const r = this.r;
    if (!(floor instanceof Floor)) throw new InvalidInput("evaluate takes a Floor");
    const checks = checksOf(options, "evaluate");
    const f = floor.handle;
    const { reasons, rows } = scoped(r.w, (a) => {
      const out = a.alloc(4);
      call(r, "evaluate", (err) => r.core.diffEvaluate(h, f, checks, out, err));
      const v = r.w.getU32(out);
      try {
        const n = Number(r.core.verdictRowCount(v));
        const indices = Array.from({ length: n }, (_, i) => Number(r.core.verdictRow(v, BigInt(i))));
        return { reasons: r.core.verdictReasons(v), rows: indices };
      } finally {
        r.core.verdictFree(v);
      }
    });
    const changed: Array<bigint | string> = rows.length > 0 ? this.list(LIST_CHANGED) : [];
    const names = REASONS.filter((_, bit) => (reasons & (1 << bit)) !== 0);
    return { passed: reasons === 0, reasons: names, rows: rows.map((i) => changed[i]!) };
  }

  /** The report schema: digests as lowercase hex, `u64` ids as decimal
   * strings, counts as numbers, no floats. */
  asDict(): {
    reference_id: string;
    candidate_id: string;
    id_kind: "u64" | "utf8";
    config: Record<string, string | number>;
    added: string[];
    removed: string[];
    changed: Array<[string, number]>;
    n_unchanged: number;
    manifest_changes: Record<string, [string | null, string | null]>;
  } {
    const render = (id: bigint | string): string => (typeof id === "bigint" ? id.toString() : id);
    const added: Array<bigint | string> = this.added;
    const removed: Array<bigint | string> = this.removed;
    return {
      reference_id: hex(this.referenceId),
      candidate_id: hex(this.candidateId),
      id_kind: this.idKind,
      config: this.config.asDict(),
      added: added.map(render),
      removed: removed.map(render),
      changed: this.changed.map(([id, h]): [string, number] => [render(id), h]),
      n_unchanged: this.nUnchanged,
      manifest_changes: this.manifestChanges,
    };
  }
}
