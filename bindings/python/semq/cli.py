# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""The ``semq`` command: show, diff, floor, version.

Exit codes: 0 success or gate passed; 1 gate failed; 2 could not evaluate.
``floor`` writes only JSON to stdout. Human output escapes control
characters in ids and manifest values.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import unicodedata
from collections.abc import Sequence
from typing import Any

from . import build_info
from .diff import Diff, Verdict
from .encoding import Encoding
from .errors import SemqError
from .floor import Floor

DEFAULT_MIN_NULLS = 3


def _escape(text: str) -> str:
    out: list[str] = []
    for ch in text:
        if unicodedata.category(ch) == "Cc":
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return "".join(out)


def _render_id(id: Any) -> str:
    return str(id) if isinstance(id, int) else _escape(id)


def _load(path: str) -> Encoding:
    try:
        return Encoding.load(path)
    except (SemqError, OSError) as exc:
        raise _Exit(2, f"{path}: {exc}") from exc


class _Exit(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def cmd_show(args: argparse.Namespace) -> int:
    e = _load(args.file)
    if args.json:
        json_ids = list(e.ids)
        report = {
            "config": e.config.as_dict(),
            "id_kind": e.id_kind,
            "n": len(e),
            "content_digest": e.content_digest.hex(),
            "state_id": e.state_id.hex(),
            "manifest": e.manifest,
            "ids": [str(i) if e.id_kind == "u64" else i for i in json_ids],
        }
        json.dump(report, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0
    cfg = e.config
    print(f"config:         {cfg.operator.name.lower()} dim={cfg.dim} {cfg.parameter_name}={cfg.as_dict()[cfg.parameter_name]}")
    print(f"id_kind:        {e.id_kind}")
    print(f"rows:           {len(e)}")
    print(f"content_digest: {e.content_digest.hex()}")
    print(f"state_id:       {e.state_id.hex()}")
    manifest = e.manifest
    print(f"manifest:       {len(manifest)} pair(s)")
    for k, v in manifest.items():
        print(f"  {_escape(k)} = {_escape(v)}")
    ids = e.ids
    shown = min(len(e), args.limit)
    print(f"ids:            first {shown} of {len(e)}")
    for i in range(shown):
        print(f"  {_render_id(int(ids[i]) if e.id_kind == 'u64' else ids[i])}")
    return 0


def _print_diff(d: Diff, limit: int) -> None:
    print(f"reference_id:  {d.reference_id.hex()}")
    print(f"candidate_id:  {d.candidate_id.hex()}")
    (n_added, added), (n_removed, removed), (n_changed, changed) = d._preview(limit)
    print(f"added:         {n_added}")
    for i in added:
        print(f"  + {_render_id(i)}")
    print(f"removed:       {n_removed}")
    for i in removed:
        print(f"  - {_render_id(i)}")
    print(f"changed:       {n_changed}")
    for i, h in changed:
        print(f"  ~ {_render_id(i)} hamming={h}")
    print(f"unchanged:     {d.n_unchanged}")
    changes = d.manifest_changes
    print(f"manifest:      {len(changes)} change(s)")
    for k, (b, a) in changes.items():
        print(f"  {_escape(k)}: {'<absent>' if b is None else _escape(b)} -> {'<absent>' if a is None else _escape(a)}")


def cmd_diff(args: argparse.Namespace) -> int:
    ref = _load(args.reference)
    cand = _load(args.candidate)
    try:
        d = ref.diff(cand)
    except SemqError as exc:
        raise _Exit(2, str(exc)) from exc
    if args.per_row and args.floor is None:
        raise _Exit(2, "--per-row needs --floor")
    floor: Floor | None = None
    verdict: Verdict | None = None
    if args.floor is not None:
        try:
            floor = Floor.load(args.floor)
        except (OSError, SemqError) as exc:
            raise _Exit(2, f"{args.floor}: invalid floor: {exc}") from exc
        try:
            verdict = d.evaluate(floor, per_row=args.per_row)
        except SemqError as exc:
            raise _Exit(2, f"{args.floor}: {exc}") from exc
    if args.json:
        report = d.as_dict()
        if verdict is not None:
            report["within"] = verdict.passed
            report["verdict"] = verdict.as_dict()
        json.dump(report, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        _print_diff(d, args.limit)
    if verdict is None:
        return 0
    for key in d.manifest_changes:
        print(f"manifest key {_escape(key)} changed", file=sys.stderr)
    if not verdict.passed:
        print(f"error: candidate is not within the floor ({', '.join(verdict.reasons)})", file=sys.stderr)
    if verdict.rows:
        shown = ", ".join(_render_id(i) for i in verdict.rows[: args.limit])
        more = f", and {len(verdict.rows) - args.limit} more" if len(verdict.rows) > args.limit else ""
        print(f"rows above max_hamming: {shown}{more}", file=sys.stderr)
    if not args.json:
        print(f"within:        {verdict.passed}")
    return 0 if verdict.passed else 1


def cmd_floor(args: argparse.Namespace) -> int:
    if args.min_nulls < 1:
        raise _Exit(2, "--min-nulls must be at least 1")
    if len(args.nulls) < args.min_nulls:
        raise _Exit(
            2,
            f"a floor needs at least {args.min_nulls} null rebuilds, got {len(args.nulls)}; "
            "pass --min-nulls to lower the requirement explicitly",
        )
    ref = _load(args.reference)
    diffs = []
    for path in args.nulls:
        null = _load(path)
        try:
            diffs.append(ref.diff(null))
        except SemqError as exc:
            raise _Exit(2, f"{path}: {exc}") from exc
    try:
        floor = Floor.measure(diffs)
    except SemqError as exc:
        raise _Exit(2, str(exc)) from exc
    floor.save(sys.stdout)
    return 0


def cmd_version(args: argparse.Namespace) -> int:
    try:
        info = build_info().as_dict()
    except SemqError as exc:
        raise _Exit(2, str(exc)) from exc
    info["platform"] = platform.system().lower()
    info["architecture"] = platform.machine()
    info["runtime"] = f"python {platform.python_version()}"
    if args.json:
        json.dump(info, sys.stdout)
        sys.stdout.write("\n")
    else:
        for k, v in info.items():
            print(f"{k}: {v}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="semq", description="Inspect, compare and gate SEMQ encodings.")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("show", help="load a file, verify it and print its identity")
    s.add_argument("file")
    s.add_argument("--json", action="store_true")
    s.add_argument("--limit", type=int, default=20, help="ids to print in human output")
    s.set_defaults(func=cmd_show)

    d = sub.add_parser("diff", help="compare a candidate against a reference")
    d.add_argument("reference")
    d.add_argument("candidate")
    d.add_argument("--floor", help="floor.json; exit 1 when the candidate is not within it")
    d.add_argument(
        "--per-row",
        action="store_true",
        help="also fail when any changed row has a hamming above the floor's max_hamming",
    )
    d.add_argument("--json", action="store_true")
    d.add_argument("--limit", type=int, default=20)
    d.set_defaults(func=cmd_diff)

    f = sub.add_parser("floor", help="measure a floor from null rebuilds of the reference")
    f.add_argument("reference")
    f.add_argument("nulls", nargs="+")
    f.add_argument(
        "--min-nulls",
        type=int,
        default=DEFAULT_MIN_NULLS,
        help=f"null rebuilds required (default {DEFAULT_MIN_NULLS}); one null is only what that rebuild happened to do",
    )
    f.set_defaults(func=cmd_floor)

    v = sub.add_parser("version", help="print build information")
    v.add_argument("--json", action="store_true")
    v.set_defaults(func=cmd_version)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except _Exit as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
