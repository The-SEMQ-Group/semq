#!/usr/bin/env python3
# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
"""Fail when the public API breaks compatibility with a base revision.

Each surface is compared with the same surface at BASE, using the tool its
ecosystem relies on. Additions pass; removals and incompatible changes fail.

    C           abidiff (libabigail): exported functions, types and layouts
    Python      griffe check
    Rust        cargo semver-checks, as a minor release of both crates
    Go          apidiff -incompatible
    TypeScript  API Extractor reports; a line of BASE's report that is gone

    python tools/api_compat.py --base origin/main
    python tools/api_compat.py --base v1.0.0 --only rust,go

A surface whose tool is missing on this host is skipped and named; CI
installs every tool, so there nothing is skipped.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GO_MODULE = "github.com/The-SEMQ-Group/semq/bindings/go"
ABIDIFF_INCOMPATIBLE = 8  # bit of abidiff's exit status for an incompatible change


class Skipped(Exception):
    """The surface cannot be checked on this host."""


def run(args: list[str], cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True)


def need(tool: str) -> str:
    path = shutil.which(tool)
    if path is None:
        raise Skipped(f"{tool} is not installed")
    return path


def check_c(base: Path, work: Path) -> list[str]:
    abidiff = need("abidiff")
    need("cmake")
    libraries = []
    for name, tree in (("base", base), ("head", ROOT)):
        build = work / f"c-{name}"
        configure = run(["cmake", "-S", str(tree), "-B", str(build), "-G", "Ninja",
                         "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_C_FLAGS=-g",
                         "-DSEMQ_BUILD_TESTS=OFF", "-DSEMQ_BUILD_BENCHMARKS=OFF"], ROOT)
        compile_ = configure if configure.returncode else run(["cmake", "--build", str(build), "--target", "semq"], ROOT)
        if compile_.returncode:
            raise RuntimeError(f"building the {name} core failed:\n{compile_.stdout}{compile_.stderr}")
        libraries.append(build / "libsemq.so")
    result = run([abidiff, "--headers-dir1", str(base / "include"), "--headers-dir2", str(ROOT / "include"),
                  str(libraries[0]), str(libraries[1])], ROOT)
    if result.returncode & ~(ABIDIFF_INCOMPATIBLE | 4):
        raise RuntimeError(f"abidiff failed:\n{result.stdout}{result.stderr}")
    return [result.stdout.strip()] if result.returncode & ABIDIFF_INCOMPATIBLE else []


def check_python(base_ref: str) -> list[str]:
    griffe = need("griffe")
    result = run([griffe, "check", "semq", "--search", "bindings/python", "--against", base_ref], ROOT)
    return [(result.stdout + result.stderr).strip()] if result.returncode else []


def check_rust(base: Path, work: Path) -> list[str]:
    need("cargo-semver-checks")
    breaks = []
    for crate in ("semq-sys", "semq"):
        result = run(["cargo", "semver-checks", "--manifest-path", "bindings/rust/Cargo.toml", "-p", crate,
                      "--baseline-root", str(base / "bindings/rust"), "--release-type", "minor"],
                     ROOT, {**os.environ, "CARGO_TARGET_DIR": str(work / "rust-target")})
        output = (result.stdout + result.stderr).strip()
        if result.returncode and "semver requires new major version" in output:
            # The failures go to stdout; stderr carries progress and the summary.
            summary = [line.strip() for line in result.stderr.splitlines() if "Summary" in line]
            breaks.append("\n".join([result.stdout.strip(), *summary]))
        elif result.returncode:
            raise RuntimeError(f"cargo semver-checks failed for {crate}:\n{output}")
    return breaks


def check_go(base: Path, work: Path) -> list[str]:
    apidiff = need("apidiff")
    exported = work / "go-base.api"
    result = run([apidiff, "-m", "-w", str(exported), GO_MODULE], base / "bindings/go")
    if result.returncode:
        raise RuntimeError(f"apidiff could not read the base module:\n{result.stderr}")
    result = run([apidiff, "-m", "-incompatible", str(exported), GO_MODULE], ROOT / "bindings/go")
    if result.returncode:
        raise RuntimeError(f"apidiff could not read the current module:\n{result.stderr}")
    # apidiff exits 0 either way; it prints one line per incompatible change.
    changes = [line for line in result.stdout.splitlines() if line.strip()]
    return ["\n".join(changes)] if changes else []


def ts_report(tree: Path, head_ts: Path, work: Path, name: str) -> list[str]:
    """The API Extractor report of the package's emitted declarations."""
    package = tree / "bindings/ts"
    if tree != ROOT and not (package / "node_modules").exists():
        # The base tree uses the current tools; they do not change its API.
        (package / "node_modules").symlink_to(head_ts / "node_modules", target_is_directory=True)
    declarations = work / f"ts-{name}"
    emitted = run([str(head_ts / "node_modules/.bin/tsc"), "-p", "tsconfig.json", "--emitDeclarationOnly",
                   "--outDir", str(declarations)], package)
    if emitted.returncode:
        raise RuntimeError(f"emitting the {name} declarations failed:\n{emitted.stdout}{emitted.stderr}")
    reports = work / f"ts-{name}-report"
    config = package / "api-extractor.compat.json"
    config.write_text(json.dumps({
        "mainEntryPointFilePath": str(declarations / "index.d.ts"),
        "projectFolder": str(package),
        "compiler": {"tsconfigFilePath": str(package / "tsconfig.json")},
        "apiReport": {"enabled": True, "reportFolder": f"{reports}/", "reportTempFolder": f"{reports}/tmp/"},
        "docModel": {"enabled": False}, "dtsRollup": {"enabled": False}, "tsdocMetadata": {"enabled": False},
        "messages": {"extractorMessageReporting": {"default": {"logLevel": "none"}},
                     "compilerMessageReporting": {"default": {"logLevel": "warning"}},
                     "tsdocMessageReporting": {"default": {"logLevel": "none"}}},
    }), encoding="utf-8")
    try:
        extracted = run([str(head_ts / "node_modules/.bin/api-extractor"), "run", "--local", "-c", str(config)], package)
    finally:
        config.unlink()
    if extracted.returncode:
        raise RuntimeError(f"API Extractor failed on the {name} declarations:\n{extracted.stdout}{extracted.stderr}")
    (report,) = reports.glob("*.api.md")
    # Comments are API Extractor's annotations, not part of the API.
    return [line for line in report.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("//")]


def check_typescript(base: Path, work: Path) -> list[str]:
    head_ts = ROOT / "bindings/ts"
    if not (head_ts / "node_modules/.bin/api-extractor").exists():
        raise Skipped("bindings/ts dependencies are not installed (npm ci)")
    before = ts_report(base, head_ts, work, "base")
    after = set(ts_report(ROOT, head_ts, work, "head"))
    # A signature line of the base report that is not in the current one was
    # removed or changed. New lines are additions and pass.
    gone = [line for line in before if line not in after and line.strip() not in ("}", "{", "```", "```ts")]
    return ["removed or changed:\n" + "\n".join(gone)] if gone else []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", required=True, help="git revision to compare against")
    parser.add_argument("--only", default="c,python,rust,go,typescript", help="comma-separated surfaces")
    args = parser.parse_args()
    only = set(args.only.split(","))
    with tempfile.TemporaryDirectory(prefix="semq-api-") as temporary:
        work = Path(temporary)
        base = work / "base"
        added = run(["git", "worktree", "add", "--detach", str(base), args.base], ROOT)
        if added.returncode:
            print(added.stderr, file=sys.stderr)
            return 2
        checks: dict[str, Callable[[], list[str]]] = {
            "c": lambda: check_c(base, work),
            "python": lambda: check_python(args.base),
            "rust": lambda: check_rust(base, work),
            "go": lambda: check_go(base, work),
            "typescript": lambda: check_typescript(base, work),
        }
        failed = False
        try:
            for name, check in checks.items():
                if name not in only:
                    continue
                try:
                    breaks = check()
                except Skipped as reason:
                    print(f"{name}: skipped ({reason})")
                    continue
                if breaks:
                    failed = True
                    print(f"{name}: INCOMPATIBLE with {args.base}")
                    for detail in breaks:
                        print("    " + detail.replace("\n", "\n    "))
                else:
                    print(f"{name}: compatible with {args.base}")
        finally:
            run(["git", "worktree", "remove", "--force", str(base)], ROOT)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
