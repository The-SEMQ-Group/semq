# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

import numpy as np
import pytest

from benchmarks import metrics, relevance
from benchmarks.run import evaluate
from benchmarks.verify_ndcg import external_ndcg, verify

pytest.importorskip("pytrec_eval")


@pytest.mark.parametrize("k", [1, 3, 10])
def test_ndcg_matches_trec_eval_with_graded_relevance_and_ties(k):
    rng = np.random.default_rng(17)
    rel = rng.integers(0, 4, size=(11, 20))
    rel[0] = 0
    ids = metrics.ranking(rng.integers(-2, 3, size=rel.shape), k)
    dense, eligible = metrics.ndcg(rel, ids)
    external = external_ndcg({"relevance": rel}, ids)
    q, d = np.nonzero(rel)
    sparse, mask = relevance.ndcg(
        {"qrel_query": q, "qrel_document": d, "qrel_score": rel[q, d]}, ids, 0
    )
    np.testing.assert_allclose(dense[eligible], external[eligible], rtol=0, atol=1e-12)
    np.testing.assert_allclose(sparse[mask], external[mask], rtol=0, atol=1e-12)
    assert not eligible[0] and external[0] == 0


def test_trec_eval_validation_does_not_truncate_fractional_gains():
    with pytest.raises(ValueError, match="integer gains"):
        external_ndcg({"relevance": np.array([[0.5, 1.0]])}, np.array([[0, 1]]))


def test_verifier_checks_stored_reference_values(tmp_path):
    corpus = np.array([[1, 0], [0, 1], [1, 1]], dtype=np.float32)
    arrays = {
        "corpus": corpus,
        "queries": corpus[:2],
        "fit": corpus,
        "relevance": np.array([[2, 0, 1], [0, 1, 0]]),
    }
    config = {
        "methods": [{"id": "fp32", "name": "fp32"}],
        "k": [2],
        "query_batch_size": 2,
        "direction_scoring": True,
    }
    report: dict = {
        "schema_version": 2,
        "status": "complete",
        "methods": evaluate(config, arrays, tmp_path),
    }
    assert verify(report, arrays)["status"] == "verified"
    report["methods"][0]["per_query"]["2"]["ndcg"][0] = 0
    with pytest.raises(ValueError, match="differs from trec_eval"):
        verify(report, arrays)
    report["methods"][0]["per_query"]["2"]["ndcg"][0] = float("nan")
    with pytest.raises(ValueError, match="non-finite"):
        verify(report, arrays)
