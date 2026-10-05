# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Run the cross-backend property tests inside each Docker architecture.

On a developer's host machine, ``pytest tests/property/test_cross_backend.py``
only exercises the SIMD backends linked for that host (typically NEON on
macOS arm64, AVX2 on Linux x86_64). This harness lifts that restriction
by running the same test file inside both ``linux/arm64`` and
``linux/amd64`` containers — so every backend gets exercised regardless
of the developer's local hardware.

Requires the images ``semq:arm64`` and ``semq:amd64`` to be built (see
``build_images.py``).
"""

from __future__ import annotations

import argparse
import subprocess
import sys


def _run_arch(arch: str) -> int:
    plat = f"linux/{arch}"
    tag = f"semq:{arch}"
    print(f"\n=== [{arch}] pytest tests/property/test_cross_backend.py ===\n")
    cmd = [
        "docker", "run", "--rm", "--platform", plat,
        "--entrypoint", "pytest", tag,
        "/app/tests/property/test_cross_backend.py",
        "-v", "--tb=short", "--no-header",
    ]
    r = subprocess.run(cmd, timeout=600)
    return r.returncode


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--platforms", nargs="+",
                   default=["arm64", "amd64"],
                   choices=["arm64", "amd64"])
    args = p.parse_args()

    failures = 0
    for arch in args.platforms:
        rc = _run_arch(arch)
        if rc != 0:
            failures += 1
            print(f"  ✗ [{arch}] failed (exit {rc})")
        else:
            print(f"  ✓ [{arch}] passed")

    print("\n--- summary ---\n")
    if failures == 0:
        print(f"  ✓ cross-backend property tests passed on "
              f"{len(args.platforms)} architecture(s)")
        return 0
    print(f"  ✗ {failures}/{len(args.platforms)} arch(es) failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
