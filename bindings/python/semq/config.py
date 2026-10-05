# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""CodecConfig: the rule, discriminated by operator."""

from __future__ import annotations

import enum
from typing import Any

from . import _ffi
from ._ffi import ffi


class Operator(enum.IntEnum):
    """The three operators. Values are pinned in the canonical form."""

    ORBIT = 0
    PHASE = 1
    QUANT = 2


class CodecConfig:
    """An immutable value: operator, dimension and the operator's parameter.

    Build one with :meth:`quant`, :meth:`phase` or :meth:`orbit`. Equality
    is equality of the 13 canonical bytes.
    """

    __slots__ = ("_bytes", "_c")

    def __init__(self, _c: Any) -> None:
        self._c = _c
        buf = ffi.new("uint8_t[13]")
        _ffi.lib().semq_config_to_bytes(_c, buf)
        self._bytes = bytes(ffi.buffer(buf, 13))

    @classmethod
    def _make(cls, ctor: str, dim: int, p1: int) -> CodecConfig:
        _check_uint32(dim, "dim")
        _check_uint32(p1, "parameter")
        out = ffi.new("semq_config_t*")
        err = _ffi.new_error()
        lib = _ffi.lib()
        status = getattr(lib, ctor)(dim, p1, out, err)
        _ffi.check(status, err, ctor)
        return cls(out)

    @classmethod
    def _from_fields(cls, op: int, dim: int, p1: int, p2: int) -> CodecConfig:
        """Adapt ABI fields; C validates them and writes the canonical form."""
        for name, value in zip(("operator", "dim", "parameter", "rule_revision"), (op, dim, p1, p2), strict=True):
            _check_uint32(value, name)
        out = ffi.new("semq_config_t*", {"op": op, "dim": dim, "p1": p1, "p2": p2})
        err = _ffi.new_error()
        _ffi.check(_ffi.lib().semq_config_validate(out, err), err, "config")
        return cls(out)

    @classmethod
    def quant(cls, dim: int, bins: int) -> CodecConfig:
        """quant: sign and magnitude bin per coordinate; ``bins`` in ``[2, 64]``."""
        return cls._make("semq_config_quant", dim, bins)

    @classmethod
    def phase(cls, dim: int, sectors: int) -> CodecConfig:
        """phase: angular sector per coordinate pair; ``sectors`` in ``[2, 256]``."""
        return cls._make("semq_config_phase", dim, sectors)

    @classmethod
    def orbit(cls, dim: int, scale: int = 50) -> CodecConfig:
        """orbit: digital-root symbol per coordinate; ``scale`` in ``[1, 2^30]``."""
        return cls._make("semq_config_orbit", dim, scale)

    @classmethod
    def from_bytes(cls, data: bytes) -> CodecConfig:
        """Parse the 13-byte canonical form."""
        raw = bytes(data)
        if len(raw) != 13:
            from .errors import InvalidInput

            raise InvalidInput(f"config canonical form is 13 bytes, got {len(raw)}")
        out = ffi.new("semq_config_t*")
        err = _ffi.new_error()
        _ffi.check(_ffi.lib().semq_config_from_bytes(raw, out, err), err, "config_from_bytes")
        return cls(out)

    def to_bytes(self) -> bytes:
        """The 13-byte canonical form."""
        return self._bytes

    @property
    def operator(self) -> Operator:
        """Which rule applies: ``Operator.QUANT``, ``PHASE`` or ``ORBIT``."""
        return Operator(self._c.op)

    @property
    def dim(self) -> int:
        """Coordinates per vector; every row encoded under this config has this length."""
        return int(self._c.dim)

    @property
    def rule_revision(self) -> int:
        """Revision of the operator's symbol mapping (``p2`` of the canonical form), currently ``0``.

        It increments only when an operator rule changes; configs with
        different revisions are incompatible.
        """
        return int(self._c.p2)

    @property
    def bins(self) -> int:
        """quant only: magnitude bins per sign, in ``[2, 64]``. ``AttributeError`` for other operators."""
        self._only(Operator.QUANT, "bins")
        return int(self._c.p1)

    @property
    def sectors(self) -> int:
        """phase only: angular sectors per coordinate pair, in ``[2, 256]``. ``AttributeError`` otherwise."""
        self._only(Operator.PHASE, "sectors")
        return int(self._c.p1)

    @property
    def scale(self) -> int:
        """orbit only: the scale applied before taking the symbol, in ``[1, 2^30]``. ``AttributeError`` otherwise."""
        self._only(Operator.ORBIT, "scale")
        return int(self._c.p1)

    @property
    def bytes_per_vector(self) -> int:
        """Packed size of one row in bytes, computed by the core; the second dimension of ``Encoding.rows``."""
        return int(_ffi.lib().semq_config_bytes_per_vector(self._c))

    @property
    def units_per_row(self) -> int:
        """Symbols per row: ``dim`` for quant and orbit, ``dim / 2`` for phase. The upper bound of a hamming distance."""
        return int(_ffi.lib().semq_config_units_per_row(self._c))

    @property
    def max_magnitude(self) -> float:
        """quant only: ``(float)(2.0 / sqrt(dim))``, computed by the core."""
        self._only(Operator.QUANT, "max_magnitude")
        return float(_ffi.lib().semq_config_max_magnitude(self._c))

    def _only(self, op: Operator, name: str) -> None:
        if self._c.op != op:
            raise AttributeError(f"{name} applies to {op.name.lower()} configs only")

    @property
    def parameter_name(self) -> str:
        """The operator's parameter key as used in reports: ``"bins"``, ``"sectors"`` or ``"scale"``."""
        return {Operator.ORBIT: "scale", Operator.PHASE: "sectors", Operator.QUANT: "bins"}[self.operator]

    def as_dict(self) -> dict[str, Any]:
        """``{"operator", "dim", <parameter>, "rule_revision"}`` as in reports."""
        return {
            "operator": self.operator.name.lower(),
            "dim": self.dim,
            self.parameter_name: int(self._c.p1),
            "rule_revision": self.rule_revision,
        }

    def __eq__(self, other: object) -> bool:
        return isinstance(other, CodecConfig) and other._bytes == self._bytes

    def __hash__(self) -> int:
        return hash(self._bytes)

    def __repr__(self) -> str:
        return f"CodecConfig.{self.operator.name.lower()}(dim={self.dim}, {self.parameter_name}={int(self._c.p1)})"

    def __str__(self) -> str:
        """``quant(dim=4, bins=4)``: the form other summaries embed."""
        return f"{self.operator.name.lower()}(dim={self.dim}, {self.parameter_name}={int(self._c.p1)})"


def _check_uint32(value: Any, name: str) -> None:
    from .errors import InvalidInput

    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidInput(f"{name} must be an int")
    if value < 0 or value > 0xFFFFFFFF:
        raise InvalidInput(f"{name} is out of range")
