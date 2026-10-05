# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""The speed harness on tiny inputs: timing, baselines, parsing, overhead."""

import os

import numpy as np
import pytest

from benchmarks import speed


def test_timed_warms_up_then_takes_the_median():
    calls = []
    timing = speed.timed(lambda: calls.append(1), 3)
    assert len(calls) == 4
    assert len(timing["runs_seconds"]) == 3
    assert timing["median_seconds"] == sorted(timing["runs_seconds"])[1]
    rate = speed.throughput({"runs_seconds": [2.0], "median_seconds": 2.0}, 10)
    assert rate["vectors_per_second"] == 5.0
    assert rate["seconds_per_vector"] == 0.2


def test_numpy_baselines_round_trip():
    vectors = speed.unit_rows(16, 32)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-5)
    codes, scale = speed.int8_encode(vectors)
    assert codes.dtype == np.int8
    assert np.abs(speed.int8_decode(codes, scale) - vectors).max() <= scale.max()
    bits = speed.binary_encode(vectors)
    assert bits.shape == (16, 4)
    assert np.array_equal(speed.binary_decode(bits, 32), np.where(vectors > 0, 1, -1))
    result = speed.numpy_speed((32,), 16, 1)
    assert set(result["32"]) == {"fp16", "int8", "binary"}


def test_semq_speed_reports_only_confirmed_backends():
    results, default = speed.semq_speed((32,), 16, 1)
    assert default
    configs = results["32"]
    assert set(configs) == {name for name, _, _ in speed.SEMQ_CONFIGS}
    for entry in configs.values():
        assert "scalar" in entry["backends"]
        assert entry["default_backend"] in entry["backends"]
        assert len({row["content_digest"] for row in entry["backends"].values()}) == 1
        for backend in entry["backends"]:
            assert backend in speed.candidate_backends()
    assert "SEMQ_FORCE_BACKEND" not in os.environ


def test_make_codec_restores_a_preset_backend(monkeypatch):
    from semq import CodecConfig

    monkeypatch.setenv("SEMQ_FORCE_BACKEND", "scalar")
    assert speed.make_codec(CodecConfig.orbit(8), "scalar").backend == "scalar"
    assert os.environ["SEMQ_FORCE_BACKEND"] == "scalar"


def test_parse_c_bench_keeps_medians():
    def entry(name, aggregate, ips):
        return {
            "name": f"{name}_{aggregate}",
            "run_name": name,
            "run_type": "aggregate",
            "aggregate_name": aggregate,
            "items_per_second": ips,
        }

    name = "encode/quant/scalar/dim:768/rows:100000/manual_time"
    report = {
        "benchmarks": [
            entry(name, "mean", 1.0),
            entry(name, "median", 2.0),
            entry("decode/orbit/neon/dim:768/rows:100000", "median", 3.0),
        ]
    }
    parsed = speed.parse_c_bench(report)["768"]
    assert parsed["semq_quant4"]["scalar"]["encode"]["items_per_second"] == 2.0
    assert parsed["semq_orbit50"]["neon"]["decode"]["rows"] == 100000


def test_c_bench_missing_binary_is_not_run(tmp_path):
    result = speed.c_bench(tmp_path / "bench_encode", 768, 100000, 5)
    assert result["status"] == "not_run"
    assert "cmake --build build-bench --target bench_encode" in result["command"]


def test_overhead_is_percent_of_embedding_time():
    semq = {
        "768": {
            "semq_quant4": {
                "default_backend": "scalar",
                "backends": {"scalar": {"encode": {"seconds_per_vector": 1e-6}}},
            }
        }
    }
    embedding = {
        "status": "ok",
        "devices": {
            "mps": {"status": "ok", "seconds_per_vector": 1e-3},
            "cpu": {"status": "not_run"},
        },
    }
    row = speed.overhead(semq, embedding)["configs"]["semq_quant4"]
    assert row["overhead_pct_vs_mps"] == pytest.approx(0.1)
    assert "overhead_pct_vs_cpu" not in row
    assert speed.overhead(semq, None)["status"] == "not_run"
