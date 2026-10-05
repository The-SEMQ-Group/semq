# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
"""Regressions at the IO, canonicalization and documented-error boundaries."""

import io
from pathlib import Path

import numpy as np
import pytest

from semq import CodecConfig, Encoding, Floor, Incompatible


def sample():
    return Encoding([1], np.zeros((1, 2), dtype=np.uint8), CodecConfig.quant(4, 4))


@pytest.mark.parametrize("result", [None, 0])
def test_save_reports_a_stream_without_progress(result):
    class Blocked(io.RawIOBase):
        def write(self, data):
            return result

    with pytest.raises(BlockingIOError):
        sample().save(Blocked())


def test_save_retries_partial_writes_and_preserves_exceptions():
    class Partial(io.RawIOBase):
        def __init__(self):
            self.data = bytearray()

        def write(self, data):
            self.data.extend(data[:3])
            return min(3, len(data))

    sink = Partial()
    enc = sample()
    enc.save(sink)
    assert Encoding.load(sink.data) == enc

    failure = OSError("disk unavailable")

    class Broken(Partial):
        def write(self, data):
            if self.data:
                raise failure
            return super().write(data)

    with pytest.raises(OSError) as caught:
        enc.save(Broken())
    assert caught.value is failure


def test_floor_report_does_not_enter_the_binary_config_parser(monkeypatch):
    floor = Floor.measure([sample().diff(sample())])

    def binary_parser_is_not_a_json_adapter(*args, **kwargs):
        raise AssertionError("JSON fields must enter through the validated ABI fields")

    monkeypatch.setattr(CodecConfig, "from_bytes", binary_parser_is_not_a_json_adapter)
    assert Floor.from_dict(floor.as_dict()) == floor


def test_concat_documented_kind_error_matches_the_core():
    root = Path(__file__).resolve().parents[2]
    text = (root / "docs/reference/contracts.md").read_text(encoding="utf-8")
    clause = text.split("- `concat(*others)`", 1)[1].split("- `diff(candidate)`", 1)[0]
    # The compatibility clause must include both config and kind before its error.
    compatibility = clause.split("`Incompatible`", 1)[0]
    assert "id kind" in compatibility
    other = Encoding(["1"], np.zeros((1, 2), dtype=np.uint8), CodecConfig.quant(4, 4))
    with pytest.raises(Incompatible):
        sample().concat(other)


def test_native_error_construction_has_no_loader_or_build_dependency(monkeypatch):
    from semq import Native, _ffi, build

    def forbidden():
        raise AssertionError("error construction queried runtime state")

    monkeypatch.setattr(build, "build_info_safe", forbidden)
    monkeypatch.setattr(_ffi, "lib", forbidden)
    err = Native("failure", operation="test", sdk_version="sdk", core_version="core", build_id="build")
    assert err.build_id == "build" and err.core_version == "core"


@pytest.mark.parametrize("operation", ["fsync", "replace"])
def test_failed_path_publication_preserves_destination(tmp_path, monkeypatch, operation):
    from semq import encoding
    target = tmp_path / "reference.semq"
    reference = sample()
    reference.save(target)
    before = target.read_bytes()

    def fail(*args):
        raise OSError("publication interrupted")

    monkeypatch.setattr(encoding.os, operation, fail)
    with pytest.raises(OSError, match="publication interrupted"):
        reference.save(target)
    assert target.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == [target.name]


def test_floor_save_obeys_text_stream_progress():
    floor = Floor.measure([sample().diff(sample())])

    class Partial:
        data = ""
        def write(self, text):
            self.data += text[:3]
            return min(len(text), 3)

    sink = Partial()
    floor.save(sink)
    assert Floor.load(sink.data.encode()) == floor

    class Blocked:
        def write(self, text):
            return None

    with pytest.raises(BlockingIOError):
        floor.save(Blocked())
