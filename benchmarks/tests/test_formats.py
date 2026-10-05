# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Reference storage formats: hand-computed codes, error bounds and storage."""

import numpy as np
import pytest

from benchmarks import codecs, formats, metrics


def unit_rows(rows=64, dim=64, seed=5):
    x = np.random.default_rng(seed).standard_normal((rows, dim)).astype(np.float32)
    return x / np.linalg.norm(x, axis=1, keepdims=True)


def bits_per_dim(encoded, corpus):
    return metrics.storage(encoded.codes.nbytes, encoded.model_bytes, *corpus.shape)[
        "effective_bits_per_dimension"
    ]


def test_e4m3_known_codes_ties_subnormals_and_saturation():
    values = [1.0, -0.5, 448.0, 500.0, 2.0**-9, 1.0625, 1.1875, 0.0, -1e-9]
    assert formats.E4M3.encode(np.array(values)).tolist() == [
        0x38,
        0xB0,
        0x7E,
        0x7E,
        0x01,
        0x38,  # tie between 1.0 (0x38) and 1.125 (0x39) goes to even
        0x3A,  # tie between 1.125 (0x39) and 1.25 (0x3A) goes to even
        0x00,
        0x80,
    ]
    assert formats.E4M3.max == 448 and formats.E4M3.max_exponent == 8
    with pytest.raises(ValueError, match="finite"):
        formats.E4M3.decode(np.array([0x7F], dtype=np.uint8))


def test_e5m2_known_codes():
    values = [1.0, 57344.0, 1e6, 2.0**-16, -2.0]
    assert formats.E5M2.encode(np.array(values)).tolist() == [
        0x3C,
        0x7B,
        0x7B,
        0x01,
        0xC0,
    ]


def test_e2m1_known_codes_and_ties():
    values = [0.25, 0.75, 1.25, 2.5, 5.0, -6.0, 7.0, 3.0]
    assert formats.E2M1.encode(np.array(values)).tolist() == [0, 2, 2, 4, 6, 15, 7, 5]
    assert formats.E2M1.magnitudes.tolist() == [0, 0.5, 1, 1.5, 2, 3, 4, 6]
    assert formats.E2M1.max_exponent == 2


def test_mxfp4_block_shares_one_exponent():
    x = np.zeros((1, 32), dtype=np.float32)
    x[0, :4] = [3.0, 1.0, 0.3, -0.75]
    result = codecs.build({"name": "mxfp4"}).encode(x, x)
    # floor(log2 3) - emax(E2M1) = 1 - 2 = -1: X = 0.5, E8M0 code 126.
    assert result.model["block_scale_e8m0"].tolist() == [[126]]
    # 6 -> 0b0111, 2 -> 0b0100, 0.6 -> 0.5 = 0b0001, -1.5 -> 0b1011; low nibble first.
    assert result.codes[0, :2].tolist() == [0x47, 0xB1]
    assert result.codes[0, 2:].tolist() == [0] * 14
    np.testing.assert_array_equal(result.reconstruction[0, :4], [3.0, 1.0, 0.25, -0.75])


def test_mxfp8_block_exponent_and_saturation():
    x = np.full((1, 32), 0.5, dtype=np.float32)
    x[0, 0] = 3.9
    result = formats.Microscaling(formats.E4M3).encode(x, x)
    # floor(log2 3.9) - 8 = -7; 3.9 * 2^7 = 499.2 saturates to 448.
    assert result.model["block_scale_e8m0"].tolist() == [[120]]
    assert result.codes[0, 0] == 0x7E and result.reconstruction[0, 0] == 3.5
    assert result.reconstruction[0, 1] == 0.5


def test_nvfp4_block_and_tensor_scales():
    x = np.zeros((1, 32), dtype=np.float32)
    x[0, :3] = [6.0, 3.0, 1.0]
    x[0, 16:18] = [0.75, 0.25]
    result = codecs.build({"name": "nvfp4"}).encode(x, x)
    assert result.model["tensor_scale"] == np.float32(6.0 / (6 * 448))
    # Block scales 448 (0x7E) and 56 = 1.75 * 2^5 (0x66), both in E4M3.
    assert result.model["block_scale_e4m3"].tolist() == [[0x7E, 0x66]]
    assert result.codes[0, :2].tolist() == [0x57, 0x02]
    assert result.codes[0, 8].tolist() == 0x47
    np.testing.assert_allclose(result.reconstruction, x, rtol=1e-6, atol=0)


def test_int4_block_known_codes():
    x = np.zeros((1, 32), dtype=np.float32)
    x[0, :4] = [7.0, -3.0, 0.5, 1.5]
    result = codecs.build({"name": "int4_block32"}).encode(x, x)
    assert result.model["block_scale"].dtype == np.float16
    assert result.model["block_scale"].tolist() == [[1.0]]
    # 7 -> 0x7, -3 -> 0xD, rint(0.5) = 0, rint(1.5) = 2.
    assert result.codes[0, :2].tolist() == [0xD7, 0x20]
    assert formats.unpack_int4(result.codes)[0, :4].tolist() == [7, -3, 0, 2]


def test_block_formats_require_whole_blocks():
    x = unit_rows(dim=48)
    for name in ("int4_block32", "mxfp4", "mxfp8"):
        with pytest.raises(ValueError, match="block size"):
            codecs.build({"name": name}).encode(x, x)


@pytest.mark.parametrize(
    "name,bits,relative,min_cosine",
    [
        ("fp8_e4m3", 8 + 32 / (64 * 64), 2.0**-4, 0.999),
        ("fp8_e5m2", 8 + 32 / (64 * 64), 2.0**-3, 0.99),
        ("int4_block32", 4.5, None, 0.97),
        ("mxfp4", 4.25, None, 0.97),
        ("mxfp8", 8.25, None, 0.999),
        ("nvfp4", 4.5 + 32 / (64 * 64), None, 0.97),
        ("st_int8", 8 + 2 * 32 / 64, None, 0.999),
        ("st_binary", 1, None, 0.6),
    ],
)
def test_round_trip_error_and_storage(name, bits, relative, min_cosine):
    x = unit_rows()
    result = codecs.build({"name": name}).encode(x, x)
    assert result.reconstruction.shape == x.shape
    assert result.reconstruction.dtype == np.float32
    assert bits_per_dim(result, x) == pytest.approx(bits)
    error = np.abs(result.reconstruction.astype(np.float64) - x)
    if relative is not None:
        scale = float(result.model["tensor_scale"])
        # Half an ulp of the element, or half the smallest subnormal step.
        subnormal = formats.E4M3 if name == "fp8_e4m3" else formats.E5M2
        floor = subnormal.magnitudes[1] / 2 * scale
        assert (error <= np.maximum(np.abs(x) * relative, floor) * (1 + 1e-6)).all()
    cosine = np.sum(result.reconstruction * x, axis=1) / np.linalg.norm(
        result.reconstruction, axis=1
    )
    assert cosine.min() > min_cosine


def test_int4_error_is_half_a_step():
    x = unit_rows()
    result = formats.Int4Block().encode(x, x)
    scale = result.model["block_scale"].astype(np.float64).repeat(32, axis=1)
    assert (np.abs(result.reconstruction - x) <= scale / 2 * (1 + 1e-3)).all()


def test_st_int8_truncates_and_calibrates_on_fit():
    fit = np.array([[0.0, -1.0], [2.55, 1.0]], dtype=np.float32)
    x = np.array([[0.0, 1.0], [0.019, -1.0], [3.0, 0.0]], dtype=np.float32)
    result = codecs.build({"name": "st_int8"}).encode(fit, x)
    # step 0.01: 0 -> -128; 0.019 -> 1.9 - 128 = -126.1 -> -126 (toward zero);
    # 3.0 is outside the fit range and clips to 127.
    assert result.codes[:, 0].tolist() == [-128, -126, 127]
    # float32 step 2/255 puts the maximum at level 254.99998, which truncates to
    # 126, exactly as upstream does; 0 -> -0.5 -> 0.
    assert result.codes[:, 1].tolist() == [126, -128, 0]
    assert result.model["ranges"].shape == (2, 2)
    x = unit_rows()
    result = formats.SentenceTransformersInt8().encode(x, x)
    steps = np.diff(result.model["ranges"], axis=0) / 255
    assert (np.abs(result.reconstruction - x) <= steps * (1 + 1e-4)).all()


def test_st_binary_packs_most_significant_bit_first():
    x = np.array([[1, -1, 0, 1, 1, 1, 1, 1, -1, -1, -1, -1, -1, -1, -1, 2]], np.float32)
    result = codecs.build({"name": "st_binary"}).encode(x, x)
    # 0b10011111 = 159 -> 31; 0b00000001 = 1 -> -127; zero is not positive.
    assert result.codes.tolist() == [[31, -127]] and result.model == {}
    assert result.reconstruction[0, :3].tolist() == [1, -1, -1]


def test_matryoshka_truncates_renormalizes_and_counts_the_kept_prefix():
    x = unit_rows(dim=512)
    result = codecs.build({"name": "mrl256"}).encode(x, x)
    head = x[:, :256] / np.linalg.norm(x[:, :256], axis=1, keepdims=True)
    np.testing.assert_allclose(result.reconstruction[:, :256], head, atol=1e-7)
    assert not result.reconstruction[:, 256:].any()
    assert bits_per_dim(result, x) == 16
    quantized = codecs.build({"name": "mrl256_int8"}).encode(x, x)
    assert quantized.codes.shape == (64, 256) and quantized.codes.dtype == np.int8
    assert bits_per_dim(quantized, x) == pytest.approx(4 + 2 * 256 * 32 / (64 * 512))
    with pytest.raises(ValueError, match="wider"):
        codecs.build({"name": "mrl256"}).encode(x[:, :256], x[:, :256])
