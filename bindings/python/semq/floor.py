# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Floor: how much changes without a cause, bound to where it was measured."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Union

from . import _convert, _ffi
from ._ffi import ffi
from ._io import TextOrBinaryReader, TextWriter, write_text
from .config import CodecConfig
from .errors import InvalidInput

if TYPE_CHECKING:
    from .diff import Diff

FLOOR_VERSION = "semq-floor/1"
_KEYS = ("version", "config", "id_kind", "reference_id", "nulls", "changed_rows", "total_rows", "hamming")
_COUNTS = ("nulls", "changed_rows", "total_rows", "hamming")

Source = Union[str, "os.PathLike[str]", bytes, bytearray, memoryview, TextOrBinaryReader]


def _count(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value >= 2**64:
        raise InvalidInput(f"floor.{name} must be a non-negative int")
    return value


class Floor:
    """An envelope of observed variation: ``(changed_rows, total_rows, hamming)``
    measured from null rebuilds, bound to the config, the id kind and the
    reference state those nulls were taken against.

    A diff is within the floor when it removes no rows, shares at least one
    row with its reference, changes at most ``changed_rows / total_rows`` of
    the shared rows, the nearest-rank p99 of its changed-row hamming
    distances does not exceed ``hamming``, and it changes neither
    ``encoder`` nor ``encoder_revision``. Added rows do not affect the
    verdict. Applying a floor to a diff of another config, id kind or
    reference raises ``Incompatible``. The floor describes what was
    observed; it claims no probabilistic coverage of the next rebuild.
    """

    __slots__ = ("_config", "_f")

    _f: Any
    _config: CodecConfig

    def __init__(
        self,
        config: CodecConfig,
        *,
        id_kind: str,
        reference_id: bytes,
        nulls: int,
        changed_rows: int,
        total_rows: int,
        hamming: int,
    ) -> None:
        if not isinstance(config, CodecConfig):
            raise InvalidInput("floor.config must be a CodecConfig")
        if id_kind not in _convert._KINDS:
            raise InvalidInput("floor.id_kind must be 'u64' or 'utf8'")
        rid = bytes(reference_id) if isinstance(reference_id, (bytes, bytearray, memoryview)) else None
        if rid is None or len(rid) != 32:
            raise InvalidInput("floor.reference_id must be 32 bytes")
        counts = [_count(n, v) for n, v in zip(_COUNTS, (nulls, changed_rows, total_rows, hamming), strict=True)]
        out = ffi.new("semq_floor_t**")
        err = _ffi.new_error()
        status = _ffi.lib().semq_floor_create(config._c, _convert._KINDS[id_kind], rid, *counts, out, err)
        _ffi.check(status, err, "floor")
        self._f = ffi.gc(out[0], _ffi.lib().semq_floor_free)
        self._config = config

    @classmethod
    def _from_handle(cls, ptr: Any) -> Floor:
        self = cls.__new__(cls)
        self._f = ffi.gc(ptr, _ffi.lib().semq_floor_free)
        self._config = CodecConfig(_convert.config_copy(_ffi.lib().semq_floor_config(ptr)))
        return self

    @classmethod
    def measure(cls, null_diffs: Iterable[Diff]) -> Floor:
        """The envelope of one or more null diffs of one reference; every input is within the result."""
        from .diff import Diff

        diffs = list(null_diffs)
        if not diffs:
            raise InvalidInput("measure needs at least one null diff")
        for d in diffs:
            if not isinstance(d, Diff):
                raise InvalidInput("measure takes Diff values")
        arr = ffi.new("const semq_diff_t*[]", [d._d for d in diffs])
        out = ffi.new("semq_floor_t**")
        err = _ffi.new_error()
        _ffi.check(_ffi.lib().semq_floor_measure(arr, len(diffs), out, err), err, "measure")
        return cls._from_handle(out[0])

    # ---- fields ----------------------------------------------------------

    @property
    def config(self) -> CodecConfig:
        """The config the nulls were encoded under; a diff of another config is ``Incompatible`` with this floor."""
        return self._config

    @property
    def id_kind(self) -> str:
        """``"u64"`` or ``"utf8"``: the id kind the floor was measured on."""
        return _convert.kind_name(int(_ffi.lib().semq_floor_id_kind(self._f)))

    @property
    def reference_id(self) -> bytes:
        """``state_id`` (32 bytes) of the reference every null was diffed against. The floor applies only to diffs of that reference."""
        buf = ffi.new("uint8_t[32]")
        _ffi.lib().semq_floor_reference_id(self._f, buf)
        return bytes(ffi.buffer(buf, 32))

    @property
    def nulls(self) -> int:
        """How many null diffs the floor was measured from (at least ``1``)."""
        return int(_ffi.lib().semq_floor_nulls(self._f))

    @property
    def changed_rows(self) -> int:
        """Numerator of the floor's ratio: changed rows in the null with the largest ``changed_rows / total_rows``."""
        return int(_ffi.lib().semq_floor_changed_rows(self._f))

    @property
    def total_rows(self) -> int:
        """Denominator of the floor's ratio: rows shared with the reference in that same null (at least ``1``)."""
        return int(_ffi.lib().semq_floor_total_rows(self._f))

    @property
    def hamming(self) -> int:
        """The largest per-null p99 of changed-row hamming distances (``0`` when no null changed a row).

        p99 is nearest-rank: of ``m`` distances, the ``m - m // 100``-th
        smallest, so it equals the maximum below 100 changed rows. A
        candidate's p99 must not exceed it. The ratio and this bound may
        come from different nulls.
        """
        return int(_ffi.lib().semq_floor_hamming(self._f))

    # ---- report form -----------------------------------------------------

    def as_dict(self) -> dict[str, Any]:
        """The ``semq-floor/1`` schema: the config as in reports, the reference id as hex."""
        return {
            "version": FLOOR_VERSION,
            "config": self.config.as_dict(),
            "id_kind": self.id_kind,
            "reference_id": self.reference_id.hex(),
            "nulls": self.nulls,
            "changed_rows": self.changed_rows,
            "total_rows": self.total_rows,
            "hamming": self.hamming,
        }

    @classmethod
    def from_dict(cls, data: object) -> Floor:
        """The inverse of ``as_dict``, strictly: those keys, that version, integers only."""
        if not isinstance(data, dict) or set(data) != set(_KEYS):
            raise InvalidInput(f"floor must have exactly the keys {', '.join(_KEYS)}")
        if data["version"] != FLOOR_VERSION:
            raise InvalidInput(f"floor.version must be {FLOOR_VERSION!r}")
        rid = data["reference_id"]
        try:
            reference_id = bytes.fromhex(rid) if isinstance(rid, str) and len(rid) == 64 else b""
        except ValueError:
            reference_id = b""
        return cls(
            _config_from_dict(data["config"]),
            id_kind=data["id_kind"] if isinstance(data["id_kind"], str) else "",
            reference_id=reference_id,
            nulls=data["nulls"],
            changed_rows=data["changed_rows"],
            total_rows=data["total_rows"],
            hamming=data["hamming"],
        )

    # ---- persistence -----------------------------------------------------

    def save(self, target: str | os.PathLike[str] | TextWriter) -> None:
        """Write ``as_dict()`` as JSON to a path or a text stream."""
        text = json.dumps(self.as_dict()) + "\n"
        if isinstance(target, (str, os.PathLike)):
            with open(target, "w", encoding="utf-8") as f:
                f.write(text)
        elif hasattr(target, "write"):
            write_text(target, text)
        else:
            raise InvalidInput("save takes a path or a text stream")

    @classmethod
    def load(cls, source: Source) -> Floor:
        """Parse ``as_dict()`` JSON from a path, a text or binary stream, or bytes."""
        if isinstance(source, (bytes, bytearray, memoryview)):
            raw: bytes | str = bytes(source)
        elif isinstance(source, (str, os.PathLike)):
            with open(source, "rb") as f:
                raw = f.read()
        elif hasattr(source, "read"):
            raw = source.read()
            if not isinstance(raw, (bytes, bytearray, str)):
                raise InvalidInput("load needs a text or binary stream")
        else:
            raise InvalidInput("load takes a path, a stream or bytes")
        try:
            text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
        except UnicodeDecodeError as exc:
            raise InvalidInput("floor is not UTF-8") from exc
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise InvalidInput(f"floor is not valid JSON: {exc}") from exc
        return cls.from_dict(data)

    # ---- value semantics -------------------------------------------------

    def _key(self) -> tuple[CodecConfig, str, bytes, int, int, int, int]:
        return (self._config, self.id_kind, self.reference_id, self.nulls, self.changed_rows, self.total_rows, self.hamming)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Floor) and self._key() == other._key()

    def __hash__(self) -> int:
        return hash(self._key())

    def __str__(self) -> str:
        """``Floor(1 of 3 rows, hamming 1, from 3 nulls)``; the same text in every binding."""
        return f"Floor({self.changed_rows} of {self.total_rows} rows, hamming {self.hamming}, from {self.nulls} nulls)"

    def __repr__(self) -> str:
        return (
            f"Floor(changed_rows={self.changed_rows}, total_rows={self.total_rows}, hamming={self.hamming}, "
            f"nulls={self.nulls}, config={self._config!r}, id_kind={self.id_kind!r}, "
            f"reference_id={self.reference_id.hex()!r})"
        )


_OPERATORS = {"orbit": (0, "scale"), "phase": (1, "sectors"), "quant": (2, "bins")}


def _config_from_dict(data: object) -> CodecConfig:
    """The report form of a config back into a ``CodecConfig``.

    The host checks the shape (those four keys, integers that fit the ABI);
    every validity rule, the rule revision included, is the core's, through
    the ABI fields.
    """
    if not isinstance(data, dict) or not isinstance(data.get("operator"), str) or data["operator"] not in _OPERATORS:
        raise InvalidInput("floor.config must be a config report")
    op, parameter = _OPERATORS[data["operator"]]
    if set(data) != {"operator", "dim", parameter, "rule_revision"}:
        raise InvalidInput("floor.config must be a config report")
    fields = [_count(f"config.{k}", data[k]) for k in ("dim", parameter, "rule_revision")]
    if any(v >= 2**32 for v in fields):
        raise InvalidInput("floor.config fields must fit in 32 bits")
    return CodecConfig._from_fields(op, *fields)
