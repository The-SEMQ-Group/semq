# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Time, peak memory and file size of the state operations at 1M rows.

Usage: python -m benchmarks.scale [--rows 100000 1000000] [--output PATH]

Each operation runs in a fresh Python subprocess, so the peak resident set
size (resource.getrusage) of one operation does not include the others. The
vectors are random unit rows from a fixed seed, generated in chunks of
100,000 rows and never held all at once. Temporary files live in one
temporary directory that is deleted at the end. Timings are single runs,
frozen per release, on the hardware recorded in the result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import numpy as np

from .size import RESULTS, ROOT, envelope, write_result

DEFAULT_OUTPUT = RESULTS / "scale.json"
DIM = 768
BINS = 4
CONFIG_ID = "semq_quant4"
ROWS = (100_000, 1_000_000)
CHUNK = 100_000
PARTS = 10
NULLS = 3
SEED = 20260928
# The candidate changes 1 row in CHANGE_STRIDE by a large step; each null
# rebuild moves 1 row in NULL_STRIDE by a small step (rebuild noise).
CHANGE_STRIDE = 100
CHANGE_STEP = 0.5
NULL_STRIDE = 1000
NULL_STEP = 0.01

OPERATIONS = (
    "encode",
    "prepare",
    "save",
    "load",
    "diff",
    "concat",
    "floor",
    "gate",
    "npy",
)


# ---------------------------------------------------------------------------
# Deterministic inputs
# ---------------------------------------------------------------------------


def _normalize(values: np.ndarray, block: int = 8192) -> np.ndarray:
    """Unit rows in place, a block at a time so no full-size temporary exists."""
    for start in range(0, len(values), block):
        rows = values[start : start + block]
        rows /= np.linalg.norm(rows, axis=1, keepdims=True)
    return values


def chunk(index: int, rows: int, dim: int = DIM) -> np.ndarray:
    """Rows [index * CHUNK, index * CHUNK + rows) of the base corpus."""
    rng = np.random.default_rng([SEED, dim, index])
    return _normalize(rng.standard_normal((rows, dim), dtype=np.float32))


def variant(
    values: np.ndarray, start: int, stride: int, offset: int, step: float, salt: int
) -> np.ndarray:
    """Move the rows whose id % stride == offset by `step` x a random unit row."""
    ids = np.arange(start, start + len(values))
    picked = np.flatnonzero(ids % stride == offset)
    if len(picked):
        rng = np.random.default_rng([SEED, values.shape[1], start, salt])
        noise = _normalize(
            rng.standard_normal((len(picked), values.shape[1]), dtype=np.float32)
        )
        values = values.copy()
        values[picked] = _normalize(values[picked] + np.float32(step) * noise)
    return values


def slices(rows: int, size: int) -> Iterator[tuple[int, int]]:
    for start in range(0, rows, size):
        yield start, min(size, rows - start)


def vectors(start: int, count: int) -> np.ndarray:
    """Base rows [start, start + count) within one chunk."""
    index, offset = divmod(start, CHUNK)
    if offset + count > CHUNK:
        raise ValueError("a slice must stay within one chunk")
    return chunk(index, offset + count)[offset:]


def _codec() -> Any:
    from semq import Codec, CodecConfig

    return Codec(CodecConfig.quant(DIM, BINS))


def _ids(start: int, count: int) -> np.ndarray:
    return np.arange(start, start + count, dtype=np.uint64)


def encode_rows(
    codec: Any, rows: int, transform: Callable[[np.ndarray, int], np.ndarray]
) -> Any:
    """Encode in chunks of CHUNK rows, then one concat; untimed helper."""
    parts = [
        codec.encode(ids=_ids(s, n), vectors=transform(chunk(s // CHUNK, n), s))
        for s, n in slices(rows, CHUNK)
    ]
    return parts[0] if len(parts) == 1 else parts[0].concat(*parts[1:])


# ---------------------------------------------------------------------------
# Operations (each one runs in its own subprocess)
# ---------------------------------------------------------------------------


def peak_rss_bytes() -> int:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes, Linux kibibytes.
    return int(peak if sys.platform == "darwin" else peak * 1024)


def _timed(fn: Callable[[], Any]) -> tuple[Any, dict[str, Any]]:
    before = peak_rss_bytes()
    start = time.perf_counter()
    result = fn()
    seconds = time.perf_counter() - start
    return result, {
        "seconds": seconds,
        "peak_rss_bytes": peak_rss_bytes(),
        "peak_rss_before_bytes": before,
    }


def op_encode(rows: int, work: Path) -> dict[str, Any]:
    codec = _codec()
    parts: list[Any] = []
    seconds = 0.0
    before = peak_rss_bytes()
    for start, count in slices(rows, CHUNK):
        values = chunk(start // CHUNK, count)
        began = time.perf_counter()
        parts.append(codec.encode(ids=_ids(start, count), vectors=values))
        seconds += time.perf_counter() - began
        del values
    began = time.perf_counter()
    state = parts[0] if len(parts) == 1 else parts[0].concat(*parts[1:])
    seconds += time.perf_counter() - began
    peak = peak_rss_bytes()
    del parts
    state.save(work / "base.semq")
    return {
        "seconds": seconds,
        "peak_rss_bytes": peak,
        "peak_rss_before_bytes": before,
        "chunks": len(list(slices(rows, CHUNK))),
        "input_chunk_bytes": min(rows, CHUNK) * DIM * 4,
        "timed": "Codec.encode per chunk plus one Encoding.concat; vector "
        "generation excluded",
    }


def op_prepare(rows: int, work: Path) -> dict[str, Any]:
    """Untimed: the candidate, the null rebuilds and the concat parts."""
    codec = _codec()
    candidate = encode_rows(
        codec,
        rows,
        lambda v, s: variant(v, s, CHANGE_STRIDE, 0, CHANGE_STEP, salt=1),
    )
    candidate.save(work / "candidate.semq")
    del candidate
    for k in range(1, NULLS + 1):

        def noise(v: np.ndarray, s: int, k: int = k) -> np.ndarray:
            return variant(v, s, NULL_STRIDE, k, NULL_STEP, salt=10 + k)

        null = encode_rows(codec, rows, noise)
        null.save(work / f"null_{k}.semq")
        del null
    per_part = rows // PARTS
    for p in range(PARTS):
        start = p * per_part
        count = rows - start if p == PARTS - 1 else per_part
        part = codec.encode(ids=_ids(start, count), vectors=vectors(start, count))
        part.save(work / f"part_{p:02d}.semq")
        del part
    return {"timed": "nothing; builds the inputs of diff, concat and floor"}


def _load(path: Path) -> Any:
    from semq import Encoding

    return Encoding.load(path)


def op_save(rows: int, work: Path) -> dict[str, Any]:
    state = _load(work / "base.semq")
    target = work / "saved.semq"
    _, timing = _timed(lambda: state.save(target))
    target.unlink()
    return {**timing, "timed": "Encoding.save to a path (atomic write with fsync)"}


def op_load(rows: int, work: Path) -> dict[str, Any]:
    state, timing = _timed(lambda: _load(work / "base.semq"))
    if len(state) != rows:
        raise ValueError("loaded row count differs")
    return {
        **timing,
        "timed": "Encoding.load from a path (file in the OS page cache)",
    }


def op_diff(rows: int, work: Path) -> dict[str, Any]:
    base, candidate = _load(work / "base.semq"), _load(work / "candidate.semq")
    diff, timing = _timed(lambda: base.diff(candidate))
    return {
        **timing,
        "changed_rows": len(diff.changed),
        "unchanged_rows": diff.n_unchanged,
        "modified_rows": len(range(0, rows, CHANGE_STRIDE)),
        "timed": "Encoding.diff against a copy with 1 row in 100 changed",
    }


def op_concat(rows: int, work: Path) -> dict[str, Any]:
    parts = [_load(work / f"part_{p:02d}.semq") for p in range(PARTS)]
    state, timing = _timed(lambda: parts[0].concat(*parts[1:]))
    if len(state) != rows:
        raise ValueError("concat row count differs")
    return {**timing, "parts": PARTS, "timed": f"Encoding.concat of {PARTS} parts"}


def op_floor(rows: int, work: Path) -> dict[str, Any]:
    from semq import Floor

    base = _load(work / "base.semq")
    diffs = [base.diff(_load(work / f"null_{k}.semq")) for k in range(1, NULLS + 1)]
    floor, timing = _timed(lambda: Floor.measure(diffs))
    return {
        **timing,
        "nulls": floor.nulls,
        "floor_changed_rows": floor.changed_rows,
        "floor_hamming": floor.hamming,
        "null_changed_rows": [len(d.changed) for d in diffs],
        "timed": f"Floor.measure over {NULLS} null diffs (diffs built untimed)",
    }


def op_gate(rows: int, work: Path) -> dict[str, Any]:
    """Measure the complete CI decision, including all file loads and null diffs."""
    from semq import Floor

    def decide() -> tuple[int, int, bool]:
        base = _load(work / "base.semq")
        null_diffs = [
            base.diff(_load(work / f"null_{k}.semq")) for k in range(1, NULLS + 1)
        ]
        floor = Floor.measure(null_diffs)
        # Each Diff retains both Encodings in C. The floor owns its measured
        # counts, so these large null states can be released before loading
        # the candidate, as they would be in a CI gate.
        del null_diffs
        candidate_diff = base.diff(_load(work / "candidate.semq"))
        return floor.nulls, len(candidate_diff.changed), candidate_diff.within(floor)

    (nulls, changed, within), timing = _timed(decide)
    return {
        **timing,
        "nulls": nulls,
        "candidate_changed_rows": changed,
        "within_floor": within,
        "timed": "load reference, three nulls and candidate; diff nulls; "
        "Floor.measure; diff candidate; Diff.within",
    }


def op_npy(rows: int, work: Path) -> dict[str, Any]:
    """Sizes of np.save files of the same vectors, written chunk by chunk."""
    sizes = {}
    for dtype in (np.float32, np.float16):
        path = work / f"vectors.{np.dtype(dtype).name}.npy"
        out = np.lib.format.open_memmap(path, mode="w+", dtype=dtype, shape=(rows, DIM))
        for start, count in slices(rows, CHUNK):
            out[start : start + count] = chunk(start // CHUNK, count)
        out.flush()
        del out
        sizes[f"npy_{np.dtype(dtype).name}_bytes"] = path.stat().st_size
        path.unlink()
    return sizes


OPS: dict[str, Callable[[int, Path], dict[str, Any]]] = {
    "encode": op_encode,
    "prepare": op_prepare,
    "save": op_save,
    "load": op_load,
    "diff": op_diff,
    "concat": op_concat,
    "floor": op_floor,
    "gate": op_gate,
    "npy": op_npy,
}


def run_op(name: str, rows: int, work: Path) -> dict[str, Any]:
    """Run one operation in a fresh interpreter and return its JSON line."""
    completed = subprocess.run(
        [sys.executable, "-m", "benchmarks.scale", "_op", name, str(rows), str(work)],
        check=True,
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        env=os.environ.copy(),
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def measure(rows: int, parent: Path | None = None) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="semq-scale-", dir=parent) as tmp:
        work = Path(tmp)
        operations = {}
        files: dict[str, Any] = {}
        for name in OPERATIONS:
            print(f"{rows} rows: {name}", file=sys.stderr, flush=True)
            result = run_op(name, rows, work)
            if name == "npy":
                files.update(result)
            elif name != "prepare":
                operations[name] = result
            if name == "encode":
                files["semq_bytes"] = (work / "base.semq").stat().st_size
    files["semq_vs_npy_float32"] = files["npy_float32_bytes"] / files["semq_bytes"]
    files["semq_vs_npy_float16"] = files["npy_float16_bytes"] / files["semq_bytes"]
    return {"operations": operations, "files": files}


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["_op"]:
        name, rows, work = argv[1], int(argv[2]), Path(argv[3])
        print(json.dumps(OPS[name](rows, work), allow_nan=False))
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--rows", type=int, nargs="+", default=list(ROWS))
    parser.add_argument(
        "--workdir", type=Path, help="parent of the temporary directory"
    )
    args = parser.parse_args(argv)
    results: dict[str, Any] = {
        "config": CONFIG_ID,
        "codec": f"CodecConfig.quant({DIM}, {BINS})",
        "dim": DIM,
        "method": {
            "process": "one fresh Python subprocess per operation; peak_rss_bytes "
            "is that process's ru_maxrss after the operation, "
            "peak_rss_before_bytes the same just before it (after setup); the "
            "encode peak includes one float32 input chunk",
            "timing": "single wall-clock run per operation",
            "inputs": f"random unit rows, numpy default_rng([{SEED}, dim, chunk]), "
            f"generated in chunks of {CHUNK:,} rows",
            "candidate": f"1 row in {CHANGE_STRIDE} moved by {CHANGE_STEP} x a "
            "random unit row, renormalized",
            "nulls": f"{NULLS} rebuilds; null k moves rows with id % {NULL_STRIDE} "
            f"== k by {NULL_STEP} x a random unit row, renormalized",
            "concat_parts": PARTS,
            "ids": "u64, 0..rows-1; empty manifest",
        },
        "rows": {},
    }
    for rows in args.rows:
        results["rows"][str(rows)] = measure(rows, args.workdir)
    inputs: dict[str, Any] = {}
    native = Path(os.environ.get("SEMQ_LIBRARY_PATH", ""))
    if native.is_file():
        inputs["native_library"] = {
            "sha256": hashlib.sha256(native.read_bytes()).hexdigest(),
            "source": (
                str(native.resolve().relative_to(ROOT))
                if native.resolve().is_relative_to(ROOT)
                else str(native.resolve())
            ),
        }
    write_result(args.output, envelope("scale", inputs, results))
    print(args.output)


if __name__ == "__main__":
    main()
