#!/usr/bin/env python3
# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
"""Set the SDK version everywhere it is declared, and check a release tag.

The SDK has one version, written in SemVer form in VERSION: ``X.Y.Z`` for a
release and ``X.Y.Z-rc.N`` for a release candidate. The same string is the
version of the Rust crates and the npm package, and the Go module tag. The
Python package uses its PEP 440 spelling (``X.Y.ZrcN``).

    python tools/version.py set 1.0.0-rc.1   # update every file and CHANGELOG.md
    python tools/version.py check v1.0.0-rc.1  # validate a tag before publishing
    python tools/version.py notes 1.0.0-rc.1   # print that version's release notes
    python tools/version.py current            # the declared version, for rehearsals
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
NUMBER = r"(?:0|[1-9][0-9]*)"
VERSION = re.compile(
    rf"(?P<base>{NUMBER}\.{NUMBER}\.{NUMBER})(?:-rc\.(?P<rc>[1-9][0-9]*))?"
)
REPOSITORY = "https://github.com/The-SEMQ-Group/semq"
NPM_NAME = "@semq/sdk"
GO_BUILD_HEADER = "bindings/go/internal/core/semq_build.h"


class Release(NamedTuple):
    version: str
    base: str
    rc: int | None

    @property
    def prerelease(self) -> bool:
        return self.rc is not None

    @property
    def python(self) -> str:
        return self.base if self.rc is None else f"{self.base}rc{self.rc}"

    @property
    def npm_tag(self) -> str:
        return "latest" if self.rc is None else "next"


def parse(version: str) -> Release:
    match = VERSION.fullmatch(version)
    if match is None:
        raise ValueError(f"{version!r} is not X.Y.Z or X.Y.Z-rc.N")
    if int(match["base"].split(".", 1)[0]) >= 2:
        raise ValueError("the Go module path needs a /v2 suffix before a major 2 release")
    rc = match["rc"]
    return Release(version, match["base"], None if rc is None else int(rc))


def _read(root: Path, path: str) -> str:
    return (root / path).read_text(encoding="utf-8")


def _write(root: Path, path: str, text: str) -> None:
    (root / path).write_text(text, encoding="utf-8")


def _replace_once(text: str, pattern: str, replacement: str, path: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise ValueError(f"{path}: expected one match for {pattern!r}")
    return updated


def declared(root: Path = ROOT) -> dict[str, str]:
    """Return the version each source file declares."""
    package = json.loads(_read(root, "bindings/ts/package.json"))
    lock = json.loads(_read(root, "bindings/ts/package-lock.json"))
    rust = tomllib.loads(_read(root, "bindings/rust/semq/Cargo.toml"))
    sys_crate = tomllib.loads(_read(root, "bindings/rust/semq-sys/Cargo.toml"))
    ts = re.search(r'export const SDK_VERSION = "([^"]*)";', _read(root, "bindings/ts/src/version.ts"))
    go = re.search(r'^#define SEMQ_CORE_VERSION "([^"]*)"$', _read(root, GO_BUILD_HEADER), flags=re.MULTILINE)
    return {
        "VERSION": _read(root, "VERSION").strip(),
        "semq crate": rust["package"]["version"],
        "semq-sys crate": sys_crate["package"]["version"],
        "semq-sys dependency": rust["dependencies"]["semq-sys"]["version"].removeprefix("="),
        "npm package": package["version"],
        "npm lockfile": lock["version"],
        "npm lockfile root": lock["packages"][""]["version"],
        "TypeScript SDK_VERSION": ts[1] if ts else "",
        "Go core copy": go[1] if go else "",
    }


def _changelog_versions(text: str) -> list[str]:
    return re.findall(r"^## \[([^\]]+)\]", text, flags=re.MULTILINE)


def _update_changelog(text: str, release: Release, today: str) -> str:
    match = re.search(r"^## \[Unreleased\]\n(?P<body>.*?)(?=^## \[|^\[Unreleased\]:)", text,
                      flags=re.MULTILINE | re.DOTALL)
    if match is None:
        raise ValueError("CHANGELOG.md: no [Unreleased] section")
    if release.version in _changelog_versions(text):
        raise ValueError(f"CHANGELOG.md already has a section for {release.version}")
    body = match["body"].strip()
    if not body:
        previous = [v for v in _changelog_versions(text) if v != "Unreleased"]
        if previous and previous[0].startswith(f"{release.base}-rc."):
            body = f"No changes since {previous[0]}."
        else:
            raise ValueError("CHANGELOG.md: the [Unreleased] section is empty")
    section = f"## [Unreleased]\n\n## [{release.version}] - {today}\n\n{body}\n\n"
    text = text[: match.start()] + section + text[match.end():]
    link = f"[{release.version}]: {REPOSITORY}/releases/tag/v{release.version}"
    return _replace_once(text, r"^(\[Unreleased\]: .*)$", rf"\1\n{link}", "CHANGELOG.md")


def set_version(version: str, root: Path = ROOT, today: str | None = None) -> Release:
    """Write ``version`` into every declaration and open its CHANGELOG section."""
    release = parse(version)
    today = today or datetime.date.today().isoformat()
    edits: dict[str, str] = {}

    edits["VERSION"] = f"{release.version}\n"

    for path in ("bindings/rust/semq/Cargo.toml", "bindings/rust/semq-sys/Cargo.toml"):
        edits[path] = _replace_once(_read(root, path), r'^version = "[^"]*"$',
                                    f'version = "{release.version}"', path)
    edits["bindings/rust/semq/Cargo.toml"] = _replace_once(
        edits["bindings/rust/semq/Cargo.toml"],
        r'^(semq-sys = \{ path = "\.\./semq-sys", version = )"[^"]*"( \})$',
        rf'\1"={release.version}"\2', "bindings/rust/semq/Cargo.toml")

    path = "bindings/ts/package.json"
    edits[path] = _replace_once(_read(root, path), r'^  "version": "[^"]*",$',
                                f'  "version": "{release.version}",', path)
    path = "bindings/ts/package-lock.json"
    lock = _read(root, path)
    lock = _replace_once(lock, r'^  "version": "[^"]*",$', f'  "version": "{release.version}",', path)
    lock = _replace_once(lock, r'^(    "": \{\n      "name": "@semq/sdk",\n      "version": )"[^"]*"',
                         rf'\1"{release.version}"', path)
    edits[path] = lock
    path = "bindings/ts/src/version.ts"
    edits[path] = _replace_once(_read(root, path), r'^export const SDK_VERSION = "[^"]*";$',
                                f'export const SDK_VERSION = "{release.version}";', path)

    # The Go module's copy of the core (tools/gen_go_core.py) states the core version.
    edits[GO_BUILD_HEADER] = _replace_once(_read(root, GO_BUILD_HEADER), r'^#define SEMQ_CORE_VERSION "[^"]*"$',
                                           f'#define SEMQ_CORE_VERSION "{release.version}"', GO_BUILD_HEADER)

    edits["CHANGELOG.md"] = _update_changelog(_read(root, "CHANGELOG.md"), release, today)

    # Validate everything before writing anything.
    for path, text in edits.items():
        _write(root, path, text)
    return release


def notes(version: str, root: Path = ROOT) -> str:
    """Return the CHANGELOG.md body of ``version``."""
    text = _read(root, "CHANGELOG.md")
    match = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(?P<body>.*?)(?=^## \[|^\[[^\]]+\]: )",
                      text, flags=re.MULTILINE | re.DOTALL)
    if match is None:
        raise ValueError(f"CHANGELOG.md has no section for {version}")
    return match["body"].strip() + "\n"


def check(tag: str, root: Path = ROOT) -> Release:
    """Validate a release tag against every declaration and CHANGELOG.md."""
    if not tag.startswith("v"):
        raise ValueError(f"release tag {tag!r} must be vX.Y.Z or vX.Y.Z-rc.N")
    release = parse(tag[1:])
    for name, actual in declared(root).items():
        if actual != release.version:
            raise ValueError(f"{name} declares {actual!r}; tag {tag} requires {release.version!r}")
    if release.version not in _changelog_versions(_read(root, "CHANGELOG.md")):
        raise ValueError(f"CHANGELOG.md has no section for {release.version}")
    package = json.loads(_read(root, "bindings/ts/package.json"))
    if package.get("name") != NPM_NAME or package.get("private", False):
        raise ValueError(f"the npm package must be public and named {NPM_NAME}")
    if package.get("repository", {}).get("url") != f"git+{REPOSITORY}.git":
        raise ValueError(f"the npm repository URL must be git+{REPOSITORY}.git")
    return release


def current(root: Path = ROOT) -> Release:
    """Return the version every file declares, without a tag or changelog check."""
    versions = set(declared(root).values())
    if len(versions) != 1:
        raise ValueError(f"the files declare different versions: {declared(root)}")
    return parse(versions.pop())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    set_parser = commands.add_parser("set", help="write a new version into every file")
    set_parser.add_argument("version", help="X.Y.Z or X.Y.Z-rc.N")
    check_parser = commands.add_parser("check", help="validate a release tag")
    check_parser.add_argument("tag", help="vX.Y.Z or vX.Y.Z-rc.N")
    check_parser.add_argument("--github-output", type=Path,
                              help="append version outputs for GitHub Actions to this file")
    notes_parser = commands.add_parser("notes", help="print the release notes of a version")
    notes_parser.add_argument("version", help="X.Y.Z or X.Y.Z-rc.N")
    current_parser = commands.add_parser("current", help="print the declared version's outputs")
    current_parser.add_argument("--github-output", type=Path,
                                help="append version outputs for GitHub Actions to this file")
    args = parser.parse_args()
    try:
        if args.command == "notes":
            print(notes(parse(args.version).version), end="")
            return 0
        if args.command == "set":
            release = set_version(args.version)
            print(f"Set version {release.version}. Review the diff, then commit it before tagging.")
            return 0
        release = current() if args.command == "current" else check(args.tag)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    outputs = {
        "version": release.version,
        "python_version": release.python,
        "prerelease": str(release.prerelease).lower(),
        "npm_tag": release.npm_tag,
    }
    lines = "".join(f"{key}={value}\n" for key, value in outputs.items())
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as handle:
            handle.write(lines)
    print(lines, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
