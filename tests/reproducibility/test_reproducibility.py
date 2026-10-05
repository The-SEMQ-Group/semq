# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""The Python host of the reproducibility fixture.

Encodes the 1,000 real embeddings of this directory with every configuration
of expected.json and compares content_digest, state_id and the saved file's
bytes. The other bindings run the same comparison; see README.md.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from semq import Codec, CodecConfig, Encoding

ROOT = Path(__file__).resolve().parent
AVAILABLE = all((ROOT / name).is_file() for name in ("vectors.f32", "ids.json", "expected.json"))
EXPECTED: dict[str, Any] = (
    json.loads((ROOT / "expected.json").read_text(encoding="utf-8")) if AVAILABLE else {"configs": {}}
)

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="reproducibility fixture missing")


@pytest.mark.parametrize("name", sorted(EXPECTED["configs"]))
def test_reproducibility(name: str, tmp_path: Path) -> None:
    meta = json.loads((ROOT / "ids.json").read_text(encoding="utf-8"))
    vectors = np.fromfile(ROOT / "vectors.f32", dtype="<f4").reshape(meta["rows"], meta["dim"])
    expect = EXPECTED["configs"][name]
    spec = expect["config"]
    codec = Codec(getattr(CodecConfig, spec["operator"])(spec["dim"], spec["parameter"]))

    state = codec.encode(
        ids=meta["values"],
        vectors=np.ascontiguousarray(vectors, dtype=np.float32),
        manifest=EXPECTED["manifest"],
        id_kind=EXPECTED["id_kind"],
    )
    path = tmp_path / f"{name}.semq"
    state.save(path)
    data = path.read_bytes()

    assert state.content_digest.hex() == expect["content_digest"]
    assert state.state_id.hex() == expect["state_id"]
    assert len(data) == expect["file_size"]
    assert hashlib.sha256(data).hexdigest() == expect["file_sha256"]
    assert Encoding.load(path).state_id == state.state_id
