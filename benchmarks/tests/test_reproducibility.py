# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

import json

import numpy as np
import pytest

from benchmarks import reproducibility as rep


def unit_rows(n: int, dim: int, seed: int = 0) -> np.ndarray:
    rows = np.random.default_rng(seed).standard_normal((n, dim))
    return (rows / np.linalg.norm(rows, axis=1, keepdims=True)).astype(np.float32)


def test_admission_rule_accepts_unit_rows_and_rejects_others():
    rows = unit_rows(3, 8)
    rows[1] *= np.float32(1.01)
    rows[2, 0] = np.float32(1e-40)  # a subnormal is flushed before the sum
    rows[2] /= np.float32(np.linalg.norm(rows[2]))
    assert rep.admitted(rows).tolist() == [True, False, True]


def test_identities_are_deterministic_and_complete():
    rows, ids = unit_rows(4, 8), ["d", "a", "c", "b"]
    first = rep.identities(rows, ids, dim=8)
    assert first == rep.identities(rows.copy(), list(ids), dim=8)
    assert sorted(first) == sorted(rep.CONFIGS)
    for value in first.values():
        assert value["config"]["dim"] == 8
        assert len(value["state_id"]) == len(value["content_digest"]) == 64
        assert len(value["file_sha256"]) == 64 and value["file_size"] > 0
    assert first["semq_quant2"]["state_id"] != first["semq_quant4"]["state_id"]


def test_fixture_round_trip(tmp_path):
    rows = unit_rows(3, rep.DIM)
    npz = tmp_path / "embeddings.npz"
    np.savez(npz, corpus=rows, corpus_ids=np.array(["10", "2", "3"]))
    out = tmp_path / "fixture"
    rep.build_fixture(npz, out, rows=3)
    vectors, ids, meta = rep.load_fixture(out)
    assert ids == ["10", "2", "3"] and meta["kind"] == "utf8"
    assert np.array_equal(vectors, rows)
    expected = json.loads((out / "expected.json").read_text())
    assert expected == rep.expected_document(out)
    assert expected["manifest"] == rep.MANIFEST and expected["rows"] == 3


def test_fixture_rejects_rows_outside_the_norm_rule(tmp_path):
    rows = unit_rows(2, rep.DIM) * np.float32(1.1)
    npz = tmp_path / "embeddings.npz"
    np.savez(npz, corpus=rows, corpus_ids=np.array(["1", "2"]))
    with pytest.raises(SystemExit, match="not admitted"):
        rep.build_fixture(npz, tmp_path / "fixture", rows=2)


def workflow() -> dict:
    return {
        "jobs": {
            "test": {
                "name": "${{ matrix.os }}",
                "strategy": {
                    "matrix": {
                        "include": [
                            {"os": "ubuntu-24.04"},
                            {"os": "windows-2025-vs2026"},
                        ]
                    }
                },
                "steps": [
                    {
                        "name": "Python tests",
                        "run": "pytest tests/unit tests/reproducibility -q",
                    }
                ],
            },
            "rust": {
                "name": "rust (${{ matrix.os }})",
                "strategy": {"matrix": {"include": [{"os": "macos-26"}]}},
                "steps": [
                    {
                        "name": "clippy",
                        "working-directory": "bindings/rust",
                        "run": "cargo clippy",
                    }
                ],
            },
            "go": {
                "name": "go (${{ matrix.os }})",
                "strategy": {"matrix": {"include": [{"os": "ubuntu-24.04-arm"}]}},
                "steps": [
                    {
                        "name": "go test",
                        "working-directory": "bindings/go",
                        "run": "go test ./...",
                    }
                ],
            },
            "ts": {
                "runs-on": "ubuntu-24.04",
                "name": "ts",
                "steps": [
                    {
                        "name": "Test",
                        "working-directory": "bindings/ts",
                        "run": "npm test",
                    }
                ],
            },
        }
    }


def test_ci_matrix_lists_only_jobs_that_run_the_test():
    rows = rep.ci_matrix(workflow())
    got = [(r["binding"], r["platform"], r["architecture"], r["ci_job"]) for r in rows]
    assert got == [
        ("python", "Linux", "x86_64", "ubuntu-24.04"),
        ("python", "Windows", "x86_64", "windows-2025-vs2026"),
        ("go", "Linux", "arm64", "go (ubuntu-24.04-arm)"),
        ("typescript", "WebAssembly (Node.js on Linux x86_64)", "wasm32", "ts"),
    ]
    assert all(r["status"] == "verified in CI" for r in rows)


def test_ci_matrix_of_the_real_workflow():
    pytest.importorskip("yaml")
    rows = rep.ci_matrix(rep.read_workflow())
    per_binding = {b: sum(r["binding"] == b for r in rows) for b in rep.BINDINGS}
    assert per_binding == {"python": 4, "rust": 4, "go": 4, "typescript": 1}
