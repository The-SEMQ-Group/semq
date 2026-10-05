// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

package semq

/*
#include "semq.h"
*/
import "C"

import (
	"bytes"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"runtime"
	"slices"
	"sort"
	"strconv"
	"strings"
	"unsafe"
)

// Diff is the result of reference.Diff(candidate). It is immutable and safe
// for concurrent use. Call Close when done; a finalizer is the fallback.
// Copies share ownership: closing any copy closes them all.
// Close must not race with another method. Accessors without an error
// result panic on a closed Diff, except the cached Config, IDKind,
// ReferenceID, CandidateID and NUnchanged.
type Diff struct {
	owner      *nativeOwner
	cfg        CodecConfig
	kind       IDKind
	reference  [32]byte
	candidate  [32]byte
	nUnchanged uint64
}

// Change is one id present on both sides with different rows. Hamming is
// the number of units whose symbol differs.
type Change struct {
	ID      ID
	Hamming uint64
}

// ManifestChange is one manifest key that differs or exists on one side
// only. A nil side means the key is absent there.
type ManifestChange struct {
	Before, After *string
}

// Unit is one differing unit of a changed row.
type Unit struct {
	Unit                 uint32
	Reference, Candidate uint8
}

func newDiff(p *C.semq_diff_t) *Diff {
	d := &Diff{
		owner:      newOwner(unsafe.Pointer(p), func(p unsafe.Pointer) { C.semq_diff_free((*C.semq_diff_t)(p)) }),
		cfg:        configFromC(C.semq_diff_config(p)),
		kind:       IDKind(C.semq_diff_id_kind(p)),
		nUnchanged: uint64(C.semq_diff_n_unchanged(p)),
	}
	C.semq_diff_reference_id(p, (*C.uint8_t)(unsafe.Pointer(&d.reference[0])))
	C.semq_diff_candidate_id(p, (*C.uint8_t)(unsafe.Pointer(&d.candidate[0])))
	return d
}

// Close releases the native handle and the rows it retained. Idempotent.
func (d *Diff) Close() {
	if d != nil {
		d.owner.close()
	}
}

func (d *Diff) handle() (*C.semq_diff_t, error) {
	if d == nil {
		return nil, &InvalidInputError{Message: "diff is nil"}
	}
	p := (*C.semq_diff_t)(d.owner.pointer())
	if p == nil {
		return nil, &InvalidInputError{Message: "diff is closed"}
	}
	return p, nil
}

func (d *Diff) mustHandle() *C.semq_diff_t {
	p, err := d.handle()
	if err != nil {
		panic(err)
	}
	return p
}

// Config reports the config shared by both sides.
func (d *Diff) Config() CodecConfig { return d.cfg }

// IDKind reports the id kind shared by both sides.
func (d *Diff) IDKind() IDKind { return d.kind }

// ReferenceID is the reference's StateID.
func (d *Diff) ReferenceID() [32]byte { return d.reference }

// CandidateID is the candidate's StateID.
func (d *Diff) CandidateID() [32]byte { return d.candidate }

// NUnchanged counts the ids present on both sides with identical rows.
func (d *Diff) NUnchanged() uint64 { return d.nUnchanged }

func (d *Diff) ids(h *C.semq_diff_t, list C.uint32_t) []ID {
	n := uint64(C.semq_diff_count(h, list))
	out := make([]ID, n)
	for i := uint64(0); i < n; i++ {
		var (
			u  C.uint64_t
			bp *C.uint8_t
			bl C.uint64_t
			ce C.semq_error_t
		)
		mustOK(C.semq_diff_id(h, list, C.uint64_t(i), &u, &bp, &bl, &ce), &ce, "diff")
		if d.kind == IDU64 {
			out[i] = U64ID(uint64(u))
		} else {
			out[i] = UTF8ID(goString(bp, uint64(bl)))
		}
	}
	return out
}

// Added lists the ids only in the candidate, in canonical order.
func (d *Diff) Added() []ID {
	h := d.mustHandle()
	defer runtime.KeepAlive(d)
	return d.ids(h, C.SEMQ_LIST_ADDED)
}

// Removed lists the ids only in the reference, in canonical order.
func (d *Diff) Removed() []ID {
	h := d.mustHandle()
	defer runtime.KeepAlive(d)
	return d.ids(h, C.SEMQ_LIST_REMOVED)
}

// Changed lists the ids on both sides with different rows, in canonical
// order, with their hamming distances.
func (d *Diff) Changed() []Change {
	h := d.mustHandle()
	defer runtime.KeepAlive(d)
	ids := d.ids(h, C.SEMQ_LIST_CHANGED)
	out := make([]Change, len(ids))
	for i, id := range ids {
		var (
			hm C.uint64_t
			ce C.semq_error_t
		)
		mustOK(C.semq_diff_hamming(h, C.uint64_t(i), &hm, &ce), &ce, "diff")
		out[i] = Change{ID: id, Hamming: uint64(hm)}
	}
	return out
}

// ManifestChanges maps each key whose value differs, or that exists on one
// side only, to its before and after values.
func (d *Diff) ManifestChanges() map[string]ManifestChange {
	h := d.mustHandle()
	defer runtime.KeepAlive(d)
	n := uint32(C.semq_diff_manifest_changes(h))
	out := make(map[string]ManifestChange, n)
	for i := uint32(0); i < n; i++ {
		var (
			m  C.semq_manifest_change_t
			ce C.semq_error_t
		)
		mustOK(C.semq_diff_manifest_change(h, C.uint32_t(i), &m, &ce), &ce, "diff")
		var mc ManifestChange
		if m.has_before != 0 {
			s := goString(m.before, uint64(m.before_len))
			mc.Before = &s
		}
		if m.has_after != 0 {
			s := goString(m.after, uint64(m.after_len))
			mc.After = &s
		}
		out[goString(m.key, uint64(m.key_len))] = mc
	}
	return out
}

// Units lists the differing units of an id present on both sides, empty for
// an identical row. InvalidInputError when the id is absent from either side
// or its kind does not match.
func (d *Diff) Units(id ID) ([]Unit, error) {
	h, err := d.handle()
	if err != nil {
		return nil, err
	}
	defer runtime.KeepAlive(d)
	capU := d.cfg.UnitsPerRow()
	n := int(capU)
	if n == 0 {
		n = 1
	}
	units := make([]C.uint32_t, n)
	ref := make([]C.uint8_t, n)
	cand := make([]C.uint8_t, n)
	var (
		count C.uint64_t
		ce    C.semq_error_t
		s     C.semq_status_t
	)
	switch id.Kind {
	case IDU64:
		s = C.semq_diff_units_u64(h, C.uint64_t(id.U64), &units[0], &ref[0], &cand[0], C.uint64_t(capU), &count, &ce)
	case IDUTF8:
		p, l := utf8Arg(id.UTF8)
		s = C.semq_diff_units_utf8(h, p, l, &units[0], &ref[0], &cand[0], C.uint64_t(capU), &count, &ce)
	default:
		return nil, &InvalidInputError{Message: "id kind must be IDU64 or IDUTF8"}
	}
	if err := check(s, &ce, "units"); err != nil {
		return nil, err
	}
	out := make([]Unit, uint64(count))
	for i := range out {
		out[i] = Unit{Unit: uint32(units[i]), Reference: uint8(ref[i]), Candidate: uint8(cand[i])}
	}
	return out, nil
}

// Within reports whether the candidate is within f: at least one row in
// common, no removed rows, at most f.ChangedRows()/f.TotalRows() of the
// common rows changed, p99 of the hamming distances at most f.Hamming() and
// no change to the manifest keys encoder or encoder_revision. Exact integer
// arithmetic in the core. IncompatibleError when f was measured against
// another config, id kind or reference than this diff's.
func (d *Diff) Within(f *Floor) (bool, error) {
	h, err := d.handle()
	if err != nil {
		return false, err
	}
	defer runtime.KeepAlive(d)
	fh, err := f.handle()
	if err != nil {
		return false, err
	}
	defer runtime.KeepAlive(f)
	var (
		out C.int
		ce  C.semq_error_t
	)
	if err := check(C.semq_diff_within(h, fh, &out, &ce), &ce, "within"); err != nil {
		return false, err
	}
	return out != 0, nil
}

// Report renders the Diff in the report schema.
func (d *Diff) Report() Report {
	r := Report{
		ReferenceID:     hex.EncodeToString(d.reference[:]),
		CandidateID:     hex.EncodeToString(d.candidate[:]),
		IDKind:          d.kind.String(),
		Config:          d.cfg.report(),
		Added:           []string{},
		Removed:         []string{},
		Changed:         []ChangeReport{},
		NUnchanged:      d.nUnchanged,
		ManifestChanges: map[string][2]*string{},
	}
	for _, id := range d.Added() {
		r.Added = append(r.Added, id.String())
	}
	for _, id := range d.Removed() {
		r.Removed = append(r.Removed, id.String())
	}
	for _, c := range d.Changed() {
		r.Changed = append(r.Changed, ChangeReport{ID: c.ID.String(), Hamming: c.Hamming})
	}
	for k, mc := range d.ManifestChanges() {
		r.ManifestChanges[k] = [2]*string{mc.Before, mc.After}
	}
	return r
}

// Report is the Diff report schema. u64 ids are decimal strings, utf8 ids
// are the strings themselves, digests are lowercase hex; no floats.
type Report struct {
	ReferenceID     string                `json:"reference_id"`
	CandidateID     string                `json:"candidate_id"`
	IDKind          string                `json:"id_kind"`
	Config          ConfigReport          `json:"config"`
	Added           []string              `json:"added"`
	Removed         []string              `json:"removed"`
	Changed         []ChangeReport        `json:"changed"`
	NUnchanged      uint64                `json:"n_unchanged"`
	ManifestChanges map[string][2]*string `json:"manifest_changes"`
}

// ConfigReport is the config entry of a Report. It marshals as
// {"operator", "dim", "bins" | "sectors" | "scale", "rule_revision"}.
type ConfigReport struct {
	Operator     string
	Dim          uint32
	Parameter    uint32
	RuleRevision uint32
}

// MarshalJSON emits the parameter under its operator-specific key.
func (c ConfigReport) MarshalJSON() ([]byte, error) {
	key := "parameter"
	for _, op := range []Operator{OperatorOrbit, OperatorPhase, OperatorQuant} {
		if op.String() == c.Operator {
			key = op.parameterName()
		}
	}
	op, err := json.Marshal(c.Operator)
	if err != nil {
		return nil, err
	}
	var b bytes.Buffer
	b.WriteString(`{"operator":`)
	b.Write(op)
	fmt.Fprintf(&b, `,"dim":%d,%q:%d,"rule_revision":%d}`, c.Dim, key, c.Parameter, c.RuleRevision)
	return b.Bytes(), nil
}

// UnmarshalJSON reads the config entry strictly: exactly the keys operator,
// dim, the operator's parameter key and rule_revision; operator one of
// "orbit", "phase" or "quant"; the others non-negative JSON integers that
// fit in 32 bits (no null, booleans, floats, exponents or numeric
// strings). Any other shape is InvalidInputError naming the key.
func (c *ConfigReport) UnmarshalJSON(b []byte) error {
	const what = "config report"
	fields, err := reportObject(b, what)
	if err != nil {
		return err
	}
	if _, ok := fields["operator"]; !ok {
		return &InvalidInputError{Message: what + " is missing key \"operator\""}
	}
	operator, err := reportString(fields, what, "operator")
	if err != nil {
		return err
	}
	key := ""
	for _, op := range []Operator{OperatorOrbit, OperatorPhase, OperatorQuant} {
		if op.String() == operator {
			key = op.parameterName()
		}
	}
	if key == "" {
		return &InvalidInputError{Message: what + " operator must be orbit, phase or quant"}
	}
	if err := reportKeys(fields, what, "operator", "dim", key, "rule_revision"); err != nil {
		return err
	}
	dim, err := reportUint(fields, what, "dim", 32)
	if err != nil {
		return err
	}
	param, err := reportUint(fields, what, key, 32)
	if err != nil {
		return err
	}
	revision, err := reportUint(fields, what, "rule_revision", 32)
	if err != nil {
		return err
	}
	*c = ConfigReport{Operator: operator, Dim: uint32(dim), Parameter: uint32(param), RuleRevision: uint32(revision)}
	return nil
}

// The strict readers of the report forms. Each takes a syntactically valid
// JSON value, as encoding/json hands it to an Unmarshaler, and returns
// InvalidInputError for any shape the schema does not allow; what names
// the form in the message.

// reportObject decodes b as a JSON object into its raw members.
func reportObject(b []byte, what string) (map[string]json.RawMessage, error) {
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(b, &fields); err != nil || fields == nil {
		return nil, &InvalidInputError{Message: what + " must be a JSON object"}
	}
	return fields, nil
}

// reportKeys requires fields to hold exactly keys. A missing key is
// reported first, then the unknown key that sorts first.
func reportKeys(fields map[string]json.RawMessage, what string, keys ...string) error {
	for _, k := range keys {
		if _, ok := fields[k]; !ok {
			return &InvalidInputError{Message: what + " is missing key " + strconv.Quote(k)}
		}
	}
	if len(fields) == len(keys) {
		return nil
	}
	var unknown []string
	for k := range fields {
		if !slices.Contains(keys, k) {
			unknown = append(unknown, k)
		}
	}
	sort.Strings(unknown)
	return &InvalidInputError{Message: what + " has unknown key " + strconv.Quote(unknown[0])}
}

// reportString reads fields[key] as a JSON string.
func reportString(fields map[string]json.RawMessage, what, key string) (string, error) {
	raw := fields[key]
	var s string
	if len(raw) == 0 || raw[0] != '"' || json.Unmarshal(raw, &s) != nil {
		return "", &InvalidInputError{Message: what + " key " + strconv.Quote(key) + " must be a string"}
	}
	return s, nil
}

// reportUint reads fields[key] as a non-negative JSON integer of at most
// bits bits: a run of digits, so no null, boolean, string, sign, fraction
// or exponent.
func reportUint(fields map[string]json.RawMessage, what, key string, bits int) (uint64, error) {
	raw := fields[key]
	for _, c := range raw {
		if c < '0' || c > '9' {
			return 0, &InvalidInputError{Message: what + " key " + strconv.Quote(key) + " must be a non-negative integer"}
		}
	}
	n, err := strconv.ParseUint(string(raw), 10, bits)
	if err != nil {
		if len(raw) == 0 {
			return 0, &InvalidInputError{Message: what + " key " + strconv.Quote(key) + " must be a non-negative integer"}
		}
		return 0, &InvalidInputError{Message: what + " key " + strconv.Quote(key) + " does not fit in " + strconv.Itoa(bits) + " bits"}
	}
	return n, nil
}

// config rebuilds the CodecConfig of a report; InvalidInputError when the
// operator is unknown. The core validates the fields when the config is
// used.
func (c ConfigReport) config() (CodecConfig, error) {
	for _, op := range []Operator{OperatorOrbit, OperatorPhase, OperatorQuant} {
		if op.String() == c.Operator {
			return CodecConfig{op: uint32(op), dim: c.Dim, p1: c.Parameter, p2: c.RuleRevision}, nil
		}
	}
	return CodecConfig{}, &InvalidInputError{Message: "config report operator must be orbit, phase or quant"}
}

// ChangeReport is one entry of Report.Changed. It marshals as the pair
// [id, hamming].
type ChangeReport struct {
	ID      string
	Hamming uint64
}

// MarshalJSON emits [id, hamming].
func (c ChangeReport) MarshalJSON() ([]byte, error) {
	return json.Marshal([2]any{c.ID, c.Hamming})
}

// String is one sentence, the same text as the other bindings:
// "1 of 3 rows changed: doc-3 (hamming 3). 0 added, 0 removed."
// Up to five changed ids are listed; changed manifest keys are named at the
// end. A closed Diff reads "Diff(closed)".
func (d *Diff) String() string {
	if _, err := d.handle(); err != nil {
		return "Diff(closed)"
	}
	changed := d.Changed()
	var b strings.Builder
	fmt.Fprintf(&b, "%d of %d rows changed", len(changed), uint64(len(changed))+d.NUnchanged())
	if len(changed) > 0 {
		b.WriteString(": ")
		for i, c := range changed {
			if i == 5 {
				break
			}
			if i > 0 {
				b.WriteString(", ")
			}
			fmt.Fprintf(&b, "%s (hamming %d)", c.ID, c.Hamming)
		}
		if len(changed) > 5 {
			fmt.Fprintf(&b, ", and %d more", len(changed)-5)
		}
	}
	fmt.Fprintf(&b, ". %d added, %d removed.", len(d.Added()), len(d.Removed()))
	if m := d.ManifestChanges(); len(m) > 0 {
		keys := make([]string, 0, len(m))
		for k := range m {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		fmt.Fprintf(&b, " Manifest changed: %s.", strings.Join(keys, ", "))
	}
	return b.String()
}
