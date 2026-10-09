// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

//! Raw FFI declarations for the SEMQ core.
//!
//! Mirrors `include/semq.h` one-to-one: the constants, every enum value,
//! the plain structs, the opaque handles and all exported functions. Nothing
//! here is safe; the `semq` crate builds the safe API on top. The
//! declarations are written by hand so the build needs no libclang; layout
//! tests pin the structs whose size and offsets the ABI depends on.
//!
//! C enums are declared as `u32` aliases with one constant per value. Every
//! function that can fail returns a [`semq_status_t`] and fills the
//! [`semq_error_t`] it is given, when non-null.

#![allow(non_camel_case_types)]

use std::marker::{PhantomData, PhantomPinned};
use std::os::raw::{c_char, c_int};

// --------------------------------------------------------------------------
// Limits and constants
// --------------------------------------------------------------------------

/// File format version written and accepted by this core.
pub const SEMQ_FILE_VERSION: u32 = 2;
/// Operator rule revision written into every config (`p2`).
pub const SEMQ_RULE_REVISION: u32 = 0;
/// Size of the canonical config form in bytes.
pub const SEMQ_CONFIG_BYTES: u32 = 13;
/// Size of each identity (`content_digest`, `state_id`) in bytes.
pub const SEMQ_DIGEST_BYTES: u32 = 32;
/// Largest accepted vector dimension.
pub const SEMQ_MAX_DIM: u32 = 65536;
/// Largest `utf8` id, in bytes. Ids are at least one byte.
pub const SEMQ_ID_MAX_BYTES: u32 = 4096;
/// Manifest limits.
pub const SEMQ_MANIFEST_MAX_PAIRS: u32 = 4096;
pub const SEMQ_MANIFEST_KEY_MAX: u32 = 256;
pub const SEMQ_MANIFEST_VALUE_MAX: u32 = 65536;
pub const SEMQ_MANIFEST_SECTION_MAX: u32 = 16 * 1024 * 1024;
/// Sentinel for "no row" / "no field" in [`semq_error_t`] and index lookups.
pub const SEMQ_NONE: u64 = u64::MAX;

/// Operators. Values are pinned: they appear in the canonical config form.
pub type semq_operator_t = u32;
pub const SEMQ_ORBIT: semq_operator_t = 0;
pub const SEMQ_PHASE: semq_operator_t = 1;
pub const SEMQ_QUANT: semq_operator_t = 2;

/// Identifier kinds. Values are pinned: they appear in files.
pub type semq_id_kind_t = u32;
pub const SEMQ_ID_U64: semq_id_kind_t = 0;
pub const SEMQ_ID_UTF8: semq_id_kind_t = 1;

/// Status codes. Each maps to exactly one host error type.
pub type semq_status_t = u32;
pub const SEMQ_OK: semq_status_t = 0;
/// An argument violates its contract.
pub const SEMQ_ERR_INVALID_INPUT: semq_status_t = 1;
/// Two states differ in config or id kind.
pub const SEMQ_ERR_INCOMPATIBLE: semq_status_t = 2;
/// A file image is not a valid v2 image.
pub const SEMQ_ERR_FORMAT: semq_status_t = 3;
/// A file image's digest does not match.
pub const SEMQ_ERR_INTEGRITY: semq_status_t = 4;
/// The operation or FP environment is not supported.
pub const SEMQ_ERR_UNSUPPORTED: semq_status_t = 5;
/// An allocation failed.
pub const SEMQ_ERR_NOMEM: semq_status_t = 6;
/// A defect in the core; report it.
pub const SEMQ_ERR_INTERNAL: semq_status_t = 7;

/// Which integrity check failed on load.
pub type semq_which_t = u32;
pub const SEMQ_WHICH_NONE: semq_which_t = 0;
pub const SEMQ_WHICH_CONTENT: semq_which_t = 1;
pub const SEMQ_WHICH_STATE: semq_which_t = 2;

/// File sections named by `field` in [`SEMQ_ERR_FORMAT`] errors.
pub type semq_section_t = u32;
pub const SEMQ_SECTION_FRAMING: semq_section_t = 0;
pub const SEMQ_SECTION_CONFIG: semq_section_t = 1;
pub const SEMQ_SECTION_SIZES: semq_section_t = 2;
pub const SEMQ_SECTION_IDS: semq_section_t = 3;
pub const SEMQ_SECTION_MANIFEST: semq_section_t = 4;
pub const SEMQ_SECTION_FOOTER: semq_section_t = 5;
pub const SEMQ_SECTION_ROWS: semq_section_t = 6;

/// Config fields named by `field` in [`SEMQ_ERR_INVALID_INPUT`] errors raised
/// by the config constructors.
pub type semq_config_field_t = u32;
pub const SEMQ_FIELD_OPERATOR: semq_config_field_t = 0;
pub const SEMQ_FIELD_DIM: semq_config_field_t = 1;
/// scale, sectors or bins.
pub const SEMQ_FIELD_P1: semq_config_field_t = 2;
pub const SEMQ_FIELD_P2: semq_config_field_t = 3;

/// Which id list of a Diff an accessor refers to.
pub type semq_list_t = u32;
pub const SEMQ_LIST_ADDED: semq_list_t = 0;
pub const SEMQ_LIST_REMOVED: semq_list_t = 1;
pub const SEMQ_LIST_CHANGED: semq_list_t = 2;

/// Checks beyond those of `semq_diff_within`: flags combined with `|`, for
/// `semq_floor_measure_for` and `semq_diff_evaluate`.
pub type semq_check_t = u32;
pub const SEMQ_CHECK_PER_ROW: semq_check_t = 1;

/// Why a verdict failed: flags combined with `|`.
pub type semq_reason_t = u32;
pub const SEMQ_REASON_NO_COMMON_ROWS: semq_reason_t = 1;
pub const SEMQ_REASON_REMOVED_ROWS: semq_reason_t = 2;
pub const SEMQ_REASON_CHANGED_RATIO: semq_reason_t = 4;
pub const SEMQ_REASON_HAMMING: semq_reason_t = 8;
pub const SEMQ_REASON_ENCODER: semq_reason_t = 16;
pub const SEMQ_REASON_ROW_ABOVE_MAX: semq_reason_t = 32;

// --------------------------------------------------------------------------
// Plain structs
// --------------------------------------------------------------------------

/// Error report. `status` is the returned status; `which` is set only for
/// [`SEMQ_ERR_INTEGRITY`]; `row` and `field` are [`SEMQ_NONE`] when they do
/// not apply. `message` is always NUL-terminated and never contains input
/// data.
#[repr(C)]
#[derive(Debug, Clone, Copy)]
pub struct semq_error_t {
    pub status: u32,
    pub which: u32,
    pub row: u64,
    pub field: u64,
    pub message: [c_char; 128],
}

/// A codec configuration. `op` is a [`semq_operator_t`]; `p1` is `scale`
/// (orbit), `sectors` (phase) or `bins` (quant); `p2` is the rule revision.
#[repr(C)]
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct semq_config_t {
    pub op: u32,
    pub dim: u32,
    pub p1: u32,
    pub p2: u32,
}

/// One manifest pair. Keys and values are UTF-8 bytes, not NUL-terminated.
#[repr(C)]
#[derive(Debug, Clone, Copy)]
pub struct semq_pair_t {
    pub key: *const u8,
    pub key_len: u32,
    pub value: *const u8,
    pub value_len: u32,
}

/// Identifiers of `n` rows, in input order (any order; the core sorts).
/// For [`SEMQ_ID_U64`] pass `u64` (n entries). For [`SEMQ_ID_UTF8`] pass
/// `utf8_offsets` (n + 1 entries, `offsets[0] = 0`, non-decreasing) and
/// `utf8_bytes` (`offsets[n]` bytes): id `i` is `bytes[offsets[i] .. offsets[i+1])`.
#[repr(C)]
#[derive(Debug, Clone, Copy)]
pub struct semq_ids_t {
    pub kind: u32,
    pub n: u64,
    pub u64: *const u64,
    pub utf8_offsets: *const u64,
    pub utf8_bytes: *const u8,
}

/// One borrowed part of the file image.
#[repr(C)]
#[derive(Debug, Clone, Copy)]
pub struct semq_part_t {
    pub ptr: *const u8,
    pub len: u64,
}

/// A change to one manifest key. `has_before`/`has_after` are 0 when the
/// key is absent on that side; the pointers are then NULL.
#[repr(C)]
#[derive(Debug, Clone, Copy)]
pub struct semq_manifest_change_t {
    pub key: *const u8,
    pub key_len: u32,
    pub has_before: c_int,
    pub before: *const u8,
    pub before_len: u32,
    pub has_after: c_int,
    pub after: *const u8,
    pub after_len: u32,
}

// --------------------------------------------------------------------------
// Opaque handles
// --------------------------------------------------------------------------

/// Opaque codec handle (`struct semq_codec`).
#[repr(C)]
pub struct semq_codec_t {
    _data: [u8; 0],
    _marker: PhantomData<(*mut u8, PhantomPinned)>,
}

/// Opaque encoding handle (`struct semq_encoding`).
#[repr(C)]
pub struct semq_encoding_t {
    _data: [u8; 0],
    _marker: PhantomData<(*mut u8, PhantomPinned)>,
}

/// Opaque diff handle (`struct semq_diff`).
#[repr(C)]
pub struct semq_diff_t {
    _data: [u8; 0],
    _marker: PhantomData<(*mut u8, PhantomPinned)>,
}

/// Opaque floor handle (`struct semq_floor`).
#[repr(C)]
pub struct semq_floor_t {
    _data: [u8; 0],
    _marker: PhantomData<(*mut u8, PhantomPinned)>,
}

/// Opaque verdict handle (`struct semq_verdict`).
#[repr(C)]
pub struct semq_verdict_t {
    _data: [u8; 0],
    _marker: PhantomData<(*mut u8, PhantomPinned)>,
}

// --------------------------------------------------------------------------
// Functions (every SEMQ_API declaration in semq.h, in header order)
// --------------------------------------------------------------------------

extern "C" {
    // CodecConfig
    pub fn semq_config_orbit(
        dim: u32,
        scale: u32,
        out: *mut semq_config_t,
        err: *mut semq_error_t,
    ) -> semq_status_t;
    pub fn semq_config_phase(
        dim: u32,
        sectors: u32,
        out: *mut semq_config_t,
        err: *mut semq_error_t,
    ) -> semq_status_t;
    pub fn semq_config_quant(
        dim: u32,
        bins: u32,
        out: *mut semq_config_t,
        err: *mut semq_error_t,
    ) -> semq_status_t;
    pub fn semq_config_validate(cfg: *const semq_config_t, err: *mut semq_error_t)
        -> semq_status_t;
    /// Write the 13-byte canonical form. `cfg` must be valid.
    pub fn semq_config_to_bytes(cfg: *const semq_config_t, out: *mut u8);
    /// Parse a 13-byte canonical form.
    pub fn semq_config_from_bytes(
        input: *const u8,
        out: *mut semq_config_t,
        err: *mut semq_error_t,
    ) -> semq_status_t;
    pub fn semq_config_bytes_per_vector(cfg: *const semq_config_t) -> u32;
    pub fn semq_config_units_per_row(cfg: *const semq_config_t) -> u32;
    /// quant only: `(float)(2.0 / sqrt((double)dim))`; 0 for other operators.
    pub fn semq_config_max_magnitude(cfg: *const semq_config_t) -> f32;
    /// 1 when the two configs have the same canonical bytes.
    pub fn semq_config_equal(a: *const semq_config_t, b: *const semq_config_t) -> c_int;

    // Codec
    pub fn semq_codec_create(
        cfg: *const semq_config_t,
        out: *mut *mut semq_codec_t,
        err: *mut semq_error_t,
    ) -> semq_status_t;
    pub fn semq_codec_free(codec: *mut semq_codec_t);
    pub fn semq_codec_config(codec: *const semq_codec_t) -> *const semq_config_t;
    /// Name of the kernel this codec runs ("scalar", "neon", "avx2", ...).
    pub fn semq_codec_backend(codec: *const semq_codec_t) -> *const c_char;
    pub fn semq_codec_encode(
        codec: *const semq_codec_t,
        ids: *const semq_ids_t,
        vectors: *const f32,
        manifest: *const semq_pair_t,
        n_pairs: u32,
        out: *mut *mut semq_encoding_t,
        err: *mut semq_error_t,
    ) -> semq_status_t;
    /// Representatives, `n x dim` float32, row `i` for `ids[i]`.
    pub fn semq_codec_decode(
        codec: *const semq_codec_t,
        enc: *const semq_encoding_t,
        out: *mut f32,
        err: *mut semq_error_t,
    ) -> semq_status_t;
    /// Symbols, `n x units_per_row` bytes, one per unit.
    pub fn semq_codec_unpack(
        codec: *const semq_codec_t,
        enc: *const semq_encoding_t,
        out: *mut u8,
        err: *mut semq_error_t,
    ) -> semq_status_t;

    // Encoding
    pub fn semq_encoding_create(
        cfg: *const semq_config_t,
        ids: *const semq_ids_t,
        rows: *const u8,
        manifest: *const semq_pair_t,
        n_pairs: u32,
        out: *mut *mut semq_encoding_t,
        err: *mut semq_error_t,
    ) -> semq_status_t;
    pub fn semq_encoding_free(enc: *mut semq_encoding_t);
    pub fn semq_encoding_config(enc: *const semq_encoding_t) -> *const semq_config_t;
    pub fn semq_encoding_id_kind(enc: *const semq_encoding_t) -> u32;
    pub fn semq_encoding_len(enc: *const semq_encoding_t) -> u64;
    /// Rows in id order, `n x bytes_per_vector` bytes.
    pub fn semq_encoding_rows(enc: *const semq_encoding_t, len: *mut u64) -> *const u8;
    /// Sorted ids. `u64` kinds: `n` values.
    pub fn semq_encoding_ids_u64(enc: *const semq_encoding_t) -> *const u64;
    /// `utf8` kinds: `n + 1` offsets.
    pub fn semq_encoding_ids_utf8_offsets(enc: *const semq_encoding_t) -> *const u64;
    /// `utf8` kinds: the id bytes.
    pub fn semq_encoding_ids_utf8_bytes(enc: *const semq_encoding_t, len: *mut u64) -> *const u8;
    /// Manifest pairs in canonical (bytewise key) order.
    pub fn semq_encoding_manifest_len(enc: *const semq_encoding_t) -> u32;
    pub fn semq_encoding_manifest_pair(
        enc: *const semq_encoding_t,
        i: u32,
        out: *mut semq_pair_t,
        err: *mut semq_error_t,
    ) -> semq_status_t;
    pub fn semq_encoding_content_digest(enc: *const semq_encoding_t, out: *mut u8);
    pub fn semq_encoding_state_id(enc: *const semq_encoding_t, out: *mut u8);
    /// Row index of an id, or [`SEMQ_NONE`] when absent.
    pub fn semq_encoding_find_u64(
        enc: *const semq_encoding_t,
        id: u64,
        index: *mut u64,
        err: *mut semq_error_t,
    ) -> semq_status_t;
    pub fn semq_encoding_find_utf8(
        enc: *const semq_encoding_t,
        id: *const u8,
        len: u64,
        index: *mut u64,
        err: *mut semq_error_t,
    ) -> semq_status_t;
    /// Total size of the file image.
    pub fn semq_encoding_file_size(enc: *const semq_encoding_t) -> u64;
    /// The file image as 5 ordered parts owned by the handle. Returns 5.
    pub fn semq_encoding_save_parts(enc: *const semq_encoding_t, parts: *mut semq_part_t) -> u32;
    /// Write the whole file image into `out` (`cap` >= file size).
    pub fn semq_encoding_save(
        enc: *const semq_encoding_t,
        out: *mut u8,
        cap: u64,
        err: *mut semq_error_t,
    ) -> semq_status_t;
    /// Parse a complete file image. The bytes are copied.
    pub fn semq_encoding_load(
        buf: *const u8,
        len: u64,
        out: *mut *mut semq_encoding_t,
        err: *mut semq_error_t,
    ) -> semq_status_t;
    /// Merge `k` Encodings with the same config, id kind and manifest and
    /// pairwise-disjoint ids.
    pub fn semq_encoding_concat(
        parts: *const *const semq_encoding_t,
        k: u32,
        out: *mut *mut semq_encoding_t,
        err: *mut semq_error_t,
    ) -> semq_status_t;
    /// `reference.diff(candidate)`.
    pub fn semq_encoding_diff(
        reference: *const semq_encoding_t,
        candidate: *const semq_encoding_t,
        out: *mut *mut semq_diff_t,
        err: *mut semq_error_t,
    ) -> semq_status_t;

    // Diff
    /// The Diff keeps both Encodings alive until it is freed.
    pub fn semq_diff_free(diff: *mut semq_diff_t);
    pub fn semq_diff_config(diff: *const semq_diff_t) -> *const semq_config_t;
    pub fn semq_diff_id_kind(diff: *const semq_diff_t) -> u32;
    pub fn semq_diff_reference_id(diff: *const semq_diff_t, out: *mut u8);
    pub fn semq_diff_candidate_id(diff: *const semq_diff_t, out: *mut u8);
    pub fn semq_diff_count(diff: *const semq_diff_t, list: u32) -> u64;
    pub fn semq_diff_n_unchanged(diff: *const semq_diff_t) -> u64;
    /// Id `i` of a list, in canonical order. For `u64` kinds `*out_u64` is
    /// set; for `utf8` kinds `*bytes`/`*len` are set.
    pub fn semq_diff_id(
        diff: *const semq_diff_t,
        list: u32,
        i: u64,
        out_u64: *mut u64,
        bytes: *mut *const u8,
        len: *mut u64,
        err: *mut semq_error_t,
    ) -> semq_status_t;
    /// Hamming distance of changed id `i` (units whose symbol differs).
    pub fn semq_diff_hamming(
        diff: *const semq_diff_t,
        i: u64,
        out: *mut u64,
        err: *mut semq_error_t,
    ) -> semq_status_t;
    pub fn semq_diff_manifest_changes(diff: *const semq_diff_t) -> u32;
    pub fn semq_diff_manifest_change(
        diff: *const semq_diff_t,
        i: u32,
        out: *mut semq_manifest_change_t,
        err: *mut semq_error_t,
    ) -> semq_status_t;
    /// Differing units of an id present on both sides. Writes up to `cap`
    /// entries and the total count into `*count`. Pass `cap = 0` to query.
    pub fn semq_diff_units_u64(
        diff: *const semq_diff_t,
        id: u64,
        units: *mut u32,
        ref_symbols: *mut u8,
        cand_symbols: *mut u8,
        cap: u64,
        count: *mut u64,
        err: *mut semq_error_t,
    ) -> semq_status_t;
    pub fn semq_diff_units_utf8(
        diff: *const semq_diff_t,
        id: *const u8,
        len: u64,
        units: *mut u32,
        ref_symbols: *mut u8,
        cand_symbols: *mut u8,
        cap: u64,
        count: *mut u64,
        err: *mut semq_error_t,
    ) -> semq_status_t;

    // Floor
    /// A floor from its fields. `config` must validate, `id_kind` must be
    /// 0 or 1, `reference_id` is 32 bytes, `nulls >= 1`, `total_rows >= 1`,
    /// `changed_rows <= total_rows` and `hamming <= units_per_row(config)`;
    /// otherwise `SEMQ_ERR_INVALID_INPUT`.
    pub fn semq_floor_create(
        config: *const semq_config_t,
        id_kind: u32,
        reference_id: *const u8,
        nulls: u64,
        changed_rows: u64,
        total_rows: u64,
        hamming: u64,
        out: *mut *mut semq_floor_t,
        err: *mut semq_error_t,
    ) -> semq_status_t;
    pub fn semq_floor_free(floor: *mut semq_floor_t);
    /// Envelope of `k >= 1` null diffs; every input diff is within the
    /// result. All nulls must share config, id kind and reference state_id
    /// (`SEMQ_ERR_INCOMPATIBLE`, `field` = the offending index) and each
    /// must be a valid null (`SEMQ_ERR_INVALID_INPUT`, `field` = index).
    pub fn semq_floor_measure(
        nulls: *const *const semq_diff_t,
        k: u32,
        out: *mut *mut semq_floor_t,
        err: *mut semq_error_t,
    ) -> semq_status_t;
    /// `semq_floor_measure` that also records what the `checks`
    /// (`SEMQ_CHECK_*` flags) need: with `SEMQ_CHECK_PER_ROW`, `max_hamming`
    /// and `distinct_nulls`. An unknown bit is `SEMQ_ERR_INVALID_INPUT`.
    pub fn semq_floor_measure_for(
        nulls: *const *const semq_diff_t,
        k: u32,
        checks: u32,
        out: *mut *mut semq_floor_t,
        err: *mut semq_error_t,
    ) -> semq_status_t;
    /// The config, owned by the handle.
    pub fn semq_floor_config(floor: *const semq_floor_t) -> *const semq_config_t;
    /// 0 = u64, 1 = utf8.
    pub fn semq_floor_id_kind(floor: *const semq_floor_t) -> u32;
    /// Writes the 32-byte state_id of the reference into `out`.
    pub fn semq_floor_reference_id(floor: *const semq_floor_t, out: *mut u8);
    pub fn semq_floor_nulls(floor: *const semq_floor_t) -> u64;
    pub fn semq_floor_changed_rows(floor: *const semq_floor_t) -> u64;
    pub fn semq_floor_total_rows(floor: *const semq_floor_t) -> u64;
    pub fn semq_floor_hamming(floor: *const semq_floor_t) -> u64;
    /// `SEMQ_NONE` for a floor without per-row data.
    pub fn semq_floor_max_hamming(floor: *const semq_floor_t) -> u64;
    /// Distinct null states among the nulls; `SEMQ_NONE` when not recorded.
    pub fn semq_floor_distinct_nulls(floor: *const semq_floor_t) -> u64;
    /// Length in bytes of the floor's JSON form.
    pub fn semq_floor_json_size(floor: *const semq_floor_t) -> u64;
    /// Writes the floor's JSON form into `out` (`cap >= semq_floor_json_size`).
    pub fn semq_floor_save(
        floor: *const semq_floor_t,
        out: *mut u8,
        cap: u64,
        err: *mut semq_error_t,
    ) -> semq_status_t;
    /// Reads a floor from its JSON form; strict on the schema's keys, other
    /// keys ignored. `SEMQ_ERR_INVALID_INPUT` on any violation.
    pub fn semq_floor_load(
        buf: *const u8,
        len: u64,
        out: *mut *mut semq_floor_t,
        err: *mut semq_error_t,
    ) -> semq_status_t;
    /// `*out = 1` iff the diff is within the floor (exact integer
    /// arithmetic). The floor must match the diff's config, id kind and
    /// reference state_id (`SEMQ_ERR_INCOMPATIBLE` otherwise).
    pub fn semq_diff_within(
        diff: *const semq_diff_t,
        floor: *const semq_floor_t,
        out: *mut c_int,
        err: *mut semq_error_t,
    ) -> semq_status_t;

    // Gate evaluation
    /// With `checks == 0`, `passed` equals `semq_diff_within`; an unknown
    /// bit is `SEMQ_ERR_INVALID_INPUT`. `SEMQ_ERR_INCOMPATIBLE` for a floor of
    /// another context, or for `SEMQ_CHECK_PER_ROW` on a floor without
    /// `max_hamming`.
    pub fn semq_diff_evaluate(
        diff: *const semq_diff_t,
        floor: *const semq_floor_t,
        checks: u32,
        out: *mut *mut semq_verdict_t,
        err: *mut semq_error_t,
    ) -> semq_status_t;
    pub fn semq_verdict_free(verdict: *mut semq_verdict_t);
    pub fn semq_verdict_passed(verdict: *const semq_verdict_t) -> c_int;
    /// `SEMQ_REASON_*` flags; 0 when the verdict passed.
    pub fn semq_verdict_reasons(verdict: *const semq_verdict_t) -> u32;
    pub fn semq_verdict_row_count(verdict: *const semq_verdict_t) -> u64;
    /// Index in the diff's changed list; `SEMQ_NONE` when out of range.
    pub fn semq_verdict_row(verdict: *const semq_verdict_t, i: u64) -> u64;

    // Build information and utilities
    /// Core version string, from the repository `VERSION` file.
    pub fn semq_core_version() -> *const c_char;
    /// Compile-time build recipe identifier. Not a provenance proof.
    pub fn semq_build_id() -> *const c_char;
    /// Effective kernel for an operator on this host ("scalar", "neon", ...).
    pub fn semq_backend_name(op: u32) -> *const c_char;
    /// Static name of a status code ("ok", "invalid_input", ...).
    pub fn semq_status_name(status: u32) -> *const c_char;
    /// SHA-256 (FIPS 180-4) of `len` bytes.
    pub fn semq_sha256(data: *const u8, len: u64, out: *mut u8);
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::ffi::CStr;
    use std::mem::{align_of, offset_of, size_of};

    /// `semq_error_t` is `u32, u32, u64, u64, char[128]`: 152 bytes.
    #[test]
    fn error_layout_matches_the_abi() {
        assert_eq!(size_of::<semq_error_t>(), 152);
        assert_eq!(align_of::<semq_error_t>(), 8);
        assert_eq!(offset_of!(semq_error_t, status), 0);
        assert_eq!(offset_of!(semq_error_t, which), 4);
        assert_eq!(offset_of!(semq_error_t, row), 8);
        assert_eq!(offset_of!(semq_error_t, field), 16);
        assert_eq!(offset_of!(semq_error_t, message), 24);
    }

    /// `semq_config_t` is four `u32`: 16 bytes.
    #[test]
    fn config_layout_matches_the_abi() {
        assert_eq!(size_of::<semq_config_t>(), 16);
        assert_eq!(align_of::<semq_config_t>(), 4);
        assert_eq!(offset_of!(semq_config_t, op), 0);
        assert_eq!(offset_of!(semq_config_t, dim), 4);
        assert_eq!(offset_of!(semq_config_t, p1), 8);
        assert_eq!(offset_of!(semq_config_t, p2), 12);
    }

    /// Pointer-bearing structs, on 64-bit hosts (the core's target).
    #[cfg(target_pointer_width = "64")]
    #[test]
    fn pointer_struct_layouts_match_the_abi() {
        assert_eq!(size_of::<semq_pair_t>(), 32);
        assert_eq!(offset_of!(semq_pair_t, key), 0);
        assert_eq!(offset_of!(semq_pair_t, key_len), 8);
        assert_eq!(offset_of!(semq_pair_t, value), 16);
        assert_eq!(offset_of!(semq_pair_t, value_len), 24);

        assert_eq!(size_of::<semq_ids_t>(), 40);
        assert_eq!(offset_of!(semq_ids_t, kind), 0);
        assert_eq!(offset_of!(semq_ids_t, n), 8);
        assert_eq!(offset_of!(semq_ids_t, u64), 16);
        assert_eq!(offset_of!(semq_ids_t, utf8_offsets), 24);
        assert_eq!(offset_of!(semq_ids_t, utf8_bytes), 32);

        assert_eq!(size_of::<semq_part_t>(), 16);
        assert_eq!(offset_of!(semq_part_t, ptr), 0);
        assert_eq!(offset_of!(semq_part_t, len), 8);

        assert_eq!(size_of::<semq_manifest_change_t>(), 48);
        assert_eq!(offset_of!(semq_manifest_change_t, key), 0);
        assert_eq!(offset_of!(semq_manifest_change_t, key_len), 8);
        assert_eq!(offset_of!(semq_manifest_change_t, has_before), 12);
        assert_eq!(offset_of!(semq_manifest_change_t, before), 16);
        assert_eq!(offset_of!(semq_manifest_change_t, before_len), 24);
        assert_eq!(offset_of!(semq_manifest_change_t, has_after), 28);
        assert_eq!(offset_of!(semq_manifest_change_t, after), 32);
        assert_eq!(offset_of!(semq_manifest_change_t, after_len), 40);
    }

    /// The library links and the simplest entry points answer as the header
    /// documents: a quant(4, 4) config and its canonical form.
    #[test]
    fn core_links_and_answers() {
        let version = unsafe { CStr::from_ptr(semq_core_version()) };
        assert!(!version.to_bytes().is_empty());

        let mut cfg = semq_config_t {
            op: 0,
            dim: 0,
            p1: 0,
            p2: 0,
        };
        let status = unsafe { semq_config_quant(4, 4, &mut cfg, std::ptr::null_mut()) };
        assert_eq!(status, SEMQ_OK);
        assert_eq!(
            cfg,
            semq_config_t {
                op: SEMQ_QUANT,
                dim: 4,
                p1: 4,
                p2: SEMQ_RULE_REVISION
            }
        );
        let mut bytes = [0u8; 13];
        unsafe { semq_config_to_bytes(&cfg, bytes.as_mut_ptr()) };
        assert_eq!(bytes, [2, 4, 0, 0, 0, 4, 0, 0, 0, 0, 0, 0, 0]);

        let name = unsafe { CStr::from_ptr(semq_status_name(SEMQ_ERR_INVALID_INPUT)) };
        assert_eq!(name.to_str().unwrap(), "invalid_input");
    }
}
