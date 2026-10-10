# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""The rebuild pair must gate, compare and count exactly as documented."""

import numpy as np
import pytest

from benchmarks import rebuild


def unit(rng, n, dim):
    x = rng.standard_normal((n, dim))
    return (x / np.linalg.norm(x, axis=1, keepdims=True)).astype(np.float32)


def nudge(x, rows, scale, seed):
    rng = np.random.default_rng(seed)
    y = x.astype(np.float64)
    y[rows] += scale * rng.standard_normal((len(rows), x.shape[1]))
    y /= np.linalg.norm(y, axis=1, keepdims=True)
    return y.astype(np.float32)


def test_p99_is_nearest_rank():
    assert rebuild.p99([]) == 0
    assert rebuild.p99([5]) == 5
    assert rebuild.p99(list(range(1, 101))) == 99
    assert rebuild.p99(list(range(1, 200))) == 198


def test_run_spec_only_overrides_listed_fields():
    ref = rebuild.run_spec(rebuild.REFERENCE)
    assert ref["device"] == "cpu" and ref["batch_size"] == 32 and ref["normalize"]
    v1 = rebuild.run_spec("change_model_v1")
    assert v1["model"] == rebuild.PREVIOUS_MODEL
    assert {k: v for k, v in v1.items() if k != "model"} == {
        k: v for k, v in ref.items() if k != "model"
    }
    assert rebuild.FLOOR_NULLS == ["null_cpu_b128", "null_gpu_b32", "null_gpu_b128"]
    assert rebuild.HELD_OUT in rebuild.CANDIDATES
    assert "null_cpu_b1" in rebuild.CANDIDATES


def test_simple_checks_and_envelope_verdicts():
    rng = np.random.default_rng(0)
    ref = unit(rng, 50, 8)
    same = ref.copy()
    tiny = ref.copy()
    tiny[3, 0] = np.nextafter(tiny[3, 0], np.float32(2))
    big = nudge(ref, list(range(10)), 0.5, 2)
    checks = {
        "n1": rebuild.simple_checks(ref, same),
        "n2": rebuild.simple_checks(ref, tiny),
        "c": rebuild.simple_checks(ref, big),
    }
    assert checks["n1"]["sha256_equal"] and checks["n1"]["max_abs_diff"] == 0.0
    assert not checks["n2"]["sha256_equal"] and checks["n2"]["allclose_default"]
    assert checks["c"]["cosine_below_share"] == pytest.approx(0.2)
    verdicts = rebuild.simple_verdicts(checks, ["n1", "n2"])
    flags = verdicts["flags"]
    assert flags["n2"]["sha256"] and not flags["n2"]["allclose"]
    assert not flags["n2"]["max_abs_diff_vs_null_envelope"]
    assert flags["c"]["max_abs_diff_vs_null_envelope"]
    assert flags["c"]["cosine_share_vs_null_envelope"]
    errors = rebuild.classify_verdicts(
        flags, {"n1": "n", "n2": "n", "c": "real_change"}
    )
    assert errors["sha256"] == {
        "false_alarms_on_nulls": ["n2"],
        "missed_real_changes": [],
    }
    assert errors["allclose"]["false_alarms_on_nulls"] == []


def test_gate_passes_held_out_null_and_rejects_change():
    rng = np.random.default_rng(3)
    ref = unit(rng, 200, 16)
    arrays = {
        "ref": ref,
        "n1": nudge(ref, [1], 0.05, 10),
        "n2": nudge(ref, [2], 0.05, 11),
        "n3": nudge(ref, [3], 0.05, 12),
        "held": ref.copy(),
        "change": nudge(ref, list(range(100)), 1.0, 13),
    }
    manifest = {"encoder": "e", "encoder_revision": "1"}
    manifests = dict.fromkeys(arrays, manifest)
    gates = rebuild.gate_all(
        arrays,
        "ref",
        ["n1", "n2", "n3"],
        ["held", "change"],
        manifests,
        ["semq_quant4"],
    )["semq_quant4"]
    assert gates["floor"]["nulls"] == 3
    assert gates["candidates"]["held"]["within"]
    assert gates["candidates"]["held"]["rows_changed"] == 0
    assert not gates["candidates"]["change"]["within"]
    assert gates["candidates"]["change"]["rows_changed"] > 50
    assert all(s["within"] for s in gates["floor_nulls"].values())
    renamed = {**manifests, "held": {"encoder": "e", "encoder_revision": "2"}}
    gated = rebuild.gate_all(
        arrays, "ref", ["n1", "n2", "n3"], ["held"], renamed, ["semq_quant4"]
    )["semq_quant4"]["candidates"]["held"]
    assert not gated["within"] and gated["manifest_changed"] == ["encoder_revision"]


def test_every_config_id_builds():
    for config_id in rebuild.CONFIGS:
        assert rebuild.semq_config(config_id, 16).dim == 16
