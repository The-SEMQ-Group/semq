# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Install-time integration test.

Run explicitly — requires a full CMake build (~30-90s):

    pytest -m install tests/install/
"""

from __future__ import annotations

import os
import subprocess
import venv
from pathlib import Path

import pytest

pytestmark = pytest.mark.install

_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def editable_venv(tmp_path_factory):
    venv_dir = tmp_path_factory.mktemp("venv")
    venv.create(venv_dir, with_pip=True)
    python = venv_dir / "bin" / "python"

    subprocess.run(
        [python, "-m", "pip", "install", "-e", str(_REPO_ROOT)],
        check=True,
        capture_output=True,
    )
    return python


def test_load_succeeds_without_library_path(editable_venv):
    env = {k: v for k, v in os.environ.items() if k != "SEMQ_LIBRARY_PATH"}
    result = subprocess.run(
        [editable_venv, "-c", "import semq; print(semq.build_info().core_version)"],
        env=env,
        capture_output=True,
    )
    assert result.returncode == 0, (
        f"build_info() failed in editable venv.\nstdout: {result.stdout.decode()}\n"
        f"stderr: {result.stderr.decode()}"
    )


def test_purelib_path_not_probed(editable_venv):
    env = {k: v for k, v in os.environ.items() if k != "SEMQ_LIBRARY_PATH"}
    result = subprocess.run(
        [
            editable_venv,
            "-c",
            "import sysconfig; from semq._ffi import _candidate_paths\n"
            "purelib = sysconfig.get_path('purelib')\n"
            "platlib = sysconfig.get_path('platlib')\n"
            "candidates = [str(p) for p in _candidate_paths()]\n"
            # In a normal venv purelib == platlib, so only flag divergence.
            "if purelib != platlib:\n"
            "    assert not any(purelib in c for c in candidates), "
            "    f'purelib {purelib!r} appeared in candidates: {candidates}'\n",
        ],
        env=env,
        capture_output=True,
    )
    assert result.returncode == 0, (
        f"purelib probe check failed.\nstdout: {result.stdout.decode()}\n"
        f"stderr: {result.stderr.decode()}"
    )
