# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
"""Exercise the installed wheel through its public API."""
from pathlib import Path

import numpy as np

import semq
from semq import Codec, CodecConfig, Encoding, Floor

print("installed package:", semq.__file__)
print("loaded core:", semq.build_info().as_dict())
for operator, parameter in [("quant", 4), ("phase", 8), ("orbit", 50)]:
    codec = Codec(getattr(CodecConfig, operator)(4, parameter))
    for kind, ids in [("u64", [2, 1]), ("utf8", ["doc-2", "doc-1"])]:
        vectors = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=np.float32)
        state = codec.encode(ids=ids, vectors=vectors, manifest={"encoder": "artifact"})
        path = Path(f"{operator}-{kind}.semq")
        state.save(path)
        restored = Encoding.load(path)
        assert state == restored and len(restored) == 2
        null = restored.diff(state)
        floor = Floor.measure([null])
        assert null.within(Floor.from_dict(floor.as_dict()))
        vectors[0, 0] = -1
        candidate = codec.encode(ids=ids, vectors=vectors, manifest={"encoder": "artifact"})
        diff = restored.diff(candidate)
        assert len(diff.changed) == 1 and not diff.within(floor)
        assert diff.changed[0][0] == ids[0]
        if operator == "quant" and kind == "u64":
            candidate.save("candidate.semq")
            floor.save("floor.json")
        print(operator, kind, "encode/restore/diff/floor OK")
