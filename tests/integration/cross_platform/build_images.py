# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Build the cross-platform Docker images used by the runners in this
directory.

Produces two images:

    semq:arm64   (linux/arm64)
    semq:amd64   (linux/amd64)

Both runners (``run_jitter.py``, ``run_property_tests.py``) expect these
tags to exist. Build context is a temporary staging directory containing
exactly the files the Dockerfile needs, so the parent project tree is
not the build context.

Usage::

    python tests/integration/cross_platform/build_images.py
    python tests/integration/cross_platform/build_images.py --platforms arm64

Requires Docker running.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SDK_ROOT = HERE.parent.parent.parent


def _stage_build_context(staging: Path) -> None:
    """Copy exactly what the Dockerfile needs into ``staging``."""

    def _ignore(_dir: str, names: list[str]) -> list[str]:
        return [n for n in names if n in {
            "__pycache__", ".pytest_cache", ".mypy_cache",
            "build", "build-bench", "build-release", ".venv",
        } or n.endswith((".pyc", ".dylib", ".so", ".a"))]

    shutil.copytree(SDK_ROOT / "include",  staging / "include",  ignore=_ignore)
    shutil.copytree(SDK_ROOT / "src",      staging / "src",      ignore=_ignore)
    shutil.copytree(SDK_ROOT / "bindings", staging / "bindings", ignore=_ignore)
    shutil.copy(SDK_ROOT / "CMakeLists.txt", staging / "CMakeLists.txt")

    (staging / "tests" / "integration").mkdir(parents=True, exist_ok=True)
    shutil.copytree(HERE, staging / "tests" / "integration" / "cross_platform")
    shutil.copytree(SDK_ROOT / "tests" / "property",
                    staging / "tests" / "property", ignore=_ignore)


def _docker_available() -> bool:
    try:
        r = subprocess.run(
            ["docker", "info"],
            capture_output=True, text=True, timeout=10,
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _build_image(staging: Path, arch: str) -> None:
    plat = f"linux/{arch}"
    tag = f"semq:{arch}"
    print(f"  → building {tag} ({plat})...", flush=True)
    r = subprocess.run(
        ["docker", "build",
         "--platform", plat,
         "-t", tag,
         "-f", str(staging / "tests" / "integration"
                   / "cross_platform" / "Dockerfile"),
         str(staging)],
        capture_output=True, text=True, timeout=1800,
    )
    if r.returncode != 0:
        raise RuntimeError(
            f"docker build {plat} failed:\n{r.stderr[-2000:]}"
        )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--platforms", nargs="+",
                   default=["arm64", "amd64"],
                   choices=["arm64", "amd64"])
    args = p.parse_args()

    if not _docker_available():
        print("⚠ Docker not reachable")
        return 2

    with tempfile.TemporaryDirectory(prefix="semq-xplat-build-") as td:
        staging = Path(td)
        _stage_build_context(staging)
        for arch in args.platforms:
            _build_image(staging, arch)

    print(f"\n✓ built {len(args.platforms)} image(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
