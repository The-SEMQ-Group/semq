# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Low-precision storage formats as reference baselines, in pure numpy.

Each adapter implements ``codecs.Codec``: ``encode(fit, corpus)`` returns the
stored codes, every scale needed to decode them (in ``model``), and the decoded
float32 reconstruction. Storage accounting therefore counts every per-tensor,
per-block and per-dimension scale, so the effective bits per dimension that the
runner reports are the full cost of the format.

Minifloat element conversion is round to nearest, ties to even, and saturates
to the largest finite magnitude (the OCP "saturating" conversion mode). Codes
are sign-magnitude bytes: ``sign << (E + M) | exponent << M | mantissa``.
Four-bit codes are packed two per byte, element ``2j`` in the low nibble.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

import numpy as np

from .codecs import Encoded


@dataclass(frozen=True)
class Minifloat:
    """A sign-magnitude binary float with no infinities in its finite range."""

    name: str
    exponent_bits: int
    mantissa_bits: int
    bias: int
    finite_codes: int  # magnitude codes 0 .. finite_codes - 1 are finite values

    @cached_property
    def magnitudes(self) -> np.ndarray:
        codes = np.arange(self.finite_codes)
        exponent = codes >> self.mantissa_bits
        fraction = (codes & ((1 << self.mantissa_bits) - 1)).astype(np.float64)
        scale = float(1 << self.mantissa_bits)
        normal = (1.0 + fraction / scale) * np.exp2(exponent - self.bias)
        subnormal = fraction / scale * np.exp2(1 - self.bias)
        return np.where(exponent == 0, subnormal, normal)

    @property
    def max(self) -> float:
        return float(self.magnitudes[-1])

    @property
    def max_exponent(self) -> int:
        """Unbiased exponent of the largest finite value (``emax`` in OCP MX)."""
        return ((self.finite_codes - 1) >> self.mantissa_bits) - self.bias

    @property
    def sign_bit(self) -> int:
        return 1 << (self.exponent_bits + self.mantissa_bits)

    def encode(self, values: np.ndarray) -> np.ndarray:
        """Round to nearest even and saturate; returns uint8 sign-magnitude codes."""
        values = np.asarray(values, dtype=np.float64)
        if not np.isfinite(values).all():
            raise ValueError(f"{self.name} input must be finite")
        table = self.magnitudes
        magnitude = np.minimum(np.abs(values), table[-1])
        low = np.clip(np.searchsorted(table, magnitude, side="right") - 1, 0, None)
        high = np.minimum(low + 1, len(table) - 1)
        below, above = magnitude - table[low], table[high] - magnitude
        up = (above < below) | ((above == below) & (low % 2 == 1))
        codes = np.where(up, high, low).astype(np.uint8)
        return np.where(np.signbit(values), codes | self.sign_bit, codes).astype(
            np.uint8
        )

    def decode(self, codes: np.ndarray) -> np.ndarray:
        codes = np.asarray(codes, dtype=np.uint8)
        magnitude = codes & (self.sign_bit - 1)
        if (magnitude >= self.finite_codes).any():
            raise ValueError(f"{self.name} code is not a finite value")
        value = self.magnitudes[magnitude]
        return np.where(codes & self.sign_bit, -value, value)


# OCP 8-bit Floating Point Specification (OFP8) rev 1.0, table 1: E4M3 has no
# infinities and one NaN magnitude (S.1111.111), max 448; E5M2 follows IEEE 754
# (exponent 11111 is Inf/NaN), max 57344. OCP MX v1.0 section 5.3.3: FP4 E2M1
# has no Inf/NaN, max 6.
E4M3 = Minifloat("fp8_e4m3", 4, 3, 7, 127)
E5M2 = Minifloat("fp8_e5m2", 5, 2, 15, 124)
E2M1 = Minifloat("fp4_e2m1", 2, 1, 1, 8)


def pack_nibbles(codes: np.ndarray) -> np.ndarray:
    codes = np.asarray(codes, dtype=np.uint8)
    if codes.shape[-1] % 2:
        raise ValueError("four-bit packing needs an even number of elements")
    return (codes[..., 0::2] & 0xF) | ((codes[..., 1::2] & 0xF) << 4)


def unpack_nibbles(packed: np.ndarray) -> np.ndarray:
    packed = np.asarray(packed, dtype=np.uint8)
    out = np.empty(packed.shape[:-1] + (2 * packed.shape[-1],), dtype=np.uint8)
    out[..., 0::2], out[..., 1::2] = packed & 0xF, packed >> 4
    return out


def blocks(corpus: np.ndarray, size: int) -> np.ndarray:
    """View rows as (rows, dim / size, size); blocks never span two rows."""
    rows, dim = corpus.shape
    if dim % size:
        raise ValueError(f"dimension {dim} is not a multiple of the block size {size}")
    return np.asarray(corpus, dtype=np.float64).reshape(rows, dim // size, size)


def tensor_amax(corpus: np.ndarray) -> float:
    amax = float(np.max(np.abs(corpus)))
    if not np.isfinite(amax):
        raise ValueError("input must be finite")
    return amax


class FP8PerTensor:
    """OCP FP8 (E4M3 or E5M2) with one FP32 scale for the whole corpus tensor.

    Format: OCP 8-bit Floating Point Specification (OFP8) revision 1.0, 2023,
    https://www.opencompute.org/documents/ocp-8-bit-floating-point-specification-ofp8-revision-1-0-2023-12-01-pdf-1
    Scale ``s = amax / format_max`` (float32), element code ``fp8(x / s)`` with
    round to nearest even and saturation; decode ``fp8_value * s``. Storage is
    8 bits per coordinate plus the 32-bit scale.
    """

    def __init__(self, element: Minifloat):
        self.element = element

    def encode(self, fit: np.ndarray, corpus: np.ndarray) -> Encoded:
        amax = tensor_amax(corpus)
        scale = np.array(amax / self.element.max if amax else 1.0, dtype=np.float32)
        codes = self.element.encode(np.asarray(corpus, np.float64) / float(scale))
        reconstruction = (self.element.decode(codes) * float(scale)).astype(np.float32)
        return Encoded(codes, {"tensor_scale": scale}, reconstruction)


class Int4Block:
    """Symmetric INT4 per block of 32 with one FP16 absmax scale per block.

    Group-wise absmax integer quantization (group size 32), the symmetric form
    used for 4-bit weight groups: ``scale = fp16(amax / 7)``, code
    ``clip(rint(x / scale), -7, 7)`` stored as a two's-complement nibble,
    decode ``code * scale``. Levels are -7..7 so zero is exact and the range is
    symmetric, as in ``int8_symmetric_per_row``; llama.cpp ``Q4_0`` differs
    (``scale = amax / -8``, 16 levels). Storage is 4 bits per coordinate plus
    16 bits per 32 coordinates (4.5 bits per dimension).
    """

    block = 32

    def encode(self, fit: np.ndarray, corpus: np.ndarray) -> Encoded:
        x = blocks(corpus, self.block)
        amax = np.max(np.abs(x), axis=2)
        with np.errstate(over="ignore"):
            scale = (amax / 7).astype(np.float16)
        if not np.isfinite(scale).all() or ((amax > 0) & (scale == 0)).any():
            raise ValueError("INT4 block scale is not representable in FP16")
        divisor = np.where(scale == 0, 1.0, scale.astype(np.float64))[..., None]
        levels = np.clip(np.rint(x / divisor), -7, 7).astype(np.int8)
        codes = pack_nibbles(levels.reshape(corpus.shape).view(np.uint8))
        reconstruction = levels * scale.astype(np.float64)[..., None]
        return Encoded(
            codes,
            {"block_scale": scale},
            reconstruction.reshape(corpus.shape).astype(np.float32),
        )


def unpack_int4(codes: np.ndarray) -> np.ndarray:
    """Sign-extend packed two's-complement nibbles."""
    nibbles = unpack_nibbles(codes).astype(np.int8)
    return np.where(nibbles > 7, nibbles - 16, nibbles).astype(np.int8)


class Microscaling:
    """OCP Microscaling (MX) v1.0: MXFP4 (E2M1) or MXFP8 (E4M3) elements.

    Format: OCP Microscaling Formats (MX) Specification v1.0, 2023, sections
    5 and 6.3, https://www.opencompute.org/documents/ocp-microscaling-formats-mx-v1-0-spec-final-pdf
    Blocks of 32 share one E8M0 scale ``X = 2^(floor(log2(amax)) - emax_elem)``
    (``emax_elem`` = 2 for E2M1, 8 for E4M3), stored as the biased exponent
    byte (bias 127, 0xFF reserved for NaN). Elements are ``quantize(v / X)``,
    round to nearest even, saturating. An all-zero block stores scale code 0.
    Storage: element bits plus 8 bits per 32 coordinates (4.25 or 8.25 bits).
    """

    block = 32

    def __init__(self, element: Minifloat):
        self.element = element

    def encode(self, fit: np.ndarray, corpus: np.ndarray) -> Encoded:
        x = blocks(corpus, self.block)
        amax = np.max(np.abs(x), axis=2)
        _, exponent = np.frexp(amax)  # amax = m * 2^e, m in [0.5, 1)
        shared = np.where(amax > 0, exponent - 1 - self.element.max_exponent, -127)
        shared = np.clip(shared, -127, 127)
        scale_codes = (shared + 127).astype(np.uint8)
        elements = self.element.encode(x / np.exp2(shared)[..., None])
        reconstruction = self.element.decode(elements) * np.exp2(shared)[..., None]
        elements = elements.reshape(corpus.shape)
        codes = pack_nibbles(elements) if self.element is E2M1 else elements
        return Encoded(
            codes,
            {"block_scale_e8m0": scale_codes},
            reconstruction.reshape(corpus.shape).astype(np.float32),
        )


class NVFP4:
    """NVIDIA NVFP4: E2M1 elements, blocks of 16, E4M3 block scale, FP32 tensor scale.

    Format: NVIDIA PTX ISA 8.7+, block-scaled ``mma`` with ``.kind::mxf4nvf4``
    and ``scale_vec::4X`` (``ue4m3`` scale per 16 elements), and the reference
    recipe in NVIDIA TensorRT Model Optimizer (``NVFP4QTensor``): tensor scale
    ``g = amax_tensor / (6 * 448)`` (FP32); block scale ``e4m3(amax_block / 6 / g)``;
    element ``e2m1(x / (block_scale * g))``; decode ``e2m1 * block_scale * g``.
    Storage: 4 bits per coordinate, 8 bits per 16 coordinates and 32 bits per
    tensor (4.5 bits per dimension plus the tensor scale).
    """

    block = 16

    def encode(self, fit: np.ndarray, corpus: np.ndarray) -> Encoded:
        x = blocks(corpus, self.block)
        amax = tensor_amax(corpus)
        tensor_scale = np.array(
            amax / (E2M1.max * E4M3.max) if amax else 1.0, dtype=np.float32
        )
        g = float(tensor_scale)
        block_scale = E4M3.encode(np.max(np.abs(x), axis=2) / E2M1.max / g)
        decoded_scale = E4M3.decode(block_scale) * g
        divisor = np.where(decoded_scale == 0, 1.0, decoded_scale)[..., None]
        elements = E2M1.encode(
            np.where(decoded_scale[..., None] == 0, 0.0, x / divisor)
        )
        reconstruction = E2M1.decode(elements) * decoded_scale[..., None]
        return Encoded(
            pack_nibbles(elements.reshape(corpus.shape)),
            {"block_scale_e4m3": block_scale, "tensor_scale": tensor_scale},
            reconstruction.reshape(corpus.shape).astype(np.float32),
        )


def st_int8_ranges(calibration: np.ndarray) -> np.ndarray:
    calibration = np.asarray(calibration, dtype=np.float32)
    return np.vstack((np.min(calibration, axis=0), np.max(calibration, axis=0)))


def st_int8_quantize(values: np.ndarray, ranges: np.ndarray) -> np.ndarray:
    """sentence-transformers ``quantize_embeddings(precision="int8")`` arithmetic.

    float32 ``((x - start) / step - 128).astype(int8)`` with
    ``step = (max - min) / 255`` (1 where the range is empty). The cast
    truncates toward zero. Values outside the calibration range are clipped to
    [-128, 127] first; upstream leaves them to wrap in the integer cast.
    """
    values = np.asarray(values, dtype=np.float32)
    starts = ranges[0, :]
    steps = (ranges[1, :] - ranges[0, :]) / np.float32(255)
    steps = np.where(steps == 0, np.float32(1), steps).astype(np.float32)
    levels = (values - starts) / steps - np.float32(128)
    return np.clip(levels, -128, 127).astype(np.int8)


def st_int8_dequantize(codes: np.ndarray, ranges: np.ndarray) -> np.ndarray:
    steps = (ranges[1, :] - ranges[0, :]) / np.float32(255)
    steps = np.where(steps == 0, np.float32(1), steps).astype(np.float32)
    return ((codes.astype(np.float32) + 128) * steps + ranges[0, :]).astype(np.float32)


class SentenceTransformersInt8:
    """sentence-transformers ``quantize_embeddings(..., precision="int8")``.

    Source: sentence-transformers 5.x, ``sentence_transformers/util/quantization.py``,
    ``quantize_embeddings`` with ``calibration_embeddings``: per-dimension ``[min, max]`` ranges from a
    calibration set (here the ``fit`` rows, which are the corpus itself in the
    prepared inputs), 256 levels. Storage is 8 bits per coordinate plus the two
    float32 range rows. The decode ``(code + 128) * step + min`` is the inverse
    of the code map; upstream has no decoder and scores int8 codes directly.

    Relation to ``uint8_affine_per_dimension`` (``codecs.Scalar8``): same
    per-dimension affine ranges and storage, but Scalar8 rounds to nearest while
    this format truncates toward zero, so the codes differ.
    """

    def encode(self, fit: np.ndarray, corpus: np.ndarray) -> Encoded:
        ranges = st_int8_ranges(fit)
        codes = st_int8_quantize(corpus, ranges)
        return Encoded(codes, {"ranges": ranges}, st_int8_dequantize(codes, ranges))


class SentenceTransformersBinary:
    """sentence-transformers ``quantize_embeddings(..., precision="binary")``.

    Source: sentence-transformers 5.x, ``sentence_transformers/util/quantization.py``:
    bit ``x > 0``, ``np.packbits`` (most significant bit first), stored as int8
    ``byte - 128``.
    One bit per coordinate and no model arrays. The reconstruction is +1 for a
    set bit and -1 otherwise.

    Relation to ``binary_sign`` (``codecs.BinarySign``): that adapter sets the
    bit for ``x >= 0``, packs least significant bit first and adds a float32
    magnitude per row (32 extra bits per row). Rankings under cosine agree except
    on exact zeros; the stored bytes and storage cost differ.
    """

    def encode(self, fit: np.ndarray, corpus: np.ndarray) -> Encoded:
        positive = np.asarray(corpus) > 0
        packed = np.packbits(positive, axis=1)
        codes = (packed.astype(np.int16) - 128).astype(np.int8)
        return Encoded(codes, {}, np.where(positive, 1.0, -1.0).astype(np.float32))


class MatryoshkaTruncation:
    """Matryoshka truncation to the first ``keep`` dimensions, renormalized.

    Kusupati et al., "Matryoshka Representation Learning", NeurIPS 2022,
    https://arxiv.org/abs/2205.13147. Only meaningful for models trained with a
    Matryoshka loss. Stored as float32 (``keep`` x 32 bits per row), or, with
    ``int8=True``, followed by ``SentenceTransformersInt8`` on the truncated
    rows (calibrated on the truncated, renormalized ``fit`` rows). The
    reconstruction pads the dropped dimensions with zeros, so the inner product
    with a full query ranks exactly like a truncated, renormalized query.
    Bits per dimension are reported against the full input dimension.
    """

    def __init__(self, keep: int, int8: bool = False):
        if type(keep) is not int or keep < 1:
            raise ValueError("keep must be a positive integer")
        self.keep, self.int8 = keep, int8

    def truncate(self, values: np.ndarray) -> np.ndarray:
        head = np.asarray(values, dtype=np.float32)[:, : self.keep].astype(np.float64)
        norms = np.linalg.norm(head, axis=1, keepdims=True)
        if (norms == 0).any():
            raise ValueError("a truncated row has zero norm")
        return (head / norms).astype(np.float32)

    def encode(self, fit: np.ndarray, corpus: np.ndarray) -> Encoded:
        if corpus.shape[1] <= self.keep:
            raise ValueError(
                f"Matryoshka truncation to {self.keep} needs a wider input"
                f" than {corpus.shape[1]} dimensions"
            )
        head = self.truncate(corpus)
        model: dict[str, np.ndarray] = {}
        if self.int8:
            ranges = st_int8_ranges(self.truncate(fit))
            codes = st_int8_quantize(head, ranges)
            model["ranges"] = ranges
            head = st_int8_dequantize(codes, ranges)
        else:
            codes = head.copy()
        reconstruction = np.zeros(corpus.shape, dtype=np.float32)
        reconstruction[:, : self.keep] = head
        return Encoded(codes, model, reconstruction)
