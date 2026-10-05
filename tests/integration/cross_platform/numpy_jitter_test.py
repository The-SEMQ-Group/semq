# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Cross-platform numpy determinism diagnostic — the counterfactual
behind the SEMQ replay claim.

If raw FP32 bytes from a deterministic numpy pipeline are byte-identical
across Darwin/arm64, Linux/aarch64, and Linux/x86_64, then SEMQ is NOT
required for cross-platform replay — vanilla numpy would suffice.

If any stage diverges, SEMQ's quantization is the only practical way
to get bit-identical agent state across machines — that is the proof
that the operator is required, not optional, for cross-platform replay.

Stages exercised (each produces float32 bytes that get SHA256'd):

  * A, B            : np.random.default_rng(42).standard_normal((1024, 1024))
  * C = A @ B       : GEMM call — most likely to diverge cross-arch
  * row_norms       : reduction (np.linalg.norm axis=1)
  * D = C / row_norms : elementwise division
  * SEMQ_codes      : the SEMQ canonical operator on D — should NEVER diverge

Output: JSON with platform info + per-stage SHA256 hex digests.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys

import numpy as np

from semq import Codec, CodecConfig


def _sha(arr: np.ndarray) -> str:
    return hashlib.sha256(
        np.ascontiguousarray(arr).tobytes()
    ).hexdigest()


def run(seed: int = 42, dim: int = 1024) -> dict:
    rng = np.random.default_rng(seed)
    A = rng.standard_normal((dim, dim)).astype(np.float32)
    B = rng.standard_normal((dim, dim)).astype(np.float32)
    h_A = _sha(A)
    h_B = _sha(B)

    C = (A @ B).astype(np.float32)
    h_C = _sha(C)

    row_norms = np.linalg.norm(C, axis=1, keepdims=True).astype(np.float32)
    h_norms = _sha(row_norms)

    safe = np.where(row_norms == 0, np.float32(1.0), row_norms)
    D = (C / safe).astype(np.float32)
    h_D = _sha(D)

    codec = Codec(CodecConfig.orbit(dim))
    encoding = codec.encode(ids=np.arange(dim, dtype=np.uint64), vectors=D)
    h_semq = encoding.content_digest.hex()

    return {
        "A_random": h_A,
        "B_random": h_B,
        "C_gemm": h_C,
        "row_norms_reduction": h_norms,
        "D_normalized": h_D,
        "SEMQ_codes": h_semq,
    }


def main() -> int:
    out = {
        "platform": f"{platform.system()}/{platform.machine()}",
        "python_version": sys.version.split()[0],
        "numpy_version": np.__version__,
        "stage_hashes": run(seed=42, dim=1024),
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
