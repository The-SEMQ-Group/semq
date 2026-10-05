// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

//! Floor: how much changes without a cause, bound to where it was measured.

use std::fmt;
use std::hash::{Hash, Hasher};
use std::ptr::{self, NonNull};

use semq_sys as sys;

use crate::config::CodecConfig;
use crate::convert::{hex, FreeOnDrop};
use crate::diff::Diff;
use crate::error::{check, new_error, Error, Result};
use crate::ids::{ptr_or_null, IdKind};

/// An envelope of observed variation, bound to the context it was measured
/// in: the config, the id kind and the `state_id` of the reference every
/// null diff was taken against.
///
/// A diff is within the floor when it shares at least one row with its
/// reference, removes none, changes at most `changed_rows / total_rows` of
/// the shared rows, its p99 hamming does not exceed `hamming`, and it
/// changes neither `encoder` nor `encoder_revision`. Applying a floor to a
/// diff of another config, id kind or reference is `Incompatible`. No
/// probabilistic coverage is claimed.
///
/// Immutable, freed on drop and safe to share between threads. Equality
/// and hashing are those of the seven fields.
pub struct Floor {
    ptr: NonNull<sys::semq_floor_t>,
    config: CodecConfig,
    id_kind: IdKind,
}

// SAFETY: a floor is immutable after construction and the core keeps no
// global or thread-local state, so sharing and moving it is sound.
unsafe impl Send for Floor {}
unsafe impl Sync for Floor {}

impl Drop for Floor {
    fn drop(&mut self) {
        // SAFETY: the handle came from the core and is freed once.
        unsafe { sys::semq_floor_free(self.ptr.as_ptr()) }
    }
}

impl Floor {
    /// A floor from its fields: `nulls >= 1`, `total_rows >= 1`,
    /// `changed_rows <= total_rows` and `hamming <= config.units_per_row()`,
    /// else `InvalidInput`. `reference_id` is the `state_id` of the
    /// reference the floor applies to.
    pub fn new(
        config: &CodecConfig,
        id_kind: IdKind,
        reference_id: [u8; 32],
        nulls: u64,
        changed_rows: u64,
        total_rows: u64,
        hamming: u64,
    ) -> Result<Floor> {
        let mut out: *mut sys::semq_floor_t = ptr::null_mut();
        let mut err = new_error();
        // SAFETY: the config is a validated struct, `reference_id` holds 32
        // readable bytes and every out-pointer is live for the call.
        let status = unsafe {
            sys::semq_floor_create(
                config.as_raw(),
                id_kind.as_raw(),
                reference_id.as_ptr(),
                nulls,
                changed_rows,
                total_rows,
                hamming,
                &mut out,
                &mut err,
            )
        };
        check(status, &err, "floor")?;
        Self::from_raw(out, "floor")
    }

    /// The envelope of one or more null diffs of one reference; every input
    /// is within the result. The diffs must share config, id kind and
    /// reference (`Incompatible`, `field` = the index of the offending
    /// diff), and each must be a valid null: it shares at least one row
    /// with its reference, adds and removes nothing, and leaves `encoder`
    /// and `encoder_revision` unchanged (`InvalidInput`, `field` = index).
    ///
    /// Takes any iterable of diffs: a `Vec<Diff>` or a slice by reference,
    /// `[&d1, &d2]`, or an iterator.
    pub fn measure<D: AsRef<Diff>>(null_diffs: impl IntoIterator<Item = D>) -> Result<Floor> {
        // Hold every item until the call returns: an owned Diff dropped while
        // collecting pointers would free the handle the core is about to read.
        let diffs: Vec<D> = null_diffs.into_iter().collect();
        let ptrs: Vec<*const sys::semq_diff_t> =
            diffs.iter().map(|d| d.as_ref().as_ptr()).collect();
        let k = u32::try_from(ptrs.len())
            .map_err(|_| Error::invalid("measure takes fewer than 2^32 diffs"))?;
        let mut out: *mut sys::semq_floor_t = ptr::null_mut();
        let mut err = new_error();
        // SAFETY: `diffs` keeps every handle alive for the call; the array
        // holds `k` pointers; the out-pointers are live for the call.
        let status = unsafe { sys::semq_floor_measure(ptr_or_null(&ptrs), k, &mut out, &mut err) };
        drop(diffs);
        check(status, &err, "measure")?;
        Self::from_raw(out, "measure")
    }

    /// Take ownership of a handle the core just produced.
    fn from_raw(ptr: *mut sys::semq_floor_t, operation: &'static str) -> Result<Floor> {
        let ptr = NonNull::new(ptr).ok_or_else(|| {
            Error::native(
                operation,
                sys::SEMQ_ERR_INTERNAL,
                None,
                None,
                "core returned a null floor",
            )
        })?;
        let guard = FreeOnDrop::new(ptr, sys::semq_floor_free);
        // SAFETY: the handle is live and owns the config it points to.
        let raw = unsafe { *sys::semq_floor_config(guard.ptr()) };
        let config = CodecConfig::from_raw(raw, operation)?;
        // SAFETY: the handle is live.
        let kind = unsafe { sys::semq_floor_id_kind(guard.ptr()) };
        let id_kind = IdKind::from_raw(kind).ok_or_else(|| {
            Error::native(
                operation,
                sys::SEMQ_ERR_INTERNAL,
                None,
                None,
                "floor has an unknown id kind",
            )
        })?;
        Ok(Floor {
            ptr: guard.release(),
            config,
            id_kind,
        })
    }

    pub(crate) fn as_ptr(&self) -> *const sys::semq_floor_t {
        self.ptr.as_ptr()
    }

    /// The config the nulls were measured under.
    pub fn config(&self) -> &CodecConfig {
        &self.config
    }

    /// The id kind of the nulls.
    pub fn id_kind(&self) -> IdKind {
        self.id_kind
    }

    /// The `state_id` of the reference every null was taken against.
    pub fn reference_id(&self) -> [u8; 32] {
        let mut out = [0u8; 32];
        // SAFETY: the handle is live and `out` has room for 32 bytes.
        unsafe { sys::semq_floor_reference_id(self.ptr.as_ptr(), out.as_mut_ptr()) };
        out
    }

    /// How many null diffs the floor was measured from.
    pub fn nulls(&self) -> u64 {
        // SAFETY: the handle is live.
        unsafe { sys::semq_floor_nulls(self.ptr.as_ptr()) }
    }

    /// Numerator of the admitted fraction of changed rows.
    pub fn changed_rows(&self) -> u64 {
        // SAFETY: the handle is live.
        unsafe { sys::semq_floor_changed_rows(self.ptr.as_ptr()) }
    }

    /// Denominator of the admitted fraction of changed rows.
    pub fn total_rows(&self) -> u64 {
        // SAFETY: the handle is live.
        unsafe { sys::semq_floor_total_rows(self.ptr.as_ptr()) }
    }

    /// Largest admitted p99 hamming distance over changed rows.
    pub fn hamming(&self) -> u64 {
        // SAFETY: the handle is live.
        unsafe { sys::semq_floor_hamming(self.ptr.as_ptr()) }
    }

    /// The `semq-floor/1` report as plain data, ready for any serializer.
    pub fn as_report(&self) -> FloorReport {
        FloorReport {
            version: FloorReport::VERSION.to_owned(),
            config: self.config,
            id_kind: self.id_kind.name().to_owned(),
            reference_id: hex(&self.reference_id()),
            nulls: self.nulls(),
            changed_rows: self.changed_rows(),
            total_rows: self.total_rows(),
            hamming: self.hamming(),
        }
    }

    /// The inverse of [`as_report`](Self::as_report), strictly: `version`
    /// must be [`FloorReport::VERSION`], `id_kind` `"u64"` or `"utf8"`,
    /// `reference_id` 64 hex characters, and the counts must satisfy
    /// [`new`](Self::new); otherwise `InvalidInput`.
    pub fn from_report(report: &FloorReport) -> Result<Floor> {
        if report.version != FloorReport::VERSION {
            return Err(Error::invalid(format!(
                "floor.version must be {:?}",
                FloorReport::VERSION
            )));
        }
        let id_kind = match report.id_kind.as_str() {
            "u64" => IdKind::U64,
            "utf8" => IdKind::Utf8,
            _ => return Err(Error::invalid("floor.id_kind must be \"u64\" or \"utf8\"")),
        };
        let reference_id = unhex32(&report.reference_id)
            .ok_or_else(|| Error::invalid("floor.reference_id must be 64 hex characters"))?;
        Floor::new(
            &report.config,
            id_kind,
            reference_id,
            report.nulls,
            report.changed_rows,
            report.total_rows,
            report.hamming,
        )
    }

    fn fields(&self) -> (CodecConfig, IdKind, [u8; 32], u64, u64, u64, u64) {
        (
            self.config,
            self.id_kind,
            self.reference_id(),
            self.nulls(),
            self.changed_rows(),
            self.total_rows(),
            self.hamming(),
        )
    }
}

impl PartialEq for Floor {
    fn eq(&self, other: &Floor) -> bool {
        self.fields() == other.fields()
    }
}

impl Eq for Floor {}

impl Hash for Floor {
    fn hash<H: Hasher>(&self, state: &mut H) {
        self.fields().hash(state);
    }
}

/// `Floor(1 of 3 rows, hamming 1, from 3 nulls)`, the same text as the
/// other bindings.
impl fmt::Display for Floor {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "Floor({} of {} rows, hamming {}, from {} nulls)",
            self.changed_rows(),
            self.total_rows(),
            self.hamming(),
            self.nulls()
        )
    }
}

impl fmt::Debug for Floor {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Floor")
            .field("config", &self.config)
            .field("id_kind", &self.id_kind.name())
            .field("reference_id", &hex(&self.reference_id()))
            .field("nulls", &self.nulls())
            .field("changed_rows", &self.changed_rows())
            .field("total_rows", &self.total_rows())
            .field("hamming", &self.hamming())
            .finish()
    }
}

/// A [`Floor`] as plain data: the `semq-floor/1` schema without a
/// serializer.
///
/// Serialized in this field order: `version` is `"semq-floor/1"`; `config`
/// is the same object a [`DiffReport`](crate::DiffReport) carries
/// (`{"operator": config.operator().name(), "dim": config.dim(),
/// config.operator().parameter_name(): config.parameter(), "rule_revision":
/// config.rule_revision()}`); `id_kind` is `"u64"` or `"utf8"`;
/// `reference_id` is 64 lowercase hex characters; the four counts are
/// integers. [`Floor::from_report`] is the strict inverse.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FloorReport {
    /// The schema version, [`VERSION`](Self::VERSION).
    pub version: String,
    /// The config the nulls were measured under.
    pub config: CodecConfig,
    /// `"u64"` or `"utf8"`.
    pub id_kind: String,
    /// The reference's `state_id`, hex.
    pub reference_id: String,
    /// How many null diffs the floor was measured from.
    pub nulls: u64,
    /// Numerator of the admitted fraction of changed rows.
    pub changed_rows: u64,
    /// Denominator of the admitted fraction of changed rows.
    pub total_rows: u64,
    /// Largest admitted p99 hamming distance over changed rows.
    pub hamming: u64,
}

impl FloorReport {
    /// The schema version every report carries.
    pub const VERSION: &'static str = "semq-floor/1";
}

/// Exactly 64 hex digits (either case) as 32 bytes.
fn unhex32(text: &str) -> Option<[u8; 32]> {
    let digits = text.as_bytes();
    if digits.len() != 64 {
        return None;
    }
    let mut out = [0u8; 32];
    for (byte, pair) in out.iter_mut().zip(digits.chunks_exact(2)) {
        let hi = (pair[0] as char).to_digit(16)?;
        let lo = (pair[1] as char).to_digit(16)?;
        *byte = (hi * 16 + lo) as u8;
    }
    Some(out)
}
