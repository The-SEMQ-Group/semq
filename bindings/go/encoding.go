// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

package semq

/*
#include "semq.h"
*/
import "C"

import (
	"encoding/hex"
	"fmt"
	"io"
	"math"
	"runtime"
	"unsafe"
)

// Encoding is an immutable set of ids with one canonical row each, a
// manifest and two identities: ContentDigest identifies the rows under the
// rule, StateID adds the manifest. Equality of two Encodings is equality of
// StateID. It is safe for concurrent use. Call Close when done; a finalizer
// is the fallback. Close must not race with another method.
//
// Accessors return copies. Those without an error result (Rows, Row,
// IDsU64, IDsUTF8, Manifest, Bytes) panic on a closed Encoding; Config,
// IDKind, Len, ContentDigest and StateID are cached and always available.
// Copies share ownership: closing any copy closes them all.
type Encoding struct {
	owner   *nativeOwner
	cfg     CodecConfig
	kind    IDKind
	n       uint64
	content [32]byte
	state   [32]byte
}

func newEncoding(p *C.semq_encoding_t) *Encoding {
	e := &Encoding{
		owner: newOwner(unsafe.Pointer(p), func(p unsafe.Pointer) { C.semq_encoding_free((*C.semq_encoding_t)(p)) }),
		cfg:   configFromC(C.semq_encoding_config(p)),
		kind:  IDKind(C.semq_encoding_id_kind(p)),
		n:     uint64(C.semq_encoding_len(p)),
	}
	C.semq_encoding_content_digest(p, (*C.uint8_t)(unsafe.Pointer(&e.content[0])))
	C.semq_encoding_state_id(p, (*C.uint8_t)(unsafe.Pointer(&e.state[0])))
	return e
}

// NewEncoding builds an Encoding from rows the caller already holds:
// len(ids) rows of cfg.BytesPerVector() bytes, contiguous, aligned with ids
// (any order). The core sorts, rejects duplicate ids and non-canonical rows
// (InvalidInputError with the input row), validates the manifest, copies the
// rows once and computes both digests. manifest may be nil.
func NewEncoding(ids IDs, rows []byte, cfg CodecConfig, manifest map[string]string) (*Encoding, error) {
	if err := cfg.validate(); err != nil {
		return nil, err
	}
	cids, err := idsToC(ids)
	if err != nil {
		return nil, err
	}
	defer cids.release()
	n, bpv := cids.n(), uint64(cfg.BytesPerVector())
	if n > math.MaxUint64/bpv || uint64(len(rows)) != n*bpv {
		return nil, &InvalidInputError{Message: fmt.Sprintf(
			"%d ids need %d row bytes (%d per row), got %d", n, n*bpv, bpv, len(rows))}
	}
	man, err := manifestToC(manifest)
	if err != nil {
		return nil, err
	}
	defer man.release()
	var rp *C.uint8_t
	if len(rows) > 0 {
		rp = (*C.uint8_t)(unsafe.Pointer(&rows[0]))
	}
	cc := cfg.toC()
	var (
		out *C.semq_encoding_t
		e   C.semq_error_t
	)
	s := C.semq_encoding_create(&cc, &cids.s, rp, man.ptr(), man.n(), &out, &e)
	if err := check(s, &e, "encoding"); err != nil {
		return nil, err
	}
	return newEncoding(out), nil
}

// Load parses a complete file image. The bytes are validated in file order
// (framing, config, sizes, ids, manifest, both digests, rows) and copied.
func Load(b []byte) (*Encoding, error) {
	buf := b
	if len(buf) == 0 {
		buf = []byte{0} // a non-nil pointer with length 0: the core reports the framing error
	}
	var (
		out *C.semq_encoding_t
		e   C.semq_error_t
	)
	s := C.semq_encoding_load((*C.uint8_t)(unsafe.Pointer(&buf[0])), C.uint64_t(len(b)), &out, &e)
	if err := check(s, &e, "load"); err != nil {
		return nil, err
	}
	return newEncoding(out), nil
}

// Read reads a whole file image from r and loads it. Read errors are
// returned as they are.
func Read(r io.Reader) (*Encoding, error) {
	data, err := io.ReadAll(r)
	if err != nil {
		return nil, err
	}
	return Load(data)
}

// Close releases the native handle. It is idempotent. A Diff built from this
// Encoding stays valid.
func (e *Encoding) Close() {
	if e != nil {
		e.owner.close()
	}
}

func (e *Encoding) handle() (*C.semq_encoding_t, error) {
	if e == nil {
		return nil, &InvalidInputError{Message: "encoding is nil"}
	}
	p := (*C.semq_encoding_t)(e.owner.pointer())
	if p == nil {
		return nil, &InvalidInputError{Message: "encoding is closed"}
	}
	return p, nil
}

func (e *Encoding) mustHandle() *C.semq_encoding_t {
	p, err := e.handle()
	if err != nil {
		panic(err)
	}
	return p
}

// WriteTo writes the file image to w and implements io.WriterTo.
func (e *Encoding) WriteTo(w io.Writer) (int64, error) {
	h, err := e.handle()
	if err != nil {
		return 0, err
	}
	defer runtime.KeepAlive(e)
	var parts [5]C.semq_part_t
	C.semq_encoding_save_parts(h, &parts[0])
	var total int64
	for _, p := range parts {
		if p.len == 0 {
			continue
		}
		part := unsafe.Slice((*byte)(unsafe.Pointer(p.ptr)), int(p.len))
		n, err := w.Write(part)
		if n < 0 || n > len(part) {
			return total, fmt.Errorf("semq: writer returned invalid byte count %d for %d-byte part", n, len(part))
		}
		total += int64(n)
		if err != nil {
			return total, err
		}
		if n != len(part) {
			return total, io.ErrShortWrite
		}
	}
	return total, nil
}

// Bytes returns a copy of the file image.
func (e *Encoding) Bytes() []byte {
	h := e.mustHandle()
	defer runtime.KeepAlive(e)
	out := make([]byte, uint64(C.semq_encoding_file_size(h)))
	var err C.semq_error_t
	mustOK(C.semq_encoding_save(h, (*C.uint8_t)(unsafe.Pointer(&out[0])), C.uint64_t(len(out)), &err), &err, "save")
	return out
}

// Config reports the config the rows were produced under.
func (e *Encoding) Config() CodecConfig { return e.cfg }

// IDKind reports the id kind.
func (e *Encoding) IDKind() IDKind { return e.kind }

// Len reports the number of rows.
func (e *Encoding) Len() int { return int(e.n) }

// ContentDigest identifies the rows under the rule.
func (e *Encoding) ContentDigest() [32]byte { return e.content }

// StateID identifies the rows plus the manifest.
func (e *Encoding) StateID() [32]byte { return e.state }

// Rows returns a copy of the canonical rows in id order, n*BytesPerVector
// bytes.
func (e *Encoding) Rows() []byte {
	h := e.mustHandle()
	defer runtime.KeepAlive(e)
	var l C.uint64_t
	p := C.semq_encoding_rows(h, &l)
	return copyBytes(p, uint64(l))
}

// Row returns a copy of row i (in id order). It panics when i is out of
// range, as a slice index would.
func (e *Encoding) Row(i int) []byte {
	if i < 0 || uint64(i) >= e.n {
		panic(fmt.Sprintf("semq: row index %d out of range [0, %d)", i, e.n))
	}
	h := e.mustHandle()
	defer runtime.KeepAlive(e)
	var l C.uint64_t
	p := C.semq_encoding_rows(h, &l)
	bpv := uint64(e.cfg.BytesPerVector())
	return copyBytes((*C.uint8_t)(unsafe.Add(unsafe.Pointer(p), uint64(i)*bpv)), bpv)
}

// IDsU64 returns a copy of the sorted ids, or nil for a utf8 Encoding.
func (e *Encoding) IDsU64() []uint64 {
	if e.kind != IDU64 {
		return nil
	}
	h := e.mustHandle()
	defer runtime.KeepAlive(e)
	out := make([]uint64, e.n)
	if e.n > 0 {
		copy(out, unsafe.Slice((*uint64)(unsafe.Pointer(C.semq_encoding_ids_u64(h))), int(e.n)))
	}
	return out
}

// IDsUTF8 returns a copy of the sorted ids, or nil for a u64 Encoding.
func (e *Encoding) IDsUTF8() []string {
	if e.kind != IDUTF8 {
		return nil
	}
	h := e.mustHandle()
	defer runtime.KeepAlive(e)
	out := make([]string, e.n)
	if e.n == 0 {
		return out
	}
	offsets := unsafe.Slice((*uint64)(unsafe.Pointer(C.semq_encoding_ids_utf8_offsets(h))), int(e.n)+1)
	var l C.uint64_t
	bp := C.semq_encoding_ids_utf8_bytes(h, &l)
	var data []byte
	if l > 0 {
		data = unsafe.Slice((*byte)(unsafe.Pointer(bp)), int(l))
	}
	for i := range out {
		out[i] = string(data[offsets[i]:offsets[i+1]])
	}
	return out
}

// Get returns a copy of the row of id. ok is false when id is absent.
// InvalidInputError when id.Kind differs from the Encoding's kind.
func (e *Encoding) Get(id ID) (row []byte, ok bool, err error) {
	h, err := e.handle()
	if err != nil {
		return nil, false, err
	}
	defer runtime.KeepAlive(e)
	var (
		index C.uint64_t
		ce    C.semq_error_t
		s     C.semq_status_t
	)
	switch id.Kind {
	case IDU64:
		s = C.semq_encoding_find_u64(h, C.uint64_t(id.U64), &index, &ce)
	case IDUTF8:
		p, l := utf8Arg(id.UTF8)
		s = C.semq_encoding_find_utf8(h, p, l, &index, &ce)
	default:
		return nil, false, &InvalidInputError{Message: "id kind must be IDU64 or IDUTF8"}
	}
	if err := check(s, &ce, "get"); err != nil {
		return nil, false, err
	}
	if uint64(index) == none {
		return nil, false, nil
	}
	return e.Row(int(index)), true, nil
}

// Manifest returns a copy of the manifest.
func (e *Encoding) Manifest() map[string]string {
	h := e.mustHandle()
	defer runtime.KeepAlive(e)
	n := uint32(C.semq_encoding_manifest_len(h))
	out := make(map[string]string, n)
	for i := uint32(0); i < n; i++ {
		var (
			p  C.semq_pair_t
			ce C.semq_error_t
		)
		mustOK(C.semq_encoding_manifest_pair(h, C.uint32_t(i), &p, &ce), &ce, "manifest")
		out[goString(p.key, uint64(p.key_len))] = goString(p.value, uint64(p.value_len))
	}
	return out
}

// Concat merges e with others: same config and id kind (else IncompatibleError),
// same manifest and pairwise-disjoint ids (else InvalidInputError with
// Field = part index). The result does not depend on the order of the parts.
func (e *Encoding) Concat(others ...*Encoding) (*Encoding, error) {
	count, countErr := abiCount(uint64(len(others)) + 1)
	if countErr != nil {
		return nil, countErr
	}
	capacity, sizeErr := sumSize(len(others), 1)
	if sizeErr != nil {
		return nil, sizeErr
	}
	all := make([]*Encoding, 0, capacity)
	all = append(all, e)
	all = append(all, others...)
	parts := make([]*C.semq_encoding_t, len(all))
	for i, p := range all {
		h, err := p.handle()
		if err != nil {
			return nil, err
		}
		parts[i] = h
	}
	var (
		out *C.semq_encoding_t
		ce  C.semq_error_t
	)
	s := C.semq_encoding_concat((**C.semq_encoding_t)(unsafe.Pointer(&parts[0])), count, &out, &ce)
	for _, p := range all {
		runtime.KeepAlive(p)
	}
	if err := check(s, &ce, "concat"); err != nil {
		return nil, err
	}
	return newEncoding(out), nil
}

// Diff compares e (the reference) with candidate. IncompatibleError when the
// configs or id kinds differ. The Diff keeps the rows it needs alive until it
// is closed, even if both Encodings are closed first.
func (e *Encoding) Diff(candidate *Encoding) (*Diff, error) {
	rh, err := e.handle()
	if err != nil {
		return nil, err
	}
	ch, err := candidate.handle()
	if err != nil {
		return nil, err
	}
	var (
		out *C.semq_diff_t
		ce  C.semq_error_t
	)
	s := C.semq_encoding_diff(rh, ch, &out, &ce)
	runtime.KeepAlive(e)
	runtime.KeepAlive(candidate)
	if err := check(s, &ce, "diff"); err != nil {
		return nil, err
	}
	return newDiff(out), nil
}

// String is "Encoding(3 rows, quant(dim=4, bins=4), state_id 40c3aa20252d...)",
// the same text as the other bindings. It reads cached fields, so it works on
// a closed Encoding.
func (e *Encoding) String() string {
	return fmt.Sprintf("Encoding(%d rows, %s, state_id %s...)", e.n, e.cfg, hex.EncodeToString(e.state[:6]))
}
