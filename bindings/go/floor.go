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

// FloorVersion is the version string of the floor report form.
const FloorVersion = "semq-floor/1"

// Floor is an envelope of observed variation, bound to the context it was
// measured in: the config, the id kind and the StateID of the reference
// every null diff was taken against. A diff is within it when it removes no
// rows, shares at least one row with its reference, changes at most
// ChangedRows/TotalRows of the shared rows, its p99 hamming does not exceed
// Hamming and it changes neither of the manifest keys encoder and
// encoder_revision. No probabilistic coverage is claimed.
//
// A Floor from MeasureFloor also records MaxHamming, the largest hamming of
// any changed row of any null, for the per-row check of Diff.Evaluate. Its
// JSON form, from json.Marshal or LoadFloor, carries it; FloorReport does
// not.
//
// Build one with NewFloor, MeasureFloor, LoadFloor or FloorFromReport. It is immutable
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

// FloorReport is the report form of a Floor, version "semq-floor/1": the
// config as in a Diff Report, the id kind by name, the reference StateID as
// lowercase hex and the counts as integers. It marshals with the keys in
// this order. It does not carry MaxHamming; marshal the Floor itself for
// the complete JSON form. Decoding JSON into it applies the core's rules
// for the floor schema, as LoadFloor does; any violation is
// InvalidInputError.
type FloorReport struct {
	Version     string       `json:"version"`
	Config      ConfigReport `json:"config"`
	IDKind      string       `json:"id_kind"`
	ReferenceID string       `json:"reference_id"`
	Nulls       uint64       `json:"nulls"`
	ChangedRows uint64       `json:"changed_rows"`
	TotalRows   uint64       `json:"total_rows"`
	Hamming     uint64       `json:"hamming"`
}

// UnmarshalJSON reads the floor schema by the core's rules, as LoadFloor
// does. On error r is left as it was.
func (r *FloorReport) UnmarshalJSON(b []byte) error {
	f, err := LoadFloor(b)
	if err != nil {
		return err
	}
	defer f.Close()
	*r = f.Report()
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

// FloorFromReport is the inverse of Report: the report's JSON form, read
// by the core as LoadFloor does. Any violation is InvalidInputError.
func FloorFromReport(r FloorReport) (*Floor, error) {
	b, err := json.Marshal(r)
	if err != nil {
		return nil, &InvalidInputError{Message: "floor report does not marshal: " + err.Error()}
	}
	return LoadFloor(b)
}

// LoadFloor reads a Floor from its JSON form by the core's rules: the keys
// of the floor schema strictly (each at most once, counts as JSON integers,
// max_hamming optional), other keys ignored, and the rules of NewFloor. Any
// violation is InvalidInputError.
func LoadFloor(b []byte) (*Floor, error) {
	var (
		out *C.semq_floor_t
		e   C.semq_error_t
	)
	var p *C.uint8_t
	if len(b) > 0 {
		p = (*C.uint8_t)(unsafe.Pointer(&b[0]))
	}
	s := C.semq_floor_load(p, C.uint64_t(len(b)), &out, &e)
	runtime.KeepAlive(b)
	if err := check(s, &e, "load"); err != nil {
		return nil, err
	}
	return newFloor(out), nil
}

// MarshalJSON writes the floor's JSON form, as the core writes it: the
// floor schema with max_hamming when the floor records it, the same bytes
// in every binding. A closed Floor is InvalidInputError.
func (f *Floor) MarshalJSON() ([]byte, error) {
	h, err := f.handle()
	if err != nil {
		return nil, err
	}
	defer runtime.KeepAlive(f)
	n := uint64(C.semq_floor_json_size(h))
	out := make([]byte, n)
	var e C.semq_error_t
	if err := check(C.semq_floor_save(h, (*C.uint8_t)(unsafe.Pointer(&out[0])), C.uint64_t(n), &e), &e, "save"); err != nil {
		return nil, err
	}
	return out, nil
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
// one from NewFloor or FloorFromReport, or read from JSON without it.
func (f *Floor) MaxHamming() (maxHamming uint64, ok bool) { return f.maxHamming, f.hasMax }

// Report renders the Floor in the report form, without MaxHamming.
func (f *Floor) Report() FloorReport {
	return FloorReport{
		Version:     FloorVersion,
		Config:      f.cfg.report(),
		IDKind:      f.kind.String(),
		ReferenceID: hex.EncodeToString(f.reference[:]),
		Nulls:       f.nulls,
		ChangedRows: f.changedRows,
		TotalRows:   f.totalRows,
		Hamming:     f.hamming,
	}
}

// String is "Floor(1 of 3 rows, hamming 1, from 3 nulls)", the same text as
// the other bindings. It reads cached fields, so it works on a closed Floor.
func (f *Floor) String() string {
	return fmt.Sprintf("Floor(%d of %d rows, hamming %d, from %d nulls)", f.changedRows, f.totalRows, f.hamming, f.nulls)
}
