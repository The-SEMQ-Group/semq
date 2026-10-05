# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Optional Faiss codecs with persisted training state and exhaustive IP scoring."""

from contextlib import contextmanager
from typing import Any, cast

import numpy as np

from .codecs import Encoded


@contextmanager
def single_thread(faiss):
    previous = faiss.omp_get_max_threads()
    faiss.omp_set_num_threads(1)
    try:
        yield
    finally:
        faiss.omp_set_num_threads(previous)


def integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in [{low}, {high}]")
    return value


class FaissCodec:
    def __init__(self, spec):
        self.name = spec["name"]
        self.bits = integer(spec["bits"], "bits", 1, 8)
        self.seed = integer(spec.get("seed", 20260921), "seed", 0, 2**31 - 1)
        if self.name == "faiss_sq" and self.bits not in (4, 6, 8):
            raise ValueError("Faiss SQ supports 4, 6 or 8 bits")
        if self.name == "faiss_turboquant_mse" and self.bits not in (1, 2, 3, 4, 8):
            raise ValueError("Faiss TurboQuant MSE supports 1, 2, 3, 4 or 8 bits")
        if self.name == "faiss_opq":
            self.subquantizers = integer(
                spec["subquantizers"], "subquantizers", 1, 65536
            )
            self.iterations = integer(spec.get("iterations", 20), "iterations", 1, 1000)

    def encode(self, fit, corpus):
        try:
            import faiss
        except ImportError as exc:
            raise RuntimeError("Install benchmarks/requirements-faiss.txt") from exc
        with single_thread(faiss):
            return self._encode(faiss, fit, corpus)

    def _encode(self, faiss, fit, corpus):
        dim = corpus.shape[1]
        model = {}
        if self.name == "faiss_opq":
            if dim % self.subquantizers or len(fit) < 2**self.bits:
                raise ValueError(
                    "OPQ requires divisible dimensions and at least 2^bits fit rows"
                )
            training_pq = faiss.ProductQuantizer(dim, self.subquantizers, self.bits)
            training_pq.cp.seed = self.seed
            transform = faiss.OPQMatrix(dim, self.subquantizers)
            transform.pq = training_pq
            transform.niter = self.iterations
            transform.niter_pq = self.iterations
            transform.niter_pq_0 = self.iterations
            transform.train(np.ascontiguousarray(fit))
            index = faiss.IndexPQ(
                dim, self.subquantizers, self.bits, faiss.METRIC_INNER_PRODUCT
            )
            index.pq.cp.seed = self.seed
            index.pq.cp.niter = self.iterations
        elif self.name in ("faiss_rabitq", "faiss_turboquant_mse"):
            transform = faiss.RandomRotationMatrix(dim, dim)
            transform.init(self.seed)
            if self.name == "faiss_rabitq":
                index = faiss.IndexRaBitQ(dim, faiss.METRIC_INNER_PRODUCT, self.bits)
                index.qb = 0
            else:
                qtype = getattr(faiss.ScalarQuantizer, f"QT_{self.bits}bit_tqmse")
                index = faiss.IndexScalarQuantizer(
                    dim, qtype, faiss.METRIC_INNER_PRODUCT
                )
                # Preserve magnitudes separately; the scalar tables encode directions.
                fit, _ = unit_rows(fit)
                corpus, norms = unit_rows(corpus)
                model["row_norms"] = norms
        else:
            transform = None
            qtype = getattr(faiss.ScalarQuantizer, f"QT_{self.bits}bit")
            index = faiss.IndexScalarQuantizer(dim, qtype, faiss.METRIC_INNER_PRODUCT)

        if transform is not None:
            model["rotation"] = faiss.vector_to_array(transform.A).reshape(dim, dim)
            fit = transform.apply_py(np.ascontiguousarray(fit))
            corpus = transform.apply_py(np.ascontiguousarray(corpus))
        index.train(np.ascontiguousarray(fit))
        codes = index.sa_encode(np.ascontiguousarray(corpus))
        # Serialize the trained empty index so codes are counted exactly once.
        model["faiss_model"] = faiss.serialize_index(index)
        return restore(codes, model)


def unit_rows(values):
    norms64 = np.linalg.norm(values.astype(np.float64), axis=1)
    with np.errstate(over="ignore"):
        norms = norms64.astype(np.float32)
    if not np.isfinite(norms).all():
        raise ValueError("row norm is not representable in float32")
    unit = np.divide(
        values.astype(np.float64),
        norms64[:, None],
        out=np.zeros(values.shape, dtype=np.float64),
        where=norms64[:, None] != 0,
    ).astype(np.float32)
    return unit, norms


def restore(codes, model):
    """Rebuild reconstruction and scoring using only persisted arrays."""
    import faiss

    index = faiss.deserialize_index(model["faiss_model"])
    index.add_sa_codes(np.ascontiguousarray(codes))
    reconstruction = np.asarray(index.reconstruct_n())
    rotation = model.get("rotation")
    norms = model.get("row_norms")
    if rotation is not None:
        reconstruction = reconstruction.astype(np.float64) @ rotation.astype(np.float64)
    if norms is not None:
        reconstruction = reconstruction * norms[:, None]

    def score(queries):
        with single_thread(faiss):
            q = np.ascontiguousarray(queries, dtype=np.float32)
            if rotation is not None:
                q = np.ascontiguousarray(q @ rotation.T)
            result = np.empty((len(q), index.ntotal), dtype=np.float64)
            # Request the full corpus, then restore corpus-row order before shared ranking.
            distances, labels = index.search(q, index.ntotal)
            if (labels < 0).any():
                raise ValueError("Faiss exhaustive search omitted corpus rows")
            np.put_along_axis(result, labels, distances, axis=1)
            if norms is not None:
                result *= norms[None, :]
            return result

    reconstruction_limit = None
    # nb_bits is present in the pinned runtime but missing from its SWIG type stub.
    if isinstance(index, faiss.IndexRaBitQ) and cast(Any, index.rabitq).nb_bits > 1:
        reconstruction_limit = "Faiss multibit RaBitQ decode exposes the one-bit representative; use method_scoring"
    return Encoded(
        codes,
        model,
        reconstruction,
        score,
        "faiss_exhaustive_ip_fp32_query_no_query_quantization",
        reconstruction_limit,
    )
