# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Run the FP32-vs-SEMQ counterfactual across host + Docker arm64 + amd64.

Requires the ``semq:arm64`` and ``semq:amd64`` images to exist — build
them once with ``python build_images.py`` before invoking this runner.

For each platform, captures the per-stage SHA256 hashes and prints
a comparison matrix that highlights which stages diverge cross-arch.
If GEMM or normalization diverge on any architecture, raw FP32
storage is unsafe for cross-platform replay — and SEMQ codes
collapsing all of them to bit-identical output is the proof that
the operator is necessary, not optional.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SDK_ROOT = HERE.parent.parent.parent


def _run_host() -> dict:
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(SDK_ROOT / "bindings" / "python"))
    env.setdefault("SEMQ_LIB_DIR", str(SDK_ROOT / "build"))
    env.setdefault("SEMQ_FORCE_BACKEND", "scalar")
    r = subprocess.run(
        [sys.executable, str(HERE / "numpy_jitter_test.py")],
        capture_output=True, text=True, timeout=120, env=env,
    )
    if r.returncode != 0:
        raise RuntimeError(f"host failed:\n{r.stderr}")
    return json.loads(r.stdout)


def _run_docker(arch: str) -> dict:
    plat = f"linux/{arch}"
    tag = f"semq:{arch}"
    r = subprocess.run(
        ["docker", "run", "--rm", "--platform", plat, tag,
         "python", "/app/cross_platform/numpy_jitter_test.py"],
        capture_output=True, text=True, timeout=300,
    )
    if r.returncode != 0:
        raise RuntimeError(f"docker {plat} failed:\n{r.stderr}")
    return json.loads(r.stdout)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--platforms", nargs="+",
                   default=["host", "arm64", "amd64"],
                   choices=["host", "arm64", "amd64"])
    args = p.parse_args()

    print("\n=== Counterfactual: does raw FP32 stay bit-identical "
          "cross-platform? ===\n")

    results: dict[str, dict] = {}
    if "host" in args.platforms:
        print("[host] running numpy_jitter_test.py...")
        results["host"] = _run_host()
    for arch in ("arm64", "amd64"):
        if arch in args.platforms:
            print(f"[{arch}] running in container...")
            results[arch] = _run_docker(arch)

    print("\n--- platforms ---\n")
    for k, v in results.items():
        print(f"  [{k}] {v['platform']}  python={v['python_version']}  "
              f"numpy={v['numpy_version']}")

    print("\n--- per-stage hash equality across platforms ---\n")
    stages = [
        "A_random", "B_random", "C_gemm",
        "row_norms_reduction", "D_normalized", "SEMQ_codes",
    ]
    platforms = list(results.keys())
    if not platforms:
        print("  (no runs)")
        return 2
    ref = platforms[0]

    print(f"  {'stage':<22}  {ref:>16}", end="")
    for p in platforms[1:]:
        print(f"  {p:>16}", end="")
    print()
    print("  " + "-" * (22 + 18 * len(platforms)))

    diverged_stages: list[str] = []
    for stage in stages:
        ref_hash = results[ref]["stage_hashes"][stage]
        line = f"  {stage:<22}  {ref_hash[:12] + '…':>16}"
        all_match = True
        for p in platforms[1:]:
            h = results[p]["stage_hashes"][stage]
            if h == ref_hash:
                line += f"  {'== ref':>16}"
            else:
                line += f"  {h[:12] + '…':>16}  ✗"
                all_match = False
        if not all_match:
            diverged_stages.append(stage)
        print(line)

    print("\n--- verdict ---\n")
    if len(platforms) < 2:
        print("  (single platform — nothing to compare; cross-platform "
              "verdict requires at least two)")
        return 0
    if not diverged_stages:
        print("  ⚠ ALL stages identical across platforms.")
        print("    Vanilla numpy was already deterministic for this workload.")
        print("    SEMQ's contribution here is therefore NOT cross-platform-")
        print("    jitter prevention — try a more BLAS-heavy workload.")
        return 0

    print(f"  ✓ COUNTERFACTUAL CONFIRMED — {len(diverged_stages)} "
          f"stage(s) diverged cross-platform:")
    for s in diverged_stages:
        print(f"     • {s}")

    semq_ok = "SEMQ_codes" not in diverged_stages
    non_semq = [s for s in diverged_stages if s != "SEMQ_codes"]
    if non_semq and semq_ok:
        print("\n  → raw FP32 is unsafe for cross-platform replay")
        print("  → SEMQ codes ARE bit-identical across the same platforms")
        print("  → SEMQ is required for the audit-grade replay claim")
    return 0


if __name__ == "__main__":
    sys.exit(main())
