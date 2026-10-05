# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

import pytest

from benchmarks import page


def test_every_result_the_page_reads_names_its_producer():
    assert set(page.PRODUCERS) == {
        "rebuild",
        "granularity",
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
