# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Floor power must compute its fixed tolerance, intervals and flags exactly."""

import numpy as np
import pytest

from benchmarks import floor_power


def test_bf16_spacing_is_seven_mantissa_bits_below_the_exponent():
    values = np.array([1.0, 0.75, -0.5, 3.0, 0.0])
    spacing = floor_power.bf16_spacing(values)
    assert spacing[:4].tolist() == [2.0**-7, 2.0**-8, 2.0**-8, 2.0**-6]
    assert spacing[4] > 0


def test_clopper_pearson_matches_closed_forms_at_the_edges():
    lo, hi = floor_power.clopper_pearson(0, 10)
    assert lo == 0.0 and hi == pytest.approx(1 - 0.025 ** (1 / 10), abs=1e-9)
    lo, hi = floor_power.clopper_pearson(10, 10)
    assert hi == 1.0 and lo == pytest.approx(0.025 ** (1 / 10), abs=1e-9)


def test_clopper_pearson_tails_hold_inside():
    k, n = 7, 50
    lo, hi = floor_power.clopper_pearson(k, n)
    assert 1 - floor_power.binomial_cdf(k - 1, n, lo) == pytest.approx(0.025)
    assert floor_power.binomial_cdf(k, n, hi) == pytest.approx(0.025)
    assert lo < k / n < hi


def test_row_statistics_aggregate_to_the_whole_array_checks():
    rng = np.random.default_rng(0)
    ref = rng.standard_normal((6, 8)).astype(np.float32)
    ref /= np.linalg.norm(ref, axis=1, keepdims=True)
    x = ref.copy()
    x[2, 3] += np.float32(1e-3)
    spacing = floor_power.bf16_spacing(ref)
    stats = floor_power.Rows(x, ref, spacing).summary()
    assert stats["allclose"] == bool(np.allclose(x, ref))
    assert stats["bytes_equal"] is False
    assert stats["max_abs"] == pytest.approx(float(np.abs(x - ref).max()))
    replaced = floor_power.Rows(ref, ref, spacing).replaced(
        np.array([2]), floor_power.Rows(x[[2]], ref[[2]], spacing[[2]])
    )
    assert replaced.summary() == stats


def test_calibrated_checks_flag_only_values_above_every_null():
    nulls = [
        {"max_abs": 1.0, "cosine_max": 0.1},
        {"max_abs": 2.0, "cosine_max": 0.3},
    ]
    base = {"allclose": True, "bf16_exceeded": False, "bytes_equal": True}
    tie = floor_power.float_flags({**base, "max_abs": 2.0, "cosine_max": 0.3}, nulls)
    above = floor_power.float_flags({**base, "max_abs": 2.5, "cosine_max": 0.2}, nulls)
    assert not tie["max_abs_calibrated"] and not tie["cosine_calibrated"]
    assert above["max_abs_calibrated"] and not above["cosine_calibrated"]
