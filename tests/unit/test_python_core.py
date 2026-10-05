# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""The Python surface against the specification: root exports, CodecConfig,
Codec, Encoding, Diff, Floor, BuildInfo and the six errors."""

from __future__ import annotations

import gc
import io
import json

import numpy as np
import pytest

import semq
from semq import (
    BuildInfo,
    Codec,
    CodecConfig,
    Diff,
    Encoding,
    Floor,
    FormatError,
    Incompatible,
    IntegrityError,
    InvalidInput,
    Native,
    Operator,
    Unsupported,
    build_info,
)

EMPTY_CONTENT = "4528e8a0422f5cde968847e021c85b4e6e78ce68da9e92b2981c62dd48f78f4a"
EMPTY_STATE = "ef4d1522eb158aa9b6b83cd5d51f80ea2cc59ac3aeb45b69a1c28c99375b55b9"
ONE_ROW_CONTENT = "1a3d8e8bfbf3429525d0bc11e18a17b75ea49af40b6b441f6863444f71230489"
ONE_ROW_STATE = "07d119f5a0a76de95bd4b41110d6005e6fc38cfc398421dd15df2be68adf9f85"

CORPUS = np.array(
    [[0.5, 0.5, 0.5, 0.5], [-0.5, -0.5, -0.5, -0.5], [1.0, 0.0, 0.0, 0.0]], dtype=np.float32
)
MANIFEST = {"encoder": "test", "encoder_revision": "1"}


@pytest.fixture(scope="module")
def q44() -> CodecConfig:
    return CodecConfig.quant(4, 4)


@pytest.fixture(scope="module")
def codec(q44: CodecConfig) -> Codec:
    return Codec(q44)


def pack_quant(symbols: np.ndarray, bits: int, bpv: int) -> np.ndarray:
    """LSB-first bit packing of one symbol per unit."""
    out = np.zeros(symbols.shape[:-1] + (bpv,), dtype=np.uint8)
    for row in range(symbols.shape[0]):
        pos = 0
        for s in symbols[row]:
            for b in range(bits):
                if (int(s) >> b) & 1:
                    out[row, pos >> 3] |= 1 << (pos & 7)
                pos += 1
    return out


@pytest.mark.parametrize("bins", [2, 3, 4, 5, 8, 17, 32, 64])
def test_quant_rows_pack_symbols_across_byte_boundaries(bins: int) -> None:
    cfg = CodecConfig.quant(9, bins)
    codec = Codec(cfg)
    vector = np.zeros((1, 9), dtype=np.float32)
    vector[0, 0] = 1.0
    encoding = codec.encode(ids=[1], vectors=vector)

    symbols = np.array([[2 * bins - 1] + [bins] * 8], dtype=np.uint8)
    bits = (2 * bins - 1).bit_length()
    expected = pack_quant(symbols, bits, cfg.bytes_per_vector)
    np.testing.assert_array_equal(encoding.rows, expected)
    np.testing.assert_array_equal(codec.unpack(encoding), symbols)


@pytest.mark.parametrize("bins", [2, 3, 4, 5, 8, 17, 64])
@pytest.mark.parametrize("dim", [9, 64])
def test_quant_diff_hamming_counts_changed_symbols(bins: int, dim: int) -> None:
    rng = np.random.default_rng(20260929 + bins + dim)
    vectors = rng.standard_normal((16, dim), dtype=np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    candidate = vectors.copy()
    candidate[:, :4] *= -1
    cfg = CodecConfig.quant(dim, bins)
    codec = Codec(cfg)
    reference = codec.encode(ids=list(range(16)), vectors=vectors)
    rebuilt = codec.encode(ids=list(range(16)), vectors=candidate)
    diff = reference.diff(rebuilt)

    ref_symbols = codec.unpack(reference)
    cand_symbols = codec.unpack(rebuilt)
    expected = {
        i: int(np.count_nonzero(ref_symbols[i] != cand_symbols[i]))
        for i in range(16)
        if not np.array_equal(ref_symbols[i], cand_symbols[i])
    }
    assert dict(diff.changed) == expected
    for id, hamming in diff.changed:
        assert len(diff.units(id)) == hamming


# ---------------------------------------------------------------------------
# Surface
# ---------------------------------------------------------------------------


def test_root_exports_are_the_fifteen_symbols() -> None:
    assert set(semq.__all__) == {
        "Operator", "CodecConfig", "Codec", "Encoding", "Diff", "Floor", "BuildInfo", "build_info",
        "InvalidInput", "Incompatible", "FormatError", "IntegrityError", "Unsupported", "Native",
        "__version__",
    }
    for name in semq.__all__:
        assert hasattr(semq, name)
    assert [Operator.ORBIT, Operator.PHASE, Operator.QUANT] == [0, 1, 2]


def test_build_info_reports_the_core() -> None:
    info = build_info()
    assert isinstance(info, BuildInfo)
    assert info.core_version and info.build_id
    assert set(info.backend) == {"orbit", "phase", "quant"}
    assert info.as_dict()["core_version"] == info.core_version


# ---------------------------------------------------------------------------
# CodecConfig
# ---------------------------------------------------------------------------


def test_config_canonical_form_and_derived(q44: CodecConfig) -> None:
    assert q44.to_bytes().hex() == "02040000000400000000000000"
    assert CodecConfig.from_bytes(q44.to_bytes()) == q44
    assert hash(CodecConfig.from_bytes(q44.to_bytes())) == hash(q44)
    assert (q44.operator, q44.dim, q44.bins, q44.rule_revision) == (Operator.QUANT, 4, 4, 0)
    assert (q44.bytes_per_vector, q44.units_per_row) == (2, 4)
    assert np.float32(q44.max_magnitude).view(np.uint32) == 0x3F800000
    assert q44.as_dict() == {"operator": "quant", "dim": 4, "bins": 4, "rule_revision": 0}
    p = CodecConfig.phase(8, 16)
    assert (p.sectors, p.bytes_per_vector, p.units_per_row) == (16, 2, 4)
    assert CodecConfig.phase(8, 17).bytes_per_vector == 4
    o = CodecConfig.orbit(5)
    assert (o.scale, o.bytes_per_vector, o.units_per_row) == (50, 5, 5)
    with pytest.raises(AttributeError):
        _ = o.bins
    with pytest.raises(AttributeError):
        _ = o.max_magnitude
    assert q44 != p


@pytest.mark.parametrize(
    "ctor, args, field",
    [
        (CodecConfig.quant, (4, 1), 2),
        (CodecConfig.quant, (4, 65), 2),
        (CodecConfig.quant, (0, 4), 1),
        (CodecConfig.quant, (65537, 4), 1),
        (CodecConfig.phase, (7, 16), 1),
        (CodecConfig.phase, (6, 16), 1),
        (CodecConfig.phase, (8, 1), 2),
        (CodecConfig.phase, (8, 257), 2),
        (CodecConfig.orbit, (8, 0), 2),
        (CodecConfig.orbit, (8, 2**30 + 1), 2),
    ],
)
def test_config_rejects_out_of_range(ctor, args, field) -> None:
    with pytest.raises(InvalidInput) as info:
        ctor(*args)
    assert info.value.field == field


def test_config_rejects_wrong_types() -> None:
    with pytest.raises(InvalidInput):
        CodecConfig.quant(4.0, 4)  # type: ignore[arg-type]
    with pytest.raises(InvalidInput):
        CodecConfig.from_bytes(b"\x02")
    with pytest.raises(InvalidInput):
        CodecConfig.from_bytes(bytes.fromhex("02040000000400000001000000"))  # rule revision 1


# ---------------------------------------------------------------------------
# Codec
# ---------------------------------------------------------------------------


def test_encode_sorts_ids_maps_symbols_and_is_deterministic(codec: Codec) -> None:
    e = codec.encode(ids=[3, 1, 2], vectors=CORPUS, manifest=MANIFEST)
    assert e.ids.tolist() == [1, 2, 3]
    assert e.id_kind == "u64"
    assert codec.unpack(e).tolist() == [[2, 2, 2, 2], [7, 4, 4, 4], [6, 6, 6, 6]]
    rep = codec.decode(e)
    assert rep.dtype == np.float32 and rep.shape == (3, 4)
    assert rep[0, 0] == -0.625 and rep[1, 0] == 0.875 and rep[1, 1] == 0.125 and rep[2, 0] == 0.625
    again = codec.encode(ids=np.array([3, 1, 2], dtype=np.uint64), vectors=CORPUS, manifest=MANIFEST)
    assert again.state_id == e.state_id and again.content_digest == e.content_digest
    assert e.manifest == MANIFEST
    assert e.config == codec.config and codec.backend
    assert len(e) == 3 and 2 in e and 9 not in e
    assert e.get(2).tolist() == e.rows[1].tolist()
    with pytest.raises(KeyError):
        e.get(9)
    assert [i for i, _ in e] == [1, 2, 3]


def test_encode_input_contract(codec: Codec) -> None:
    bad = CORPUS.copy()
    bad[1, 2] = np.nan
    with pytest.raises(InvalidInput) as info:
        codec.encode(ids=[1, 2, 3], vectors=bad)
    assert (info.value.row, info.value.field) == (1, 2)
    with pytest.raises(InvalidInput) as info:
        codec.encode(ids=[1], vectors=np.array([[0.9, 0, 0, 0]], dtype=np.float32))
    assert info.value.row == 0
    with pytest.raises(InvalidInput):
        codec.encode(ids=[1], vectors=np.array([[1, 0, 0, 0]], dtype=np.float64))
    with pytest.raises(InvalidInput):
        codec.encode(ids=[1], vectors=np.array([1, 0, 0, 0], dtype=np.float32))
    with pytest.raises(InvalidInput):
        codec.encode(ids=[1, 2], vectors=CORPUS[:1])
    with pytest.raises(InvalidInput) as info:
        codec.encode(ids=[4, 4], vectors=CORPUS[:2])
    assert info.value.row == 1
    with pytest.raises(InvalidInput):
        codec.encode(ids=[1, "a"], vectors=CORPUS[:2])
    with pytest.raises(InvalidInput):
        codec.encode(ids=[-1], vectors=CORPUS[:1])
    with pytest.raises(InvalidInput):
        codec.encode(ids=[2**64], vectors=CORPUS[:1])
    with pytest.raises(InvalidInput):
        codec.encode(ids=[], vectors=None)
    with pytest.raises(InvalidInput):
        codec.encode(ids=[1], vectors=CORPUS[:1], manifest={"k": 1})  # type: ignore[dict-item]
    with pytest.raises(InvalidInput):
        codec.encode(ids=[1], vectors=CORPUS[:1], id_kind="utf8")
    # Edge of the norm tolerance: 1 + 2^-10 is admitted, just above is not.
    codec.encode(ids=[1], vectors=np.array([[1.0, 0.03125, 0, 0]], dtype=np.float32))
    with pytest.raises(InvalidInput):
        codec.encode(ids=[1], vectors=np.array([[1.0, 0.0316, 0, 0]], dtype=np.float32))
    # Subnormals are canonicalized before anything else.
    a = codec.encode(ids=[1], vectors=np.array([[1.0, 1e-40, -1e-41, 0.0]], dtype=np.float32))
    b = codec.encode(ids=[1], vectors=np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32))
    assert a.content_digest == b.content_digest
    # A non-contiguous view is copied, not rejected.
    wide = np.zeros((3, 8), dtype=np.float32)
    wide[:, ::2] = CORPUS
    assert codec.encode(ids=[1, 2, 3], vectors=wide[:, ::2]).content_digest == codec.encode(
        ids=[1, 2, 3], vectors=CORPUS
    ).content_digest


def test_empty_encoding_needs_a_kind(codec: Codec) -> None:
    e = codec.encode(ids=[], vectors=None, id_kind="u64")
    assert len(e) == 0 and e.ids.tolist() == [] and e.rows.shape == (0, 2)
    assert e.content_digest.hex() == EMPTY_CONTENT and e.state_id.hex() == EMPTY_STATE
    u = codec.encode(ids=[], vectors=None, id_kind="utf8")
    assert u.id_kind == "utf8" and u.ids == ()
    assert u.state_id != e.state_id


def test_utf8_ids_sort_bytewise_and_reject_surrogates(codec: Codec) -> None:
    e = codec.encode(ids=["b", "a", "ab"], vectors=CORPUS)
    assert e.ids == ("a", "ab", "b") and e.id_kind == "utf8"
    assert e.get("ab").tolist() == e.rows[1].tolist()
    assert "b" in e and "zz" not in e
    with pytest.raises(InvalidInput):
        e.get(1)
    with pytest.raises(InvalidInput) as info:
        codec.encode(ids=["ok", "\ud800"], vectors=CORPUS[:2])
    assert info.value.row == 1
    with pytest.raises(InvalidInput):
        codec.encode(ids=["", "a"], vectors=CORPUS[:2])
    with pytest.raises(InvalidInput):
        codec.encode(ids=["x" * 4097], vectors=CORPUS[:1])


def test_decode_and_unpack_across_configs_are_incompatible(codec: Codec) -> None:
    other = Codec(CodecConfig.quant(4, 3))
    e = codec.encode(ids=[1], vectors=CORPUS[:1])
    with pytest.raises(Incompatible):
        other.decode(e)
    with pytest.raises(Incompatible):
        other.unpack(e)


def test_orbit_and_phase_symbols() -> None:
    v = np.array([[0.5, 0.5, -0.5, 0.5]], dtype=np.float32)
    orbit = Codec(CodecConfig.orbit(4))
    phase = Codec(CodecConfig.phase(4, 16))
    eo = orbit.encode(ids=[1], vectors=v)
    ep = phase.encode(ids=[1], vectors=v)
    assert orbit.unpack(eo).tolist() == [[7, 7, 16, 7]]
    assert phase.unpack(ep).tolist() == [[10, 14]]  # 45 degrees starts sector 10, 135 degrees starts sector 14
    assert orbit.decode(eo)[0].tolist() == pytest.approx([0.14, 0.14, -0.14, 0.14])
    assert ep.rows.shape == (1, 1)


# ---------------------------------------------------------------------------
# Encoding: constructor, identities, persistence
# ---------------------------------------------------------------------------


def test_low_level_constructor_matches_the_spec_examples(q44: CodecConfig) -> None:
    e = Encoding([7], np.array([[0x07, 0x07]], dtype=np.uint8), q44, {"encoder": "x"})
    assert e.content_digest.hex() == ONE_ROW_CONTENT
    assert e.state_id.hex() == ONE_ROW_STATE
    empty = Encoding([], None, q44, id_kind="u64")
    buf = io.BytesIO()
    empty.save(buf)
    assert len(buf.getvalue()) == 96
    assert buf.getvalue()[:6] == b"SEMQ\x02\x00"
    assert Encoding.load(buf.getvalue()).state_id.hex() == EMPTY_STATE
    with pytest.raises(InvalidInput) as info:
        Encoding([1], np.array([[0x07, 0x17]], dtype=np.uint8), q44)  # padding bit
    assert info.value.row == 0
    with pytest.raises(InvalidInput):
        Encoding([1], np.array([[0x90]], dtype=np.uint8), CodecConfig.phase(4, 8))  # nibble 9
    with pytest.raises(InvalidInput):
        Encoding([1], np.array([[1, 2, 3]], dtype=np.uint8), q44)  # width
    with pytest.raises(InvalidInput):
        Encoding([1], np.array([[1, 2]], dtype=np.int16), q44)  # dtype


def test_save_and_load_through_path_stream_and_bytes(codec: Codec, tmp_path) -> None:
    e = codec.encode(ids=[3, 1, 2], vectors=CORPUS, manifest=MANIFEST)
    path = tmp_path / "state.semq"
    e.save(path)
    assert not list(tmp_path.glob(".semq-*"))
    from_path = Encoding.load(path)
    with open(path, "rb") as f:
        from_stream = Encoding.load(f)
    from_bytes = Encoding.load(path.read_bytes())
    assert from_path.state_id == from_stream.state_id == from_bytes.state_id == e.state_id
    assert from_bytes.manifest == MANIFEST and from_bytes.ids.tolist() == [1, 2, 3]
    stream = io.BytesIO()
    e.save(stream)
    assert stream.getvalue() == path.read_bytes()
    with pytest.raises(InvalidInput):
        Encoding.load(42)  # type: ignore[arg-type]
    with pytest.raises(OSError):
        Encoding.load(tmp_path / "missing.semq")


def test_load_reports_format_and_integrity_errors(codec: Codec) -> None:
    e = codec.encode(ids=[10, 20], vectors=CORPUS[:2], manifest={"k": "v"})
    buf = io.BytesIO()
    e.save(buf)
    img = bytearray(buf.getvalue())
    rows_at = 28 + 16
    bad = img.copy()
    bad[rows_at] ^= 1
    with pytest.raises(IntegrityError) as info:
        Encoding.load(bytes(bad))
    assert info.value.which == "content"
    bad = img.copy()
    bad[-64 - 1] ^= 1  # last manifest byte
    with pytest.raises(IntegrityError) as info:
        Encoding.load(bytes(bad))
    assert info.value.which == "state"
    with pytest.raises(FormatError):
        Encoding.load(bytes(img[:-1]))
    with pytest.raises(FormatError):
        Encoding.load(bytes(img) + b"\x00")
    bad = img.copy()
    bad[4] = 1
    with pytest.raises(FormatError) as info:
        Encoding.load(bytes(bad))
    assert info.value.section == 0
    with pytest.raises(FormatError):
        Encoding.load(b"")


def test_views_are_read_only_and_outlive_the_encoding(codec: Codec) -> None:
    e = codec.encode(ids=[3, 1, 2], vectors=CORPUS)
    rows = e.rows
    ids = e.ids
    expected = rows.tolist()
    assert not rows.flags.writeable and not ids.flags.writeable
    with pytest.raises(ValueError):
        rows[0, 0] = 1
    # The flag cannot be turned back on: the bytes an identity names stay fixed.
    for view in (rows, ids, e.get(1), rows[0]):
        with pytest.raises(ValueError):
            view.setflags(write=True)
    state = e.state_id
    del e
    gc.collect()
    assert rows.tolist() == expected and ids.tolist() == [1, 2, 3]
    assert state == codec.encode(ids=[3, 1, 2], vectors=CORPUS).state_id


def test_utf8_ids_are_immutable(codec: Codec) -> None:
    e = codec.encode(ids=["b", "a"], vectors=CORPUS[:2])
    assert isinstance(e.ids, tuple) and e.ids == ("a", "b")
    assert e.ids is e.ids  # cached, and nothing a caller does to it changes the state


def test_encodings_compare_and_hash_by_state_id(codec: Codec, tmp_path) -> None:
    a = codec.encode(ids=[1, 2], vectors=CORPUS[:2], manifest=MANIFEST)
    a.save(tmp_path / "a.semq")
    b = Encoding.load(tmp_path / "a.semq")
    c = codec.encode(ids=[1, 2], vectors=CORPUS[:2], manifest={})
    assert a == b and hash(a) == hash(b) and len({a, b}) == 1
    assert a != c and a.content_digest == c.content_digest
    assert a.__eq__("not an encoding") is NotImplemented


class _OneBytePerCall(io.RawIOBase):
    """A raw stream that accepts a single byte per write, as a pipe may."""

    def __init__(self) -> None:
        super().__init__()
        self.data = bytearray()

    def writable(self) -> bool:
        return True

    def write(self, b) -> int:  # type: ignore[override]
        self.data += bytes(b[:1])
        return 1


class _Sink:
    """A duck-typed sink implementing the binary write protocol."""

    def __init__(self) -> None:
        self.data = bytearray()

    def write(self, b) -> int:
        self.data += bytes(b)
        return len(b)


def test_save_completes_partial_writes(codec: Codec) -> None:
    e = codec.encode(ids=[3, 1, 2], vectors=CORPUS, manifest=MANIFEST)
    expected = io.BytesIO()
    e.save(expected)
    raw = _OneBytePerCall()
    e.save(raw)
    sink = _Sink()
    e.save(sink)
    assert bytes(raw.data) == expected.getvalue() == bytes(sink.data)
    assert Encoding.load(bytes(raw.data)) == e


# ---------------------------------------------------------------------------
# concat and diff
# ---------------------------------------------------------------------------


def test_concat_is_commutative_associative_and_checked(codec: Codec) -> None:
    whole = codec.encode(ids=[1, 2, 3], vectors=CORPUS, manifest=MANIFEST)
    parts = [codec.encode(ids=[i + 1], vectors=CORPUS[i : i + 1], manifest=MANIFEST) for i in range(3)]
    assert parts[0].concat(parts[1], parts[2]).state_id == whole.state_id
    assert parts[2].concat(parts[0]).concat(parts[1]).state_id == whole.state_id
    empty = codec.encode(ids=[], vectors=None, id_kind="u64", manifest=MANIFEST)
    assert whole.concat(empty).state_id == whole.state_id
    with pytest.raises(InvalidInput) as info:
        whole.concat(parts[1])
    assert info.value.field == 1
    with pytest.raises(InvalidInput):
        whole.concat(codec.encode(ids=[9], vectors=CORPUS[:1]))  # manifest differs
    with pytest.raises(Incompatible):
        whole.concat(Codec(CodecConfig.quant(4, 3)).encode(ids=[9], vectors=CORPUS[:1], manifest=MANIFEST))
    with pytest.raises(Incompatible):
        whole.concat(codec.encode(ids=["z"], vectors=CORPUS[:1], manifest=MANIFEST))


def test_diff_reports_lists_units_and_manifest(codec: Codec) -> None:
    ref = codec.encode(ids=[1, 2, 3], vectors=CORPUS, manifest={"encoder": "m", "note": "a"})
    cand_vectors = np.array([[-0.5, -0.5, -0.5, -0.5], [0.0, 1.0, 0.0, 0.0], [0.5, 0.5, 0.5, 0.5]], dtype=np.float32)
    cand = codec.encode(ids=[2, 3, 4], vectors=cand_vectors, manifest={"encoder": "m", "run": "7"})
    d = ref.diff(cand)
    assert isinstance(d, Diff)
    assert (d.added, d.removed, d.n_unchanged) == ([4], [1], 1)
    assert d.changed == [(3, 2)]
    assert d.units(3) == [(0, 7, 4), (1, 4, 7)]
    assert d.units(2) == []
    with pytest.raises(InvalidInput):
        d.units(1)
    assert d.manifest_changes == {"note": ("a", None), "run": (None, "7")}
    assert d.reference_id == ref.state_id and d.candidate_id == cand.state_id
    assert d.config == codec.config and d.id_kind == "u64"
    report = d.as_dict()
    assert report["added"] == ["4"] and report["changed"] == [["3", 2]] and report["id_kind"] == "u64"
    assert report["config"] == {"operator": "quant", "dim": 4, "bins": 4, "rule_revision": 0}
    assert report["manifest_changes"] == {"note": ["a", None], "run": [None, "7"]}
    assert not d.within(Floor(d.config, id_kind=d.id_kind, reference_id=d.reference_id, nulls=1, changed_rows=4, total_rows=4, hamming=4))  # removed is not empty
    del ref, cand
    gc.collect()
    assert d.units(3) == [(0, 7, 4), (1, 4, 7)]
    with pytest.raises(TypeError):
        Diff()


def test_diff_short_circuit_and_incompatible(codec: Codec) -> None:
    a = codec.encode(ids=[1, 2], vectors=CORPUS[:2])
    b = codec.encode(ids=[2, 1], vectors=CORPUS[:2][::-1])
    d = a.diff(b)
    assert d.n_unchanged == 2 and d.changed == [] and d.added == [] and d.removed == []
    with pytest.raises(Incompatible):
        a.diff(codec.encode(ids=["1"], vectors=CORPUS[:1]))
    with pytest.raises(Incompatible):
        a.diff(Codec(CodecConfig.quant(4, 3)).encode(ids=[1], vectors=CORPUS[:1]))


# ---------------------------------------------------------------------------
# Floor
# ---------------------------------------------------------------------------


def _rows(n: int, n_changed: int, flip: int, base: int = 4) -> Encoding:
    cfg = CodecConfig.quant(16, 4)
    symbols = np.full((n, 16), base, dtype=np.uint8)
    symbols[:n_changed, :flip] = base + 1
    return Encoding(np.arange(n, dtype=np.uint64), pack_quant(symbols, 3, cfg.bytes_per_vector), cfg, id_kind="u64")


def _floor(d, nulls: int, changed: int, total: int, hamming: int, **over) -> Floor:
    config = over.pop("config", d.config)
    fields = {"id_kind": d.id_kind, "reference_id": d.reference_id, "nulls": nulls, "changed_rows": changed, "total_rows": total, "hamming": hamming}
    fields.update(over)
    return Floor(config, **fields)


def test_floor_measure_is_the_envelope_and_within_is_exact() -> None:
    base = _rows(100, 0, 0)
    null_a = base.diff(_rows(100, 1, 1))
    null_a2 = base.diff(_rows(100, 2, 1))
    null_b = _rows(1, 0, 0).diff(_rows(1, 1, 10))
    floor = Floor.measure([null_a, null_a2])
    assert (floor.changed_rows, floor.total_rows, floor.hamming, floor.nulls) == (2, 100, 1, 2)
    assert floor.config == base.config and floor.id_kind == "u64" and floor.reference_id == base.state_id
    assert floor == _floor(null_a, 2, 2, 100, 1)
    assert null_a.within(floor) and null_a2.within(floor)
    one = Floor.measure([null_a])
    assert one == _floor(null_a, 1, 1, 100, 1)
    assert not null_a2.within(one) and null_a2.within(_floor(null_a, 1, 2, 100, 1))
    # Bound to its reference: another reference, config or id kind is incompatible.
    with pytest.raises(Incompatible):
        Floor.measure([null_a, null_b])
    with pytest.raises(Incompatible):
        null_b.within(floor)
    with pytest.raises(Incompatible):
        null_a.within(_floor(null_a, 1, 1, 100, 1, config=CodecConfig.orbit(16)))
    with pytest.raises(Incompatible):
        null_a.within(_floor(null_a, 1, 1, 100, 1, id_kind="utf8"))
    empty = _rows(0, 0, 0).diff(_rows(0, 0, 0))
    assert not empty.within(_floor(empty, 1, 2, 100, 1))
    # Invalid floors fail at construction.
    for bad in ((1, 5, 4, 1), (1, 0, 0, 1), (1, -1, 4, 1), (1, 1, 1, 17), (0, 1, 1, 1)):
        with pytest.raises(InvalidInput):
            _floor(null_a, *bad)
    with pytest.raises(InvalidInput):
        _floor(null_a, 1, 1, 1, 1, id_kind="u32")
    with pytest.raises(InvalidInput):
        _floor(null_a, 1, 1, 1, 1, reference_id=b"short")
    with pytest.raises(InvalidInput):
        Floor.measure([])
    with pytest.raises(InvalidInput):
        Floor.measure([empty])
    with pytest.raises(InvalidInput):
        Floor.measure([_rows(2, 0, 0).diff(_rows(1, 0, 0))])  # removed a row
    with pytest.raises(InvalidInput):
        null_a.within("floor")  # type: ignore[arg-type]
    assert repr(floor).startswith("Floor(changed_rows=2, total_rows=100, hamming=1, nulls=2, ")


def test_floor_report_form_round_trips_and_is_strict(tmp_path) -> None:
    base = _rows(100, 0, 0)
    floor = Floor.measure([base.diff(_rows(100, 1, 1))])
    d = floor.as_dict()
    assert list(d) == ["version", "config", "id_kind", "reference_id", "nulls", "changed_rows", "total_rows", "hamming"]
    assert d["version"] == "semq-floor/1" and d["reference_id"] == base.state_id.hex()
    assert Floor.from_dict(json.loads(json.dumps(d))) == floor
    floor.save(tmp_path / "floor.json")
    assert Floor.load(tmp_path / "floor.json") == floor
    assert Floor.load((tmp_path / "floor.json").read_bytes()) == floor
    with open(tmp_path / "floor.json", encoding="utf-8") as f:
        assert Floor.load(f) == floor
    for mutate in (
        lambda x: x.pop("nulls"),
        lambda x: x.update(extra=1),
        lambda x: x.update(version="semq-floor/2"),
        lambda x: x.update(nulls="1"),
        lambda x: x.update(hamming=1.0),
        lambda x: x.update(changed_rows=True),
        lambda x: x.update(reference_id="zz"),
        lambda x: x.update(id_kind="u32"),
        lambda x: x.update(config={"operator": "quant", "dim": 16}),
        lambda x: x.update(config=dict(x["config"], rule_revision=1)),
    ):
        bad = json.loads(json.dumps(d))
        mutate(bad)
        with pytest.raises(InvalidInput):
            Floor.from_dict(bad)
    with pytest.raises(InvalidInput):
        Floor.load(b"not json")
    # Invalid UTF-8 is InvalidInput through every source, never a decode error.
    (tmp_path / "bad.json").write_bytes(b"\xff")
    with pytest.raises(InvalidInput):
        Floor.load(b"\xff")
    with pytest.raises(InvalidInput):
        Floor.load(tmp_path / "bad.json")
    with open(tmp_path / "bad.json", "rb") as f, pytest.raises(InvalidInput):
        Floor.load(f)
    # The rule revision is validated by the core, not by the host.
    with pytest.raises(InvalidInput, match="rule revision"):
        Floor.from_dict(dict(d, config=dict(d["config"], rule_revision=1)))


def test_floor_measure_rejects_reserved_manifest_changes(codec: Codec) -> None:
    a = codec.encode(ids=[1, 2], vectors=CORPUS[:2], manifest={"encoder": "x"})
    b = codec.encode(ids=[1, 2], vectors=CORPUS[:2], manifest={"encoder": "y"})
    with pytest.raises(InvalidInput):
        Floor.measure([a.diff(b)])
    c = codec.encode(ids=[1, 2], vectors=CORPUS[:2], manifest={"encoder": "x", "note": "n"})
    floor = Floor.measure([a.diff(c)])
    assert (floor.changed_rows, floor.total_rows, floor.hamming) == (0, 2, 0)
    # A change to a reserved key is never within, whatever the floor allows.
    assert not a.diff(b).within(floor)


# ---------------------------------------------------------------------------
# Errors and the FP environment
# ---------------------------------------------------------------------------


def test_failed_library_load_reports_native_without_deadlock() -> None:
    """Building the Native error must not re-enter the loader's lock."""
    import subprocess
    import sys

    script = (
        "import pathlib, semq._ffi as f\n"
        "f._candidate_paths = lambda: [pathlib.Path('/nonexistent/semq-missing-for-loader-test')]\n"
        "f._LIB = None\n"
        "from semq.errors import Native\n"
        "try:\n"
        "    f.lib()\n"
        "except Native as exc:\n"
        "    assert 'could not load' in str(exc) and 'core=unavailable' in str(exc), str(exc)\n"
        "    print('native')\n"
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, timeout=60)
    assert result.returncode == 0 and result.stdout.strip() == b"native", result.stderr.decode(errors="replace")


def test_errors_share_a_base_and_carry_context() -> None:
    from semq.errors import SemqError

    for cls in (InvalidInput, Incompatible, FormatError, IntegrityError, Unsupported, Native):
        assert issubclass(cls, SemqError)
    err = Native("boom", operation="op", status=7)
    assert err.operation == "op" and err.status == 7 and err.core_version and "build=" in str(err)


def test_direct_constructors_positional_vectors_and_readable_summaries():
    """The first lines a reader writes, and what printing the results says; the same
    text every binding produces for this data."""
    from semq import Codec, Encoding, Floor

    vectors = np.array([[0.6, 0.8, 0.0, 0.0], [0.0, 0.6, 0.8, 0.0], [0.0, 0.0, 0.6, 0.8]], dtype=np.float32)
    ids = ["doc-1", "doc-2", "doc-3"]
    manifest = {"encoder": "example-encoder", "encoder_revision": "1"}
    codec = Codec.quant(dim=4, bins=4)
    assert codec.config == Codec(CodecConfig.quant(4, 4)).config
    assert Codec.phase(dim=4, sectors=16).config.sectors == 16
    assert Codec.orbit(dim=4).config.scale == 50
    state = codec.encode(vectors, ids=ids, manifest=manifest)
    assert state == codec.encode(ids=ids, vectors=vectors, manifest=manifest)
    reference = Encoding.load(_roundtrip(state))
    assert str(codec.config) == "quant(dim=4, bins=4)"
    assert str(reference) == "Encoding(3 rows, quant(dim=4, bins=4), state_id 6e6f8a89bae4...)"
    rebuilt = vectors.copy()
    rebuilt[2] = [0.8, 0.0, 0.0, 0.6]
    diff = reference.diff(codec.encode(rebuilt, ids=ids, manifest=manifest))
    assert str(diff) == "1 of 3 rows changed: doc-3 (hamming 3). 0 added, 0 removed."
    assert str(reference.diff(codec.encode(vectors, ids=ids, manifest=manifest))) == "0 of 3 rows changed. 0 added, 0 removed."
    other = codec.encode(vectors, ids=ids, manifest={"encoder": "other", "encoder_revision": "1"})
    assert str(reference.diff(other)) == "0 of 3 rows changed. 0 added, 0 removed. Manifest changed: encoder."
    grown = codec.encode(np.vstack([vectors, [[1, 0, 0, 0]]]).astype(np.float32), ids=ids + ["doc-4"], manifest=manifest)
    assert str(reference.diff(grown)) == "0 of 3 rows changed. 1 added, 0 removed."
    floor = Floor.measure([reference.diff(codec.encode(vectors, ids=ids, manifest=manifest)) for _ in range(3)])
    assert str(floor) == "Floor(0 of 3 rows, hamming 0, from 3 nulls)"
    assert diff.within(floor) is False


def _roundtrip(state):
    import io

    buffer = io.BytesIO()
    state.save(buffer)
    return buffer.getvalue()
