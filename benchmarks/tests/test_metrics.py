# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Hand-checkable contracts, including undefined metrics and percentile gates."""

import numpy as np
import pytest

from benchmarks import metrics


def test_ties_use_ascending_corpus_row():
    assert metrics.ranking(np.array([[1, 2, 2, 0]]), 3).tolist() == [[1, 2, 0]]


def test_overlap_ignores_order_but_not_missing_neighbors():
    values = metrics.overlap(np.array([[2, 1], [2, 3]]), np.array([[1, 2], [0, 2]]))
    assert values.tolist() == [1, 0.5]


def test_ndcg_linear_gain_and_zero_ideal_policy():
    values, eligible = metrics.ndcg(
        np.array([[3, 1, 0], [0, 0, 0]]), np.array([[1, 0], [0, 1]])
    )
    discount = 1 / np.log2(3)
    assert values[0] == pytest.approx((1 + 3 * discount) / (3 + discount))
    assert np.isnan(values[1]) and eligible.tolist() == [True, False]


@pytest.mark.parametrize(
    "rel,ids",
    [
        ([[-1, 0]], [[0]]),
        ([[np.nan, 0]], [[0]]),
        ([[1, 0]], [[2]]),
        ([[1, 0]], [[0, 0]]),
    ],
)
def test_ndcg_rejects_invalid_inputs(rel, ids):
    with pytest.raises(ValueError):
        metrics.ndcg(np.array(rel), np.array(ids))


def test_small_latency_sample_does_not_publish_extreme_percentile():
    result = metrics.latency_summary(list(range(1000)))["percentiles"]
    assert result["p50"]["value"] == 499
    assert result["p99"]["value"] is None
    assert result["p99_9"]["status"] == "insufficient_samples"


def test_latency_nearest_rank_and_tail_policy():
    result = metrics.latency_summary(list(range(100000)))["percentiles"]
    assert result["p99"]["value"] == 98999
    assert result["p99_9"]["value"] == 99899
    assert metrics.latency_summary([])["percentiles"]["p50"]["value"] is None


def test_storage_counts_model_and_does_not_claim_index_size():
    value = metrics.storage(100, 20, 10, 10)
    assert value["effective_bits_per_dimension"] == 9.6
    assert value["bytes_per_embedding"] == 12
    assert "index" not in value


@pytest.mark.parametrize("k", [1, 4])
def test_ndcg_equal_gains_remain_ideal_for_any_tie_order(k):
    values, eligible = metrics.ndcg(
        np.full((1, 4), 3.0), np.array([[3, 1, 0, 2]])[:, :k]
    )
    np.testing.assert_allclose(values, [1.0], rtol=0, atol=1e-15)
    assert eligible.tolist() == [True]


def test_storage_breakdown_sums_to_effective_bits():
    result = metrics.storage(100, 20, 10, 10)
    assert result["code_bits_per_dimension"] == 8
    assert result["model_bits_per_dimension"] == 1.6
    assert result["effective_bits_per_dimension"] == 9.6


def test_paired_bootstrap_uses_shared_queries_and_excludes_undefined():
    from benchmarks.metrics import paired_ndcg_interval

    result = paired_ndcg_interval(
        [0.5, None, 0.25], [0.75, None, 0.5], samples=200, confidence=0.95, seed=1
    )
    assert result["eligible_queries"] == 2
    assert result["lower"] == result["upper"] == result["mean_delta"] == -0.25
    assert (
        paired_ndcg_interval([], [], samples=20, confidence=0.95, seed=1)["status"]
        == "unavailable"
    )
    with pytest.raises(ValueError, match="eligibility"):
        paired_ndcg_interval([None], [1.0], samples=20, confidence=0.95, seed=1)
