# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Readable output must retain comparability and missing-label semantics."""

import pytest

from benchmarks.render import render
from benchmarks.run import evaluate, load_data


def test_summary_keeps_profiles_and_missing_labels_separate(tmp_path):
    config = {
        "seed": 1,
        "k": [1],
        "query_batch_size": 2,
        "direction_scoring": True,
        "methods": [{"id": "fp32", "name": "fp32"}],
        "synthetic": {"corpus_rows": 4, "query_rows": 2, "fit_rows": 4, "dim": 4},
    }
    arrays, dataset = load_data(config, None)
    methods = evaluate(config, arrays, tmp_path)
    report = {
        "schema_version": 2,
        "suite": "codec_quality",
        "status": "complete",
        "dataset": dataset,
        "methods": methods,
        "scoring_profile": "original_query_ip_f64_no_renormalization",
    }
    summary = render(report)
    assert "not semantic-quality evidence" in summary
    assert "labels_unavailable" in summary
    assert "## Raw reconstruction" in summary
    assert "## Normalized direction" in summary
    assert "not_requested" in summary
    methods[0]["quality"] = {"status": "not_comparable", "reason": "decoder limit"}
    assert "not_comparable: decoder limit" in render(report)
    assert "NSE:" not in render(report)


@pytest.mark.parametrize(
    "report", [{}, {"schema_version": 1}, {"schema_version": 2, "status": "failed"}]
)
def test_incomplete_or_old_reports_are_rejected(report):
    with pytest.raises(ValueError, match="complete codec_quality"):
        render(report)
