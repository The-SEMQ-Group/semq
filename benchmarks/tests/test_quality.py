# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Collection of quality runs into the retained-quality result file."""

import json

import numpy as np
import pytest

from benchmarks import quality
from benchmarks.run import evaluate

BEIR = {
    "datasets": {
        "tiny": {
            "repo": "example/tiny",
            "revision": "a" * 40,
            "qrels_repo": "example/tiny-qrels",
            "qrels_revision": "b" * 40,
            "corpus_rows": 64,
            "test_queries": 6,
        }
    },
    "models": {
        name: {
            "repo": f"example/{name}",
            "revision": revision * 40,
            "query_prefix": "",
            "document_prefix": "",
            "dimension": 512,
            **({"matryoshka": True} if name == "arctic_m" else {}),
        }
        for name, revision in (("e5_small", "c"), ("arctic_m", "d"))
    },
}
FROZEN = {
    "release": "released",
    "inputs": {
        "tiny-e5": {
            "files": [{"file": "embeddings.npz", "asset": "tiny-e5.npz", "sha256": "1"}]
        }
    },
    "pending": {"release": "next", "inputs": {}},
}


def report(tmp_path, model, methods):
    rng = np.random.default_rng(3)
    x = rng.standard_normal((64, 512)).astype(np.float32)
    x /= np.linalg.norm(x, axis=1, keepdims=True)
    queries = x[:6] + 0.3 * rng.standard_normal((6, 512)).astype(np.float32)
    queries /= np.linalg.norm(queries, axis=1, keepdims=True)
    relevance = np.zeros((6, 64))
    relevance[np.arange(6), np.arange(6)] = 1
    relevance[np.arange(6), np.arange(6) + 10] = 1
    config = {
        "k": [10],
        "query_batch_size": 4,
        "methods": methods,
        "method_scoring": True,
        "direction_scoring": True,
        "uncertainty": {"bootstrap_samples": 50, "confidence": 0.95, "seed": 1},
    }
    arrays = {"corpus": x, "fit": x, "queries": queries, "relevance": relevance}
    directory = tmp_path / model
    directory.mkdir()
    spec = BEIR["models"][model]
    return {
        "status": "complete",
        "methods": evaluate(config, arrays, directory),
        "provenance": {"config_sha256": "cfg", "git_commit": "abc"},
        "dataset": {
            "sha256": "1" if model == "e5_small" else "2",
            "arrays": {"corpus": {"shape": [64, 512]}, "queries": {"shape": [6, 512]}},
            "preparation": {
                "dataset": "tiny",
                "sources": BEIR["datasets"]["tiny"],
                "model": {"repo": spec["repo"], "revision": spec["revision"]},
            },
        },
    }


BASE = [
    {"id": "fp32", "name": "fp32"},
    {"id": "fp8_e4m3", "name": "fp8_e4m3"},
    {"id": "st_binary", "name": "st_binary"},
]


def test_collects_retained_quality_and_marks_missing_cells(tmp_path):
    reports = [
        report(tmp_path, "e5_small", BASE),
        report(tmp_path, "arctic_m", BASE + [{"id": "mrl256", "name": "mrl256"}]),
    ]
    frozen = json.loads(json.dumps(FROZEN))
    frozen["pending"]["inputs"]["tiny-arctic"] = {
        "files": [{"file": "embeddings.npz", "asset": "tiny-arctic.npz", "sha256": "2"}]
    }
    inputs, results = quality.collect(
        reports,
        BEIR,
        frozen,
        {"arctic_m/tiny": "unused"},
        models=("e5_small", "arctic_m"),
        datasets=("tiny",),
    )
    e5 = results["table"]["e5_small"]["tiny"]
    assert e5["status"] == "measured" and e5["queries"] == 6
    fp32 = e5["methods"]["fp32"]
    assert fp32["ndcg10_retained_pct"] == 100 and fp32["overlap10"] == 100
    assert fp32["bits_per_dim"] == 32 and fp32["ndcg10_delta_ci"]["mean_delta"] == 0
    assert e5["methods"]["fp8_e4m3"]["bits_per_dim"] == pytest.approx(
        8 + 32 / (64 * 512)
    )
    assert e5["methods"]["st_binary"]["bits_per_dim"] == 1
    assert e5["methods"]["st_binary"]["scoring"] == "direction_scoring"
    assert e5["methods"]["mrl256"]["status"] == "not_applicable"
    arctic = results["table"]["arctic_m"]["tiny"]["methods"]
    assert arctic["mrl256"]["status"] == "measured"
    assert inputs["tiny-e5"]["sha256"] == "1"
    assert "released asset tiny-e5.npz (uploaded)" in inputs["tiny-e5"]["source"]
    assert "pending upload" in inputs["tiny-arctic"]["source"]
    assert results["models"]["arctic_m"]["matryoshka"] is True
    json.dumps(results, allow_nan=False)

    _, partial = quality.collect(
        reports[:1],
        BEIR,
        frozen,
        {"arctic_m/tiny": "took too long"},
        models=("e5_small", "arctic_m"),
        datasets=("tiny",),
    )
    missing = partial["table"]["arctic_m"]["tiny"]
    assert missing["status"] == "not_run" and missing["reason"] == "took too long"
    assert "quality-arctic.json" in missing["command"]


def test_rejects_unregistered_or_changed_inputs(tmp_path):
    reports = [report(tmp_path, "e5_small", BASE)]
    reports[0]["dataset"]["sha256"] = "changed"
    with pytest.raises(ValueError, match="registered sha256"):
        quality.collect(reports, BEIR, FROZEN, models=("e5_small",), datasets=("tiny",))
    reports[0]["dataset"]["preparation"]["model"]["revision"] = "e" * 40
    with pytest.raises(ValueError, match="not in beir-datasets"):
        quality.collect(reports, BEIR, FROZEN, models=("e5_small",), datasets=("tiny",))
