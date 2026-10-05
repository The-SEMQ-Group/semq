# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""The conformance gate.

Regenerates every vector with the core's generator into a scratch directory,
checks the non-kernel vectors with the independent Python reference, and
compares the result with the committed vectors under tests/conformance/.
Any byte or verdict difference fails, unless the pull request also bumps the
file version or the rule revision and regenerates (run with --update).

    python tools/conformance.py build/semq_vectors            # gate
    python tools/conformance.py build/semq_vectors --update   # regenerate
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMITTED = ROOT / "tests" / "conformance"
REFERENCE = COMMITTED / "reference.py"
KEEP = {"README.md", "reference.py", "semq_vectors.c", "test_conformance.py", "__pycache__"}


def vector_dirs(root: Path) -> list[Path]:
    return sorted(p for p in root.iterdir() if p.is_dir() and p.name[:2].isdigit())


def compare(generated: Path) -> list[str]:
    problems: list[str] = []
    gen = {p.name: p for p in vector_dirs(generated)}
    com = {p.name: p for p in vector_dirs(COMMITTED)}
    for name in sorted(set(gen) | set(com)):
        if name not in gen:
            problems.append(f"{name}: committed but not generated")
            continue
        if name not in com:
            problems.append(f"{name}: generated but not committed")
            continue
        left = {p.name for p in gen[name].iterdir()}
        right = {p.name for p in com[name].iterdir()}
        for missing in sorted(left - right):
            problems.append(f"{name}/{missing}: generated but not committed")
        for extra in sorted(right - left):
            problems.append(f"{name}/{extra}: committed but not generated")
        for common in sorted(left & right):
            if not filecmp.cmp(gen[name] / common, com[name] / common, shallow=False):
                problems.append(f"{name}/{common}: differs")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("generator", help="path to the built semq_vectors binary")
    parser.add_argument("--update", action="store_true", help="replace the committed vectors")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="semq-vectors-") as scratch:
        out = Path(scratch) / "vectors"
        subprocess.run([str(Path(args.generator).resolve()), str(out)], check=True)
        subprocess.run([sys.executable, str(REFERENCE), str(out)], check=True)
        if args.update:
            for old in vector_dirs(COMMITTED):
                shutil.rmtree(old)
            for new in vector_dirs(out):
                shutil.copytree(new, COMMITTED / new.name)
            print(f"conformance: committed vectors replaced from {args.generator}")
            return 0
        problems = compare(out)
    if problems:
        print("conformance: the generated vectors differ from tests/conformance/:", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        print("bump SEMQ_FILE_VERSION or the rule revision and run with --update if the change is intended", file=sys.stderr)
        return 1
    print("conformance: generated vectors match the committed ones")
    return 0


if __name__ == "__main__":
    sys.exit(main())
