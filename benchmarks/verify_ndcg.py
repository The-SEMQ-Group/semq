# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Check nDCG against trec_eval on identical rankings and relevance judgments."""

import argparse
import importlib.metadata
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np

from . import metrics, relevance
from .run import digest, load_data, write_json


def external_ndcg(arrays: dict, ids: np.ndarray, start: int = 0) -> np.ndarray:
    import pytrec_eval

    judgments = {}
    runs = {}
    for offset, ranking in enumerate(ids):
        row = start + offset
        pairs: Iterable[tuple[Any, Any]]
        if "relevance" in arrays:
            pairs = enumerate(arrays["relevance"][row])
        else:
            selected = arrays["qrel_query"] == row
            pairs = zip(
                arrays["qrel_document"][selected],
                arrays["qrel_score"][selected],
                strict=True,
            )
        qrels = {}
        for document, gain in pairs:
            if not np.isfinite(gain) or gain < 0 or gain != int(gain):
                raise ValueError(
                    "trec_eval validation requires nonnegative integer gains"
                )
            qrels[str(document)] = int(gain)
        if not qrels:
            qrels = {"unjudged-placeholder": 0}
        judgments[str(row)] = qrels
        # Ordinal scores preserve our chosen tie order; this checks nDCG, not tie policy.
        runs[str(row)] = {
            str(doc): float(len(ranking) - i) for i, doc in enumerate(ranking)
        }
    metric = f"ndcg_cut_{ids.shape[1]}"
    results = pytrec_eval.RelevanceEvaluator(judgments, {metric}).evaluate(runs)
    return np.asarray([results[str(start + row)][metric] for row in range(len(ids))])


def verify(report: dict, arrays: dict) -> dict:
    if report.get("schema_version") != 2 or report.get("status") != "complete":
        raise ValueError("expected a complete version 2 report")
    fp32 = next(m for m in report["methods"] if m["method"]["name"] == "fp32")
    original = arrays["corpus"].astype(np.float64)
    original_queries = arrays["queries"].astype(np.float64)
    profiles = {}
    for name in ("quality", "direction_scoring"):
        section = fp32[name]
        if section["status"] != "measured":
            raise ValueError("FP32 reference profile is not measured")
        observed = fp32["per_query"] if name == "quality" else section["per_query"]
        corpus, queries = original, original_queries
        if name == "direction_scoring":
            corpus = corpus / np.linalg.norm(corpus, axis=1, keepdims=True)
            queries = queries / np.linalg.norm(queries, axis=1, keepdims=True)
        maximum_error = 0.0
        for cutoff, per_query in observed.items():
            k = int(cutoff)
            values: list[float | None] = []
            for start in range(0, len(queries), 8):
                ids = metrics.ranking(queries[start : start + 8] @ corpus.T, k)
                expected = external_ndcg(arrays, ids, start)
                actual, eligible = (
                    metrics.ndcg(arrays["relevance"][start : start + len(ids)], ids)
                    if "relevance" in arrays
                    else relevance.ndcg(arrays, ids, start)
                )
                np.testing.assert_allclose(
                    actual[eligible], expected[eligible], rtol=0, atol=1e-12
                )
                values.extend(
                    float(v) if ok else None
                    for v, ok in zip(expected, eligible, strict=True)
                )
            stored = per_query["ndcg"]
            if any(v is not None and not np.isfinite(v) for v in stored):
                raise ValueError("report contains non-finite nDCG")
            if len(stored) != len(values) or [v is None for v in stored] != [
                v is None for v in values
            ]:
                raise ValueError(
                    "report query eligibility differs from source judgments"
                )
            differences = [
                abs(a - b)
                for a, b in zip(stored, values, strict=True)
                if a is not None and b is not None
            ]
            maximum_error = max(maximum_error, max(differences, default=0.0))
        if maximum_error > 1e-12:
            raise ValueError(f"report nDCG differs from trec_eval: {maximum_error}")
        profiles[name] = {"queries": len(queries), "max_absolute_error": maximum_error}
    return {
        "status": "verified",
        "evaluator": "pytrec-eval-terrier",
        "version": importlib.metadata.version("pytrec-eval-terrier"),
        "scope": "FP32 per-query raw and direction nDCG; shared metric checked on identical rankings",
        "tolerance": 1e-12,
        "profiles": profiles,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.report.read_text())
    arrays, source = load_data({"k": [1]}, args.data)
    if source["arrays"] != report["dataset"]["arrays"]:
        raise ValueError("input arrays do not match the evaluated report")
    evidence = verify(report, arrays)
    evidence["report_sha256"] = digest(args.report)
    evidence["verification_source_sha256"] = digest(Path(__file__))
    write_json(args.output, evidence)
    print(args.output)


if __name__ == "__main__":
    main()
