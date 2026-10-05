# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Detection granularity: if a small part of the corpus changed, which part?

Candidates replace k% of the reference rows with embeddings of edited
documents (the text cut to its first half). Two distribution-drift checks as
Evidently implements them for embeddings, re-implemented here in numpy so no
new dependency is needed, say whether each candidate drifted; a SEMQ diff
lists the changed ids, which are scored against the edited ids.

* ``python -m benchmarks.granularity --embed`` (in ``.venv-data``) embeds the
  edited documents; it needs the reference run of ``benchmarks.rebuild``.
* ``python -m benchmarks.granularity`` (in ``.venv``) writes the result file.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from . import rebuild

CACHE = Path.home() / ".cache" / "semq-benchmarks" / "granularity"
OUTPUT = (
    rebuild.ROOT / "docs" / "assets" / "benchmarks" / "summary" / "granularity.json"
)
SEED = 20260921
PERCENTS = (0.1, 1.0, 5.0, 10.0, 50.0)
CONFIG = "semq_quant4"

# Evidently's embedding drift defaults (docs.evidentlyai.com, "Embedding
# drift detection", and embedding_drift_methods.py in evidentlyai/evidently):
# model(threshold=0.55) trains SGDClassifier(loss="log_loss", random_state=42)
# on train_test_split(test_size=0.5, random_state=42) and reports ROC AUC;
# distance(dist="euclidean", threshold=0.2) compares the mean embeddings.
# Bootstrap is off by default above 1,000 objects, so the fixed thresholds apply.
EVIDENTLY: dict[str, Any] = {
    "source": [
        "https://docs.evidentlyai.com/metrics/customize_embedding_drift",
        "https://github.com/evidentlyai/evidently/blob/main/src/evidently/legacy/metrics/data_drift/embedding_drift_methods.py",
    ],
    "model_threshold_roc_auc": 0.55,
    "distance_threshold": 0.2,
    "distance_default_metric": "euclidean",
    "sgd_alpha": 1e-4,
    "bootstrap": "off (default is off above 1,000 objects)",
}


def edit(text: str) -> str:
    """A realistic edit: keep the first half of the words."""
    words = text.split()
    return " ".join(words[: len(words) // 2])


def edited_rows(n: int, seed: int = SEED) -> np.ndarray:
    """A fixed order of rows; the first k% of it are the edited rows."""
    return np.random.default_rng(seed).permutation(n)


def row_count(n: int, percent: float) -> int:
    return max(1, round(n * percent / 100))


def replace_rows(base: np.ndarray, rows: np.ndarray, values: np.ndarray) -> np.ndarray:
    out = base.copy()
    out[rows] = values
    return out


# -- drift checks, Evidently's defaults in numpy ------------------------------


def centroid_distances(reference: np.ndarray, current: np.ndarray) -> dict[str, float]:
    a = reference.astype(np.float64).mean(axis=0)
    b = current.astype(np.float64).mean(axis=0)
    cosine = 1.0 - float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))
    return {"cosine": cosine, "euclidean": float(np.linalg.norm(a - b))}


def roc_auc(labels: np.ndarray, scores: np.ndarray) -> float:
    """ROC AUC as the Mann-Whitney statistic with average ranks for ties."""
    order = np.argsort(scores, kind="mergesort")
    sorted_scores = scores[order]
    ranks = np.empty(len(scores), dtype=np.float64)
    i = 0
    while i < len(scores):
        j = i
        while j + 1 < len(scores) and sorted_scores[j + 1] == sorted_scores[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    positive = labels == 1
    n_pos, n_neg = int(positive.sum()), int((~positive).sum())
    return float((ranks[positive].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def logistic_fit(
    x: np.ndarray, y: np.ndarray, alpha: float, iterations: int = 100
) -> np.ndarray:
    """Minimize mean log loss + alpha/2 * |w|^2 (intercept unpenalized) by Newton.

    This is the objective SGDClassifier(loss="log_loss", alpha) approximates
    with stochastic steps; Newton reaches its minimum deterministically.
    """
    design = np.hstack([x, np.ones((len(x), 1))])
    weights = np.zeros(design.shape[1])
    penalty = np.full(design.shape[1], alpha)
    penalty[-1] = 0.0
    for _ in range(iterations):
        p = 1.0 / (1.0 + np.exp(-(design @ weights)))
        grad = design.T @ (p - y) / len(y) + penalty * weights
        hess = (design.T * (p * (1 - p))) @ design / len(y) + np.diag(penalty)
        hess[-1, -1] += 1e-12
        step = np.linalg.solve(hess, grad)
        weights -= step
        if np.max(np.abs(step)) < 1e-10:
            break
    return weights


def domain_classifier_auc(
    reference: np.ndarray, current: np.ndarray, seed: int = 42, alpha: float = 1e-4
) -> float:
    """Reference vs current classifier, 50/50 split, ROC AUC on the held-out half."""
    x = np.vstack([reference, current]).astype(np.float64)
    y = np.concatenate([np.zeros(len(reference)), np.ones(len(current))])
    order = np.random.default_rng(seed).permutation(len(x))
    train, test = order[: len(x) // 2], order[len(x) // 2 :]
    weights = logistic_fit(x[train], y[train], alpha)
    scores = np.hstack([x[test], np.ones((len(test), 1))]) @ weights
    return roc_auc(y[test], scores)


def drift_checks(reference: np.ndarray, current: np.ndarray) -> dict[str, Any]:
    distances = centroid_distances(reference, current)
    auc = domain_classifier_auc(reference, current, alpha=EVIDENTLY["sgd_alpha"])
    return {
        "centroid_cosine_distance": distances["cosine"],
        "centroid_cosine_drift": distances["cosine"] > EVIDENTLY["distance_threshold"],
        "centroid_euclidean_distance": distances["euclidean"],
        "centroid_euclidean_drift": distances["euclidean"]
        > EVIDENTLY["distance_threshold"],
        "classifier_roc_auc": auc,
        "classifier_drift": auc > EVIDENTLY["model_threshold_roc_auc"],
    }


# -- SEMQ ---------------------------------------------------------------------


def changed_set_scores(changed: set[int], truth: set[int]) -> dict[str, Any]:
    hit = len(changed & truth)
    return {
        "ids_reported": len(changed),
        "ids_edited": len(truth),
        "true_positives": hit,
        "false_positives": len(changed - truth),
        "missed": len(truth - changed),
        "precision": hit / len(changed) if changed else 1.0,
        "recall": hit / len(truth) if truth else 1.0,
        "exact": changed == truth,
    }


def semq_diff(
    codec: Any, reference_state: Any, candidate: np.ndarray, manifest: dict, floor: Any
) -> tuple[set[int], dict[str, Any]]:
    ids = np.arange(len(candidate), dtype=np.uint64)
    diff = reference_state.diff(
        codec.encode(ids=ids, vectors=candidate, manifest=manifest)
    )
    changed = {int(i) for i, _ in diff.changed}
    return changed, rebuild.diff_summary(diff, floor)


# -- embedding (runs in .venv-data) -------------------------------------------


def embed_edits(cache: Path, offline: bool) -> None:
    corpus = rebuild.load_corpus(offline)
    n = len(corpus["text"])
    rows = edited_rows(n)[: row_count(n, max(PERCENTS))]
    texts = [edit(corpus["text"][i]) for i in rows]
    result = rebuild.embed(texts, rebuild.run_spec(rebuild.REFERENCE), offline)
    cache.mkdir(parents=True, exist_ok=True)
    np.save(cache / "edited_rows.npy", rows.astype(np.int64))
    np.save(cache / "edited.npy", result["values"])
    unchanged = sum(t == corpus["text"][i] for t, i in zip(texts, rows, strict=True))
    meta = {
        "edit": "keep the first half of the whitespace-separated words",
        "seed": SEED,
        "rows": len(rows),
        "texts_unchanged_by_edit": int(unchanged),
        "embedding": result["meta"],
    }
    (cache / "edited.json").write_text(rebuild.dump(meta))
    print(f"edited: {result['meta']['embed_seconds']} s", flush=True)


# -- analysis (runs in .venv) -------------------------------------------------


def evaluate(cache: Path, rebuild_cache: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    from semq import Codec, Floor

    reference = np.load(rebuild_cache / f"{rebuild.REFERENCE}.npy")
    held_out = np.load(rebuild_cache / f"{rebuild.HELD_OUT}.npy")
    rows = np.load(cache / "edited_rows.npy")
    edited = np.load(cache / "edited.npy")
    meta = json.loads((cache / "edited.json").read_text())
    n, dim = reference.shape
    if not np.array_equal(rows, edited_rows(n)[: len(rows)]):
        raise ValueError("cached edited rows do not match the seed")
    manifest = rebuild.manifest_for(rebuild.REFERENCE_MODEL)
    ids = np.arange(n, dtype=np.uint64)
    codec = Codec(rebuild.semq_config(CONFIG, dim))
    ref_state = codec.encode(ids=ids, vectors=reference, manifest=manifest)
    floor = Floor.measure(
        [
            ref_state.diff(
                codec.encode(
                    ids=ids,
                    vectors=np.load(rebuild_cache / f"{name}.npy"),
                    manifest=manifest,
                )
            )
            for name in rebuild.FLOOR_NULLS
        ]
    )
    per_k: dict[str, dict[str, Any]] = {}
    for percent in PERCENTS:
        count = row_count(n, percent)
        chosen = rows[:count]
        truth = {int(i) for i in chosen}
        on_reference = replace_rows(reference, chosen, edited[:count])
        on_rebuild = replace_rows(held_out, chosen, edited[:count])
        changed, summary = semq_diff(codec, ref_state, on_reference, manifest, floor)
        changed_rb, summary_rb = semq_diff(
            codec, ref_state, on_rebuild, manifest, floor
        )
        cosines = rebuild.row_cosines(reference[chosen], edited[:count])
        per_k[f"{percent:g}"] = {
            "percent": percent,
            "rows_edited": count,
            "edit_cosine_to_original": {
                "mean": float(cosines.mean()),
                "min": float(cosines.min()),
                "max": float(cosines.max()),
            },
            "drift": drift_checks(reference, on_reference),
            "semq": {
                **changed_set_scores(changed, truth),
                "within_rebuild_floor": summary["within"],
                "p99_hamming": summary["p99_hamming"],
            },
            "semq_on_null_rebuild": {
                **changed_set_scores(changed_rb, truth),
                "within_rebuild_floor": summary_rb["within"],
                "p99_hamming": summary_rb["p99_hamming"],
            },
        }
    headline = per_k["1"]
    results = {
        "question": "If a small part of my corpus changed, will I know which part?",
        "reference": rebuild.REFERENCE,
        "config": CONFIG,
        "edit": meta,
        "evidently_defaults": EVIDENTLY,
        "implementation": (
            "Evidently's centroid distance and domain classifier re-implemented in "
            "numpy (no new dependency): L2 logistic regression solved by Newton "
            "instead of SGD, 50/50 random split with seed 42, ROC AUC on the "
            "held-out half"
        ),
        "floor": {"nulls": rebuild.FLOOR_NULLS, **rebuild.floor_summary(floor)},
        "variants": {
            "semq": "edited rows replace rows of the reference bytes; all other rows identical",
            "semq_on_null_rebuild": (
                f"edited rows replace rows of the held-out null rebuild "
                f"({rebuild.HELD_OUT}), so rebuild noise is also present"
            ),
        },
        "per_k": per_k,
        "headline": {
            "percent": 1.0,
            "rows_edited": headline["rows_edited"],
            "centroid_cosine_drift": headline["drift"]["centroid_cosine_drift"],
            "classifier_drift": headline["drift"]["classifier_drift"],
            "classifier_roc_auc": headline["drift"]["classifier_roc_auc"],
            "semq_exact_ids": headline["semq"]["exact"],
            "semq_precision": headline["semq"]["precision"],
            "semq_recall": headline["semq"]["recall"],
        },
    }
    inputs = {
        f"rebuild/{rebuild.REFERENCE}.npy": {
            "sha256": rebuild.sha256_file(rebuild_cache / f"{rebuild.REFERENCE}.npy"),
            "source": "python -m benchmarks.rebuild --embed",
        },
        f"rebuild/{rebuild.HELD_OUT}.npy": {
            "sha256": rebuild.sha256_file(rebuild_cache / f"{rebuild.HELD_OUT}.npy"),
            "source": "python -m benchmarks.rebuild --embed",
        },
        **{
            f"rebuild/{name}.npy": {
                "sha256": rebuild.sha256_file(rebuild_cache / f"{name}.npy"),
                "source": "python -m benchmarks.rebuild --embed",
            }
            for name in rebuild.FLOOR_NULLS
        },
        **{
            f"granularity/{name}": {
                "sha256": rebuild.sha256_file(cache / name),
                "source": "python -m benchmarks.granularity --embed",
            }
            for name in ("edited.npy", "edited_rows.npy")
        },
    }
    return inputs, results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--embed", action="store_true", help="regenerate embeddings")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--cache", type=Path, default=CACHE)
    parser.add_argument("--rebuild-cache", type=Path, default=rebuild.CACHE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.embed:
        embed_edits(args.cache, args.offline)
        return
    inputs, results = evaluate(args.cache, args.rebuild_cache)
    rebuild.write_or_check(
        args.output, rebuild.envelope("granularity", inputs, results), args.check
    )


if __name__ == "__main__":
    main()
