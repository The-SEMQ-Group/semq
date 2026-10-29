# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
"""How the p99 check of ``within`` relates to the per-row check.

The p99 of ``m`` changed rows is the ``k``-th smallest hamming with
``k = m - floor(m / 100)``: the largest when ``m < 100``. A floor's
``hamming`` never exceeds its ``max_hamming``, so below 100 changed rows a
candidate within the floor also passes the per-row check.
"""

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from semq import CodecConfig, Encoding, Floor

DIM = 8
ROWS = 200
CONFIG = CodecConfig.orbit(DIM, 50)  # one byte per unit, symbols 0..18
REFERENCE_ROWS = (np.arange(ROWS * DIM, dtype=np.uint8) % 19).reshape(ROWS, DIM)
IDS = np.arange(ROWS, dtype=np.uint64)
REFERENCE = Encoding(IDS, REFERENCE_ROWS, CONFIG)


def rebuilt(changes: dict[int, int]) -> Encoding:
    """The reference with row ``r`` changed in its first ``h`` units."""
    rows = REFERENCE_ROWS.copy()
    for row, hamming in changes.items():
        rows[row, :hamming] = (rows[row, :hamming] + 1) % 19
    return Encoding(IDS, rows, CONFIG)


@st.composite
def null_changes(draw):
    """Many rows moved by one unit and a few by more, so that from 100
    changed rows the p99 can sit below the largest hamming."""
    noise = draw(st.one_of(st.integers(100, 150), st.integers(0, 99)))
    outliers = draw(st.dictionaries(st.integers(noise, ROWS - 1), st.integers(1, DIM), max_size=3))
    return {**dict.fromkeys(range(noise), 1), **outliers}


@settings(max_examples=200, deadline=None)
@given(st.lists(null_changes(), min_size=1, max_size=4), st.data())
def test_within_implies_per_row_below_100_changed_rows(nulls, data):
    floor = Floor.measure([REFERENCE.diff(rebuilt(c)) for c in nulls], per_row=True)
    assert floor.hamming <= floor.max_hamming
    count = data.draw(st.integers(0, min(99, floor.changed_rows)))
    rows = data.draw(st.lists(st.integers(0, ROWS - 1), min_size=count, max_size=count, unique=True))
    top = data.draw(st.integers(1, DIM))
    candidate = REFERENCE.diff(rebuilt({row: data.draw(st.integers(1, top)) for row in rows}))
    assert len(candidate.changed) < 100
    if candidate.within(floor):
        assert candidate.evaluate(floor, per_row=True).passed


def test_per_row_catches_what_the_p99_ignores_from_100_changed_rows():
    floor = Floor.measure([REFERENCE.diff(rebuilt(dict.fromkeys(range(150), 1)))], per_row=True)
    assert (floor.hamming, floor.max_hamming) == (1, 1)
    # 99 changed rows: the p99 is the largest hamming, so within already fails.
    below = REFERENCE.diff(rebuilt({**dict.fromkeys(range(98), 1), 98: DIM}))
    assert not below.within(floor)
    # 100 changed rows: the p99 ignores the most changed row; per-row does not.
    at = REFERENCE.diff(rebuilt({**dict.fromkeys(range(99), 1), 99: DIM}))
    assert at.within(floor)
    verdict = at.evaluate(floor, per_row=True)
    assert not verdict.passed and verdict.reasons == ("row_above_max",) and verdict.rows == [99]
