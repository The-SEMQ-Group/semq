// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

//! Gate evaluation: the options of [`Diff::evaluate`](crate::Diff::evaluate)
//! and the verdict it returns.

use semq_sys as sys;

use crate::ids::Id;

/// Which checks [`Diff::evaluate`](crate::Diff::evaluate) applies beyond
/// those of [`Diff::within`](crate::Diff::within). Every check is off by
/// default, so a new check never changes an existing verdict.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Hash)]
pub struct GateOptions {
    per_row: bool,
}

impl GateOptions {
    /// Every check off: the verdict of [`Diff::within`](crate::Diff::within).
    pub fn new() -> GateOptions {
        GateOptions::default()
    }

    /// Per-row check: also fail when any changed row has a hamming above
    /// the floor's [`max_hamming`](crate::Floor::max_hamming), and list
    /// those rows. Needs a floor that records it (`Incompatible`
    /// otherwise).
    pub fn per_row(mut self, enabled: bool) -> GateOptions {
        self.per_row = enabled;
        self
    }

    pub(crate) fn is_per_row(&self) -> bool {
        self.per_row
    }
}

/// A check that failed in a [`Verdict`].
#[non_exhaustive]
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum Reason {
    /// The candidate shares no row with the reference.
    NoCommonRows,
    /// The candidate removed rows.
    RemovedRows,
    /// More of the shared rows changed than the floor's ratio.
    ChangedRatio,
    /// The p99 hamming is above the floor's.
    Hamming,
    /// `encoder` or `encoder_revision` changed.
    Encoder,
    /// Per-row check: a row changed more than any row of any null.
    RowAboveMax,
}

impl Reason {
    const ALL: [(Reason, sys::semq_reason_t); 6] = [
        (Reason::NoCommonRows, sys::SEMQ_REASON_NO_COMMON_ROWS),
        (Reason::RemovedRows, sys::SEMQ_REASON_REMOVED_ROWS),
        (Reason::ChangedRatio, sys::SEMQ_REASON_CHANGED_RATIO),
        (Reason::Hamming, sys::SEMQ_REASON_HAMMING),
        (Reason::Encoder, sys::SEMQ_REASON_ENCODER),
        (Reason::RowAboveMax, sys::SEMQ_REASON_ROW_ABOVE_MAX),
    ];

    /// The name every binding uses: `"no_common_rows"`, `"removed_rows"`,
    /// `"changed_ratio"`, `"hamming"`, `"encoder"` or `"row_above_max"`.
    pub fn name(self) -> &'static str {
        match self {
            Reason::NoCommonRows => "no_common_rows",
            Reason::RemovedRows => "removed_rows",
            Reason::ChangedRatio => "changed_ratio",
            Reason::Hamming => "hamming",
            Reason::Encoder => "encoder",
            Reason::RowAboveMax => "row_above_max",
        }
    }

    pub(crate) fn from_flags(flags: u32) -> Vec<Reason> {
        Reason::ALL
            .iter()
            .filter(|(_, bit)| flags & bit != 0)
            .map(|(r, _)| *r)
            .collect()
    }
}

/// The result of [`Diff::evaluate`](crate::Diff::evaluate): whether the
/// candidate passed, every check that failed, and the rows the per-row
/// check flagged.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct Verdict {
    pub(crate) reasons: Vec<Reason>,
    pub(crate) rows: Vec<Id>,
}

impl Verdict {
    /// `true` iff no check failed.
    pub fn passed(&self) -> bool {
        self.reasons.is_empty()
    }

    /// The failed checks, in the order of [`Reason`]; empty when passed.
    pub fn reasons(&self) -> &[Reason] {
        &self.reasons
    }

    /// Ids of the changed rows above the floor's `max_hamming`, canonical
    /// order; empty unless the per-row check ran.
    pub fn rows(&self) -> &[Id] {
        &self.rows
    }
}
