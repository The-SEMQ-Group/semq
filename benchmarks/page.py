# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Render the benchmark pages from frozen benchmark results.

Run ``python -m benchmarks.page`` to regenerate the public pages. The result
files remain the source of truth; ``--check`` detects a stale rendering.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "docs/assets/benchmarks/summary"

SCENARIOS = (
    ("null_mps_b64", "GPU rebuild, different batch size"),
    ("null_cpu_b1", "CPU rebuild, one document per batch"),
    ("change_model_v1", "Previous encoder revision"),
    ("change_fp16_mps", "Half precision"),
    ("change_max_length_128", "128-token truncation"),
    ("change_cls_pooling", "CLS instead of mean pooling"),
    ("change_unnormalized_renorm64", "Normalization moved after the model"),
)


SIMPLE_CHECKS = {
    "sha256": "Hash of the FP32 bytes",
    "allclose": "`np.allclose`, default tolerances",
    "cosine_any_below": "Any row with cosine below 0.9999",
    "max_abs_diff_vs_null_envelope": "Largest absolute difference, calibrated on the nulls",
    "semq_quant4": "SEMQ diff against its floor",
}
# The real changes a check can miss, and what each one changed. The
# normalization case moves no coordinate by more than 3e-8 and is not counted.
REAL_CHANGES = {
    "change_model_v1": "the model",
    "change_fp16_mps": "the precision",
    "change_max_length_128": "the input",
    "change_cls_pooling": "the pooling",
}


# The command that writes each result file the page reads.
PRODUCERS = {
    "rebuild": "python -m benchmarks.rebuild",
    "granularity": "python -m benchmarks.granularity",
    "quality": "python -m benchmarks.run, then python -m benchmarks.quality RUN_DIR [RUN_DIR ...]",
    "speed": "python -m benchmarks.speed measure",
    "scale": "python -m benchmarks.scale",
    "reproducibility": "python -m benchmarks.reproducibility",
    "size": "python -m benchmarks.size",
}


def load(name: str) -> dict[str, Any]:
    """A frozen result file. A missing file stops the page instead of leaving a
    section empty, and names the benchmark that writes it."""
    path = RESULTS / f"{name}.json"
    if not path.is_file():
        producer = PRODUCERS.get(name, f"the benchmark that writes {name}.json")
        raise SystemExit(
            f"benchmark page: {path.relative_to(ROOT)} is missing. Run {producer} to create it, "
            "then python -m benchmarks.page."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def percent(value: float) -> str:
    if value == 0:
        return "0%"
    if value < 1:
        return f"{value:.2f}%"
    if value >= 99.95:
        return "100%"
    return f"{value:.1f}%"


def table(header: list[str], rows: list[list[str]], align: str) -> list[str]:
    sep = ["---" if a == "-" else "---:" for a in align]
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(sep) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines + [""]


def rebuild_panel(data: dict[str, Any]) -> list[str]:
    results = data["results"]
    config = results["headline"]["config"]
    experiment = results["semq"][config]
    floor = experiment["floor"]
    lines = [
        "## Rebuild gate",
        "",
        "A second encoding of 5,183 SciFact documents with `e5-small-v2`. "
        "The floor comes from three unchanged rebuilds; each candidate is "
        "compared with the same reference state. Bar length shows the share "
        "of rows with different symbols. The verdict also considers the floor "
        "and manifest.",
        "",
        '<div class="semq-scenarios">',
    ]
    for key, label in SCENARIOS:
        candidate = experiment["candidates"][key]
        changed = candidate["rows_changed_pct"]
        status = "within floor" if candidate["within"] else "outside floor"
        css = "pass" if candidate["within"] else "fail"
        lines.extend(
            [
                f'<div class="semq-scenario is-{css}">',
                f'<div class="semq-scenario__head"><strong>{label}</strong><span>{percent(changed)} · {status}</span></div>',
                f'<div class="semq-scenario__track"><span style="width:{changed:.2f}%;min-width:{2 if changed > 0 else 0}px"></span></div>',
                "</div>",
            ]
        )
    lines += [
        "</div>",
        "",
        f"The observed floor for quant with four bins was {floor['changed_rows']} of "
        f"{floor['total_rows']:,} rows and a hamming bound of {floor['hamming']}, "
        f"measured from {floor['nulls']} unchanged rebuilds. One corpus and model "
        "family cannot establish a general noise floor.",
        "",
        "[Full rebuild measurements](../assets/benchmarks/summary/rebuild.json) · "
        "[Run the gate yourself](../guides/gate-a-rebuild.md)",
        "",
    ]
    return lines


def simpler_panel(data: dict[str, Any]) -> list[str]:
    """The same runs judged with a float hash, allclose, a cosine threshold and
    a calibrated max-difference threshold, from ``results.errors``."""
    results = data["results"]
    nulls = [key for key in results["runs"] if key.startswith("null_")]
    rows = []
    for key, label in SIMPLE_CHECKS.items():
        errors = results["errors"][key]
        missed = [m for m in errors["missed_real_changes"] if m in REAL_CHANGES]
        detail = f" ({', '.join(REAL_CHANGES[m] for m in missed)})" if missed else ""
        rows.append(
            [
                label,
                f"{len(errors['false_alarms_on_nulls'])} of {len(nulls)}",
                f"{len(missed)} of {len(REAL_CHANGES)}{detail}",
            ]
        )
    return [
        "## Why not something simpler?",
        "",
        "The same runs checked with the tools a pipeline already has. A false alarm "
        "is a rebuild that changed nothing flagged as changed; a miss is a real change "
        "that passes.",
        "",
        *table(
            ["Check", "False alarms on rebuilds", "Real changes missed"], rows, "-rr"
        ),
        "Hashing the floats fails on every rebuild because GPUs and batch sizes change "
        "the last bits. A cosine threshold that ignores that noise also ignores a switch "
        "to half precision. A threshold on the largest difference can work, but it has "
        "to be calibrated on your own rebuilds, which is what the floor does, and it "
        "cannot say which rows moved.",
        "",
        '??? note "What the experiment does and does not show"',
        "",
        "    - What moves rows is the device, not the batch size: the three GPU runs flip "
        "the same few rows, and CPU runs with different batch sizes flip none. The "
        "held-out rebuild therefore resembles two of the floor's nulls.",
        "    - Normalizing after the model instead of inside it moves no coordinate by "
        "more than 3e-8; every check except the float hash treats it as unchanged, "
        "and it is not counted as a real change above.",
        "    - The previous model revision also changes the manifest, which alone fails "
        "the gate. It is caught by its rows too: scored with an unchanged manifest, as "
        "a pipeline that forgot to update it would, it still changes 100% of rows.",
        "    - One corpus and one model family; the floor is an envelope of what was "
        "observed here, not a prediction for other pipelines.",
        "",
        "Source: [`rebuild.json`](../assets/benchmarks/summary/rebuild.json), produced by "
        "`python -m benchmarks.rebuild`.",
        "",
    ]


def rows_panel(data: dict[str, Any]) -> list[str]:
    """Edited documents against distribution-drift checks, from ``results.per_k``."""
    results = data["results"]
    head = results["headline"]
    rows = []
    for key in sorted(results["per_k"], key=float):
        k = results["per_k"][key]
        drift, semq = k["drift"], k["semq"]
        rows.append(
            [
                f"{float(key):g}% ({k['rows_edited']:,} rows)",
                f"{drift['centroid_cosine_distance']:.1e} · "
                + ("drift" if drift["centroid_cosine_drift"] else "no drift"),
                f"{drift['classifier_roc_auc']:.2f} · "
                + ("**drift**" if drift["classifier_drift"] else "no drift"),
                f"{semq['ids_reported']:,} ids · recall {semq['recall']:.3f}",
            ]
        )
    return [
        "## Which rows changed?",
        "",
        f"Edit {head['percent']:g}% of the corpus ({head['rows_edited']} documents cut to "
        "their first half and embedded again). Distribution drift, the check embedding "
        "monitors use, sees nothing; `diff` returns the "
        f"{head['rows_edited']} ids that changed and no others.",
        "",
        *table(
            [
                "Documents edited",
                "Centroid distance",
                "Domain classifier AUC",
                "SEMQ diff",
            ],
            rows,
            "-rrr",
        ),
        "Drift checks follow Evidently's defaults (centroid distance with threshold 0.2, "
        "a domain classifier with ROC AUC threshold 0.55), re-implemented in numpy. "
        "They answer a different question, whether the distribution moved, and they "
        "only flag once half the corpus changed. From 5% up a few edited documents "
        "encode to the same quantized row as before, so `diff` misses them (recall "
        "below 1); it never reports a row that did not change.",
        "",
        "Source: [`granularity.json`](../assets/benchmarks/summary/granularity.json), "
        "produced by `python -m benchmarks.granularity`.",
        "",
    ]


# --------------------------------------------------------------------------- codecs

# Display names and the formats each codec chart compares, in reading order.
NAMES = {
    "semq_quant2": "SEMQ quant · 2 bits",
    "semq_quant4": "SEMQ quant · 3 bits",
    "semq_quant8": "SEMQ quant · 4 bits",
    "semq_phase16": "SEMQ phase · 16 sectors",
    "semq_orbit50": "SEMQ orbit · scale 50",
    "fp32": "FP32",
    "fp16": "FP16",
    "int8": "INT8",
    "binary": "Binary",
    "faiss_pq": "Faiss PQ",
    "st_int8": "INT8, sentence-transformers",
    "st_binary": "Binary, sentence-transformers",
    "faiss_pq2": "Faiss PQ · 2 bits",
    "rabitq4": "RaBitQ · 4 bits",
    "turboquant_mse2": "TurboQuant · 2 bits",
}
SEMQ = ("semq_quant2", "semq_quant4", "semq_quant8", "semq_phase16", "semq_orbit50")
QUALITY_ROWS = SEMQ + (
    "st_binary",
    "faiss_pq2",
    "turboquant_mse2",
    "rabitq4",
    "st_int8",
)
SIZE_ROWS = SEMQ + ("fp32", "fp16", "int8", "binary", "faiss_pq")
DIM = "768"
SVG_WIDTH = 760
LABEL_WIDTH = 230
ROW_HEIGHT = 30


def is_semq(key: str) -> bool:
    return key.startswith("semq_")


def esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def compact(value: float) -> str:
    if value >= 1e6:
        return f"{value / 1e6:.1f}M"
    if value >= 1e3:
        return f"{value / 1e3:.0f}k"
    return f"{value:.0f}"


def bar_path(x: float, y: float, w: float, h: float, css: str) -> str:
    """A bar that grows from the baseline at x: square there, 4px rounded at its data end."""
    r = min(4.0, w / 2, h / 2)
    d = f"M{x:.1f},{y:.1f}h{w - r:.1f}a{r},{r} 0 0 1 {r},{r}v{h - 2 * r:.1f}a{r},{r} 0 0 1 -{r},{r}h-{w - r:.1f}z"
    return f'<path class="semq-chart__bar {css}" d="{d}"/>'


def svg_open(height: int, label: str) -> list[str]:
    return [
        f'<figure class="semq-chart" role="group" aria-label="{esc(label)}">',
        f'<svg viewBox="0 0 {SVG_WIDTH} {height}" xmlns="http://www.w3.org/2000/svg">',
    ]


def axis_ticks(scale, ticks: list[float], top: int, bottom: int, fmt) -> list[str]:
    out = []
    for tick in ticks:
        x = scale(tick)
        out.append(
            f'<line class="semq-chart__grid" x1="{x:.1f}" x2="{x:.1f}" y1="{top}" y2="{bottom}"/>'
        )
        out.append(
            f'<text class="semq-chart__tick" x="{x:.1f}" y="{bottom + 16}" text-anchor="middle">{fmt(tick)}</text>'
        )
    return out


def bar_chart(
    rows: list[tuple[str, str, float, str]],
    label: str,
    unit: str,
    ticks: list[float],
    fmt,
) -> list[str]:
    """Horizontal bars from one baseline: SEMQ rows in the accent, the rest in gray.

    rows are (key, name, value, tip label); every bar carries its value at the tip
    and a native tooltip, and the table view repeats the numbers."""
    top, height = 8, 8 + ROW_HEIGHT * len(rows) + 44
    right = SVG_WIDTH - 70
    hi = ticks[-1]
    scale = lambda v: LABEL_WIDTH + v / hi * (right - LABEL_WIDTH)  # noqa: E731
    out = svg_open(height, label)
    out += axis_ticks(scale, ticks, top, top + ROW_HEIGHT * len(rows), fmt)
    for i, (key, name, value, tip) in enumerate(rows):
        y = top + i * ROW_HEIGHT + 7
        css = "is-semq" if is_semq(key) else "is-comparison"
        w = max(scale(value) - LABEL_WIDTH, 2)
        out.append(f"<g><title>{esc(name)}: {esc(tip)} {esc(unit)}</title>")
        out.append(
            f'<text class="semq-chart__label" x="{LABEL_WIDTH - 10}" y="{y + 12}" text-anchor="end">{esc(name)}</text>'
        )
        out.append(bar_path(LABEL_WIDTH, y, w, 16, css))
        out.append(
            f'<text class="semq-chart__value" x="{LABEL_WIDTH + w + 6:.1f}" y="{y + 12}">{esc(tip)}</text></g>'
        )
    out.append(
        f'<text class="semq-chart__axis" x="{(LABEL_WIDTH + right) / 2:.0f}" y="{height - 4}" text-anchor="middle">{esc(unit)}</text>'
    )
    return out + ["</svg>", "</figure>", ""]


def table_view(header: list[str], rows: list[list[str]], align: str) -> list[str]:
    return [
        '??? info "Table view"',
        "",
        *["    " + line if line else "" for line in table(header, rows, align)],
    ]


def quality_ranges(quality: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Across every measured model and dataset: bits per dimension and the range of
    nDCG@10 kept relative to FP32."""
    table_ = quality["results"]["table"]
    out: dict[str, dict[str, float]] = {}
    for key in QUALITY_ROWS:
        runs = [
            table_[m][d]["methods"][key]
            for m in table_
            for d in table_[m]
            if table_[m][d]["methods"].get(key, {}).get("status") == "measured"
        ]
        kept = [r["ndcg10_retained_pct"] for r in runs]
        bits = [r["bits_per_dim"] for r in runs]
        out[key] = {
            "min": min(kept),
            "max": max(kept),
            "bits_lo": min(bits),
            "bits_hi": max(bits),
            "runs": len(runs),
        }
    return out


def bits_label(r: dict[str, float]) -> str:
    """Measured total bits per dimension: one value when every run agrees to 0.05."""

    def one(v: float) -> str:
        return f"{v:.0f}" if abs(v - round(v)) < 0.05 else f"{v:.1f}"

    lo, hi = r["bits_lo"], r["bits_hi"]
    return one(lo) if abs(hi - lo) < 0.05 else f"{lo:.1f}–{hi:.1f}"


# Chart labels name the method; the measured bits follow, so the name carries no bit count.
SHORT = {
    "semq_quant2": "SEMQ quant",
    "semq_quant4": "SEMQ quant",
    "semq_quant8": "SEMQ quant",
    "semq_phase16": "SEMQ phase",
    "semq_orbit50": "SEMQ orbit",
    "st_binary": "Binary",
    "faiss_pq2": "Faiss PQ",
    "turboquant_mse2": "TurboQuant",
    "rabitq4": "RaBitQ",
    "st_int8": "INT8",
}


def chart_name(key: str, r: dict[str, float]) -> str:
    bits = bits_label(r)
    return f"{SHORT[key]} · {bits} bit{'' if bits == '1' else 's'}/dim"


def range_chart(ranges: dict[str, dict[str, float]]) -> list[str]:
    """One row per format: a 2px line from the lowest to the highest nDCG@10 kept,
    with an end dot at each extreme and a reference line at 100%."""
    rows = sorted(ranges.items(), key=lambda kv: (kv[1]["bits_lo"], -kv[1]["min"]))
    top, height = 8, 8 + ROW_HEIGHT * len(rows) + 44
    right = SVG_WIDTH - 90
    lo, hi = 30.0, 105.0

    def scale(v: float) -> float:
        return LABEL_WIDTH + (v - lo) / (hi - lo) * (right - LABEL_WIDTH)

    out = svg_open(
        height,
        "nDCG@10 kept relative to FP32, lowest to highest across six runs, per format",
    )
    out += axis_ticks(
        scale,
        [40, 60, 80, 100],
        top,
        top + ROW_HEIGHT * len(rows),
        lambda v: f"{v:.0f}%",
    )
    out.append(
        f'<line class="semq-chart__reference" x1="{scale(100):.1f}" x2="{scale(100):.1f}" y1="{top}" y2="{top + ROW_HEIGHT * len(rows)}"/>'
    )
    for i, (key, r) in enumerate(rows):
        y = top + i * ROW_HEIGHT + 15
        css = "is-semq" if is_semq(key) else "is-comparison"
        name = chart_name(key, r)
        span = f"{r['min']:.1f}% to {r['max']:.1f}%"
        out.append(
            f"<g><title>{esc(name)}: {span} of FP32 nDCG@10 across {r['runs']} runs</title>"
        )
        out.append(
            f'<text class="semq-chart__label" x="{LABEL_WIDTH - 10}" y="{y + 4}" text-anchor="end">{esc(name)}</text>'
        )
        out.append(
            f'<line class="semq-chart__range {css}" x1="{scale(r["min"]):.1f}" x2="{scale(r["max"]):.1f}" y1="{y}" y2="{y}"/>'
        )
        for v in (r["min"], r["max"]):
            out.append(
                f'<circle class="semq-chart__dot {css}" cx="{scale(v):.1f}" cy="{y}" r="5"/>'
            )
        out.append(
            f'<text class="semq-chart__value" x="{scale(max(r["max"], 100)) + 10:.1f}" y="{y + 4}">{r["min"]:.0f}–{r["max"]:.0f}%</text></g>'
        )
    out.append(
        f'<text class="semq-chart__axis" x="{(LABEL_WIDTH + right) / 2:.0f}" y="{height - 4}" text-anchor="middle">nDCG@10 kept relative to FP32 · the line spans the lowest and highest of six runs</text>'
    )
    return out + ["</svg>", "</figure>", ""]


def speed_rows(speed: dict[str, Any]) -> list[tuple[str, float, float]]:
    out = []
    for key in SEMQ:
        entry = speed["results"]["semq"][DIM][key]
        b = entry["backends"][entry["default_backend"]]
        out.append(
            (key, b["encode"]["vectors_per_second"], b["decode"]["vectors_per_second"])
        )
    return out


def speed_chart(rows: list[tuple[str, float, float]]) -> list[str]:
    """Grouped horizontal bars on one axis: encode and decode per configuration."""
    top, pair = 30, 44
    height = top + pair * len(rows) + 44
    right = SVG_WIDTH - 70
    hi = 7e6
    scale = lambda v: LABEL_WIDTH + v / hi * (right - LABEL_WIDTH)  # noqa: E731
    out = svg_open(
        height,
        f"Encode and decode throughput in vectors per second, {DIM} dimensions, per SEMQ configuration",
    )
    out += axis_ticks(
        scale,
        [0, 2e6, 4e6, 6e6],
        top,
        top + pair * len(rows),
        lambda v: compact(v) if v else "0",
    )
    for i, (key, enc, dec) in enumerate(rows):
        y = top + i * pair + 5
        out.append(
            f'<text class="semq-chart__label" x="{LABEL_WIDTH - 10}" y="{y + 20}" text-anchor="end">{esc(NAMES[key])}</text>'
        )
        for j, (kind, value) in enumerate((("encode", enc), ("decode", dec))):
            yy = y + j * 17
            w = max(scale(value) - LABEL_WIDTH, 2)
            out.append(
                f"<g><title>{esc(NAMES[key])}, {kind}: {value:,.0f} vectors per second</title>"
            )
            out.append(bar_path(LABEL_WIDTH, yy, w, 14, f"is-{kind}"))
            out.append(
                f'<text class="semq-chart__value" x="{LABEL_WIDTH + w + 6:.1f}" y="{yy + 11}">{compact(value)}</text></g>'
            )
    ly = 14
    out.append(
        f'<rect class="semq-chart__bar is-encode" x="{LABEL_WIDTH}" y="{ly - 9}" width="12" height="10" rx="3"/>'
    )
    out.append(
        f'<text class="semq-chart__label" x="{LABEL_WIDTH + 18}" y="{ly}">Encode</text>'
    )
    out.append(
        f'<rect class="semq-chart__bar is-decode" x="{LABEL_WIDTH + 90}" y="{ly - 9}" width="12" height="10" rx="3"/>'
    )
    out.append(
        f'<text class="semq-chart__label" x="{LABEL_WIDTH + 108}" y="{ly}">Decode</text>'
    )
    out.append(
        f'<text class="semq-chart__axis" x="{(LABEL_WIDTH + right) / 2:.0f}" y="{height - 4}" text-anchor="middle">Vectors per second, {DIM} dimensions, one thread from Python</text>'
    )
    return out + ["</svg>", "</figure>", ""]


def codecs_page(
    quality: dict[str, Any], size: dict[str, Any], speed: dict[str, Any]
) -> str:
    ranges = quality_ranges(quality)
    sizes = size["results"]["dims"][DIM]
    q4 = ranges["semq_quant4"]
    s4 = sizes["semq_quant4"]
    enc4 = {k: e for k, e, _ in speed_rows(speed)}["semq_quant4"]
    hardware = speed["hardware"]["arch"]
    backend = speed["results"]["semq"][DIM]["semq_quant4"]["default_backend"]
    srows = speed_rows(speed)
    numpy = speed["results"]["numpy_baselines"]["dims"][DIM]
    size_rows = sorted(
        (
            (
                k,
                NAMES[k],
                sizes[k]["bytes_per_vector"],
                f"{sizes[k]['bytes_per_vector']:,} B",
            )
            for k in SIZE_ROWS
        ),
        key=lambda r: r[2],
    )
    lines = [
        "---",
        "title: Benchmarks",
        "---",
        "",
        "# Benchmarks",
        "",
        "How SEMQ's operators compare with the vector formats a retrieval pipeline already "
        "uses: how much search quality survives, how many bytes each vector takes, and how "
        "fast it encodes. Every number comes from a frozen result file with its inputs, "
        "commit and hardware.",
        "",
        '<div class="semq-evidence-stats">',
        f"<div><strong>{s4['x_smaller_than_fp32']:.1f}×</strong><span>smaller than FP32 · SEMQ quant at 3 bits</span></div>",
        f"<div><strong>{q4['min']:.0f}–{q4['max']:.0f}%</strong><span>of FP32 search quality kept · six runs</span></div>",
        f"<div><strong>{compact(enc4)}</strong><span>vectors encoded per second · {DIM} dimensions</span></div>",
        "</div>",
        "",
        "## Search quality kept",
        "",
        "For each format, the line spans the lowest and the highest nDCG@10, relative to "
        "FP32, across three embedding models and two datasets (SciFact and FiQA). Formats "
        "are ordered by storage, fewest bits per dimension first. SEMQ is in blue.",
        "",
        *range_chart(ranges),
        *table_view(
            ["Format", "Bits per dimension", "Lowest", "Highest"],
            [
                [NAMES[k], bits_label(r), f"{r['min']:.1f}%", f"{r['max']:.1f}%"]
                for k, r in sorted(
                    ranges.items(), key=lambda kv: (kv[1]["bits_lo"], -kv[1]["min"])
                )
            ],
            "-rrr",
        ),
        "",
        "A value above 100% means the ranking scored slightly better against the available "
        "relevance judgments; it is not a quality improvement in general. Queries search "
        "decoded rows by cosine, with no rescoring.",
        "",
        "### Explore one run",
        "",
        "Pick a model and a dataset to see every measured format at its storage cost.",
        "",
        '<div class="semq-benchmark-explorer" data-semq-benchmark-explorer '
        'data-source="../assets/benchmarks/summary/quality.json">',
        '  <p class="semq-benchmark-explorer__status" role="status">Loading measured results…</p>',
        "</div>",
        "",
        "## Storage per vector",
        "",
        f"Bytes per {DIM}-dimension vector, codes only. A `.semq` file adds an 8-byte id per "
        "row and a fixed header; Faiss PQ also stores a codebook once.",
        "",
        *bar_chart(
            size_rows,
            f"Bytes per {DIM}-dimension vector, per format",
            "bytes per vector",
            [0, 1000, 2000, 3000, 4000],
            lambda v: f"{v:,.0f}",
        ),
        *table_view(
            ["Format", "Bytes per vector", "Smaller than FP32", "GB for 100M vectors"],
            [
                [
                    NAMES[k],
                    f"{sizes[k]['bytes_per_vector']:,}",
                    f"{sizes[k]['x_smaller_than_fp32']:.1f}×",
                    f"{sizes[k]['gb_100m_vectors']:.1f}",
                ]
                for k, *_ in size_rows
            ],
            "-rrr",
        ),
        "",
        "## Encode and decode speed",
        "",
        f"Vectors per second for {DIM}-dimension rows, measured from Python on one {hardware} "
        f"CPU with the `{backend}` backend, median of five runs. Encode includes the unit-norm "
        "check and the state's digests.",
        "",
        *speed_chart(srows),
        *table_view(
            ["Format", "Encode, vectors/s", "Decode, vectors/s"],
            [[NAMES[k], f"{e:,.0f}", f"{d:,.0f}"] for k, e, d in srows]
            + [
                [
                    f"NumPy {k}",
                    f"{v['encode']['vectors_per_second']:,.0f}",
                    f"{v['decode']['vectors_per_second']:,.0f}",
                ]
                for k, v in sorted(numpy.items())
            ],
            "-rr",
        ),
        "",
        "The table also lists plain NumPy casts to FP16, INT8 and binary for scale: they "
        "convert arrays and compute no identity.",
        "",
        "## Choose a configuration",
        "",
        *table(
            [
                "Configuration",
                "Bits per dimension",
                f"Bytes per vector ({DIM})",
                "Search quality kept",
                "Encode, vectors/s",
            ],
            [
                [
                    NAMES[k],
                    bits_label(ranges[k]),
                    f"{sizes[k]['bytes_per_vector']:,}",
                    f"{ranges[k]['min']:.1f}–{ranges[k]['max']:.1f}%",
                    compact(e),
                ]
                for k, e, _ in srows
            ],
            "-rrrr",
        ),
        "[Quality data](../assets/benchmarks/summary/quality.json) · "
        "[Storage data](../assets/benchmarks/summary/size.json) · "
        "[Throughput data](../assets/benchmarks/summary/speed.json) · "
        "[Extended evaluation with uncertainty intervals](../guides/benchmark-results.md) · "
        "[Methodology](../guides/benchmark-protocol.md)",
        "",
        "## Other measurements",
        "",
        "- [Rebuild detection](rebuild.md): does the gate pass a rebuild that changed nothing, "
        "and fail one that did?",
        "- [Scale and portability](scale.md): a million rows, and the same bytes on every platform.",
        "",
    ]
    return "\n".join(lines)


def rebuild_page(rebuild: dict[str, Any], granularity: dict[str, Any]) -> str:
    lines = [
        "---",
        "title: Rebuild detection",
        "---",
        "",
        "# Rebuild detection",
        "",
        "Re-embed the same corpus and SEMQ should stay quiet; change the model, the "
        "precision or the input and it should fail the gate, naming the rows that moved. "
        "These runs test that on 5,183 SciFact documents.",
        "",
        *rebuild_panel(rebuild),
        *simpler_panel(rebuild),
        *rows_panel(granularity),
    ]
    return "\n".join(lines)


def scale_page(
    speed: dict[str, Any], scale: dict[str, Any], repro: dict[str, Any]
) -> str:
    speed_results = speed["results"]
    entry = speed_results["semq"]["768"]["semq_quant4"]
    backend = entry["default_backend"]
    encode = entry["backends"][backend]["encode"]["vectors_per_second"]
    million = scale["results"]["rows"]["1000000"]
    operations = million["operations"]
    file_mb = million["files"]["semq_bytes"] / 1e6
    matrix = repro["results"]["ci_matrix"]
    hosts = {
        f"{row['platform']} {row['architecture']}"
        for row in matrix
        if row["architecture"] != "wasm32"
    }
    lines = [
        "---",
        "title: Scale and portability",
        "---",
        "",
        "# Scale and portability",
        "",
        "What the state operations cost at a million rows, and whether every platform "
        f"produces the same bytes. The timings used one {speed['hardware']['arch']} CPU with "
        f"the `{backend}` backend and include Python and process memory; they are not a "
        "cross-machine speed comparison.",
        "",
        '<div class="semq-evidence-stats">',
        f"<div><strong>{encode / 1000:,.0f}k</strong><span>quant encodes per second · 768 dimensions</span></div>",
        f'<div><strong>{operations["diff"]["seconds"] * 1000:.0f} ms</strong><span>diff · 1M rows, 1% changed</span></div>',
        f'<div><strong>{operations["gate"]["seconds"]:.1f} s</strong><span>full gate · 1M rows</span></div>',
        f"<div><strong>{file_mb:.0f} MB</strong><span><code>.semq</code> file · 1M rows</span></div>",
        "</div>",
        "",
        "## A million rows",
        "",
        *table(
            ["Operation", "Seconds", "What is timed"],
            [
                [name, f"{op['seconds']:.3f}", op["timed"]]
                for name, op in operations.items()
            ],
            "-r-",
        ),
        "## The same bytes everywhere",
        "",
        "The CI identity fixture encodes 1,000 real SciFact vectors under all five "
        f"configurations on {len(hosts)} native host targets and WebAssembly. "
        "Each job compares `content_digest`, `state_id` and the saved-file hash "
        "with committed values. It tests byte identity, not equal throughput.",
        "",
        "[Throughput measurements](../assets/benchmarks/summary/speed.json) · "
        "[Scale measurements](../assets/benchmarks/summary/scale.json) · "
        "[CI matrix and expected identities](../assets/benchmarks/summary/reproducibility.json)",
        "",
    ]
    return "\n".join(lines)


def pages() -> dict[Path, str]:
    """Every generated page, keyed by its path."""
    speed, scale_ = load("speed"), load("scale")
    return {
        ROOT
        / "docs/benchmarks/index.md": codecs_page(load("quality"), load("size"), speed),
        ROOT
        / "docs/benchmarks/rebuild.md": rebuild_page(
            load("rebuild"), load("granularity")
        ),
        ROOT
        / "docs/benchmarks/scale.md": scale_page(
            speed, scale_, load("reproducibility")
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for path, rendered in pages().items():
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != rendered:
                raise SystemExit(
                    f"{path.relative_to(ROOT)} is stale; run python -m benchmarks.page"
                )
        else:
            path.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
