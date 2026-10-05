# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Persisted artifacts and estimator agreement with upstream Faiss search."""

from typing import Any, cast

import numpy as np
import pytest

from benchmarks import codecs
from benchmarks.faiss_codecs import restore, single_thread

faiss = pytest.importorskip("faiss")

SPECS = [
    {"name": "faiss_sq", "bits": 4},
    {"name": "faiss_sq", "bits": 8},
    {"name": "faiss_opq", "bits": 4, "subquantizers": 4, "iterations": 4},
    *[{"name": "faiss_rabitq", "bits": b} for b in (1, 2, 4)],
    *[{"name": "faiss_turboquant_mse", "bits": b} for b in (1, 2, 3, 4, 8)],
]


@pytest.mark.parametrize("spec", SPECS)
def test_artifact_roundtrip_and_native_scores(spec, tmp_path):
    rng = np.random.default_rng(13)
    fit = rng.normal(size=(640, 16)).astype(np.float32)
    corpus = rng.normal(size=(13, 16)).astype(np.float32)
    queries = rng.normal(size=(4, 16)).astype(np.float32)
    corpus[0] = 0
    queries[0] = 0
    previous_threads = faiss.omp_get_max_threads()
    encoded = codecs.build(spec).encode(fit, corpus)
    assert faiss.omp_get_max_threads() == previous_threads
    path = tmp_path / "artifact.npz"
    payload: dict[str, Any] = {"codes": encoded.codes, **encoded.model}
    np.savez(path, **payload)
    with np.load(path, allow_pickle=False) as saved:
        model = {key: saved[key] for key in encoded.model}
        loaded = restore(saved["codes"], model)
    np.testing.assert_array_equal(loaded.reconstruction, encoded.reconstruction)
    assert loaded.score is not None and encoded.score is not None
    np.testing.assert_array_equal(loaded.score(queries), encoded.score(queries))
    assert faiss.omp_get_max_threads() == previous_threads
    assert encoded.model_bytes == sum(array.nbytes for array in model.values())

    index = faiss.deserialize_index(model["faiss_model"])
    assert index.ntotal == 0
    index.add_sa_codes(encoded.codes)
    q = queries
    if "rotation" in model:
        rotation = model["rotation"]
        np.testing.assert_allclose(rotation @ rotation.T, np.eye(16), atol=2e-6)
        q = np.ascontiguousarray(q @ rotation.T)
    with single_thread(faiss):
        distances, ids = index.search(q, len(corpus))
    direct = np.empty((len(q), len(corpus)), dtype=np.float64)
    with single_thread(faiss):
        dc = cast(Any, index).get_FlatCodesDistanceComputer()
        for row, query in enumerate(q):
            dc.set_query(faiss.swig_ptr(query))
            direct[row] = [dc(i) for i in range(len(corpus))]
    expected = np.empty_like(distances, dtype=np.float64)
    np.put_along_axis(expected, ids, distances, axis=1)
    np.testing.assert_allclose(expected, direct, rtol=2e-6, atol=2e-6)
    if "row_norms" in model:
        expected *= model["row_norms"][None, :]
        np.testing.assert_array_equal(loaded.reconstruction[0], np.zeros(16))
    np.testing.assert_allclose(loaded.score(queries), expected, rtol=2e-6, atol=2e-6)
    assert np.isfinite(loaded.reconstruction).all()
    assert np.isfinite(expected).all()


def test_sq4_odd_dimensions_and_constant_training_coordinates():
    fit = np.array([[0, 3, -1], [1, 3, 1]], dtype=np.float32)
    x = np.array([[-4, 3, 5]], dtype=np.float32)
    encoded = codecs.build({"name": "faiss_sq", "bits": 4}).encode(fit, x)
    assert encoded.codes.nbytes == 2
    assert encoded.reconstruction[0, 1] == 3


def test_turboquant_preserves_row_magnitude_and_zero_rows():
    rng = np.random.default_rng(4)
    x = rng.normal(size=(5, 16)).astype(np.float32)
    x[0] = 0
    codec = codecs.build({"name": "faiss_turboquant_mse", "bits": 2})
    a, b = codec.encode(x, x), codec.encode(x, 8 * x)
    np.testing.assert_array_equal(a.codes, b.codes)
    np.testing.assert_allclose(b.reconstruction, 8 * a.reconstruction)
    assert a.score is not None and b.score is not None
    np.testing.assert_allclose(b.score(x), 8 * a.score(x))
    assert a.model["row_norms"].nbytes == len(x) * 4


@pytest.mark.parametrize(
    "spec",
    [
        {"name": "faiss_sq", "bits": 2},
        {"name": "faiss_rabitq", "bits": 0},
        {"name": "faiss_turboquant_mse", "bits": 5},
        {"name": "faiss_opq", "bits": 4, "subquantizers": 0},
        {"name": "faiss_opq", "bits": 4, "subquantizers": 2, "iterations": 0},
        {"name": "faiss_rabitq", "bits": 2, "seed": True},
        {"name": "faiss_sq", "bits": 4, "rotation": True},
    ],
)
def test_invalid_parameters(spec):
    with pytest.raises(ValueError):
        codecs.build(spec)


def test_opq_rejects_padding_and_insufficient_training():
    codec = codecs.build({"name": "faiss_opq", "bits": 4, "subquantizers": 2})
    with pytest.raises(ValueError, match="divisible"):
        codec.encode(
            np.ones((32, 3), dtype=np.float32), np.ones((2, 3), dtype=np.float32)
        )
    with pytest.raises(ValueError, match="fit rows"):
        codec.encode(
            np.ones((8, 4), dtype=np.float32), np.ones((2, 4), dtype=np.float32)
        )


@pytest.mark.parametrize("spec", SPECS[:6])
def test_training_state_does_not_use_evaluation_corpus(spec):
    rng = np.random.default_rng(8)
    fit = rng.normal(size=(640, 16)).astype(np.float32)
    x = rng.normal(size=(5, 16)).astype(np.float32)
    codec = codecs.build(spec)
    a, b = codec.encode(fit, x), codec.encode(fit, x * 3)
    np.testing.assert_array_equal(a.model["faiss_model"], b.model["faiss_model"])
    if "rotation" in a.model:
        np.testing.assert_array_equal(a.model["rotation"], b.model["rotation"])


def test_multibit_rabitq_is_excluded_from_reconstruction_comparisons(tmp_path):
    from benchmarks.run import evaluate

    rng = np.random.default_rng(9)
    x = rng.normal(size=(8, 8)).astype(np.float32)
    c = {
        "k": [1],
        "query_batch_size": 2,
        "direction_scoring": True,
        "method_scoring": True,
        "methods": [{"id": "rq2", "name": "faiss_rabitq", "bits": 2}],
    }
    report = evaluate(c, {"corpus": x, "fit": x, "queries": x[:2]}, tmp_path)[0]
    assert report["quality"]["status"] == "not_comparable"
    assert "retrieval" not in report["quality"]
    assert report["direction_scoring"]["status"] == "not_comparable"
    assert report["method_scoring"]["status"] == "measured"
