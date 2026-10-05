# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Codec: the machine that applies a CodecConfig."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from . import _convert, _ffi
from ._ffi import ffi
from ._types import IdsInput
from .config import CodecConfig
from .encoding import Encoding
from .errors import InvalidInput


class Codec:
    """An immutable encoder for one :class:`CodecConfig`, safe to share between threads."""

    __slots__ = ("_c", "_config")

    def __init__(self, config: CodecConfig) -> None:
        if not isinstance(config, CodecConfig):
            raise InvalidInput("Codec takes a CodecConfig")
        out = ffi.new("semq_codec_t**")
        err = _ffi.new_error()
        lib = _ffi.lib()
        _ffi.check(lib.semq_codec_create(config._c, out, err), err, "codec")
        self._c = ffi.gc(out[0], lib.semq_codec_free)
        self._config = config

    @classmethod
    def quant(cls, dim: int, bins: int) -> Codec:
        """A codec for ``CodecConfig.quant(dim, bins)``: sign and magnitude bin per coordinate."""
        return cls(CodecConfig.quant(dim, bins))

    @classmethod
    def phase(cls, dim: int, sectors: int) -> Codec:
        """A codec for ``CodecConfig.phase(dim, sectors)``: angular sector per coordinate pair."""
        return cls(CodecConfig.phase(dim, sectors))

    @classmethod
    def orbit(cls, dim: int, scale: int = 50) -> Codec:
        """A codec for ``CodecConfig.orbit(dim, scale)``: one discrete symbol per coordinate."""
        return cls(CodecConfig.orbit(dim, scale))

    @property
    def config(self) -> CodecConfig:
        """The rule this codec applies; every Encoding it produces carries the same config."""
        return self._config

    @property
    def backend(self) -> str:
        """The kernel the core runs for this operator on this host."""
        return _ffi.string(_ffi.lib().semq_codec_backend(self._c))

    def encode(
        self,
        vectors: NDArray[np.float32] | None,
        *,
        ids: IdsInput,
        manifest: dict[str, str] | None = None,
        id_kind: str | None = None,
    ) -> Encoding:
        """Encode ``vectors`` (float32, ``[n, dim]``, unit-norm) under ``ids``.

        ``id_kind`` is inferred from the first id and required when ``n = 0``.
        Row errors carry the input row index.
        """
        c_ids, keep = _convert.ids_to_c(ids, id_kind)
        n = int(c_ids.n)
        if vectors is None:
            if n != 0:
                raise InvalidInput("vectors is required")
            arr = np.zeros((0, self._config.dim), dtype=np.float32)
        else:
            arr = _convert.to_float32_matrix(vectors, self._config.dim)
        if arr.shape[0] != n:
            raise InvalidInput(f"{n} ids but {arr.shape[0]} vectors")
        pairs, n_pairs, keep_m = _convert.manifest_to_c(manifest)
        out = ffi.new("semq_encoding_t**")
        err = _ffi.new_error()
        vec_ptr = ffi.from_buffer("float[]", arr) if n else ffi.NULL
        status = _ffi.lib().semq_codec_encode(self._c, c_ids, vec_ptr, pairs, n_pairs, out, err)
        del keep, keep_m, vec_ptr
        _ffi.check(status, err, "encode")
        return Encoding._from_handle(out[0])

    def decode(self, encoding: Encoding) -> NDArray[np.float32]:
        """Representatives, float32 ``[n, dim]``, row ``i`` for ``encoding.ids[i]``. Not normalized."""
        n = len(encoding)
        out = np.empty((n, self._config.dim), dtype=np.float32)
        err = _ffi.new_error()
        ptr = ffi.from_buffer("float[]", out) if n else ffi.NULL
        _ffi.check(_ffi.lib().semq_codec_decode(self._c, encoding._e, ptr, err), err, "decode")
        return out

    def unpack(self, encoding: Encoding) -> NDArray[np.uint8]:
        """Symbols, uint8 ``[n, units_per_row]``."""
        n = len(encoding)
        out = np.empty((n, self._config.units_per_row), dtype=np.uint8)
        err = _ffi.new_error()
        ptr = ffi.from_buffer("uint8_t[]", out) if n else ffi.NULL
        _ffi.check(_ffi.lib().semq_codec_unpack(self._c, encoding._e, ptr, err), err, "unpack")
        return out

    def __repr__(self) -> str:
        return f"Codec({self._config!r}, backend={self.backend!r})"
