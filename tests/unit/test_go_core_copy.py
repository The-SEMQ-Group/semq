# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
"""The Go module's copy of the C core matches include/ and src/.

`go get` delivers only the Go module, so tools/gen_go_core.py copies the core
into bindings/go/internal/core. A change to the core that is not followed by
regenerating the copy would ship the old core to Go users.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_go_core_copy_is_up_to_date() -> None:
    result = subprocess.run([sys.executable, str(ROOT / "tools/gen_go_core.py"), "--check"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
