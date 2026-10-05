"""Catch broken repository links and Markdown without a discoverable entry point.

MkDocs validates the published site's navigation and anchors. These checks also
cover contributor instructions, adjacent READMEs, and architectural decisions.
They inspect file destinations, not external website availability or anchors.
"""

from __future__ import annotations

import re
import subprocess
from collections import deque
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_INLINE_LINK = re.compile(r"\]\(\s*(?:<([^>]+)>|([^\s)]+))")
_REFERENCE = re.compile(r"^\s*\[([^\]]+)\]:\s*(?:<([^>]+)>|(\S+))", re.MULTILINE)
_REFERENCE_USE = re.compile(r"\[([^\]\n]+)\](?:\[([^\]\n]*)\])?(?!\()")
_HTML_LINK = re.compile(r"(?:href|src)=[\"']([^\"']+)[\"']")
_NAV_PAGE = re.compile(r"^\s*-\s+(?:[^:]+:\s*)?([\w./-]+\.md)\s*$")
_SOURCE_URL = re.compile(r"^/(?:blob|tree)/main/(.+)$")


def _markdown_files() -> set[Path]:
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            "*.md",
            "*.mdx",
            "*.markdown",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return {
        ROOT / name.decode()
        for name in result.stdout.split(b"\0")
        if name and (ROOT / name.decode()).is_file()
    }


def _prose(page: Path) -> str:
    text = re.sub(r"<!--.*?-->", "", page.read_text(encoding="utf-8"), flags=re.DOTALL)
    lines = []
    fence = None
    for line in text.splitlines():
        match = _FENCE.match(line)
        if match:
            marker = match[1]
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
        elif fence is None:
            lines.append(line)
    return "\n".join(lines)


def _links(page: Path, *, include_definitions: bool = False) -> list[str]:
    prose = _prose(page)
    definitions = {}
    for label, angle, bare in _REFERENCE.findall(prose):
        key = " ".join(label.split()).casefold()
        definitions.setdefault(key, angle or bare)
    prose = _REFERENCE.sub("", prose)
    links = [angle or bare for angle, bare in _INLINE_LINK.findall(prose)]
    links += _HTML_LINK.findall(prose)
    if include_definitions:
        links += list(definitions.values())
    else:
        # A definition by itself renders no link. Only used full, collapsed,
        # or shortcut references make another document discoverable.
        prose = re.sub(r"(`+).*?\1", "", prose, flags=re.DOTALL)
        for label, reference in _REFERENCE_USE.findall(prose):
            key = " ".join((reference or label).split()).casefold()
            if key in definitions:
                links.append(definitions[key])
    return links


def _destination(page: Path, link: str) -> Path | None:
    url = urlsplit(link)
    if url.netloc == "github.com" and url.path.startswith("/The-SEMQ-Group/semq/"):
        match = _SOURCE_URL.match(url.path.removeprefix("/The-SEMQ-Group/semq"))
        return (ROOT / unquote(match[1])).resolve() if match else None
    if url.scheme or url.netloc or not url.path:
        return None
    target = (page.parent / unquote(url.path)).resolve()
    if target == ROOT / "docs/reference/typescript-api/index.html":
        # tools/docs_api.py registers this virtual page at build time. MkDocs
        # strict link validation checks it against the generated file list.
        return None
    if url.path.endswith("/") and page.is_relative_to(ROOT / "docs"):
        # Raw HTML on a site page links to published routes, which MkDocs does
        # not rewrite: "quickstart/" is quickstart.md or quickstart/index.md.
        for source in (target.with_suffix(".md"), target / "index.md"):
            if source.exists():
                return source
    return target


def _navigation_pages() -> set[Path]:
    # The nav uses ordinary relative .md scalars. Reading just that section
    # avoids a YAML dependency (mkdocs.yml also contains plugin-specific tags).
    pages = set()
    in_nav = False
    for line in (ROOT / "mkdocs.yml").read_text(encoding="utf-8").splitlines():
        if line == "nav:":
            in_nav = True
        elif in_nav and line and not line[0].isspace() and not line.startswith("#"):
            break
        elif in_nav and (match := _NAV_PAGE.match(line)):
            pages.add(ROOT / "docs" / match[1])
    assert pages, "No Markdown entry points found in the MkDocs navigation"
    return pages


def test_repository_markdown_links_exist() -> None:
    failures = []
    for page in sorted(_markdown_files()):
        for link in _links(page, include_definitions=True):
            target = _destination(page, link)
            if target is not None and (
                not target.is_relative_to(ROOT) or not target.exists()
            ):
                failures.append(f"{page.relative_to(ROOT)}: {link}")
    assert not failures, "Broken repository links:\n" + "\n".join(failures)


def test_repository_markdown_is_reachable() -> None:
    pages = _markdown_files()
    pending = deque({ROOT / "README.md"} | _navigation_pages())
    seen = set()
    while pending:
        page = pending.popleft()
        if page in seen or page not in pages:
            continue
        seen.add(page)
        for link in _links(page):
            target = _destination(page, link)
            if target is not None and target.is_dir():
                target = target / "README.md"
            if target in pages and target not in seen:
                pending.append(target)
    orphans = sorted(str(page.relative_to(ROOT)) for page in pages - seen)
    assert not orphans, (
        "Markdown has no route from README.md or the MkDocs navigation. "
        "Link useful material from the appropriate entry point, or remove "
        "temporary/obsolete documents:\n" + "\n".join(orphans)
    )
