# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Pure metric definitions shared by benchmark runners.

Scores rank descending, breaking ties by ascending corpus row index. nDCG
uses linear nonnegative relevance gains and excludes queries with zero IDCG.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np


def ranking(scores: np.ndarray, k: int) -> np.ndarray:
    scores = np.asarray(scores, dtype=np.float64)
    if scores.ndim != 2 or not np.isfinite(scores).all():
        raise ValueError("scores must be a finite query-by-corpus matrix")
    if not 1 <= k <= scores.shape[1]:
        raise ValueError("k must fit the corpus")
    return np.argsort(-scores, axis=1, kind="stable")[:, :k]


def overlap(actual: np.ndarray, reference: np.ndarray) -> np.ndarray:
    actual, reference = np.asarray(actual), np.asarray(reference)
    if actual.ndim != 2 or actual.shape != reference.shape or actual.shape[1] == 0:
        raise ValueError("rankings must have the same nonempty width")
    if any(len(set(row)) != len(row) for rows in (actual, reference) for row in rows):
        raise ValueError("rankings must contain unique IDs")
    return np.array(
        [len(set(a) & set(b)) / len(a) for a, b in zip(actual, reference, strict=True)]
    )


def ndcg(relevance: np.ndarray, ids: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return values plus eligibility mask; ineligible queries have NaN internally."""
    relevance, ids = np.asarray(relevance, dtype=np.float64), np.asarray(ids)
    if relevance.ndim != 2 or not np.isfinite(relevance).all() or (relevance < 0).any():
        raise ValueError("relevance must be finite and nonnegative")
    if ids.ndim != 2 or ids.shape[0] != relevance.shape[0] or ids.shape[1] == 0:
        raise ValueError("ranking shape does not match relevance")
    if (
        not np.issubdtype(ids.dtype, np.integer)
        or (ids < 0).any()
        or (ids >= relevance.shape[1]).any()
    ):
        raise ValueError("ranking IDs must index the corpus")
    if any(len(set(row)) != len(row) for row in ids):
        raise ValueError("ranking IDs must be unique")
    discounts = 1.0 / np.log2(np.arange(ids.shape[1]) + 2)
    ideal = np.sort(relevance, axis=1)[:, ::-1][:, : ids.shape[1]] @ discounts
    dcg = np.take_along_axis(relevance, ids, axis=1) @ discounts
    eligible = ideal > 0
    values = np.full(len(ids), np.nan)
    np.divide(dcg, ideal, out=values, where=eligible)
    return values, eligible


def latency_summary(samples_ns: list[int], *, min_tail_samples: int = 100) -> dict:
    """Nearest-rank percentiles with an explicit, configurable sample-count gate.

    This gate is a reporting policy, not a statistical confidence guarantee.
    Inputs are successful, timed operations; failures must be reported separately.
    """
    if min_tail_samples < 1 or any(not isinstance(x, int) or x < 0 for x in samples_ns):
        raise ValueError("latencies must be nonnegative integer nanoseconds")
    ordered = sorted(samples_ns)
    result: dict[str, Any] = {
        "unit": "ns",
        "count": len(ordered),
        "estimator": "nearest_rank",
        "percentiles": {},
    }
    for name, p, denominator in [
        ("p50", 0.5, 2),
        ("p95", 0.95, 20),
        ("p99", 0.99, 100),
        ("p99_9", 0.999, 1000),
    ]:
        minimum = min_tail_samples * denominator
        enough = len(ordered) >= minimum
        result["percentiles"][name] = {
            "value": ordered[math.ceil(p * len(ordered)) - 1] if enough else None,
            "status": "measured" if enough else "insufficient_samples",
            "minimum_samples": minimum,
        }
    return result


def storage(code_bytes: int, model_bytes: int, rows: int, dim: int) -> dict:
    if (
        min(code_bytes, model_bytes) < 0
        or min(rows, dim) <= 0
        or code_bytes + model_bytes == 0
    ):
        raise ValueError("invalid storage dimensions or byte counts")
    total = code_bytes + model_bytes
    return {
        "code_bytes": code_bytes,
        "model_bytes": model_bytes,
        "code_and_model_bytes": total,
        "bytes_per_embedding": total / rows,
        "code_bits_per_dimension": 8 * code_bytes / (rows * dim),
        "model_bits_per_dimension": 8 * model_bytes / (rows * dim),
        "effective_bits_per_dimension": 8 * total / (rows * dim),
        "ratio_vs_fp32_payload": 4 * rows * dim / total,
        "scope": "array_payload_and_model; excludes file envelope, index and runtime memory",
    }


def paired_ndcg_interval(
    actual: list, reference: list, *, samples: int, confidence: float, seed: int
) -> dict:
    """Percentile bootstrap of paired per-query nDCG differences."""
    if len(actual) != len(reference):
        raise ValueError("paired observations must have equal lengths")
    if type(samples) is not int or samples < 1 or not 0 < confidence < 1 or seed < 0:
        raise ValueError("invalid bootstrap settings")
    differences = []
    for a, b in zip(actual, reference, strict=True):
        if (a is None) != (b is None):
            raise ValueError("paired observations need matching eligibility")
        if a is not None:
            if not np.isfinite([a, b]).all():
                raise ValueError("bootstrap observations must be finite")
            differences.append(a - b)
    if not differences:
        return {"status": "unavailable", "eligible_queries": 0}
    values = np.asarray(differences)
    rng = np.random.Generator(np.random.PCG64(seed))
    means = np.asarray(
        [
            np.mean(values[rng.integers(len(values), size=len(values))])
            for _ in range(samples)
        ]
    )
    tail = (1 - confidence) / 2
    low, high = np.quantile(means, [tail, 1 - tail])
    return {
        "status": "measured",
        "method": "paired_query_percentile_bootstrap",
        "confidence": confidence,
        "samples": samples,
        "seed": seed,
        "eligible_queries": len(values),
        "mean_delta": float(values.mean()),
        "lower": float(low),
        "upper": float(high),
    }
