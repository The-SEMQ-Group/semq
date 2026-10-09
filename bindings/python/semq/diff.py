# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Diff: what changed between a reference and a candidate."""

from __future__ import annotations

from typing import Any

from . import _convert, _ffi
from ._ffi import ffi
from ._types import Id, InputId
from .config import CodecConfig
from .errors import InvalidInput
from .floor import Floor

REASONS = ("no_common_rows", "removed_rows", "changed_ratio", "hamming", "encoder", "row_above_max")


class Verdict:
    """The result of ``Diff.evaluate``: ``passed``, the checks that failed, and the rows above ``max_hamming``.

    ``reasons`` names every failed check, in this order: ``no_common_rows``,
    ``removed_rows``, ``changed_ratio``, ``hamming``, ``encoder``,
    ``row_above_max``. ``rows`` is empty unless the per-row check ran.
    """

    __slots__ = ("passed", "reasons", "rows")

    passed: bool
    reasons: tuple[str, ...]
    rows: list[Id]

    def __init__(self, passed: bool, reasons: tuple[str, ...], rows: list[Id]) -> None:
        self.passed = passed
        self.reasons = reasons
        self.rows = rows

    def __bool__(self) -> bool:
        return self.passed

    def as_dict(self) -> dict[str, Any]:
        """``{"passed", "reasons", "rows"}`` with ids as strings, as in reports."""
        return {"passed": self.passed, "reasons": list(self.reasons), "rows": [str(i) for i in self.rows]}

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Verdict) and (self.passed, self.reasons, self.rows) == (
            other.passed, other.reasons, other.rows,
        )

    def __hash__(self) -> int:
        return hash((self.passed, self.reasons, tuple(self.rows)))

    def __repr__(self) -> str:
        return f"Verdict(passed={self.passed}, reasons={list(self.reasons)!r}, rows={self.rows!r})"


class Diff:
    """The result of ``reference.diff(candidate)``.

    Keeps the rows it needs alive until it is released, even if the caller
    drops its Encodings.
    """

    __slots__ = ("_config", "_d")

    _d: Any
    _config: CodecConfig | None

    def __init__(self) -> None:
        raise TypeError("Diff values come from Encoding.diff")

    @classmethod
    def _from_handle(cls, ptr: Any) -> Diff:
        self = cls.__new__(cls)
        self._d = ffi.gc(ptr, _ffi.lib().semq_diff_free)
        self._config = None
        return self

    @property
    def config(self) -> CodecConfig:
        """The config shared by the reference and the candidate."""
        if self._config is None:
            self._config = CodecConfig(_convert.config_copy(_ffi.lib().semq_diff_config(self._d)))
        return self._config

    @property
    def id_kind(self) -> str:
        """``"u64"`` or ``"utf8"``, shared by both sides."""
        return _convert.kind_name(int(_ffi.lib().semq_diff_id_kind(self._d)))

    @property
    def reference_id(self) -> bytes:
        """``state_id`` of the reference Encoding (32 bytes); a floor applies only to diffs of the same reference."""
        buf = ffi.new("uint8_t[32]")
        _ffi.lib().semq_diff_reference_id(self._d, buf)
        return bytes(ffi.buffer(buf, 32))

    @property
    def candidate_id(self) -> bytes:
        """``state_id`` of the candidate Encoding (32 bytes)."""
        buf = ffi.new("uint8_t[32]")
        _ffi.lib().semq_diff_candidate_id(self._d, buf)
        return bytes(ffi.buffer(buf, 32))

    def _count(self, which: int) -> int:
        return int(_ffi.lib().semq_diff_count(self._d, which))

    def _ids(self, which: int, limit: int | None = None) -> list[Id]:
        lib = _ffi.lib()
        count = self._count(which)
        n = count if limit is None else min(count, max(limit, 0))
        u64 = ffi.new("uint64_t*")
        bytes_p = ffi.new("const uint8_t**")
        length = ffi.new("uint64_t*")
        err = _ffi.new_error()
        out: list[Id] = []
        is_u64 = self.id_kind == "u64"
        for i in range(n):
            _ffi.check(lib.semq_diff_id(self._d, which, i, u64, bytes_p, length, err), err, "diff")
            if is_u64:
                out.append(int(u64[0]))
            else:
                out.append(bytes(ffi.buffer(bytes_p[0], int(length[0]))).decode("utf-8"))
        return out

    @property
    def added(self) -> list[Id]:
        """Ids only in the candidate, canonical order."""
        return self._ids(_ffi.LIST_ADDED)

    @property
    def removed(self) -> list[Id]:
        """Ids only in the reference, canonical order."""
        return self._ids(_ffi.LIST_REMOVED)

    @property
    def changed(self) -> list[tuple[Id, int]]:
        """``(id, hamming)`` for ids on both sides with different rows, canonical order."""
        return self._changed()

    def _changed(self, limit: int | None = None) -> list[tuple[Id, int]]:
        lib = _ffi.lib()
        ids = self._ids(_ffi.LIST_CHANGED, limit)
        h = ffi.new("uint64_t*")
        err = _ffi.new_error()
        out: list[tuple[Id, int]] = []
        for i, id in enumerate(ids):
            _ffi.check(lib.semq_diff_hamming(self._d, i, h, err), err, "diff")
            out.append((id, int(h[0])))
        return out

    def _preview(self, limit: int) -> tuple[tuple[int, list[Id]], tuple[int, list[Id]], tuple[int, list[tuple[Id, int]]]]:
        """Counts and bounded prefixes for human CLI output."""
        return (
            (self._count(_ffi.LIST_ADDED), self._ids(_ffi.LIST_ADDED, limit)),
            (self._count(_ffi.LIST_REMOVED), self._ids(_ffi.LIST_REMOVED, limit)),
            (self._count(_ffi.LIST_CHANGED), self._changed(limit)),
        )

    @property
    def n_unchanged(self) -> int:
        """Ids on both sides whose rows are byte-identical. ``n_unchanged + len(changed)`` is the number of shared rows."""
        return int(_ffi.lib().semq_diff_n_unchanged(self._d))

    @property
    def manifest_changes(self) -> dict[str, tuple[str | None, str | None]]:
        """``key -> (before | None, after | None)`` for keys that differ or exist on one side."""
        lib = _ffi.lib()
        out: dict[str, tuple[str | None, str | None]] = {}
        change = ffi.new("semq_manifest_change_t*")
        err = _ffi.new_error()
        for i in range(int(lib.semq_diff_manifest_changes(self._d))):
            _ffi.check(lib.semq_diff_manifest_change(self._d, i, change, err), err, "diff")
            key = bytes(ffi.buffer(change.key, change.key_len)).decode("utf-8")
            before = (
                bytes(ffi.buffer(change.before, change.before_len)).decode("utf-8") if change.has_before else None
            )
            after = bytes(ffi.buffer(change.after, change.after_len)).decode("utf-8") if change.has_after else None
            out[key] = (before, after)
        return out

    def units(self, id: InputId) -> list[tuple[int, int, int]]:
        """``(unit, symbol_reference, symbol_candidate)`` for every unit of ``id`` that differs.

        Empty for an identical row; ``InvalidInput`` when ``id`` is absent from either side.
        """
        lib = _ffi.lib()
        cap = self.config.units_per_row
        units = ffi.new("uint32_t[]", max(cap, 1))
        ref = ffi.new("uint8_t[]", max(cap, 1))
        cand = ffi.new("uint8_t[]", max(cap, 1))
        count = ffi.new("uint64_t*")
        err = _ffi.new_error()
        if self.id_kind == "u64":
            status = lib.semq_diff_units_u64(self._d, _convert.u64_id(id), units, ref, cand, cap, count, err)
        else:
            ptr, n, keep = _convert.utf8_id_to_c(id)
            status = lib.semq_diff_units_utf8(self._d, ptr, n, units, ref, cand, cap, count, err)
            del keep
        _ffi.check(status, err, "units")
        return [(int(units[i]), int(ref[i]), int(cand[i])) for i in range(int(count[0]))]

    def within(self, floor: Floor) -> bool:
        """True iff the candidate is within ``floor`` (exact integer arithmetic in the core).

        The floor must have been measured with this diff's config, id kind
        and reference; otherwise ``Incompatible``. A change to ``encoder``
        or ``encoder_revision`` is never within.
        """
        if not isinstance(floor, Floor):
            raise InvalidInput("within takes a Floor")
        out = ffi.new("int*")
        err = _ffi.new_error()
        _ffi.check(_ffi.lib().semq_diff_within(self._d, floor._f, out, err), err, "within")
        return bool(out[0])

    def evaluate(self, floor: Floor, *, per_row: bool = False) -> Verdict:
        """The verdict of ``floor`` on this diff, with every check that failed.

        With no options, ``evaluate(floor).passed == within(floor)``. With
        ``per_row=True`` the verdict also fails when any changed row has a
        hamming above ``floor.max_hamming``, and ``rows`` lists those ids;
        a floor without per-row data (one from ``Floor.measure`` without
        ``per_row=True``, or saved by SEMQ 1.0) raises ``Incompatible``.
        """
        if not isinstance(floor, Floor):
            raise InvalidInput("evaluate takes a Floor")
        lib = _ffi.lib()
        err = _ffi.new_error()
        checks = _ffi.CHECK_PER_ROW if per_row else 0
        out = ffi.new("semq_verdict_t**")
        _ffi.check(lib.semq_diff_evaluate(self._d, floor._f, checks, out, err), err, "evaluate")
        v = ffi.gc(out[0], lib.semq_verdict_free)
        reasons = int(lib.semq_verdict_reasons(v))
        changed = self._ids(_ffi.LIST_CHANGED) if lib.semq_verdict_row_count(v) else []
        rows = [changed[int(lib.semq_verdict_row(v, i))] for i in range(int(lib.semq_verdict_row_count(v)))]
        return Verdict(
            bool(lib.semq_verdict_passed(v)),
            tuple(name for bit, name in enumerate(REASONS) if reasons & (1 << bit)),
            rows,
        )

    def as_dict(self) -> dict[str, Any]:
        """The report schema: digests as hex, ``u64`` ids as decimal strings, no floats."""
        def render(id: Id) -> str:
            return str(id)

        return {
            "reference_id": self.reference_id.hex(),
            "candidate_id": self.candidate_id.hex(),
            "id_kind": self.id_kind,
            "config": self.config.as_dict(),
            "added": [render(i) for i in self.added],
            "removed": [render(i) for i in self.removed],
            "changed": [[render(i), h] for i, h in self.changed],
            "n_unchanged": self.n_unchanged,
            "manifest_changes": {k: [b, a] for k, (b, a) in self.manifest_changes.items()},
        }

    def __str__(self) -> str:
        """One sentence: ``1 of 3 rows changed: doc-3 (hamming 3). 0 added, 0 removed.``

        Up to five changed ids are listed; a changed ``encoder`` or
        ``encoder_revision``, or any other manifest key, is named at the end.
        The same text in every binding.
        """
        changed, added, removed = (self._count(w) for w in (_ffi.LIST_CHANGED, _ffi.LIST_ADDED, _ffi.LIST_REMOVED))
        text = f"{changed} of {changed + self.n_unchanged} rows changed"
        if changed:
            shown = ", ".join(f"{id} (hamming {h})" for id, h in self._changed(5))
            text += f": {shown}" + (f", and {changed - 5} more" if changed > 5 else "")
        text += f". {added} added, {removed} removed."
        keys = sorted(self.manifest_changes)
        if keys:
            text += f" Manifest changed: {', '.join(keys)}."
        return text

    def __repr__(self) -> str:
        lib = _ffi.lib()
        return (
            f"Diff(added={lib.semq_diff_count(self._d, 0)}, removed={lib.semq_diff_count(self._d, 1)}, "
            f"changed={lib.semq_diff_count(self._d, 2)}, n_unchanged={self.n_unchanged})"
        )
