# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

import json
import subprocess
import sys
from copy import deepcopy

import pytest

from benchmarks.compare import PROTOCOL_SOURCES, compare


def report():
    return {
        "status": "complete",
        "schema_version": 2,
        "suite": "codec_quality",
        "scoring_profile": "ip",
        "dataset": {"arrays": {"corpus": {"sha256": "same"}}},
        "provenance": {
            "config_sha256": "same",
            "architecture": "arm64",
            "platform": "macOS",
            "python": "3.11.1",
            "packages": {"numpy": "2.4.6", "semq": "old"},
            "git_commit": "old",
            "benchmark_source_sha256": {
                f"benchmarks/{name}": "same" for name in PROTOCOL_SOURCES
            },
        },
        "methods": [
            {
                "id": "fp32",
                "method": {"name": "fp32"},
                "storage": {"code_bytes": 32, "model_bytes": 0},
                "quality": {
                    "status": "measured",
                    "score_rmse": 0,
                    "retrieval": {"10": {"ndcg": 0.5, "overlap": 1.0}},
                },
                "direction_scoring": {"status": "not_requested"},
                "method_scoring": {"status": "not_supported"},
            }
        ],
    }


def test_sdk_revision_changes_are_comparable_and_metric_changes_visible():
    old = report()
    new = deepcopy(old)
    new["provenance"].update(
        git_commit="new", packages={"numpy": "2.4.6", "semq": "new"}
    )
    assert compare(new, old)["status"] == "unchanged"
    new["methods"][0]["quality"]["retrieval"]["10"]["ndcg"] = 0.48
    result = compare(new, old)
    assert result["status"] == "changed"
    assert result["changes"][0]["delta"] == pytest.approx(-0.02)


@pytest.mark.parametrize("field", ["data", "config", "protocol", "environment"])
def test_incompatible_reports_are_not_compared(field):
    old, new = report(), report()
    if field == "data":
        new["dataset"]["arrays"]["corpus"]["sha256"] = "changed"
    elif field == "config":
        new["provenance"]["config_sha256"] = "changed"
    elif field == "protocol":
        new["provenance"]["benchmark_source_sha256"][
            "benchmarks/metrics.py"
        ] = "changed"
    else:
        new["provenance"]["architecture"] = "x86_64"
    assert compare(new, old)["status"] == "not_comparable"


def test_storage_and_availability_changes_are_visible_but_roundoff_is_ignored():
    old, new = report(), report()
    assert compare(new, None)["status"] == "no_baseline"
    new["methods"][0]["quality"]["retrieval"]["10"]["ndcg"] += 1e-9
    assert compare(new, old)["status"] == "unchanged"
    new["methods"][0]["storage"]["model_bytes"] += 1
    assert compare(new, old)["status"] == "changed"
    new["methods"][0]["quality"]["retrieval"]["10"]["ndcg"] = None
    assert len(compare(new, old)["changes"]) == 2


def test_kernel_updates_are_informational_but_libc_and_numeric_versions_matter():
    old, new = report(), report()
    old["provenance"]["platform"] = "Linux-6.17.0-1022-azure-x86_64-with-glibc2.39"
    new["provenance"]["platform"] = "Linux-6.18.0-1023-azure-x86_64-with-glibc2.39"
    assert compare(new, old)["status"] == "unchanged"
    new["provenance"]["quality_environment"] = {
        "system": "Linux",
        "libc": ["glibc", "2.39"],
    }
    assert compare(new, old)["status"] == "unchanged"
    new["provenance"]["quality_environment"]["libc"][1] = "2.40"
    assert compare(new, old)["status"] == "not_comparable"
    new = deepcopy(old)
    new["provenance"]["packages"]["numpy"] = "other"
    assert compare(new, old)["status"] == "not_comparable"


@pytest.mark.parametrize(
    "state", ["unchanged", "changed", "not_comparable", "no_baseline"]
)
def test_cli_writes_report_and_separates_annotations_from_summary(tmp_path, state):
    old, new = report(), report()
    if state == "changed":
        new["methods"][0]["storage"]["code_bytes"] += 1
    elif state == "not_comparable":
        new["provenance"]["config_sha256"] = "other"
    current, baseline, output = (
        tmp_path / f"{n}.json" for n in ("current", "baseline", "comparison")
    )
    current.write_text(json.dumps(new))
    baseline.write_text(json.dumps(old))
    command = [
        sys.executable,
        "-m",
        "benchmarks.compare",
        "--current",
        str(current),
        "--output",
        str(output),
    ]
    if state != "no_baseline":
        command += ["--baseline", str(baseline)]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    assert json.loads(output.read_text())["status"] == state
    assert f"**{state}**" in result.stdout
    assert "::warning" not in result.stdout
    assert ("::warning title=Benchmark comparison::" in result.stderr) == (
        state != "unchanged"
    )
