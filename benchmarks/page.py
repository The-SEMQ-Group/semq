# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Render the benchmark pages from frozen benchmark results.

Run ``python -m benchmarks.page`` to regenerate the public pages. The result
files remain the source of truth; ``--check`` detects a stale rendering.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "docs/assets/benchmarks/summary"

SCENARIOS = (
    ("null_gpu_b64", "GPU rebuild, different batch size"),
    ("null_cpu_b1", "CPU rebuild, one document per batch"),
    ("change_model_v1", "Previous encoder revision"),
    ("change_fp16_gpu", "Half precision"),
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
    "change_fp16_gpu": "the precision",
    "change_max_length_128": "the input",
    "change_cls_pooling": "the pooling",
}


# The command that writes each result file the page reads.
PRODUCERS = {
    "rebuild": "python -m benchmarks.rebuild",
    "granularity": "python -m benchmarks.granularity",
    "floor-power": "python -m benchmarks.floor_power",
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
        "## Real pipeline changes",
        "",
        f"A floor measured from {floor['nulls']} unchanged rebuilds, then seven "
        "candidates: two more unchanged rebuilds and five changes to the pipeline. "
        "Each bar is the share of rows whose symbols changed, not how serious the "
        "change is. Moving the normalization after the model shifts no coordinate by "
        "more than 3e-8, so it counts as no change: four real changes remain.",
        "",
        f"Hardware: {hardware_line(data)}.",
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
        f"The floor allowed {floor['changed_rows']} of {floor['total_rows']:,} rows to "
        f"change, by at most {floor['hamming']} symbol each.",
        "",
    ]
    return lines


def simpler_panel(data: dict[str, Any]) -> list[str]:
    """The same runs judged with a float hash, allclose, a cosine threshold and
    a calibrated max-difference threshold, from ``results.errors``."""
    results = data["results"]
    calibration = set(results["floor_nulls"])
    nulls = {
        key
        for key in results["runs"]
        if key.startswith("null_") and key not in calibration
    }
    rows = []
    for key, label in SIMPLE_CHECKS.items():
        errors = results["errors"][key]
        missed = [m for m in errors["missed_real_changes"] if m in REAL_CHANGES]
        detail = f" ({', '.join(REAL_CHANGES[m] for m in missed)})" if missed else ""
        rows.append(
            [
                label,
                f"{len(nulls.intersection(errors['false_alarms_on_nulls']))} of {len(nulls)}",
                f"{len(missed)} of {len(REAL_CHANGES)}{detail}",
            ]
        )
    return [
        "**The same runs, judged by other checks.** A false alarm flags a rebuild "
        "with unchanged text and encoder; a miss lets a tested pipeline change pass. "
        f"False alarms count only the {len(nulls)} rebuilds held out from the "
        f"{len(calibration)} used to measure the floor.",
        "",
        *table(
            ["Check", "False alarms on held-out rebuilds", "Tested changes missed"],
            rows,
            "-rr",
        ),
        "In these runs, every held-out rebuild changed the FP32 bytes. The fixed "
        "cosine threshold also lets the switch to half precision pass. A threshold "
        "on the largest difference works "
        "when it is calibrated on your own rebuilds, which is what the floor does.",
        "",
        "Source: [`rebuild.json`](../assets/benchmarks/summary/rebuild.json), produced by "
        "`python -m benchmarks.rebuild`.",
        "",
    ]


POWER_CHECKS = {
    "floor_within": "SEMQ floor, `within`",
    "floor_per_row": "SEMQ floor, per-row",
    "max_abs_calibrated": "Largest absolute difference, calibrated",
    "cosine_calibrated": "Lowest row cosine, calibrated",
    "fp32_hash": "Hash of the FP32 bytes",
    "allclose_default": "`np.allclose`, default tolerances",
    "bf16_fixed": "Fixed tolerance of one bfloat16 spacing",
}
CALIBRATED = ("max_abs_calibrated", "cosine_calibrated")
POWER_DETECTORS = (
    "floor_within",
    "floor_per_row",
    "max_abs_calibrated",
    "cosine_calibrated",
)
DEVICES = {"cpu": "CPU", "mps": "GPU", "cuda": "GPU"}
FAULT_FAMILIES = ("replace", "truncate", "substitute", "diffuse", "sparse")


def sci(value: float) -> str:
    """Scientific notation without padding: 4.5e-6, 1e-4."""
    mantissa, exponent = f"{value:.1e}".split("e")
    return f"{mantissa.rstrip('0').rstrip('.')}e{int(exponent)}"


def fault_order(fault: dict[str, Any]) -> tuple:
    family = fault["family"]
    params = [
        v
        for k, v in sorted(fault.items())
        if k != "size_median_1_minus_cos" and isinstance(v, (int, float))
    ]
    return (FAULT_FAMILIES.index(family), *params)


def fault_label(fault: dict[str, Any]) -> str:
    family = fault["family"]
    if family == "replace":
        k = fault["documents"]
        return f"Replace {k} document{'' if k == 1 else 's'}"
    if family == "truncate":
        return f"Cut the last {fault['cut']:.0%} of words in one document"
    if family == "substitute":
        m = fault["words"]
        return f"Swap {m} word{'' if m == 1 else 's'} in one document"
    if family == "diffuse":
        return (
            f"Noise on every coordinate, {fault['noise_x_null_scale']}× rebuild noise"
        )
    return (
        f"Scale {fault['coordinates']:.0%} of coordinates by 1 + {sci(fault['scale'])}"
    )


def rate_cells(r: dict[str, Any]) -> list[str]:
    lo, hi = r["ci95"]
    return [percent(100 * r["rate"]), f"{percent(100 * lo)}–{percent(100 * hi)}"]


def states_summary(regime: dict[str, Any]) -> str:
    """How many rebuilds matched the reference state, and how much the rest changed."""
    states = regime["states"]
    same = sum(st["nulls"] for st in states if st["equals_reference"])
    other = [st for st in states if not st["equals_reference"]]
    if not other:
        return f"all {same} matched the reference"
    n_other = sum(st["nulls"] for st in other)
    lo = min(st["rows_changed"] for st in other)
    hi = max(st["rows_changed"] for st in other)
    rows = (
        f"{lo} row"
        if lo == hi == 1
        else f"{lo} rows" if lo == hi else f"{lo} to {hi} rows"
    )
    ham = max(st["max_hamming"] for st in other)
    return (
        f"{same} matched the reference and the other {n_other} changed {rows} "
        f"(hamming at most {ham})"
    )


# -- floor charts: `within` in the accent, per-row in orange, in every chart --

GATE_CSS = {"floor_within": "is-within", "floor_per_row": "is-per-row"}
GATE_NAMES = {"floor_within": "within", "floor_per_row": "per-row"}


def hardware_line(data: dict[str, Any]) -> str:
    """The CPU and GPU a result was produced on, from its envelope."""
    hw = data["hardware"]
    cpu = f"{hw['machine']} ({hw['arch']})"
    return f"CPU: {cpu} · GPU: {hw['gpu']}" if hw.get("gpu") else f"CPU: {cpu}"


def chart_legend(items: list[tuple[str, str]]) -> str:
    spans = "".join(f'<span class="{css}">{esc(name)}</span>' for css, name in items)
    return f'<p class="semq-chart-legend">{spans}</p>'


def false_alarm_chart(vfar: dict[str, Any]) -> list[str]:
    """False-alarm rate against nulls in the floor (log scale), measured and bounded."""
    ns = sorted(int(k) for k in vfar)
    left, right, top, bottom = 62, SVG_WIDTH - 154, 36, 250
    lo_n, hi_n = math.log(ns[0]), math.log(ns[-1])

    def xs(n: float) -> float:
        return left + (math.log(n) - lo_n) / (hi_n - lo_n) * (right - left)

    def ys(v: float) -> float:
        return bottom - v / 80 * (bottom - top)

    out = svg_open(bottom + 44, "False alarms against the number of nulls in the floor")
    out[0] = out[0].replace(
        'class="semq-chart"', 'class="semq-chart is-rebuild" tabindex="0"'
    )
    out.append(
        f'<text class="semq-chart__axis" x="{left - 8}" y="{top - 18}">'
        "false-alarm rate (%)</text>"
    )
    for v in (0, 20, 40, 60, 80):
        out.append(
            f'<line class="semq-chart__grid" x1="{left}" x2="{right}" '
            f'y1="{ys(v):.1f}" y2="{ys(v):.1f}"/>'
        )
        out.append(
            f'<text class="semq-chart__tick" x="{left - 8}" y="{ys(v) + 4:.1f}" '
            f'text-anchor="end">{v}%</text>'
        )
    for n in ns:
        out.append(
            f'<text class="semq-chart__tick" x="{xs(n):.1f}" y="{bottom + 18}" '
            f'text-anchor="middle">{n}</text>'
        )
    out.append(
        f'<text class="semq-chart__axis" x="{(left + right) / 2:.0f}" y="{bottom + 38}" '
        'text-anchor="middle">calibration rebuilds (N, log scale)</text>'
    )
    ends = []
    for det, stats in (("floor_within", 2), ("floor_per_row", 3)):
        css = GATE_CSS[det]
        steps = [ns[0] * (ns[-1] / ns[0]) ** (i / 60) for i in range(61)]
        pts = " ".join(f"{xs(n):.1f},{ys(100 * stats / (n + 1)):.1f}" for n in steps)
        out.append(f'<polyline class="semq-chart__bound {css}" points="{pts}"/>')
        out.append(
            f'<text class="semq-chart__note" x="{xs(ns[0]) + 10:.1f}" '
            f'y="{ys(100 * stats / (ns[0] + 1)) - 6:.1f}">bound {stats}/(N+1)</text>'
        )
        pts = " ".join(
            f"{xs(n):.1f},{ys(100 * vfar[str(n)][det]['rate']):.1f}" for n in ns
        )
        out.append(f'<polyline class="semq-chart__line {css}" points="{pts}"/>')
        for n in ns:
            r = vfar[str(n)][det]
            lo, up = (100 * c for c in r["ci95"])
            x = xs(n)
            out.append(
                f'<path class="semq-chart__interval {css}" '
                f'd="M{x:.1f},{ys(lo):.1f}V{ys(up):.1f}'
                f'M{x - 4:.1f},{ys(lo):.1f}h8M{x - 4:.1f},{ys(up):.1f}h8"/>'
            )
            out.append(
                f"<g><title>{GATE_NAMES[det]}, {n} nulls: {percent(100 * r['rate'])} "
                f"(95% interval {percent(lo)}–{percent(up)}; "
                f"bound {percent(100 * stats / (n + 1))})</title>"
                f'<circle class="semq-chart__point {css}" cx="{xs(n):.1f}" '
                f'cy="{ys(100 * r["rate"]):.1f}" r="4.5"/></g>'
            )
        ends.append((ys(100 * vfar[str(ns[-1])][det]["rate"]), det))
    # Direct labels at the right end, pushed apart when the two rates are close.
    (ya, da), (yb, db) = sorted(ends)
    if yb - ya < 20:
        mid = (ya + yb) / 2
        ya, yb = mid - 10, mid + 10
    for y, det in ((ya, da), (yb, db)):
        last = percent(100 * vfar[str(ns[-1])][det]["rate"])
        out.append(
            f'<text class="semq-chart__label" x="{right + 12}" y="{y + 4:.1f}">'
            f"{GATE_NAMES[det]} {last}</text>"
        )
    return out + [
        "</svg>",
        '<figcaption class="semq-scroll-hint">Scroll horizontally to view the full chart.</figcaption>',
        "</figure>",
        "",
    ]


def rank_chart(example: dict[str, Any]) -> list[str]:
    """The measured noise and replaced rows, without a broken or logarithmic axis."""
    faulted = sorted(example["faulted_hamming"])
    counts = {int(h): c for h, c in example["hamming_counts"].items()}
    for h in faulted:
        counts[h] -= 1
    noise = {h: c for h, c in counts.items() if c > 0}
    total = example["changed_rows"]
    n_noise = sum(noise.values())
    noise_range = (
        str(min(noise)) if min(noise) == max(noise) else f"{min(noise)}–{max(noise)}"
    )
    ignored = example["rows_ignored_by_p99"]
    return [
        '<figure class="semq-row-example" aria-label="Changed rows in the synthetic example">',
        '<div class="semq-row-example__bar" aria-hidden="true">',
        f'<span class="is-noise" style="width:{100 * n_noise / total:.4f}%"></span>',
        f'<span class="is-faulted" style="width:{100 * len(faulted) / total:.4f}%"></span>',
        "</div>",
        '<div class="semq-row-example__groups">',
        '<div class="is-noise"><span>Rebuild noise</span>',
        f"<strong>{n_noise:,} rows</strong><p>{noise_range} symbols changed per row</p></div>",
        '<div class="is-faulted"><span>Replaced documents</span>',
        f'<strong>{len(faulted)} rows</strong><p>{" and ".join(str(h) for h in faulted)} '
        "symbols changed</p></div>",
        "</div>",
        f"<figcaption>Of {total:,} changed rows, the p99 ignores these {ignored} rows "
        f'with the largest changes. The candidate’s p99 stays at {example["candidate_p99"]}; '
        f'the per-row limit is {example["floor_max_hamming"]} symbols.</figcaption>',
        "</figure>",
        "",
    ]


SIZE_MARKS = (
    ("floor_within", "is-floor", "SEMQ floor"),
    ("max_abs_calibrated", "is-maxabs", "largest difference, calibrated"),
    ("cosine_calibrated", "is-cosine", "lowest cosine, calibrated"),
)


def mark(css: str, x: float, y: float) -> str:
    if css == "is-floor":
        return (
            f'<circle class="semq-chart__mark {css}" cx="{x:.1f}" cy="{y:.1f}" r="7"/>'
        )
    if css == "is-maxabs":
        return (
            f'<rect class="semq-chart__mark {css}" x="{x - 3.5:.1f}" y="{y - 3.5:.1f}" '
            'width="7" height="7"/>'
        )
    return (
        f'<path class="semq-chart__mark {css}" '
        f'd="M{x:.1f},{y - 4.5:.1f}l4.5,4.5l-4.5,4.5l-4.5,-4.5z"/>'
    )


def detection_size_chart(det: dict[str, Any]) -> list[str]:
    """Named numeric scenarios with rates and intervals; labels stay HTML text."""
    faults = sorted(
        (f for f in det.values() if f["family"] in ("diffuse", "sparse")),
        key=fault_order,
    )
    out = [
        '<figure class="semq-dotchart" aria-label="Detection of injected numeric changes">',
        "<figcaption>Detection rate · higher is better. Whiskers show 95% "
        "resampling intervals.</figcaption>",
        '<div class="semq-dotchart__axis"><span>Injected change</span>',
        '<div class="semq-dotchart__ticks">'
        + "".join(f"<span>{v}%</span>" for v in (0, 25, 50, 75, 100))
        + "</div></div>",
    ]
    short_names = ("SEMQ", "Max diff", "Cosine")
    for f in faults:
        label = (
            f"Gaussian noise · {f['noise_x_null_scale']}× rebuild noise"
            if f["family"] == "diffuse"
            else f"Scale {f['coordinates']:.0%} of dimensions by 1 + {sci(f['scale'])}"
        )
        rates = [f["detectors"][key] for key, _, _ in SIZE_MARKS]
        out.extend(
            [
                '<div class="semq-dotchart__row">',
                f'<div class="semq-dotchart__label"><strong>{esc(label)}</strong>'
                f'<small>Angular change: {sci(f["size_median_1_minus_cos"])}</small></div>',
                '<svg viewBox="0 0 360 60" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">',
            ]
        )
        for v in (0, 25, 50, 75, 100):
            x = 20 + 3.2 * v
            out.append(
                f'<line class="semq-chart__grid" x1="{x}" x2="{x}" y1="0" y2="60"/>'
            )
        for i, ((_, css, _), r) in enumerate(zip(SIZE_MARKS, rates, strict=True)):
            y = 12 + 18 * i
            lo, hi = (20 + 320 * c for c in r["ci95"])
            out.append(
                f'<path class="semq-dotchart__interval {css}" '
                f'd="M{lo:.1f},{y}H{hi:.1f}M{lo:.1f},{y - 3}v6M{hi:.1f},{y - 3}v6"/>'
            )
            out.append(mark(css, 20 + 320 * r["rate"], y))
        out.extend(["</svg>", '<div class="semq-dotchart__rates">'])
        for name, (_, css, _), r in zip(short_names, SIZE_MARKS, rates, strict=True):
            out.append(
                f'<span class="{css}">{name}: <strong>{percent(100 * r["rate"])}</strong></span>'
            )
        out.extend(["</div>", "</div>"])
    return out + ["</figure>", ""]


def gate_diagram(example: dict[str, Any]) -> list[str]:
    """Calibration and candidate checks as responsive, accessible HTML."""
    rows = (
        ("Changed rows", example["changed_rows"], example["floor_changed_rows"]),
        ("p99 symbols changed", example["candidate_p99"], example["floor_hamming"]),
        (
            "Most symbols changed in one row",
            max(int(h) for h in example["hamming_counts"]),
            example["floor_max_hamming"],
        ),
    )
    out = [
        '<figure class="semq-gate" aria-label="Calibrate the floor, then evaluate a candidate">',
        '<div class="semq-gate__steps">',
        '<div><span class="semq-gate__step">1 · Calibrate</span>',
        f'<strong>{example["nulls_in_floor"]} unchanged rebuilds</strong>',
        "<p>Compare each with the same reference. Keep the largest observed "
        "value of each statistic as the floor.</p></div>",
        '<div><span class="semq-gate__step">2 · Evaluate</span>',
        "<strong>One candidate rebuild</strong>",
        "<p>Compare it with that reference, then check each value against its "
        "floor limit.</p></div>",
        "</div>",
        '<ul class="semq-gate__checks">',
    ]
    for label, value, bound in rows:
        ok = value <= bound
        out.append(
            f'<li><span>{esc(label)}</span><code>{value:,} {"≤" if ok else ">"} {bound:,}</code>'
            f'<strong class="{"is-pass" if ok else "is-fail"}">'
            f'{"Within" if ok else "Exceeds"}</strong></li>'
        )
    out += [
        "</ul>",
        "<figcaption>Illustrative candidate from the measured synthetic pool. "
        "<code>within</code> accepts the first two values; <code>per-row</code> "
        f'also checks the last and flags {len(example["faulted_hamming"])} rows.</figcaption>',
        "</figure>",
        "",
    ]
    return out


def tradeoff_table(vdet: dict[str, Any], far: dict[str, Any], n: int) -> list[str]:
    """Detection and false alarms together, with one 0–100% scale and exact rates."""
    rows = [
        (
            f"Replace {vdet[key]['documents']} document{'s' if vdet[key]['documents'] != 1 else ''}",
            "Detected · higher is better",
            vdet[key]["detectors"],
        )
        for key in ("replace_1", "replace_2")
    ]
    rows.append(("Unchanged rebuild", "False alarm · lower is better", far))
    out = [
        '<figure class="semq-tradeoff" aria-label="Detection and false alarms with and without per-row">',
        f"<figcaption>Synthetic pool · {n} calibration rebuilds. Bars show rates "
        "on a 0–100% scale; ranges are 95% resampling intervals.</figcaption>",
        '<table><thead><tr><th scope="col">Scenario</th>',
        '<th scope="col"><code>within</code></th>',
        '<th scope="col">With <code>per-row</code></th></tr></thead><tbody>',
    ]
    for label, direction, rates in rows:
        out.append(
            f'<tr><th scope="row">{esc(label)}<small>{esc(direction)}</small></th>'
        )
        for key in GATE_NAMES:
            r = rates[key]
            out.append(
                f'<td><strong>{percent(100 * r["rate"])}</strong>'
                f'<span class="semq-rate-track" aria-hidden="true"><span '
                f'class="{GATE_CSS[key]}" style="width:{100 * r["rate"]:.4f}%"></span></span>'
                f"<small>{esc(rate_cells(r)[1])}</small></td>"
            )
        out.append("</tr>")
    return out + ["</tbody></table>", "</figure>", ""]


def calibration_details(vfar: dict[str, Any], vbound: dict[str, Any]) -> list[str]:
    """Keep the bound, calibration chart and its values in one closed disclosure."""
    body = [
        "**False-alarm bounds.** The floor keeps, for each statistic, the largest "
        "value over N calibration rebuilds. When those rebuilds and the candidate "
        "are produced the same way (exchangeable), an unchanged candidate exceeds "
        "that largest value with probability at most `1/(N+1)`. A gate checking s "
        "statistics therefore rejects it at most `s/(N+1)` of the time. `within` "
        "checks two statistics; per-row adds a third. These are upper bounds, not "
        "predicted rates. The observed rates below are lower; dependence between "
        "statistics and tied Hamming values can make the bounds conservative.",
        "",
        chart_legend(
            [
                ("is-within", "within"),
                ("is-per-row", "per-row"),
                ("is-bound", "bound s/(N+1)"),
            ]
        ),
        "",
        *false_alarm_chart(vfar),
        "More calibration rebuilds reduced false alarms in this synthetic pool. "
        "Solid lines show observed rates, whiskers show 95% resampling intervals, "
        "and dashed lines show the theoretical upper bounds. Lower is better.",
        "",
        *table(
            [
                "Calibration rebuilds",
                "`within`",
                "95% interval",
                "Upper bound",
                "Per-row",
                "95% interval",
                "Upper bound",
            ],
            [
                [
                    key,
                    *rate_cells(vfar[key]["floor_within"]),
                    percent(100 * vbound[key]["floor_within"]),
                    *rate_cells(vfar[key]["floor_per_row"]),
                    percent(100 * vbound[key]["floor_per_row"]),
                ]
                for key in sorted(vfar, key=int)
            ],
            "rrrrrrr",
        ),
    ]
    return [
        '??? info "How calibration affects false alarms"',
        "",
        *["    " + line if line else "" for line in body],
        "",
    ]


def power_panel(data: dict[str, Any]) -> list[str]:
    """False alarms and detection rates of the floor and of float checks, from
    ``results.pools`` of ``floor-power.json``."""
    results = data["results"]
    real, varying = results["pools"]["real"], results["pools"]["varying"]
    n = str(results["detection_n"])
    regime = real["regime"]
    far = real["false_alarms"][n]
    few = str(min(int(k) for k in real["false_alarms"]))
    far_few = real["false_alarms"][few]
    noise_rows = max(st["rows_changed"] for st in regime["states"])
    # The false-alarm sentence names two groups; fail loudly if the data disagrees.
    if any(far[k]["rate"] != 0 for k in POWER_DETECTORS) or any(
        far[k]["rate"] != 1 for k in ("fp32_hash", "allclose_default", "bf16_fixed")
    ):
        raise ValueError("floor-power false alarms no longer split into 0% and 100%")
    det = real["detection"][n]
    vfar, vbound = varying["false_alarms"], varying["false_alarm_bounds"]
    vdet = varying["detection"][n]
    varying_rows = sorted(s["rows_changed"] for s in varying["regime"]["states"])
    sigma = varying["synthetic"]["sigma"]
    example = varying["example"]
    return [
        "## False alarms and detection power",
        "",
        f"Hardware: {hardware_line(data)}.",
        "",
        f"{regime['nulls']} rebuilds of the same corpus that change only the device, "
        "the batch size and the input order. Every rebuild's floats differed from "
        "the reference, but "
        f"there were only {regime['distinct_states_including_reference']} SEMQ "
        f"states: {states_summary(regime)}.",
        "",
        f"Each of {results['draws']:,} draws holds out one rebuild, measures a floor from "
        f"N of the others, and judges the held-out rebuild, then the same rebuild with "
        "one fault. Calibrated float checks take their threshold from the same N "
        "rebuilds. Intervals are 95% Clopper–Pearson.",
        "",
        f"**False alarms.** With {n} rebuilds in the floor, the floor and both "
        f"calibrated float checks raised none in {results['draws']:,} draws (95% "
        f"interval {rate_cells(far['floor_within'])[1]}). A hash of the floats, "
        "`np.allclose` and a fixed tolerance of one bfloat16 spacing rejected every "
        f"rebuild. With only {few} rebuilds in the floor, the floor raised "
        f"{percent(100 * far_few['floor_within']['rate'])} and the calibrated float "
        f"checks {percent(100 * min(far_few[k]['rate'] for k in CALIBRATED))} to "
        f"{percent(100 * max(far_few[k]['rate'] for k in CALIBRATED))}: a floor from "
        "a few rebuilds can underestimate the variation in unchanged candidates. "
        "The draws resample the same "
        f"{regime['nulls']} rebuilds, so the intervals describe this pool, not every "
        "future rebuild.",
        "",
        *table_view(
            ["Check", "False alarms", "95% interval"],
            [[label, *rate_cells(far[key])] for key, label in POWER_CHECKS.items()],
            "-rr",
            "False alarms by check",
        ),
        "",
        "**Detection.** Each fault is injected into a held-out rebuild. On the tested "
        "content edits, SEMQ and the calibrated float checks had similar detection "
        f"rates: one replaced document {percent(100 * det['replace_1']['detectors']['floor_within']['rate'])}"
        f" for every check, one swapped word "
        f"{percent(100 * det['substitute_1']['detectors']['floor_within']['rate'])} for the floor "
        f"and {percent(100 * det['substitute_1']['detectors']['cosine_calibrated']['rate'])} for "
        "the cosine check. Some cuts remove only text beyond the model's 512-token "
        "window, leaving the model input unchanged.",
        "",
        "**Numeric changes.** A perturbation can change floats without crossing a "
        "quantization boundary. SEMQ's symbols change only when a coordinate crosses "
        "that boundary; the calibrated float checks detect smaller movements in "
        "these runs. Each row below names the injected change. Angular change is "
        "the median 1 − cosine between modified rows and those same rows before "
        "the injection. The scaled dimensions are the same in every document.",
        "",
        chart_legend(
            [
                ("is-floor", "SEMQ within"),
                ("is-maxabs", "largest difference, calibrated"),
                ("is-cosine", "lowest cosine, calibrated"),
            ]
        ),
        "",
        *detection_size_chart(det),
        *table_view(
            [
                "Fault",
                "Angular change (1 − cosine)",
                "Floor, `within`",
                "Floor, per-row",
                "Largest difference, calibrated",
                "Cosine, calibrated",
            ],
            [
                [
                    fault_label(f),
                    f"{f['size_median_1_minus_cos']:.1e}",
                    *(
                        percent(100 * f["detectors"][d]["rate"])
                        for d in POWER_DETECTORS
                    ),
                ]
                for f in sorted(det.values(), key=fault_order)
            ],
            "-rrrrr",
            "Detection rates by fault",
        ),
        "",
        "### When the rebuild noise varies (synthetic)",
        "",
        f"The rebuilds above changed at most {noise_rows} rows each. To test rebuilds "
        "that change hundreds of rows every time, this pool adds "
        f"noise: each of {varying['regime']['nulls']} nulls is a GPU rebuild plus "
        f"Gaussian noise (σ = {sci(sigma)} per coordinate), renormalized, and changes "
        f"{varying_rows[0]} to {varying_rows[-1]} rows. It is a controlled test of "
        "varying noise, not a model of a specific GPU kernel.",
        "",
        "**Why `within` can miss a localized change.** The p99 summarizes changed "
        "rows and can omit the largest individual changes. In this candidate, the "
        "changed-row count and p99 both stay within the floor, so `within` passes. "
        "Per-row also checks each row against `max_hamming` and flags the replaced "
        "documents.",
        "",
        *rank_chart(example),
        "",
        "### What per-row adds",
        "",
        "Per-row caught localized changes the p99 hid, at the cost of more false "
        "alarms in this synthetic test. Compare both outcomes before choosing a "
        "gate; these are observed rates, not guarantees.",
        "",
        *tradeoff_table(vdet, vfar[n], int(n)),
        *table_view(
            ["Fault", *(POWER_CHECKS[d] for d in POWER_DETECTORS)],
            [
                [
                    fault_label(vdet[key]),
                    *(
                        percent(100 * vdet[key]["detectors"][d]["rate"])
                        for d in POWER_DETECTORS
                    ),
                ]
                for key in ("replace_1", "replace_2")
            ],
            "-rrrr",
            "Detection of replaced documents",
        ),
        "",
        *calibration_details(vfar, vbound),
        "Source: [`floor-power.json`](../assets/benchmarks/summary/floor-power.json), "
        "produced by `python -m benchmarks.floor_power`.",
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
                f"{round(semq['recall'] * k['rows_edited']):,} of "
                f"{k['rows_edited']:,} identified",
            ]
        )
    return [
        "## Which rows changed?",
        "",
        f"Hardware: {hardware_line(data)}.",
        "",
        f"Edit {head['percent']:g}% of the corpus ({head['rows_edited']} documents cut to "
        "their first half and embedded again). Distribution drift, the check embedding "
        "monitors use, sees nothing; `diff` returns the "
        f"{head['rows_edited']} ids that changed and no others. The two answer "
        "different questions: whether the distribution moved, and which documents "
        "changed.",
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
        "With these thresholds, the domain classifier flagged drift only in the "
        "tested 50% scenario; the centroid check flagged none. From 5% up a few "
        "edited documents encode to "
        "the same quantized row as before, so `diff` misses them; no unedited row was "
        "reported in these runs.",
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


def table_view(
    header: list[str], rows: list[list[str]], align: str, title: str = "Table view"
) -> list[str]:
    return [
        f'??? info "{title}"',
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
        "and fail one that did? With [false-alarm and detection rates]"
        "(rebuild.md#false-alarms-and-detection-power) over many rebuilds.",
        "- [Scale and portability](scale.md): a million rows, and the same bytes on every platform.",
        "",
    ]
    return "\n".join(lines)


def rebuild_page(
    rebuild: dict[str, Any], power: dict[str, Any], granularity: dict[str, Any]
) -> str:
    real = power["results"]["pools"]["real"]
    n = str(power["results"]["detection_n"])
    det = real["detection"][n]
    word = det["substitute_1"]["detectors"]["floor_per_row"]["rate"]
    missed = rebuild["results"]["errors"]["semq_quant4"]["missed_real_changes"]
    missed = [m for m in missed if m in REAL_CHANGES]
    lines = [
        "---",
        "title: Rebuild detection",
        "---",
        "",
        "# Rebuild detection",
        "",
        "Rebuilding an embedding corpus can change its floating-point values even "
        "when its text and encoder are unchanged. SEMQ turns each embedding into "
        "symbols, reports changed row IDs, and compares the differences with a "
        "floor: the largest variations observed in unchanged rebuilds. Passing "
        "the gate means the candidate stayed within that measured envelope; it "
        "does not establish semantic equivalence.",
        "",
        '<figure class="semq-figure" markdown="1">',
        "",
        "![The same document rebuilt on another device gives other floats but "
        "the same symbols; an edited document changes symbols and its row is "
        "reported](../assets/images/rebuild-noise-vs-change.svg)",
        "",
        "<figcaption>Illustrative values. A real rebuild can change some symbols "
        "within the floor, and a small edit can leave every symbol unchanged."
        '<span class="semq-scroll-hint">Scroll horizontally to view the full illustration.</span></figcaption>',
        "",
        "</figure>",
        "",
        "**Setup:** 5,183 SciFact documents · `e5-small-v2` · quant with four bins.",
        "",
        "Each section is a separate experiment with its own calibration. The "
        "hardware and frozen results are listed with that experiment.",
        "",
        f"- **No false alarms on real rebuilds:** none with {n} rebuilds in the floor, "
        f"over {power['results']['draws']:,} resamples of {real['regime']['nulls']} "
        "rebuilds, where a hash of the floats, `np.allclose` and a fixed tolerance "
        "rejected all of them.",
        f"- **Real changes caught:** {len(REAL_CHANGES) - len(missed)} of "
        f"{len(REAL_CHANGES)} pipeline changes, and one swapped word in one document "
        f"{percent(100 * word)} of the time.",
        "- **A compact, portable state.** A float check calibrated on the same "
        "rebuilds catches content changes as well, catches small numeric faults "
        "better and can list rows too; SEMQ compares a compact state that every "
        "platform reads the same way and reports a structured diff.",
        "",
        "## How the gate decides",
        "",
        "Here a row is one document's embedding. The reference is the state you "
        "trust; a candidate is a new rebuild. A row's hamming is how many of its "
        "symbols differ from the reference, and the p99 is taken over the changed "
        "rows only, not over the whole corpus.",
        "",
        *gate_diagram(power["results"]["pools"]["varying"]["example"]),
        "Measure a floor for a specific reference and expected rebuild settings. "
        "Recalibrate when the reference or noise regime changes. Each candidate "
        "is compared with that reference: `within` checks the changed-row ratio "
        "and p99 Hamming; `--per-row` also checks the largest row change. The "
        "example shows the numeric checks; a changed encoder manifest also fails "
        "the gate.",
        "",
        *rebuild_panel(rebuild),
        *simpler_panel(rebuild),
        *power_panel(power),
        *rows_panel(granularity),
        '??? note "What these runs do and do not show"',
        "",
        "    - One corpus and one model. The floor describes these rebuilds, not "
        "another pipeline's.",
        "    - The rebuilds vary the device, the batch size and the input order, and "
        f"changed at most {max(st['rows_changed'] for st in real['regime']['states'])} "
        "rows each.",
        "    - The varying-noise pool is synthetic.",
        "    - The previous model revision also changes the manifest, which alone fails "
        "the gate. With the manifest unchanged, it still changes 100% of rows.",
        "    - The draws resample one fixed pool. The intervals describe that pool.",
        "",
        "[Run the gate yourself](../guides/gate-a-rebuild.md)",
        "",
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
            load("rebuild"), load("floor-power"), load("granularity")
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
