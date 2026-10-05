# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Shared helpers for the scale + concurrency stress-test suite.

Every test in this directory is marked ``@pytest.mark.slow`` so
``pytest tests/`` (the default) skips them. Run explicitly with::

    pytest tests/scale/ -m slow -v

or via the wrapper script::

    scripts/run-scale-benchmark.sh

Helpers exposed here:

* :func:`measure` — context manager that records wall time + peak
  RSS delta for a block of work.
* :func:`current_rss_mb` — current (not peak) RSS in megabytes.
* :func:`write_result` — dump a per-test JSON payload under
  ``tests/scale/results/``.
* Percentile helpers for latency-shaped tests.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

RESULTS_DIR = Path(__file__).parent / "results"


def current_rss_mb() -> float:
    """Return the process' resident set size in MB.

    Uses ``ps`` so we can call it from any thread without owning
    the GIL. Returns ``0.0`` on Windows (where the whole scale
    suite is a no-op)."""
    if sys.platform not in ("darwin", "linux"):
        return 0.0
    out = subprocess.check_output(
        ["ps", "-o", "rss=", "-p", str(os.getpid())], text=True,
    ).strip()
    # ps -o rss= gives KiB on both darwin and linux.
    return int(out) / 1024.0


@dataclass
class Measurement:
    """One measurement collected via :func:`measure`."""

    label: str
    elapsed_s: float = 0.0
    rss_before_mb: float = 0.0
    rss_after_mb: float = 0.0
    rss_delta_mb: float = 0.0
    extras: dict[str, Any] = field(default_factory=dict)


@contextmanager
def measure(label: str):
    """Context manager that records wall-clock time + RSS delta.

    Attach arbitrary metrics to the yielded object via
    ``m.extras[key] = value`` — those land in the JSON report."""
    m = Measurement(label=label)
    m.rss_before_mb = current_rss_mb()
    start = time.perf_counter()
    try:
        yield m
    finally:
        m.elapsed_s = time.perf_counter() - start
        m.rss_after_mb = current_rss_mb()
        m.rss_delta_mb = m.rss_after_mb - m.rss_before_mb


def percentiles(samples: list[float]) -> dict[str, float]:
    """Return p50/p95/p99/max for a list of samples."""
    import statistics as _s

    if not samples:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}
    sorted_s = sorted(samples)
    n = len(sorted_s)

    def _pct(p: float) -> float:
        idx = min(int(p * n), n - 1)
        return sorted_s[idx]

    return {
        "p50": _pct(0.50),
        "p95": _pct(0.95),
        "p99": _pct(0.99),
        "max": sorted_s[-1],
        "mean": _s.mean(sorted_s),
    }


def write_result(name: str, payload: dict[str, Any]) -> Path:
    """Write ``payload`` to ``tests/scale/results/<name>.json``.

    Overwrites on each run. The file is not committed by default
    (see ``.gitignore``); commit intentionally when publishing a
    benchmark milestone.
    """
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    import platform

    envelope = {
        "test": name,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": sys.version.split()[0],
        "os": platform.system(),
        "arch": platform.machine(),
        "result": payload,
    }
    dst = RESULTS_DIR / f"{name}.json"
    dst.write_text(json.dumps(envelope, indent=2, sort_keys=True))
    return dst


# ---------------------------------------------------------------------
# Pytest fixtures — inject helpers into tests without relative imports.
# ---------------------------------------------------------------------


@pytest.fixture
def scale_helpers():
    """Expose ``measure`` / ``percentiles`` / ``write_result`` to
    tests via a namespace object. Avoids relative imports so the
    test files stay pytest-native + free of package-init dance."""

    class _NS:
        measure = staticmethod(measure)
        percentiles = staticmethod(percentiles)
        write_result = staticmethod(write_result)
        current_rss_mb = staticmethod(current_rss_mb)

    return _NS
