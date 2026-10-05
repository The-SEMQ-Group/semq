# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Bytes per vector and storage at scale for SEMQ and common vector formats.

Usage: python -m benchmarks.size [--output PATH] [--check]

Every baseline size is computed from the format's definition (bits per value
plus its scale overhead). SEMQ payload sizes come from CodecConfig, and the
.semq file cost comes from real files written by the SDK. The result is
deterministic; --check regenerates it in memory and fails when the committed
file differs in "results".
"""

from __future__ import annotations

import argparse
import io
import json
import os
import platform
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "docs/assets/benchmarks/summary"
DEFAULT_OUTPUT = RESULTS / "size.json"

DIMS = (384, 768, 1024)
VECTORS_AT_SCALE = 100_000_000
FILE_ROWS = 1_000_000
ID_BYTES = 8
GB = 10**9

# (id, constructor, parameter); the five configurations shown on the page.
SEMQ_CONFIGS: tuple[tuple[str, str, int], ...] = (
    ("semq_quant2", "quant", 2),
    ("semq_quant4", "quant", 4),
    ("semq_quant8", "quant", 8),
    ("semq_phase16", "phase", 16),
    ("semq_orbit50", "orbit", 50),
)


# ---------------------------------------------------------------------------
# Shared result envelope (also used by benchmarks.speed and benchmarks.scale)
# ---------------------------------------------------------------------------


def _git(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(ROOT), *args], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def hardware() -> dict[str, Any]:
    machine = platform.processor() or platform.machine()
    if sys.platform == "darwin":
        try:
            machine = subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            if platform.machine() == "arm64":
                try:
                    overview = subprocess.check_output(
                        ["system_profiler", "SPHardwareDataType"],
                        text=True,
                        stderr=subprocess.DEVNULL,
                    )
                    chip = re.search(r"^\s*Chip:\s*(.+)$", overview, re.MULTILINE)
                    if chip is not None:
                        machine = chip.group(1)
                except (OSError, subprocess.CalledProcessError):
                    pass
    result: dict[str, Any] = {
        "machine": machine,
        "os": platform.platform(),
        "arch": platform.machine(),
        "cpu_threads": os.cpu_count(),
    }
    if sys.platform == "darwin" and platform.machine() == "arm64":
        result["gpu"] = f"{machine} (MPS)"
    return result


def envelope(metric: str, inputs: dict, results: dict) -> dict[str, Any]:
    return {
        "schema": f"semq-bench/{metric}/1",
        "sdk_commit": _git("rev-parse", "HEAD"),
        "working_tree_dirty": _git("status", "--porcelain") not in ("", "unknown"),
        "hardware": hardware(),
        "generated_utc": datetime.now(UTC).isoformat(),
        "inputs": inputs,
        "results": results,
    }


def dumps(value: dict) -> str:
    return json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"


def write_result(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(value))


def check_result(path: Path, results: dict) -> None:
    committed = json.loads(path.read_text())["results"]
    fresh = json.loads(dumps({"results": results}))["results"]
    if committed != fresh:
        raise SystemExit(f"{path} is stale; run python -m benchmarks.size")


# ---------------------------------------------------------------------------
# Format definitions
# ---------------------------------------------------------------------------


def _row(
    bits_per_value: int,
    dims: int,
    *,
    per_row_bytes: int = 0,
    block: int | None = None,
    block_scale_bytes: int = 0,
    per_tensor_bytes: int = 0,
    model_bytes: int = 0,
) -> dict[str, int]:
    """Payload bytes of one vector, and the fixed bytes shared by the corpus."""
    bits = bits_per_value * dims
    if bits % 8:
        raise ValueError("payload is not a whole number of bytes")
    payload = bits // 8 + per_row_bytes
    if block is not None:
        if dims % block:
            raise ValueError("dimension is not a multiple of the block size")
        payload += (dims // block) * block_scale_bytes
    return {
        "bytes_per_vector": payload,
        "fixed_bytes": per_tensor_bytes + model_bytes,
    }


BASELINES: dict[str, dict[str, str]] = {
    "fp32": {"label": "FP32", "definition": "32-bit IEEE float per value"},
    "fp16": {"label": "FP16", "definition": "16-bit IEEE float per value"},
    "bf16": {"label": "BF16", "definition": "bfloat16 per value"},
    "int8": {
        "label": "int8",
        "definition": "8-bit signed level per value plus one FP32 scale per row "
        "(per-row absmax, as benchmarks/codecs.py)",
    },
    "binary": {
        "label": "binary (packed)",
        "definition": "1 sign bit per value, packed 8 per byte",
    },
    "fp8_e4m3": {
        "label": "FP8 E4M3",
        "definition": "1 byte per value plus one FP32 scale per tensor",
    },
    "fp8_e5m2": {
        "label": "FP8 E5M2",
        "definition": "1 byte per value plus one FP32 scale per tensor",
    },
    "int4_block32": {
        "label": "INT4 (block 32)",
        "definition": "4 bits per value plus one FP16 scale per block of 32",
    },
    "mxfp4": {
        "label": "MXFP4",
        "definition": "4-bit E2M1 per value plus one E8M0 scale byte per block of 32",
    },
    "mxfp8": {
        "label": "MXFP8",
        "definition": "8-bit float per value plus one E8M0 scale byte per block of 32",
    },
    "nvfp4": {
        "label": "NVFP4",
        "definition": "4-bit E2M1 per value plus one E4M3 scale byte per block of 16 "
        "and one FP32 scale per tensor",
    },
    "matryoshka256_fp32": {
        "label": "Matryoshka 256 dims, FP32",
        "definition": "first 256 dimensions kept, 32-bit float per value "
        "(needs a Matryoshka-trained model)",
    },
    "matryoshka256_int8": {
        "label": "Matryoshka 256 dims, int8",
        "definition": "first 256 dimensions kept, int8 per value plus one FP32 "
        "scale per row (needs a Matryoshka-trained model)",
    },
    "faiss_pq": {
        "label": "FAISS PQ (same bytes as semq_quant2)",
        "definition": "M = dim/4 subquantizers of 8 bits each (one byte per "
        "4 dimensions); fixed cost is the trained codebook of 256 centroids "
        "per subquantizer in FP32",
    },
}


def baseline_sizes(dims: int) -> dict[str, dict[str, int]]:
    rows = {
        "fp32": _row(32, dims),
        "fp16": _row(16, dims),
        "bf16": _row(16, dims),
        "int8": _row(8, dims, per_row_bytes=4),
        "binary": _row(1, dims),
        "fp8_e4m3": _row(8, dims, per_tensor_bytes=4),
        "fp8_e5m2": _row(8, dims, per_tensor_bytes=4),
        "int4_block32": _row(4, dims, block=32, block_scale_bytes=2),
        "mxfp4": _row(4, dims, block=32, block_scale_bytes=1),
        "mxfp8": _row(8, dims, block=32, block_scale_bytes=1),
        "nvfp4": _row(4, dims, block=16, block_scale_bytes=1, per_tensor_bytes=4),
    }
    if dims >= 768:  # Matryoshka truncation is shown for the larger models
        rows["matryoshka256_fp32"] = _row(32, 256)
        rows["matryoshka256_int8"] = _row(8, 256, per_row_bytes=4)
    # PQ with 8-bit codes: one byte per subquantizer, M = dim / 4 so that the
    # payload matches semq_quant2 (2 bits per dimension). Codebook: 256
    # centroids of dim/M values each, per subquantizer = 256 * dim FP32 values.
    subquantizers = dims // 4
    rows["faiss_pq"] = {
        "bytes_per_vector": subquantizers,
        "fixed_bytes": 256 * dims * 4,
    }
    return rows


def semq_file_overhead(config: Any, rows: int) -> int:
    """Bytes a real .semq file of `rows` u64-id rows spends beyond the rows."""
    import numpy as np

    from semq import Codec

    rng = np.random.default_rng(20260928)
    vectors = rng.standard_normal((rows, config.dim)).astype(np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    state = Codec(config).encode(ids=np.arange(rows, dtype=np.uint64), vectors=vectors)
    stream = io.BytesIO()
    state.save(stream)
    return len(stream.getvalue()) - rows * (config.bytes_per_vector + ID_BYTES)


def semq_sizes(dims: int) -> dict[str, dict[str, int]]:
    from semq import CodecConfig

    result = {}
    for name, ctor, parameter in SEMQ_CONFIGS:
        config = getattr(CodecConfig, ctor)(dims, parameter)
        # The file layout is fixed-size sections plus one id and one packed row
        # per row (docs/reference/file-format.md). Real files of 1, 2 and 1000
        # rows confirm that the overhead does not depend on the row count.
        overheads = {semq_file_overhead(config, n) for n in (1, 2, 1000)}
        if len(overheads) != 1:
            raise ValueError(f"{name}: .semq overhead depends on row count")
        overhead = overheads.pop()
        file_bytes = overhead + FILE_ROWS * (config.bytes_per_vector + ID_BYTES)
        result[name] = {
            "bytes_per_vector": config.bytes_per_vector,
            "fixed_bytes": 0,
            "file_fixed_bytes": overhead,
            "file_bytes_1m_rows": file_bytes,
        }
    return result


def summarize(sizes: dict[str, int], dims: int) -> dict[str, Any]:
    fp32 = 4 * dims
    payload = sizes["bytes_per_vector"]
    at_scale = VECTORS_AT_SCALE * payload + sizes["fixed_bytes"]
    row: dict[str, Any] = {
        **sizes,
        "x_smaller_than_fp32": round(fp32 / payload, 4),
        "gb_100m_vectors": round(at_scale / GB, 6),
    }
    if "file_bytes_1m_rows" in sizes:
        row["file_bytes_per_row_1m_rows"] = round(
            sizes["file_bytes_1m_rows"] / FILE_ROWS, 6
        )
        row["file_gb_100m_rows"] = round(
            (sizes["file_fixed_bytes"] + VECTORS_AT_SCALE * (payload + ID_BYTES)) / GB,
            6,
        )
    return row


def compute() -> dict[str, Any]:
    by_dim = {}
    for dims in DIMS:
        sizes = {**baseline_sizes(dims), **semq_sizes(dims)}
        by_dim[str(dims)] = {name: summarize(s, dims) for name, s in sizes.items()}
    return {
        "units": {
            "bytes_per_vector": "payload bytes of one vector, excluding its id",
            "fixed_bytes": "bytes shared by the whole corpus (per-tensor scales, "
            "trained codebooks); counted once in gb_100m_vectors",
            "gb_100m_vectors": f"decimal GB (10^9 bytes) for {VECTORS_AT_SCALE:,} "
            "vectors: payload only, no ids and no container",
            "x_smaller_than_fp32": "FP32 payload bytes / this payload bytes",
            "file_bytes_1m_rows": f"size of a .semq file with {FILE_ROWS:,} rows, "
            "u64 ids (8 bytes each) and an empty manifest; a manifest adds its "
            "own bytes once",
            "file_bytes_per_row_1m_rows": "file_bytes_1m_rows / 1,000,000: "
            "bytes_per_vector + 8-byte id + amortized header and footer",
            "file_gb_100m_rows": "decimal GB of a .semq file with 100,000,000 rows",
        },
        "formats": {
            **BASELINES,
            **{
                name: {
                    "label": name,
                    "definition": f"CodecConfig.{ctor}(dim, {parameter}); size "
                    "from CodecConfig.bytes_per_vector",
                }
                for name, ctor, parameter in SEMQ_CONFIGS
            },
        },
        "vectors_at_scale": VECTORS_AT_SCALE,
        "file_rows": FILE_ROWS,
        "dims": by_dim,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    results = compute()
    if args.check:
        check_result(args.output, results)
        print(f"{args.output} is up to date")
        return
    write_result(args.output, envelope("size", {}, results))
    print(args.output)


if __name__ == "__main__":
    main()
