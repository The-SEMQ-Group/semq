# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
"""Version declarations, the release tag check and the release history page."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import docs_releases  # noqa: E402
import gen_go_core  # noqa: E402
import version  # noqa: E402

FILES = (
    "VERSION",
    "CHANGELOG.md",
    "bindings/rust/semq/Cargo.toml",
    "bindings/rust/semq-sys/Cargo.toml",
    "bindings/ts/package.json",
    "bindings/ts/package-lock.json",
    "bindings/ts/src/version.ts",
    "bindings/go/internal/core/semq_build.h",
)


# The repository's CHANGELOG changes with every release, so the tests use the
# real preamble (the links the release history page rewrites) followed by
# their own unreleased notes and no published version.
UNRELEASED = """## [Unreleased]

First public release.

### Added

- A codec.

[Unreleased]: https://github.com/The-SEMQ-Group/semq/commits/main
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    for name in FILES:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, tmp_path / name)
    preamble = (ROOT / "CHANGELOG.md").read_text().split("## [Unreleased]", 1)[0]
    (tmp_path / "CHANGELOG.md").write_text(preamble + UNRELEASED)
    return tmp_path


def test_every_declaration_names_the_same_version() -> None:
    declared = version.declared()
    assert len(set(declared.values())) == 1, declared


def test_set_writes_every_declaration_and_opens_a_changelog_section(repo: Path) -> None:
    version.set_version("1.0.0-rc.1", repo, today="2026-10-10")

    assert set(version.declared(repo).values()) == {"1.0.0-rc.1"}
    cargo = (repo / "bindings/rust/semq/Cargo.toml").read_text()
    assert 'semq-sys = { path = "../semq-sys", version = "=1.0.0-rc.1" }' in cargo
    changelog = (repo / "CHANGELOG.md").read_text()
    assert "## [Unreleased]\n\n## [1.0.0-rc.1] - 2026-10-10\n\nFirst public release." in changelog
    assert "[1.0.0-rc.1]: https://github.com/The-SEMQ-Group/semq/releases/tag/v1.0.0-rc.1" in changelog
    # The Go copy of the core stays what tools/gen_go_core.py would write.
    go_header = (repo / "bindings/go/internal/core/semq_build.h").read_text()
    assert go_header == gen_go_core.build_header("1.0.0-rc.1")


def test_check_reports_the_registry_spellings(repo: Path) -> None:
    version.set_version("1.0.0-rc.1", repo, today="2026-10-10")
    candidate = version.check("v1.0.0-rc.1", repo)
    assert (candidate.python, candidate.npm_tag, candidate.prerelease) == ("1.0.0rc1", "next", True)

    version.set_version("1.0.0", repo, today="2026-10-20")
    release = version.check("v1.0.0", repo)
    assert (release.python, release.npm_tag, release.prerelease) == ("1.0.0", "latest", False)


def test_a_release_after_its_candidate_needs_no_new_notes(repo: Path) -> None:
    version.set_version("1.0.0-rc.1", repo, today="2026-10-10")
    version.set_version("1.0.0", repo, today="2026-10-20")
    assert version.notes("1.0.0", repo) == "No changes since 1.0.0-rc.1.\n"
    assert version.notes("1.0.0-rc.1", repo).startswith("First public release.")


def test_a_new_version_without_notes_is_refused(repo: Path) -> None:
    version.set_version("1.0.0", repo, today="2026-10-10")
    with pytest.raises(ValueError, match="empty"):
        version.set_version("1.0.1", repo)


def test_a_failed_set_writes_nothing(repo: Path) -> None:
    version.set_version("1.0.0", repo, today="2026-10-10")
    before = {name: (repo / name).read_text() for name in FILES}
    with pytest.raises(ValueError):
        version.set_version("1.0.0", repo)
    assert {name: (repo / name).read_text() for name in FILES} == before


@pytest.mark.parametrize("tag", ["1.0.0", "v1.0", "v1.0.0rc1", "v1.0.0-rc.0", "v1.0.0-beta.1", "v2.0.0"])
def test_check_refuses_malformed_tags(repo: Path, tag: str) -> None:
    with pytest.raises(ValueError):
        version.check(tag, repo)


def test_check_refuses_a_tag_the_files_do_not_declare(repo: Path) -> None:
    version.set_version("1.0.0-rc.1", repo, today="2026-10-10")
    with pytest.raises(ValueError, match="declares"):
        version.check("v1.0.0-rc.2", repo)


def test_release_history_lists_versions_and_omits_unreleased(repo: Path) -> None:
    assert "No version has been published yet." in docs_releases.render(
        (repo / "CHANGELOG.md").read_text())

    version.set_version("1.0.0-rc.1", repo, today="2026-10-10")
    page = docs_releases.render((repo / "CHANGELOG.md").read_text())
    assert "| [1.0.0-rc.1](#100-rc1-2026-10-10) | 2026-10-10 | Release candidate |" in page
    assert "## [Unreleased]" not in page
    assert "](compatibility.md)" in page
    assert "](docs/" not in page


def test_release_and_test_workflows_pin_the_same_toolchains() -> None:
    def env(name: str) -> dict[str, str]:
        text = (ROOT / ".github/workflows" / name).read_text()
        block = text.split("\nenv:\n", 1)[1].split("\n\n", 1)[0]
        return dict(line.strip().replace('"', "").split(": ", 1) for line in block.splitlines())

    pinned = env("test.yml")
    assert set(pinned) == {"RUST_TOOLCHAIN", "EMSDK_VERSION"}
    assert env("release.yml") == pinned
    assert env("api-compat.yml")["RUST_TOOLCHAIN"] == pinned["RUST_TOOLCHAIN"]


def test_current_reports_the_declared_version(repo: Path) -> None:
    version.set_version("1.0.0-rc.1", repo, today="2026-10-10")
    assert version.current(repo) == version.parse("1.0.0-rc.1")
    (repo / "VERSION").write_text("1.0.1\n")
    with pytest.raises(ValueError, match="different versions"):
        version.current(repo)


def test_ci_tests_the_declared_minimum_versions() -> None:
    import json
    import re
    import tomllib

    workflow = (ROOT / ".github/workflows/test.yml").read_text()
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    crates = [
        tomllib.loads((ROOT / f"bindings/rust/{name}/Cargo.toml").read_text())
        for name in ("semq", "semq-sys")
    ]
    go_mod = (ROOT / "bindings/go/go.mod").read_text()
    package = json.loads((ROOT / "bindings/ts/package.json").read_text())

    python_job = workflow.split("\n  python-versions:\n", 1)[1].split("\n  rust-minimum:\n", 1)[0]
    oldest_python = re.findall(r'- python: "([0-9.]+)"', python_job)[0]
    assert pyproject["project"]["requires-python"] == f">={oldest_python}"

    rust_job = workflow.split("\n  rust-minimum:\n", 1)[1].split("\n  # ", 1)[0]
    toolchain = re.search(r'toolchain: "([0-9.]+)"', rust_job)[1]
    assert {crate["package"]["rust-version"] for crate in crates} == {toolchain}

    go_job = workflow.split("\n  go:\n", 1)[1]
    assert re.search(r'go-version: "([0-9.]+)"', go_job)[1] == re.search(r"^go ([0-9.]+)$", go_mod, re.M)[1]

    ts_job = workflow.split("\n  ts:\n", 1)[1]
    assert package["engines"]["node"] == ">=" + re.search(r'node-version: "([0-9]+)"', ts_job)[1]
