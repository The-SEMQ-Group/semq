// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

import { SDK_VERSION } from "./version.js";

/**
 * An argument violates its contract: representation (dtype, shape, a bigint
 * outside the u64 range, a lone surrogate), a non-finite or non-unit row, a
 * duplicate id, a non-canonical row, a config parameter out of range, an
 * invalid manifest or floor, or a disposed handle.
 *
 * `row` is the input row at fault when one applies; `field` the coordinate,
 * column, pair index or config field.
 */
export class InvalidInput extends Error {
  readonly row?: number;
  readonly field?: number;

  constructor(message: string, payload: { row?: number; field?: number } = {}) {
    super(message);
    this.name = "InvalidInput";
    this.row = payload.row;
    this.field = payload.field;
  }
}

/** Two states differ in config or id kind (`decode`, `unpack`, `diff`, `concat`). */
export class Incompatible extends Error {
  readonly field?: number;

  constructor(message: string, payload: { field?: number } = {}) {
    super(message);
    this.name = "Incompatible";
    this.field = payload.field;
  }
}

/**
 * A file image is not a valid version 2 image. `section` is the file section
 * that failed (0 framing, 1 config, 2 sizes, 3 ids, 4 manifest, 5 footer,
 * 6 rows); `row` the row index when a stored row is not canonical.
 */
export class FormatError extends Error {
  readonly row?: number;
  readonly section?: number;

  constructor(message: string, payload: { row?: number; section?: number } = {}) {
    super(message);
    this.name = "FormatError";
    this.row = payload.row;
    this.section = payload.section;
  }
}

/** A file image's digest does not match its footer. `which` names the check
 * that failed, not a cause. */
export class IntegrityError extends Error {
  readonly which?: "content" | "state";

  constructor(message: string, payload: { which?: "content" | "state" } = {}) {
    super(message);
    this.name = "IntegrityError";
    this.which = payload.which;
  }
}

/** The operation, or the floating-point environment, is not supported. */
export class Unsupported extends Error {
  readonly operation?: string;

  constructor(message: string, payload: { operation?: string } = {}) {
    super(message);
    this.name = "Unsupported";
    this.operation = payload.operation;
  }
}

/**
 * A defect in the core or the binding, or the wasm module could not be
 * loaded. Carries what a bug report needs and never input data.
 */
export class Native extends Error {
  readonly operation?: string;
  readonly status?: number;
  readonly row?: number;
  readonly field?: number;
  readonly sdkVersion: string;
  readonly coreVersion: string;
  readonly buildId: string;

  constructor(
    message: string,
    payload: {
      operation?: string;
      status?: number;
      row?: number;
      field?: number;
      coreVersion?: string;
      buildId?: string;
    } = {},
  ) {
    const coreVersion = payload.coreVersion ?? "unavailable";
    const buildId = payload.buildId ?? "unavailable";
    super(
      `${message} [operation=${payload.operation ?? "?"} status=${payload.status ?? "?"} ` +
        `sdk=${SDK_VERSION} core=${coreVersion} build=${buildId}]`,
    );
    this.name = "Native";
    this.operation = payload.operation;
    this.status = payload.status;
    this.row = payload.row;
    this.field = payload.field;
    this.sdkVersion = SDK_VERSION;
    this.coreVersion = coreVersion;
    this.buildId = buildId;
  }
}
