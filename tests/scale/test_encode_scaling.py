# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Scale: encode throughput as corpus size grows.

A sharp drop between two adjacent sizes signals a real performance cliff
(allocator contention, cache overflow, a hidden quadratic path) that a
per-operation unit test would never surface.
"""

from __future__ import annotations

import numpy as np
import pytest

from semq import Codec, CodecConfig

_SIZES = [10_000, 100_000, 1_000_000]
_DIM = 32


@pytest.mark.slow
def test_encode_throughput_vs_corpus_size(scale_helpers) -> None:
    results: list[dict] = []
    rng = np.random.default_rng(0)
    codec = Codec(CodecConfig.quant(_DIM, 4))

    for n in _SIZES:
        corpus = rng.standard_normal((n, _DIM)).astype(np.float64)
        corpus /= np.linalg.norm(corpus, axis=1, keepdims=True)
        corpus = corpus.astype(np.float32)
        ids = np.arange(n, dtype=np.uint64)
        with scale_helpers.measure(f"encode_n={n}") as m:
            e = codec.encode(ids=ids, vectors=corpus)
        code_bytes = int(e.rows.nbytes)

        vectors_per_sec = n / m.elapsed_s if m.elapsed_s > 0 else 0.0
        results.append({
            "n": n,
            "elapsed_s": round(m.elapsed_s, 3),
            "vectors_per_sec": round(vectors_per_sec, 0),
            "bytes_per_vec": round(code_bytes / n, 2),
            "rss_delta_mb": round(m.rss_delta_mb, 1),
        })
        print(
            f"  n={n:>8d}  time={m.elapsed_s:>6.2f}s  throughput={vectors_per_sec:>8.0f} vec/s  "
            f"bytes/vec={code_bytes / n:>5.2f}  RSS Δ={m.rss_delta_mb:>+6.1f} MB"
        )

    scale_helpers.write_result("encode_scaling", {"sizes": results, "dim": _DIM})

    small = results[0]["vectors_per_sec"]
    big = results[-1]["vectors_per_sec"]
    assert big >= small * 0.2, (
        f"perf cliff: {small} vec/s at n={_SIZES[0]} → {big} vec/s at n={_SIZES[-1]}"
    )
