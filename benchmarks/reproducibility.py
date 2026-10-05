"""Reproducibility matrix: the same real embeddings give the same state_id everywhere.

The fixture in tests/reproducibility holds 1,000 real SciFact e5-small-v2
embeddings, their BEIR document ids and expected.json: for each SEMQ
configuration of the page, the content_digest, the state_id, and the size and
SHA-256 of the saved .semq file, computed with the Python binding. Every
binding has a test that encodes the fixture with its own Codec and compares
with expected.json.

This script writes docs/assets/benchmarks/summary/reproducibility.json with three
parts: the expected identities, the CI matrix (every job of
.github/workflows/test.yml that runs one of those tests, read from the
workflow file itself), and the result of running the four tests on this
machine.

`--check` recomputes the expected identities from the fixture and the matrix
from the workflow, and fails when either differs from the committed file or
from expected.json. It does not rerun the local tests: that part records one
run on one machine.

`--build-fixture NPZ` rewrites the fixture from the frozen embeddings archive
(benchmarks/prepare_beir.py format). Run it only when the fixture must change.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from .run import ROOT, digest

SCHEMA = "semq-bench/reproducibility/1"
FIXTURE = ROOT / "tests" / "reproducibility"
WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"
OUTPUT = ROOT / "docs" / "assets" / "benchmarks" / "summary" / "reproducibility.json"
SOURCE = "~/.cache/semq-benchmarks/scifact-e5/embeddings.npz"

DIM = 384
ROWS = 1000
MANIFEST = {
    "encoder": "intfloat/e5-small-v2",
    "encoder_revision": "ffb93f3bd4047442299a41ebb6fa998a38507c52",
}
# id -> (operator, parameter): the configurations of the benchmark page.
CONFIGS = {
    "semq_quant2": ("quant", 2),
    "semq_quant4": ("quant", 4),
    "semq_quant8": ("quant", 8),
    "semq_phase16": ("phase", 16),
    "semq_orbit50": ("orbit", 50),
}

# Workflow runner label -> (platform, architecture).
RUNNERS = {
    "ubuntu-24.04": ("Linux", "x86_64"),
    "ubuntu-24.04-arm": ("Linux", "arm64"),
    "macos-26": ("macOS", "arm64"),
    "windows-2025-vs2026": ("Windows", "x86_64"),
}
# binding -> (workflow job, test file, predicate on a step that runs the test).
BINDINGS: dict[str, tuple[str, str, Any]] = {
    "python": (
        "test",
        "tests/reproducibility/test_reproducibility.py",
        lambda step: "pytest" in step.get("run", "")
        and "tests/reproducibility" in step.get("run", ""),
    ),
    "rust": (
        "rust",
        "bindings/rust/semq/tests/reproducibility.rs",
        lambda step: step.get("working-directory") == "bindings/rust"
        and step.get("run", "").strip().startswith("cargo test"),
    ),
    "go": (
        "go",
        "bindings/go/reproducibility_test.go",
        lambda step: step.get("working-directory") == "bindings/go"
        and step.get("run", "").strip().startswith("go test"),
    ),
    "typescript": (
        "ts",
        "bindings/ts/test/reproducibility.test.ts",
        lambda step: step.get("working-directory") == "bindings/ts"
        and step.get("run", "").strip() == "npm test",
    ),
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def admitted(vectors: np.ndarray) -> np.ndarray:
    """SEMQ's admission rule per row (docs/reference/contracts.md, Input rows).

    Subnormals become +0.0, then the squares are summed in binary64 in index
    order (np.cumsum is sequential) and the row passes when |s - 1| <= 2^-10.
    """
    x = np.where(np.abs(vectors) < np.float32(2.0**-126), np.float32(0.0), vectors)
    squares = x.astype(np.float64) ** 2
    s = np.cumsum(squares, axis=1)[:, -1]
    return np.asarray(np.abs(s - 1.0) <= 2.0**-10)


def load_fixture(directory: Path = FIXTURE) -> tuple[np.ndarray, list[str], dict]:
    meta = json.loads((directory / "ids.json").read_text(encoding="utf-8"))
    raw = (directory / "vectors.f32").read_bytes()
    vectors = np.frombuffer(raw, dtype="<f4").astype(np.float32)
    vectors = vectors.reshape(meta["rows"], meta["dim"])
    return vectors, list(meta["values"]), meta


def identities(vectors: np.ndarray, ids: list[str], dim: int = DIM) -> dict:
    """content_digest, state_id and the saved file of every configuration."""
    from semq import Codec, CodecConfig

    out = {}
    for name, (operator, parameter) in CONFIGS.items():
        config = getattr(CodecConfig, operator)(dim, parameter)
        state = Codec(config).encode(
            ids=ids, vectors=vectors, manifest=dict(MANIFEST), id_kind="utf8"
        )
        buffer = io.BytesIO()
        state.save(buffer)
        data = buffer.getvalue()
        out[name] = {
            "config": {"operator": operator, "dim": dim, "parameter": parameter},
            "content_digest": state.content_digest.hex(),
            "state_id": state.state_id.hex(),
            "file_size": len(data),
            "file_sha256": sha256(data),
        }
    return out


def expected_document(directory: Path = FIXTURE) -> dict:
    vectors, ids, meta = load_fixture(directory)
    return {
        "manifest": dict(MANIFEST),
        "id_kind": "utf8",
        "rows": len(ids),
        "dim": meta["dim"],
        "vectors_sha256": digest(directory / "vectors.f32"),
        "configs": identities(vectors, ids, meta["dim"]),
    }


def write_text(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def build_fixture(npz: Path, directory: Path = FIXTURE, rows: int = ROWS) -> None:
    with np.load(npz, allow_pickle=False) as archive:
        corpus = np.asarray(archive["corpus"][:rows], dtype=np.float32)
        ids = [str(value) for value in archive["corpus_ids"][:rows]]
    if corpus.shape != (rows, DIM):
        raise SystemExit(f"expected {rows} x {DIM} corpus rows, got {corpus.shape}")
    rejected = np.flatnonzero(~admitted(corpus))
    if rejected.size:
        raise SystemExit(
            f"rows not admitted by the norm rule: {rejected[:10].tolist()}"
        )
    if len(set(ids)) != rows:
        raise SystemExit("duplicate ids in the selected rows")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "vectors.f32").write_bytes(corpus.astype("<f4").tobytes())
    write_text(
        directory / "ids.json",
        {
            "kind": "utf8",
            "rows": rows,
            "dim": DIM,
            "values": ids,
            "source": {
                "file": SOURCE,
                "sha256": digest(npz),
                "array": "corpus",
                "ids_array": "corpus_ids",
                "selection": f"rows 0..{rows - 1} (lexical BEIR document id order)",
                "admission": "every row passes |sum(x_i^2) - 1| <= 2^-10 in binary64",
            },
        },
    )
    write_text(directory / "expected.json", expected_document(directory))


def expand_matrix(text: str, values: dict) -> str:
    """Replace each ${{ matrix.KEY }} in a job name with the entry's value."""

    def value(match: re.Match[str]) -> str:
        return str(values.get(match[1], ""))

    return re.sub(r"\$\{\{ matrix\.(\w+) \}\}", value, text)


def ci_matrix(workflow: dict) -> list[dict]:
    """Every (platform, architecture, binding) whose CI job runs the test."""
    jobs = workflow.get("jobs", {})
    rows = []
    for binding, (job_id, test_file, runs_test) in BINDINGS.items():
        job = jobs.get(job_id)
        if job is None:
            continue
        steps = [s for s in job.get("steps", []) if runs_test(s)]
        if not steps or not (ROOT / test_file).is_file():
            continue
        include = job.get("strategy", {}).get("matrix", {}).get("include")
        entries = include if include else [{}]
        for entry in entries:
            label = entry.get("os", job.get("runs-on"))
            platform_name, arch = RUNNERS[label]
            name = expand_matrix(str(job.get("name", job_id)), {"os": label, **entry})
            if binding == "typescript":
                arch = "wasm32"
                platform_name = (
                    f"WebAssembly (Node.js on {platform_name} {RUNNERS[label][1]})"
                )
            rows.append(
                {
                    "platform": platform_name,
                    "architecture": arch,
                    "binding": binding,
                    "runner": label,
                    "ci_job": name,
                    "ci_step": steps[0].get("name", ""),
                    "test": test_file,
                    "status": "verified in CI",
                }
            )
    return rows


def read_workflow(path: Path = WORKFLOW) -> dict:
    import yaml

    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def local_commands(rust_lib: Path) -> dict[str, tuple[list[str], Path, dict]]:
    library = os.environ.get("SEMQ_LIBRARY_PATH", "")
    return {
        "python": (
            [sys.executable, "-m", "pytest", "tests/reproducibility", "-q"],
            ROOT,
            {"SEMQ_LIBRARY_PATH": library},
        ),
        "rust": (
            ["cargo", "test", "-p", "semq", "--test", "reproducibility"],
            ROOT / "bindings" / "rust",
            {
                "SEMQ_LIBRARY_PATH": str(rust_lib),
                "DYLD_LIBRARY_PATH": str(rust_lib),
                "LD_LIBRARY_PATH": str(rust_lib),
            },
        ),
        "go": (
            ["go", "test", "-race", "-run", "TestReproducibility", "."],
            ROOT / "bindings" / "go",
            {},
        ),
        "typescript": (
            ["npx", "vitest", "run", "test/reproducibility.test.ts"],
            ROOT / "bindings" / "ts",
            {},
        ),
    }


def run_local(rust_lib: Path) -> dict:
    results = {}
    for binding, (command, cwd, extra) in local_commands(rust_lib).items():
        env = {**os.environ, **extra}
        shown = [f"{k}={v}" for k, v in extra.items()]
        shown += ["python" if part == sys.executable else part for part in command]
        text = " ".join(shown).replace(str(ROOT) + os.sep, "$REPO/")
        record = {"command": f"(cd {cwd.relative_to(ROOT)} && {text})"}
        try:
            done = subprocess.run(
                command, cwd=cwd, env=env, capture_output=True, text=True
            )
        except FileNotFoundError as error:
            record.update(status="not_run", reason=str(error))
        else:
            output = done.stdout + done.stderr
            skipped = "reproducibility fixture missing" in output
            if done.returncode == 0 and not skipped:
                record["status"] = "pass"
            else:
                record["status"] = "skipped" if skipped else "fail"
                record["output_tail"] = output[-2000:]
        results[binding] = record
    return results


def hardware() -> dict:
    machine = platform.processor() or platform.machine()
    if sys.platform == "darwin":
        try:
            machine = subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"], text=True
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            pass
    return {
        "machine": machine,
        "os": platform.platform(),
        "arch": platform.machine(),
        "cpu_threads": os.cpu_count(),
        "gpu": "not used by this metric",
    }


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def document(expected: dict, matrix: list[dict], local: dict, meta: dict) -> dict:
    return {
        "schema": SCHEMA,
        "sdk_commit": git("rev-parse", "HEAD"),
        "working_tree_dirty": bool(git("status", "--porcelain")),
        "hardware": hardware(),
        "generated_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "inputs": {
            "scifact-e5": {
                "sha256": meta["source"]["sha256"],
                "source": f"{meta['source']['file']} ({meta['source']['selection']})",
            },
            "fixture_vectors": {
                "sha256": digest(FIXTURE / "vectors.f32"),
                "source": "tests/reproducibility/vectors.f32",
            },
            "fixture_ids": {
                "sha256": digest(FIXTURE / "ids.json"),
                "source": "tests/reproducibility/ids.json",
            },
            "workflow": {
                "sha256": digest(WORKFLOW),
                "source": ".github/workflows/test.yml",
            },
        },
        "results": {
            "claim": "the same real embeddings give the same content_digest, state_id "
            "and file bytes on every platform and in every binding",
            "expected": expected,
            "ci_matrix": matrix,
            "local": {"machine": hardware()["machine"], "bindings": local},
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--build-fixture", type=Path, metavar="NPZ")
    parser.add_argument("--rust-lib", type=Path, default=ROOT / "build-trim-rel")
    args = parser.parse_args()

    if args.build_fixture:
        build_fixture(args.build_fixture.expanduser())
    _, _, meta = load_fixture()
    expected = expected_document()
    matrix = ci_matrix(read_workflow())

    if args.check:
        failures = []
        committed_expected = json.loads((FIXTURE / "expected.json").read_text("utf-8"))
        if committed_expected != expected:
            failures.append("tests/reproducibility/expected.json")
        committed = json.loads(args.output.read_text(encoding="utf-8"))["results"]
        for key, value in (("expected", expected), ("ci_matrix", matrix)):
            if committed.get(key) != value:
                failures.append(f"{args.output}: results.{key}")
        if failures:
            raise SystemExit("out of date: " + ", ".join(failures))
        print("reproducibility: up to date")
        return

    local = run_local(args.rust_lib.resolve())
    write_text(args.output, document(expected, matrix, local, meta))
    print(json.dumps(local, indent=2))


if __name__ == "__main__":
    main()
