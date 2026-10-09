# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Floor power: how often does the gate reject an unchanged rebuild, and how
often does it catch a real fault?

A pool of null rebuilds of SciFact varies only the device, the batch size
and the input order. Each draw holds out one null, measures a floor from
``N`` of the others, and judges the held-out null (a false alarm if it
fails) and the same null with one fault applied (a detection if it fails).
SEMQ verdicts come from the SDK; float checks are computed on the same
vectors. Two pools: ``real``, the rebuilds as embedded, and ``varying``, a
synthetic pool that adds independent Gaussian noise to every rebuild.

* ``python -m benchmarks.floor_power --embed`` (in ``.venv-data``) embeds the
  reference on CPU, null rebuilds on the accelerator (MPS, else CUDA) and on
  CPU, and fault texts in the same session as each run. Without an
  accelerator only the CPU runs are embedded, and ``pool.json`` says so.
* ``python -m benchmarks.floor_power`` (in ``.venv``) writes the result file.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np

from . import rebuild

CACHE = Path.home() / ".cache" / "semq-benchmarks" / "floor-power"
OUTPUT = (
    rebuild.ROOT / "docs" / "assets" / "benchmarks" / "summary" / "floor-power.json"
)
CONFIG = "semq_quant4"
REFERENCE = "ref_cpu_b32_o0"

# The pool: one CPU reference, null rebuilds on the accelerator for every
# batch size and input order below, and CPU null rebuilds in a shuffled order.
ACCELERATOR_BATCHES = (16, 24, 32, 48, 64, 96, 128, 192)
ACCELERATOR_ORDERS = (0, 1, 2)
CPU_BATCHES = (8, 16, 64, 256)

# Fault texts: 50 documents, each truncated and with words substituted.
# Embedded in the same session as every run; the evaluation uses a subset.
FAULT_DOCS = 50
EMBED_TRUNCATE = (0.02, 0.05, 0.10, 0.25, 0.50)
EMBED_SUBSTITUTE = (1, 3, 10)

DRAWS = 2000
NULL_COUNTS = (3, 5, 10, 20)
DETECTION_N = 20
VARYING_EXTRA_N = 39

# The synthetic pool: null i is accelerator null i mod 24 plus N(0, SIGMA)
# per coordinate from np.random.default_rng(VARYING_SEED + i), renormalized.
VARYING_NULLS = 40
VARYING_SIGMA = 4.5e-6
VARYING_SEED = 10_000

REPLACE_K = (1, 2, 10)
TRUNCATE_F = (0.02, 0.10, 0.50)
SUBSTITUTE_M = (1, 3)
DIFFUSE_C = (1, 4)
SPARSE = ((0.01, 1e-4), (0.1, 1e-4), (0.01, 1e-3))

ALLCLOSE = {"rtol": 1e-5, "atol": 1e-8}
BF16_MANTISSA_BITS = 7

DETECTORS = {
    "floor_within": "SEMQ: Diff.within(floor)",
    "floor_per_row": "SEMQ: Diff.evaluate(floor, per_row=True).passed",
    "max_abs_calibrated": (
        "largest absolute coordinate difference above the largest seen on the "
        "floor's nulls"
    ),
    "cosine_calibrated": (
        "largest per-row 1 - cosine above the largest seen on the floor's nulls"
    ),
    "fp32_hash": "SHA-256 of the float32 bytes differs",
    "allclose_default": "np.allclose fails (rtol=1e-05, atol=1e-08)",
    "bf16_fixed": (
        "any coordinate differs by more than one bfloat16 spacing of the "
        "reference value"
    ),
}


def embed_rng(*parts: Any) -> np.random.Generator:
    """Seeds of the embedded pool: fault documents, substitutions, input orders."""
    key = json.dumps(["floorpow", *parts]).encode()
    return np.random.default_rng(
        int.from_bytes(hashlib.sha256(key).digest()[:8], "big")
    )


def draw_rng(*parts: Any) -> np.random.Generator:
    """Seeds of the evaluation draws."""
    key = json.dumps(["floor-power", *parts]).encode()
    return np.random.default_rng(
        int.from_bytes(hashlib.sha256(key).digest()[:8], "big")
    )


def run_specs(accelerator: str | None) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = [
        {"name": REFERENCE, "device": "cpu", "batch_size": 32, "order": 0}
    ]
    if accelerator is not None:
        specs += [
            {
                "name": f"null_{accelerator}_b{b}_o{o}",
                "device": accelerator,
                "batch_size": b,
                "order": o,
            }
            for b in ACCELERATOR_BATCHES
            for o in ACCELERATOR_ORDERS
        ]
    specs += [
        {"name": f"null_cpu_b{b}_o1", "device": "cpu", "batch_size": b, "order": 1}
        for b in CPU_BATCHES
    ]
    return specs


def fault_texts(texts: list[str]) -> tuple[list[str], list[dict[str, Any]]]:
    """Truncations and word substitutions of FAULT_DOCS documents."""
    docs = sorted(
        embed_rng("fault-docs").choice(len(texts), FAULT_DOCS, replace=False).tolist()
    )
    vocab = sorted({w for t in texts for w in t.split()})
    out, meta = [], []
    for d in docs:
        words = texts[d].split()
        for f in EMBED_TRUNCATE:
            keep = max(1, round(len(words) * (1 - f)))
            out.append(" ".join(words[:keep]))
            meta.append({"doc": d, "family": "truncate", "level": f})
        for m in EMBED_SUBSTITUTE:
            r = embed_rng("subst", d, m)
            w = list(words)
            for pos in r.choice(len(w), min(m, len(w)), replace=False):
                w[pos] = vocab[r.integers(len(vocab))]
            out.append(" ".join(w))
            meta.append({"doc": d, "family": "substitute", "level": m})
    return out, meta


# -- embedding (runs in .venv-data) -------------------------------------------


def accelerator_available() -> str | None:
    import torch

    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return None


def embed_pool(cache: Path, offline: bool, only: list[str] | None) -> None:
    import torch
    from sentence_transformers import SentenceTransformer

    torch.set_num_threads(rebuild.TORCH_THREADS)
    cache.mkdir(parents=True, exist_ok=True)
    corpus = rebuild.load_corpus(offline)
    texts = corpus["text"]
    ftexts, fmeta = fault_texts(texts)
    (cache / "faults.json").write_text(json.dumps(fmeta))
    accelerator = accelerator_available()
    specs = run_specs(accelerator)
    meta = {
        "corpus": {
            "dataset": "BeIR/scifact",
            "rows": len(corpus["ids"]),
            "source_files": corpus["source_files"],
            "ids_sha256": hashlib.sha256("\n".join(corpus["ids"]).encode()).hexdigest(),
        },
        "accelerator": accelerator,
        "model": rebuild.REFERENCE_MODEL,
        "settings": {
            "dtype": "float32",
            "max_length": 512,
            "normalize": True,
            "prefix": rebuild.PREFIX,
            "torch_threads": rebuild.TORCH_THREADS,
        },
        "versions": {
            name: importlib.metadata.version(name)
            for name in ("torch", "sentence-transformers", "transformers")
        },
        "runs": {s["name"]: {k: v for k, v in s.items() if k != "name"} for s in specs},
        "fault_texts": len(ftexts),
    }
    (cache / "pool.json").write_text(rebuild.dump(meta))
    if accelerator is None:
        print("no accelerator: embedding the CPU runs only", flush=True)
    for spec in specs:
        path = cache / f"{spec['name']}.npz"
        if (only and spec["name"] not in only) or (not only and path.exists()):
            continue
        model = SentenceTransformer(
            rebuild.REFERENCE_MODEL["repo"],
            revision=rebuild.REFERENCE_MODEL["revision"],
            device=spec["device"],
            local_files_only=offline,
            trust_remote_code=False,
        )
        model.float()
        model.max_seq_length = 512
        n = len(texts)
        perm = (
            np.arange(n)
            if spec["order"] == 0
            else embed_rng("order", spec["order"]).permutation(n)
        )
        started = time.perf_counter()
        options = {
            "prompt": rebuild.PREFIX,
            "batch_size": spec["batch_size"],
            "normalize_embeddings": True,
            "convert_to_numpy": True,
            "show_progress_bar": False,
        }
        values = model.encode([texts[i] for i in perm], **options)
        rows = np.empty_like(values)
        rows[perm] = values
        faults = model.encode(ftexts, **options)
        np.savez(
            path,
            rows=np.ascontiguousarray(rows, np.float32),
            faults=np.ascontiguousarray(faults, np.float32),
        )
        print(
            f"{spec['name']}: {time.perf_counter() - started:.1f} s",
            flush=True,
        )
        del model
        if spec["device"] == "mps":
            torch.mps.empty_cache()


# -- statistics ---------------------------------------------------------------


def bf16_spacing(values: np.ndarray) -> np.ndarray:
    """The gap between adjacent bfloat16 numbers at each value's magnitude."""
    a = np.abs(values.astype(np.float64))
    a = np.where(a == 0, np.finfo(np.float32).tiny, a)
    return np.asarray(2.0 ** (np.floor(np.log2(a)) - BF16_MANTISSA_BITS))


def binomial_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k) for X ~ Binomial(n, p)."""
    if k < 0:
        return 0.0
    if k >= n or p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 0.0
    logs = [
        math.lgamma(n + 1)
        - math.lgamma(j + 1)
        - math.lgamma(n - j + 1)
        + j * math.log(p)
        + (n - j) * math.log1p(-p)
        for j in range(k + 1)
    ]
    top = max(logs)
    return min(1.0, math.exp(top) * sum(math.exp(v - top) for v in logs))


def clopper_pearson(k: int, n: int, level: float = 0.95) -> tuple[float, float]:
    """Exact two-sided interval for a binomial rate, by bisection on the CDF."""
    tail = (1.0 - level) / 2

    def solve(f: Any) -> float:
        lo, hi = 0.0, 1.0
        for _ in range(100):
            mid = (lo + hi) / 2
            if f(mid):
                hi = mid
            else:
                lo = mid
        return (lo + hi) / 2

    lower = 0.0 if k == 0 else solve(lambda p: 1 - binomial_cdf(k - 1, n, p) >= tail)
    upper = 1.0 if k == n else solve(lambda p: binomial_cdf(k, n, p) <= tail)
    return lower, upper


def rate(count: int, draws: int) -> dict[str, Any]:
    lo, hi = clopper_pearson(count, draws)
    return {
        "count": count,
        "draws": draws,
        "rate": count / draws,
        "ci95": [round(lo, 6), round(hi, 6)],
    }


def unit_rows(x: np.ndarray) -> np.ndarray:
    wide = x.astype(np.float64)
    return (wide / np.linalg.norm(wide, axis=1, keepdims=True)).astype(np.float32)


class Rows:
    """Per-row float statistics of a candidate against the reference."""

    __slots__ = ("allclose", "bf16", "cosdev", "equal", "maxabs")

    allclose: np.ndarray
    bf16: np.ndarray
    cosdev: np.ndarray
    equal: np.ndarray
    maxabs: np.ndarray

    def __init__(self, x: np.ndarray, ref: np.ndarray, spacing: np.ndarray) -> None:
        d = np.abs(x.astype(np.float64) - ref.astype(np.float64))
        self.maxabs = d.max(axis=1)
        self.cosdev = 1.0 - rebuild.row_cosines(ref, x)
        tol = ALLCLOSE["atol"] + ALLCLOSE["rtol"] * np.abs(ref.astype(np.float64))
        self.allclose = np.asarray((d <= tol).all(axis=1))
        self.bf16 = np.asarray((d > spacing).any(axis=1))
        self.equal = np.asarray((x == ref).all(axis=1))

    def replaced(self, rows: np.ndarray, new: Rows) -> Rows:
        out = Rows.__new__(Rows)
        for name in Rows.__slots__:
            values = getattr(self, name).copy()
            values[rows] = getattr(new, name)
            setattr(out, name, values)
        return out

    def summary(self) -> dict[str, Any]:
        return {
            "max_abs": float(self.maxabs.max()),
            "cosine_max": float(self.cosdev.max()),
            "allclose": bool(self.allclose.all()),
            "bf16_exceeded": bool(self.bf16.any()),
            "bytes_equal": bool(self.equal.all()),
        }


def float_flags(cand: dict[str, Any], nulls: list[dict[str, Any]]) -> dict[str, bool]:
    """True = flagged as changed. Calibrated checks use the floor's nulls."""
    return {
        "max_abs_calibrated": cand["max_abs"] > max(n["max_abs"] for n in nulls),
        "cosine_calibrated": cand["cosine_max"] > max(n["cosine_max"] for n in nulls),
        "fp32_hash": not cand["bytes_equal"],
        "allclose_default": not cand["allclose"],
        "bf16_fixed": cand["bf16_exceeded"],
    }


def semq_flags(diff: Any, floor: Any) -> dict[str, bool]:
    return {
        "floor_within": not diff.within(floor),
        "floor_per_row": not diff.evaluate(floor, per_row=True).passed,
    }


# -- pools --------------------------------------------------------------------


def load_pool(cache: Path) -> dict[str, Any]:
    meta = json.loads((cache / "pool.json").read_text())
    runs = {name: dict(np.load(cache / f"{name}.npz").items()) for name in meta["runs"]}
    return {
        "meta": meta,
        "runs": runs,
        "faults": json.loads((cache / "faults.json").read_text()),
    }


def varying_pool(
    runs: dict[str, dict[str, np.ndarray]], bases: list[str]
) -> dict[str, dict[str, np.ndarray]]:
    out = {}
    for i in range(VARYING_NULLS):
        base = runs[bases[i % len(bases)]]
        noise = np.random.default_rng(VARYING_SEED + i)
        out[f"varying_{i:02d}"] = {
            "rows": unit_rows(
                base["rows"] + VARYING_SIGMA * noise.standard_normal(base["rows"].shape)
            ),
            "faults": unit_rows(
                base["faults"]
                + VARYING_SIGMA * noise.standard_normal(base["faults"].shape)
            ),
        }
    return out


def null_scale(arrays: list[np.ndarray]) -> float:
    """Median over pairs of nulls of the std of their coordinate differences."""
    stds = [
        float(np.std(a - b))
        for i, a in enumerate(arrays)
        for b in arrays[i + 1 :]
        if not np.array_equal(a, b)
    ]
    return float(np.median(stds)) if stds else 0.0


def fault_specs() -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}
    for k in REPLACE_K:
        specs[f"replace_{k}"] = {"family": "replace", "documents": k}
    for f in TRUNCATE_F:
        specs[f"truncate_{f:g}"] = {"family": "truncate", "documents": 1, "cut": f}
    for m in SUBSTITUTE_M:
        specs[f"substitute_{m}"] = {"family": "substitute", "documents": 1, "words": m}
    for c in DIFFUSE_C:
        specs[f"diffuse_{c}"] = {"family": "diffuse", "noise_x_null_scale": c}
    for rho, eps in SPARSE:
        specs[f"sparse_{rho:g}_{eps:g}"] = {
            "family": "sparse",
            "coordinates": rho,
            "scale": eps,
        }
    return specs


def evaluate_pool(
    name: str,
    nulls: dict[str, dict[str, np.ndarray]],
    ref: np.ndarray,
    fault_meta: list[dict[str, Any]],
    devices: dict[str, str],
    draws: int,
) -> dict[str, Any]:
    from semq import Codec, Floor

    n, dim = ref.shape
    ids = np.arange(n, dtype=np.uint64)
    codec = Codec(rebuild.semq_config(CONFIG, dim))
    ref_state = codec.encode(ids=ids, vectors=ref)
    spacing = bf16_spacing(ref)
    names = sorted(nulls)
    states = {k: codec.encode(ids=ids, vectors=nulls[k]["rows"]) for k in names}
    diffs = {k: ref_state.diff(states[k]) for k in names}
    rows = {k: Rows(nulls[k]["rows"], ref, spacing) for k in names}
    floats = {k: rows[k].summary() for k in names}
    s_null = null_scale([nulls[k]["rows"] for k in names])

    # Regime: distinct float arrays and SEMQ states across the pool.
    by_state: dict[bytes, list[str]] = {}
    for k in names:
        by_state.setdefault(states[k].content_digest, []).append(k)
    whole = Floor.measure(diffs.values(), per_row=True)
    state_rows = []
    for digest, members in sorted(
        by_state.items(), key=lambda kv: (-len(kv[1]), len(diffs[kv[1][0]].changed))
    ):
        changed = diffs[members[0]].changed
        state_rows.append(
            {
                "nulls": len(members),
                "devices": sorted({devices[k] for k in members}),
                "equals_reference": digest == ref_state.content_digest,
                "rows_changed": len(changed),
                "max_hamming": max((h for _, h in changed), default=0),
            }
        )
    regime = {
        "nulls": len(names),
        "float_arrays_equal_to_reference": sum(floats[k]["bytes_equal"] for k in names),
        "distinct_float_arrays": len(
            {hashlib.sha256(nulls[k]["rows"].tobytes()).digest() for k in names}
        ),
        "distinct_states": whole.distinct_nulls,
        "distinct_states_including_reference": len(
            set(by_state) | {ref_state.content_digest}
        ),
        "states": state_rows,
        "null_scale": s_null,
    }

    fault_index = {
        (m["doc"], m["family"], m["level"]): i for i, m in enumerate(fault_meta)
    }
    fault_docs = np.array(sorted({m["doc"] for m in fault_meta}))
    others = np.setdiff1d(np.arange(n), fault_docs)
    specs = fault_specs()
    counts = [N for N in NULL_COUNTS if len(names) > N]
    if name == "varying":
        counts.append(VARYING_EXTRA_N)
    detect_at = [N for N in (DETECTION_N, VARYING_EXTRA_N) if N in counts]
    detectors = list(DETECTORS)
    false_alarms = {N: dict.fromkeys(detectors, 0) for N in counts}
    detected = {N: {f: dict.fromkeys(detectors, 0) for f in specs} for N in detect_at}
    sizes: dict[str, list[float]] = {f: [] for f in specs}

    def candidates(held: str, r: np.random.Generator) -> dict[str, tuple]:
        x = nulls[held]["rows"]
        fv = nulls[held]["faults"]
        order = r.permutation(fault_docs)
        out: dict[str, tuple] = {}

        def row_fault(key: str, chosen: np.ndarray, vecs: np.ndarray) -> None:
            y = x.copy()
            y[chosen] = vecs
            stats = rows[held].replaced(
                chosen, Rows(vecs, ref[chosen], spacing[chosen])
            )
            size = 1.0 - rebuild.row_cosines(x[chosen], vecs)
            out[key] = (y, stats.summary(), float(np.median(size)))

        for k in REPLACE_K:
            chosen = np.sort(order[:k])
            row_fault(f"replace_{k}", chosen, x[r.choice(others, k, replace=False)])
        doc = order[:1]
        for f in TRUNCATE_F:
            vec = fv[[fault_index[(int(doc[0]), "truncate", f)]]]
            row_fault(f"truncate_{f:g}", doc, vec)
        for m in SUBSTITUTE_M:
            vec = fv[[fault_index[(int(doc[0]), "substitute", m)]]]
            row_fault(f"substitute_{m}", doc, vec)

        def dense_fault(key: str, y: np.ndarray) -> None:
            size = 1.0 - rebuild.row_cosines(x, y)
            out[key] = (y, Rows(y, ref, spacing).summary(), float(np.median(size)))

        for c in DIFFUSE_C:
            noise = c * s_null * r.standard_normal(x.shape)
            dense_fault(f"diffuse_{c}", unit_rows(x + noise))
        for rho, eps in SPARSE:
            cols = r.choice(dim, max(1, round(rho * dim)), replace=False)
            y = x.astype(np.float64)
            y[:, cols] *= 1 + eps
            dense_fault(f"sparse_{rho:g}_{eps:g}", unit_rows(y))
        return out

    for i in range(draws):
        r = draw_rng(name, i)
        order = [names[j] for j in r.permutation(len(names))]
        held, rest = order[0], order[1:]
        floors = {
            N: Floor.measure([diffs[k] for k in rest[:N]], per_row=True) for N in counts
        }
        for N in counts:
            flags = {
                **semq_flags(diffs[held], floors[N]),
                **float_flags(floats[held], [floats[k] for k in rest[:N]]),
            }
            for det, flag in flags.items():
                false_alarms[N][det] += flag
        for key, (y, summary, size) in candidates(held, r).items():
            sizes[key].append(size)
            diff = ref_state.diff(codec.encode(ids=ids, vectors=y))
            for N in detect_at:
                flags = {
                    **semq_flags(diff, floors[N]),
                    **float_flags(summary, [floats[k] for k in rest[:N]]),
                }
                for det, flag in flags.items():
                    detected[N][key][det] += flag

    return {
        "nulls": names,
        "regime": regime,
        "false_alarms": {
            str(N): {det: rate(c, draws) for det, c in per.items()}
            for N, per in false_alarms.items()
        },
        "false_alarm_bounds": {
            str(N): {"floor_within": 2 / (N + 1), "floor_per_row": 3 / (N + 1)}
            for N in counts
        },
        "detection": {
            str(N): {
                key: {
                    **specs[key],
                    "size_median_1_minus_cos": float(np.median(sizes[key])),
                    "detectors": {det: rate(c, draws) for det, c in per.items()},
                }
                for key, per in faults.items()
            }
            for N, faults in detected.items()
        },
    }


def evaluate(cache: Path, draws: int) -> tuple[dict[str, Any], dict[str, Any]]:
    pool = load_pool(cache)
    meta, runs = pool["meta"], pool["runs"]
    ref = runs[REFERENCE]["rows"]
    real = {k: v for k, v in runs.items() if k != REFERENCE}
    devices = {k: meta["runs"][k]["device"] for k in real}
    accelerated = sorted(k for k in real if devices[k] != "cpu")
    bases = accelerated or sorted(real)
    varying = varying_pool(runs, bases)
    pools = {
        "real": evaluate_pool("real", real, ref, pool["faults"], devices, draws),
        "varying": evaluate_pool(
            "varying",
            varying,
            ref,
            pool["faults"],
            {f"varying_{i:02d}": "synthetic" for i in range(VARYING_NULLS)},
            draws,
        ),
    }
    pools["real"]["synthetic"] = False
    pools["varying"]["synthetic"] = {
        "description": (
            "each null is an accelerator null of the real pool, taken in turn, "
            "plus independent Gaussian noise on every coordinate of its rows and "
            "fault vectors, renormalized; it models a rebuild whose noise varies "
            "from run to run"
        ),
        "bases": bases,
        "sigma": VARYING_SIGMA,
        "seeds": f"np.random.default_rng({VARYING_SEED} + i) for null i",
    }
    results = {
        "question": (
            "How often does the floor reject an unchanged rebuild, and how often "
            "does it catch a real fault, next to float checks on the same vectors?"
        ),
        "corpus": meta["corpus"],
        "embedding": {k: meta[k] for k in ("model", "settings", "versions")},
        "accelerator": meta["accelerator"],
        "reference": REFERENCE,
        "config": CONFIG,
        "draws": draws,
        "draw_seeds": (
            "SHA-256 of the JSON ['floor-power', pool, draw]; first 8 bytes, "
            "big-endian, seed np.random.default_rng"
        ),
        "procedure": (
            "each draw permutes the pool, holds out the first null, and measures "
            "Floor.measure(per_row=True) from the next N; the held-out null is "
            "judged for false alarms; each fault is applied to the held-out null "
            "and judged at the detection N. Calibrated float checks use the same "
            "N nulls"
        ),
        "detectors": DETECTORS,
        "faults": {
            "replace": "k fault documents take the vector of other documents of the same run",
            "truncate": "one document keeps the first (1 - cut) of its words, embedded in the same session",
            "substitute": "words of one document replaced by random corpus words, embedded in the same session",
            "diffuse": "Gaussian noise of c times the pool's null scale on every coordinate, renormalized",
            "sparse": "a share of the coordinates multiplied by (1 + scale) in every row, renormalized",
            "size": "median over draws of the median 1 - cosine of the modified rows to the held-out null",
        },
        "detection_n": DETECTION_N,
        "pools": pools,
        "limits": [
            "one corpus (SciFact, 5,183 documents) and one model (e5-small-v2)",
            "the varying pool is synthetic: real rebuilds here gave one SEMQ state per device",
            "the draws resample one fixed pool; the intervals describe that pool, not the rebuilds of another pipeline",
            "the bounds 2/(N+1) for within and 3/(N+1) for per-row assume the nulls and the "
            "candidate are exchangeable",
        ],
    }
    inputs = {
        **{
            f"floor-power/{name}.npz": {
                "sha256": rebuild.sha256_file(cache / f"{name}.npz"),
                "source": "python -m benchmarks.floor_power --embed",
            }
            for name in meta["runs"]
        },
        **{
            f"floor-power/{name}": {
                "sha256": rebuild.sha256_file(cache / name),
                "source": "python -m benchmarks.floor_power --embed",
            }
            for name in ("faults.json", "pool.json")
        },
    }
    return inputs, results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--embed", action="store_true", help="regenerate embeddings")
    parser.add_argument("--runs", nargs="*", help="with --embed: re-embed these runs")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--cache", type=Path, default=CACHE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--draws", type=int, default=DRAWS)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.embed:
        embed_pool(args.cache, args.offline, args.runs)
        return
    started = time.perf_counter()
    inputs, results = evaluate(args.cache, args.draws)
    print(f"evaluated in {time.perf_counter() - started:.0f} s", flush=True)
    rebuild.write_or_check(
        args.output, rebuild.envelope("floor-power", inputs, results), args.check
    )


if __name__ == "__main__":
    main()
