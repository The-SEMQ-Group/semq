# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Representation checks and conversions between Python objects and the C ABI.

The host validates what only it can see (Python types, surrogates, integer
ranges); every rule about bytes stays in the core.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray

from . import _ffi
from ._ffi import ffi
from .errors import InvalidInput

_KINDS = {"u64": _ffi.ID_U64, "utf8": _ffi.ID_UTF8}
_KIND_NAMES = {v: k for k, v in _KINDS.items()}


def kind_name(kind: int) -> str:
    return _KIND_NAMES[kind]


def ids_to_c(ids: Any, id_kind: str | None) -> tuple[Any, list[Any]]:
    """Build a ``semq_ids_t`` from a sequence of ints or strs.

    Returns the struct and a list of objects that must stay alive while the
    struct is in use.
    """
    if id_kind is not None and id_kind not in _KINDS:
        raise InvalidInput("id_kind must be 'u64' or 'utf8'")
    if isinstance(ids, np.ndarray):
        if ids.ndim != 1:
            raise InvalidInput("ids must be one-dimensional")
        if ids.dtype.kind in "iu":
            inferred = "u64"
        elif ids.dtype.kind in "UO":
            inferred = "utf8"
            ids = ids.tolist()
        else:
            raise InvalidInput("ids must be integers (u64) or strings (utf8)")
    else:
        ids = list(ids)
        if ids:
            first = ids[0]
            if isinstance(first, bool):
                raise InvalidInput("ids must be integers (u64) or strings (utf8)", row=0)
            if isinstance(first, (int, np.integer)):
                inferred = "u64"
            elif isinstance(first, str):
                inferred = "utf8"
            else:
                raise InvalidInput("ids must be integers (u64) or strings (utf8)", row=0)
        else:
            inferred = ""
    n = len(ids)
    if n == 0:
        if id_kind is None:
            raise InvalidInput("id_kind is required for an empty encoding")
        kind = id_kind
    else:
        if id_kind is not None and id_kind != inferred:
            raise InvalidInput(f"ids are {inferred} but id_kind is {id_kind}", row=0)
        kind = inferred

    keep: list[Any] = []
    s = ffi.new("semq_ids_t*")
    s.kind = _KINDS[kind]
    s.n = n
    if kind == "u64":
        if isinstance(ids, np.ndarray):
            if ids.dtype.kind == "i" and ids.size and int(ids.min()) < 0:
                raise InvalidInput("u64 ids must be non-negative", row=int(np.argmin(ids)))
            arr = np.ascontiguousarray(ids, dtype=np.uint64)
        else:
            arr = np.empty(n, dtype=np.uint64)
            for i, v in enumerate(ids):
                if isinstance(v, bool) or not isinstance(v, (int, np.integer)):
                    raise InvalidInput("ids must all be integers", row=i)
                iv = int(v)
                if iv < 0 or iv >= 2**64:
                    raise InvalidInput("u64 id is out of range", row=i)
                arr[i] = iv
        keep.append(arr)
        s.u64 = ffi.from_buffer("uint64_t[]", arr) if n else ffi.NULL
    else:
        chunks: list[bytes] = []
        offsets = np.zeros(n + 1, dtype=np.uint64)
        total = 0
        for i, v in enumerate(ids):
            if not isinstance(v, str):
                raise InvalidInput("ids must all be strings", row=i)
            try:
                b = v.encode("utf-8")
            except UnicodeEncodeError:
                raise InvalidInput("utf8 id contains a lone surrogate", row=i) from None
            chunks.append(b)
            total += len(b)
            offsets[i + 1] = total
        blob = b"".join(chunks)
        keep.extend([offsets, blob])
        s.utf8_offsets = ffi.from_buffer("uint64_t[]", offsets)
        s.utf8_bytes = ffi.from_buffer("uint8_t[]", blob) if blob else ffi.NULL
    keep.append(s)
    return s, keep


def manifest_to_c(manifest: dict[str, str] | None) -> tuple[Any, int, list[Any]]:
    """Build a ``semq_pair_t[]`` from a ``dict[str, str]``."""
    if manifest is None:
        return ffi.NULL, 0, []
    if not isinstance(manifest, dict):
        raise InvalidInput("manifest must be a dict of str to str")
    keep: list[Any] = []
    pairs = ffi.new("semq_pair_t[]", max(len(manifest), 1))
    for i, (k, v) in enumerate(manifest.items()):
        if not isinstance(k, str) or not isinstance(v, str):
            raise InvalidInput("manifest keys and values must be str", field=i)
        try:
            kb = k.encode("utf-8")
            vb = v.encode("utf-8")
        except UnicodeEncodeError:
            raise InvalidInput("manifest text contains a lone surrogate", field=i) from None
        keep.extend([kb, vb])
        pairs[i].key = ffi.from_buffer("uint8_t[]", kb)
        pairs[i].key_len = len(kb)
        pairs[i].value = ffi.from_buffer("uint8_t[]", vb) if vb else ffi.NULL
        pairs[i].value_len = len(vb)
    keep.append(pairs)
    return pairs, len(manifest), keep


def utf8_id_to_c(id: Any) -> tuple[Any, int, bytes]:
    if not isinstance(id, str):
        raise InvalidInput("id must be a str for a utf8 encoding")
    try:
        b = id.encode("utf-8")
    except UnicodeEncodeError:
        raise InvalidInput("utf8 id contains a lone surrogate") from None
    return (ffi.from_buffer("uint8_t[]", b) if b else ffi.NULL), len(b), b


def u64_id(id: Any) -> int:
    if isinstance(id, bool) or not isinstance(id, (int, np.integer)):
        raise InvalidInput("id must be an int for a u64 encoding")
    iv = int(id)
    if iv < 0 or iv >= 2**64:
        raise InvalidInput("u64 id is out of range")
    return iv


def config_copy(ptr: Any) -> Any:
    """Copy a ``const semq_config_t*`` owned by a handle into a fresh struct."""
    return ffi.new("semq_config_t*", {"op": ptr.op, "dim": ptr.dim, "p1": ptr.p1, "p2": ptr.p2})


def to_float32_matrix(vectors: object, dim: int) -> NDArray[np.float32]:
    """Validate the representation of ``vectors``: float32, shape ``[n, dim]``."""
    if not isinstance(vectors, np.ndarray):
        raise InvalidInput("vectors must be a numpy float32 array of shape [n, dim]")
    if vectors.dtype != np.float32:
        raise InvalidInput(f"vectors must be float32, got {vectors.dtype}")
    if vectors.ndim != 2:
        raise InvalidInput(f"vectors must have shape [n, dim], got {vectors.shape}")
    if vectors.shape[1] != dim:
        raise InvalidInput(f"vectors have dim {vectors.shape[1]}, config has dim {dim}")
    return np.ascontiguousarray(vectors)
