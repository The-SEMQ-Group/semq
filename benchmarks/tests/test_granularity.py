# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Granularity must score drift checks and changed ids exactly."""

import numpy as np
import pytest

from benchmarks import granularity


def unit(x):
    return (x / np.linalg.norm(x, axis=1, keepdims=True)).astype(np.float32)


def test_edit_keeps_first_half_of_words():
    assert granularity.edit("a b c d e") == "a b"
    assert granularity.edit("  one   two ") == "one"


def test_rows_are_fixed_by_the_seed_and_nested():
    a, b = granularity.edited_rows(100), granularity.edited_rows(100)
    assert np.array_equal(a, b) and sorted(a.tolist()) == list(range(100))
    assert granularity.row_count(5183, 0.1) == 5
    assert granularity.row_count(5183, 1) == 52
    assert granularity.row_count(5183, 50) == 2592
    assert granularity.row_count(10, 0.1) == 1


def test_roc_auc_matches_pair_counting_with_ties():
    labels = np.array([0, 0, 1, 1, 0, 1])
    scores = np.array([0.1, 0.4, 0.4, 0.8, 0.2, 0.3])
    pairs = [
        1.0 if p > n else 0.5 if p == n else 0.0
        for p in scores[labels == 1]
        for n in scores[labels == 0]
    ]
    assert granularity.roc_auc(labels, scores) == pytest.approx(np.mean(pairs))


def test_drift_checks_quiet_on_same_distribution_and_loud_on_shift():
    rng = np.random.default_rng(0)
    # Embeddings share a common direction, so their centroid is far from zero.
    common, other = np.eye(8)[0] * 3.0, np.eye(8)[1] * 3.0
    ref = unit(rng.standard_normal((4000, 8)) + common)
    same = unit(rng.standard_normal((4000, 8)) + common)
    shifted = unit(rng.standard_normal((4000, 8)) + other)
    quiet = granularity.drift_checks(ref, same)
    loud = granularity.drift_checks(ref, shifted)
    assert not quiet["classifier_drift"] and not quiet["centroid_cosine_drift"]
    assert loud["classifier_drift"] and loud["classifier_roc_auc"] > 0.99
    assert loud["centroid_cosine_drift"]


def test_changed_set_scores():
    s = granularity.changed_set_scores({1, 2, 3}, {2, 3, 4, 5})
    assert (s["true_positives"], s["false_positives"], s["missed"]) == (2, 1, 2)
    assert s["precision"] == pytest.approx(2 / 3) and s["recall"] == 0.5
    assert not s["exact"]
    assert granularity.changed_set_scores({7}, {7})["exact"]


def test_semq_diff_lists_exactly_the_replaced_rows():
    from semq import Codec, Floor

    rng = np.random.default_rng(1)
    ref = unit(rng.standard_normal((100, 16)))
    rows = granularity.edited_rows(100)[:5]
    cand = granularity.replace_rows(ref, rows, unit(rng.standard_normal((5, 16))))
    codec = Codec(granularity.rebuild.semq_config("semq_quant4", 16))
    ids = np.arange(100, dtype=np.uint64)
    manifest = {"encoder": "e", "encoder_revision": "1"}
    state = codec.encode(ids=ids, vectors=ref, manifest=manifest)
    floor = Floor.measure(
        [state.diff(codec.encode(ids=ids, vectors=ref, manifest=manifest))]
    )
    changed, summary = granularity.semq_diff(codec, state, cand, manifest, floor)
    assert changed == {int(i) for i in rows}
    assert not summary["within"]
