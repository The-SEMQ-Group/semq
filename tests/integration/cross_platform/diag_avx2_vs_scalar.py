# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Diagnostic for the AVX2 vs scalar bit-identity divergence.

Encodes a fixed deterministic float32 input twice — once with the
dispatcher forced to ``scalar``, once with it forced to ``avx2`` —
in the same process, then diffs the resulting codes dim-by-dim.

Designed to run inside the linux/amd64 container where both backends
are linked. Emits JSON on stdout with the active backend names, the
input sample, and the list of dimensions where codes differ.
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np


def _encode_with(backend: str, emb: np.ndarray):
    # Set the override BEFORE creating the Codec: the dispatcher reads
    # SEMQ_FORCE_BACKEND when the codec is created.
    os.environ["SEMQ_FORCE_BACKEND"] = backend
    from semq import Codec, CodecConfig

    codec = Codec(CodecConfig.orbit(int(emb.shape[1])))
    encoding = codec.encode(ids=np.arange(emb.shape[0], dtype=np.uint64), vectors=emb)
    return codec.backend, codec.unpack(encoding)


def main() -> int:
    rng = np.random.default_rng(seed=42)
    n_dim = int(os.environ.get("DIAG_DIM", "64"))
    emb = rng.standard_normal((1, n_dim)).astype(np.float32)
    emb /= np.linalg.norm(emb, axis=1, keepdims=True)

    scalar_active, codes_scalar = _encode_with("scalar", emb)
    avx2_active,   codes_avx2   = _encode_with("avx2",   emb)

    diffs = []
    for i in range(n_dim):
        s = int(codes_scalar[0, i])
        a = int(codes_avx2[0, i])
        if s != a:
            diffs.append({
                "dim": i,
                "input": float(emb[0, i]),
                "scaled_round_double": float(np.round(emb[0, i] * 50.0)),
                "scalar_code": s,
                "avx2_code":   a,
            })

    out = {
        "scalar_backend": scalar_active,
        "avx2_backend":   avx2_active,
        "scale":          50,
        "alphabet":       "default (19 dense)",
        "n_dims":         n_dim,
        "n_diffs":        len(diffs),
        "first_diffs":    diffs[:20],
    }
    print(json.dumps(out, indent=2))
    return 0 if len(diffs) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
