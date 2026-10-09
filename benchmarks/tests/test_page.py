# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

import pytest

from benchmarks import floor_power, page


def test_every_result_the_page_reads_names_its_producer():
    assert set(page.PRODUCERS) == {
        "rebuild",
        "granularity",
        "floor-power",
        "quality",
        "size",
        "speed",
        "scale",
        "reproducibility",
    }


def test_a_missing_result_names_the_benchmark_that_writes_it(tmp_path, monkeypatch):
    monkeypatch.setattr(page, "RESULTS", tmp_path / "docs/assets/benchmarks/summary")
    monkeypatch.setattr(page, "ROOT", tmp_path)
    with pytest.raises(SystemExit) as stop:
        page.load("scale")
    assert str(stop.value) == (
        "benchmark page: docs/assets/benchmarks/summary/scale.json is missing. "
        "Run python -m benchmarks.scale to create it, then python -m benchmarks.page."
    )


FIXED_TOLERANCE = ("fp32_hash", "allclose_default", "bf16_fixed")


def small_report():
    def r(rate):
        return {"count": 0, "draws": 10, "rate": rate, "ci95": [0.0, 0.3]}

    detectors = dict.fromkeys(floor_power.DETECTORS, r(1.0))
    faults = {
        key: {**spec, "size_median_1_minus_cos": 0.2, "detectors": detectors}
        for key, spec in floor_power.fault_specs().items()
    }
    state = {
        "nulls": 2,
        "devices": ["cpu"],
        "equals_reference": True,
        "rows_changed": 0,
        "max_hamming": 0,
    }

    def pool(counts):
        return {
            "regime": {
                "nulls": 2,
                "distinct_states_including_reference": 1,
                "states": [state],
            },
            "false_alarms": {
                str(n): {
                    d: r(1.0 if d in FIXED_TOLERANCE else 0.0)
                    for d in floor_power.DETECTORS
                }
                for n in counts
            },
            "false_alarm_bounds": {
                str(n): {"floor_within": 2 / (n + 1), "floor_per_row": 3 / (n + 1)}
                for n in counts
            },
            "detection": {"20": faults},
            "synthetic": {"sigma": 4.5e-6},
            "example": {
                "nulls_in_floor": 20,
                "changed_rows": 241,
                "hamming_counts": {"1": 232, "2": 7, "260": 1, "267": 1},
                "faulted_hamming": [260, 267],
                "rows_ignored_by_p99": 2,
                "candidate_p99": 2,
                "floor_hamming": 2,
                "floor_max_hamming": 3,
                "within": True,
                "per_row": False,
            },
        }

    return {
        "hardware": {"machine": "Test CPU", "arch": "x86_64", "gpu": "Test GPU"},
        "results": {
            "draws": 10,
            "detection_n": 20,
            "pools": {"real": pool([20]), "varying": pool([3, 20])},
        },
    }


def test_power_panel_renders_from_a_small_report():
    text = "\n".join(page.power_panel(small_report()))
    assert "## False alarms and detection power" in text
    assert "states: all 2 matched the reference" in text
    assert "Hardware: CPU: Test CPU (x86_64) · GPU: Test GPU." in text
    assert "| Replace 2 documents |" in text
    assert "| 3 | 0% | 50.0% | 0% | 75.0% |" in text
    # The row-by-row example: what the p99 drops and what per-row compares.
    assert "⌊241/100⌋ = 2 most-changed rows, so it reads 2" in text
    assert "the p99 ignores these 2 rows" in text
    assert "floor max_hamming = 3: per-row flags any row above it" in text


def test_power_panel_refuses_false_alarms_its_text_does_not_describe():
    report = small_report()
    report["results"]["pools"]["real"]["false_alarms"]["20"]["floor_within"][
        "rate"
    ] = 0.05
    with pytest.raises(ValueError, match="no longer split"):
        page.power_panel(report)
