# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""SEMQ: deterministic symbolic encoding of float32 vectors.

Five types and one service, backed by a C core that owns every rule:

* :class:`CodecConfig`: the rule (``quant``, ``phase`` or ``orbit``).
* :class:`Codec`: encodes unit-norm float32 vectors into an :class:`Encoding`.
* :class:`Encoding`: ids, canonical rows, a manifest and two identities;
  ``save``/``load``, ``concat`` and ``diff``.
* :class:`Diff`: added, removed and changed ids with hamming distances.
* :class:`Floor`: the envelope of variation observed in null diffs.
* :class:`BuildInfo` from :func:`build_info`.

Errors: :class:`InvalidInput`, :class:`Incompatible`, :class:`FormatError`,
:class:`IntegrityError`, :class:`Unsupported`, :class:`Native`.
"""

from .build import BuildInfo, build_info
from .codec import Codec
from .config import CodecConfig, Operator
from .diff import Diff, Verdict
from .encoding import Encoding
from .errors import (
    FormatError,
    Incompatible,
    IntegrityError,
    InvalidInput,
    Native,
    Unsupported,
)
from .floor import Floor

try:
    from importlib.metadata import version as _version

    __version__ = _version("semq")
    del _version
except Exception:  # pragma: no cover
    __version__ = "0.0.0+unknown"

__all__ = [
    "BuildInfo",
    "Codec",
    "CodecConfig",
    "Diff",
    "Encoding",
    "Floor",
    "FormatError",
    "Incompatible",
    "IntegrityError",
    "InvalidInput",
    "Native",
    "Operator",
    "Unsupported",
    "Verdict",
    "__version__",
    "build_info",
]
