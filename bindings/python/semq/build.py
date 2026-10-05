# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""BuildInfo: the identity of this build."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import _ffi


@dataclass(frozen=True)
class BuildInfo:
    """Versions and kernel selection of the loaded core.

    ``backend`` maps each operator name to the kernel the core runs for it
    on this host. ``build_id`` identifies a reproducible build recipe; it is
    not a provenance proof.
    """

    sdk_version: str
    core_version: str
    backend: dict[str, str]
    build_id: str

    def as_dict(self) -> dict[str, Any]:
        """The four fields as plain JSON-ready values, as ``semq version --json`` prints them."""
        return {
            "sdk_version": self.sdk_version,
            "core_version": self.core_version,
            "backend": dict(self.backend),
            "build_id": self.build_id,
        }


def _sdk_version() -> str:
    try:
        from importlib.metadata import version

        return version("semq")
    except Exception:
        return "0.0.0+unknown"


def build_info() -> BuildInfo:
    """Query the loaded core."""
    from . import _ffi

    lib = _ffi.lib()
    return BuildInfo(
        sdk_version=_sdk_version(),
        core_version=_ffi.string(lib.semq_core_version()),
        backend={
            "orbit": _ffi.string(lib.semq_backend_name(0)),
            "phase": _ffi.string(lib.semq_backend_name(1)),
            "quant": _ffi.string(lib.semq_backend_name(2)),
        },
        build_id=_ffi.string(lib.semq_build_id()),
    )


def build_info_safe() -> BuildInfo:
    """Like :func:`build_info`, but never raises and never loads the library.

    Used while reporting errors: when the library is not loaded (including
    while a load is failing under the loader's lock) the core fields read
    ``unavailable`` instead of triggering a second load.
    """
    if _ffi.loaded() is None:
        return BuildInfo(_sdk_version(), "unavailable", {}, "unavailable")
    try:
        return build_info()
    except Exception:
        return BuildInfo(_sdk_version(), "unavailable", {}, "unavailable")
