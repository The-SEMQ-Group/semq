# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Scale: SIMD differential fuzz — every backend must be bit-identical.

The product's headline guarantee is that an index encoded on one CPU
is byte-for-byte identical to one encoded on any other. The default
tests validate this on friendly inputs; this fuzz hammers the SIMD
kernels with *adversarial* float32 patterns — subnormals, signed
zeros, values sitting exactly on quantile / rounding boundaries,
near-overflow magnitudes, and alphabet-saturating distributions —
and asserts the SIMD path produces the same bytes as the scalar
reference for every one of them, across all three operators
(QUANT, PHASE, CANON).

Mechanism: the dispatcher honours ``SEMQ_FORCE_BACKEND`` at process
start. We run the worker (``_simd_fuzz_worker.py``) once per backend
available on this host and compare the resulting fingerprint maps.
On Apple Silicon that is scalar vs NEON; on x86 CI it is scalar vs
AVX2/AVX-512; on Graviton scalar vs NEON/SVE. So this single test is
also the cross-architecture regression guard when run in CI.

If only the scalar backend is available (no SIMD on this host), the
test skips — there is nothing to differentially compare.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

_WORKER = Path(__file__).parent / "_simd_fuzz_worker.py"

# Candidate SIMD backends to probe for on this host. scalar is always
# the reference and is never in this list.
_CANDIDATE_BACKENDS = ["neon", "avx2", "avx512", "sve"]

_DIM = 24  # not a multiple of any vector width, to exercise tail handling


def _run_worker(bundle: Path, force_backend: str) -> dict:
    env = dict(os.environ)
    env["SEMQ_FORCE_BACKEND"] = force_backend
    out = subprocess.check_output(
        [sys.executable, str(_WORKER), str(bundle)],
        env=env, text=True,
    )
    return json.loads(out)


def _available_simd_backends(bundle: Path) -> list[str]:
    """Return the SIMD backends that actually resolve on this host
    (forcing an unavailable one silently falls back to scalar)."""
    available = []
    for be in _CANDIDATE_BACKENDS:
        result = _run_worker(bundle, be)
        if be in result["backend"].values():
            available.append(be)
    return available


def _adversarial_bundle(tmp_path: Path) -> Path:
    """Build an .npz of adversarial (n, dim) float32 corpora."""
    rng = np.random.default_rng(20260708)
    n = 96
    dim = _DIM
    cases: dict[str, np.ndarray] = {}

    # Baseline gaussian (sanity — must also stay identical).
    cases["gaussian"] = rng.standard_normal((n, dim)).astype(np.float32)

    # Subnormals: smallest positive subnormal float32 and neighbours.
    tiny = np.float32(1.0e-45)  # ~ smallest subnormal
    cases["subnormal"] = (rng.integers(0, 3, (n, dim)) * tiny).astype(np.float32)

    # Signed zeros mixed with small values.
    sz = rng.choice([-0.0, 0.0, 1e-20, -1e-20], size=(n, dim))
    cases["signed_zero"] = sz.astype(np.float32)

    # Near-overflow magnitudes (close to float32 max), mixed signs.
    big = np.float32(3.0e38)
    cases["near_overflow"] = (
        rng.choice([-1.0, 1.0], size=(n, dim)) * big
        * rng.uniform(0.1, 1.0, (n, dim))
    ).astype(np.float32)

    # Powers of two and values just above/below (rounding edges).
    exps = rng.integers(-20, 20, (n, dim))
    base = (2.0 ** exps).astype(np.float32)
    nudge = rng.choice([-1.0, 0.0, 1.0], size=(n, dim)) * np.spacing(base)
    cases["power_of_two_edges"] = (base + nudge).astype(np.float32)

    # Exactly-equal rows (ties in quantile binning must break the same
    # way on every backend).
    tie_row = rng.standard_normal((1, dim)).astype(np.float32)
    cases["ties"] = np.repeat(tie_row, n, axis=0)

    # Alphabet-saturating: heavy-tailed so QUANT pushes many values to
    # the extreme bins.
    cases["heavy_tail"] = (
        rng.standard_t(df=1.5, size=(n, dim))
    ).astype(np.float32)

    # Wide dynamic range within a single row.
    dr = rng.standard_normal((n, dim)).astype(np.float32)
    dr[:, ::2] *= np.float32(1e6)
    dr[:, 1::2] *= np.float32(1e-6)
    cases["dynamic_range"] = dr

    # Large but still IN-DOMAIN magnitudes: values ~1e18 keep the
    # per-row float32 L2 norm finite (sum of squares ~ dim·1e36 <
    # FLT_MAX). These must stay bit-identical — they sit just under
    # the norm-overflow domain gate and exercise the large-value path
    # without being rejected.
    cases["large_in_domain"] = (
        rng.standard_normal((n, dim)) * 1.0e18
    ).astype(np.float32)

    bundle = tmp_path / "adversarial_corpora.npz"
    np.savez(bundle, **cases)
    return bundle


@pytest.mark.slow
def test_simd_backends_are_bit_identical_to_scalar(
    scale_helpers, tmp_path: Path,
) -> None:
    bundle = _adversarial_bundle(tmp_path)

    reference = _run_worker(bundle, "scalar")
    assert set(reference["backend"].values()) == {"scalar"}, (
        "could not force the scalar reference backend"
    )
    ref_fps = reference["fingerprints"]
    assert ref_fps, "worker produced no fingerprints"

    simd = _available_simd_backends(bundle)
    if not simd:
        pytest.skip("no SIMD backend available on this host to compare")

    report: dict[str, dict] = {"scalar_cases": len(ref_fps), "backends": {}}
    mismatches: list[str] = []
    for be in simd:
        result = _run_worker(bundle, be)
        fps = result["fingerprints"]
        be_mismatch = [
            key for key in ref_fps
            if fps.get(key) != ref_fps[key]
        ]
        report["backends"][be] = {
            "cases": len(fps),
            "mismatches": be_mismatch,
        }
        for key in be_mismatch:
            mismatches.append(
                f"{be} vs scalar differ on {key}: "
                f"{fps.get(key)} != {ref_fps[key]}"
            )

    scale_helpers.write_result("simd_differential_fuzz", report)
    print(f"  scalar reference: {len(ref_fps)} (case×op) fingerprints")
    for be, info in report["backends"].items():
        status = "OK" if not info["mismatches"] else f"{len(info['mismatches'])} MISMATCH"
        print(f"  {be:8} vs scalar: {info['cases']} fingerprints — {status}")

    assert not mismatches, (
        "SIMD backend(s) diverge from the scalar reference — the "
        "cross-arch bit-identity guarantee is broken:\n  "
        + "\n  ".join(mismatches[:20])
    )
