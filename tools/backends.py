#!/usr/bin/env python3
# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
"""Run the conformance vectors under every SIMD backend this host can execute.

The core picks its kernels from the CPU, so a host without AVX-512 or SVE
never runs them, and SEMQ_FORCE_BACKEND silently falls back to scalar for a
backend the CPU lacks. This tool asks the core which backend each forced
choice really uses, runs tests/conformance once per backend that is really
available, and fails when an expected backend is missing.

    python tools/backends.py                          # list what is available
    python tools/backends.py --run --expect scalar,avx2
"""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ("scalar", "avx2", "avx512", "neon", "sve")
OPERATORS = ("orbit", "phase", "quant")


def effective(backend: str) -> dict[str, str]:
    """The backend each operator's codec uses when `backend` is forced."""
    script = (
        "from semq import Codec, CodecConfig\n"
        "cfgs = {'orbit': CodecConfig.orbit(8), 'phase': CodecConfig.phase(8, 4),"
        " 'quant': CodecConfig.quant(8, 4)}\n"
        f"print(' '.join(Codec(cfgs[op]).backend for op in {OPERATORS!r}))\n"
    )
    env = {**os.environ, "SEMQ_FORCE_BACKEND": backend}
    out = subprocess.run([sys.executable, "-c", script], env=env, check=True,
                         capture_output=True, text=True).stdout.split()
    return dict(zip(OPERATORS, out, strict=True))


def available() -> dict[str, dict[str, str]]:
    """Backends the host really executes, with the backend each operator uses."""
    result = {}
    for name in CANDIDATES:
        used = effective(name)
        # A backend is available when it runs at least one operator: SVE, for
        # instance, has orbit and phase kernels but no quant kernel.
        if name in used.values():
            result[name] = used
    return result


def cpu() -> str:
    try:
        if sys.platform == "darwin":
            return subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                                  capture_output=True, text=True).stdout.strip()
        if sys.platform.startswith("linux"):
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                if line.lower().startswith(("model name", "cpu part")):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--expect", default="", help="comma-separated backends that must be available")
    parser.add_argument("--run", action="store_true", help="run tests/conformance under each backend")
    args = parser.parse_args()

    found = available()
    lines = [f"CPU: {cpu()} ({platform.machine()})", "", "| Backend | orbit | phase | quant |",
             "| --- | --- | --- | --- |"]
    lines += [f"| {name} | " + " | ".join(used[op] for op in OPERATORS) + " |" for name, used in found.items()]
    report = "\n".join(lines)
    print(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(f"### SIMD backends\n\n{report}\n\n")

    missing = [name for name in args.expect.split(",") if name and name not in found]
    if missing:
        print(f"error: expected backends not available on this host: {', '.join(missing)}", file=sys.stderr)
        return 1
    if not args.run:
        return 0
    failed = []
    for name in found:
        print(f"\n== conformance with SEMQ_FORCE_BACKEND={name}", flush=True)
        env = {**os.environ, "SEMQ_FORCE_BACKEND": name}
        result = subprocess.run([sys.executable, "-m", "pytest", str(ROOT / "tests/conformance"), "-q",
                                 "-p", "no:cacheprovider"], env=env)
        if result.returncode != 0:
            failed.append(name)
    if failed:
        print(f"error: conformance failed under: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
