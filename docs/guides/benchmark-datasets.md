# Evaluate SciFact and FiQA

**Goal:** measure storage and retrieval-quality changes on full, labeled public
corpora using fixed embeddings and the same queries for every codec.

**Prerequisites:** Python 3.12 or newer for the pinned preparation dependencies.
Follow the native-library setup in the
[benchmark protocol](benchmark-protocol.md). Preparation also requires the
optional model and dataset dependencies below. Allow space for model weights,
embeddings and per-method artifacts. GPU inference is optional.

## Datasets and models

- [SciFact](https://huggingface.co/datasets/BeIR/scifact): 5,183 documents and 300 test queries; retrieve scientific evidence for a claim.
- [FiQA-2018](https://huggingface.co/datasets/BeIR/fiqa): 57,638 documents and 648 test queries; retrieve answers to financial questions.

`benchmarks/configs/beir-datasets.json` pins full commit hashes for each corpus,
query collection, relevance collection and model. Preparation preserves every
corpus document, including distractors, and selects exactly the queries in the
official test judgments. Corpus and query IDs are ordered lexically as strings.
The source distributions declare CC BY-SA 4.0; retain their attribution and
review their source terms before redistributing text or derived datasets.

Four model configurations are provided. The published results use the first,
third and fourth, one per dimension; BGE-small remains available as an input.

- [E5-small-v2](https://huggingface.co/intfloat/e5-small-v2), 384 dimensions:
  `query: ` and `passage: ` prefixes for queries and documents, respectively.
- [BGE-small-en-v1.5](https://huggingface.co/BAAI/bge-small-en-v1.5), 384
  dimensions: the retrieval instruction on queries, and no document prefix.
- [snowflake-arctic-embed-m-v1.5](https://huggingface.co/Snowflake/snowflake-arctic-embed-m-v1.5),
  768 dimensions, trained for Matryoshka truncation: the retrieval instruction on
  queries, and no document prefix.
- [mxbai-embed-large-v1](https://huggingface.co/mixedbread-ai/mxbai-embed-large-v1),
  1024 dimensions, trained for Matryoshka truncation: the same instruction on
  queries, and no document prefix.

Both use their published pooling configuration, float32 model weights,
512-token truncation and L2-normalized embeddings. Document titles and text
are stripped and joined with one space. The manifest records package versions,
device, batch size, prefixes and source-file hashes. Encoding on different
hardware can produce different floating-point embeddings: codec reproducibility
starts from the same frozen input bytes, not from text inference.

## 1. Prepare embeddings

### Download the frozen inputs

To reproduce the published codec evaluation with identical input bytes, download
the versioned [benchmark input assets](https://github.com/The-SEMQ-Group/semq/releases/tag/benchmark-inputs-2026-09):

```sh
python -m benchmarks.inputs scifact-e5 --output benchmarks/data/scifact-e5
python -m benchmarks.inputs fiqa-e5 --output benchmarks/data/fiqa-e5
python -m benchmarks.inputs scifact-arctic --output benchmarks/data/scifact-arctic
python -m benchmarks.inputs fiqa-arctic --output benchmarks/data/fiqa-arctic
python -m benchmarks.inputs scifact-mxbai --output benchmarks/data/scifact-mxbai
python -m benchmarks.inputs fiqa-mxbai --output benchmarks/data/fiqa-mxbai
```

The BGE-small inputs (`scifact-bge`, `fiqa-bge`) download the same way.

For a private repository, authenticate the GitHub CLI and add `--github` to each
command. Repository access is required; the downloader does not change visibility.
Each input contains the exact NPZ, preparation manifest and dataset attribution.
SciFact uses about 15.8 MiB and FiQA 171.2 MiB per model, including the repeated
fit array. Dataset assets carry CC BY-SA 4.0 attribution separately from the
SDK's PolyForm Noncommercial code license; model weights and source text are
not redistributed.

The downloader checks file sizes and SHA-256 hashes from
`benchmarks/configs/frozen-inputs.json` before exposing the output directory.
To check a downloaded directory again:

```sh
python -m benchmarks.inputs scifact-e5 --output benchmarks/data/scifact-e5 --verify-only
```

Proceed to **Evaluate codecs**. Model-inference dependencies are unnecessary when
using frozen inputs. Reproducing these input bytes does not promise byte-identical
external-codec scores or training across hardware.

### Generate embeddings from source text

From the repository root, in the benchmark environment:

```sh
python -m pip install -r benchmarks/requirements-data.txt
python -m benchmarks.prepare_beir \
  --dataset scifact --model e5_small \
  --output benchmarks/data/scifact-e5
python -m benchmarks.prepare_beir \
  --dataset fiqa --model e5_small \
  --output benchmarks/data/fiqa-e5
```

Preparation defaults to CPU. Use `--device cuda` or `--device mps` for an
available GPU, and `--offline` to require cached sources. Output directories
must be new. To evaluate the second model, repeat with `--model bge_small` and
different output paths.

**Expected result:** each directory contains `embeddings.npz` and
`manifest.json`. The NPZ stores corpus/query/fit arrays, ID maps, sparse
relevance triplets and embedded provenance. The manifest also hashes the NPZ.
Relevance triplets refer to query and corpus row positions; they preserve the
original relevance grades without allocating a query-by-corpus label matrix.

The fit array contains the full indexed corpus. This is an explicit
**transductive** setup: trained codecs may learn from documents they will encode,
but do not receive test queries or relevance labels. Do not remove fit documents
from the searched corpus. This protocol does not establish unseen-domain transfer
or absence of benchmark exposure during embedding-model training.

## 2. Evaluate codecs

```sh
python -m pip install -r benchmarks/requirements-faiss.txt
python -m benchmarks.run \
  --config benchmarks/configs/quality-beir.json \
  --data benchmarks/data/scifact-e5/embeddings.npz \
  --output benchmarks/results/scifact-e5
python -m benchmarks.run \
  --config benchmarks/configs/quality-beir.json \
  --data benchmarks/data/fiqa-e5/embeddings.npz \
  --output benchmarks/results/fiqa-e5
python -m benchmarks.render benchmarks/results/scifact-e5/report.json
python -m benchmarks.render benchmarks/results/fiqa-e5/report.json
```

The configuration includes all three SEMQ operators and the benchmark's
four-bin quant baseline,
reduced-precision formats, scalar quantizers and representative Faiss codecs.
TurboQuant MSE and RaBitQ cover nominal two-, three- and four-bit settings.
The actual storage budget includes auxiliary row data and model metadata, so
equal nominal bits are not necessarily equal total storage.
PQ/OPQ use 192 two-coordinate subquantizers with 16 centroids each: 2 nominal
bits per dimension at dimension 384. Their measured storage includes centroids
and rotations. This configuration avoids training 256 centroids per subquantizer
on SciFact's small corpus. It is one reproducible setting, not a tuned optimum
for either dataset.

**Expected result:** separate raw reconstruction, normalized-direction and
native-estimator measurements, with nDCG@10, overlap@10 and counted storage. Native
Faiss estimators score the full corpus in query batches and restore corpus-row
order before shared tie handling. They are not ANN indexes or latency measurements.
orbit remains a coordinate-level control; multibit RaBitQ has no comparable
reconstruction result in this backend.

## 3. Interpret differences

For each scoring profile, compare nDCG against its original-embedding reference.
The report includes a paired query bootstrap interval for the nDCG difference:
2,000 resamples, 95% confidence and a fixed seed. Each resample uses the same
query positions for the codec and reference. Queries without positive judgments
are excluded and counted. These intervals describe query-sampling uncertainty
on this dataset; they do not capture model, dataset or training-seed variability.
They are not corrected for comparisons across multiple codecs.

Overlap measures preservation of FP32 neighbors. nDCG measures agreement with
relevance judgments. Report both: preserving the reference ranking does not
prove that the reference retrieves useful documents. Unjudged documents receive
zero gain under the evaluation convention, not a claim of verified irrelevance.

Keep results for each dataset and model separate. Retain full JSON reports and
input hashes before publishing the interactive results. Public results should identify
the SDK revision, input artifact, model and scoring profile. Do not treat raw
packed-code storage as persisted `.semq` index size.

## 4. Verify and publish

Run the evaluation from a clean checkout of the SDK revision being measured.
Keep input artifacts and full reports locally; tracked public reports contain
aggregate metrics, confidence intervals, configuration and provenance only.

```sh
python -m pip install -r benchmarks/requirements-evaluation.txt
python -m benchmarks.verify_ndcg \
  --report benchmarks/results/scifact-e5/report.json \
  --data benchmarks/data/scifact-e5/embeddings.npz \
  --output benchmarks/results/scifact-e5/verification.json
python -m benchmarks.publish \
  --report benchmarks/results/scifact-e5/report.json \
  --verification benchmarks/results/scifact-e5/verification.json \
  --config benchmarks/configs/quality-beir.json \
  --output docs/assets/benchmarks/scifact-e5-new-revision.json
python -m benchmarks.publish
python -m benchmarks.publish --check
mkdocs build --strict
```

Use a new filename identifying the dataset, model and evaluated revision. The
exporter refuses dirty-source reports, mismatched configurations and verification
evidence from another report. Repeat for the other dataset/model combinations.
Review the generated [results page](benchmark-results.md) and commit it together
with the compact reports. For a refreshed snapshot, remove superseded public
JSON files in the same review; Git retains the earlier snapshot.

The independent evaluator checks the FP32 reference's per-query nDCG against
`trec_eval` in raw and direction profiles using identical rankings. It accepts
integer relevance grades, preserves the benchmark's tie order, and excludes
queries without positive judgments consistently. Tests also cover graded
judgments and tied scores. This verifies metric calculation, not every codec's
ranking implementation. Full reports retain per-query observations for further
analysis; their hashes link them to the compact snapshot.

## Next steps

- [Benchmark protocol](benchmark-protocol.md): metric definitions and report contracts.
- [Retrieval quality and storage](benchmark-results.md): frozen results for both models and datasets.
- [Cost evaluation](cost-evaluation.md): translate measured quantities into declared scenarios.
- [Conformance vectors](https://github.com/The-SEMQ-Group/semq/tree/main/tests/conformance): the codec bytes every binding verifies, separately from model inference.
