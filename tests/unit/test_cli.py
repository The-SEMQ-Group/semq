# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""The semq command: exit codes, JSON output and escaping."""

from __future__ import annotations

import json

import numpy as np
import pytest

from semq import Codec, CodecConfig, Encoding, Floor
from semq.cli import main

CORPUS = np.array(
    [[0.5, 0.5, 0.5, 0.5], [-0.5, -0.5, -0.5, -0.5], [1.0, 0.0, 0.0, 0.0]], dtype=np.float32
)


@pytest.fixture
def files(tmp_path):
    codec = Codec(CodecConfig.quant(4, 4))
    man = {"encoder": "m", "encoder_revision": "1"}
    ref = codec.encode(ids=[1, 2, 3], vectors=CORPUS, manifest=man)
    null = codec.encode(ids=[1, 2, 3], vectors=CORPUS, manifest=dict(man, note="rerun"))
    changed = CORPUS.copy()
    changed[2] = [0.0, 1.0, 0.0, 0.0]
    drift = codec.encode(ids=[1, 2, 3], vectors=changed, manifest=man)
    removed = codec.encode(ids=[1, 2], vectors=CORPUS[:2], manifest=man)
    added = codec.encode(ids=[1, 2, 3, 4], vectors=np.vstack([CORPUS, CORPUS[:1]]), manifest=man)
    encoder = codec.encode(ids=[1, 2, 3], vectors=CORPUS, manifest=dict(man, encoder="other"))
    weird = codec.encode(ids=["a\x1bb"], vectors=CORPUS[:1], manifest={"k": "v\x07"})
    paths = {}
    for name, e in {
        "ref": ref, "null": null, "drift": drift, "removed": removed, "added": added,
        "encoder": encoder, "weird": weird,
    }.items():
        p = tmp_path / f"{name}.semq"
        e.save(p)
        paths[name] = str(p)
    paths["floor"] = str(tmp_path / "floor.json")
    Floor.measure([ref.diff(null)]).save(tmp_path / "floor.json")
    paths["loose"] = str(tmp_path / "loose.json")
    (tmp_path / "loose.json").write_text(json.dumps({"changed_rows": 0, "total_rows": 3, "hamming": 0}))
    other = codec.encode(ids=[1, 2, 3], vectors=CORPUS, manifest=dict(man, corpus="v2"))
    paths["other-ref"] = str(tmp_path / "other-ref.semq")
    other.save(tmp_path / "other-ref.semq")
    paths["bad"] = str(tmp_path / "bad.semq")
    (tmp_path / "bad.semq").write_bytes(b"not a semq file")
    return paths


def test_show(files, capsys) -> None:
    assert main(["show", files["ref"]]) == 0
    out = capsys.readouterr().out
    assert "quant dim=4 bins=4" in out and "state_id:" in out
    assert main(["show", files["ref"], "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ids"] == ["1", "2", "3"] and report["id_kind"] == "u64" and report["n"] == 3
    assert report["manifest"] == {"encoder": "m", "encoder_revision": "1"}
    assert main(["show", files["bad"]]) == 2
    assert "error:" in capsys.readouterr().err
    assert main(["show", files["weird"]]) == 0
    out = capsys.readouterr().out
    assert "\\u001b" in out and "\\u0007" in out and "\x1b" not in out


def test_diff_without_floor_is_a_report(files, capsys) -> None:
    assert main(["diff", files["ref"], files["drift"]]) == 0
    assert "changed:       1" in capsys.readouterr().out
    assert main(["diff", files["ref"], files["drift"], "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["changed"] == [["3", 2]] and "within" not in report
    assert main(["diff", files["ref"], files["bad"]]) == 2


def test_diff_limit_zero_does_not_enumerate_ids(files, capsys, monkeypatch) -> None:
    from semq.diff import Diff

    def unexpected_list(_self):
        raise AssertionError("--limit 0 must not enumerate diff ids")

    for name in ("added", "removed", "changed"):
        monkeypatch.setattr(Diff, name, property(unexpected_list))
    assert main(["diff", files["ref"], files["drift"], "--limit", "0"]) == 0
    out = capsys.readouterr().out
    assert "changed:       1" in out
    assert "  ~ " not in out


def test_diff_with_floor_gates(files, capsys) -> None:
    floor = files["floor"]
    assert main(["diff", files["ref"], files["null"], "--floor", floor]) == 0
    assert "within:        True" in capsys.readouterr().out
    assert main(["diff", files["ref"], files["added"], "--floor", floor]) == 0
    capsys.readouterr()
    assert main(["diff", files["ref"], files["drift"], "--floor", floor]) == 1
    assert "not within the floor" in capsys.readouterr().err
    assert main(["diff", files["ref"], files["removed"], "--floor", floor]) == 1
    capsys.readouterr()
    assert main(["diff", files["ref"], files["encoder"], "--floor", floor]) == 1
    err = capsys.readouterr().err
    assert "manifest key encoder changed" in err and "not within the floor" in err
    assert main(["diff", files["ref"], files["drift"], "--floor", floor, "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["within"] is False
    # A floor of another reference cannot be applied; a loose or broken floor cannot be loaded.
    assert main(["diff", files["other-ref"], files["null"], "--floor", floor]) == 2
    assert "different reference" in capsys.readouterr().err
    assert main(["diff", files["ref"], files["null"], "--floor", files["loose"]]) == 2
    assert "invalid floor" in capsys.readouterr().err
    assert main(["diff", files["ref"], files["null"], "--floor", files["bad"]]) == 2


def test_floor_writes_only_json(files, capsys) -> None:
    assert main(["floor", files["ref"], files["null"], files["drift"], "--min-nulls", "2"]) == 0
    out = capsys.readouterr().out
    floor = Floor.load(out.encode())
    assert (floor.nulls, floor.changed_rows, floor.total_rows, floor.hamming) == (2, 1, 3, 2)
    assert floor.reference_id == Encoding.load(files["ref"]).state_id
    # Fewer nulls than required is a usage error unless lowered explicitly.
    assert main(["floor", files["ref"], files["null"]]) == 2
    assert "at least 3 null rebuilds" in capsys.readouterr().err
    assert main(["floor", files["ref"], files["null"], "--min-nulls", "1"]) == 0
    capsys.readouterr()
    assert main(["floor", files["ref"], files["null"], "--min-nulls", "0"]) == 2
    capsys.readouterr()
    assert main(["floor", files["ref"], files["removed"], "--min-nulls", "1"]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "error:" in captured.err
    assert main(["floor", files["ref"], files["encoder"], "--min-nulls", "1"]) == 2


def test_undecodable_floor_exits_2_in_a_real_process(files, tmp_path) -> None:
    import subprocess
    import sys

    bad = tmp_path / "bad-utf8.json"
    bad.write_bytes(b"\xff")
    result = subprocess.run(
        [sys.executable, "-m", "semq", "diff", files["ref"], files["null"], "--floor", str(bad)],
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 2, result.stderr.decode(errors="replace")
    assert b"invalid floor" in result.stderr and b"Traceback" not in result.stderr


def test_version(files, capsys) -> None:
    assert main(["version", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert {"sdk_version", "core_version", "backend", "build_id", "platform", "architecture", "runtime"} <= set(report)
    assert main(["version"]) == 0
    assert "core_version:" in capsys.readouterr().out
