# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Economics must retain missing evidence, allocation boundaries and provenance."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from benchmarks.costs import bind_artifact, evaluate

CONFIGS = Path(__file__).resolve().parents[1] / "configs"


def scenario():
    return json.loads((CONFIGS / "cost-illustrative.json").read_text())


def value(report, key):
    return Decimal(report["metrics"][key]["value"])


def test_explicit_monthly_and_preparation_arithmetic():
    report = evaluate(scenario())
    # 2*720*.50 + 2000*.02 + 100*.05 + 1000*.004 + 4*(1+2+3)*.50
    assert value(report, "monthly_scenario_cost") == Decimal("781")
    assert value(report, "monthly_cost_per_million_embeddings") == Decimal("781")
    assert value(report, "cost_per_million_successful_queries") == Decimal("78.1")
    assert value(report, "preparation_run_cost") == Decimal("3")
    assert value(report, "preparation_cost_per_million_embeddings") == Decimal("3")
    assert report["metrics"]["monthly_scenario_cost"]["status"] == "illustrative"
    assert report["requirements_check"]["status"] == "not_verified"


def test_idle_service_still_costs_money_but_query_unit_cost_is_undefined():
    data = scenario()
    data["workload"]["monthly_successful_queries"] = 0
    report = evaluate(data)
    assert value(report, "monthly_scenario_cost") == Decimal("781")
    assert report["metrics"]["cost_per_million_successful_queries"]["value"] is None


def test_missing_tariff_does_not_become_zero_or_a_partial_total():
    data = scenario()
    del data["pricing"]["transfer_gb"]
    report = evaluate(data)
    assert report["metrics"]["monthly_scenario_cost"]["status"] == "not_evaluated"
    assert Decimal(report["monthly_components"]["storage"]["value"]) == Decimal("40")


def test_no_additional_preparation_does_not_charge_a_second_time():
    data = scenario()
    data["deployment"]["additional_preparation_runs_month"] = 0
    del data["preparation"]
    report = evaluate(data)
    assert value(report, "monthly_scenario_cost") == Decimal("769")
    assert report["metrics"]["preparation_run_cost"]["value"] is None


def test_known_zero_transfer_needs_no_tariff():
    data = scenario()
    data["deployment"]["transferred_bytes_month"] = 0
    del data["pricing"]["transfer_gb"]
    assert value(evaluate(data), "monthly_scenario_cost") == Decimal("776")


def test_requirement_failure_does_not_hide_cost_or_qualify_the_scenario():
    data = scenario()
    data["observations"] = {
        "quality": 0.59,
        "p99_ms": 10,
        "error_rate": 0,
        "source": "example observations",
    }
    report = evaluate(data)
    assert report["requirements_check"]["status"] == "failed"
    assert report["requirements_check"]["checks"]["quality"] == "failed"
    assert value(report, "monthly_scenario_cost") == Decimal("781")
    data["observations"]["quality"] = 0.60
    assert evaluate(data)["requirements_check"]["status"] == "passed"
    del data["observations"]["source"]
    assert evaluate(data)["requirements_check"]["status"] == "not_verified"


def test_quoted_tariff_is_still_an_estimate_not_observed_billing():
    data = scenario()
    data["pricing"]["kind"] = "quoted"
    report = evaluate(data)
    assert report["metrics"]["monthly_scenario_cost"]["status"] == "estimated"


@pytest.mark.parametrize("bad", [-1, True, "NaN", "Infinity", "not-a-price"])
def test_invalid_money_is_rejected(bad):
    data = scenario()
    data["pricing"]["instance_hour"] = bad
    with pytest.raises(ValueError):
        evaluate(data)


def test_unknown_keys_and_fractional_instances_are_rejected():
    data = scenario()
    data["deployment"]["instances"] = 1.5
    with pytest.raises(ValueError):
        evaluate(data)
    data = scenario()
    data["pricing"]["extra_ram_charge"] = 1
    with pytest.raises(ValueError):
        evaluate(data)


def benchmark_report():
    return {
        "schema_version": 1,
        "status": "complete",
        "suite": "codec_quality",
        "dataset": {
            "kind": "synthetic_smoke",
            "arrays": {"corpus": {"shape": [100, 32]}},
        },
        "scoring_profile": "original_query_ip_f64_no_renormalization",
        "methods": [
            {
                "id": "quant2",
                "artifact": {
                    "file": "quant2.npz",
                    "file_bytes": 1000,
                    "sha256": "example",
                },
            }
        ],
    }


def test_artifact_binding_cannot_become_a_serving_estimate():
    data = json.loads((CONFIGS / "cost-storage-illustrative.json").read_text())
    resolved, evidence = bind_artifact(data, benchmark_report(), "quant2")
    report = evaluate(resolved)
    assert Decimal(report["monthly_components"]["storage"]["value"]) == Decimal(
        "0.00000002"
    )
    assert report["metrics"]["monthly_scenario_cost"]["value"] is None
    assert report["metrics"]["cost_per_million_successful_queries"]["value"] is None
    assert evidence["dataset_kind"] == "synthetic_smoke"
    assert "not a searchable index" in evidence["storage_basis"]
    assert "stored_bytes_per_copy" not in data["deployment"]


def test_conflicting_report_size_and_failed_report_are_rejected():
    with pytest.raises(ValueError, match="conflicts"):
        bind_artifact(scenario(), benchmark_report(), "quant2")
    report = benchmark_report()
    report["status"] = "failed"
    with pytest.raises(ValueError, match="completed"):
        bind_artifact(scenario(), report, "quant2")


def test_cli_preserves_input_hash_and_refuses_overwrite(tmp_path, monkeypatch):
    import sys

    from benchmarks.costs import main
    from benchmarks.run import digest

    source = tmp_path / "scenario.json"
    source.write_text(json.dumps(scenario()))
    output = tmp_path / "run"
    monkeypatch.setattr(
        sys, "argv", ["costs", "--scenario", str(source), "--output", str(output)]
    )
    main()
    report = output / "report.json"
    original = report.read_bytes()
    assert json.loads(original)["provenance"]["scenario_sha256"] == digest(source)
    with pytest.raises(FileExistsError):
        main()
    assert report.read_bytes() == original


@pytest.mark.parametrize("convert", [int, float, str])
def test_artifact_binding_accepts_matching_numeric_scenario_fields(convert):
    data = json.loads((CONFIGS / "cost-storage-illustrative.json").read_text())
    report = benchmark_report()
    rows = report["dataset"]["arrays"]["corpus"]["shape"][0]
    size = report["methods"][0]["artifact"]["file_bytes"]
    data.setdefault("workload", {})["embeddings"] = convert(rows)
    data["deployment"]["stored_bytes_per_copy"] = convert(size)
    resolved, _ = bind_artifact(data, report, "quant2")
    assert resolved["workload"]["embeddings"] == rows
    assert resolved["deployment"]["stored_bytes_per_copy"] == size
