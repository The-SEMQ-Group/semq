// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

import { rt } from "./runtime.js";
import { SDK_VERSION } from "./version.js";

/**
 * Versions and kernel selection of the loaded core. `backend` maps each
 * operator to the kernel the core runs for it on this host. `buildId`
 * identifies a reproducible build recipe; it is not a provenance proof.
 */
export interface BuildInfo {
  sdkVersion: string;
  coreVersion: string;
  backend: { orbit: string; phase: string; quant: string };
  buildId: string;
}

/** Query the loaded core. */
export function buildInfo(): BuildInfo {
  const { core } = rt();
  return {
    sdkVersion: SDK_VERSION,
    coreVersion: core.coreVersion(),
    backend: { orbit: core.backendName(0), phase: core.backendName(1), quant: core.backendName(2) },
    buildId: core.buildId(),
  };
}
