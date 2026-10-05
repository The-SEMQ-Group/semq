#!/usr/bin/env python3
# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
"""Run only from a copied artifact bundle, on a host without the SDK checkout.

CI deliberately runs this in a job without actions/checkout. Local callers can
deny filesystem access to their checkout while running this standalone script.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import venv
from pathlib import Path


def clean_env() -> dict[str, str]:
    excluded = {"PYTHONPATH", "PYTHONHOME", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH",
                "DYLD_FALLBACK_LIBRARY_PATH", "CARGO_TARGET_DIR", "GOWORK", "GOFLAGS"}
    return {key: value for key, value in os.environ.items()
            if key not in excluded and not key.startswith(("SEMQ_", "CGO_"))}


def run(args: list[str], cwd: Path, env: dict[str, str], expected: int = 0) -> None:
    print(f"RUN {args!r} ({cwd})", flush=True)
    result = subprocess.run(args, cwd=cwd, env=env)
    if result.returncode != expected:
        raise RuntimeError(f"exit {result.returncode}, expected {expected}: {args!r}")


def extract(path: Path, destination: Path) -> None:
    with tarfile.open(path) as archive:
        archive.extractall(destination, filter="data")


def only(directory: Path, pattern: str) -> Path:
    paths = list(directory.glob(pattern))
    if len(paths) != 1:
        raise RuntimeError(f"expected exactly one {pattern}: {paths}")
    return paths[0]


def conformance_env(bundle: Path, env: dict[str, str]) -> dict[str, str]:
    """The environment for a conformance runner: the bundle's vectors, required."""
    return {**env, "SEMQ_CONFORMANCE_DIR": str(bundle / "conformance")}


def check_python(bundle: Path, work: Path, env: dict[str, str], *, sdist: bool = False) -> None:
    venv.create(work / "venv", with_pip=True)
    scripts = work / "venv" / ("Scripts" if os.name == "nt" else "bin")
    python = scripts / ("python.exe" if os.name == "nt" else "python")
    artifact = only(bundle, "semq-[0-9]*.tar.gz" if sdist else "*.whl")
    run([str(python), "-m", "pip", "install", str(artifact)], work, env)
    run([str(python), str(bundle / "consumers/python/consumer.py")], work, env)
    cli = [str(python), "-m", "semq"]
    run(cli + ["version"], work, env)
    run([str(python), "-m", "pip", "install", "pytest"], work, env)
    run([str(python), "-m", "pytest", str(bundle / "conformance"), "-q", "-p", "no:cacheprovider"],
        work, conformance_env(bundle, env))
    run(cli + ["diff", "quant-u64.semq", "quant-u64.semq", "--floor", "floor.json"], work, env)
    run(cli + ["diff", "quant-u64.semq", "candidate.semq", "--floor", "floor.json"], work, env, expected=1)


def check_rust(bundle: Path, work: Path, env: dict[str, str], version: str) -> None:
    for path in bundle.glob("*.crate"):
        extract(path, work / "crates")
    src = work / "src"
    src.mkdir()
    shutil.copy2(bundle / "consumers/rust/main.rs", src / "main.rs")
    (work / "Cargo.toml").write_text(
        '[package]\nname="external-semq-consumer"\nversion="0.0.0"\nedition="2021"\n'
        '[dependencies]\nsemq={path="crates/semq-' + version + '"}\n'
        '[patch.crates-io]\nsemq-sys={path="crates/semq-sys-' + version + '"}\n'
        '[dev-dependencies]\nserde_json="1"\n', encoding="utf-8")
    (work / "tests").mkdir()
    shutil.copy2(bundle / "conformance-runners/conformance.rs", work / "tests/conformance.rs")
    # Only the extracted .crate payloads are dependencies. No repo path, no
    # prebuilt native override, and no reused target directory.
    run(["cargo", "run", "--release"], work, env)
    run(["cargo", "test", "--release", "--test", "conformance"], work, conformance_env(bundle, env))


def check_go(bundle: Path, work: Path, env: dict[str, str], manifest: dict) -> None:
    # The module compiles its own copy of the core: no native library or flags.
    env = dict(env)
    env.update({"CGO_ENABLED": "1",
                "GOPROXY": (bundle / "go-proxy").as_uri(), "GOSUMDB": "off",
                "GONOPROXY": "", "GOPRIVATE": "", "GOWORK": "off",
                "GOMODCACHE": str(work / "module-cache"), "GOCACHE": str(work / "build-cache")})
    module, version = manifest["go"]["module"], manifest["go"]["version"]
    (work / "go.mod").write_text(
        f"module external-semq-consumer\n\ngo 1.21\n\nrequire {module} {version}\n", encoding="utf-8")
    shutil.copy2(bundle / "consumers/go/main.go", work / "main.go")
    run(["go", "mod", "download"], work, env)
    run(["go", "run", "-mod=mod", "."], work, env)
    # The module's own conformance test, run from the module cache.
    run(["go", "test", "-mod=mod", "-count=1", "-run", "^TestConformance$", module], work,
        conformance_env(bundle, env))


def check_typescript(bundle: Path, work: Path, env: dict[str, str]) -> None:
    (work / "package.json").write_text('{"private":true,"type":"module"}\n', encoding="utf-8")
    shutil.copy2(bundle / "consumers/typescript/consumer.ts", work / "consumer.ts")
    package = only(bundle, "*.tgz")
    run(["npm", "install", "--ignore-scripts", "--no-audit", "--no-fund", str(package),
         "typescript@^5.5", "@types/node@^22"], work, env)
    run(["node", "node_modules/typescript/bin/tsc", "consumer.ts", "--strict",
         "--target", "ES2022", "--module", "NodeNext", "--moduleResolution", "NodeNext"], work, env)
    run(["node", "consumer.js"], work, env)
    # The package's conformance runner against the installed package.
    source = (bundle / "conformance-runners/conformance.test.ts").read_text(encoding="utf-8")
    if '"../src/index.js"' not in source:
        raise RuntimeError("conformance.test.ts no longer imports ../src/index.js")
    (work / "conformance.test.ts").write_text(source.replace('"../src/index.js"', '"@semq/sdk"'),
                                              encoding="utf-8")
    installed = json.loads((work / "node_modules/@semq/sdk/package.json").read_text(encoding="utf-8"))
    run(["npm", "install", "--ignore-scripts", "--no-audit", "--no-fund",
         "vitest@" + installed["devDependencies"]["vitest"]], work, env)
    run(["node", "node_modules/vitest/vitest.mjs", "run", "conformance.test.ts"], work,
        conformance_env(bundle, env))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=Path, help="empty directory for the four consumers")
    parser.add_argument("--forbid-checkout", type=Path, help="assert OS access to this checkout is denied")
    args = parser.parse_args()
    bundle = Path(__file__).resolve().parent
    if (bundle / "include/semq.h").exists() or (bundle / ".git").exists():
        parser.error("run from the artifact bundle, not the checkout")
    if args.forbid_checkout is not None:
        try:
            (args.forbid_checkout / "include/semq.h").read_bytes()
        except PermissionError:
            print("PASS: OS denies reading the checkout", flush=True)
        else:
            parser.error("the checkout is still accessible")
    work = args.work.resolve()
    if work.exists() and any(work.iterdir()):
        parser.error("consumer workspace must be empty")
    manifest = json.loads((bundle / "artifacts.json").read_text(encoding="utf-8"))
    for relative, expected in manifest["sha256"].items():
        actual = hashlib.sha256((bundle / relative).read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"artifact changed: {relative}")
    env = clean_env()
    languages = ("python", "python-sdist", "rust", "go", "typescript")
    for language in languages:
        destination = work / language
        destination.mkdir(parents=True)
        if language.startswith("python"):
            check_python(bundle, destination, env, sdist=language == "python-sdist")
        elif language == "rust":
            check_rust(bundle, destination, env, manifest["rust_version"])
        elif language == "go":
            check_go(bundle, destination, env, manifest)
        else:
            check_typescript(bundle, destination, env)
    for operator in ("quant", "phase", "orbit"):
        for kind in ("u64", "utf8"):
            name = f"{operator}-{kind}.semq"
            images = [(work / language / name).read_bytes()
                      for language in languages]
            if any(image != images[0] for image in images[1:]):
                raise RuntimeError(f"external artifacts disagree: {name}")
            print(f"IDENTICAL {name}: {hashlib.sha256(images[0]).hexdigest()}")
    print("PASS: four isolated consumers; six byte-identical states; encode/restore/diff/floor and CLI")


if __name__ == "__main__":
    main()
