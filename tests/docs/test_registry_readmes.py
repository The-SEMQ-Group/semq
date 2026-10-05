# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
"""Keep the READMEs that package registries display usable outside the repository.

PyPI shows README.md, npm shows bindings/ts/README.md and crates.io shows
bindings/rust/semq/README.md. A registry page has no checkout to resolve a
relative link against, so every link in those files must be absolute.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_READMES = ("README.md", "bindings/ts/README.md", "bindings/rust/semq/README.md")
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_TARGET = re.compile(r"\]\(\s*<?([^)\s>]+)|(?:href|src)=[\"']([^\"']+)[\"']")


def _targets(text: str) -> list[str]:
    targets, fenced = [], False
    for line in text.splitlines():
        if _FENCE.match(line):
            fenced = not fenced
        elif not fenced:
            targets += [a or b for a, b in _TARGET.findall(line)]
    return targets


@pytest.mark.parametrize("name", REGISTRY_READMES)
def test_registry_readme_links_are_absolute(name: str) -> None:
    relative = [
        target
        for target in _targets((ROOT / name).read_text(encoding="utf-8"))
        if not re.match(r"(https?:|mailto:|#)", target)
    ]
    assert not relative, f"{name} has links a registry page cannot resolve: {relative}"


def test_manifests_declare_the_registry_readmes() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["readme"] == "README.md"
    crate = tomllib.loads((ROOT / "bindings/rust/semq/Cargo.toml").read_text(encoding="utf-8"))
    assert crate["package"]["readme"] == "README.md"
    assert "README.md" in crate["package"]["include"]
