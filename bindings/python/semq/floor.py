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
_COUNTS = ("nulls", "changed_rows", "total_rows", "hamming", "max_hamming")

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

    A measured floor also records ``max_hamming``, the largest hamming of
    any changed row of any null, for the per-row check of
    ``Diff.evaluate``. A floor read from JSON without it, such as one saved
    by SEMQ 1.0, has ``max_hamming`` ``None``.

    The JSON form is written and read by the core: ``save``/``load`` and
    ``as_dict``/``from_dict`` apply the same rules in every binding.
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
        max_hamming: int | None = None,
    ) -> None:
        if not isinstance(config, CodecConfig):
            raise InvalidInput("floor.config must be a CodecConfig")
        if id_kind not in _convert._KINDS:
            raise InvalidInput("floor.id_kind must be 'u64' or 'utf8'")
        rid = bytes(reference_id) if isinstance(reference_id, (bytes, bytearray, memoryview)) else None
        if rid is None or len(rid) != 32:
            raise InvalidInput("floor.reference_id must be 32 bytes")
        values = (nulls, changed_rows, total_rows, hamming) + (() if max_hamming is None else (max_hamming,))
        counts = [_count(n, v) for n, v in zip(_COUNTS, values, strict=False)]
        out = ffi.new("semq_floor_t**")
        err = _ffi.new_error()
        kind = _convert._KINDS[id_kind]
        if max_hamming is None:
            status = _ffi.lib().semq_floor_create(config._c, kind, rid, *counts, out, err)
        else:
            status = _ffi.lib().semq_floor_create_with_max(config._c, kind, rid, *counts, out, err)
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

    @property
    def max_hamming(self) -> int | None:
        """The largest hamming of any changed row of any null (``0`` when no null changed a row).

        ``Diff.evaluate(floor, per_row=True)`` flags every changed row above
        it. ``None`` for a floor that does not record it: one built without
        ``max_hamming`` or read from JSON without it.
        """
        v = int(_ffi.lib().semq_floor_max_hamming(self._f))
        return None if v == _ffi.NONE else v

    # ---- report form -----------------------------------------------------

    def _json(self) -> bytes:
        """The floor's JSON form, written by the core."""
        lib = _ffi.lib()
        n = int(lib.semq_floor_json_size(self._f))
        buf = ffi.new("uint8_t[]", max(n, 1))
        err = _ffi.new_error()
        _ffi.check(lib.semq_floor_save(self._f, buf, n, err), err, "save")
        return bytes(ffi.buffer(buf, n))

    @classmethod
    def _from_json(cls, raw: bytes) -> Floor:
        out = ffi.new("semq_floor_t**")
        err = _ffi.new_error()
        _ffi.check(_ffi.lib().semq_floor_load(raw, len(raw), out, err), err, "load")
        return cls._from_handle(out[0])

    def as_dict(self) -> dict[str, Any]:
        """The floor schema as a dict: the config as in reports, the reference id as hex.

        ``max_hamming`` is present only when the floor records it.
        """
        out: dict[str, Any] = json.loads(self._json())
        return out

    @classmethod
    def from_dict(cls, data: object) -> Floor:
        """The inverse of ``as_dict``, by the core's rules for the floor schema.

        Unknown keys are ignored; known keys are checked strictly (integers
        only, no booleans or floats). Anything else is ``InvalidInput``.
        """
        try:
            text = json.dumps(data, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise InvalidInput(f"floor is not a JSON value: {exc}") from exc
        return cls._from_json(text.encode("utf-8", "surrogatepass"))

    # ---- persistence -----------------------------------------------------

    def save(self, target: str | os.PathLike[str] | TextWriter) -> None:
        """Write the floor's JSON form, and a newline, to a path or a text stream."""
        text = self._json().decode("utf-8") + "\n"
        if isinstance(target, (str, os.PathLike)):
            with open(target, "w", encoding="utf-8") as f:
                f.write(text)
        elif hasattr(target, "write"):
            write_text(target, text)
        else:
            raise InvalidInput("save takes a path or a text stream")

    @classmethod
    def load(cls, source: Source) -> Floor:
        """Read the floor's JSON form from a path, a text or binary stream, or bytes."""
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
        return cls._from_json(raw.encode("utf-8", "surrogatepass") if isinstance(raw, str) else bytes(raw))

    # ---- value semantics -------------------------------------------------

    def _key(self) -> tuple[CodecConfig, str, bytes, int, int, int, int, int | None]:
        return (
            self._config, self.id_kind, self.reference_id, self.nulls, self.changed_rows, self.total_rows, self.hamming,
            self.max_hamming,
        )

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
            f"max_hamming={self.max_hamming}, "
            f"nulls={self.nulls}, config={self._config!r}, id_kind={self.id_kind!r}, "
            f"reference_id={self.reference_id.hex()!r})"
        )
