# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

import hashlib
from io import BytesIO

import pytest

from benchmarks import inputs


def registry():
    return {
        "repository": "owner/repo",
        "release": "inputs-v1",
        "inputs": {
            "example": {
                "files": [
                    {
                        "file": "embeddings.npz",
                        "asset": "example.npz",
                        "bytes": 4,
                        "sha256": hashlib.sha256(b"data").hexdigest(),
                    }
                ]
            }
        },
    }


def test_download_verifies_before_publishing_and_refuses_overwrite(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(inputs, "urlopen", lambda url, timeout: BytesIO(b"data"))
    destination = tmp_path / "verified"
    inputs.download(registry(), "example", destination)
    inputs.verify(destination, registry()["inputs"]["example"]["files"])
    with pytest.raises(FileExistsError):
        inputs.download(registry(), "example", destination)
    (destination / "embeddings.npz").write_bytes(b"oops")
    with pytest.raises(ValueError, match="verification failed"):
        inputs.verify(destination, registry()["inputs"]["example"]["files"])


def test_corrupt_download_does_not_leave_a_valid_looking_directory(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(inputs, "urlopen", lambda url, timeout: BytesIO(b"oops"))
    destination = tmp_path / "failed"
    with pytest.raises(ValueError, match="verification failed"):
        inputs.download(registry(), "example", destination)
    assert not destination.exists()
    assert not list(tmp_path.iterdir())


def test_authenticated_download_uses_exact_asset_and_same_hash_check(
    tmp_path, monkeypatch
):
    def run(command, check):
        assert command[:4] == ["gh", "release", "download", "inputs-v1"]
        assert command[command.index("--pattern") + 1] == "example.npz"
        from pathlib import Path

        Path(command[-1]).write_bytes(b"data")

    monkeypatch.setattr(inputs.subprocess, "run", run)
    inputs.download(registry(), "example", tmp_path / "private", github=True)
