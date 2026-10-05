# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
"""Compile both supported and forbidden platform modes; no running core needed."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_compiler_rejects_unsupported_platform_modes(tmp_path):
    msvc = os.name == "nt"
    cc = shutil.which("cl" if msvc else os.environ.get("CC", "cc"))
    if cc is None:
        pytest.skip("C compiler is not available")
    source = tmp_path / "premises.c"
    source.write_text('#include "semq_platform.h"\nint main(void) { return 0; }\n', encoding="utf-8")
    if msvc:
        command = [cc, "/nologo", "/std:c11", "/c", f"/I{ROOT / 'src'}", f"/I{ROOT / 'include'}", str(source), f"/Fo{tmp_path / 'probe.obj'}"]
        bad_modes = [["/fp:fast"]]
    else:
        command = [cc, "-std=c11", "-fsyntax-only", f"-I{ROOT / 'src'}", f"-I{ROOT / 'include'}", str(source)]
        bad_modes = [["-ffast-math"], ["-fshort-enums"], ["-D__STDC_NO_ATOMICS__=1"], ["-U__BYTE_ORDER__", "-D__BYTE_ORDER__=__ORDER_BIG_ENDIAN__"]]
    good = subprocess.run(command, capture_output=True, text=True)
    assert good.returncode == 0, good.stdout + good.stderr
    for mode in bad_modes:
        bad = subprocess.run(command + mode, capture_output=True, text=True)
        assert bad.returncode != 0, f"unsupported mode admitted: {mode}"
        assert "SEMQ" in bad.stdout + bad.stderr
