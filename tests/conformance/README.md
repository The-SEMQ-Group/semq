# Conformance vectors

One directory per vector, `NN-name/`, each with a `manifest.json` of cases
and the binary files the cases reference. They pin every contract that
determines bytes or verdicts: SHA-256, the canonical config form and its
derived quantities, the symbol mapping and packing of the three operators,
the input contract, representatives, ids, manifests, the two identities,
the file image and its reader, `concat`, `diff`, `Floor` and the report
schema, and the floating-point environment.

## Who produces what

- `semq_vectors.c`, built with the library's tests (`-DSEMQ_BUILD_TESTS=ON`),
  is the only generator. It writes the directories from the same sources as
  the core and checks the kernel-level properties no host can reach: the
  fixed point `kernel_encode(decode(row)) == row` (vector 5) and byte
  identity under FZ/DAZ (vector 15).
- `reference.py` is a pure-Python implementation of the non-kernel contracts
  (canonical forms, identities, file image, `concat`, `diff`, `Floor`). It
  recomputes the expectations from the inputs so the core never verifies
  itself on them.
- `test_conformance.py` is the Python host runner. Every host has one; it
  executes each case through the public surface only.

## The gate

`tools/conformance.py <generator>` regenerates the vectors into a scratch
directory, runs the reference, and compares with this directory. CI runs it
on every architecture of the matrix; a byte or verdict difference fails the
build. Regenerate with `--update` only together with a bump of
`SEMQ_FILE_VERSION` (framing) or of the operator rule revision (rules), or
with a change to the [floor schema](../../docs/reference/contracts.md#floor-schema),
in the same pull request, and review the diff of the regenerated files like
code.

Adding cases also takes `--update`, provided that no existing case and no
existing file changes.

## Case format

Float32 inputs are `.f32` files (little-endian) with a `shape`, or arrays of
hex bit patterns for small cases. Ids are `{"kind": "u64" | "utf8",
"values": [...]}` with `u64` values as decimal strings. Bytes and digests
are lowercase hex. Expected errors are `{"error", "row", "field", "which"}`.
Cases marked `host` describe representation checks a host performs before
the core sees the input.

## Real embeddings

The vectors above are synthetic by design. The
[reproducibility fixture](../reproducibility/README.md) adds 1,000 real
embeddings and their expected identities under the five published
configurations; every binding checks it on every platform of the CI matrix.
