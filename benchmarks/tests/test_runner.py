# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""End-to-end report semantics and explicit input/configuration contracts."""

import json

import numpy as np
import pytest

from benchmarks.run import evaluate, load_data, validate, write_json


def config():
    return {
        "schema_version": 1,
        "suite": "codec_quality",
        "seed": 1,
        "k": [1, 2],
        "query_batch_size": 1,
        "methods": [{"id": "fp32", "name": "fp32"}],
        "synthetic": {"corpus_rows": 4, "fit_rows": 4, "query_rows": 3, "dim": 2},
    }


def test_labeled_reference_and_undefined_query_are_reported(tmp_path):
    x = np.array([[1, 0], [0, 1], [-1, 0]], dtype=np.float32)
    arrays = {
        "corpus": x,
        "fit": x,
        "queries": x[:2],
        "relevance": np.array([[3, 1, 0], [0, 0, 0]]),
    }
    report = evaluate(config(), arrays, tmp_path)[0]
    assert report["quality"]["score_rmse"] == 0
    assert report["quality"]["retrieval"]["1"]["ndcg"] == 1
    assert report["quality"]["retrieval"]["1"]["ndcg_eligible_queries"] == 1
    assert report["per_query"]["1"]["ndcg"] == [1, None]
    write_json(tmp_path / "report.json", report)
    assert json.loads((tmp_path / "report.json").read_text()) == report
    with pytest.raises(FileExistsError):
        write_json(tmp_path / "report.json", report)


def test_synthetic_smoke_does_not_invent_relevance(tmp_path):
    c = config()
    validate(c)
    arrays, source = load_data(c, None)
    report = evaluate(c, arrays, tmp_path)[0]
    assert source["kind"] == "synthetic_smoke"
    assert report["quality"]["retrieval"]["1"]["ndcg"] is None
    assert report["quality"]["retrieval"]["1"]["ndcg_status"] == "labels_unavailable"
    assert report["quality"]["retrieval"]["2"]["overlap"] == 1


def test_data_requires_explicit_fit_and_matching_relevance(tmp_path):
    p = tmp_path / "data.npz"
    x = np.ones((4, 2), dtype=np.float32)
    np.savez(p, corpus=x, queries=x)
    with pytest.raises(ValueError, match="explicit fit"):
        load_data(config(), p)
    np.savez(p, corpus=x, queries=x, fit=x, relevance=np.ones((1, 4)))
    with pytest.raises(ValueError, match="align"):
        load_data(config(), p)


@pytest.mark.parametrize(
    "change",
    [
        {"surprise": 1},
        {"schema_version": 2},
        {"k": [1, 1]},
        {"query_batch_size": 0},
        {"seed": -1},
    ],
)
def test_invalid_config_is_rejected(change):
    c = config()
    c.update(change)
    with pytest.raises(ValueError):
        validate(c)


def test_method_scoring_is_separate_from_reconstruction(tmp_path, monkeypatch):
    from benchmarks import codecs

    class ExampleCodec:
        def encode(self, fit, corpus):
            return codecs.Encoded(
                corpus,
                {},
                corpus,
                lambda q: -(q.astype(np.float64) @ corpus.T),
                "test_negative_ip",
            )

    monkeypatch.setattr(codecs, "build", lambda spec: ExampleCodec())
    c = config()
    c["method_scoring"] = True
    x = np.eye(2, dtype=np.float32)
    report = evaluate(
        c, {"corpus": x, "fit": x, "queries": x, "relevance": np.eye(2)}, tmp_path
    )[0]
    assert report["quality"]["retrieval"]["1"]["overlap"] == 1
    native = report["method_scoring"]
    assert native["profile"] == "test_negative_ip"
    assert native["quality"]["retrieval"]["1"]["overlap"] == 0
    assert native["quality"]["retrieval"]["1"]["ndcg"] == 0
    assert native["quality"]["score_rmse"] > 0
    assert report["quality"]["score_rmse"] == 0


def test_unsupported_method_scoring_does_not_fall_back(tmp_path):
    c = config()
    c["method_scoring"] = True
    arrays, _ = load_data(c, None)
    result = evaluate(c, arrays, tmp_path)[0]
    assert result["method_scoring"] == {"status": "not_supported"}
    c["method_scoring"] = "true"
    with pytest.raises(ValueError, match="boolean"):
        validate(c)


@pytest.mark.parametrize("bad", [np.zeros((1, 1)), np.full((3, 4), np.nan)])
def test_invalid_method_score_matrix_fails(bad):
    from benchmarks.run import score_quality

    c = config()
    arrays, _ = load_data(c, None)
    with pytest.raises(ValueError, match="method scores"):
        score_quality(c, arrays, lambda q: bad)


def test_direction_profile_removes_scale_without_hiding_raw_error(
    tmp_path, monkeypatch
):
    from benchmarks import codecs

    class Scaled:
        def encode(self, fit, corpus):
            return codecs.Encoded(corpus, {}, corpus * 4)

    monkeypatch.setattr(codecs, "build", lambda spec: Scaled())
    c = config()
    c["direction_scoring"] = True
    x = np.eye(2, dtype=np.float32)
    result = evaluate(c, {"corpus": x, "fit": x, "queries": x}, tmp_path)[0]
    assert result["quality"]["normalized_squared_error"] == 9
    direction = result["direction_scoring"]
    assert direction["quality"]["direction_coordinate_mse"] == 0
    assert direction["quality"]["score_rmse"] == 0


def test_direction_profile_reports_zero_norms_explicitly():
    from benchmarks.run import direction_quality

    x = np.array([[0, 0], [1, 0]], dtype=np.float32)
    result = direction_quality(config(), {"corpus": x, "queries": x[1:]}, x)
    assert result["status"] == "not_comparable"
    assert result["zero_rows"] == {"corpus": 1, "queries": 0, "reconstruction": 1}
