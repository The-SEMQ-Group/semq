# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Known representations and direct native/third-party agreement."""

from typing import Any

import numpy as np
import pytest

from benchmarks import codecs


def test_bfloat16_known_ties_signed_zero_and_subnormal():
    bits = np.array(
        [0x3F808000, 0x3F818000, 0xBF808000, 0x80000000, 0x00010000], dtype=np.uint32
    )
    encoded = codecs.bf16_encode(bits.view(np.float32))
    assert encoded.tolist() == [0x3F80, 0x3F82, 0xBF80, 0x8000, 0x0001]
    assert codecs.bf16_decode(encoded).view(np.uint32).tolist() == [
        0x3F800000,
        0x3F820000,
        0xBF800000,
        0x80000000,
        0x00010000,
    ]


def test_bfloat16_overflow_is_explicit():
    with pytest.raises(ValueError, match="overflow"):
        codecs.bf16_encode(np.array([np.finfo(np.float32).max], dtype=np.float32))


@pytest.mark.parametrize("name,width", [("fp32", 4), ("fp16", 2), ("bf16", 2)])
def test_float_storage_and_exactly_representable_values(name, width):
    x = np.array([[0, 1, -2, 0.5]], dtype=np.float32)
    result = codecs.build({"name": name}).encode(x, x)
    assert result.codes.nbytes == x.size * width
    np.testing.assert_array_equal(result.reconstruction, x)


def test_int8_counts_scale_and_reconstructs_zero_rows():
    x = np.array([[0, 0], [-1, 1]], dtype=np.float32)
    result = codecs.Int8Symmetric().encode(x, x)
    assert result.codes.tolist() == [[0, 0], [-127, 127]]
    assert result.model_bytes == 8
    np.testing.assert_array_equal(result.reconstruction, x)


def test_scalar_fits_training_only_and_clips_held_out_values():
    fit = np.array([[0, 3], [1, 3]], dtype=np.float32)
    x = np.array([[-1, 8], [2, -4]], dtype=np.float32)
    result = codecs.Scalar8().encode(fit, x)
    assert result.codes.tolist() == [[0, 0], [255, 0]]
    np.testing.assert_array_equal(result.reconstruction, [[0, 3], [1, 3]])
    assert result.model_bytes == 16


@pytest.mark.parametrize("bits", [2, 3, 7])
def test_native_quant_adapter_matches_direct_binding(bits):
    from semq import Codec, CodecConfig

    x = np.array([[-0.6, 0.0, 0.0, 0.8, 0.0]], dtype=np.float32)
    result = codecs.SemqQuant(bits).encode(x, x)
    config = CodecConfig.quant(5, 2 ** (bits - 1))
    codec = Codec(config)
    encoding = codec.encode(ids=[0], vectors=x)
    np.testing.assert_array_equal(result.codes, encoding.rows)
    np.testing.assert_array_equal(result.reconstruction, codec.decode(encoding))
    assert result.codes.nbytes == (5 * bits + 7) // 8 and result.model_bytes == 12
    assert result.model["max_magnitude"] == np.float32(config.max_magnitude)


def test_faiss_artifact_is_sufficient_to_reconstruct():
    faiss = pytest.importorskip("faiss")
    rng = np.random.default_rng(7)
    fit = rng.standard_normal((128, 8)).astype(np.float32)
    x = rng.standard_normal((5, 8)).astype(np.float32)
    result = codecs.FaissPQ(2, 2, 7).encode(fit, x)
    pq = faiss.ProductQuantizer(*[int(n) for n in result.model["shape"]])
    faiss.copy_array_to_vector(result.model["centroids"], pq.centroids)
    np.testing.assert_array_equal(pq.decode(result.codes), result.reconstruction)


def test_unknown_parameters_and_quant_width_fail():
    with pytest.raises(ValueError):
        codecs.build({"name": "fp16", "bits": 8})
    with pytest.raises(ValueError):
        codecs.SemqQuant(8)


def test_integer_baselines_reject_unrepresentable_scales():
    tiny = np.nextafter(np.float32(0), np.float32(1))
    x = np.array([[0, tiny], [tiny, 0]], dtype=np.float32)
    for codec in (codecs.Int8Symmetric(), codecs.Scalar8()):
        with pytest.raises(ValueError, match="underflow"):
            codec.encode(x, x)


@pytest.mark.parametrize(
    "name,options,width",
    [
        ("semq_phase", {"sectors": 16}, 1),
        ("semq_phase", {"sectors": 256}, 2),
        ("semq_orbit", {"scale": 50}, 4),
    ],
)
def test_native_artifact_restores_configuration_and_reconstruction(
    name, options, width, tmp_path
):
    from semq import Codec, CodecConfig

    x = np.array([[0.5, 0.5, 0.5, 0.5], [-0.75, 0.25, 0.5, -0.35]], dtype=np.float32)
    x /= np.linalg.norm(x, axis=1, keepdims=True)
    result = codecs.build({"name": name, **options}).encode(x, x)
    path = tmp_path / "codec.npz"
    payload: dict[str, Any] = {"codes": result.codes, **result.model}
    np.savez(path, **payload)
    with np.load(path) as artifact:
        cfg = {key: int(artifact[key].item()) for key in result.model}
        dim = cfg.pop("dim")
        config = (
            CodecConfig.phase(dim, cfg["sectors"])
            if name == "semq_phase"
            else CodecConfig.orbit(dim, cfg["scale"])
        )
        codec = Codec(config)
        encoding = codec.encode(ids=np.arange(len(x)), vectors=x)
        np.testing.assert_array_equal(artifact["codes"], encoding.rows)
        np.testing.assert_array_equal(codec.decode(encoding), result.reconstruction)
    assert result.codes.nbytes == len(x) * width
    assert result.model_bytes == 8


@pytest.mark.parametrize(
    "spec",
    [
        {"name": "semq_phase", "sectors": 1},
        {"name": "semq_phase", "sectors": 257},
        {"name": "semq_phase", "sectors": "16"},
        {"name": "semq_orbit", "scale": 0},
        {"name": "semq_orbit", "scale": 2**30 + 1},
        {"name": "semq_orbit", "scale": 50, "alphabet_size": 19},
    ],
)
def test_native_invalid_configurations_fail(spec):
    with pytest.raises(ValueError):
        codecs.build(spec)


@pytest.mark.parametrize("sectors,dim", [(16, 2), (256, 3)])
def test_phase_does_not_silently_pad_dimensions(sectors, dim):
    x = np.zeros((1, dim), dtype=np.float32)
    x[0, 0] = 1.0
    with pytest.raises(ValueError, match="divisible"):
        codecs.SemqPhase(sectors).encode(x, x)


def test_binary_sign_packing_zero_and_scale():
    x = np.array([[-2, 1, 0, -1, 1, 0, 2, -1, -1], [0] * 9], dtype=np.float32)
    result = codecs.build({"name": "binary_sign"}).encode(x, x)
    signs = np.unpackbits(result.codes, axis=1, count=9, bitorder="little")
    np.testing.assert_array_equal(signs, x >= 0)
    assert result.codes.shape == (2, 2)
    assert result.model_bytes == 12
    np.testing.assert_array_equal(result.reconstruction[1], np.zeros(9))
    np.testing.assert_allclose(result.reconstruction[0], np.where(x[0] >= 0, 1, -1))


@pytest.mark.parametrize(
    "name",
    [
        "semq_phase",
        "semq_orbit",
        "faiss_pq",
        "faiss_opq",
        "faiss_sq",
        "faiss_rabitq",
        "faiss_turboquant_mse",
    ],
)
def test_missing_codec_parameters_have_actionable_errors(name):
    with pytest.raises(ValueError, match=f"missing parameters for {name}:"):
        codecs.build({"name": name})


@pytest.mark.parametrize("dim", [32, 384, 768])
def test_quant_default_is_four_bins_at_the_closed_form_range(dim):
    from semq import Codec, CodecConfig

    x = np.ones((2, dim), dtype=np.float32)
    x /= np.linalg.norm(x, axis=1, keepdims=True)
    encoded = codecs.build({"name": "semq_quant"}).encode(x, x)
    config = CodecConfig.quant(dim, 4)
    codec = Codec(config)
    np.testing.assert_array_equal(
        encoded.codes, codec.encode(ids=[0, 1], vectors=x).rows
    )
    assert encoded.model["bins"] == 4
    assert encoded.model["max_magnitude"] == np.float32(config.max_magnitude)
    assert encoded.codes.nbytes == len(x) * ((dim * 3 + 7) // 8)


def test_scale_free_quant_rejects_non_unit_data():
    x = np.ones((1, 4), dtype=np.float32)
    with pytest.raises(ValueError, match="unit-norm"):
        codecs.build({"name": "semq_quant", "bits": 2}).encode(x, x)
