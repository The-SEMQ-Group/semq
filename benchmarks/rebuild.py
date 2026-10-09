# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Rebuild pair: does the gate stay quiet on null rebuilds and fire on real changes?

Two steps, two environments:

* ``python -m benchmarks.rebuild --embed`` (in ``.venv-data``) embeds the full
  SciFact corpus once per run below and caches each run as float32 ``.npy``.
* ``python -m benchmarks.rebuild`` (in ``.venv``) encodes every cached run with
  each SEMQ configuration, measures a floor from three null rebuilds, gates
  every candidate, runs the ``semq`` CLI once on the default configuration,
  compares simpler checks on the same runs, and writes the result file.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path.home() / ".cache" / "semq-benchmarks" / "rebuild"
OUTPUT = ROOT / "docs" / "assets" / "benchmarks" / "summary" / "rebuild.json"
DATASETS = ROOT / "benchmarks" / "configs" / "beir-datasets.json"

REFERENCE_MODEL = {
    "repo": "intfloat/e5-small-v2",
    "revision": "ffb93f3bd4047442299a41ebb6fa998a38507c52",
}
PREVIOUS_MODEL = {
    "repo": "intfloat/e5-small",
    "revision": "e272f3049e853b47cb5ca3952268c6662abda68f",
}
PREFIX = "passage: "
TORCH_THREADS = 4

# Every run embeds the same 5,183 SciFact documents. Only the listed fields
# differ from the reference (CPU, float32, batch 32, max_length 512, mean
# pooling as configured by the model, normalize_embeddings=True).
RUNS: dict[str, dict[str, Any]] = {
    "reference_cpu_b32": {"role": "reference"},
    "null_cpu_b128": {"role": "floor_null", "batch_size": 128},
    "null_gpu_b32": {"role": "floor_null", "device": "gpu"},
    "null_gpu_b128": {"role": "floor_null", "device": "gpu", "batch_size": 128},
    "null_cpu_b1": {"role": "extra_null", "batch_size": 1},
    "null_gpu_b64": {"role": "held_out_null", "device": "gpu", "batch_size": 64},
    "change_model_v1": {"role": "real_change", "model": PREVIOUS_MODEL},
    "change_fp16_gpu": {"role": "real_change", "device": "gpu", "dtype": "float16"},
    "change_max_length_128": {"role": "real_change", "max_length": 128},
    "change_unnormalized_renorm64": {"role": "real_change", "normalize": False},
    "change_cls_pooling": {"role": "real_change", "pooling": "cls"},
}
DESCRIPTIONS = {
    "reference_cpu_b32": "reference: CPU, float32, batch 32",
    "null_cpu_b128": "null rebuild: CPU, batch 128",
    "null_gpu_b32": "null rebuild: GPU, batch 32",
    "null_gpu_b128": "null rebuild: GPU, batch 128",
    "null_cpu_b1": "null rebuild: CPU, batch 1 (not used for the floor)",
    "null_gpu_b64": "null rebuild held out as the candidate that should pass: GPU, batch 64",
    "change_model_v1": "model revision change: intfloat/e5-small (v1) instead of e5-small-v2",
    "change_fp16_gpu": "precision change: float16 on the GPU",
    "change_max_length_128": "truncation change: max_length 128 instead of 512",
    "change_unnormalized_renorm64": (
        "normalization change: normalize_embeddings=False, then renormalized in float64"
    ),
    "change_cls_pooling": "pooling change: CLS token instead of mean pooling",
}
FLOOR_NULLS = [name for name, run in RUNS.items() if run["role"] == "floor_null"]
CANDIDATES = [
    name for name, run in RUNS.items() if run["role"] not in ("reference", "floor_null")
]
REFERENCE = "reference_cpu_b32"
HELD_OUT = "null_gpu_b64"
HEADLINE_CHANGE = "change_model_v1"

# Ids of the SEMQ configurations; the builders receive the dimension.
CONFIGS: dict[str, tuple[str, int]] = {
    "semq_quant2": ("quant", 2),
    "semq_quant4": ("quant", 4),
    "semq_quant8": ("quant", 8),
    "semq_phase16": ("phase", 16),
    "semq_orbit50": ("orbit", 50),
}
DEFAULT_CONFIG = "semq_quant4"
COSINE_ROW_THRESHOLD = 0.9999
LIST_IDS_UP_TO = 50


def run_spec(name: str) -> dict[str, Any]:
    """The full settings of one run: the reference with the run's overrides."""
    base = {
        "model": REFERENCE_MODEL,
        "device": "cpu",
        "batch_size": 32,
        "dtype": "float32",
        "max_length": 512,
        "pooling": "mean",
        "normalize": True,
    }
    return {**base, **{k: v for k, v in RUNS[name].items() if k != "role"}}


# -- shared helpers (also used by benchmarks.granularity) ---------------------


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def hardware() -> dict[str, Any]:
    """The CPU, and the GPU the embeddings ran on: MPS on macOS, else NVIDIA if any."""
    machine = platform.processor()
    gpu = None
    if sys.platform == "darwin":
        try:
            machine = subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"], text=True
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            pass
        gpu = f"{machine} (MPS)"
    else:
        try:
            with open("/proc/cpuinfo", encoding="utf-8") as f:
                machine = next(
                    line.split(":", 1)[1].strip()
                    for line in f
                    if line.startswith("model name")
                )
        except (OSError, StopIteration):
            pass
        try:
            names = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], text=True
            ).split("\n")
            gpu = names[0].strip() or None
        except (OSError, subprocess.CalledProcessError):
            pass
    return {
        "machine": machine,
        "os": platform.platform(),
        "arch": platform.machine(),
        "cpu_threads": os.cpu_count(),
        "gpu": gpu,
    }


def envelope(metric: str, inputs: dict[str, Any], results: dict[str, Any]) -> dict:
    return {
        "schema": f"semq-bench/{metric}/1",
        "sdk_commit": git("rev-parse", "HEAD"),
        "working_tree_dirty": bool(git("status", "--porcelain")),
        "hardware": hardware(),
        "generated_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "inputs": inputs,
        "results": results,
    }


def dump(value: dict) -> str:
    return json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"


def write_or_check(path: Path, report: dict, check: bool) -> None:
    """Write ``report``; with ``check``, fail when the committed results differ."""
    if check:
        committed = json.loads(path.read_text())
        fresh = json.loads(dump(report))
        if committed["results"] != fresh["results"]:
            sys.exit(f"{path}: results differ from a fresh computation")
        print(f"{path}: results match", flush=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump(report))
    print(path, flush=True)


def p99(values: list[int]) -> int:
    """Nearest-rank p99 as a descriptive benchmark statistic."""
    m = len(values)
    if m == 0:
        return 0
    return sorted(values)[m - m // 100 - 1]


def semq_config(config_id: str, dim: int) -> Any:
    from semq import CodecConfig

    operator, parameter = CONFIGS[config_id]
    return getattr(CodecConfig, operator)(dim, parameter)


def manifest_for(model: dict[str, str]) -> dict[str, str]:
    return {"encoder": model["repo"], "encoder_revision": model["revision"]}


def diff_summary(diff: Any, floor: Any | None) -> dict[str, Any]:
    changed = diff.changed
    n_common = len(changed) + diff.n_unchanged
    hamming = [h for _, h in changed]
    summary = {
        "rows_changed": len(changed),
        "rows_changed_pct": 100.0 * len(changed) / n_common,
        "p99_hamming": p99(hamming),
        "max_hamming": max(hamming, default=0),
        "manifest_changed": sorted(diff.manifest_changes),
    }
    if len(changed) <= LIST_IDS_UP_TO:
        summary["changed_ids"] = [int(i) for i, _ in changed]
    if floor is not None:
        summary["within"] = diff.within(floor)
    return summary


def floor_summary(floor: Any) -> dict[str, Any]:
    return {
        "changed_rows": floor.changed_rows,
        "total_rows": floor.total_rows,
        "changed_pct": 100.0 * floor.changed_rows / floor.total_rows,
        "hamming": floor.hamming,
        "nulls": floor.nulls,
    }


# -- simpler checks on the float32 vectors ------------------------------------


def row_cosines(reference: np.ndarray, candidate: np.ndarray) -> np.ndarray:
    a = reference.astype(np.float64)
    b = candidate.astype(np.float64)
    return np.einsum("ij,ij->i", a, b) / (
        np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1)
    )


def simple_checks(reference: np.ndarray, candidate: np.ndarray) -> dict[str, Any]:
    """Checks a user could write without SEMQ, computed on the float32 vectors."""
    cosines = row_cosines(reference, candidate)
    return {
        "sha256_equal": hashlib.sha256(reference.tobytes()).hexdigest()
        == hashlib.sha256(candidate.tobytes()).hexdigest(),
        "allclose_default": bool(np.allclose(candidate, reference)),
        "max_abs_diff": float(np.max(np.abs(candidate - reference))),
        "cosine_below_share": float(np.mean(cosines < COSINE_ROW_THRESHOLD)),
        "min_cosine": float(cosines.min()),
    }


def simple_verdicts(
    checks: dict[str, dict[str, Any]], floor_nulls: list[str]
) -> dict[str, dict[str, Any]]:
    """Turn each check into a flag. Threshold checks get the null envelope.

    ``sha256`` and ``allclose`` flag any difference. ``max_abs_diff`` and
    ``cosine_below_share`` have no default threshold, so each gets the same
    treatment as the SEMQ floor: the largest value seen on the floor nulls.
    ``cosine_any_below`` flags a run as soon as one row falls below the cosine
    threshold.
    """
    limit_abs = max(checks[n]["max_abs_diff"] for n in floor_nulls)
    limit_cos = max(checks[n]["cosine_below_share"] for n in floor_nulls)
    out = {}
    for name, c in checks.items():
        out[name] = {
            "sha256": not c["sha256_equal"],
            "allclose": not c["allclose_default"],
            "max_abs_diff_vs_null_envelope": c["max_abs_diff"] > limit_abs,
            "cosine_any_below": c["cosine_below_share"] > 0,
            "cosine_share_vs_null_envelope": c["cosine_below_share"] > limit_cos,
        }
    return {
        "flags": out,
        "null_envelope": {
            "max_abs_diff": limit_abs,
            "cosine_below_share": limit_cos,
        },
    }


def classify_verdicts(
    flags: dict[str, dict[str, bool]], roles: dict[str, str]
) -> dict[str, dict[str, list[str]]]:
    """For each check: which nulls it wrongly flags and which changes it misses."""
    methods = sorted(next(iter(flags.values())))
    out = {}
    for method in methods:
        out[method] = {
            "false_alarms_on_nulls": sorted(
                n for n, f in flags.items() if roles[n] != "real_change" and f[method]
            ),
            "missed_real_changes": sorted(
                n
                for n, f in flags.items()
                if roles[n] == "real_change" and not f[method]
            ),
        }
    return out


# -- embedding (runs in .venv-data) -------------------------------------------


def load_corpus(offline: bool = False) -> dict[str, Any]:
    """The SciFact corpus text exactly as benchmarks.prepare_beir builds it."""
    import pyarrow.parquet as pq
    from huggingface_hub import hf_hub_download

    from .prepare_beir import align

    spec = json.loads(DATASETS.read_text())["datasets"]["scifact"]
    files = {}

    def fetch(repo: str, revision: str, filename: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("revisions must be full commit hashes")
        path = Path(
            hf_hub_download(
                repo,
                filename,
                repo_type="dataset",
                revision=revision,
                local_files_only=offline,
            )
        )
        files[f"{repo}/{filename}"] = {
            "revision": revision,
            "sha256": sha256_file(path),
        }
        return path

    corpus = pq.read_table(
        fetch(spec["repo"], spec["revision"], spec["corpus_file"])
    ).to_pylist()
    queries = pq.read_table(
        fetch(spec["repo"], spec["revision"], spec["queries_file"])
    ).to_pylist()
    with fetch(spec["qrels_repo"], spec["qrels_revision"], "test.tsv").open() as s:
        qrels = list(csv.DictReader(s, delimiter="\t"))
    data = align(corpus, queries, qrels)
    if len(data["corpus_ids"]) != spec["corpus_rows"]:
        raise ValueError("source counts differ from the frozen dataset definition")
    return {
        "ids": [str(i) for i in data["corpus_ids"]],
        "text": data["corpus_text"],
        "source_files": files,
    }


def embed(texts: list[str], spec: dict[str, Any], offline: bool = False) -> dict:
    """Embed ``texts`` with the settings of ``spec``; float32, unit rows."""
    import torch
    from sentence_transformers import SentenceTransformer
    from sentence_transformers.sentence_transformer.modules import Pooling

    torch.set_num_threads(TORCH_THREADS)
    device = spec["device"]
    if device == "gpu":
        if torch.backends.mps.is_available():
            device = "mps"
        elif torch.cuda.is_available():
            device = "cuda"
        else:
            raise SystemExit(
                "this run needs a GPU (MPS or CUDA), and none is available"
            )
    model = SentenceTransformer(
        spec["model"]["repo"],
        revision=spec["model"]["revision"],
        device=device,
        local_files_only=offline,
        trust_remote_code=False,
    )
    if spec["dtype"] == "float16":
        model.half()
    else:
        model.float()
    model.max_seq_length = spec["max_length"]
    if spec["pooling"] == "cls":
        dim = model.get_sentence_embedding_dimension()
        model[1] = Pooling(dim, pooling_mode="cls")
    started = time.perf_counter()
    values = model.encode(
        texts,
        prompt=PREFIX,
        batch_size=spec["batch_size"],
        normalize_embeddings=spec["normalize"],
        convert_to_numpy=True,
        show_progress_bar=True,
    )
    seconds = time.perf_counter() - started
    raw_dtype = str(values.dtype)
    renormalized = not spec["normalize"] or spec["dtype"] == "float16"
    if renormalized:
        wide = np.asarray(values, dtype=np.float64)
        values = wide / np.linalg.norm(wide, axis=1, keepdims=True)
    values = np.ascontiguousarray(values, dtype=np.float32)
    if not np.isfinite(values).all():
        raise ValueError("non-finite embeddings")
    return {
        "values": values,
        "meta": {
            **spec,
            "device": str(model.device),
            "output_dtype": raw_dtype,
            "renormalized_float64": renormalized,
            "embed_seconds": round(seconds, 1),
            "torch": importlib.metadata.version("torch"),
            "sentence-transformers": importlib.metadata.version(
                "sentence-transformers"
            ),
            "transformers": importlib.metadata.version("transformers"),
            "torch_threads": TORCH_THREADS,
            "prefix": PREFIX,
        },
    }


def embed_all(cache: Path, offline: bool, only: list[str] | None) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    corpus = load_corpus(offline)
    meta_path = cache / "runs.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    meta["corpus"] = {
        "dataset": "BeIR/scifact",
        "rows": len(corpus["ids"]),
        "source_files": corpus["source_files"],
        "ids_sha256": hashlib.sha256("\n".join(corpus["ids"]).encode()).hexdigest(),
    }
    for name in only or list(RUNS):
        print(f"embedding {name}", flush=True)
        result = embed(corpus["text"], run_spec(name), offline)
        np.save(cache / f"{name}.npy", result["values"])
        meta.setdefault("runs", {})[name] = result["meta"]
        meta_path.write_text(dump(meta))
        print(f"{name}: {result['meta']['embed_seconds']} s", flush=True)


# -- analysis (runs in .venv) -------------------------------------------------


def load_runs(cache: Path) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    meta = json.loads((cache / "runs.json").read_text())
    arrays = {name: np.load(cache / f"{name}.npy") for name in RUNS}
    return arrays, meta


def gate_all(
    arrays: dict[str, np.ndarray],
    reference: str,
    floor_nulls: list[str],
    candidates: list[str],
    manifests: dict[str, dict[str, str]],
    config_ids: list[str],
) -> dict[str, Any]:
    """Encode every run per configuration, measure the floor and gate candidates."""
    from semq import Codec, Floor

    n, dim = arrays[reference].shape
    ids = np.arange(n, dtype=np.uint64)
    out = {}
    for config_id in config_ids:
        codec = Codec(semq_config(config_id, dim))
        ref = codec.encode(
            ids=ids, vectors=arrays[reference], manifest=manifests[reference]
        )
        states = {
            name: codec.encode(ids=ids, vectors=arrays[name], manifest=manifests[name])
            for name in [*floor_nulls, *candidates]
        }
        floor = Floor.measure([ref.diff(states[name]) for name in floor_nulls])
        out[config_id] = {
            "bits_per_dim": 8 * codec.config.bytes_per_vector / dim,
            "floor": floor_summary(floor),
            "floor_nulls": {
                name: diff_summary(ref.diff(states[name]), floor)
                for name in floor_nulls
            },
            "candidates": {
                name: diff_summary(ref.diff(states[name]), floor) for name in candidates
            },
        }
    return out


def rows_only_verdict(
    arrays: dict[str, np.ndarray], name: str, config_id: str
) -> dict[str, Any]:
    """Gate ``name`` with the reference manifest, as if the pipeline forgot to update it."""
    manifests = {k: manifest_for(REFERENCE_MODEL) for k in RUNS}
    result = gate_all(arrays, REFERENCE, FLOOR_NULLS, [name], manifests, [config_id])
    return result[config_id]["candidates"][name]


def run_cli(
    arrays: dict[str, np.ndarray], manifests: dict[str, dict[str, str]], config_id: str
) -> dict[str, Any]:
    """The documented workflow: ``semq floor`` then ``semq diff --floor``."""
    from semq import Codec

    n, dim = arrays[REFERENCE].shape
    ids = np.arange(n, dtype=np.uint64)
    codec = Codec(semq_config(config_id, dim))
    exe = Path(sys.executable).with_name("semq")
    command = [str(exe)] if exe.exists() else [sys.executable, "-m", "semq"]
    out: dict[str, Any] = {"config": config_id, "diff_exit_codes": {}}
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for name in [REFERENCE, *FLOOR_NULLS, *CANDIDATES]:
            codec.encode(ids=ids, vectors=arrays[name], manifest=manifests[name]).save(
                str(work / f"{name}.semq")
            )
        floor = subprocess.run(
            [
                *command,
                "floor",
                f"{REFERENCE}.semq",
                *(f"{n}.semq" for n in FLOOR_NULLS),
            ],
            cwd=work,
            capture_output=True,
            text=True,
        )
        out["floor_command"] = "semq floor " + " ".join(
            f"{n}.semq" for n in [REFERENCE, *FLOOR_NULLS]
        )
        out["floor_exit_code"] = floor.returncode
        if floor.returncode != 0:
            out["floor_stderr"] = floor.stderr
            return out
        out["floor_json"] = json.loads(floor.stdout)
        (work / "floor.json").write_text(floor.stdout)
        out["diff_command"] = (
            f"semq diff {REFERENCE}.semq CANDIDATE.semq --floor floor.json"
        )
        for name in CANDIDATES:
            done = subprocess.run(
                [
                    *command,
                    "diff",
                    f"{REFERENCE}.semq",
                    f"{name}.semq",
                    "--floor",
                    "floor.json",
                ],
                cwd=work,
                capture_output=True,
                text=True,
            )
            out["diff_exit_codes"][name] = done.returncode
    return out


def evaluate(cache: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    arrays, meta = load_runs(cache)
    roles = {name: run["role"] for name, run in RUNS.items()}
    manifests = {name: manifest_for(run_spec(name)["model"]) for name in RUNS}
    gates = gate_all(
        arrays, REFERENCE, FLOOR_NULLS, CANDIDATES, manifests, list(CONFIGS)
    )
    compared = [*FLOOR_NULLS, *CANDIDATES]
    checks = {name: simple_checks(arrays[REFERENCE], arrays[name]) for name in compared}
    verdicts = simple_verdicts(checks, FLOOR_NULLS)
    cli = run_cli(arrays, manifests, DEFAULT_CONFIG)
    api = {n: gates[DEFAULT_CONFIG]["candidates"][n]["within"] for n in CANDIDATES}
    cli["matches_api"] = all(
        (code == 0) == api[n] for n, code in cli["diff_exit_codes"].items()
    )
    semq_flags = {
        config_id: {
            **{n: not g["floor_nulls"][n]["within"] for n in FLOOR_NULLS},
            **{n: not g["candidates"][n]["within"] for n in CANDIDATES},
        }
        for config_id, g in gates.items()
    }
    all_flags = {
        name: {
            **verdicts["flags"][name],
            **{cid: semq_flags[cid][name] for cid in CONFIGS},
        }
        for name in compared
    }
    default = gates[DEFAULT_CONFIG]["candidates"]
    results = {
        "question": (
            "If I re-embed the same corpus, does the gate stay quiet, and does it "
            "fire when something real changed?"
        ),
        "corpus": meta["corpus"],
        "runs": {
            name: {
                "role": roles[name],
                "description": DESCRIPTIONS[name],
                "manifest": manifests[name],
                "embedding": meta["runs"][name],
            }
            for name in RUNS
        },
        "reference": REFERENCE,
        "floor_nulls": FLOOR_NULLS,
        "ids": "0..n-1 as u64",
        "semq": gates,
        "model_change_rows_only": {
            "note": (
                "change_model_v1 gated with the reference manifest, as a pipeline "
                "that forgot to record the new encoder would; the verdict then "
                "rests on the rows alone"
            ),
            **{cid: rows_only_verdict(arrays, HEADLINE_CHANGE, cid) for cid in CONFIGS},
        },
        "cli": cli,
        "simple_checks": {
            "cosine_row_threshold": COSINE_ROW_THRESHOLD,
            "values": checks,
            "null_envelope": verdicts["null_envelope"],
            "rule": (
                "sha256 and allclose (numpy defaults rtol=1e-05, atol=1e-08) flag any "
                "difference; max_abs_diff and cosine_below_share flag values above "
                "the largest seen on the three floor nulls; cosine_any_below flags "
                "one row below the cosine threshold"
            ),
        },
        "notes": [
            "change_unnormalized_renorm64 moves no coordinate by more than "
            "max_abs_diff in simple_checks.values; it is listed as a real change "
            "as planned, and change_cls_pooling is the pooling mistake that does "
            "move the vectors",
            "changed_ids lists the changed ids of every diff with at most "
            f"{LIST_IDS_UP_TO} changed rows",
        ],
        "flags": all_flags,
        "errors": classify_verdicts(all_flags, roles),
        "headline": {
            "config": DEFAULT_CONFIG,
            "held_out_null": {
                "run": HELD_OUT,
                "rows_changed_pct": default[HELD_OUT]["rows_changed_pct"],
                "within": default[HELD_OUT]["within"],
            },
            "model_revision_change": {
                "run": HEADLINE_CHANGE,
                "rows_changed_pct": default[HEADLINE_CHANGE]["rows_changed_pct"],
                "within": default[HEADLINE_CHANGE]["within"],
            },
        },
    }
    inputs = {
        f"rebuild/{name}.npy": {
            "sha256": sha256_file(cache / f"{name}.npy"),
            "source": f"python -m benchmarks.rebuild --embed ({DESCRIPTIONS[name]})",
        }
        for name in RUNS
    }
    return inputs, results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--embed", action="store_true", help="regenerate embeddings")
    parser.add_argument("--runs", nargs="*", choices=list(RUNS), help="with --embed")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--cache", type=Path, default=CACHE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.embed:
        embed_all(args.cache, args.offline, args.runs)
        return
    inputs, results = evaluate(args.cache)
    write_or_check(args.output, envelope("rebuild", inputs, results), args.check)


if __name__ == "__main__":
    main()
