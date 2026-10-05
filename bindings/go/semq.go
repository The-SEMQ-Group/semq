// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

package semq

/*
// The core is compiled from internal/core, a copy of the C sources that
// tools/gen_go_core.py keeps in sync.
#cgo CFLAGS: -I${SRCDIR}/internal/core/include
#include "semq.h"
*/
import "C"

import (
	"math"
	"runtime"
	"unsafe"

	// Links the C core into the binary.
	_ "github.com/The-SEMQ-Group/semq/bindings/go/internal/core"
)

// none is SEMQ_NONE: "no row" / "no field".
const none = ^uint64(0)

// optU64 maps SEMQ_NONE to nil.
func optU64(v C.uint64_t) *uint64 {
	if uint64(v) == none {
		return nil
	}
	u := uint64(v)
	return &u
}

// copyBytes copies n bytes of core-owned memory into a fresh slice.
func copyBytes(p *C.uint8_t, n uint64) []byte {
	out := make([]byte, n)
	if n > 0 {
		copy(out, unsafe.Slice((*byte)(unsafe.Pointer(p)), int(n)))
	}
	return out
}

// goString copies n bytes of core-owned memory into a string.
func goString(p *C.uint8_t, n uint64) string {
	if n == 0 {
		return ""
	}
	return string(unsafe.Slice((*byte)(unsafe.Pointer(p)), int(n)))
}

// utf8Arg exposes a Go string to the core for the duration of one call.
func utf8Arg(s string) (*C.uint8_t, C.uint64_t) {
	if len(s) == 0 {
		return nil, 0
	}
	return (*C.uint8_t)(unsafe.Pointer(unsafe.StringData(s))), C.uint64_t(len(s))
}

// cManifest is a semq_pair_t array whose pointers lead into pinned Go memory.
type cManifest struct {
	pairs []C.semq_pair_t
	pin   runtime.Pinner
}

func (m *cManifest) ptr() *C.semq_pair_t {
	if len(m.pairs) == 0 {
		return nil
	}
	return &m.pairs[0]
}

func (m *cManifest) n() C.uint32_t { return C.uint32_t(len(m.pairs)) }

func (m *cManifest) release() { m.pin.Unpin() }

// manifestToC packs a manifest into one blob plus a pair table. Only the
// representation is checked here; the limits are the core's.
func manifestToC(manifest map[string]string) (*cManifest, error) {
	m := &cManifest{}
	if len(manifest) == 0 {
		return m, nil
	}
	if uint64(len(manifest)) > math.MaxUint32 {
		return nil, &InvalidInputError{Message: "manifest has too many pairs"}
	}
	total := 0
	for k, v := range manifest {
		if uint64(len(k)) > math.MaxUint32 || uint64(len(v)) > math.MaxUint32 {
			return nil, &InvalidInputError{Message: "manifest text is too long"}
		}
		pairSize, err := sumSize(len(k), len(v))
		if err != nil {
			return nil, err
		}
		total, err = sumSize(total, pairSize)
		if err != nil {
			return nil, err
		}
	}
	type span struct{ koff, klen, voff, vlen int }
	spans := make([]span, 0, len(manifest))
	blob := make([]byte, 0, total)
	for k, v := range manifest {
		s := span{koff: len(blob), klen: len(k)}
		blob = append(blob, k...)
		s.voff, s.vlen = len(blob), len(v)
		blob = append(blob, v...)
		spans = append(spans, s)
	}
	var base unsafe.Pointer
	if len(blob) > 0 {
		m.pin.Pin(&blob[0])
		base = unsafe.Pointer(&blob[0])
	}
	at := func(off, n int) *C.uint8_t {
		if n == 0 {
			return nil
		}
		return (*C.uint8_t)(unsafe.Add(base, off))
	}
	m.pairs = make([]C.semq_pair_t, len(spans))
	for i, s := range spans {
		m.pairs[i] = C.semq_pair_t{
			key:       at(s.koff, s.klen),
			key_len:   C.uint32_t(s.klen),
			value:     at(s.voff, s.vlen),
			value_len: C.uint32_t(s.vlen),
		}
	}
	return m, nil
}

// abiCount checks a host collection count before narrowing it for the ABI.
func abiCount(n uint64) (C.uint32_t, error) {
	if n > math.MaxUint32 {
		return 0, &InvalidInputError{Message: "collection count does not fit the C ABI"}
	}
	return C.uint32_t(n), nil
}

// sumSize checks host allocation arithmetic without imposing core limits.
func sumSize(a, b int) (int, error) {
	if a < 0 || b < 0 || a > int(^uint(0)>>1)-b {
		return 0, &InvalidInputError{Message: "buffer size does not fit the host"}
	}
	return a + b, nil
}
