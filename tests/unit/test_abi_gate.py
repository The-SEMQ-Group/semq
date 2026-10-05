# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
"""The ABI gate must reject unilateral changes, including same-size types."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("semq_abi_gate", ROOT / "tools/check_abi.py")
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def test_ffi_signatures_match_header():
    _, structs, functions, _ = GATE.header()
    py = (ROOT / "bindings/python/semq/_ffi.py").read_text(encoding="utf-8")
    rs = (ROOT / "bindings/rust/semq-sys/src/lib.rs").read_text(encoding="utf-8")
    ts = (ROOT / "bindings/ts/src/native.ts").read_text(encoding="utf-8")
    cmake = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
    GATE.check_python(structs, functions, py)
    GATE.check_rust(structs, functions, rs)
    GATE.check_ts(functions, ts, cmake)
    with pytest.raises(AssertionError):
        GATE.check_python(structs, functions, py.replace("uint64_t row;", "int64_t row;"))
    with pytest.raises(AssertionError):
        GATE.check_rust(structs, functions, rs.replace("id: u64", "id: u32", 1))
    with pytest.raises(AssertionError):
        GATE.check_ts(functions, ts.replace("encodingLen: (enc: number) => bigint", "encodingLen: (enc: number) => number"), cmake)
    with pytest.raises(AssertionError):
        GATE.check_ts(functions, ts, cmake.replace(",_semq_sha256", ""))


@pytest.mark.parametrize("version,missing", [(b"2.0.0", False), (b"1.0.0", True)])
def test_loader_rejects_incompatible_library_before_handles(monkeypatch, version, missing):
    from semq import Native, _ffi

    class Library:
        def semq_core_version(self):
            return _ffi.ffi.new("char[]", version)

        def __getattr__(self, name):
            if missing and name == "semq_codec_create":
                raise AttributeError("symbol not found: " + name)
            raise AssertionError("loader must reject before invoking another function")

    monkeypatch.setattr(_ffi, "_candidate_paths", lambda: [Path("incompatible-library")])
    monkeypatch.setattr(_ffi.ffi, "dlopen", lambda path: Library())
    if missing:
        # Accessing exported addresses is allowed; invoking them is not.
        def symbol(self, name):
            if name == "semq_codec_create":
                raise AttributeError("symbol not found: " + name)
            return lambda *args: pytest.fail("native function called before ABI admission")
        Library.__getattr__ = symbol
    with pytest.raises(Native, match="incompatible SEMQ library"):
        _ffi._load()


def test_loader_never_searches_by_bare_name(monkeypatch):
    # A bare name lets the dynamic loader search the current directory on
    # Windows and macOS. Only SEMQ_LIBRARY_PATH may be relative.
    from semq import _ffi

    monkeypatch.delenv("SEMQ_LIBRARY_PATH", raising=False)
    candidates = list(_ffi._candidate_paths())
    assert candidates
    assert all(path.is_absolute() for path in candidates), candidates
