# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Sparse relevance judgments aligned to stable query and corpus rows."""

import numpy as np

FIELDS = {"qrel_query", "qrel_document", "qrel_score"}


def validate(arrays: dict, queries: int, documents: int) -> None:
    if FIELDS & arrays.keys() != FIELDS:
        raise ValueError("sparse relevance requires query, document and score arrays")
    q, d, s = (arrays[name] for name in ("qrel_query", "qrel_document", "qrel_score"))
    if q.ndim != 1 or d.shape != q.shape or s.shape != q.shape:
        raise ValueError(
            "sparse relevance arrays must have matching one-dimensional shapes"
        )
    if (
        not np.issubdtype(q.dtype, np.integer)
        or not np.issubdtype(d.dtype, np.integer)
        or (q < 0).any()
        or (q >= queries).any()
        or (d < 0).any()
        or (d >= documents).any()
    ):
        raise ValueError("sparse relevance IDs must index queries and corpus")
    if not np.isfinite(s).all() or (s < 0).any():
        raise ValueError("sparse relevance must be finite and nonnegative")
    if len(set(zip(q.tolist(), d.tolist(), strict=True))) != len(q):
        raise ValueError("duplicate sparse relevance pair")


def ndcg(arrays: dict, ids: np.ndarray, start: int) -> tuple[np.ndarray, np.ndarray]:
    discounts = 1 / np.log2(np.arange(ids.shape[1]) + 2)
    values = np.full(len(ids), np.nan)
    for offset, ranking in enumerate(ids):
        selected = arrays["qrel_query"] == start + offset
        judgments = dict(
            zip(
                arrays["qrel_document"][selected],
                arrays["qrel_score"][selected],
                strict=True,
            )
        )
        gains = sorted(judgments.values(), reverse=True)[: len(ranking)]
        ideal = np.dot(gains, discounts[: len(gains)])
        if ideal > 0:
            values[offset] = (
                np.dot([judgments.get(int(d), 0) for d in ranking], discounts) / ideal
            )
    return values, np.isfinite(values)
