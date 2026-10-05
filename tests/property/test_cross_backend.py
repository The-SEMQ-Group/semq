# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Cross-backend byte identity.

``SEMQ_FORCE_BACKEND`` selects the kernel when a Codec is created. The same
unit-norm input encoded under the scalar kernel and under the host's SIMD
kernel must produce the same content digest for every operator.
"""

from __future__ import annotations

import os
import platform

import numpy as np
import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from semq import Codec, CodecConfig

_IS_ARM64 = platform.machine() in ("arm64", "aarch64")
_IS_X86_64 = platform.machine() in ("x86_64", "amd64", "AMD64")


def _codec(backend: str, config: CodecConfig) -> Codec:
    os.environ["SEMQ_FORCE_BACKEND"] = backend
    try:
        return Codec(config)
    finally:
        os.environ.pop("SEMQ_FORCE_BACKEND", None)


def _available(name: str) -> bool:
    return _codec(name, CodecConfig.orbit(8)).backend == name


_HAS_NEON = _IS_ARM64 and _available("neon")
_HAS_SVE = _IS_ARM64 and _available("sve")
_HAS_AVX2 = _IS_X86_64 and _available("avx2")
_HAS_AVX512 = _IS_X86_64 and _available("avx512")
_SIMD = [n for n, ok in (("neon", _HAS_NEON), ("sve", _HAS_SVE), ("avx2", _HAS_AVX2), ("avx512", _HAS_AVX512)) if ok]
_QUANT_SIMD = [name for name in _SIMD if name != "sve"]

_DIMS = st.sampled_from([4, 8, 16, 20, 32, 36, 64, 68, 128, 384, 768, 1024, 1028])


def _unit_rows(dim: int, n: int = 3) -> st.SearchStrategy[np.ndarray]:
    def normalize(rows: list[list[float]]) -> np.ndarray:
        arr = np.asarray(rows, dtype=np.float64)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        assume(np.all(norms > 1e-6))
        out = (arr / norms).astype(np.float32)
        assume(np.all(np.abs(np.sum(out.astype(np.float64) ** 2, axis=1) - 1.0) <= 2**-10))
        return out

    return st.lists(
        st.lists(st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, width=32), min_size=dim, max_size=dim),
        min_size=n,
        max_size=n,
    ).map(normalize)


def test_force_backend_flips_the_kernel() -> None:
    assert _codec("scalar", CodecConfig.orbit(8)).backend == "scalar"
    # An unknown name is ignored: the dispatcher selects as if unset.
    assert _codec("totally-bogus", CodecConfig.orbit(8)).backend == Codec(CodecConfig.orbit(8)).backend


def test_wrong_architecture_requests_fall_back_to_scalar() -> None:
    other = "avx2" if _IS_ARM64 else "neon"
    assert _codec(other, CodecConfig.orbit(8)).backend == "scalar"


@pytest.mark.parametrize("backend", _QUANT_SIMD)
def test_quant_uses_selected_simd_backend(backend: str) -> None:
    assert _codec(backend, CodecConfig.quant(8, 4)).backend == backend


@pytest.mark.skipif(not _HAS_SVE, reason="SVE is unavailable on this host")
def test_quant_uses_neon_on_sve_hosts() -> None:
    assert _codec("sve", CodecConfig.quant(8, 4)).backend == "neon"


@pytest.mark.parametrize("backend", _SIMD)
@pytest.mark.parametrize("bins", [2, 3, 4, 5, 8, 17, 64])
@settings(deadline=None, max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(dim=_DIMS, data=st.data())
def test_quant_simd_matches_scalar(backend: str, bins: int, dim: int, data: st.DataObject) -> None:
    rows = data.draw(_unit_rows(dim))
    cfg = CodecConfig.quant(dim, bins)
    scalar = _codec("scalar", cfg).encode(ids=[1, 2, 3], vectors=rows)
    simd = _codec(backend, cfg).encode(ids=[1, 2, 3], vectors=rows)
    assert scalar.rows.tobytes() == simd.rows.tobytes()
    assert scalar.state_id == simd.state_id


@pytest.mark.parametrize("backend", _SIMD)
@pytest.mark.parametrize("bins", [2, 3, 4, 5, 8, 17, 64])
def test_quant_simd_matches_scalar_at_bin_boundaries(backend: str, bins: int) -> None:
    cfg = CodecConfig.quant(64, bins)
    vectors = []
    for boundary in range(1, bins):
        center = np.float32(cfg.max_magnitude * boundary / bins)
        for magnitude in (
            np.nextafter(center, np.float32(0)),
            center,
            np.nextafter(center, np.float32(1)),
        ):
            for sign in (-1, 1):
                row = np.zeros(64, dtype=np.float32)
                row[0] = magnitude * sign
                row[1] = np.float32(np.sqrt(1.0 - float(magnitude) ** 2))
                vectors.append(row)
    data = np.stack(vectors)
    ids = list(range(len(data)))
    scalar = _codec("scalar", cfg).encode(ids=ids, vectors=data)
    simd = _codec(backend, cfg).encode(ids=ids, vectors=data)
    assert scalar.rows.tobytes() == simd.rows.tobytes()


@pytest.mark.skipif(not _SIMD, reason="no SIMD kernel on this host")
@pytest.mark.parametrize("backend", _SIMD)
@settings(deadline=None, max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(dim=_DIMS, data=st.data())
def test_orbit_simd_matches_scalar(backend: str, dim: int, data: st.DataObject) -> None:
    rows = data.draw(_unit_rows(dim))
    cfg = CodecConfig.orbit(dim)
    s = _codec("scalar", cfg).encode(ids=[1, 2, 3], vectors=rows)
    v = _codec(backend, cfg).encode(ids=[1, 2, 3], vectors=rows)
    assert s.content_digest == v.content_digest


@pytest.mark.skipif(not _SIMD, reason="no SIMD kernel on this host")
@pytest.mark.parametrize("backend", _SIMD)
@pytest.mark.parametrize("sectors", [2, 8, 16, 17, 256])
@settings(deadline=None, max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(dim=_DIMS, data=st.data())
def test_phase_simd_matches_scalar(backend: str, sectors: int, dim: int, data: st.DataObject) -> None:
    rows = data.draw(_unit_rows(dim))
    cfg = CodecConfig.phase(dim, sectors)
    s = _codec("scalar", cfg).encode(ids=[1, 2, 3], vectors=rows)
    v = _codec(backend, cfg).encode(ids=[1, 2, 3], vectors=rows)
    assert s.content_digest == v.content_digest


@pytest.mark.skipif(not _SIMD, reason="no SIMD kernel on this host")
@pytest.mark.parametrize("backend", _SIMD)
@settings(deadline=None, max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(dim=_DIMS, data=st.data())
def test_decode_matches_scalar(backend: str, dim: int, data: st.DataObject) -> None:
    rows = data.draw(_unit_rows(dim))
    cfg = CodecConfig.orbit(dim)
    s = _codec("scalar", cfg)
    v = _codec(backend, cfg)
    e = s.encode(ids=[1, 2, 3], vectors=rows)
    np.testing.assert_array_equal(s.decode(e), v.decode(e))
