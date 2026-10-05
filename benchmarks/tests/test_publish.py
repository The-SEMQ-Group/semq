# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

import hashlib
import json
from copy import deepcopy

import pytest

from benchmarks.publish import PAGE, REPORTS, compact, page


def snapshot():
    config: dict = {
        "k": [10],
        "methods": [
            {"id": "fp32", "name": "fp32"},
            {"id": "rabitq4", "name": "faiss_rabitq", "bits": 4},
        ],
        "uncertainty": {"bootstrap_samples": 10, "confidence": 0.95, "seed": 1},
    }
    quality = {
        "status": "measured",
        "score_rmse": 0.0,
        "normalized_squared_error": 0.0,
        "direction_coordinate_mse": 0.0,
        "retrieval": {"10": {"ndcg": 1.0, "ndcg_status": "measured", "overlap": 1.0}},
    }
    methods = []
    for spec in config["methods"]:
        methods.append(
            {
                "id": spec["id"],
                "method": spec,
                "role": "reference",
                "quality": deepcopy(quality),
                "storage": {
                    "code_bits_per_dimension": 32.0,
                    "model_bits_per_dimension": 0.0,
                    "effective_bits_per_dimension": 32.0,
                },
                "direction_scoring": {
                    "status": "measured",
                    "profile": "cosine",
                    "quality": deepcopy(quality),
                },
                "method_scoring": {
                    "status": "measured",
                    "profile": "ip",
                    "quality": deepcopy(quality),
                },
            }
        )
    methods[1]["quality"] = {"status": "not_comparable"}
    methods[0]["method_scoring"] = {"status": "not_supported"}
    report = {
        "schema_version": 2,
        "suite": "codec_quality",
        "status": "complete",
        "scoring_profile": "ip",
        "provenance": {
            "working_tree_dirty": False,
            "git_commit": "abc1234",
            "platform": "test",
            "packages": {"semq": "stale-distribution", "numpy": "test"},
            "config_sha256": hashlib.sha256(
                json.dumps(config, sort_keys=True).encode()
            ).hexdigest(),
        },
        "dataset": {
            "kind": "user_npz",
            "arrays": {
                k: {"shape": [20, 2], "sha256": "fixture"}
                for k in ("corpus", "queries", "fit")
            },
            "preparation": {
                "dataset": "new-dataset",
                "device": "cpu",
                "model": {"repo": "example/model", "revision": "fixture"},
            },
        },
        "methods": methods,
    }
    evidence = {"status": "verified", "report_sha256": "fixture"}
    return compact(report, evidence, config, "fixture")


@pytest.mark.parametrize("problem", ["dirty", "verification", "config", "incomplete"])
def test_publication_rejects_unverified_or_mismatched_results(problem):
    report = snapshot()
    publication = report["publication"]
    if problem == "dirty":
        report["provenance"]["working_tree_dirty"] = True
    elif problem == "verification":
        publication["verification"]["report_sha256"] = "different report"
    elif problem == "config":
        publication["config"]["seed"] = 2
    else:
        report["status"] = "running"
    with pytest.raises(ValueError):
        compact(
            report,
            publication["verification"],
            publication["config"],
            publication["source_report_sha256"],
        )


def test_compaction_keeps_unavailable_results_and_hashes_without_local_details():
    report = snapshot()
    publication = report.pop("publication")
    report["dataset"]["path"] = "/private/input.npz"
    report["methods"][0]["per_query"] = {"10": {"ndcg": [1.0]}}
    original = deepcopy(report)
    result = compact(
        report,
        publication["verification"],
        publication["config"],
        publication["source_report_sha256"],
    )
    assert report == original
    assert "semq" not in result["provenance"]["packages"]
    assert "path" not in result["dataset"]
    assert "per_query" not in result["methods"][0]
    assert result["dataset"]["arrays"] == report["dataset"]["arrays"]
    rabitq = next(m for m in result["methods"] if m["id"] == "rabitq4")
    assert rabitq["quality"]["status"] == "not_comparable"
    assert rabitq["method_scoring"]["status"] == "measured"


def test_published_page_matches_all_versioned_reports():
    reports = [
        (p.name, json.loads(p.read_text())) for p in sorted(REPORTS.glob("*.json"))
    ]
    assert page(reports) == PAGE.read_text()
    for _, report in reports:
        assert len(report["methods"]) == len(report["publication"]["config"]["methods"])
        assert (
            report["publication"]["verification"]["profiles"]["quality"]["queries"]
            == report["dataset"]["arrays"]["queries"]["shape"][0]
        )


def test_new_dataset_and_public_number_format():
    from benchmarks.publish import cell

    text = page([("fixture.json", snapshot())])
    assert "new-dataset" in text
    assert "<table" not in text and "| ---" not in text
    assert "data-semq-detail-explorer" in text
    assert cell(0.123456) == "0.1235"
    assert "e-" not in cell(-0.000013)
    assert float(cell(-0.000013)) < 0
    assert "native estimators" in text
    assert 'data-files="[&quot;fixture.json&quot;]"' in text


def test_published_inputs_have_matching_download_hashes():
    from benchmarks.inputs import REGISTRY

    registry = json.loads(REGISTRY.read_text())
    hashes = {
        f["sha256"]
        for spec in registry["inputs"].values()
        for f in spec["files"]
        if f["file"] == "embeddings.npz"
    }
    for path in REPORTS.glob("*.json"):
        assert json.loads(path.read_text())["dataset"]["sha256"] in hashes


def test_compaction_preserves_a_paired_method_comparison():
    report = snapshot()
    publication = report.pop("publication")
    fp32 = report["methods"][0]
    quant4 = deepcopy(fp32)
    quant4["id"] = "quant4"
    quant4["method"] = {"id": "quant4", "name": "semq_quant", "bits": 4}
    for method, values in ((fp32, [1.0, 0.0]), (quant4, [0.5, 0.0])):
        method["direction_scoring"]["per_query"] = {"10": {"ndcg": values}}
        method["direction_scoring"]["quality"]["retrieval"]["10"]["ndcg"] = sum(
            values
        ) / len(values)
    report["methods"].append(quant4)
    publication["config"]["methods"].append(quant4["method"])
    report["provenance"]["config_sha256"] = hashlib.sha256(
        json.dumps(publication["config"], sort_keys=True).encode()
    ).hexdigest()
    result = compact(
        report, publication["verification"], publication["config"], "fixture"
    )
    interval = result["publication"]["paired_comparisons"]["quant4 vs fp32"]["10"]
    assert interval["mean_delta"] == -0.25
    assert interval["eligible_queries"] == 2
    assert "per_query" not in result["methods"][-1]["direction_scoring"]
