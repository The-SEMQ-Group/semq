// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

import { ABI } from "./layout.js";

import { InvalidInput } from "./errors.js";
import { type Arena, scoped } from "./module.js";
import { call, rt, type Runtime } from "./runtime.js";

/** The three operators. Values are pinned: they appear in the canonical form. */
export enum Operator {
  Orbit = 0,
  Phase = 1,
  Quant = 2,
}

const OPERATOR_NAME = ["orbit", "phase", "quant"] as const;
const PARAMETER_NAME = ["scale", "sectors", "bins"] as const;

/**
 * An immutable value: operator, dimension and the operator's parameter.
 * Build one with {@link CodecConfig.quant}, {@link CodecConfig.phase} or
 * {@link CodecConfig.orbit}; the core validates every parameter and computes
 * every derived quantity. Equality is equality of the 13 canonical bytes.
 */
export class CodecConfig {
  /** op, dim, p1, p2: the `semq_config_t` fields. */
  private readonly raw: Uint32Array;
  private readonly canonical: Uint8Array;
  private readonly bpv: number;
  private readonly upr: number;
  private readonly magnitude: number;

  private constructor(raw: Uint32Array, canonical: Uint8Array, bpv: number, upr: number, magnitude: number) {
    this.raw = raw;
    this.canonical = canonical;
    this.bpv = bpv;
    this.upr = upr;
    this.magnitude = magnitude;
  }

  /** @internal Copy a valid `semq_config_t` the core owns or the caller just filled. */
  static fromPointer(r: Runtime, cfg: number): CodecConfig {
    const { w, core } = r;
    const raw = Uint32Array.from([ABI.config.op, ABI.config.dim, ABI.config.p1, ABI.config.p2], (offset) => w.getU32(cfg + offset));
    return scoped(w, (a) => {
      const out = a.alloc(13);
      core.configToBytes(cfg, out);
      return new CodecConfig(
        raw,
        w.readU8(out, 13),
        core.configBytesPerVector(cfg),
        core.configUnitsPerRow(cfg),
        core.configMaxMagnitude(cfg),
      );
    });
  }

  private static make(op: Operator, dim: number, p1: number): CodecConfig {
    const r = rt();
    checkU32(dim, "dim");
    checkU32(p1, PARAMETER_NAME[op]);
    const ctor =
      op === Operator.Quant ? r.core.configQuant : op === Operator.Phase ? r.core.configPhase : r.core.configOrbit;
    return scoped(r.w, (a) => {
      const out = a.alloc(ABI.config.size);
      call(r, `config.${OPERATOR_NAME[op]}`, (err) => ctor(dim, p1, out, err));
      return CodecConfig.fromPointer(r, out);
    });
  }

  /** quant: sign and magnitude bin per coordinate; `bins` in [2, 64]. */
  static quant(dim: number, bins: number): CodecConfig {
    return CodecConfig.make(Operator.Quant, dim, bins);
  }

  /** @internal Adapt ABI fields, leaving validation and canonical bytes to C. */
  static fromFields(op: number, dim: number, p1: number, p2: number): CodecConfig {
    const fields = [op, dim, p1, p2];
    for (const value of fields) checkU32(value, "config field");
    const r = rt();
    return scoped(r.w, (a) => {
      const cfg = a.alloc(ABI.config.size);
      [ABI.config.op, ABI.config.dim, ABI.config.p1, ABI.config.p2].forEach((offset, i) => r.w.setU32(cfg + offset, fields[i]!));
      call(r, "config", (err) => r.core.configValidate(cfg, err));
      return CodecConfig.fromPointer(r, cfg);
    });
  }

  /** phase: angular sector per coordinate pair; `sectors` in [2, 256]. */
  static phase(dim: number, sectors: number): CodecConfig {
    return CodecConfig.make(Operator.Phase, dim, sectors);
  }

  /** orbit: digital-root symbol per coordinate; `scale` in [1, 2^30]. */
  static orbit(dim: number, scale = 50): CodecConfig {
    return CodecConfig.make(Operator.Orbit, dim, scale);
  }

  /** Parse the 13-byte canonical form. */
  static fromBytes(data: Uint8Array): CodecConfig {
    const r = rt();
    if (!(data instanceof Uint8Array) || data.length !== 13) {
      throw new InvalidInput("config canonical form is a Uint8Array of 13 bytes");
    }
    return scoped(r.w, (a) => {
      const input = a.u8(data);
      const out = a.alloc(ABI.config.size);
      call(r, "config.fromBytes", (err) => r.core.configFromBytes(input, out, err));
      return CodecConfig.fromPointer(r, out);
    });
  }

  /** The 13-byte canonical form (a copy). */
  toBytes(): Uint8Array {
    return this.canonical.slice();
  }

  /** @internal Write a `semq_config_t` into the arena. */
  write(a: Arena): number {
    const cfg = a.alloc(ABI.config.size);
    [ABI.config.op, ABI.config.dim, ABI.config.p1, ABI.config.p2].forEach((offset, i) => a.w.setU32(cfg + offset, this.raw[i]!));
    return cfg;
  }

  get operator(): Operator {
    return this.raw[0]!;
  }

  get dim(): number {
    return this.raw[1]!;
  }

  /** Operator rule revision (`p2`), 0 for this core. */
  get ruleRevision(): number {
    return this.raw[3]!;
  }

  /** quant only. */
  get bins(): number {
    this.only(Operator.Quant, "bins");
    return this.raw[2]!;
  }

  /** phase only. */
  get sectors(): number {
    this.only(Operator.Phase, "sectors");
    return this.raw[2]!;
  }

  /** orbit only. */
  get scale(): number {
    this.only(Operator.Orbit, "scale");
    return this.raw[2]!;
  }

  get bytesPerVector(): number {
    return this.bpv;
  }

  get unitsPerRow(): number {
    return this.upr;
  }

  /** quant only: `(float)(2.0 / sqrt(dim))` as the core computes it, the
   * binary32 value as a JavaScript number. */
  get maxMagnitude(): number {
    this.only(Operator.Quant, "maxMagnitude");
    return this.magnitude;
  }

  private only(op: Operator, name: string): void {
    if (this.operator !== op) {
      throw new InvalidInput(`${name} applies to ${OPERATOR_NAME[op]} configs only`);
    }
  }

  /** True when `other` has the same canonical bytes. */
  equals(other: CodecConfig): boolean {
    if (!(other instanceof CodecConfig)) return false;
    for (let i = 0; i < 13; i++) if (this.canonical[i] !== other.canonical[i]) return false;
    return true;
  }

  /** `{ operator, dim, <bins | sectors | scale>, rule_revision }` as in reports. */
  asDict(): Record<string, string | number> {
    return {
      operator: OPERATOR_NAME[this.operator],
      dim: this.dim,
      [PARAMETER_NAME[this.operator]]: this.raw[2]!,
      rule_revision: this.ruleRevision,
    };
  }

  /** @internal `quant(dim=4, bins=4)`: the form the other summaries embed. */
  summary(): string {
    return `${OPERATOR_NAME[this.operator]}(dim=${this.dim}, ${PARAMETER_NAME[this.operator]}=${this.raw[2]})`;
  }

  toString(): string {
    return `CodecConfig.${OPERATOR_NAME[this.operator]}(dim=${this.dim}, ${PARAMETER_NAME[this.operator]}=${this.raw[2]})`;
  }
}

function checkU32(value: unknown, name: string): asserts value is number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0 || value > 0xffffffff) {
    throw new InvalidInput(`${name} must be an integer in [0, 2^32)`);
  }
}
