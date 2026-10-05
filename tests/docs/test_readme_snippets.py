# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Execute the ``python`` code blocks in the top-level Markdown files.

The README is the first thing a user copies from, and nothing checked it
until now; the earlier snippet suite scanned ``docs/`` only.

Rules:

* Blocks in one file run in order and share a namespace, so a file reads
  top to bottom like a script.
* Each file runs in its own temporary working directory. A snippet may
  write ``corpus.semq`` or any other file without cleanup.
* A block with ``<!-- docs-test: skip -->`` in the three lines above it
  does not run. Use the marker for fragments that name undefined
  placeholders, and for snippets that need the network.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Top-level pages a user reads before anything else.
_PAGES = ("README.md", "CONTRIBUTING.md", "SECURITY.md")

_SKIP_MARK = "<!-- docs-test: skip -->"

_FENCE_RE = re.compile(r"^```python\s*$")
_FENCE_END_RE = re.compile(r"^```\s*$")


def _python_blocks(page: Path) -> list[tuple[int, str]]:
    """Return (starting_line, source) for each runnable python fence."""
    lines = page.read_text(encoding="utf-8").splitlines()
    blocks: list[tuple[int, str]] = []
    i = 0
    while i < len(lines):
        if _FENCE_RE.match(lines[i]):
            skip = any(_SKIP_MARK in lines[j] for j in range(max(0, i - 3), i))
            start = i + 1
            j = start
            while j < len(lines) and not _FENCE_END_RE.match(lines[j]):
                j += 1
            if not skip:
                blocks.append((start + 1, "\n".join(lines[start:j])))
            i = j + 1
        else:
            i += 1
    return blocks


def _runnable_pages() -> list[Path]:
    pages = []
    for name in _PAGES:
        page = REPO_ROOT / name
        if page.is_file() and _python_blocks(page):
            pages.append(page)
    return pages


@pytest.mark.parametrize(
    "page",
    _runnable_pages(),
    ids=lambda p: p.name,
)
def test_readme_snippets_execute(
    page: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    namespace: dict[str, object] = {"__name__": "__docs_snippet__"}
    for lineno, source in _python_blocks(page):
        code = compile(source, f"{page.name}:{lineno}", "exec")
        try:
            exec(code, namespace)  # noqa: S102 — executing our own docs is the point
        except Exception as exc:  # pragma: no cover — failure reporting
            pytest.fail(
                f"snippet at {page.name}:{lineno} raised "
                f"{type(exc).__name__}: {exc}"
            )
