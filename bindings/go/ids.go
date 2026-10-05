// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

package semq

/*
#include "semq.h"
*/
import "C"

import (
	"fmt"
	"runtime"
	"strconv"
	"unsafe"
)

// IDKind is the identifier kind of an Encoding. Values are pinned: they
// appear in files.
type IDKind uint8

const (
	// IDU64: unsigned 64-bit ids, ordered numerically.
	IDU64 IDKind = 0
	// IDUTF8: UTF-8 string ids of 1 to 4096 bytes, ordered bytewise.
	IDUTF8 IDKind = 1
)

// String returns the report name of the kind: "u64" or "utf8".
func (k IDKind) String() string {
	switch k {
	case IDU64:
		return "u64"
	case IDUTF8:
		return "utf8"
	}
	return fmt.Sprintf("IDKind(%d)", uint8(k))
}

// ID is one identifier of either kind. Kind selects which field is meaningful.
type ID struct {
	Kind IDKind
	U64  uint64
	UTF8 string
}

// U64ID builds a u64 ID.
func U64ID(v uint64) ID { return ID{Kind: IDU64, U64: v} }

// UTF8ID builds a utf8 ID. Go strings are arbitrary bytes; the core rejects
// ids that are not valid UTF-8.
func UTF8ID(s string) ID { return ID{Kind: IDUTF8, UTF8: s} }

// String renders a u64 id in decimal and a utf8 id as is.
func (id ID) String() string {
	if id.Kind == IDUTF8 {
		return id.UTF8
	}
	return strconv.FormatUint(id.U64, 10)
}

// IDs is the identifier set of one Encoding, in any order (the core sorts).
// Exactly one of U64 and UTF8 is used; whichever is non-empty decides the
// kind. Kind is consulted only when both are empty, which is how an empty
// Encoding states its kind. U64IDs and UTF8IDs set it.
type IDs struct {
	Kind IDKind
	U64  []uint64
	UTF8 []string
}

// U64IDs builds a u64 id set. U64IDs() is the empty u64 set.
func U64IDs(ids ...uint64) IDs { return IDs{Kind: IDU64, U64: ids} }

// UTF8IDs builds a utf8 id set. UTF8IDs() is the empty utf8 set.
func UTF8IDs(ids ...string) IDs { return IDs{Kind: IDUTF8, UTF8: ids} }

// resolve returns the effective kind and count.
func (ids IDs) resolve() (IDKind, int, error) {
	switch {
	case len(ids.U64) > 0 && len(ids.UTF8) > 0:
		return 0, 0, &InvalidInputError{Message: "ids mix u64 and utf8"}
	case len(ids.U64) > 0:
		return IDU64, len(ids.U64), nil
	case len(ids.UTF8) > 0:
		return IDUTF8, len(ids.UTF8), nil
	case ids.Kind == IDU64 || ids.Kind == IDUTF8:
		return ids.Kind, 0, nil
	}
	return 0, 0, &InvalidInputError{Message: "id kind must be IDU64 or IDUTF8"}
}

// cIDs is a semq_ids_t whose pointers lead into pinned Go memory.
type cIDs struct {
	s   C.semq_ids_t
	pin runtime.Pinner
}

func (c *cIDs) release() { c.pin.Unpin() }

func (c *cIDs) n() uint64 { return uint64(c.s.n) }

// idsToC exposes the id set to the core without copying u64 ids; utf8 ids
// are packed into one blob plus offsets, as the ABI requires.
func idsToC(ids IDs) (*cIDs, error) {
	kind, n, err := ids.resolve()
	if err != nil {
		return nil, err
	}
	c := &cIDs{}
	c.s.kind = C.uint32_t(kind)
	c.s.n = C.uint64_t(n)
	if n == 0 {
		return c, nil
	}
	if kind == IDU64 {
		c.pin.Pin(&ids.U64[0])
		c.s.u64 = (*C.uint64_t)(unsafe.Pointer(&ids.U64[0]))
		return c, nil
	}
	count, sizeErr := sumSize(n, 1)
	if sizeErr != nil {
		return nil, sizeErr
	}
	offsets := make([]uint64, count)
	total := 0
	for i, s := range ids.UTF8 {
		total, err = sumSize(total, len(s))
		if err != nil {
			return nil, err
		}
		offsets[i+1] = uint64(total)
	}
	c.pin.Pin(&offsets[0])
	c.s.utf8_offsets = (*C.uint64_t)(unsafe.Pointer(&offsets[0]))
	if total > 0 {
		blob := make([]byte, 0, total)
		for _, s := range ids.UTF8 {
			blob = append(blob, s...)
		}
		c.pin.Pin(&blob[0])
		c.s.utf8_bytes = (*C.uint8_t)(unsafe.Pointer(&blob[0]))
	}
	return c, nil
}
