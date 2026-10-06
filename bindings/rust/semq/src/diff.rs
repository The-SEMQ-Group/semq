// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

//! Diff: what changed between a reference and a candidate.

use std::collections::BTreeMap;
use std::fmt;
use std::os::raw::c_int;
use std::ptr::{self, NonNull};

use semq_sys as sys;

use crate::config::CodecConfig;
use crate::convert::{hex, text, FreeOnDrop};
use crate::error::{check, new_error, Error, Result};
use crate::floor::Floor;
use crate::gate::{GateOptions, Reason, Verdict};
use crate::ids::{ptr_or_null, Id, IdKind};

/// The result of [`Encoding::diff`](crate::Encoding::diff).
///
/// Keeps the rows it needs alive until it is dropped, even if the caller
/// drops its Encodings. Safe to share between threads.
pub struct Diff {
    ptr: NonNull<sys::semq_diff_t>,
    config: CodecConfig,
    id_kind: IdKind,
}

// SAFETY: a diff is immutable after construction and the core keeps no
// mutable semantic state. Retention/release of the shared Encodings uses
// atomic reference counts on every supported target (enforced at C build).
// Rust borrows prevent Drop while a call or returned slice uses the handle.
unsafe impl Send for Diff {}
unsafe impl Sync for Diff {}

impl Drop for Diff {
    fn drop(&mut self) {
        // SAFETY: the handle came from `semq_encoding_diff` and is freed once.
        unsafe { sys::semq_diff_free(self.ptr.as_ptr()) }
    }
}

impl AsRef<Diff> for Diff {
    fn as_ref(&self) -> &Diff {
        self
    }
}

impl Diff {
    /// Take ownership of a handle the core just produced.
    pub(crate) fn from_raw(ptr: *mut sys::semq_diff_t, operation: &'static str) -> Result<Diff> {
        let ptr = NonNull::new(ptr).ok_or_else(|| {
            Error::native(
                operation,
                sys::SEMQ_ERR_INTERNAL,
                None,
                None,
                "core returned a null diff",
            )
        })?;
        let guard = FreeOnDrop::new(ptr, sys::semq_diff_free);
        // SAFETY: the handle is live and owns the config it points to.
        let raw = unsafe { *sys::semq_diff_config(guard.ptr()) };
        let config = CodecConfig::from_raw(raw, operation)?;
        // SAFETY: the handle is live.
        let kind = unsafe { sys::semq_diff_id_kind(guard.ptr()) };
        let id_kind = IdKind::from_raw(kind).ok_or_else(|| {
            Error::native(
                operation,
                sys::SEMQ_ERR_INTERNAL,
                None,
                None,
                "diff has an unknown id kind",
            )
        })?;
        Ok(Diff {
            ptr: guard.release(),
            config,
            id_kind,
        })
    }

    pub(crate) fn as_ptr(&self) -> *const sys::semq_diff_t {
        self.ptr.as_ptr()
    }

    /// The configuration shared by both sides.
    pub fn config(&self) -> &CodecConfig {
        &self.config
    }

    /// The id kind shared by both sides.
    pub fn id_kind(&self) -> IdKind {
        self.id_kind
    }

    /// The reference's `state_id`.
    pub fn reference_id(&self) -> [u8; 32] {
        let mut out = [0u8; 32];
        // SAFETY: the handle is live and `out` has room for 32 bytes.
        unsafe { sys::semq_diff_reference_id(self.ptr.as_ptr(), out.as_mut_ptr()) };
        out
    }

    /// The candidate's `state_id`.
    pub fn candidate_id(&self) -> [u8; 32] {
        let mut out = [0u8; 32];
        // SAFETY: the handle is live and `out` has room for 32 bytes.
        unsafe { sys::semq_diff_candidate_id(self.ptr.as_ptr(), out.as_mut_ptr()) };
        out
    }

    fn count(&self, list: u32) -> u64 {
        // SAFETY: the handle is live.
        unsafe { sys::semq_diff_count(self.ptr.as_ptr(), list) }
    }

    fn list(&self, list: u32) -> Vec<Id> {
        let n = self.count(list);
        let mut out = Vec::with_capacity(n as usize);
        for i in 0..n {
            let mut value = 0u64;
            let mut bytes: *const u8 = ptr::null();
            let mut len = 0u64;
            let mut err = new_error();
            // SAFETY: `i` is in range; every out-pointer is live.
            let status = unsafe {
                sys::semq_diff_id(
                    self.ptr.as_ptr(),
                    list,
                    i,
                    &mut value,
                    &mut bytes,
                    &mut len,
                    &mut err,
                )
            };
            check(status, &err, "accessor")
                .expect("SEMQ core violated an infallible accessor contract");
            out.push(match self.id_kind {
                IdKind::U64 => Id::U64(value),
                // SAFETY: the bytes point into memory the diff owns.
                IdKind::Utf8 => Id::Utf8(unsafe { text(bytes, len as usize) }),
            });
        }
        out
    }

    /// Ids only in the candidate, canonical order.
    pub fn added(&self) -> Vec<Id> {
        self.list(sys::SEMQ_LIST_ADDED)
    }

    /// Ids only in the reference, canonical order.
    pub fn removed(&self) -> Vec<Id> {
        self.list(sys::SEMQ_LIST_REMOVED)
    }

    /// `(id, hamming)` for ids on both sides with different rows, canonical
    /// order. `hamming` counts the units whose symbol differs.
    pub fn changed(&self) -> Vec<(Id, u64)> {
        self.list(sys::SEMQ_LIST_CHANGED)
            .into_iter()
            .enumerate()
            .map(|(i, id)| {
                let mut hamming = 0u64;
                let mut err = new_error();
                // SAFETY: `i` indexes the changed list; out-pointers are live.
                let status = unsafe {
                    sys::semq_diff_hamming(self.ptr.as_ptr(), i as u64, &mut hamming, &mut err)
                };
                check(status, &err, "hamming")
                    .expect("SEMQ core violated an infallible accessor contract");
                (id, hamming)
            })
            .collect()
    }

    /// Ids on both sides with identical rows.
    pub fn n_unchanged(&self) -> u64 {
        // SAFETY: the handle is live.
        unsafe { sys::semq_diff_n_unchanged(self.ptr.as_ptr()) }
    }

    /// `key -> (before, after)` for keys whose value differs or that exist
    /// on one side only; `None` marks the absent side.
    pub fn manifest_changes(&self) -> BTreeMap<String, (Option<String>, Option<String>)> {
        // SAFETY: the handle is live.
        let n = unsafe { sys::semq_diff_manifest_changes(self.ptr.as_ptr()) };
        let mut out = BTreeMap::new();
        for i in 0..n {
            let mut change = sys::semq_manifest_change_t {
                key: ptr::null(),
                key_len: 0,
                has_before: 0,
                before: ptr::null(),
                before_len: 0,
                has_after: 0,
                after: ptr::null(),
                after_len: 0,
            };
            let mut err = new_error();
            // SAFETY: `i < n`; the out-pointers are live.
            let status = unsafe {
                sys::semq_diff_manifest_change(self.ptr.as_ptr(), i, &mut change, &mut err)
            };
            check(status, &err, "accessor")
                .expect("SEMQ core violated an infallible accessor contract");
            // SAFETY: the change points into memory the diff owns.
            let (key, before, after) = unsafe {
                (
                    text(change.key, change.key_len as usize),
                    (change.has_before != 0)
                        .then(|| text(change.before, change.before_len as usize)),
                    (change.has_after != 0).then(|| text(change.after, change.after_len as usize)),
                )
            };
            out.insert(key, (before, after));
        }
        out
    }

    /// `(unit, symbol_reference, symbol_candidate)` for every unit of `id`
    /// that differs; empty for an identical row. `InvalidInput` when `id`
    /// is absent from either side or its kind is not the diff's.
    pub fn units(&self, id: &Id) -> Result<Vec<(u32, u8, u8)>> {
        let cap = self.config.units_per_row() as usize;
        let mut units = vec![0u32; cap];
        let mut reference = vec![0u8; cap];
        let mut candidate = vec![0u8; cap];
        let mut count = 0u64;
        let mut err = new_error();
        // SAFETY: the three buffers hold `cap` entries; the id bytes outlive
        // the call; every out-pointer is live.
        let status = match id {
            Id::U64(v) => unsafe {
                sys::semq_diff_units_u64(
                    self.ptr.as_ptr(),
                    *v,
                    units.as_mut_ptr(),
                    reference.as_mut_ptr(),
                    candidate.as_mut_ptr(),
                    cap as u64,
                    &mut count,
                    &mut err,
                )
            },
            Id::Utf8(s) => unsafe {
                sys::semq_diff_units_utf8(
                    self.ptr.as_ptr(),
                    ptr_or_null(s.as_bytes()),
                    s.len() as u64,
                    units.as_mut_ptr(),
                    reference.as_mut_ptr(),
                    candidate.as_mut_ptr(),
                    cap as u64,
                    &mut count,
                    &mut err,
                )
            },
        };
        check(status, &err, "units")?;
        let count = (count as usize).min(cap);
        Ok((0..count)
            .map(|i| (units[i], reference[i], candidate[i]))
            .collect())
    }

    /// `true` iff the candidate is within `floor`: it shares at least one
    /// row with the reference, removes none, changes at most
    /// `changed_rows / total_rows` of the shared rows, its p99 hamming does
    /// not exceed `floor.hamming()`, and it changes neither `encoder` nor
    /// `encoder_revision`. Exact integer arithmetic in the core.
    /// `Incompatible` when the floor was measured under another config or
    /// id kind, or against another reference than this diff's.
    pub fn within(&self, floor: &Floor) -> Result<bool> {
        let mut out: c_int = 0;
        let mut err = new_error();
        // SAFETY: both handles are live; every pointer is valid for the call.
        let status =
            unsafe { sys::semq_diff_within(self.ptr.as_ptr(), floor.as_ptr(), &mut out, &mut err) };
        check(status, &err, "within")?;
        Ok(out != 0)
    }

    /// The verdict of `floor` on this diff, with every check that failed.
    ///
    /// With [`GateOptions::new`], `passed()` equals [`within`](Self::within).
    /// With [`GateOptions::per_row`] the verdict also fails when any changed
    /// row has a hamming above [`Floor::max_hamming`], and
    /// [`Verdict::rows`] lists those ids. `Incompatible` for a floor of
    /// another config, id kind or reference, and for the per-row check on a
    /// floor without `max_hamming`.
    pub fn evaluate(&self, floor: &Floor, options: &GateOptions) -> Result<Verdict> {
        let mut opts: *mut sys::semq_gate_options_t = ptr::null_mut();
        let mut err = new_error();
        // SAFETY: the out-pointers are live for the call.
        let status = unsafe { sys::semq_gate_options_create(&mut opts, &mut err) };
        check(status, &err, "evaluate")?;
        let opts = NonNull::new(opts).ok_or_else(|| {
            Error::native(
                "evaluate",
                sys::SEMQ_ERR_INTERNAL,
                None,
                None,
                "core returned null options",
            )
        })?;
        let opts = FreeOnDrop::new(opts, sys::semq_gate_options_free);
        // SAFETY: the options handle is live and owned here.
        unsafe {
            sys::semq_gate_options_set_per_row(opts.ptr(), c_int::from(options.is_per_row()))
        };
        let mut out: *mut sys::semq_verdict_t = ptr::null_mut();
        // SAFETY: every handle is live; the out-pointers are live for the call.
        let status = unsafe {
            sys::semq_diff_evaluate(
                self.ptr.as_ptr(),
                floor.as_ptr(),
                opts.ptr(),
                &mut out,
                &mut err,
            )
        };
        check(status, &err, "evaluate")?;
        let verdict = NonNull::new(out).ok_or_else(|| {
            Error::native(
                "evaluate",
                sys::SEMQ_ERR_INTERNAL,
                None,
                None,
                "core returned a null verdict",
            )
        })?;
        let verdict = FreeOnDrop::new(verdict, sys::semq_verdict_free);
        // SAFETY: the verdict handle is live for these reads.
        let (flags, n) = unsafe {
            (
                sys::semq_verdict_reasons(verdict.ptr()),
                sys::semq_verdict_row_count(verdict.ptr()),
            )
        };
        let changed = if n > 0 {
            self.list(sys::SEMQ_LIST_CHANGED)
        } else {
            Vec::new()
        };
        let rows = (0..n)
            .map(|i| {
                // SAFETY: the verdict handle is live and `i` is in range.
                let index = unsafe { sys::semq_verdict_row(verdict.ptr(), i) };
                changed[index as usize].clone()
            })
            .collect();
        Ok(Verdict {
            reasons: Reason::from_flags(flags),
            rows,
        })
    }

    /// The report as plain data, ready for any serializer.
    pub fn as_report(&self) -> DiffReport {
        DiffReport {
            reference_id: hex(&self.reference_id()),
            candidate_id: hex(&self.candidate_id()),
            id_kind: self.id_kind.name(),
            config: self.config,
            added: self.added().iter().map(Id::to_string).collect(),
            removed: self.removed().iter().map(Id::to_string).collect(),
            changed: self
                .changed()
                .iter()
                .map(|(id, h)| (id.to_string(), *h))
                .collect(),
            n_unchanged: self.n_unchanged(),
            manifest_changes: self.manifest_changes(),
        }
    }
}

/// One sentence, the same text as the other bindings:
/// `1 of 3 rows changed: doc-3 (hamming 3). 0 added, 0 removed.`
///
/// Up to five changed ids are listed; changed manifest keys are named at
/// the end.
impl fmt::Display for Diff {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let changed = self.changed();
        let shared = changed.len() as u64 + self.n_unchanged();
        write!(f, "{} of {shared} rows changed", changed.len())?;
        if !changed.is_empty() {
            let shown: Vec<String> = changed
                .iter()
                .take(5)
                .map(|(id, h)| format!("{id} (hamming {h})"))
                .collect();
            write!(f, ": {}", shown.join(", "))?;
            if changed.len() > 5 {
                write!(f, ", and {} more", changed.len() - 5)?;
            }
        }
        write!(
            f,
            ". {} added, {} removed.",
            self.count(sys::SEMQ_LIST_ADDED),
            self.count(sys::SEMQ_LIST_REMOVED)
        )?;
        let changes = self.manifest_changes();
        if !changes.is_empty() {
            let keys: Vec<&str> = changes.keys().map(String::as_str).collect();
            write!(f, " Manifest changed: {}.", keys.join(", "))?;
        }
        Ok(())
    }
}

impl fmt::Debug for Diff {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Diff")
            .field("added", &self.count(sys::SEMQ_LIST_ADDED))
            .field("removed", &self.count(sys::SEMQ_LIST_REMOVED))
            .field("changed", &self.count(sys::SEMQ_LIST_CHANGED))
            .field("n_unchanged", &self.n_unchanged())
            .finish()
    }
}

/// A [`Diff`] as plain data: the report schema without a serializer.
///
/// Digests are 64 lowercase hex characters; ids are rendered as text
/// (decimal for `u64`); counts are integers; no floats anywhere. The
/// `config` object of the schema is `{"operator": config.operator().name(),
/// "dim": config.dim(), config.operator().parameter_name():
/// config.parameter(), "rule_revision": config.rule_revision()}`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DiffReport {
    /// The reference's `state_id`, hex.
    pub reference_id: String,
    /// The candidate's `state_id`, hex.
    pub candidate_id: String,
    /// `"u64"` or `"utf8"`.
    pub id_kind: &'static str,
    /// The shared configuration.
    pub config: CodecConfig,
    /// Ids only in the candidate, canonical order.
    pub added: Vec<String>,
    /// Ids only in the reference, canonical order.
    pub removed: Vec<String>,
    /// `(id, hamming)` for rows that differ, canonical order.
    pub changed: Vec<(String, u64)>,
    /// Rows on both sides that are identical.
    pub n_unchanged: u64,
    /// `key -> (before, after)`; `None` marks the absent side.
    pub manifest_changes: BTreeMap<String, (Option<String>, Option<String>)>,
}
