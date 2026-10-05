# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
"""Every tracked source file states its copyright and license.

The LICENSE.md terms govern the whole repository, but a file copied out of it
carries only its own text, so each one names the license. Generated files say
so too; the Go module's copy of the core starts with a generated-code line.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ("*.c", "*.h", "*.cpp", "*.py", "*.rs", "*.go", "*.ts", "*.mjs", "*.js", "*.css", "*.sh")
# Not ours: the JavaScript glue Emscripten generates.
EXEMPT = ("bindings/ts/src/wasm/",)
NOTICE = "Licensed under the PolyForm Noncommercial License 1.0.0."


def test_every_source_file_names_the_license() -> None:
    tracked = subprocess.check_output(["git", "ls-files", "-z", "--", *SOURCES], cwd=ROOT, text=True)
    missing = []
    for name in filter(None, tracked.split("\0")):
        if name.startswith(EXEMPT):
            continue
        head = (ROOT / name).read_text(encoding="utf-8", errors="replace").splitlines()[:12]
        if not any(NOTICE in line for line in head):
            missing.append(name)
    assert not missing, "files without the license header: " + ", ".join(missing)


def test_the_go_module_carries_the_license_terms() -> None:
    # A Go module contains only bindings/go, so its own copies are what users get.
    for name in ("LICENSE.md", "NOTICE"):
        assert (ROOT / "bindings/go" / name).read_bytes() == (ROOT / name).read_bytes(), name
