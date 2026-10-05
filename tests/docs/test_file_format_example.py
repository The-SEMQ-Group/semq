# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""The worked examples of the file-format page are real files."""

from __future__ import annotations

import re
from pathlib import Path

from semq import Encoding

REPO_ROOT = Path(__file__).resolve().parents[2]
PAGE = REPO_ROOT / "docs" / "reference" / "file-format.md"
FIXTURE = REPO_ROOT / "tests" / "conformance" / "09-file" / "empty-u64.semq"


def _hex_block_after(text: str, marker: str) -> bytes:
    start = text.index(marker)
    block = re.search(r"```\n([0-9a-f ]+)\n```", text[start:])
    assert block is not None, marker
    return bytes.fromhex(block.group(1).replace(" ", ""))


def test_complete_file_example_is_the_empty_fixture() -> None:
    text = PAGE.read_text(encoding="utf-8")
    image = _hex_block_after(text, "as a complete 96-byte file")
    assert image == FIXTURE.read_bytes()
    e = Encoding.load(image)
    assert len(e) == 0 and e.id_kind == "u64"
    # The digests printed a few lines above are the ones in the footer.
    digests = re.findall(r"(content_digest|state_id)\s+= ([0-9a-f]{64})", text)
    assert (e.content_digest.hex(), e.state_id.hex()) == (digests[0][1], digests[1][1])
