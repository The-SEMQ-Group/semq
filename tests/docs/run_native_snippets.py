"""Compile and execute published Rust, Go, or TypeScript examples.

Run from the repository root after building that binding:
    python tests/docs/run_native_snippets.py rust
    python tests/docs/run_native_snippets.py go
    python tests/docs/run_native_snippets.py typescript

Each fence is an independent program with a temporary working directory.
No fixture, code example, or package import is rewritten before compilation.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from snippet_utils import REPO_ROOT, all_snippets


def run(command: list[str], cwd: Path, env: dict[str, str]) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True, timeout=180)


def check(language: str) -> None:
    examples = all_snippets(language)
    if not examples:
        raise SystemExit(f"No runnable {language} examples found")
    env = dict(os.environ)
    env.setdefault("CARGO_TARGET_DIR", str(REPO_ROOT / "bindings/rust/target"))
    with TemporaryDirectory(prefix="semq-docs-") as temp:
        root = Path(temp)
        if language == "rust":
            crate = root / "rust"
            (crate / "src/bin").mkdir(parents=True)
            (crate / "Cargo.toml").write_text(
                '[package]\nname = "semq-docs-examples"\nversion = "0.0.0"\nedition = "2021"\n'
                "[dependencies]\nsemq = { path = "
                + json.dumps(str(REPO_ROOT / "bindings/rust/semq"))
                + " }\n",
                encoding="utf-8",
            )
            for i, example in enumerate(examples):
                print(f"COMPILE example_{i}: {example.label}", flush=True)
                (crate / f"src/bin/example_{i}.rs").write_text(
                    example.source, encoding="utf-8"
                )
            run(
                [
                    "cargo",
                    "build",
                    "--quiet",
                    "--manifest-path",
                    str(crate / "Cargo.toml"),
                    "--bins",
                ],
                root,
                env,
            )
        elif language == "typescript":
            package = REPO_ROOT / "bindings/ts"
            if not (package / "dist/wasm/semq.wasm").is_file():
                raise SystemExit(
                    "Build TypeScript and copy src/wasm to dist/wasm first; see Installation."
                )
            (root / "node_modules/@semq").mkdir(parents=True)
            (root / "node_modules/@semq/sdk").symlink_to(
                package, target_is_directory=True
            )
            (root / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
        for i, example in enumerate(examples):
            print(f"CHECK {language} {example.label}", flush=True)
            work = root / f"run-{i}"
            work.mkdir()
            if language == "rust":
                suffix = ".exe" if os.name == "nt" else ""
                run(
                    [str(Path(env["CARGO_TARGET_DIR"]) / f"debug/example_{i}{suffix}")],
                    work,
                    env,
                )
            elif language == "go":
                (work / "go.mod").write_text(
                    "module semq-docs-example\n\ngo 1.21\n\n"
                    "require github.com/The-SEMQ-Group/semq/bindings/go v0.0.0\n"
                    "replace github.com/The-SEMQ-Group/semq/bindings/go => "
                    + json.dumps(str(REPO_ROOT / "bindings/go"))
                    + "\n",
                    encoding="utf-8",
                )
                (work / "main.go").write_text(example.source, encoding="utf-8")
                run(["go", "run", "."], work, env)
            else:
                source = work / "example.ts"
                source.write_text(example.source, encoding="utf-8")
                run(
                    [
                        "node",
                        str(package / "node_modules/typescript/bin/tsc"),
                        "--target",
                        "ES2022",
                        "--module",
                        "NodeNext",
                        "--moduleResolution",
                        "NodeNext",
                        "--strict",
                        "--skipLibCheck",
                        "--types",
                        "node",
                        "--typeRoots",
                        str(package / "node_modules/@types"),
                        str(source),
                    ],
                    work,
                    env,
                )
                run(["node", str(work / "example.js")], work, env)
    print(f"PASS: {len(examples)} {language} examples", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("language", choices=["rust", "go", "typescript"])
    check(parser.parse_args().language)
