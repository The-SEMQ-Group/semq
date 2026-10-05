# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""The six error types of the SEMQ SDK.

Each core status maps to exactly one class. Out-of-memory raises
``MemoryError`` and file I/O raises ``OSError``, as anywhere in Python.
"""

from __future__ import annotations


class SemqError(Exception):
    """Common base of the six SEMQ errors, for callers who want one ``except``."""


class InvalidInput(SemqError):
    """An argument violates its contract.

    ``row`` is the input row index when a row is at fault; ``field`` is the
    coordinate, column, pair index or config field when one applies.
    """

    def __init__(self, message: str, *, row: int | None = None, field: int | None = None) -> None:
        super().__init__(message)
        self.row = row
        self.field = field


class Incompatible(SemqError):
    """Two states differ in config or id kind."""

    def __init__(self, message: str, *, field: int | None = None) -> None:
        super().__init__(message)
        self.field = field


class FormatError(SemqError):
    """A file image is not a valid version 2 image.

    ``section`` is the file section that failed; ``row`` the row index when
    a row is not canonical.
    """

    def __init__(self, message: str, *, row: int | None = None, section: int | None = None) -> None:
        super().__init__(message)
        self.row = row
        self.section = section


class IntegrityError(SemqError):
    """A file image's digest does not match its footer.

    ``which`` names the check that failed: ``"content"`` or ``"state"``.
    """

    def __init__(self, message: str, *, which: str | None = None) -> None:
        super().__init__(message)
        self.which = which


class Unsupported(SemqError):
    """The operation, or the floating-point environment, is not supported."""

    def __init__(self, message: str, *, operation: str | None = None) -> None:
        super().__init__(message)
        self.operation = operation


class Native(SemqError):
    """A defect in the core or the binding, or the library could not be loaded.

    Carries what a bug report needs and never input data.
    """

    def __init__(
        self,
        message: str,
        *,
        operation: str | None = None,
        status: int | None = None,
        row: int | None = None,
        field: int | None = None,
        sdk_version: str = "unavailable",
        core_version: str = "unavailable",
        build_id: str = "unavailable",
    ) -> None:
        super().__init__(
            f"{message} [operation={operation} status={status} sdk={sdk_version} "
            f"core={core_version} build={build_id}]"
        )
        self.operation = operation
        self.status = status
        self.row = row
        self.field = field
        self.sdk_version = sdk_version
        self.core_version = core_version
        self.build_id = build_id
