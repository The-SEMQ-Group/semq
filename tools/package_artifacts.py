#!/usr/bin/env python3
# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
"""Build publication artifacts; no registry upload and no checkout mutation.

Requires Python build tooling, Cargo, Go, npm and an already built TS package.
Rust's bundled core and the Go module's copy come from the same C source tree.
The output also carries the independent external-consumer programs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    print(f"RUN {args!r} ({cwd})", flush=True)
    subprocess.run(args, cwd=cwd, env=env, check=True)


def copy_core(destination: Path) -> None:
    for directory in ("include", "src"):
        shutil.copytree(ROOT / directory, destination / directory)
    for name in ("CMakeLists.txt", "VERSION", "LICENSE.md", "NOTICE"):
        shutil.copy2(ROOT / name, destination / name)
    revision = subprocess.check_output(
        ["git", "rev-parse", "--short=12", "HEAD"], cwd=ROOT, text=True
    ).strip()
    (destination / "SOURCE_REVISION").write_text(revision + "\n", encoding="utf-8")


def rust_artifacts(output: Path, stage: Path, offline: bool) -> None:
    workspace = stage / "rust"
    workspace.mkdir()
    # Library workspaces do not commit Cargo.lock. Resolve only from the
    # versioned manifests, equally in a clean checkout and on a developer host.
    shutil.copy2(ROOT / "bindings/rust/Cargo.toml", workspace / "Cargo.toml")
    for name in ("semq", "semq-sys"):
        crate = workspace / name
        crate.mkdir()
        shutil.copy2(ROOT / "bindings/rust" / name / "Cargo.toml", crate / "Cargo.toml")
        shutil.copytree(ROOT / "bindings/rust" / name / "src", crate / "src")
        for legal in ("LICENSE.md", "NOTICE"):
            shutil.copy2(ROOT / legal, crate / legal)
    shutil.copy2(ROOT / "bindings/rust/semq-sys/build.rs", workspace / "semq-sys/build.rs")
    shutil.copy2(ROOT / "bindings/rust/semq/README.md", workspace / "semq/README.md")
    copy_core(workspace / "semq-sys/native")
    # Cargo packages the workspace together, resolving the unpublished pair
    # locally. Verification is performed by a separate consumer of the archives.
    args = ["cargo", "package", "--workspace", "--allow-dirty", "--no-verify"]
    if offline:
        args.append("--offline")
    run(args, workspace)
    crates = sorted((workspace / "target/package").glob("*.crate"))
    if len(crates) != 2:
        raise RuntimeError(f"expected two crate archives, found {crates}")
    for path in crates:
        shutil.copy2(path, output / path.name)
    # Keep the exact staged sources so the publish job can regenerate both
    # archives, compare them with the verified ones, and upload from them.
    with tarfile.open(output / "semq-rust-source.tar.gz", "w:gz") as archive:
        archive.add(workspace / "Cargo.toml", arcname="rust/Cargo.toml")
        for name in ("semq-sys", "semq"):
            archive.add(workspace / name, arcname=f"rust/{name}")


def go_artifacts(output: Path, version: str) -> dict[str, str]:
    module = "github.com/The-SEMQ-Group/semq/bindings/go"
    escaped = "".join("!" + c.lower() if c.isupper() else c for c in module)
    proxy = output / "go-proxy" / escaped / "@v"
    proxy.mkdir(parents=True)
    source = ROOT / "bindings/go"
    (proxy / f"{version}.mod").write_bytes((source / "go.mod").read_bytes())
    timestamp = subprocess.check_output(
        ["git", "log", "-1", "--format=%cI"], cwd=ROOT, text=True).strip()
    (proxy / f"{version}.info").write_text(
        json.dumps({"Version": version, "Time": timestamp}), encoding="utf-8")
    (proxy / "list").write_text(version + "\n", encoding="utf-8")
    # Every tracked file in the module, as proxy.golang.org serves it: its copy
    # of the C core and of the license files included, nothing from outside.
    tracked = subprocess.check_output(["git", "ls-files", "-z", "--", "."], cwd=source, text=True)
    files = {name: source / name for name in tracked.split("\0") if name}
    with zipfile.ZipFile(proxy / f"{version}.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for name, path in sorted(files.items()):
            archive.write(path, f"{module}@{version}/{name}")
    return {"module": module, "version": version}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--offline-rust", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    if output == ROOT or ROOT in output.parents:
        parser.error("output must be outside the checkout")
    if output.exists() and any(output.iterdir()):
        parser.error("output must be empty (never mix builds)")
    output.mkdir(parents=True, exist_ok=True)
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    with tempfile.TemporaryDirectory(prefix="semq-package-") as temporary:
        stage = Path(temporary)
        rust_artifacts(output, stage, args.offline_rust)
        run([sys.executable, "-m", "build", "--wheel", "--sdist", "--outdir", str(output)], ROOT)
        ts = stage / "typescript"
        ts.mkdir()
        # Pack the emitted package, with one copy of WASM and no source tree.
        for name in ("package.json", "README.md"):
            shutil.copy2(ROOT / "bindings/ts" / name, ts / name)
        shutil.copytree(ROOT / "bindings/ts/dist", ts / "dist")
        for legal in ("LICENSE.md", "NOTICE", "THIRD_PARTY_LICENSES"):
            shutil.copy2(ROOT / legal, ts / legal)
        run(["npm", "pack", "--ignore-scripts", "--pack-destination", str(output)], ts)
    go = go_artifacts(output, "v" + version)
    shutil.copytree(ROOT / "tests/install/consumers", output / "consumers")
    # The conformance vectors and each language's runner, so the consumers
    # check the published packages byte for byte, not only their behavior.
    shutil.copytree(ROOT / "tests/conformance", output / "conformance",
                    ignore=shutil.ignore_patterns("__pycache__", "*.c", "reference.py", "README.md"))
    runners = output / "conformance-runners"
    runners.mkdir()
    shutil.copy2(ROOT / "bindings/rust/semq/tests/conformance.rs", runners / "conformance.rs")
    shutil.copy2(ROOT / "bindings/ts/test/conformance.test.ts", runners / "conformance.test.ts")
    shutil.copy2(ROOT / "tests/install/run_artifacts.py", output / "run_artifacts.py")
    files = {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(output.rglob("*")) if p.is_file()}
    rust_version = tomllib.loads((ROOT / "bindings/rust/semq/Cargo.toml").read_text())["package"]["version"]
    manifest = {"go": go, "rust_version": rust_version, "sha256": files}
    (output / "artifacts.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Artifacts ready at {output}; run run_artifacts.py on a host without the checkout.")


if __name__ == "__main__":
    main()
