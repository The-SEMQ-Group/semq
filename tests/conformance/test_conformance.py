# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""The Python host runner: every conformance case through the public surface.

Each vector directory holds a manifest.json with cases; this module executes
them with `semq` only (no private helpers) and compares with the expectations.
Cases a host cannot execute (setting the FP rounding mode) are skipped as
`unsupported`, as the vector document allows.
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path
from typing import Any

import numpy as np
import pytest

import semq
from semq import Codec, CodecConfig, Encoding, Floor

ROOT = Path(__file__).resolve().parent
ERRORS = {
    "InvalidInput": semq.InvalidInput,
    "Incompatible": semq.Incompatible,
    "FormatError": semq.FormatError,
    "IntegrityError": semq.IntegrityError,
    "Unsupported": semq.Unsupported,
    "Native": semq.Native,
}


def manifest(name: str) -> dict[str, Any]:
    return json.loads((ROOT / name / "manifest.json").read_text(encoding="utf-8"))


def cases(name: str) -> list[Any]:
    return [pytest.param(c, id=c["id"]) for c in manifest(name)["cases"]]


def config_of(spec: dict[str, Any]) -> CodecConfig:
    op = spec["operator"]
    p1 = spec.get("bins", spec.get("sectors", spec.get("scale", spec.get("parameter"))))
    return getattr(CodecConfig, op)(spec["dim"], p1)


def f32_from_hex(words: list[str]) -> np.ndarray:
    return np.array([struct.unpack("<f", bytes.fromhex(w)[::-1])[0] for w in words], dtype=np.float32)


def ids_of(spec: dict[str, Any]) -> list[Any]:
    return [int(v) for v in spec["values"]] if spec["kind"] == "u64" else list(spec["values"])


def assert_error(exc: Exception, expect: dict[str, Any]) -> None:
    assert isinstance(exc, ERRORS[expect["error"]]), f"{type(exc).__name__}: {exc}"
    row = getattr(exc, "row", None)
    field = getattr(exc, "field", getattr(exc, "section", None))
    if expect.get("row") is not None:
        assert row == expect["row"]
    if expect.get("field") is not None:
        assert field == expect["field"]
    if expect.get("which") is not None:
        assert getattr(exc, "which", None) == expect["which"]


def run_expecting(expect: dict[str, Any], fn):
    """Call fn; when the case expects an error, assert it; otherwise return the value."""
    if "error" in expect:
        with pytest.raises(tuple(ERRORS.values())) as info:
            fn()
        assert_error(info.value, expect)
        return None
    return fn()


# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", cases("00-sha256-fips"))
def test_00_sha256(case: dict[str, Any]) -> None:
    import hashlib

    inp = case["input"]
    msg = inp["ascii"].encode("ascii") if "ascii" in inp else inp["repeat"].encode("ascii") * inp["count"]
    # The host has no SHA-256 entry point; the identity contract is pinned
    # through state ids. hashlib is the platform reference here.
    assert hashlib.sha256(msg).hexdigest() == case["expect"]["digest"]


@pytest.mark.parametrize("case", cases("01-config-canonical"))
def test_01_config_canonical(case: dict[str, Any]) -> None:
    i = case["input"]
    cfg = run_expecting(case["expect"], lambda: getattr(CodecConfig, i["operator"])(i["dim"], i["parameter"]))
    if cfg is not None:
        assert cfg.to_bytes().hex() == case["expect"]["bytes"]
        assert CodecConfig.from_bytes(cfg.to_bytes()) == cfg


@pytest.mark.parametrize("case", cases("02-config-derived"))
def test_02_config_derived(case: dict[str, Any]) -> None:
    i, e = case["input"], case["expect"]
    cfg = getattr(CodecConfig, i["operator"])(i["dim"], i["parameter"])
    assert cfg.bytes_per_vector == e["bytes_per_vector"]
    assert cfg.units_per_row == e["units_per_row"]
    if i["operator"] == "quant":
        assert struct.pack(">f", cfg.max_magnitude).hex() == e["max_magnitude_bits"]


def load_vectors(vec: str, i: dict[str, Any]) -> np.ndarray:
    path = ROOT / vec / i["vectors_file"]
    return np.fromfile(path, dtype="<f4").reshape(i["shape"])


@pytest.mark.parametrize("case", cases("03-encode"))
def test_03_encode(case: dict[str, Any]) -> None:
    i, e = case["input"], case["expect"]
    codec = Codec(config_of(i["config"]))
    vectors = load_vectors("03-encode", i)
    enc = codec.encode(ids=np.arange(vectors.shape[0], dtype=np.uint64), vectors=vectors)
    assert enc.rows.tobytes() == (ROOT / "03-encode" / e["rows_file"]).read_bytes()
    assert codec.unpack(enc).tobytes() == (ROOT / "03-encode" / e["symbols_file"]).read_bytes()


@pytest.mark.parametrize("case", cases("04-encode-rejects"))
def test_04_encode_rejects(case: dict[str, Any]) -> None:
    i, e = case["input"], case["expect"]
    cfg = config_of(i["config"])
    codec = Codec(cfg)
    if "host" in i:
        # Representation checks the host performs before the core.
        if case["id"] == "float64-input":
            with pytest.raises(semq.InvalidInput):
                codec.encode(ids=[1], vectors=np.zeros((1, cfg.dim), dtype=np.float64))
        elif case["id"] == "wrong-width":
            with pytest.raises(semq.InvalidInput):
                codec.encode(ids=[1], vectors=np.zeros((1, cfg.dim - 1), dtype=np.float32))
        return
    vectors = f32_from_hex(i["vectors_f32"]).reshape(-1, cfg.dim) if i["vectors_f32"] else None
    kind = i["ids"]["kind"]
    ids = ids_of(i["ids"]) if i["ids"]["values"] else []
    if case["id"] == "empty-without-kind":
        with pytest.raises(semq.InvalidInput):
            codec.encode(ids=[], vectors=None)
        return
    if vectors is not None:
        vectors = vectors[: len(ids)]
    enc = run_expecting(e, lambda: codec.encode(ids=ids, vectors=vectors, id_kind=kind))
    if enc is not None:
        assert enc.content_digest.hex() == e["content_digest"]


def ulp_close(got: np.ndarray, want: np.ndarray, ulps: int) -> bool:
    g = got.astype(np.float32).view(np.int32).astype(np.int64)
    w = want.astype(np.float32).view(np.int32).astype(np.int64)
    return bool(np.all(np.abs(g - w) <= ulps))


@pytest.mark.parametrize("case", cases("05-decode"))
def test_05_decode(case: dict[str, Any]) -> None:
    i, e = case["input"], case["expect"]
    cfg = config_of(i["config"])
    codec = Codec(cfg)
    rows = np.fromfile(ROOT / "05-decode" / i["rows_file"], dtype=np.uint8).reshape(i["shape"][0], cfg.bytes_per_vector)
    enc = Encoding(np.arange(rows.shape[0], dtype=np.uint64), rows, cfg)
    want = np.fromfile(ROOT / "05-decode" / e["representatives_file"], dtype="<f4").reshape(i["shape"])
    assert ulp_close(codec.decode(enc), want, e["tolerance_ulp"])


@pytest.mark.parametrize("case", cases("06-ids-canonical"))
def test_06_ids(case: dict[str, Any]) -> None:
    i, e = case["input"], case["expect"]
    cfg = CodecConfig.quant(4, 4)
    if case["id"] == "utf8-too-long":
        with pytest.raises(semq.InvalidInput) as info:
            Encoding(["x" * i["length"]], np.zeros((1, 2), dtype=np.uint8), cfg)
        assert info.value.row == 0
        return
    if case["id"] == "lone-surrogate":
        with pytest.raises(semq.InvalidInput):
            Encoding(["\ud800"], np.zeros((1, 2), dtype=np.uint8), cfg)
        return
    spec = i["ids"]
    if "values_hex" in spec:
        raw = [bytes.fromhex(h) for h in spec["values_hex"]]
        # The host only accepts str; invalid bytes cannot be represented, so
        # they are rejected on decoding, before the core sees them.
        with pytest.raises((semq.InvalidInput, UnicodeDecodeError)):
            Encoding([b.decode("utf-8") for b in raw], np.zeros((len(raw), 2), dtype=np.uint8), cfg)
        return
    ids = ids_of(spec)
    enc = Encoding(ids, np.zeros((len(ids), 2), dtype=np.uint8), cfg, id_kind=spec["kind"])
    got = [str(int(v)) for v in enc.ids] if spec["kind"] == "u64" else list(enc.ids)
    assert got == e["sorted"]
    image = bytearray()
    enc.save(_Sink(image))
    assert bytes(image[28 : 28 + len(e["ids_section"]) // 2]).hex() == e["ids_section"]


class _Sink:
    def __init__(self, buf: bytearray) -> None:
        self.buf = buf

    def write(self, data: Any) -> int:
        self.buf.extend(bytes(data))
        return len(data)


@pytest.mark.parametrize("case", cases("07-manifest-canonical"))
def test_07_manifest(case: dict[str, Any]) -> None:
    i, e = case["input"], case["expect"]
    cfg = CodecConfig.quant(4, 4)
    raw_pairs = i.get("pairs")
    if raw_pairs is None:
        # Non-ASCII inputs travel as hex; bytes that are not UTF-8 cannot
        # become a Python str, so the host rejects them before the core.
        try:
            raw_pairs = [[bytes.fromhex(k).decode("utf-8"), bytes.fromhex(v).decode("utf-8")] for k, v in i["pairs_hex"]]
        except UnicodeDecodeError:
            assert e["error"] == "InvalidInput"
            return
    pairs: dict[str, str] = {}
    duplicate = False
    for k, v in raw_pairs:
        duplicate = duplicate or k in pairs
        pairs[k] = v
    if duplicate:
        # A Python dict cannot carry a duplicate key; the host has no way to
        # send one, so the core's rejection is exercised by the C tests.
        pytest.skip("unsupported: dict keys are unique")
    enc = run_expecting(e, lambda: Encoding([], None, cfg, pairs, id_kind="u64"))
    if enc is not None:
        image = bytearray()
        enc.save(_Sink(image))
        assert bytes(image[28:-64]).hex() == e["manifest_section"]
        assert enc.state_id.hex() == e["state_id"]
        assert enc.manifest == pairs


@pytest.mark.parametrize("case", cases("08-digests"))
def test_08_digests(case: dict[str, Any]) -> None:
    i, e = case["input"], case["expect"]
    if "file" in i:
        enc = Encoding.load(ROOT / "08-digests" / i["file"])
        assert enc.config == config_of(i["config"])
        assert enc.content_digest.hex() == e["content_digest"]
        assert enc.state_id.hex() == e["state_id"]
        return
    codec = Codec(config_of(i["config"]))
    vectors = np.fromfile(ROOT / "08-digests" / i["vectors_file"], dtype="<f4").reshape(-1, codec.config.dim)
    for order in i["orders"]:
        ids = [int(v) for v in order]
        rows = np.stack([vectors[v - 1] for v in ids])
        assert codec.encode(ids=ids, vectors=rows).state_id.hex() == e["state_id"]


@pytest.mark.parametrize("case", cases("09-file"))
def test_09_file(case: dict[str, Any]) -> None:
    i, e = case["input"], case["expect"]
    buf = bytearray((ROOT / "09-file" / i["file"]).read_bytes())
    if "mutate" in i:
        m = i["mutate"]
        if m["kind"] == "xor_byte":
            buf[m["at"]] ^= m["value"]
        elif m["kind"] == "set_byte":
            buf[m["at"]] = m["value"]
        elif m["kind"] == "truncate":
            buf = buf[: m["at"]]
        elif m["kind"] == "append_byte":
            buf.append(m["value"])
    enc = run_expecting(e, lambda: Encoding.load(bytes(buf)))
    if enc is not None:
        assert len(buf) == e["file_size"]
        assert enc.state_id.hex() == e["state_id"]
        assert len(enc) == e["n"] and enc.id_kind == e["id_kind"]
        out = bytearray()
        enc.save(_Sink(out))
        assert bytes(out) == bytes(buf)


@pytest.mark.parametrize("case", cases("10-concat"))
def test_10_concat(case: dict[str, Any]) -> None:
    i, e = case["input"], case["expect"]
    parts = [Encoding.load(ROOT / "10-concat" / f) for f in i["files"]]
    result = run_expecting(e, lambda: parts[0].concat(*parts[1:]))
    if result is not None:
        assert result.state_id.hex() == e["state_id"] and len(result) == e["n"]


@pytest.mark.parametrize("case", cases("11-diff"))
def test_11_diff(case: dict[str, Any]) -> None:
    i, e = case["input"], case["expect"]
    ref = Encoding.load(ROOT / "11-diff" / i["reference"])
    cand = Encoding.load(ROOT / "11-diff" / i["candidate"])
    d = run_expecting(e, lambda: ref.diff(cand))
    if d is not None:
        assert d.as_dict() == e["report"]
        if "units_of" in i:
            assert [list(u) for u in d.units(i["units_of"])] == e["units"]


@pytest.mark.parametrize("case", cases("12-floor"))
def test_12_floor(case: dict[str, Any]) -> None:
    i, e = case["input"], case["expect"]
    if "null_diffs" in i:
        diffs = [Encoding.load(ROOT / "12-floor" / a).diff(Encoding.load(ROOT / "12-floor" / b)) for a, b in i["null_diffs"]]
        floor = run_expecting(e, lambda: Floor.measure(diffs))
        if floor is not None:
            assert floor.as_dict() == e["floor"]
            for d in diffs:
                assert d.within(floor)
        return
    d = Encoding.load(ROOT / "12-floor" / i["reference"]).diff(Encoding.load(ROOT / "12-floor" / i["candidate"]))
    verdict = run_expecting(e, lambda: d.evaluate(Floor.from_dict(i["floor"]), per_row=i.get("per_row", False)))
    if verdict is not None:
        floor = Floor.from_dict(i["floor"])
        assert floor.as_dict() == i["floor"]
        assert verdict.as_dict() == e["evaluate"]
        assert d.within(floor) == e["within"]


@pytest.mark.parametrize("case", cases("13-report"))
def test_13_report(case: dict[str, Any]) -> None:
    i, e = case["input"], case["expect"]
    if "report" in e:
        d = Encoding.load(ROOT / "13-report" / i["reference"]).diff(Encoding.load(ROOT / "13-report" / i["candidate"]))
        assert json.loads(json.dumps(d.as_dict())) == e["report"]
    else:
        diffs = [Encoding.load(ROOT / "13-report" / a).diff(Encoding.load(ROOT / "13-report" / b)) for a, b in i["null_diffs"]]
        f = Floor.measure(diffs)
        assert json.loads(json.dumps(f.as_dict())) == e["floor"]
        assert Floor.from_dict(e["floor"]) == f


@pytest.mark.parametrize("case", cases("15-fp-environment"))
def test_15_fp_environment(case: dict[str, Any]) -> None:
    i, e = case["input"], case["expect"]
    if "rounding_mode" in i:
        pytest.skip("unsupported: Python cannot set the FP rounding mode")
    cfg = config_of(i["config"])
    vectors = f32_from_hex(i["vectors_f32"]).reshape(-1, cfg.dim)
    enc = Codec(cfg).encode(ids=ids_of(i["ids"]), vectors=vectors)
    assert enc.content_digest.hex() == e["content_digest"]


def test_root_surface_is_generated_from_the_host_table() -> None:
    assert len(semq.__all__) == 16
    assert math.isfinite(CodecConfig.quant(4, 4).max_magnitude)
