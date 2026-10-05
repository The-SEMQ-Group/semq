# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
"""Publish the release history page from CHANGELOG.md in the MkDocs build.

CHANGELOG.md is the only record of versions: tools/version.py adds a section
for every release and release candidate, and the release workflow refuses a
tag without one. This hook renders those sections as a virtual
``releases.md`` page, with a summary table, and leaves out the unreleased
section.
"""

from __future__ import annotations

import re
from pathlib import Path

REPOSITORY = "https://github.com/The-SEMQ-Group/semq"
HEADING = re.compile(r"^## \[(?P<version>[^\]]+)\](?: - (?P<date>\d{4}-\d{2}-\d{2}))?\s*$", re.MULTILINE)
LINK = re.compile(r"\]\((?!https?://|#|mailto:)(?P<path>[^)\s]+)\)")

INTRO = """# Release history

Every published version of the SDK, newest first. A release candidate
(`X.Y.Z-rc.N`) is a pre-release: no installer picks it unless you ask for it.

| Language | Install a release | Install a release candidate |
| --- | --- | --- |
| Python | `pip install semq==X.Y.Z` | `pip install semq==X.Y.ZrcN` |
| Rust | `cargo add semq@X.Y.Z` | `cargo add semq@=X.Y.Z-rc.N` |
| Go | `go get github.com/The-SEMQ-Group/semq/bindings/go@vX.Y.Z` | `go get github.com/The-SEMQ-Group/semq/bindings/go@vX.Y.Z-rc.N` |
| TypeScript | `npm install @semq/sdk@X.Y.Z` | `npm install @semq/sdk@next` |

See [Compatibility and migration](compatibility.md) for what each version
guarantees.
"""


def _rewrite_link(match: re.Match[str]) -> str:
    path = match["path"]
    if path.startswith("docs/"):
        return f"]({path.removeprefix('docs/')})"
    return f"]({REPOSITORY}/blob/main/{path})"


def render(changelog: str) -> str:
    """Return the release history page for the text of CHANGELOG.md."""
    sections = list(HEADING.finditer(changelog))
    released = [s for s in sections if s["version"] != "Unreleased"]
    if released:
        rows = "\n".join(
            f"| [{s['version']}](#{_anchor(s['version'], s['date'])}) | {s['date'] or ''} | "
            f"{'Release candidate' if '-rc.' in s['version'] else 'Release'} |"
            for s in released
        )
        table = f"| Version | Date | Type |\n| --- | --- | --- |\n{rows}\n"
        start = released[0].start()
        body = LINK.sub(_rewrite_link, changelog[start:]).rstrip() + "\n"
    else:
        table = "No version has been published yet.\n"
        body = ""
    return f"{INTRO}\n{table}\n{body}"


def _anchor(version: str, date: str | None) -> str:
    # Mirrors the toc extension's default slug for "[1.0.0-rc.1] - 2026-10-10":
    # drop punctuation, then collapse runs of spaces and hyphens.
    text = f"{version} - {date}" if date else version
    return re.sub(r"[-\s]+", "-", re.sub(r"[^\w\s-]", "", text).strip().lower())


def on_files(files, config):
    from mkdocs.structure.files import File

    root = Path(config.config_file_path).parent
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    files.append(File.generated(config, "releases.md", content=render(changelog)))
    return files
