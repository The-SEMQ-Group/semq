# Reproducibility fixture

1,000 real embeddings and the identities SEMQ must give them in every binding
and on every platform. Each binding has a test that reads these files with its
own IO, encodes them with its own `Codec` and compares `content_digest`,
`state_id` and the SHA-256 of the saved `.semq` file with `expected.json`:

| binding | test |
| --- | --- |
| Python | `tests/reproducibility/test_reproducibility.py` |
| Rust | `bindings/rust/semq/tests/reproducibility.rs` |
| Go | `bindings/go/reproducibility_test.go` |
| TypeScript (wasm) | `bindings/ts/test/reproducibility.test.ts` |

## Files

- `vectors.f32`: 1,000 x 384 float32, little-endian, row-major (1,536,000
  bytes). The first 1,000 rows of the `corpus` array of the frozen SciFact
  e5-small-v2 archive (`~/.cache/semq-benchmarks/scifact-e5/embeddings.npz`,
  sha256 `1de0ad4e829851fcbae4af37658b8d4ccdfdd4bb1e3a07a35a68f077893d0f94`,
  produced by `benchmarks/prepare_beir.py`), in lexical document id order.
  Every row passes SEMQ's admission rule (`|s - 1| <= 2^-10`, `s` summed in
  binary64 in index order); the largest deviation is `2.2e-7`.
- `ids.json`: the BEIR document ids of those rows as UTF-8 strings, in row
  order, with the source file and its sha256.
- `expected.json`: for each configuration of the benchmark page
  (`semq_quant2`, `semq_quant4`, `semq_quant8`, `semq_phase16`,
  `semq_orbit50`), with the manifest `{"encoder": "intfloat/e5-small-v2",
  "encoder_revision": "ffb93f3bd4047442299a41ebb6fa998a38507c52"}` and id kind
  `utf8`: `content_digest`, `state_id`, the file size and the file's sha256,
  computed with the Python binding.

Regenerate all three with
`python -m benchmarks.reproducibility --build-fixture ~/.cache/semq-benchmarks/scifact-e5/embeddings.npz`
and check them with `python -m benchmarks.reproducibility --check`. A change
of any expected value is a change of the byte contract and needs the same
review as the conformance vectors.

## License

These embeddings are derived from SciFact (David Wadden et al., "Fact or
Fiction: Verifying Scientific Claims", 2020; distributed through BEIR,
https://huggingface.co/datasets/BeIR/scifact at revision
`b3b5335604bf5ee3c4447671af975ea25143d4f5`) with the MIT-licensed model
`intfloat/e5-small-v2` at revision `ffb93f3bd4047442299a41ebb6fa998a38507c52`
(document titles and text joined with a space, `passage: ` prefix, 512-token
truncation, L2-normalized float32). The source identifies its license as
CC BY-SA 4.0, and these derived data are distributed under CC BY-SA 4.0
(https://creativecommons.org/licenses/by-sa/4.0/), separately from the SDK
code. They contain no document text and no model weights. No endorsement by
the dataset or model authors is implied.
