# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""The scale harness on tiny inputs: deterministic data and every operation."""

import numpy as np

from benchmarks import scale


def test_inputs_are_deterministic_unit_rows():
    a, b = scale.chunk(0, 64), scale.chunk(0, 64)
    assert np.array_equal(a, b)
    assert np.allclose(np.linalg.norm(a, axis=1), 1, atol=1e-5)
    assert not np.array_equal(scale.chunk(1, 64), a)
    assert np.array_equal(scale.vectors(10, 20), a[10:30])


def test_variant_moves_only_the_picked_rows():
    base = scale.chunk(0, 250)
    moved = scale.variant(base, 0, 100, 0, 0.5, salt=1)
    changed = np.flatnonzero(np.any(moved != base, axis=1))
    assert changed.tolist() == [0, 100, 200]
    assert np.allclose(np.linalg.norm(moved, axis=1), 1, atol=1e-5)
    assert np.array_equal(scale.chunk(0, 250), base)  # input not mutated


def test_every_operation_in_fresh_processes(tmp_path):
    result = scale.measure(200, tmp_path)
    ops = result["operations"]
    assert set(ops) == {"encode", "save", "load", "diff", "concat", "floor", "gate"}
    for op in ops.values():
        assert op["seconds"] >= 0
        assert op["peak_rss_bytes"] >= op["peak_rss_before_bytes"] > 0
    assert ops["diff"]["modified_rows"] == 2
    assert ops["diff"]["changed_rows"] + ops["diff"]["unchanged_rows"] == 200
    assert ops["floor"]["nulls"] == 3
    assert ops["gate"]["nulls"] == 3
    assert ops["gate"]["candidate_changed_rows"] == ops["diff"]["changed_rows"]
    assert ops["gate"]["within_floor"] is False
    files = result["files"]
    assert files["semq_bytes"] == 96 + 200 * (288 + 8)
    assert files["npy_float32_bytes"] == 128 + 200 * 768 * 4
    assert files["npy_float16_bytes"] == 128 + 200 * 768 * 2
    assert list(tmp_path.iterdir()) == []  # temporary files removed
