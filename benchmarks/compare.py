# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Compare compatible quality reports; surface changes without a timing gate."""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from .run import write_json

PROTOCOL_SOURCES = ("run.py", "metrics.py", "relevance.py", "faiss_codecs.py")


def runtime_environment(provenance: dict) -> dict:
    if "quality_environment" in provenance:
        return provenance["quality_environment"]
    description = provenance["platform"]
    if description.startswith("Linux-"):
        match = re.search(r"with-(glibc|musl)([\d.]+)$", description)
        if match:
            return {"system": "Linux", "libc": list(match.groups())}
    # Preserve unknown environments rather than assuming they are equivalent.
    return {"platform": description}


def identity(report: dict) -> dict:
    p = report["provenance"]
    sources = p["benchmark_source_sha256"]
    return {
        "schema": report["schema_version"],
        "suite": report["suite"],
        "scoring_profile": report["scoring_profile"],
        "config": p["config_sha256"],
        "arrays": report["dataset"]["arrays"],
        "model": report["dataset"].get("preparation", {}).get("model"),
        "protocol": {name: sources[f"benchmarks/{name}"] for name in PROTOCOL_SOURCES},
        "environment": {
            "architecture": p["architecture"],
            "runtime": runtime_environment(p),
            "python": ".".join(p["python"].split(".")[:2]),
            "packages": {k: v for k, v in p["packages"].items() if k != "semq"},
        },
        "methods": [m["method"] for m in report["methods"]],
    }


def observations(report: dict) -> dict:
    values: dict[str, tuple[Any, float | None]] = {}
    for method in report["methods"]:
        mid = method["id"]
        for key in ("code_bytes", "model_bytes"):
            values[f"{mid}.storage.{key}"] = (method["storage"][key], 0)
        for profile in ("quality", "direction_scoring", "method_scoring"):
            section = method[profile]
            prefix = f"{mid}.{profile}"
            values[prefix + ".status"] = (section["status"], None)
            if section["status"] != "measured":
                continue
            values[prefix + ".profile"] = (
                section.get("profile", report["scoring_profile"]),
                None,
            )
            quality = section if profile == "quality" else section["quality"]
            for key in (
                "score_rmse",
                "coordinate_mse",
                "normalized_squared_error",
                "direction_coordinate_mse",
            ):
                if key in quality:
                    values[prefix + "." + key] = (quality[key], 1e-8)
            for k, row in quality["retrieval"].items():
                for key in ("ndcg", "overlap"):
                    values[f"{prefix}.{key}@{k}"] = (row[key], 1e-4)
    return values


def compare(current: dict, baseline: dict | None) -> dict:
    if current.get("status") != "complete":
        raise ValueError("current report is incomplete")
    if baseline is None:
        return {"status": "no_baseline", "reason": "no retained successful main report"}
    if baseline.get("status") != "complete":
        return {"status": "not_comparable", "reasons": ["baseline incomplete"]}
    a, b = identity(current), identity(baseline)
    differences = [key for key in a if a[key] != b[key]]
    if differences:
        return {"status": "not_comparable", "reasons": differences}
    now, before = observations(current), observations(baseline)
    changes = []
    for key in sorted(now.keys() | before.keys()):
        value, tolerance = now.get(key, (None, None))
        prior, _ = before.get(key, (None, None))
        if value == prior:
            continue
        delta = None
        if isinstance(value, (int, float)) and isinstance(prior, (int, float)):
            delta = value - prior
            if tolerance is not None and abs(delta) <= tolerance:
                continue
        changes.append({"metric": key, "before": prior, "after": value, "delta": delta})
    return {
        "status": "changed" if changes else "unchanged",
        "changes": changes,
        "baseline_commit": baseline["provenance"]["git_commit"],
        "current_commit": current["provenance"]["git_commit"],
        "policy": "absolute tolerances: quality 0.0001; errors 1e-8; storage bytes 0; informational only",
    }


def markdown(result: dict) -> str:
    lines = [
        "## Comparison with previous successful main evaluation",
        "",
        f"Status: **{result['status']}**.",
        "",
    ]
    if "reasons" in result:
        lines.append("Incompatible fields: " + ", ".join(result["reasons"]) + ".")
    if "reason" in result:
        lines.append(result["reason"])
    if "policy" in result:
        lines += [
            result["policy"],
            "",
            f"Baseline: `{result['baseline_commit']}`; current: `{result['current_commit']}`.",
        ]
    if result.get("changes"):
        lines += [
            "",
            "| Metric | Before | After | Delta |",
            "| --- | ---: | ---: | ---: |",
        ]
        for row in result["changes"]:
            lines.append(
                "| "
                + " | ".join(
                    str(row[k]) for k in ("metric", "before", "after", "delta")
                )
                + " |"
            )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    current = json.loads(args.current.read_text())
    baseline = json.loads(args.baseline.read_text()) if args.baseline else None
    result = compare(current, baseline)
    write_json(args.output, result)
    print(markdown(result))
    if result["status"] in ("changed", "not_comparable", "no_baseline"):
        print(
            f"::warning title=Benchmark comparison::{result['status']}; inspect the benchmark job summary",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
