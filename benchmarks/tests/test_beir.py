# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Full-corpus alignment and sparse relevance must preserve evaluation semantics."""

import numpy as np
import pytest

from benchmarks import metrics, relevance
from benchmarks.prepare_beir import align
from benchmarks.run import load_data, score_quality


def rows():
    return (
        [
            {"_id": "20", "title": " Title ", "text": " Body "},
            {"_id": "3", "text": "Distractor"},
            {"_id": "1", "text": "Answer"},
        ],
        [{"_id": "q2", "text": "Unused train query"}, {"_id": "q1", "text": " Test "}],
        [{"query-id": "q1", "corpus-id": "1", "score": 1}],
    )


def test_alignment_keeps_distractors_and_selects_only_official_test_queries():
    result = align(*rows())
    assert result["corpus_ids"].tolist() == ["1", "20", "3"]
    assert result["query_ids"].tolist() == ["q1"]
    assert result["corpus_text"] == ["Answer", "Title Body", "Distractor"]
    assert result["query_text"] == ["Test"]
    assert result["qrel_document"].tolist() == [0]


@pytest.mark.parametrize(
    "kind",
    ["duplicate_id", "duplicate_pair", "unknown_doc", "unknown_query", "negative"],
)
def test_alignment_rejects_invalid_sources(kind):
    corpus, queries, qrels = rows()
    if kind == "duplicate_id":
        corpus.append(corpus[0])
    elif kind == "duplicate_pair":
        qrels.append(qrels[0])
    elif kind == "unknown_doc":
        qrels[0]["corpus-id"] = "absent"
    elif kind == "unknown_query":
        qrels[0]["query-id"] = "absent"
    else:
        qrels[0]["score"] = -1
    with pytest.raises(ValueError):
        align(corpus, queries, qrels)


def test_sparse_ndcg_matches_dense_with_grades_zeros_and_batch_offset():
    dense = np.array([[0, 0, 0, 0], [3, 0, 1, 0], [0, 0, 0, 0], [0, 2, 1, 0]])
    q, d = np.nonzero(dense)
    sparse = {"qrel_query": q, "qrel_document": d, "qrel_score": dense[q, d]}
    relevance.validate(sparse, 4, 4)
    ids = np.array([[2, 0], [0, 3], [3, 2]])
    actual, mask = relevance.ndcg(sparse, ids, 1)
    expected, expected_mask = metrics.ndcg(dense[1:], ids)
    np.testing.assert_allclose(actual, expected, equal_nan=True)
    np.testing.assert_array_equal(mask, expected_mask)


def test_prepared_npz_preserves_provenance_and_scores_sparse_labels(tmp_path):
    x = np.eye(3, dtype=np.float32)
    p = tmp_path / "data.npz"
    np.savez(
        p,
        corpus=x,
        queries=x[:2],
        fit=x,
        corpus_ids=np.array(["a", "b", "c"]),
        query_ids=np.array(["1", "2"]),
        qrel_query=np.array([0, 1]),
        qrel_document=np.array([0, 1]),
        qrel_score=np.array([1.0, 2.0]),
        dataset_provenance=np.array('{"dataset":"test"}'),
    )
    config = {"k": [1, 2], "query_batch_size": 1}
    arrays, source = load_data(config, p)
    assert source["preparation"] == {"dataset": "test"}
    result = score_quality(config, arrays, lambda q: q @ x.T)
    assert result["quality"]["retrieval"]["1"]["ndcg"] == 1
    assert result["quality"]["retrieval"]["1"]["ndcg_eligible_queries"] == 2


@pytest.mark.parametrize(
    "q,d,s",
    [
        ([2], [0], [1]),
        ([0], [3], [1]),
        ([0, 0], [1, 1], [1, 2]),
        ([0], [0], [float("nan")]),
    ],
)
def test_sparse_validation_rejects_bad_coordinates_and_scores(q, d, s):
    with pytest.raises(ValueError):
        relevance.validate(
            {
                "qrel_query": np.array(q),
                "qrel_document": np.array(d),
                "qrel_score": np.array(s),
            },
            2,
            3,
        )
