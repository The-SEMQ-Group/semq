# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Render a completed quality report as separate, readable Markdown profiles."""

import argparse
import json
from pathlib import Path


def cell(value: object) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value).replace("|", "\\|").replace("\n", " ")


def render(report: dict) -> str:
    if (
        report.get("schema_version") != 2
        or report.get("suite") != "codec_quality"
        or report.get("status") != "complete"
    ):
        raise ValueError(
            "expected a complete codec_quality report with schema_version 2"
        )
    lines = ["# Codec quality results", ""]
    dataset = report["dataset"]
    for name in ("corpus", "queries", "fit"):
        array = dataset["arrays"][name]
        lines.append(f"{name}: {cell(array['shape'])}; SHA-256: `{array['sha256']}`.\n")
    preparation = dataset.get("preparation", {})
    if preparation:
        model = preparation["model"]
        lines.append(
            f"Dataset: {cell(preparation['dataset'])}; model: {cell(model['repo'])} @ `{model['revision']}`.\n"
        )
    provenance = report.get("provenance", {})
    lines.append(
        f"Revision: {cell(provenance.get('git_commit'))}; "
        f"dirty tree: {cell(provenance.get('working_tree_dirty'))}.\n"
    )
    if report["dataset"]["kind"] == "synthetic_smoke":
        lines += [
            "Synthetic smoke: infrastructure validation, not semantic-quality evidence.",
            "",
        ]
    lines += [
        "Code and model storage excludes the NPZ container and SDK index overhead.",
        "CANON's audit role is distinct from retrieval-oriented representations.",
        "",
        "| Method | Role | Code bits/dim | Model bits/dim | Total bits/dim |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for method in report["methods"]:
        storage = method["storage"]
        values = [method["id"], method["role"]] + [
            storage[key]
            for key in (
                "code_bits_per_dimension",
                "model_bits_per_dimension",
                "effective_bits_per_dimension",
            )
        ]
        lines.append("| " + " | ".join(map(cell, values)) + " |")
    profiles = (
        ("Raw reconstruction", "quality"),
        ("Normalized direction", "direction_scoring"),
        ("Native estimators", "method_scoring"),
    )
    for title, key in profiles:
        lines += [
            "",
            f"## {title}",
            "",
            "| Method | Profile / status | k | Overlap@k | nDCG@k | Δ nDCG interval | Score RMSE | Reconstruction error |",
            "| --- | --- | ---: | ---: | ---: | --- | ---: | --- |",
        ]
        for method in report["methods"]:
            result = method[key]
            if result["status"] != "measured":
                status = result["status"]
                if result.get("reason"):
                    status += ": " + result["reason"]
                lines.append(
                    f"| {cell(method['id'])} | {cell(status)} | — | — | — | — | — | — |"
                )
                continue
            quality = result if key == "quality" else result["quality"]
            profile = (
                report["scoring_profile"] if key == "quality" else result["profile"]
            )
            error = "—"
            if key == "quality":
                error = "NSE: " + cell(quality["normalized_squared_error"])
            elif key == "direction_scoring":
                error = "Unit-coordinate MSE: " + cell(
                    quality["direction_coordinate_mse"]
                )
            for k, metrics in quality["retrieval"].items():
                ndcg = (
                    metrics["ndcg"]
                    if metrics["ndcg_status"] == "measured"
                    else metrics["ndcg_status"]
                )
                interval = metrics.get("ndcg_delta_interval", {})
                delta_interval = (
                    f"{interval['confidence']:.0%}: [{cell(interval['lower'])}, {cell(interval['upper'])}]"
                    if interval.get("status") == "measured"
                    else "unavailable"
                )
                values = [
                    method["id"],
                    profile,
                    k,
                    metrics["overlap"],
                    ndcg,
                    delta_interval,
                    quality["score_rmse"],
                    error,
                ]
                lines.append("| " + " | ".join(map(cell, values)) + " |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    print(render(json.loads(args.report.read_text())), end="")


if __name__ == "__main__":
    main()
