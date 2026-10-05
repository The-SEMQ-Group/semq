# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Storage/reconstruction adapters, deliberately separate from native search.

New adapters implement encode(fit, corpus) -> Encoded. Encoding artifacts retain
all model arrays needed by reconstruction. Optional scorers expose a separate
method-specific profile; the workload owns ranking and metric definitions.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, cast

import numpy as np


@dataclass
class Encoded:
    codes: np.ndarray
    model: dict[str, np.ndarray]
    reconstruction: np.ndarray
    score: Callable[[np.ndarray], np.ndarray] | None = None
    score_profile: str | None = None
    reconstruction_limit: str | None = None

    @property
    def model_bytes(self) -> int:
        return sum(value.nbytes for value in self.model.values())


class Codec(Protocol):
    def encode(self, fit: np.ndarray, corpus: np.ndarray) -> Encoded: ...


def bf16_encode(values: np.ndarray) -> np.ndarray:
    """Binary32 to bfloat16, nearest-even rounding with gradual underflow."""
    values = np.asarray(values, dtype=np.float32)
    if not np.isfinite(values).all():
        raise ValueError("BF16 input must be finite")
    bits = values.view(np.uint32)
    rounded = bits + np.uint32(0x7FFF) + ((bits >> 16) & 1)
    codes = (rounded >> 16).astype(np.uint16)
    if not np.isfinite(bf16_decode(codes)).all():
        raise ValueError("BF16 conversion overflowed")
    return codes


def bf16_decode(codes: np.ndarray) -> np.ndarray:
    return (codes.astype(np.uint32) << 16).view(np.float32)


class FloatCodec:
    def __init__(self, name: str):
        self.name = name

    def encode(self, fit: np.ndarray, corpus: np.ndarray) -> Encoded:
        if self.name == "bf16":
            codes = bf16_encode(corpus)
            reconstruction = bf16_decode(codes)
        else:
            with np.errstate(over="ignore"):
                codes = corpus.astype(np.float16 if self.name == "fp16" else np.float32)
            reconstruction = codes.astype(np.float32)
        if not np.isfinite(reconstruction).all():
            raise ValueError(f"{self.name} conversion overflowed")
        return Encoded(codes, {}, reconstruction)


class Int8Symmetric:
    """Per-row absmax/127, nearest-even, signed levels [-127, 127]."""

    def encode(self, fit: np.ndarray, corpus: np.ndarray) -> Encoded:
        maximum = np.max(np.abs(corpus), axis=1, keepdims=True)
        scale = maximum / np.float32(127)
        if ((maximum > 0) & (scale == 0)).any():
            raise ValueError("INT8 scale underflowed float32")
        scale[scale == 0] = 1.0
        codes = np.clip(np.rint(corpus / scale), -127, 127).astype(np.int8)
        return Encoded(codes, {"scale": scale}, codes.astype(np.float32) * scale)


class Scalar8:
    """Per-dimension affine UINT8, fit min/max, nearest-even, endpoint levels."""

    def encode(self, fit: np.ndarray, corpus: np.ndarray) -> Encoded:
        low = np.min(fit, axis=0)
        with np.errstate(over="ignore"):
            span = np.max(fit, axis=0) - low
        if not np.isfinite(span).all():
            raise ValueError("scalar range overflowed")
        scale = span / np.float32(255)
        if ((span > 0) & (scale == 0)).any():
            raise ValueError("scalar scale underflowed float32")
        constant = span == 0
        scale[constant] = 1.0
        with np.errstate(over="ignore"):
            codes = np.clip(np.rint((corpus - low) / scale), 0, 255).astype(np.uint8)
        codes[:, constant] = 0
        return Encoded(
            codes,
            {"offset": low, "scale": scale},
            codes.astype(np.float32) * scale + low,
        )


class BinarySign:
    """One sign bit per coordinate with a least-squares magnitude per row."""

    def encode(self, fit: np.ndarray, corpus: np.ndarray) -> Encoded:
        positive = corpus >= 0
        scale = np.mean(np.abs(corpus.astype(np.float64)), axis=1).astype(np.float32)
        codes = np.packbits(positive, axis=1, bitorder="little")
        return Encoded(
            codes,
            {
                "dim": np.array(corpus.shape[1], dtype=np.uint32),
                "scale": scale,
            },
            np.where(positive, 1.0, -1.0) * scale[:, None],
        )


class FaissPQ:
    """Optional upstream Faiss ProductQuantizer; no local PQ implementation."""

    def __init__(self, subquantizers: int, bits: int, seed: int):
        if type(subquantizers) is not int or subquantizers < 1:
            raise ValueError("subquantizers must be positive")
        if type(bits) is not int or not 1 <= bits <= 8:
            raise ValueError("PQ bits must be in [1, 8]")
        if type(seed) is not int or not 0 <= seed < 2**31:
            raise ValueError("PQ seed must be a nonnegative signed 32-bit integer")
        self.subquantizers, self.bits, self.seed = subquantizers, bits, seed

    def encode(self, fit: np.ndarray, corpus: np.ndarray) -> Encoded:
        try:
            import faiss
        except ImportError as exc:
            raise RuntimeError(
                "faiss_pq requires benchmarks/requirements-faiss.txt"
            ) from exc
        dim = corpus.shape[1]
        if dim % self.subquantizers or len(fit) < 2**self.bits:
            raise ValueError(
                "PQ needs divisible dimensions and at least 2^bits fit rows"
            )
        from .faiss_codecs import single_thread

        with single_thread(faiss):
            pq = faiss.ProductQuantizer(dim, self.subquantizers, self.bits)
            pq.cp.seed = self.seed
            pq.train(np.ascontiguousarray(fit))
            codes = pq.compute_codes(np.ascontiguousarray(corpus))
            model = {
                "centroids": faiss.vector_to_array(pq.centroids),
                "shape": np.array(
                    [dim, self.subquantizers, self.bits], dtype=np.uint32
                ),
            }
            # Faiss installs an ndarray wrapper over the pointer-based SWIG signature.
            decode = cast(Callable[[np.ndarray], np.ndarray], pq.decode)
            return Encoded(codes, model, decode(codes))


def _semq_encode(config, corpus: np.ndarray):
    """Encode a unit-norm float32 corpus under one CodecConfig.

    Every SEMQ operator admits unit-norm rows only; rows are numbered by
    position so the codes come back in corpus order.
    """
    from semq import Codec

    corpus = np.ascontiguousarray(corpus, dtype=np.float32)
    norms = np.linalg.norm(corpus.astype(np.float64), axis=1)
    if not np.allclose(norms, 1.0, rtol=0, atol=1e-5):
        raise ValueError(
            "SEMQ requires unit-norm corpus rows; normalize before encoding"
        )
    codec = Codec(config)
    encoding = codec.encode(
        ids=np.arange(corpus.shape[0], dtype=np.uint64), vectors=corpus
    )
    return codec, encoding, encoding.rows.copy(), codec.decode(encoding)


class SemqQuant:
    def __init__(self, bits: int | None = None):
        if bits is not None and (type(bits) is not int or not 2 <= bits <= 7):
            raise ValueError("SEMQ QUANT bits must be in [2, 7]")
        self.bins = 4 if bits is None else 2 ** (bits - 1)

    def encode(self, fit: np.ndarray, corpus: np.ndarray) -> Encoded:
        from semq import CodecConfig

        config = CodecConfig.quant(corpus.shape[1], self.bins)
        _, _, codes, reconstruction = _semq_encode(config, corpus)
        model = {
            "dim": np.array(config.dim, dtype=np.uint32),
            "bins": np.array(config.bins, dtype=np.uint32),
            "max_magnitude": np.array(config.max_magnitude, dtype=np.float32),
        }
        return Encoded(codes, model, reconstruction)


class SemqPhase:
    def __init__(self, sectors: int):
        if type(sectors) is not int or not 2 <= sectors <= 256:
            raise ValueError("PHASE sectors must be in [2, 256]")
        self.sectors = sectors

    def encode(self, fit: np.ndarray, corpus: np.ndarray) -> Encoded:
        from semq import CodecConfig, InvalidInput

        dim = corpus.shape[1]
        try:
            config = CodecConfig.phase(dim, self.sectors)
        except InvalidInput as exc:
            raise ValueError(
                f"PHASE dimension {dim} is not divisible as required: {exc}"
            ) from exc
        _, _, codes, reconstruction = _semq_encode(config, corpus)
        return Encoded(
            codes,
            {
                "dim": np.array(dim, dtype=np.uint32),
                "sectors": np.array(self.sectors, dtype=np.uint32),
            },
            reconstruction,
        )


class SemqOrbit:
    def __init__(self, scale: int):
        if type(scale) is not int or not 1 <= scale <= 2**30:
            raise ValueError("ORBIT scale must be an integer in [1, 2^30]")
        self.scale = scale

    def encode(self, fit: np.ndarray, corpus: np.ndarray) -> Encoded:
        from semq import CodecConfig

        dim = corpus.shape[1]
        config = CodecConfig.orbit(dim, self.scale)
        _, _, codes, reconstruction = _semq_encode(config, corpus)
        return Encoded(
            codes,
            {
                "dim": np.array(dim, dtype=np.uint32),
                "scale": np.array(self.scale, dtype=np.uint32),
            },
            reconstruction,
        )


@dataclass(frozen=True)
class CodecSpec:
    factory: Callable[[dict], Codec]
    required: frozenset[str] = frozenset()
    optional: frozenset[str] = frozenset()
    role: str = "retrieval"


def faiss_codec(spec: dict) -> Codec:
    from .faiss_codecs import FaissCodec

    return FaissCodec(spec)


def format_codec(spec: dict) -> Codec:
    """Reference low-precision storage formats implemented in formats.py."""
    from . import formats

    name = spec["name"]
    factories: dict[str, Callable[[], Codec]] = {
        "fp8_e4m3": lambda: formats.FP8PerTensor(formats.E4M3),
        "fp8_e5m2": lambda: formats.FP8PerTensor(formats.E5M2),
        "int4_block32": formats.Int4Block,
        "mxfp4": lambda: formats.Microscaling(formats.E2M1),
        "mxfp8": lambda: formats.Microscaling(formats.E4M3),
        "nvfp4": formats.NVFP4,
        "st_int8": formats.SentenceTransformersInt8,
        "st_binary": formats.SentenceTransformersBinary,
        "mrl256": lambda: formats.MatryoshkaTruncation(256),
        "mrl256_int8": lambda: formats.MatryoshkaTruncation(256, int8=True),
    }
    return factories[name]()


FORMATS = (
    "fp8_e4m3",
    "fp8_e5m2",
    "int4_block32",
    "mxfp4",
    "mxfp8",
    "nvfp4",
    "st_int8",
    "st_binary",
    "mrl256",
    "mrl256_int8",
)

REGISTRY = {
    **{
        name: CodecSpec(lambda s: FloatCodec(s["name"]))
        for name in ("fp32", "fp16", "bf16")
    },
    "binary_sign": CodecSpec(lambda s: BinarySign()),
    "int8_symmetric_per_row": CodecSpec(lambda s: Int8Symmetric()),
    "uint8_affine_per_dimension": CodecSpec(lambda s: Scalar8()),
    "semq_quant": CodecSpec(
        lambda s: SemqQuant(s.get("bits")),
        optional=frozenset({"bits"}),
    ),
    "semq_phase": CodecSpec(
        lambda s: SemqPhase(s["sectors"]),
        frozenset({"sectors"}),
        role="angular_representation",
    ),
    "semq_orbit": CodecSpec(
        lambda s: SemqOrbit(s["scale"]),
        frozenset({"scale"}),
        role="comparison",
    ),
    "faiss_pq": CodecSpec(
        lambda s: FaissPQ(s["subquantizers"], s["bits"], s.get("seed", 20260921)),
        frozenset({"subquantizers", "bits"}),
        frozenset({"seed"}),
    ),
    "faiss_sq": CodecSpec(faiss_codec, frozenset({"bits"})),
    "faiss_opq": CodecSpec(
        faiss_codec,
        frozenset({"subquantizers", "bits"}),
        frozenset({"seed", "iterations"}),
    ),
    "faiss_rabitq": CodecSpec(faiss_codec, frozenset({"bits"}), frozenset({"seed"})),
    "faiss_turboquant_mse": CodecSpec(
        faiss_codec, frozenset({"bits"}), frozenset({"seed"})
    ),
    **{name: CodecSpec(format_codec) for name in FORMATS},
}


def build(spec: dict) -> Codec:
    name = spec.get("name")
    if not isinstance(name, str) or name not in REGISTRY:
        raise ValueError(f"unknown codec: {name}")
    entry = REGISTRY[name]
    missing = entry.required - spec.keys()
    if missing:
        raise ValueError(f"missing parameters for {name}: {', '.join(sorted(missing))}")
    if set(spec) - entry.required - entry.optional - {"name", "id"}:
        raise ValueError(f"unknown parameters for {name}")
    return entry.factory(spec)
