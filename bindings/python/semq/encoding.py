# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Encoding: a state with an identity."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, Union

import numpy as np
from numpy.typing import NDArray

from . import _convert, _ffi
from ._ffi import ffi
from .config import CodecConfig
from .errors import InvalidInput

if TYPE_CHECKING:
    from .diff import Diff

from ._io import BinaryReader, BinaryWriter, write_binary
from ._types import Id, IdsInput, IdsView, InputId

Source = Union[str, "os.PathLike[str]", bytes, bytearray, memoryview, BinaryReader]


class Encoding:
    """An immutable set of ids with one canonical row each, a manifest and two identities.

    ``content_digest`` identifies the rows under the rule; ``state_id`` adds
    the manifest. Equality of two Encodings is equality of ``state_id``.
    """

    __slots__ = ("_config", "_e", "_ids", "_rows")

    _e: Any
    _config: CodecConfig | None
    _rows: NDArray[np.uint8] | None
    _ids: IdsView | None

    def __init__(
        self,
        ids: IdsInput,
        rows: NDArray[np.uint8] | None,
        config: CodecConfig,
        manifest: dict[str, str] | None = None,
        id_kind: str | None = None,
    ) -> None:
        """Build from rows the caller already holds (``uint8 [n, bytes_per_vector]``)."""
        if not isinstance(config, CodecConfig):
            raise InvalidInput("config must be a CodecConfig")
        c_ids, keep = _convert.ids_to_c(ids, id_kind)
        n = int(c_ids.n)
        bpv = config.bytes_per_vector
        if rows is None:
            arr = np.zeros((0, bpv), dtype=np.uint8)
        else:
            if not isinstance(rows, np.ndarray) or rows.dtype != np.uint8:
                raise InvalidInput("rows must be a numpy uint8 array of shape [n, bytes_per_vector]")
            if rows.ndim != 2 or rows.shape[1] != bpv:
                raise InvalidInput(f"rows must have shape [n, {bpv}], got {rows.shape}")
            arr = np.ascontiguousarray(rows)
        if arr.shape[0] != n:
            raise InvalidInput(f"{n} ids but {arr.shape[0]} rows")
        pairs, n_pairs, keep_m = _convert.manifest_to_c(manifest)
        out = ffi.new("semq_encoding_t**")
        err = _ffi.new_error()
        ptr = ffi.from_buffer("uint8_t[]", arr) if n else ffi.NULL
        status = _ffi.lib().semq_encoding_create(config._c, c_ids, ptr, pairs, n_pairs, out, err)
        del keep, keep_m, ptr
        _ffi.check(status, err, "encoding")
        self._init_handle(out[0])

    @classmethod
    def _from_handle(cls, ptr: Any) -> Encoding:
        self = cls.__new__(cls)
        self._init_handle(ptr)
        return self

    def _init_handle(self, ptr: Any) -> None:
        self._e = ffi.gc(ptr, _ffi.lib().semq_encoding_free)
        self._config = None
        self._rows = None
        self._ids = None

    # ---- persistence -----------------------------------------------------

    @classmethod
    def load(cls, source: Source) -> Encoding:
        """Parse a file image from a path, a binary stream or bytes. Always copies."""
        if isinstance(source, (bytes, bytearray, memoryview)):
            data = bytes(source)
        elif isinstance(source, (str, os.PathLike)):
            with open(source, "rb") as f:
                data = f.read()
        elif hasattr(source, "read"):
            data = source.read()
            if not isinstance(data, (bytes, bytearray)):
                raise InvalidInput("load needs a binary stream")
            data = bytes(data)
        else:
            raise InvalidInput("load takes a path, a binary stream or bytes")
        out = ffi.new("semq_encoding_t**")
        err = _ffi.new_error()
        # An empty buffer is a valid (too short) image, not a missing one.
        ptr = ffi.from_buffer("uint8_t[]", data) if data else ffi.new("uint8_t[1]")
        status = _ffi.lib().semq_encoding_load(ptr, len(data), out, err)
        del ptr
        _ffi.check(status, err, "load")
        return cls._from_handle(out[0])

    def save(self, target: str | os.PathLike[str] | BinaryWriter) -> None:
        """Write to a path (atomic replacement) or binary stream.

        Streams report bytes written; no progress raises BlockingIOError.
        Atomic replacement does not promise durability of the directory entry.
        """
        if isinstance(target, (str, os.PathLike)):
            path = os.fspath(target)
            directory = os.path.dirname(path) or "."
            fd, tmp = tempfile.mkstemp(prefix=".semq-", dir=directory)
            try:
                with os.fdopen(fd, "wb") as f:
                    self._write_parts(f)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        elif hasattr(target, "write"):
            self._write_parts(target)
        else:
            raise InvalidInput("save takes a path or a binary stream")

    def _write_parts(self, f: BinaryWriter) -> None:
        parts = ffi.new("semq_part_t[5]")
        _ffi.lib().semq_encoding_save_parts(self._e, parts)
        for i in range(5):
            n = int(parts[i].len)
            if n:
                write_binary(f, memoryview(ffi.buffer(parts[i].ptr, n)))

    # ---- access ----------------------------------------------------------

    @property
    def config(self) -> CodecConfig:
        """The rule the rows were encoded under; ``diff`` and ``concat`` require equal configs."""
        if self._config is None:
            self._config = CodecConfig(_convert.config_copy(_ffi.lib().semq_encoding_config(self._e)))
        return self._config

    @property
    def id_kind(self) -> str:
        """``"u64"`` or ``"utf8"``: the kind of every id in this Encoding (never mixed)."""
        return _convert.kind_name(int(_ffi.lib().semq_encoding_id_kind(self._e)))

    def _view(self, ptr: Any, nbytes: int) -> NDArray[np.uint8]:
        owner = self._e
        # The view's buffer keeps `p` alive, and `p`'s destructor closure keeps
        # the handle alive, so the C memory outlives every view of it. The
        # array is built over a read-only memoryview: numpy then refuses to
        # set its WRITEABLE flag, so the identity cannot be detached from the
        # bytes it names.
        p = ffi.gc(ffi.cast("uint8_t*", ptr), lambda _p: owner)
        readonly = memoryview(ffi.buffer(p, nbytes)).toreadonly()
        arr: NDArray[np.uint8] = np.frombuffer(readonly, dtype=np.uint8)
        return arr

    @property
    def rows(self) -> NDArray[np.uint8]:
        """Canonical rows in id order: a read-only uint8 view ``[n, bytes_per_vector]``."""
        if self._rows is None:
            length = ffi.new("uint64_t*")
            ptr = _ffi.lib().semq_encoding_rows(self._e, length)
            n = len(self)
            bpv = self.config.bytes_per_vector
            self._rows = self._view(ptr, int(length[0])).reshape(n, bpv)
        return self._rows

    @property
    def ids(self) -> IdsView:
        """Sorted ids: a read-only uint64 view for ``u64``, a tuple of str for ``utf8``."""
        if self._ids is None:
            lib = _ffi.lib()
            n = len(self)
            if self.id_kind == "u64":
                ptr = lib.semq_encoding_ids_u64(self._e)
                self._ids = self._view(ptr, n * 8).view(np.uint64)
            else:
                offsets = lib.semq_encoding_ids_utf8_offsets(self._e)
                length = ffi.new("uint64_t*")
                data = lib.semq_encoding_ids_utf8_bytes(self._e, length)
                blob = bytes(ffi.buffer(data, int(length[0])))
                self._ids = tuple(blob[int(offsets[i]) : int(offsets[i + 1])].decode("utf-8") for i in range(n))
        return self._ids

    @property
    def manifest(self) -> dict[str, str]:
        """The declared string pairs, stored verbatim and never verified.

        ``encoder`` and ``encoder_revision`` are conventions: a diff reports
        changes to them and the gate fails when they change.
        """
        lib = _ffi.lib()
        out: dict[str, str] = {}
        pair = ffi.new("semq_pair_t*")
        err = _ffi.new_error()
        for i in range(int(lib.semq_encoding_manifest_len(self._e))):
            _ffi.check(lib.semq_encoding_manifest_pair(self._e, i, pair, err), err, "manifest")
            key = bytes(ffi.buffer(pair.key, pair.key_len)).decode("utf-8")
            value = bytes(ffi.buffer(pair.value, pair.value_len)).decode("utf-8") if pair.value_len else ""
            out[key] = value
        return out

    @property
    def content_digest(self) -> bytes:
        """SHA-256 (32 bytes) of the config, the id kind, the count, the ids and the rows.

        Answers "same rows under the same rule", whatever the manifest says.
        """
        buf = ffi.new("uint8_t[32]")
        _ffi.lib().semq_encoding_content_digest(self._e, buf)
        return bytes(ffi.buffer(buf, 32))

    @property
    def state_id(self) -> bytes:
        """SHA-256 (32 bytes) of ``content_digest`` and the manifest: the identity of the state as declared.

        Two Encodings are equal when their ``state_id`` is equal.
        """
        buf = ffi.new("uint8_t[32]")
        _ffi.lib().semq_encoding_state_id(self._e, buf)
        return bytes(ffi.buffer(buf, 32))

    def __len__(self) -> int:
        return int(_ffi.lib().semq_encoding_len(self._e))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Encoding):
            return NotImplemented
        return self.state_id == other.state_id

    def __hash__(self) -> int:
        return hash(self.state_id)

    def __iter__(self) -> Iterator[tuple[Id, NDArray[np.uint8]]]:
        ids = self.ids
        rows = self.rows
        for i in range(len(self)):
            yield (int(ids[i]) if self.id_kind == "u64" else ids[i]), rows[i]

    def _find(self, id: object) -> int | None:
        lib = _ffi.lib()
        index = ffi.new("uint64_t*")
        err = _ffi.new_error()
        if self.id_kind == "u64":
            _ffi.check(lib.semq_encoding_find_u64(self._e, _convert.u64_id(id), index, err), err, "get")
        else:
            ptr, n, keep = _convert.utf8_id_to_c(id)
            _ffi.check(lib.semq_encoding_find_utf8(self._e, ptr, n, index, err), err, "get")
            del keep
        return None if index[0] == _ffi.NONE else int(index[0])

    def get(self, id: InputId) -> NDArray[np.uint8]:
        """The row of ``id`` (a read-only view). ``KeyError`` when absent."""
        i = self._find(id)
        if i is None:
            raise KeyError(id)
        row: NDArray[np.uint8] = self.rows[i]
        return row

    def __contains__(self, id: object) -> bool:
        return self._find(id) is not None

    # ---- verbs -----------------------------------------------------------

    def concat(self, *others: Encoding) -> Encoding:
        """Merge with Encodings of the same config, kind and manifest and disjoint ids."""
        parts: list[Encoding] = [self, *others]
        for p in parts:
            if not isinstance(p, Encoding):
                raise InvalidInput("concat takes Encodings")
        arr = ffi.new("const semq_encoding_t*[]", [p._e for p in parts])
        out = ffi.new("semq_encoding_t**")
        err = _ffi.new_error()
        _ffi.check(_ffi.lib().semq_encoding_concat(arr, len(parts), out, err), err, "concat")
        return Encoding._from_handle(out[0])

    def diff(self, candidate: Encoding) -> Diff:
        """``self`` is the reference, ``candidate`` the state under review."""
        from .diff import Diff

        if not isinstance(candidate, Encoding):
            raise InvalidInput("diff takes an Encoding")
        out = ffi.new("semq_diff_t**")
        err = _ffi.new_error()
        _ffi.check(_ffi.lib().semq_encoding_diff(self._e, candidate._e, out, err), err, "diff")
        return Diff._from_handle(out[0])

    def __repr__(self) -> str:
        return f"Encoding({self.config!r}, n={len(self)}, id_kind={self.id_kind!r}, state_id={self.state_id.hex()[:12]}...)"

    def __str__(self) -> str:
        """``Encoding(3 rows, quant(dim=4, bins=4), state_id 40c3aa20252d...)``; the same text in every binding."""
        return f"Encoding({len(self)} rows, {self.config}, state_id {self.state_id.hex()[:12]}...)"
