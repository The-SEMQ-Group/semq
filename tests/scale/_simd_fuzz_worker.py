# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Subprocess worker for the SIMD differential-fuzz test.

Reads a corpus bundle (an .npz of named float32 arrays), normalizes every
row (the codec admits unit-norm rows only), encodes every corpus with every
operator under whatever kernel the dispatcher selected for this process
(controlled by the parent via ``SEMQ_FORCE_BACKEND``), and prints one JSON
object to stdout::

    {"backend": {"orbit": "neon", ...}, "fingerprints": {"<case>|<op>": "<hex>", ...}}

The parent runs this once per backend and asserts the fingerprint maps are
identical: the SIMD path is byte-for-byte equal to the scalar reference on
every adversarial input.
"""

from __future__ import annotations

import json
import sys

import numpy as np

from semq import Codec, CodecConfig, InvalidInput, build_info


def _configs(dim: int):
    yield "quant", CodecConfig.quant(dim, 8)
    yield "phase", CodecConfig.phase(dim, 16)
    yield "orbit", CodecConfig.orbit(dim)


def _unit_rows(corpus: np.ndarray) -> np.ndarray:
    arr = corpus.astype(np.float64)
    finite = np.all(np.isfinite(arr), axis=1)
    norms = np.linalg.norm(arr, axis=1)
    keep = finite & (norms > 0) & np.isfinite(norms)
    arr = arr[keep] / norms[keep, None]
    return arr.astype(np.float32)


def main() -> int:
    data = np.load(sys.argv[1])
    fingerprints: dict[str, str] = {}
    for case_name in data.files:
        corpus = _unit_rows(data[case_name])
        if corpus.ndim != 2 or corpus.shape[0] == 0:
            continue
        dim = corpus.shape[1]
        ids = np.arange(corpus.shape[0], dtype=np.uint64)
        for op_label, cfg in _configs(dim):
            try:
                e = Codec(cfg).encode(ids=ids, vectors=corpus)
            except InvalidInput:
                # Out of the input contract after normalization (rounding put
                # the row outside the tolerance). Identical on every backend.
                continue
            fingerprints[f"{case_name}|{op_label}"] = e.content_digest.hex()
    print(json.dumps({"backend": build_info().backend, "fingerprints": fingerprints}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
