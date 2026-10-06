// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

package semq

/*
#include "semq.h"
*/
import "C"

import "runtime"

// GateOptions selects the checks Diff.Evaluate applies beyond those of
// Diff.Within. The zero value has every check off, so a new check never
// changes an existing verdict.
type GateOptions struct {
	// PerRow also fails the verdict when any changed row has a hamming
	// above the floor's MaxHamming, and lists those rows. It needs a floor
	// that records MaxHamming (IncompatibleError otherwise).
	PerRow bool
}

// Reason names a check that failed in a Verdict, with the name every
// binding uses.
type Reason string

// The checks of a Verdict, in the order Reasons lists them.
const (
	ReasonNoCommonRows Reason = "no_common_rows" // no row in common with the reference
	ReasonRemovedRows  Reason = "removed_rows"   // the candidate removed rows
	ReasonChangedRatio Reason = "changed_ratio"  // more shared rows changed than the floor's ratio
	ReasonHamming      Reason = "hamming"        // the p99 hamming is above the floor's
	ReasonEncoder      Reason = "encoder"        // encoder or encoder_revision changed
	ReasonRowAboveMax  Reason = "row_above_max"  // per-row check: a row changed more than any null row
)

var reasonFlags = []struct {
	reason Reason
	flag   C.uint32_t
}{
	{ReasonNoCommonRows, C.SEMQ_REASON_NO_COMMON_ROWS},
	{ReasonRemovedRows, C.SEMQ_REASON_REMOVED_ROWS},
	{ReasonChangedRatio, C.SEMQ_REASON_CHANGED_RATIO},
	{ReasonHamming, C.SEMQ_REASON_HAMMING},
	{ReasonEncoder, C.SEMQ_REASON_ENCODER},
	{ReasonRowAboveMax, C.SEMQ_REASON_ROW_ABOVE_MAX},
}

// Verdict is the result of Diff.Evaluate.
type Verdict struct {
	// Passed is true iff no check failed.
	Passed bool
	// Reasons lists every failed check in the order of the Reason
	// constants; empty when Passed.
	Reasons []Reason
	// Rows are the ids of the changed rows above the floor's MaxHamming,
	// in canonical order; empty unless the per-row check ran.
	Rows []ID
}

// Evaluate returns the verdict of f on this diff, with every check that
// failed. With the zero GateOptions, Passed equals Within. With PerRow the
// verdict also fails when any changed row has a hamming above
// f.MaxHamming(), and Rows lists those ids. IncompatibleError when f was
// measured against another config, id kind or reference, or for PerRow on
// a floor without MaxHamming.
func (d *Diff) Evaluate(f *Floor, opts GateOptions) (Verdict, error) {
	h, err := d.handle()
	if err != nil {
		return Verdict{}, err
	}
	defer runtime.KeepAlive(d)
	fh, err := f.handle()
	if err != nil {
		return Verdict{}, err
	}
	defer runtime.KeepAlive(f)
	var (
		o  *C.semq_gate_options_t
		v  *C.semq_verdict_t
		ce C.semq_error_t
	)
	if err := check(C.semq_gate_options_create(&o, &ce), &ce, "evaluate"); err != nil {
		return Verdict{}, err
	}
	defer C.semq_gate_options_free(o)
	if opts.PerRow {
		C.semq_gate_options_set_per_row(o, 1)
	}
	if err := check(C.semq_diff_evaluate(h, fh, o, &v, &ce), &ce, "evaluate"); err != nil {
		return Verdict{}, err
	}
	defer C.semq_verdict_free(v)
	flags := C.semq_verdict_reasons(v)
	out := Verdict{Passed: C.semq_verdict_passed(v) != 0, Reasons: []Reason{}, Rows: []ID{}}
	for _, r := range reasonFlags {
		if flags&r.flag != 0 {
			out.Reasons = append(out.Reasons, r.reason)
		}
	}
	if n := uint64(C.semq_verdict_row_count(v)); n > 0 {
		changed := d.ids(h, C.SEMQ_LIST_CHANGED)
		for i := uint64(0); i < n; i++ {
			out.Rows = append(out.Rows, changed[uint64(C.semq_verdict_row(v, C.uint64_t(i)))])
		}
	}
	return out, nil
}
