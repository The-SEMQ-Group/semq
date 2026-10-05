# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
"""Public algebraic invariants across operators and ID kinds."""
import io
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from semq import Codec, CodecConfig, Encoding, Floor


def test_parallel_chunk_encode_has_the_same_state_as_one_call() -> None:
    codec = Codec(CodecConfig.quant(64, 4))
    ids = np.arange(97, dtype=np.uint64)
    vectors = np.zeros((97, 64), dtype=np.float32)
    vectors[np.arange(97), np.arange(97) % 64] = 1.0
    whole = codec.encode(ids=ids, vectors=vectors)

    def encode_chunk(start: int) -> Encoding:
        stop = min(start + 13, len(ids))
        return codec.encode(ids=ids[start:stop], vectors=vectors[start:stop])

    with ThreadPoolExecutor(max_workers=4) as pool:
        chunks = list(pool.map(encode_chunk, range(0, len(ids), 13)))
    joined = chunks[0].concat(*chunks[1:])
    assert joined.state_id == whole.state_id
    assert joined.rows.tobytes() == whole.rows.tobytes()


@pytest.mark.parametrize("operator", ["quant", "phase", "orbit"])
@pytest.mark.parametrize("kind", ["u64", "utf8"])
@settings(max_examples=25, deadline=None)
@given(st.lists(st.integers(min_value=0, max_value=10000), unique=True, max_size=12))
def test_state_algebra(operator, kind, numbers):
    cfg = {"quant": CodecConfig.quant, "phase": CodecConfig.phase, "orbit": CodecConfig.orbit}[operator](4, 8)
    codec = Codec(cfg)
    ids = numbers if kind == "u64" else [f"id-{n}" for n in numbers]
    vectors = np.zeros((len(ids), 4), dtype=np.float32)
    for i, number in enumerate(numbers):
        vectors[i, number % 4] = 1
    def encode(which):
        return codec.encode(ids=[ids[i] for i in which], vectors=vectors[which], id_kind=kind)
    indices = list(range(len(ids)))
    state = encode(indices)
    assert state == encode(indices[::-1])
    image = io.BytesIO()
    state.save(image)
    assert Encoding.load(image.getvalue()) == state
    parts = [encode(indices[i::3]) for i in range(3)]
    a, b, c = parts
    assert a.concat(b, c) == c.concat(a, b) == a.concat(b).concat(c) == a.concat(b.concat(c)) == state
    empty = encode([])
    assert state.concat(empty) == empty.concat(state) == state
    own = state.diff(state)
    assert not own.added and not own.removed and not own.changed and not own.manifest_changes
    assert own.n_unchanged == len(ids)
    if ids:
        candidate = codec.encode(ids=ids, vectors=-vectors, id_kind=kind)
        null = state.diff(candidate)
        floor = Floor.measure([own, null])
        assert own.within(floor) and null.within(floor)
    declared = Encoding(state.ids, state.rows, cfg, {"declared": ""}, id_kind=kind)
    assert state.diff(declared).manifest_changes == {"declared": (None, "")}
    assert declared.diff(state).manifest_changes == {"declared": ("", None)}
