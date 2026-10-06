# SEMQ

**Deterministic symbolic states for float32 vectors.**

[![test](https://github.com/The-SEMQ-Group/semq/actions/workflows/test.yml/badge.svg)](https://github.com/The-SEMQ-Group/semq/actions/workflows/test.yml)
[![docs](https://github.com/The-SEMQ-Group/semq/actions/workflows/docs.yml/badge.svg)](https://github.com/The-SEMQ-Group/semq/actions/workflows/docs.yml)
[![license](https://img.shields.io/badge/license-PolyForm%20Noncommercial%201.0.0-blue.svg)](https://github.com/The-SEMQ-Group/semq/blob/main/LICENSE.md)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://github.com/The-SEMQ-Group/semq/tree/main/bindings/python)
[![Rust](https://img.shields.io/badge/Rust-binding-000000?logo=rust&logoColor=white)](https://github.com/The-SEMQ-Group/semq/blob/main/bindings/rust/semq/README.md)
[![Go](https://img.shields.io/badge/Go-binding-00ADD8?logo=go&logoColor=white)](https://github.com/The-SEMQ-Group/semq/tree/main/bindings/go)
[![TypeScript](https://img.shields.io/badge/TypeScript%2FWASM-binding-3178C6?logo=typescript&logoColor=white)](https://github.com/The-SEMQ-Group/semq/tree/main/bindings/ts)

When you re-embed a corpus (new GPU, new batch size, a library bump, a
model update), you need to know whether anything actually changed, and
if so, _where_ it changed. SEMQ turns unit-norm `float32` vectors produced by your embedding or
feature pipeline into compact symbolic rows kept under your ids, with an
identity for the whole state derived from the rows themselves (a SHA-256).
You can measure your pipeline's own rebuild noise (via Floor)
and diff new builds against it row by row, so rebuild noise passes and real changes fail with
identical results in every binding and on every architecture.

A hash of the raw floats tells you whether the bytes changed, not whether the
state did. A rebuild on another device or with another batch size never
produces the same bytes, so a float hash fires on every rebuild and says
nothing about where. SEMQ encodes each vector as a few quantized symbols, so
rebuild noise below the bin width leaves the rows and their `state_id`
unchanged; for the rows that do move, `diff` against a floor measured on your
own null rebuilds tells noise from change, row by row.

Build with our Python, Rust, Go, and TypeScript/WASM bindings, or call the C core directly.

SEMQ does not generate embeddings, train a model, normalize vectors, or
search. The input is unit-norm, finite `float32`.

## What the SDK provides

| Need | SEMQ capability |
| --- | --- |
| Compact representation | quant, phase and orbit operators, one `CodecConfig` each |
| A state with an identity | `Encoding`: sorted ids, canonical rows, a manifest, `content_digest` and `state_id` |
| Persistence | The `.semq` file format, validated on load before any allocation |
| Change detection | `Diff`: added, removed and changed rows with hamming distances |
| A rebuild gate | `Floor` measured from null rebuilds (the unchanged corpus encoded again) and bound to its reference; `semq diff --floor` |
| Deployment targets | Python, Rust, Go, and TypeScript/WebAssembly |

The bytes and verdicts are pinned by the shared
[conformance vectors](https://github.com/The-SEMQ-Group/semq/blob/main/tests/conformance/README.md).

## Where it fits

```text
embedding model → float32 unit-norm vectors → SEMQ state (.semq) → diff, floor, verdict
```

## Install

Install the binding for your language from its registry:

```sh
pip install semq                                    # Python 3.11+
cargo add semq                                      # Rust 1.77+
go get github.com/The-SEMQ-Group/semq/bindings/go   # Go 1.21+, with cgo
npm install @semq/sdk                               # Node.js 22+ or a browser bundler
```

The Python wheels and the npm package include the compiled core, so they need
no compiler. The Rust crate and the Go module compile the core they carry,
which needs a C compiler; Rust also needs CMake 3.20+. See
[Installation](https://github.com/The-SEMQ-Group/semq/blob/main/docs/installation.md)
for each language, and [CONTRIBUTING](https://github.com/The-SEMQ-Group/semq/blob/main/CONTRIBUTING.md)
to build from a clone of this repository.

## Encode, save and compare

Three embeddings of dimension 4 under your own ids, no model or dataset
needed. Encode them, save the state, load it back and diff it against a
rebuild in which `doc-3` changed:

```python
import numpy as np
from semq import Codec, Encoding

vectors = np.array([
    [0.6, 0.8, 0.0, 0.0],
    [0.0, 0.6, 0.8, 0.0],
    [0.0, 0.0, 0.6, 0.8],
], dtype=np.float32)
ids = ["doc-1", "doc-2", "doc-3"]
manifest = {"encoder": "example-encoder", "encoder_revision": "1"}

codec = Codec.quant(dim=4, bins=4)
codec.encode(vectors, ids=ids, manifest=manifest).save("corpus.semq")

reference = Encoding.load("corpus.semq")
print(reference)

rebuilt = vectors.copy()
rebuilt[2] = [0.8, 0.0, 0.0, 0.6]  # doc-3 changed
print(reference.diff(codec.encode(rebuilt, ids=ids, manifest=manifest)))
```

Expected output:

```text
Encoding(3 rows, quant(dim=4, bins=4), state_id 6e6f8a89bae4...)
1 of 3 rows changed: doc-3 (hamming 3). 0 added, 0 removed.
```

`diff.as_dict()` is the machine-readable
[report](https://github.com/The-SEMQ-Group/semq/blob/main/docs/reference/contracts.md#report-schema). To tell a change like
this from the noise of a rebuild that changed nothing, measure a floor from
null rebuilds and gate against it: the [quickstart](https://github.com/The-SEMQ-Group/semq/blob/main/docs/quickstart.md) does
that in four languages, and [Gate a rebuild](https://github.com/The-SEMQ-Group/semq/blob/main/docs/guides/gate-a-rebuild.md)
from the command line.

## Documentation

Read the [SDK documentation site](https://the-semq-group.github.io/semq/) or
browse its [source landing page](https://github.com/The-SEMQ-Group/semq/blob/main/docs/index.md).

| Task | Start here |
| --- | --- |
| Understand states, identities, diffs and floors | [Concepts](https://github.com/The-SEMQ-Group/semq/blob/main/docs/concepts.md) |
| Gate an embedding rebuild | [Gate a rebuild](https://github.com/The-SEMQ-Group/semq/blob/main/docs/guides/gate-a-rebuild.md), [CLI](https://github.com/The-SEMQ-Group/semq/blob/main/docs/reference/cli.md) |
| Choose a configuration | [Configuration guide](https://github.com/The-SEMQ-Group/semq/blob/main/docs/guides/choosing-a-config.md) |
| Look up a binding operation | [API reference](https://github.com/The-SEMQ-Group/semq/blob/main/docs/reference/index.md) |
| Read the byte and verdict contracts | [Core contracts](https://github.com/The-SEMQ-Group/semq/blob/main/docs/reference/contracts.md), [file format](https://github.com/The-SEMQ-Group/semq/blob/main/docs/reference/file-format.md) |
| Compare measured quality and storage | [Benchmark overview](https://github.com/The-SEMQ-Group/semq/blob/main/docs/benchmarks/index.md) |
| Check the bytes every binding must produce | [Conformance vectors](https://github.com/The-SEMQ-Group/semq/blob/main/tests/conformance/README.md) |
| Upgrade an installation | [Compatibility and migration](https://github.com/The-SEMQ-Group/semq/blob/main/docs/compatibility.md), [changelog](https://github.com/The-SEMQ-Group/semq/blob/main/CHANGELOG.md) |
| Contribute or maintain the SDK | [Contributor guide](https://github.com/The-SEMQ-Group/semq/blob/main/CONTRIBUTING.md) |
| Report a vulnerability | [Security policy](https://github.com/The-SEMQ-Group/semq/blob/main/SECURITY.md) |

## License and community

The SDK is licensed under the [PolyForm Noncommercial License 1.0.0](https://github.com/The-SEMQ-Group/semq/blob/main/LICENSE.md).
Production use by companies, and any other use the license does not permit,
requires a separate license from The SEMQ Group Inc.; write to
**licensing@thesemqgroup.ai**. The [licensing FAQ](https://www.thesemqgroup.ai/licensing)
answers common questions about permitted use.
See [NOTICE](https://github.com/The-SEMQ-Group/semq/blob/main/NOTICE) for the required notice and the
[Code of Conduct](https://github.com/The-SEMQ-Group/semq/blob/main/CODE_OF_CONDUCT.md) for community expectations. The npm
package also includes the third-party components listed in
[THIRD_PARTY_LICENSES](https://github.com/The-SEMQ-Group/semq/blob/main/THIRD_PARTY_LICENSES).
