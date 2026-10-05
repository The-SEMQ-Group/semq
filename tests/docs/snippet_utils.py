# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
"""Read executable Markdown fences, including indented MkDocs language tabs."""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_FENCE = re.compile(r"^(?P<indent> *)(?P<fence>`{3,}|~{3,})(?P<language>[\w+-]*)\s*$")
_EXCLUDED = {"RELEASING.md"}


@dataclass(frozen=True)
class Snippet:
    page: Path
    line: int
    language: str
    source: str

    @property
    def label(self) -> str:
        return f"{self.page.relative_to(REPO_ROOT)}:{self.line}"


def site_pages() -> list[Path]:
    return [
        page
        for page in sorted((REPO_ROOT / "docs").rglob("*.md"))
        if not set(page.relative_to(REPO_ROOT / "docs").parts) & _EXCLUDED
    ]


def snippets(page: Path, language: str) -> list[Snippet]:
    """Return complete runnable fences; explicit skip markers opt out fragments."""
    lines = page.read_text(encoding="utf-8").splitlines()
    result = []
    i = 0
    while i < len(lines):
        match = _FENCE.match(lines[i])
        if not match:
            i += 1
            continue
        start = i + 1
        marker = match["fence"]
        end = start
        while end < len(lines):
            if lines[end].strip() == marker:
                break
            end += 1
        skip = any(
            "<!-- docs-test: skip -->" in line for line in lines[max(0, i - 3) : i]
        )
        actual = {"ts": "typescript", "py": "python"}.get(
            match["language"], match["language"]
        )
        if actual == language and not skip:
            if end == len(lines):
                raise ValueError(f"Unclosed code fence at {page}:{i + 1}")
            result.append(
                Snippet(
                    page,
                    start + 1,
                    actual,
                    textwrap.dedent("\n".join(lines[start:end])),
                )
            )
        i = end + 1
    return result


def all_snippets(language: str) -> list[Snippet]:
    return [snippet for page in site_pages() for snippet in snippets(page, language)]
