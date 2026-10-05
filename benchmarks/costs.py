# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Evaluate declared economic scenarios without fetching or inventing prices.

Usage: python -m benchmarks.costs --scenario FILE --output NEW_DIRECTORY
Optional --report/--method binds corpus count and codec artifact storage to an
existing successful quality report. This does not supply serving measurements.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .run import digest, write_json

GB = Decimal(10**9)
MILLION = Decimal(10**6)
SECTIONS = {
    "pricing": {
        "kind",
        "provider",
        "region",
        "hardware",
        "currency",
        "as_of",
        "source",
        "instance_hour",
        "storage_gb_month",
        "transfer_gb",
        "requests_per_thousand",
    },
    "workload": {"embeddings", "monthly_successful_queries"},
    "deployment": {
        "instances",
        "billed_hours_per_instance_month",
        "stored_bytes_per_copy",
        "storage_copies",
        "transferred_bytes_month",
        "requests_month",
        "additional_preparation_runs_month",
    },
    "preparation": {
        "embeddings",
        "training_instance_hours",
        "encoding_instance_hours",
        "build_and_persist_instance_hours",
    },
    "requirements": {"quality_metric", "min_quality", "max_p99_ms", "max_error_rate"},
    "observations": {"quality", "p99_ms", "error_rate", "source"},
}
TEXT = {
    "kind",
    "provider",
    "region",
    "hardware",
    "currency",
    "as_of",
    "source",
    "quality_metric",
}
COUNTS = {
    "embeddings",
    "monthly_successful_queries",
    "instances",
    "storage_copies",
    "stored_bytes_per_copy",
    "transferred_bytes_month",
    "requests_month",
    "additional_preparation_runs_month",
}


def number(value, label: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError(f"{label} must be a nonnegative number or null")
    try:
        result = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError(f"invalid number for {label}") from error
    if not result.is_finite() or result < 0:
        raise ValueError(f"{label} must be finite and nonnegative")
    return result


def validate(scenario: dict) -> None:
    allowed = {"schema_version", "name", "excluded_costs", *SECTIONS}
    if set(scenario) - allowed or scenario.get("schema_version") != 1:
        raise ValueError("unknown scenario field or schema version")
    if not isinstance(scenario.get("name"), str) or not scenario["name"].strip():
        raise ValueError("scenario needs a name")
    excluded = scenario.get("excluded_costs")
    if not isinstance(excluded, list) or any(not isinstance(x, str) for x in excluded):
        raise ValueError("excluded_costs must be an explicit list")
    for section, fields in SECTIONS.items():
        values = scenario.get(section, {})
        if not isinstance(values, dict) or set(values) - fields:
            raise ValueError(f"unknown fields in {section}")
        for key, value in values.items():
            if key in TEXT:
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"{section}.{key} must be nonempty text")
            else:
                n = number(value, f"{section}.{key}")
                if n is not None and key in COUNTS and n != n.to_integral_value():
                    raise ValueError(f"{section}.{key} must be an integer")
                if (
                    n is not None
                    and key in {"embeddings", "instances", "storage_copies"}
                    and n == 0
                ):
                    raise ValueError(f"{section}.{key} must be positive")
                if n is not None and key in {"error_rate", "max_error_rate"} and n > 1:
                    raise ValueError("error rates must be fractions in [0, 1]")
    price = scenario.get("pricing", {})
    for field in (
        "kind",
        "provider",
        "region",
        "hardware",
        "currency",
        "as_of",
        "source",
    ):
        if field not in price:
            raise ValueError(f"pricing.{field} is required")
    if price["kind"] not in {"illustrative", "quoted"}:
        raise ValueError(
            "pricing.kind must be illustrative or quoted; invoiced costs are not supported"
        )
    if (
        len(price["currency"]) != 3
        or not price["currency"].isalpha()
        or not price["currency"].isupper()
    ):
        raise ValueError("currency must be a three-letter uppercase code")
    date.fromisoformat(price["as_of"])


def multiply(*values: Decimal | None) -> Decimal | None:
    # An explicit zero quantity costs zero, even if its unused tariff is unknown.
    if any(v == 0 for v in values):
        return Decimal(0)
    if any(v is None for v in values):
        return None
    result = Decimal(1)
    for value in values:
        assert value is not None
        result *= value
    return result


def total(values) -> Decimal | None:
    values = list(values)
    return None if any(v is None for v in values) else sum(values, Decimal(0))


def amount(
    value: Decimal | None, status: str, reason: str = "missing quantities or tariffs"
) -> dict:
    return {
        "value": format(value, "f") if value is not None else None,
        "status": status if value is not None else "not_evaluated",
        "reason": None if value is not None else reason,
    }


def check_requirements(scenario: dict) -> dict:
    req, obs = scenario.get("requirements", {}), scenario.get("observations", {})
    checks = {}
    for label, bound, greater in [
        ("quality", "min_quality", True),
        ("p99_ms", "max_p99_ms", False),
        ("error_rate", "max_error_rate", False),
    ]:
        limit, value = number(req.get(bound), bound), number(obs.get(label), label)
        verified = limit is not None and value is not None and bool(obs.get("source"))
        if label == "quality":
            verified = verified and bool(req.get("quality_metric"))
        if not verified:
            checks[label] = "not_verified"
        else:
            assert value is not None and limit is not None
            checks[label] = (
                "passed"
                if (value >= limit if greater else value <= limit)
                else "failed"
            )
    status = (
        "failed"
        if "failed" in checks.values()
        else (
            "passed" if all(v == "passed" for v in checks.values()) else "not_verified"
        )
    )
    return {
        "status": status,
        "checks": checks,
        "scope": "caller-supplied observations; not an independent capacity or SLO verification",
    }


def evaluate(scenario: dict) -> dict:
    validate(scenario)

    def get(section, key):
        return number(scenario.get(section, {}).get(key), f"{section}.{key}")

    def rate(key):
        return get("pricing", key)

    stage_costs = {
        name: multiply(get("preparation", name), rate("instance_hour"))
        for name in (
            "training_instance_hours",
            "encoding_instance_hours",
            "build_and_persist_instance_hours",
        )
    }
    preparation = total(stage_costs.values())
    stored = multiply(
        get("deployment", "stored_bytes_per_copy"),
        get("deployment", "storage_copies"),
        Decimal(1) / GB,
    )
    components = {
        "compute": multiply(
            get("deployment", "instances"),
            get("deployment", "billed_hours_per_instance_month"),
            rate("instance_hour"),
        ),
        "storage": multiply(stored, rate("storage_gb_month")),
        "transfer": multiply(
            get("deployment", "transferred_bytes_month"),
            Decimal(1) / GB,
            rate("transfer_gb"),
        ),
        "requests": multiply(
            get("deployment", "requests_month"),
            Decimal("0.001"),
            rate("requests_per_thousand"),
        ),
        "additional_preparation": multiply(
            get("deployment", "additional_preparation_runs_month"), preparation
        ),
    }
    monthly = total(components.values())
    corpus = get("workload", "embeddings")
    queries = get("workload", "monthly_successful_queries")
    prepared = get("preparation", "embeddings")
    status = (
        "illustrative" if scenario["pricing"]["kind"] == "illustrative" else "estimated"
    )
    return {
        "schema_version": 1,
        "suite": "cost_model",
        "status": "complete",
        "currency": scenario["pricing"]["currency"],
        "scenario": scenario,
        "requirements_check": check_requirements(scenario),
        "monthly_components": {k: amount(v, status) for k, v in components.items()},
        "preparation_stages": {k: amount(v, status) for k, v in stage_costs.items()},
        "metrics": {
            "monthly_scenario_cost": amount(monthly, status),
            "monthly_cost_per_million_embeddings": amount(
                monthly * MILLION / corpus if monthly is not None and corpus else None,
                status,
            ),
            "cost_per_million_successful_queries": amount(
                (
                    monthly * MILLION / queries
                    if monthly is not None and queries
                    else None
                ),
                status,
                "missing monthly total or positive successful query count",
            ),
            "preparation_run_cost": amount(preparation, status),
            "preparation_cost_per_million_embeddings": amount(
                (
                    preparation * MILLION / prepared
                    if preparation is not None and prepared
                    else None
                ),
                status,
            ),
        },
        "limitations": [
            "linear effective tariffs, no automatic price lookup or billing-tier calculation",
            "cost per query allocates the same monthly total; do not add these metrics together",
            "RAM is included in the compute tariff, not charged again",
            "additional preparation must be billed outside the serving allocation",
            "no automatic machine sizing, capacity extrapolation or savings claim",
        ],
    }


def bind_artifact(scenario: dict, report: dict, method_id: str) -> tuple[dict, dict]:
    if (
        report.get("schema_version") not in (1, 2)
        or report.get("status") != "complete"
        or report.get("suite") != "codec_quality"
    ):
        raise ValueError("expected a completed version 1 codec_quality report")
    matches = [m for m in report["methods"] if m["id"] == method_id]
    if len(matches) != 1:
        raise ValueError("method ID must identify exactly one report entry")
    method = matches[0]
    corpus_rows = report["dataset"]["arrays"]["corpus"]["shape"][0]
    artifact_bytes = method["artifact"]["file_bytes"]
    out = deepcopy(scenario)
    for section, key, value in [
        ("workload", "embeddings", corpus_rows),
        ("deployment", "stored_bytes_per_copy", artifact_bytes),
    ]:
        old = out.setdefault(section, {}).get(key)
        if old is not None and number(old, key) != value:
            raise ValueError(
                f"scenario {section}.{key} conflicts with the benchmark report"
            )
        out[section][key] = value
    return out, {
        "method": method_id,
        "storage_basis": "NPZ codec artifact; not a searchable index",
        "artifact": method["artifact"],
        "scoring_profile": report["scoring_profile"],
        "dataset_kind": report["dataset"]["kind"],
        "scope": "only corpus size and storage bytes are bound; serving observations remain unverified",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--method")
    args = parser.parse_args()
    if bool(args.report) != bool(args.method):
        parser.error("--report and --method must be supplied together")
    scenario = json.loads(args.scenario.read_text())
    input_hash = digest(args.scenario)
    evidence = None
    if args.report:
        scenario, evidence = bind_artifact(
            scenario, json.loads(args.report.read_text()), args.method
        )
        evidence["report_sha256"] = digest(args.report)
    result = evaluate(scenario)
    result["provenance"] = {
        "utc": datetime.now(UTC).isoformat(),
        "scenario_sha256": input_hash,
        "evaluator_sha256": digest(Path(__file__)),
        "benchmark_evidence": evidence,
    }
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "scenario.json", scenario)
    write_json(args.output / "report.json", result)
    print(args.output / "report.json")


if __name__ == "__main__":
    main()
