# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Prepare full BEIR test corpora and pinned embedding models for codec evaluation."""

from __future__ import annotations

import argparse
import csv
import importlib.metadata
import json
import platform
import re
from pathlib import Path

import numpy as np

from .run import digest, write_json


def align(corpus: list[dict], queries: list[dict], qrels: list[dict]) -> dict:
    """Keep the full corpus and exactly the queries judged in the selected split."""

    def indexed(rows):
        result = {str(row["_id"]): row for row in rows}
        if len(result) != len(rows):
            raise ValueError("duplicate document or query ID")
        return result

    docs, questions = indexed(corpus), indexed(queries)
    corpus_ids = sorted(docs)
    query_ids = sorted({str(row["query-id"]) for row in qrels})
    if not corpus_ids or not query_ids or set(query_ids) - questions.keys():
        raise ValueError("empty corpus/qrels or unknown query ID")
    doc_index = {key: i for i, key in enumerate(corpus_ids)}
    query_index = {key: i for i, key in enumerate(query_ids)}
    triples = {}
    for row in qrels:
        query, document = str(row["query-id"]), str(row["corpus-id"])
        score = float(row["score"])
        if document not in docs or not np.isfinite(score) or score < 0:
            raise ValueError("unknown document ID or invalid relevance")
        pair = (query_index[query], doc_index[document])
        if pair in triples:
            raise ValueError("duplicate relevance pair")
        triples[pair] = score
    pairs = sorted(triples)
    return {
        "corpus_ids": np.asarray(corpus_ids),
        "query_ids": np.asarray(query_ids),
        "corpus_text": [
            " ".join(
                str(docs[key].get(field, "")).strip() for field in ("title", "text")
            ).strip()
            for key in corpus_ids
        ],
        "query_text": [str(questions[key]["text"]).strip() for key in query_ids],
        "qrel_query": np.asarray([q for q, _ in pairs], dtype=np.int64),
        "qrel_document": np.asarray([d for _, d in pairs], dtype=np.int64),
        "qrel_score": np.asarray([triples[p] for p in pairs], dtype=np.float64),
    }


def prepare(
    config: dict,
    dataset: str,
    model_name: str,
    output: Path,
    *,
    offline: bool,
    device: str,
    batch_size: int,
) -> None:
    import pyarrow.parquet as pq
    import torch
    from huggingface_hub import hf_hub_download
    from sentence_transformers import SentenceTransformer

    spec = config["datasets"][dataset]
    encoder = config["models"][model_name]
    for revision in (spec["revision"], spec["qrels_revision"], encoder["revision"]):
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("source and model revisions must be full commit hashes")
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    output.mkdir(parents=True, exist_ok=False)
    source_files = {}

    def fetch(repo, revision, filename):
        path = Path(
            hf_hub_download(
                repo,
                filename,
                repo_type="dataset",
                revision=revision,
                local_files_only=offline,
            )
        )
        source_files[f"{repo}/{filename}"] = {
            "revision": revision,
            "sha256": digest(path),
        }
        return path

    corpus = pq.read_table(
        fetch(spec["repo"], spec["revision"], spec["corpus_file"])
    ).to_pylist()
    queries = pq.read_table(
        fetch(spec["repo"], spec["revision"], spec["queries_file"])
    ).to_pylist()
    with fetch(spec["qrels_repo"], spec["qrels_revision"], "test.tsv").open() as stream:
        qrels = list(csv.DictReader(stream, delimiter="\t"))
    data = align(corpus, queries, qrels)
    if (len(data["corpus_ids"]), len(data["query_ids"])) != (
        spec["corpus_rows"],
        spec["test_queries"],
    ):
        raise ValueError("source counts differ from the frozen dataset definition")
    torch.manual_seed(config["seed"])
    torch.set_num_threads(4)
    model = SentenceTransformer(
        encoder["repo"],
        revision=encoder["revision"],
        device=device,
        local_files_only=offline,
        trust_remote_code=False,
    )
    model.float()
    model.max_seq_length = encoder["max_length"]
    arrays = {}
    for key, prefix in (("corpus", "document_prefix"), ("queries", "query_prefix")):
        texts = data["corpus_text" if key == "corpus" else "query_text"]
        print(f"Encoding {dataset}/{model_name}: {len(texts)} {key}", flush=True)
        values = model.encode(
            texts,
            prompt=encoder[prefix],
            batch_size=batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=True,
        )
        values = np.asarray(values, dtype=np.float32)
        if (
            values.shape != (len(texts), encoder["dimension"])
            or not np.isfinite(values).all()
        ):
            raise ValueError("invalid embedding shape or values")
        arrays[key] = values
    manifest = {
        "schema_version": 1,
        "dataset": dataset,
        "sources": spec,
        "source_files": source_files,
        "model": encoder,
        "preprocessing": "strip title and text; join with one space; lexical string ID order",
        "split": "official test qrels; full corpus; only queries present in test qrels",
        "fit_policy": "transductive: full indexed corpus; no test queries or relevance used for fitting",
        "normalization": "L2; float32 embeddings",
        "seed": config["seed"],
        "device": str(model.device),
        "batch_size": batch_size,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": {
            name: importlib.metadata.version(name)
            for name in (
                "numpy",
                "torch",
                "transformers",
                "sentence-transformers",
                "huggingface-hub",
                "pyarrow",
            )
        },
        "preparation_source_sha256": digest(Path(__file__)),
    }
    payload = {
        **arrays,
        "fit": arrays["corpus"],
        **{
            key: data[key]
            for key in (
                "corpus_ids",
                "query_ids",
                "qrel_query",
                "qrel_document",
                "qrel_score",
            )
        },
        "dataset_provenance": np.asarray(json.dumps(manifest, sort_keys=True)),
    }
    np.savez(output / "embeddings.npz", **payload)
    write_json(
        output / "manifest.json",
        {**manifest, "artifact_sha256": digest(output / "embeddings.npz")},
    )
    print(output / "embeddings.npz", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=Path("benchmarks/configs/beir-datasets.json")
    )
    parser.add_argument("--dataset", choices=("scifact", "fiqa"), required=True)
    parser.add_argument(
        "--model",
        choices=("e5_small", "bge_small", "arctic_m", "mxbai_large"),
        default="e5_small",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()
    prepare(
        json.loads(args.config.read_text()),
        args.dataset,
        args.model,
        args.output,
        offline=args.offline,
        device=args.device,
        batch_size=args.batch_size,
    )


if __name__ == "__main__":
    main()
