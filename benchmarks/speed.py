# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Encode and decode throughput from Python, next to the embedding model cost.

Two steps, in two environments:

    # 1. embedding throughput (needs sentence-transformers; no semq import)
    .venv-data/bin/python -m benchmarks.speed embed --output EMBED.json
    # 2. SEMQ, numpy baselines and the C microbenchmark (needs semq)
    .venv/bin/python -m benchmarks.speed measure --embedding EMBED.json

Timings are wall-clock medians of several runs after one warm-up, in a single
process, on the hardware recorded in the result. They are frozen per release:
there is no --check, because they depend on the machine.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import statistics
import subprocess
import time
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

import numpy as np

from .size import RESULTS, ROOT, SEMQ_CONFIGS, envelope, write_result

DEFAULT_OUTPUT = RESULTS / "speed.json"
DEFAULT_BENCH = ROOT / "build-bench/bench_encode"
DIMS = (384, 768, 1024)
ROWS = 100_000
RUNS = 5
SEED = 20260928
OVERHEAD_DIM = 768

EMBED_MODEL: dict[str, Any] = {
    "repo": "intfloat/e5-base-v2",
    "revision": "f52bf8ec8c7124536f0efb74aca902b2995e5bcd",
    "document_prefix": "passage: ",
    "max_length": 512,
    "dimension": 768,
}
EMBED_DOCUMENTS = 2000
EMBED_BATCH = 64

# The C suite registers one parameter per operator (tests/bench/bench_encode.cpp).
C_BENCH_CONFIGS = {
    "quant": "semq_quant4",
    "phase": "semq_phase16",
    "orbit": "semq_orbit50",
}


def candidate_backends() -> list[str]:
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return ["scalar", "neon", "sve"]
    if machine in ("x86_64", "amd64"):
        return ["scalar", "avx2", "avx512"]
    return ["scalar"]


def make_codec(config: Any, backend: str | None) -> Any:
    """A Codec on the forced backend (None: what the dispatcher picks)."""
    from semq import Codec

    previous = os.environ.pop("SEMQ_FORCE_BACKEND", None)
    try:
        if backend is not None:
            os.environ["SEMQ_FORCE_BACKEND"] = backend
        return Codec(config)
    finally:
        os.environ.pop("SEMQ_FORCE_BACKEND", None)
        if previous is not None:
            os.environ["SEMQ_FORCE_BACKEND"] = previous


def unit_rows(rows: int, dims: int, seed: int = SEED) -> np.ndarray:
    rng = np.random.default_rng([seed, dims])
    values = rng.standard_normal((rows, dims), dtype=np.float32)
    values /= np.linalg.norm(values, axis=1, keepdims=True)
    return values


def timed(fn: Callable[[], Any], runs: int) -> dict[str, Any]:
    """Wall-clock seconds of `runs` calls after one untimed warm-up call."""
    fn()
    seconds = []
    for _ in range(runs):
        start = time.perf_counter()
        result = fn()
        seconds.append(time.perf_counter() - start)
        del result
    return {"runs_seconds": seconds, "median_seconds": statistics.median(seconds)}


def throughput(timing: dict[str, Any], rows: int) -> dict[str, Any]:
    median = timing["median_seconds"]
    return {
        **timing,
        "vectors_per_second": rows / median,
        "seconds_per_vector": median / rows,
    }


def semq_speed(
    dims: tuple[int, ...], rows: int, runs: int
) -> tuple[dict[str, Any], str]:
    from semq import CodecConfig

    ids = np.arange(rows, dtype=np.uint64)
    results: dict[str, Any] = {}
    default_backend = ""
    for dim in dims:
        vectors = unit_rows(rows, dim)
        per_dim: dict[str, Any] = {}
        for name, ctor, parameter in SEMQ_CONFIGS:
            config = getattr(CodecConfig, ctor)(dim, parameter)
            default = make_codec(config, None).backend
            default_backend = default_backend or default
            per_backend: dict[str, Any] = {}
            reference_rows: np.ndarray | None = None
            reference_digest: bytes | None = None
            for backend in candidate_backends():
                codec = make_codec(config, backend)
                # Report a backend only when the codec confirms that kernel.
                if codec.backend != backend:
                    continue
                encoding = codec.encode(ids=ids, vectors=vectors)
                digest = encoding.content_digest
                if reference_rows is None:
                    reference_rows = encoding.rows
                    reference_digest = digest
                elif digest != reference_digest or not np.array_equal(
                    encoding.rows, reference_rows
                ):
                    raise AssertionError(
                        f"{name} dim {dim}: {backend} row bytes differ from scalar"
                    )

                def encode(codec: Any = codec, vectors: Any = vectors) -> Any:
                    return codec.encode(ids=ids, vectors=vectors)

                def decode(codec: Any = codec, encoding: Any = encoding) -> Any:
                    return codec.decode(encoding)

                per_backend[backend] = {
                    "default": backend == default,
                    "content_digest": digest.hex(),
                    "encode": throughput(timed(encode, runs), rows),
                    "decode": throughput(timed(decode, runs), rows),
                }
                del encoding
            per_dim[name] = {"default_backend": default, "backends": per_backend}
        results[str(dim)] = per_dim
        del vectors
    return results, default_backend


def int8_encode(vectors: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    scale = np.max(np.abs(vectors), axis=1, keepdims=True) / np.float32(127)
    scale[scale == 0] = 1.0
    codes = np.clip(np.rint(vectors / scale), -127, 127).astype(np.int8)
    return codes, scale


def int8_decode(codes: np.ndarray, scale: np.ndarray) -> np.ndarray:
    return codes.astype(np.float32) * scale


def binary_encode(vectors: np.ndarray) -> np.ndarray:
    return np.packbits(vectors > 0, axis=1)


def binary_decode(codes: np.ndarray, dims: int) -> np.ndarray:
    bits = np.unpackbits(codes, axis=1, count=dims)
    return bits.astype(np.float32) * np.float32(2) - np.float32(1)


BASELINE_DEFINITIONS = {
    "fp16": "vectors.astype(np.float16); decode .astype(np.float32)",
    "int8": "per-row absmax/127, np.rint, clip to [-127, 127], int8; decode "
    "codes.astype(np.float32) * scale",
    "binary": "np.packbits(vectors > 0, axis=1); decode np.unpackbits to +-1 float32",
}


def numpy_speed(dims: tuple[int, ...], rows: int, runs: int) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for dim in dims:
        vectors = unit_rows(rows, dim)
        half = vectors.astype(np.float16)
        codes, scale = int8_encode(vectors)
        bits = binary_encode(vectors)
        cases: dict[str, tuple[Callable[[], Any], Callable[[], Any]]] = {
            "fp16": (
                partial(vectors.astype, np.float16),
                partial(half.astype, np.float32),
            ),
            "int8": (partial(int8_encode, vectors), partial(int8_decode, codes, scale)),
            "binary": (
                partial(binary_encode, vectors),
                partial(binary_decode, bits, dim),
            ),
        }
        results[str(dim)] = {
            name: {
                "encode": throughput(timed(encode, runs), rows),
                "decode": throughput(timed(decode, runs), rows),
            }
            for name, (encode, decode) in cases.items()
        }
        del vectors, half, codes, scale, bits
    return results


def parse_c_bench(report: dict) -> dict[str, Any]:
    """Median items_per_second per operation, operator and backend."""
    result: dict[str, Any] = {}
    for entry in report.get("benchmarks", []):
        if entry.get("run_type") == "aggregate" and entry.get("aggregate_name") != (
            "median"
        ):
            continue
        if entry.get("error_occurred") or entry.get("skipped"):
            continue
        parts = entry.get("run_name", entry["name"]).split("/")
        operation, operator, backend, dim, rows = parts[:5]
        key = C_BENCH_CONFIGS.get(operator)
        if key is None:
            continue
        slot = result.setdefault(dim.split(":")[1], {}).setdefault(key, {})
        slot = slot.setdefault(backend, {})
        slot[operation] = {
            "items_per_second": entry["items_per_second"],
            "rows": int(rows.split(":")[1]),
            "aggregate": entry.get("aggregate_name", "single run"),
        }
    return result


def c_bench(binary: Path, dim: int, rows: int, runs: int) -> dict[str, Any]:
    pattern = f"^(encode|decode)/[a-z]+/[a-z0-9]+/dim:{dim}/rows:{rows}(/|$)"
    command = [
        str(binary),
        "--benchmark_format=json",
        f"--benchmark_filter={pattern}",
        f"--benchmark_repetitions={runs}",
        "--benchmark_report_aggregates_only=true",
    ]
    shown = " ".join(
        [str(binary.relative_to(ROOT)) if binary.is_relative_to(ROOT) else str(binary)]
        + [f"'{a}'" if "(" in a else a for a in command[1:]]
    )
    if not binary.is_file():
        return {
            "status": "not_run",
            "reason": f"{binary} is missing",
            "command": "cmake --build build-bench --target bench_encode && " + shown,
        }
    env = {k: v for k, v in os.environ.items() if k != "SEMQ_FORCE_BACKEND"}
    output = subprocess.run(
        command, check=True, capture_output=True, text=True, env=env
    ).stdout
    if not output.strip():
        return {
            "status": "not_run",
            "reason": f"the C suite registers no benchmark at dim {dim}, rows {rows}",
            "command": shown,
        }
    report = json.loads(output)
    return {
        "status": "ok",
        "command": shown,
        "binary_sha256": sha256(binary),
        "context": {
            k: report.get("context", {}).get(k)
            for k in ("semq_core_version", "semq_build_id", "library_build_type")
        },
        "note": "the C suite has one parameter per operator (quant bins 4, phase "
        "sectors 16, orbit scale 50) and its own seeded inputs",
        "results": parse_c_bench(report),
    }


def sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def overhead(semq: dict[str, Any], embedding: dict[str, Any] | None) -> dict[str, Any]:
    if embedding is None or embedding.get("status") != "ok":
        return {
            "status": "not_run",
            "reason": "no embedding throughput file; pass --embedding",
            "command": ".venv-data/bin/python -m benchmarks.speed embed --output EMBED.json",
        }
    per_dim = semq.get(str(OVERHEAD_DIM))
    if per_dim is None:
        return {"status": "not_run", "reason": f"{OVERHEAD_DIM} dims not measured"}
    devices = embedding["devices"]
    result: dict[str, Any] = {
        "status": "ok",
        "dim": OVERHEAD_DIM,
        "definition": "100 x semq_encode_seconds_per_vector / "
        "embed_seconds_per_vector, SEMQ on the default backend",
        "configs": {},
    }
    for name, entry in per_dim.items():
        backend = entry["default_backend"]
        spv = entry["backends"][backend]["encode"]["seconds_per_vector"]
        row: dict[str, Any] = {
            "backend": backend,
            "semq_encode_seconds_per_vector": spv,
        }
        for device, timing in devices.items():
            if timing.get("status") == "ok":
                row[f"overhead_pct_vs_{device}"] = (
                    100 * spv / timing["seconds_per_vector"]
                )
        result["configs"][name] = row
    return result


# ---------------------------------------------------------------------------
# Embedding throughput (.venv-data)
# ---------------------------------------------------------------------------


def scifact_documents(count: int) -> tuple[list[str], dict[str, Any]]:
    """The first `count` SciFact corpus texts in the order prepare_beir uses."""
    import csv

    import pyarrow.parquet as pq
    from huggingface_hub import hf_hub_download

    from .prepare_beir import align

    config = json.loads((ROOT / "benchmarks/configs/beir-datasets.json").read_text())
    spec = config["datasets"]["scifact"]
    sources = {}

    def fetch(repo: str, revision: str, filename: str) -> Path:
        path = Path(
            hf_hub_download(repo, filename, repo_type="dataset", revision=revision)
        )
        sources[f"{repo}/{filename}"] = {"revision": revision, "sha256": sha256(path)}
        return path

    corpus = pq.read_table(
        fetch(spec["repo"], spec["revision"], spec["corpus_file"])
    ).to_pylist()
    queries = pq.read_table(
        fetch(spec["repo"], spec["revision"], spec["queries_file"])
    ).to_pylist()
    with fetch(spec["qrels_repo"], spec["qrels_revision"], "test.tsv").open() as f:
        qrels = list(csv.DictReader(f, delimiter="\t"))
    texts = align(corpus, queries, qrels)["corpus_text"][:count]
    if len(texts) != count:
        raise ValueError("SciFact has fewer documents than requested")
    return texts, sources


def embed_device(
    texts: list[str], device: str, runs: int, batch_size: int
) -> dict[str, Any]:
    import torch
    from sentence_transformers import SentenceTransformer

    if device == "mps" and not torch.backends.mps.is_available():
        return {"status": "not_run", "reason": "MPS is not available"}
    model = SentenceTransformer(
        EMBED_MODEL["repo"],
        revision=EMBED_MODEL["revision"],
        device=device,
        trust_remote_code=False,
    )
    model.float()
    model.max_seq_length = int(EMBED_MODEL["max_length"])

    def encode(items: list[str]) -> np.ndarray:
        values = model.encode(
            items,
            prompt=EMBED_MODEL["document_prefix"],
            batch_size=batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        if device == "mps":
            torch.mps.synchronize()
        return np.asarray(values)

    encode(texts[: batch_size * 2])  # warm-up: kernels and allocator
    seconds = []
    shape: tuple[int, ...] = ()
    for _ in range(runs):
        start = time.perf_counter()
        shape = encode(texts).shape
        seconds.append(time.perf_counter() - start)
    if shape != (len(texts), EMBED_MODEL["dimension"]):
        raise ValueError(f"unexpected embedding shape {shape}")
    median = statistics.median(seconds)
    return {
        "status": "ok",
        "device": str(model.device),
        "dtype": "float32",
        "torch_threads": torch.get_num_threads(),
        "runs_seconds": seconds,
        "median_seconds": median,
        "vectors_per_second": len(texts) / median,
        "seconds_per_vector": median / len(texts),
    }


def run_embed(args: argparse.Namespace) -> None:
    texts, sources = scifact_documents(args.documents)
    devices = {}
    for device, runs in (("mps", args.runs), ("cpu", args.cpu_runs)):
        if runs > 0:
            print(f"embedding {len(texts)} documents on {device}", flush=True)
            devices[device] = embed_device(texts, device, runs, args.batch_size)
    packages = {}
    for name in ("torch", "transformers", "sentence-transformers", "numpy"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    result = envelope(
        "speed-embedding",
        {name: {**value, "source": "huggingface"} for name, value in sources.items()},
        {
            "status": "ok",
            "model": EMBED_MODEL,
            "dataset": "BeIR/scifact corpus, first documents in lexical id order, "
            "title and text joined as benchmarks/prepare_beir.py",
            "documents": len(texts),
            "batch_size": args.batch_size,
            "packages": packages,
            "devices": devices,
        },
    )
    write_result(args.output, result)
    print(args.output)


# ---------------------------------------------------------------------------
# Measure (.venv)
# ---------------------------------------------------------------------------


def run_measure(args: argparse.Namespace) -> None:
    import semq

    dims = tuple(args.dims)
    native = Path(os.environ.get("SEMQ_LIBRARY_PATH", ""))
    inputs: dict[str, Any] = {}
    if native.is_file():
        inputs["native_library"] = {
            "sha256": sha256(native),
            "source": (
                str(native.resolve().relative_to(ROOT))
                if native.resolve().is_relative_to(ROOT)
                else str(native.resolve())
            ),
        }
    embedding = None
    if args.embedding is not None:
        full = json.loads(args.embedding.read_text())
        embedding = full["results"]
        inputs["embedding_throughput"] = {
            "sha256": sha256(args.embedding),
            "source": "python -m benchmarks.speed embed (run in .venv-data)",
            "hardware": full["hardware"],
            "generated_utc": full["generated_utc"],
        }
    print("SEMQ encode/decode", flush=True)
    semq_results, default_backend = semq_speed(dims, args.rows, args.runs)
    print("numpy baselines", flush=True)
    baselines = numpy_speed(dims, args.rows, args.runs)
    print("C microbenchmark", flush=True)
    c_dim = OVERHEAD_DIM if OVERHEAD_DIM in dims else dims[0]
    c_results = c_bench(args.bench_binary, c_dim, args.rows, args.runs)
    results = {
        "method": {
            "rows": args.rows,
            "runs": args.runs,
            "statistic": "median wall-clock seconds after one warm-up, single process",
            "inputs": "random unit-norm float32 rows from numpy default_rng(seed, dim)",
            "seed": SEED,
            "encode": "Codec.encode(ids=np.arange(rows, dtype=np.uint64), vectors)",
            "decode": "Codec.decode(encoding)",
            "backends": "forced with SEMQ_FORCE_BACKEND before creating the Codec; "
            "reported only when codec.backend confirms the kernel; all reported "
            "row bytes and content digests must equal scalar for the same input",
        },
        "python": platform.python_version(),
        "numpy": np.__version__,
        "semq_version": getattr(semq, "__version__", "unknown"),
        "default_backend": default_backend,
        "semq": semq_results,
        "numpy_baselines": {
            "definitions": BASELINE_DEFINITIONS,
            "dims": baselines,
        },
        "c_microbenchmark": c_results,
        "embedding": embedding
        or {
            "status": "not_run",
            "reason": "no embedding throughput file; pass --embedding",
        },
        "overhead": overhead(semq_results, embedding),
    }
    write_result(args.output, envelope("speed", inputs, results))
    print(args.output)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    embed = commands.add_parser("embed", help="embedding throughput (.venv-data)")
    embed.add_argument("--output", type=Path, required=True)
    embed.add_argument("--documents", type=int, default=EMBED_DOCUMENTS)
    embed.add_argument("--batch-size", type=int, default=EMBED_BATCH)
    embed.add_argument("--runs", type=int, default=3, help="MPS runs; 0 skips")
    embed.add_argument("--cpu-runs", type=int, default=1, help="CPU runs; 0 skips")
    measure = commands.add_parser("measure", help="SEMQ, numpy and C (.venv)")
    measure.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    measure.add_argument("--embedding", type=Path)
    measure.add_argument("--bench-binary", type=Path, default=DEFAULT_BENCH)
    measure.add_argument("--rows", type=int, default=ROWS)
    measure.add_argument("--runs", type=int, default=RUNS)
    measure.add_argument("--dims", type=int, nargs="+", default=list(DIMS))
    args = parser.parse_args(argv)
    if args.command == "embed":
        run_embed(args)
    else:
        run_measure(args)


if __name__ == "__main__":
    main()
