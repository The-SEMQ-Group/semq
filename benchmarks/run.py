# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Run a versioned codec-quality workload: python -m benchmarks.run --help."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from . import codecs, metrics, relevance

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def write_json(path: Path, value: dict) -> None:
    text = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    with path.open("x") as stream:
        stream.write(text)


def provenance(config: dict) -> dict:
    def git(*args):
        return subprocess.check_output(
            ["git", "-C", str(ROOT), *args], text=True
        ).strip()

    packages = {}
    for name in ("numpy", "semq", "faiss-cpu"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    result = {
        "utc": datetime.now(UTC).isoformat(),
        "git_commit": git("rev-parse", "HEAD"),
        "working_tree_dirty": bool(git("status", "--porcelain")),
        "platform": platform.platform(),
        "quality_environment": (
            {"system": "Linux", "libc": list(platform.libc_ver())}
            if platform.system() == "Linux" and all(platform.libc_ver())
            else {"platform": platform.platform()}
        ),
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "packages": packages,
        "config_sha256": hashlib.sha256(
            json.dumps(config, sort_keys=True).encode()
        ).hexdigest(),
        "benchmark_source_sha256": {
            str(p.relative_to(ROOT)): digest(p)
            for p in sorted((ROOT / "benchmarks").glob("*.py"))
        },
    }
    if any(
        m["name"] in ("semq_quant", "semq_phase", "semq_orbit")
        for m in config["methods"]
    ):
        import semq

        module = Path(semq.__file__).resolve()
        expected_root = ROOT / "bindings/python/semq"
        expected = {
            str(p.relative_to(expected_root)): digest(p)
            for p in expected_root.rglob("*.py")
        }
        loaded = {
            str(p.relative_to(module.parent)): digest(p)
            for p in module.parent.rglob("*.py")
        }
        if loaded != expected:
            raise ValueError(
                "Installed binding source differs from checkout; install this SDK"
            )
        native = Path(os.environ.get("SEMQ_LIBRARY_PATH", ""))
        if not native.is_file():
            raise ValueError(
                "Set SEMQ_LIBRARY_PATH to the built native library for provenance"
            )
        result["semq"] = {
            "module": str(module),
            "binding_source_sha256": loaded,
            "native_library": str(native.resolve()),
            "native_sha256": digest(native),
        }
    return result


def validate(config: dict) -> None:
    allowed = {
        "schema_version",
        "suite",
        "seed",
        "k",
        "query_batch_size",
        "methods",
        "synthetic",
        "method_scoring",
        "direction_scoring",
        "uncertainty",
    }
    if (
        set(config) - allowed
        or config.get("schema_version") != 1
        or config.get("suite") != "codec_quality"
    ):
        raise ValueError("unknown configuration field, schema version or suite")
    if type(config.get("seed")) is not int or config["seed"] < 0:
        raise ValueError("seed must be a nonnegative integer")
    ks = config.get("k", [])
    if (
        not ks
        or any(type(k) is not int or k < 1 for k in ks)
        or len(set(ks)) != len(ks)
    ):
        raise ValueError("k must contain distinct positive integers")
    batch = config.get("query_batch_size")
    if type(batch) is not int or batch < 1:
        raise ValueError("query_batch_size must be positive")
    if type(config.get("method_scoring", False)) is not bool:
        raise ValueError("method_scoring must be boolean")
    if type(config.get("direction_scoring", False)) is not bool:
        raise ValueError("direction_scoring must be boolean")
    if "uncertainty" in config:
        settings = config["uncertainty"]
        if (
            not isinstance(settings, dict)
            or set(settings) != {"bootstrap_samples", "confidence", "seed"}
            or type(settings["bootstrap_samples"]) is not int
            or settings["bootstrap_samples"] < 1
            or type(settings["seed"]) is not int
            or settings["seed"] < 0
            or type(settings["confidence"]) not in (float, int)
            or not 0 < settings["confidence"] < 1
        ):
            raise ValueError("invalid uncertainty settings")
    methods = config.get("methods", [])
    ids = [m.get("id") for m in methods]
    if (
        not ids
        or any(
            not isinstance(i, str) or not i or not i.replace("_", "").isalnum()
            for i in ids
        )
        or len(set(ids)) != len(ids)
    ):
        raise ValueError("methods need unique alphanumeric/underscore IDs")
    for method in methods:
        codecs.build(method)


def load_data(config: dict, path: Path | None) -> tuple[dict, dict]:
    source: dict[str, Any]
    if path:
        with np.load(path, allow_pickle=False) as data:
            if not {"corpus", "queries", "fit"}.issubset(data.files):
                raise ValueError(
                    "NPZ must contain corpus, queries and explicit fit arrays"
                )
            arrays = {name: data[name] for name in ("corpus", "queries", "fit")}
            for name in {"relevance", "corpus_ids", "query_ids"} | relevance.FIELDS:
                if name in data.files:
                    arrays[name] = data[name]
            dataset_provenance = (
                json.loads(str(data["dataset_provenance"].item()))
                if "dataset_provenance" in data.files
                else None
            )
        source = {
            "kind": "user_npz",
            "path": str(path.resolve()),
            "sha256": digest(path),
            "scope": "user supplied; dataset/model provenance must accompany publication",
        }
        if dataset_provenance is not None:
            source["preparation"] = dataset_provenance
    else:
        spec = config.get("synthetic", {})
        if set(spec) != {"corpus_rows", "fit_rows", "query_rows", "dim"} or any(
            type(n) is not int or n < 1 for n in spec.values()
        ):
            raise ValueError("provide --data or positive synthetic dimensions")
        rng = np.random.Generator(np.random.PCG64(config["seed"]))
        arrays = {}
        for name, key in [
            ("fit", "fit_rows"),
            ("corpus", "corpus_rows"),
            ("queries", "query_rows"),
        ]:
            x = rng.standard_normal((spec[key], spec["dim"])).astype(np.float32)
            x /= np.linalg.norm(x, axis=1, keepdims=True)
            arrays[name] = x
        source = {
            "kind": "synthetic_smoke",
            "generator": "PCG64 normalized Gaussian",
            "scope": "pipeline validation only; no semantic-quality claim",
        }
    for name in ("corpus", "queries", "fit"):
        x = arrays[name]
        if (
            x.ndim != 2
            or not all(x.shape)
            or x.dtype != np.float32
            or not np.isfinite(x).all()
        ):
            raise ValueError(f"{name} must be a nonempty finite float32 matrix")
    corpus, queries, fit = (arrays[n] for n in ("corpus", "queries", "fit"))
    if len({x.shape[1] for x in (corpus, queries, fit)}) != 1 or max(config["k"]) > len(
        corpus
    ):
        raise ValueError("dimensions differ or k exceeds corpus size")
    if "relevance" in arrays and arrays["relevance"].shape != (
        len(queries),
        len(corpus),
    ):
        raise ValueError(
            "relevance must align with query rows and the full searched corpus"
        )
    if relevance.FIELDS & arrays.keys():
        if "relevance" in arrays:
            raise ValueError("choose dense or sparse relevance, not both")
        relevance.validate(arrays, len(queries), len(corpus))
    for name, rows in (("corpus_ids", len(corpus)), ("query_ids", len(queries))):
        if name in arrays and (
            arrays[name].shape != (rows,) or len(set(arrays[name].tolist())) != rows
        ):
            raise ValueError("document/query IDs must be unique and aligned")
    source["arrays"] = {
        name: {
            "shape": list(x.shape),
            "dtype": str(x.dtype),
            "sha256": hashlib.sha256(x.tobytes(order="C")).hexdigest(),
        }
        for name, x in arrays.items()
    }
    return arrays, source


def score_quality(config: dict, arrays: dict, score) -> dict:
    original = arrays["corpus"].astype(np.float64)
    queries = arrays["queries"]
    per_query: dict[str, dict[str, list]] = {
        str(k): {"overlap": [], "ndcg": [], "reference_ndcg": []} for k in config["k"]
    }
    square_error, error_sum, count = 0.0, 0.0, 0
    for start in range(0, len(queries), config["query_batch_size"]):
        stop = start + config["query_batch_size"]
        q = queries[start:stop].astype(np.float64)
        reference = q @ original.T
        scores = np.asarray(score(queries[start:stop]), dtype=np.float64)
        if scores.shape != reference.shape or not np.isfinite(scores).all():
            raise ValueError("invalid method scores")
        delta = scores - reference
        square_error += float(np.sum(delta * delta))
        error_sum += float(delta.sum())
        count += delta.size
        actual_ranking = metrics.ranking(scores, max(config["k"]))
        reference_ranking = metrics.ranking(reference, max(config["k"]))
        for k in config["k"]:
            actual_ids, reference_ids = (
                actual_ranking[:, :k],
                reference_ranking[:, :k],
            )
            row = per_query[str(k)]
            row["overlap"].extend(metrics.overlap(actual_ids, reference_ids).tolist())
            if "relevance" in arrays or "qrel_score" in arrays:
                if "relevance" in arrays:
                    rel = arrays["relevance"][start:stop]
                    actual_ndcg, mask = metrics.ndcg(rel, actual_ids)
                    reference_ndcg, _ = metrics.ndcg(rel, reference_ids)
                else:
                    actual_ndcg, mask = relevance.ndcg(arrays, actual_ids, start)
                    reference_ndcg, _ = relevance.ndcg(arrays, reference_ids, start)
                row["ndcg"].extend(
                    float(v) if ok else None
                    for v, ok in zip(actual_ndcg, mask, strict=True)
                )
                row["reference_ndcg"].extend(
                    float(v) if ok else None
                    for v, ok in zip(reference_ndcg, mask, strict=True)
                )
    retrieval: dict[str, dict[str, Any]] = {}
    for k, values in per_query.items():
        eligible = [v for v in values["ndcg"] if v is not None]
        ref = [v for v in values["reference_ndcg"] if v is not None]
        retrieval[k] = {
            "overlap": float(np.mean(values["overlap"])),
            "ndcg": float(np.mean(eligible)) if eligible else None,
            "reference_ndcg": float(np.mean(ref)) if ref else None,
            "ndcg_delta": (
                float(np.mean(np.subtract(eligible, ref))) if eligible else None
            ),
            "ndcg_eligible_queries": len(eligible),
            "ndcg_status": (
                "measured"
                if eligible
                else (
                    "no_positive_relevance"
                    if "relevance" in arrays or "qrel_score" in arrays
                    else "labels_unavailable"
                )
            ),
        }
        if "uncertainty" in config:
            settings = config["uncertainty"]
            retrieval[k]["ndcg_delta_interval"] = metrics.paired_ndcg_interval(
                values["ndcg"],
                values["reference_ndcg"],
                samples=settings["bootstrap_samples"],
                confidence=settings["confidence"],
                seed=settings["seed"],
            )
    return {
        "quality": {
            "retrieval": retrieval,
            "score_rmse": (square_error / count) ** 0.5,
            "score_bias": error_sum / count,
        },
        "per_query": per_query,
    }


def direction_quality(config: dict, arrays: dict, reconstructed: np.ndarray) -> dict:
    values = {
        "corpus": arrays["corpus"],
        "queries": arrays["queries"],
        "reconstruction": reconstructed,
    }
    normalized = {}
    zero_rows = {}
    for name, value in values.items():
        value = value.astype(np.float64)
        norms = np.linalg.norm(value, axis=1, keepdims=True)
        zero_rows[name] = int(np.count_nonzero(norms == 0))
        normalized[name] = np.divide(
            value, norms, out=np.zeros_like(value), where=norms != 0
        )
    if any(zero_rows.values()):
        return {
            "status": "not_comparable",
            "reason": "cosine undefined for zero-norm rows",
            "zero_rows": zero_rows,
        }
    normalized_arrays = {
        **arrays,
        "corpus": normalized["corpus"],
        "queries": normalized["queries"],
    }
    scores = score_quality(
        config, normalized_arrays, lambda q: q @ normalized["reconstruction"].T
    )
    scores["quality"]["direction_coordinate_mse"] = float(
        np.mean((normalized["corpus"] - normalized["reconstruction"]) ** 2)
    )
    return {
        "status": "measured",
        "profile": "unit_query_unit_reconstruction_cosine_f64",
        **scores,
    }


def evaluate(config: dict, arrays: dict, output: Path) -> list[dict]:
    corpus, fit = arrays["corpus"], arrays["fit"]
    original = corpus.astype(np.float64)
    results = []
    for spec in config["methods"]:
        encoded = codecs.build(spec).encode(fit, corpus)
        reconstructed = encoded.reconstruction.astype(np.float64)
        if reconstructed.shape != corpus.shape or not np.isfinite(reconstructed).all():
            raise ValueError("invalid codec reconstruction")
        artifact = output / f"{spec['id']}.npz"
        payload: dict[str, Any] = {"codes": encoded.codes, **encoded.model}
        np.savez(artifact, **payload)
        unavailable: dict[str, Any] = {
            "status": "not_comparable",
            "reason": encoded.reconstruction_limit,
        }
        common: dict[str, Any]
        if encoded.reconstruction_limit:
            common = {"quality": unavailable, "per_query": {}}
        else:
            common = score_quality(
                config, arrays, lambda q, r=reconstructed: q.astype(np.float64) @ r.T
            )
            residual = reconstructed - original
            energy = float(np.sum(original * original))
            common["quality"].update(
                {
                    "status": "measured",
                    "coordinate_mse": float(np.mean(residual * residual)),
                    "normalized_squared_error": (
                        float(np.sum(residual * residual)) / energy if energy else None
                    ),
                }
            )
        directional: dict[str, Any] = {"status": "not_requested"}
        if config.get("direction_scoring", False):
            directional = (
                unavailable
                if encoded.reconstruction_limit
                else direction_quality(config, arrays, reconstructed)
            )
        method_scoring: dict[str, Any] = {"status": "not_requested"}
        if config.get("method_scoring", False):
            if encoded.score is None:
                method_scoring = {"status": "not_supported"}
            else:
                method_scoring = {
                    "status": "measured",
                    "profile": encoded.score_profile,
                    **score_quality(config, arrays, encoded.score),
                }
        results.append(
            {
                "id": spec["id"],
                "method": spec,
                "storage": metrics.storage(
                    encoded.codes.nbytes, encoded.model_bytes, *corpus.shape
                ),
                "artifact": {
                    "file": artifact.name,
                    "file_bytes": artifact.stat().st_size,
                    "sha256": digest(artifact),
                },
                "quality": common["quality"],
                "direction_scoring": directional,
                "role": codecs.REGISTRY[spec["name"]].role,
                "resolved_parameters": {
                    key: value.item()
                    for key, value in encoded.model.items()
                    if value.ndim == 0
                },
                "per_query": common["per_query"],
                "method_scoring": method_scoring,
            }
        )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--data", type=Path, help="NPZ: corpus, queries, fit, optional relevance"
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="new, immutable run directory"
    )
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    validate(config)
    arrays, dataset = load_data(config, args.data)
    environment = provenance(config)
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "config.json", config)
    try:
        results = evaluate(config, arrays, args.output)
        report = {
            "schema_version": 2,
            "status": "complete",
            "suite": "codec_quality",
            "scoring_profile": "original_query_ip_f64_no_renormalization",
            "provenance": environment,
            "dataset": dataset,
            "methods": results,
            "performance": {
                "status": "not_measured",
                "reason": "codec quality workload",
            },
            "memory": {
                "status": "not_measured",
                "reason": "no process-level collector",
            },
            "portability": {"status": "not_measured", "reason": "single runtime"},
        }
        write_json(args.output / "report.json", report)
    except Exception as error:
        write_json(
            args.output / "failure.json",
            {
                "status": "failed",
                "error": str(error),
                "provenance": environment,
                "dataset": dataset,
            },
        )
        raise
    print(args.output / "report.json")


if __name__ == "__main__":
    main()
