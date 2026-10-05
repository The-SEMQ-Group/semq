# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Collect retrieval quality retained per storage format into one result file.

Run ``python -m benchmarks.run`` once per model and dataset with the
``quality-<model>.json`` configs, then pass the run directories here:

    python -m benchmarks.quality RUN_DIR [RUN_DIR ...]

For every model x dataset x method it records nDCG@10, the percentage of the
FP32 nDCG@10 retained, the top-10 overlap with FP32, the effective bits per
dimension (codes plus every scale and model byte) and the runner's paired
bootstrap interval of the per-query nDCG@10 difference from FP32. Scores are
cosine between the original query and the decoded corpus row (no rescoring);
formats without a faithful decoder use their native estimator, and each row
names the profile used. ``--check`` rebuilds ``results`` from the same run
directories and fails if the committed file differs.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .run import ROOT

OUTPUT = ROOT / "docs/assets/benchmarks/summary/quality.json"
SCHEMA = "semq-bench/quality/1"
K = "10"
MODELS = ("e5_small", "arctic_m", "mxbai_large")
DATASETS = ("scifact", "fiqa")
INPUT_SUFFIX = {
    "e5_small": "e5",
    "bge_small": "bge",
    "arctic_m": "arctic",
    "mxbai_large": "mxbai",
}
MATRYOSHKA_ONLY = ("mrl256", "mrl256_int8")
PROFILES = {
    "direction_scoring": "cosine(original query, decoded row), float64",
    "method_scoring": "method's own exhaustive estimator, float32 query",
}


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def hardware() -> dict[str, Any]:
    return {
        "machine": "Apple M4 Pro",
        "os": platform.platform(),
        "arch": platform.machine(),
        "cpu_threads": os.cpu_count(),
        "gpu": "Apple M4 Pro (MPS)",
    }


def input_name(model: str, dataset: str) -> str:
    return f"{dataset}-{INPUT_SUFFIX[model]}"


def model_key(beir: dict, repo: str, revision: str) -> str:
    for key, spec in beir["models"].items():
        if spec["repo"] == repo and spec["revision"] == revision:
            return key
    raise ValueError(f"model {repo}@{revision} is not in beir-datasets.json")


def frozen_entry(frozen: dict, name: str, sha256: str) -> dict[str, Any]:
    """Locate an input's embeddings file in the released or pending registry."""
    for section, release in (
        ("inputs", frozen["release"]),
        ("pending", frozen.get("pending", {}).get("release")),
    ):
        entries = frozen.get(section, {})
        if section == "pending":
            entries = entries.get("inputs", {})
        for spec in entries.get(name, {}).get("files", []):
            if spec["file"] == "embeddings.npz":
                if spec["sha256"] != sha256:
                    raise ValueError(f"{name} differs from its registered sha256")
                return {"release": release, "asset": spec["asset"], "state": section}
    raise ValueError(f"{name} is not registered in frozen-inputs.json")


def score_section(method: dict) -> tuple[str, dict]:
    for key in ("direction_scoring", "method_scoring"):
        section = method[key]
        if section.get("status") == "measured":
            return key, section["quality"]["retrieval"][K]
    raise ValueError(f"{method['id']} has no measured ranking")


def method_row(method: dict, fp32_ndcg: float) -> dict[str, Any]:
    profile, metric = score_section(method)
    interval = metric["ndcg_delta_interval"]
    storage = method["storage"]
    ndcg = metric["ndcg"]
    return {
        "status": "measured",
        "ndcg10": ndcg,
        "ndcg10_retained_pct": 100 * ndcg / fp32_ndcg,
        "overlap10": 100 * metric["overlap"],
        "bits_per_dim": storage["effective_bits_per_dimension"],
        "code_bits_per_dim": storage["code_bits_per_dimension"],
        "model_bits_per_dim": storage["model_bits_per_dimension"],
        "ndcg10_delta_ci": {
            key: interval[key]
            for key in (
                "confidence",
                "eligible_queries",
                "lower",
                "mean_delta",
                "method",
                "samples",
                "upper",
            )
        },
        "scoring": profile,
    }


def run_command(model: str, dataset: str) -> str:
    return (
        f"python -m benchmarks.run"
        f" --config benchmarks/configs/quality-{INPUT_SUFFIX[model]}.json"
        f" --data ~/.cache/semq-benchmarks/{input_name(model, dataset)}/embeddings.npz"
        " --output RUN_DIR"
    )


def collect(
    reports: list[dict],
    beir: dict,
    frozen: dict,
    not_run: dict[str, str] | None = None,
    models: tuple[str, ...] = MODELS,
    datasets: tuple[str, ...] = DATASETS,
) -> tuple[dict, dict]:
    """Return (inputs, results) for the result envelope; pure function of reports."""
    not_run = not_run or {}
    by_cell: dict[tuple[str, str], dict] = {}
    for report in reports:
        prep = report["dataset"]["preparation"]
        key = (
            model_key(beir, prep["model"]["repo"], prep["model"]["revision"]),
            prep["dataset"],
        )
        if key in by_cell:
            raise ValueError(f"two reports for {key}")
        by_cell[key] = report
    method_ids: dict[str, dict] = {}
    for report in reports:
        for method in report["methods"]:
            method_ids.setdefault(method["id"], method["method"])
    inputs: dict[str, dict] = {}
    table: dict[str, dict] = {}
    for model in models:
        spec = beir["models"][model]
        table[model] = {}
        for dataset in datasets:
            cell = by_cell.pop((model, dataset), None)
            if cell is None:
                table[model][dataset] = {
                    "status": "not_run",
                    "reason": not_run.get(
                        f"{model}/{dataset}", "no run report supplied"
                    ),
                    "command": run_command(model, dataset),
                }
                continue
            name = input_name(model, dataset)
            sha256 = cell["dataset"]["sha256"]
            registry = frozen_entry(frozen, name, sha256)
            prep = cell["dataset"]["preparation"]
            inputs[name] = {
                "sha256": sha256,
                "source": (
                    f"release {registry['release']} asset {registry['asset']}"
                    f" ({'uploaded' if registry['state'] == 'inputs' else 'pending upload'});"
                    f" {prep['sources']['repo']}@{prep['sources']['revision']},"
                    f" {spec['repo']}@{spec['revision']}"
                ),
            }
            methods = {m["id"]: m for m in cell["methods"]}
            fp32 = methods["fp32"]["direction_scoring"]["quality"]["retrieval"][K]
            fp32_ndcg = fp32["ndcg"]
            if not fp32_ndcg:
                raise ValueError(f"{name} has no measured FP32 nDCG@10")
            rows: dict[str, Any] = {}
            for method_id in method_ids:
                if method_id in methods:
                    rows[method_id] = method_row(methods[method_id], fp32_ndcg)
                elif method_id in MATRYOSHKA_ONLY and not spec.get("matryoshka"):
                    rows[method_id] = {
                        "status": "not_applicable",
                        "reason": "model is not trained with Matryoshka representation learning",
                    }
                else:
                    raise ValueError(f"{name} report lacks method {method_id}")
            arrays = cell["dataset"]["arrays"]
            table[model][dataset] = {
                "status": "measured",
                "input": name,
                "corpus_rows": arrays["corpus"]["shape"][0],
                "queries": arrays["queries"]["shape"][0],
                "fp32_ndcg10": fp32_ndcg,
                "run": {
                    "config_sha256": cell["provenance"]["config_sha256"],
                    "git_commit": cell["provenance"]["git_commit"],
                    "native_sha256": cell["provenance"]
                    .get("semq", {})
                    .get("native_sha256"),
                },
                "methods": rows,
            }
    if by_cell:
        raise ValueError(f"reports outside the model x dataset grid: {sorted(by_cell)}")
    results = {
        "k": int(K),
        "scoring_profiles": PROFILES,
        "rescoring": "none",
        "reference": "fp32: exact float64 cosine of the original float32 embeddings",
        "methods": method_ids,
        "models": {
            model: {
                key: beir["models"][model][key]
                for key in ("repo", "revision", "dimension", "query_prefix")
            }
            | {
                "document_prefix": beir["models"][model]["document_prefix"],
                "matryoshka": bool(beir["models"][model].get("matryoshka")),
            }
            for model in models
        },
        "datasets": {
            dataset: {
                key: beir["datasets"][dataset][key]
                for key in (
                    "repo",
                    "revision",
                    "qrels_repo",
                    "qrels_revision",
                    "corpus_rows",
                    "test_queries",
                )
            }
            for dataset in datasets
        },
        "table": table,
    }
    return inputs, results


def dumps(value: dict) -> str:
    return json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"


def load(paths: list[Path]) -> list[dict]:
    reports = []
    for path in paths:
        report = json.loads((path / "report.json").read_text())
        if report.get("status") != "complete":
            raise ValueError(f"{path} is not a complete run")
        reports.append(report)
    return reports


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("runs", nargs="+", type=Path, help="benchmarks.run output dirs")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument(
        "--not-run",
        action="append",
        default=[],
        metavar="MODEL/DATASET=REASON",
        help="reason recorded for a grid cell without a run",
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    not_run = dict(item.split("=", 1) for item in args.not_run)
    beir = json.loads((ROOT / "benchmarks/configs/beir-datasets.json").read_text())
    frozen = json.loads((ROOT / "benchmarks/configs/frozen-inputs.json").read_text())
    inputs, results = collect(load(args.runs), beir, frozen, not_run)
    if args.check:
        committed = json.loads(args.output.read_text())
        if dumps(committed["results"]) != dumps(results):
            raise SystemExit(f"{args.output}: results differ from the run reports")
        print(f"{args.output}: results match")
        return
    value = {
        "schema": SCHEMA,
        "sdk_commit": git("rev-parse", "HEAD"),
        "working_tree_dirty": bool(git("status", "--porcelain")),
        "hardware": hardware(),
        "generated_utc": datetime.now(UTC).isoformat(),
        "inputs": inputs,
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(dumps(value))
    print(args.output)


if __name__ == "__main__":
    main()
