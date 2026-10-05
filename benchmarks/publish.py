# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Freeze verified quality reports and generate the public explorer."""

import argparse
import hashlib
import json
from html import escape
from pathlib import Path

from .metrics import paired_ndcg_interval
from .render import render
from .run import ROOT, digest, write_json

REPORTS = ROOT / "docs/assets/benchmarks"
PAGE = ROOT / "docs/guides/benchmark-results.md"


def compact(report: dict, evidence: dict, config: dict, report_sha256: str) -> dict:
    render(report)  # Validate the report contract before publishing any numbers.
    if report["provenance"].get("working_tree_dirty") is not False:
        raise ValueError("publication requires a clean source checkout")
    if not report["dataset"].get("preparation"):
        raise ValueError("publication requires dataset and model provenance")
    if (
        evidence.get("status") != "verified"
        or evidence.get("report_sha256") != report_sha256
    ):
        raise ValueError("verification does not match this report")
    if (
        hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        != report["provenance"]["config_sha256"]
    ):
        raise ValueError("configuration does not match this report")

    def prune(value):
        if isinstance(value, dict):
            return {
                k: prune(v)
                for k, v in value.items()
                if k not in ("per_query", "path", "module", "native_library")
            }
        if isinstance(value, list):
            return [prune(v) for v in value]
        return value

    result = prune(report)
    # The source commit and validated source hashes identify the evaluated SDK.
    result["provenance"]["packages"].pop("semq", None)
    pairs = dict(report.get("publication", {}).get("paired_comparisons", {}))
    methods = {m["id"]: m for m in report["methods"]}
    for left, right in (
        ("quant4", "fp32"),
        ("quant2", "turboquant_mse2"),
        ("quant4", "sq4"),
        ("quant4", "turboquant_mse4"),
        ("quant2", "pq2"),
        ("quant2", "opq2"),
    ):
        a, b = methods.get(left, {}).get("direction_scoring", {}), methods.get(
            right, {}
        ).get("direction_scoring", {})
        if "per_query" in a and "per_query" in b and config.get("uncertainty"):
            settings = config["uncertainty"]
            pairs[left + " vs " + right] = {
                k: paired_ndcg_interval(
                    a["per_query"][k]["ndcg"],
                    b["per_query"][k]["ndcg"],
                    samples=settings["bootstrap_samples"],
                    confidence=settings["confidence"],
                    seed=settings["seed"],
                )
                for k in a["per_query"]
            }
    result["publication"] = {
        "schema_version": 1,
        "source_report_sha256": report_sha256,
        "verification": evidence,
        "config": config,
        "paired_comparisons": pairs,
        "omitted": "per-query arrays, machine-local paths and installed SEMQ distribution metadata; encoded artifacts are not distributed",
    }
    return result


def cell(value: object) -> str:
    """Keep the precision used in generated prose and tests."""
    if isinstance(value, float):
        if value and abs(value) < 0.00005:
            return f"{value:.8f}"
        return f"{value:.4f}"
    return str(value).replace("|", "\\|").replace("\n", " ")


INTRO = """# Retrieval quality in detail

Explore frozen evaluations on SciFact and FiQA. Select a dataset, model and scoring profile.
Each point represents one measured format at its **total bits per dimension**,
including stored scales, codebooks and rotations. The source report for the
selected run contains every exact value and method configuration.

**nDCG@10** measures relevance against available judgments; **Overlap@10**
measures preservation of FP32 neighbors. The Δ nDCG interval is a paired
query-bootstrap interval against FP32. An interval crossing zero does not
establish equivalence; these intervals exclude dataset, model and training-seed
variation and have no multiple-comparison correction.

The scoring profiles answer different questions. **Normalized direction** uses
cosine on decoded rows, **raw reconstruction** uses inner products without
renormalization, and **native estimators** use a backend's own scoring. Do not
combine their rankings. No method uses rescoring.

"""


def observations(reports: list[tuple[str, dict]]) -> list[str]:
    lines = ["## What these runs show", ""]
    deltas = []
    for _, report in reports:
        method = next((m for m in report["methods"] if m["id"] == "semq_quant2"), None)
        if method and method["direction_scoring"]["status"] == "measured":
            deltas.append(
                method["direction_scoring"]["quality"]["retrieval"]["10"][
                    "ndcg_delta_interval"
                ]["mean_delta"]
            )
    if deltas:
        lines.append(
            f"- **Sensitivity varies with the inputs:** 2-bit SEMQ quant's mean "
            f"nDCG difference from FP32 ranges from {cell(min(deltas))} to "
            f"{cell(max(deltas))}. These runs do not isolate a cause."
        )
    return lines + [""]


def reference_checks(reports: list[tuple[str, dict]]) -> list[str]:
    references = json.loads(
        (ROOT / "benchmarks/configs/published-references.json").read_text()
    )["models"]
    lines = [
        "## FP32 baseline check",
        "",
        "This sanity check compares FP32 nDCG@10 with pinned model-card values. "
        "The model cards do not pin dataset revisions, so a difference is not "
        "evidence of a reproduction failure.",
        "",
        '<div class="semq-evidence-stats">',
    ]
    for _, report in reports:
        prep = report["dataset"]["preparation"]
        reference = references.get(prep["model"]["repo"], {})
        value = reference.get("ndcg_at_10_points", {}).get(prep["dataset"])
        if value is None or reference["model_revision"] != prep["model"]["revision"]:
            continue
        fp32 = next(m for m in report["methods"] if m["method"]["name"] == "fp32")
        measured = fp32["direction_scoring"]["quality"]["retrieval"]["10"]["ndcg"] * 100
        label = f"{prep['dataset']} · {prep['model']['repo'].split('/')[-1]}"
        lines.append(
            f"<div><strong>{measured:.2f} / {value:.2f}</strong>"
            f"<span>{escape(label)} · this run / model card · "
            f'<a href="{escape(reference["source_url"], quote=True)}">source</a></span></div>'
        )
    return lines + ["</div>", ""]


def page(reports: list[tuple[str, dict]]) -> str:
    if not reports:
        raise ValueError("no published reports found")
    files: list[str] = []
    downloads: list[str] = []
    for filename, report in reports:
        publication = report["publication"]
        if publication["schema_version"] != 1:
            raise ValueError("unsupported publication schema")
        compact(
            report,
            publication["verification"],
            publication["config"],
            publication["source_report_sha256"],
        )
        files.append(filename)
        prep = report["dataset"]["preparation"]
        label = f"{prep['dataset']} · {prep['model']['repo'].split('/')[-1]}"
        downloads.append(f"[{label}](../assets/benchmarks/{filename})")
    encoded_files = escape(json.dumps(files), quote=True)
    lines = [
        INTRO,
        '<div class="semq-detail-explorer" data-semq-detail-explorer '
        f'data-files="{encoded_files}">',
        '  <p role="status">Loading verified reports…</p>',
        "</div>",
        "",
        "Exact measurements and provenance in the frozen reports:",
        "",
        " · ".join(downloads),
        "",
        *observations(reports),
        *reference_checks(reports),
        "## Scope and verification",
        "",
        "FP32 per-query nDCG was checked against `pytrec-eval-terrier` on identical "
        "rankings in both common profiles (absolute tolerance `1e-12`). This "
        "checks the shared metric and stored FP32 values, not each codec or the "
        "tie policy. Compact reports retain the source revision, input hashes, "
        "verification results, storage breakdowns and paired comparisons.",
        "",
        "The [benchmark overview](../benchmarks/index.md) covers speed, scale, "
        "rebuild variation and cross-platform identity. The "
        "[reproduction guide](benchmark-datasets.md) describes the datasets, "
        "preprocessing and evaluation commands.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--verification", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    exporting = any((args.report, args.verification, args.config, args.output))
    if exporting:
        if args.check or not all(
            (args.report, args.verification, args.config, args.output)
        ):
            parser.error(
                "export requires --report, --verification, --config and --output, without --check"
            )
        value = compact(
            json.loads(args.report.read_text()),
            json.loads(args.verification.read_text()),
            json.loads(args.config.read_text()),
            digest(args.report),
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_json(args.output, value)
        return
    reports = [
        (p.name, json.loads(p.read_text())) for p in sorted(REPORTS.glob("*.json"))
    ]
    rendered = page(reports)
    if args.check:
        if not PAGE.exists() or PAGE.read_text(encoding="utf-8") != rendered:
            raise SystemExit(f"{PAGE.name} is stale; run python -m benchmarks.publish")
    else:
        PAGE.parent.mkdir(parents=True, exist_ok=True)
        PAGE.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
