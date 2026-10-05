# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Size table values pinned by hand, and the committed file kept current."""

import json

import pytest

from benchmarks import size


@pytest.fixture(scope="module")
def table():
    return size.compute()["dims"]


def test_hand_pinned_payloads(table):
    d768 = table["768"]
    assert d768["fp32"]["bytes_per_vector"] == 3072
    assert d768["semq_quant4"]["bytes_per_vector"] == 288  # 3 bits x 768 / 8
    assert d768["semq_quant2"]["bytes_per_vector"] == 192
    assert d768["semq_phase16"]["bytes_per_vector"] == 192
    assert d768["semq_orbit50"]["bytes_per_vector"] == 768
    assert d768["int8"]["bytes_per_vector"] == 772  # 768 + FP32 row scale
    assert d768["binary"]["bytes_per_vector"] == 96
    assert d768["int4_block32"]["bytes_per_vector"] == 384 + 24 * 2
    assert d768["mxfp4"]["bytes_per_vector"] == 384 + 24
    assert d768["mxfp8"]["bytes_per_vector"] == 768 + 24
    assert d768["nvfp4"]["bytes_per_vector"] == 384 + 48
    assert d768["nvfp4"]["fixed_bytes"] == 4
    assert d768["faiss_pq"]["bytes_per_vector"] == 192
    assert d768["faiss_pq"]["fixed_bytes"] == 256 * 768 * 4
    assert d768["matryoshka256_int8"]["bytes_per_vector"] == 260
    assert "matryoshka256_fp32" not in table["384"]
    assert table["1024"]["semq_quant8"]["bytes_per_vector"] == 512


def test_scale_and_ratio(table):
    q4 = table["768"]["semq_quant4"]
    assert q4["x_smaller_than_fp32"] == pytest.approx(3072 / 288, abs=1e-4)
    assert q4["gb_100m_vectors"] == 28.8
    assert table["768"]["fp32"]["gb_100m_vectors"] == 307.2


def test_semq_file_cost_is_payload_plus_id_plus_fixed(table):
    q4 = table["768"]["semq_quant4"]
    # magic 4 + version 2 + config 13 + id_kind 1 + n 8 + footer 64 + the
    # manifest section of an empty manifest.
    assert q4["file_fixed_bytes"] == 96
    assert q4["file_bytes_1m_rows"] == 96 + 1_000_000 * (288 + 8)
    assert q4["file_bytes_per_row_1m_rows"] == 296.000096


def test_committed_file_is_current():
    committed = json.loads(size.DEFAULT_OUTPUT.read_text())
    assert committed["schema"] == "semq-bench/size/1"
    size.check_result(size.DEFAULT_OUTPUT, size.compute())
