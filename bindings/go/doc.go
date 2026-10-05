// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

// Package semq binds the SEMQ core: deterministic symbolic encoding of
// float32 vectors with content-addressed identities.
//
// The core owns every rule that determines bytes or verdicts; this package
// validates Go representations, maps errors and does I/O. Five types and one
// query:
//
//   - CodecConfig: the rule (Quant, Phase or Orbit), a comparable value.
//   - Codec: encodes unit-norm float32 vectors into an Encoding.
//   - Encoding: sorted ids, one canonical row each, a manifest and two
//     identities; Load/Read, WriteTo/Bytes, Concat and Diff.
//   - Diff: added, removed and changed ids with hamming distances, manifest
//     changes, Units, Within and Report.
//   - Floor: the envelope of variation observed in null diffs of one
//     reference (MeasureFloor), bound to that config, id kind and reference;
//     Report and FloorFromReport are its report form and strict inverse.
//   - BuildInfo from Info.
//
// Errors are six types matched with errors.As: *InvalidInputError,
// *IncompatibleError, *FormatError, *IntegrityError, *UnsupportedError and
// *NativeError. Allocation failure wraps ErrNoMemory (errors.Is).
//
// Codec, Encoding, Diff and Floor hold native handles: immutable after
// construction, safe for concurrent use, released with Close (idempotent,
// with a finalizer as fallback). Accessors return copies.
//
// The module includes the C core (internal/core), which cgo compiles and
// links statically; no native library is installed separately.
package semq
