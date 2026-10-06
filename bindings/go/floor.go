// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

package semq

/*
#include "semq.h"
*/
import "C"

import (
	"encoding/hex"
	"encoding/json"
	"fmt"
	"runtime"
	"unsafe"
)

// FloorVersion is the version string of the floor report form without
// max_hamming.
const FloorVersion = "semq-floor/1"

// FloorVersion2 is the version string of the floor report form with
// max_hamming, the form a measured Floor reports.
const FloorVersion2 = "semq-floor/2"

// Floor is an envelope of observed variation, bound to the context it was
// measured in: the config, the id kind and the StateID of the reference
// every null diff was taken against. A diff is within it when it removes no
// rows, shares at least one row with its reference, changes at most
// ChangedRows/TotalRows of the shared rows, its p99 hamming does not exceed
// Hamming and it changes neither of the manifest keys encoder and
// encoder_revision. No probabilistic coverage is claimed.
//
// A Floor from MeasureFloor also records MaxHamming, the largest hamming of
// any changed row of any null, for the per-row check of Diff.Evaluate.
//
// Build one with NewFloor, MeasureFloor or FloorFromReport. It is immutable
// and safe for concurrent use. Call Close when done; a finalizer is the
// fallback. Close must not race with another method. The accessors are
// cached and stay valid after Close; Diff.Within on a closed Floor returns
// InvalidInputError.
// Copies share ownership: closing any copy closes them all.
type Floor struct {
	owner       *nativeOwner
	cfg         CodecConfig
	kind        IDKind
	reference   [32]byte
	nulls       uint64
	changedRows uint64
	totalRows   uint64
	hamming     uint64
	maxHamming  uint64
	hasMax      bool
}

// FloorReport is the report form of a Floor: the config as in a Diff
// Report, the id kind by name, the reference StateID as lowercase hex and
// the counts as integers. Version "semq-floor/2" carries MaxHamming;
// version "semq-floor/1" does not: MaxHamming is 0 and is not marshaled.
// It marshals with the keys in this order. Decoding JSON into it is strict: exactly the keys
// of its version (eight, or nine with max_hamming),
// version, id_kind and reference_id as strings, config as ConfigReport
// reads it and the counts as non-negative JSON integers (no null,
// booleans, floats, exponents or numeric strings); any other shape is
// InvalidInputError naming the key. FloorFromReport checks the values.
type FloorReport struct {
	Version     string       `json:"version"`
	Config      ConfigReport `json:"config"`
	IDKind      string       `json:"id_kind"`
	ReferenceID string       `json:"reference_id"`
	Nulls       uint64       `json:"nulls"`
	ChangedRows uint64       `json:"changed_rows"`
	TotalRows   uint64       `json:"total_rows"`
	Hamming     uint64       `json:"hamming"`
	MaxHamming  uint64       `json:"max_hamming"`
}

// MarshalJSON writes the keys of the report's version, in order.
func (r FloorReport) MarshalJSON() ([]byte, error) {
	type plain FloorReport
	if r.Version == FloorVersion2 {
		return json.Marshal(plain(r))
	}
	return json.Marshal(struct {
		Version     string       `json:"version"`
		Config      ConfigReport `json:"config"`
		IDKind      string       `json:"id_kind"`
		ReferenceID string       `json:"reference_id"`
		Nulls       uint64       `json:"nulls"`
		ChangedRows uint64       `json:"changed_rows"`
		TotalRows   uint64       `json:"total_rows"`
		Hamming     uint64       `json:"hamming"`
	}{r.Version, r.Config, r.IDKind, r.ReferenceID, r.Nulls, r.ChangedRows, r.TotalRows, r.Hamming})
}

// floorReportKeys are the keys of the floor schema, in marshal order.
var floorReportKeys = []string{"version", "config", "id_kind", "reference_id", "nulls", "changed_rows", "total_rows", "hamming"}

// UnmarshalJSON reads the floor schema as the type's documentation says.
// On error r is left as it was.
func (r *FloorReport) UnmarshalJSON(b []byte) error {
	const what = "floor report"
	fields, err := reportObject(b, what)
	if err != nil {
		return err
	}
	var out FloorReport
	if _, ok := fields["version"]; ok {
		if out.Version, err = reportString(fields, what, "version"); err != nil {
			return err
		}
	}
	keys := floorReportKeys
	if out.Version == FloorVersion2 {
		keys = append(keys[:len(keys):len(keys)], "max_hamming")
	}
	if err := reportKeys(fields, what, keys...); err != nil {
		return err
	}
	if err = json.Unmarshal(fields["config"], &out.Config); err != nil {
		return err
	}
	if out.IDKind, err = reportString(fields, what, "id_kind"); err != nil {
		return err
	}
	if out.ReferenceID, err = reportString(fields, what, "reference_id"); err != nil {
		return err
	}
	if out.Nulls, err = reportUint(fields, what, "nulls", 64); err != nil {
		return err
	}
	if out.ChangedRows, err = reportUint(fields, what, "changed_rows", 64); err != nil {
		return err
	}
	if out.TotalRows, err = reportUint(fields, what, "total_rows", 64); err != nil {
		return err
	}
	if out.Hamming, err = reportUint(fields, what, "hamming", 64); err != nil {
		return err
	}
	if out.Version == FloorVersion2 {
		if out.MaxHamming, err = reportUint(fields, what, "max_hamming", 64); err != nil {
			return err
		}
	}
	*r = out
	return nil
}

func newFloor(p *C.semq_floor_t) *Floor {
	f := &Floor{
		owner:       newOwner(unsafe.Pointer(p), func(p unsafe.Pointer) { C.semq_floor_free((*C.semq_floor_t)(p)) }),
		cfg:         configFromC(C.semq_floor_config(p)),
		kind:        IDKind(C.semq_floor_id_kind(p)),
		nulls:       uint64(C.semq_floor_nulls(p)),
		changedRows: uint64(C.semq_floor_changed_rows(p)),
		totalRows:   uint64(C.semq_floor_total_rows(p)),
		hamming:     uint64(C.semq_floor_hamming(p)),
		maxHamming:  uint64(C.semq_floor_max_hamming(p)),
	}
	f.hasMax = f.maxHamming != uint64(C.SEMQ_NONE)
	C.semq_floor_reference_id(p, (*C.uint8_t)(unsafe.Pointer(&f.reference[0])))
	return f
}

// NewFloor builds a floor from its fields. The core validates every one:
// config valid, kind IDU64 or IDUTF8, nulls >= 1, totalRows >= 1,
// changedRows <= totalRows and hamming <= config.UnitsPerRow(); a violation
// is InvalidInputError.
func NewFloor(config CodecConfig, kind IDKind, referenceID [32]byte, nulls, changedRows, totalRows, hamming uint64) (*Floor, error) {
	cc := config.toC()
	var (
		out *C.semq_floor_t
		e   C.semq_error_t
	)
	s := C.semq_floor_create(&cc, C.uint32_t(kind), (*C.uint8_t)(unsafe.Pointer(&referenceID[0])),
		C.uint64_t(nulls), C.uint64_t(changedRows), C.uint64_t(totalRows), C.uint64_t(hamming), &out, &e)
	if err := check(s, &e, "floor"); err != nil {
		return nil, err
	}
	return newFloor(out), nil
}

// WithMaxHamming returns this floor also recording maxHamming:
// Hamming() <= maxHamming <= Config().UnitsPerRow(), else InvalidInputError.
func (f *Floor) WithMaxHamming(maxHamming uint64) (*Floor, error) {
	if _, err := f.handle(); err != nil {
		return nil, err
	}
	defer runtime.KeepAlive(f)
	cc := f.cfg.toC()
	var (
		out *C.semq_floor_t
		e   C.semq_error_t
	)
	s := C.semq_floor_create_with_max(&cc, C.uint32_t(f.kind), (*C.uint8_t)(unsafe.Pointer(&f.reference[0])),
		C.uint64_t(f.nulls), C.uint64_t(f.changedRows), C.uint64_t(f.totalRows), C.uint64_t(f.hamming),
		C.uint64_t(maxHamming), &out, &e)
	if err := check(s, &e, "floor"); err != nil {
		return nil, err
	}
	return newFloor(out), nil
}

// MeasureFloor returns the envelope of one or more null diffs; every input
// is within the result and Nulls reports how many there were. All nulls
// must share config, id kind and reference (else IncompatibleError with
// Field = diff index), and each must have rows in common, nothing added or
// removed and no change to the manifest keys encoder or encoder_revision
// (else InvalidInputError with Field = diff index).
func MeasureFloor(nulls []*Diff) (*Floor, error) {
	if len(nulls) == 0 {
		return nil, &InvalidInputError{Message: "measure needs at least one null diff"}
	}
	count, countErr := abiCount(uint64(len(nulls)))
	if countErr != nil {
		return nil, countErr
	}
	handles := make([]*C.semq_diff_t, len(nulls))
	for i, d := range nulls {
		h, err := d.handle()
		if err != nil {
			return nil, err
		}
		handles[i] = h
	}
	var (
		out *C.semq_floor_t
		e   C.semq_error_t
	)
	s := C.semq_floor_measure((**C.semq_diff_t)(unsafe.Pointer(&handles[0])), count, &out, &e)
	for _, d := range nulls {
		runtime.KeepAlive(d)
	}
	if err := check(s, &e, "measure"); err != nil {
		return nil, err
	}
	return newFloor(out), nil
}

// FloorFromReport is the inverse of Report, strictly: Version must be
// FloorVersion (with MaxHamming 0) or FloorVersion2, IDKind "u64" or "utf8", ReferenceID 64 hex characters, Config a valid
// config, and the counts as NewFloor and WithMaxHamming require. Any
// violation is InvalidInputError.
func FloorFromReport(r FloorReport) (*Floor, error) {
	if r.Version != FloorVersion2 && (r.Version != FloorVersion || r.MaxHamming != 0) {
		return nil, &InvalidInputError{Message: "floor version must be \"" + FloorVersion2 + "\", or \"" + FloorVersion + "\" without max_hamming"}
	}
	var kind IDKind
	switch r.IDKind {
	case IDU64.String():
		kind = IDU64
	case IDUTF8.String():
		kind = IDUTF8
	default:
		return nil, &InvalidInputError{Message: "floor id_kind must be \"u64\" or \"utf8\""}
	}
	// The length is checked before decoding into the fixed-size array.
	var reference [32]byte
	if len(r.ReferenceID) != hex.EncodedLen(len(reference)) {
		return nil, &InvalidInputError{Message: "floor reference_id must be 64 hex characters"}
	}
	if _, err := hex.Decode(reference[:], []byte(r.ReferenceID)); err != nil {
		return nil, &InvalidInputError{Message: "floor reference_id must be 64 hex characters"}
	}
	cfg, err := r.Config.config()
	if err != nil {
		return nil, err
	}
	f, err := NewFloor(cfg, kind, reference, r.Nulls, r.ChangedRows, r.TotalRows, r.Hamming)
	if err != nil || r.Version == FloorVersion {
		return f, err
	}
	defer f.Close()
	return f.WithMaxHamming(r.MaxHamming)
}

// Close releases the native handle. Idempotent.
func (f *Floor) Close() {
	if f != nil {
		f.owner.close()
	}
}

func (f *Floor) handle() (*C.semq_floor_t, error) {
	if f == nil {
		return nil, &InvalidInputError{Message: "floor is nil"}
	}
	p := (*C.semq_floor_t)(f.owner.pointer())
	if p == nil {
		return nil, &InvalidInputError{Message: "floor is closed"}
	}
	return p, nil
}

// Config reports the config the nulls were encoded with.
func (f *Floor) Config() CodecConfig { return f.cfg }

// IDKind reports the id kind of the nulls.
func (f *Floor) IDKind() IDKind { return f.kind }

// ReferenceID is the StateID of the reference every null was taken against.
func (f *Floor) ReferenceID() [32]byte { return f.reference }

// Nulls counts the null diffs the floor was measured from.
func (f *Floor) Nulls() uint64 { return f.nulls }

// ChangedRows is the numerator of the admitted change ratio.
func (f *Floor) ChangedRows() uint64 { return f.changedRows }

// TotalRows is the denominator of the admitted change ratio.
func (f *Floor) TotalRows() uint64 { return f.totalRows }

// Hamming is the admitted p99 hamming distance.
func (f *Floor) Hamming() uint64 { return f.hamming }

// MaxHamming is the largest hamming of any changed row of any null (0 when
// no null changed a row). ok is false for a floor that does not record it:
// one from NewFloor or from a "semq-floor/1" report.
func (f *Floor) MaxHamming() (maxHamming uint64, ok bool) { return f.maxHamming, f.hasMax }

// Report renders the Floor in the report form: FloorVersion2 with
// MaxHamming when the floor records it, FloorVersion otherwise.
func (f *Floor) Report() FloorReport {
	r := FloorReport{
		Version:     FloorVersion,
		Config:      f.cfg.report(),
		IDKind:      f.kind.String(),
		ReferenceID: hex.EncodeToString(f.reference[:]),
		Nulls:       f.nulls,
		ChangedRows: f.changedRows,
		TotalRows:   f.totalRows,
		Hamming:     f.hamming,
	}
	if f.hasMax {
		r.Version, r.MaxHamming = FloorVersion2, f.maxHamming
	}
	return r
}

// String is "Floor(1 of 3 rows, hamming 1, from 3 nulls)", the same text as
// the other bindings. It reads cached fields, so it works on a closed Floor.
func (f *Floor) String() string {
	return fmt.Sprintf("Floor(%d of %d rows, hamming %d, from %d nulls)", f.changedRows, f.totalRows, f.hamming, f.nulls)
}
