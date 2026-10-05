# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
"""Stream protocols and complete writes, independent of native resources."""
from __future__ import annotations

import errno
from typing import Protocol


class BinaryReader(Protocol):
    def read(self, size: int = -1, /) -> bytes: ...


class BinaryWriter(Protocol):
    def write(self, data: memoryview, /) -> int | None: ...


class TextOrBinaryReader(Protocol):
    def read(self, size: int = -1, /) -> str | bytes: ...


class TextWriter(Protocol):
    def write(self, data: str, /) -> int | None: ...


def write_binary(f: BinaryWriter, data: memoryview) -> None:
    """Write every byte, or propagate failure/no progress from the stream."""
    while len(data):
        written = f.write(data)
        if written is None or written == 0:
            raise BlockingIOError(errno.EAGAIN, "save: the stream accepted no bytes")
        if not isinstance(written, int) or written < 0 or written > len(data):
            raise OSError("save: the stream returned an invalid byte count")
        data = data[written:]


def write_text(f: TextWriter, data: str) -> None:
    """TextIO reports characters accepted, with the same progress requirement."""
    while data:
        written = f.write(data)
        if written is None or written == 0:
            raise BlockingIOError(errno.EAGAIN, "save: the stream accepted no characters")
        if not isinstance(written, int) or written < 0 or written > len(data):
            raise OSError("save: the stream returned an invalid character count")
        data = data[written:]
