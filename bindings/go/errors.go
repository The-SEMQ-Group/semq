// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

package semq

/*
#include "semq.h"
*/
import "C"

import (
	"errors"
	"fmt"
	"strings"
)

// ErrNoMemory is returned (wrapped) when the core cannot allocate. Test for
// it with errors.Is.
var ErrNoMemory = errors.New("semq: out of memory")

// InvalidInputError: an argument violates its contract. Row is the input row
// at fault and Field the coordinate, column, pair index or config field, when
// one applies.
type InvalidInputError struct {
	Row, Field *uint64
	Message    string
}

func (e *InvalidInputError) Error() string {
	return "semq: invalid input: " + e.Message + where(e.Row, "row", e.Field, "field")
}

// IncompatibleError: two states differ in config or id kind.
type IncompatibleError struct {
	Field   *uint64
	Message string
}

func (e *IncompatibleError) Error() string {
	return "semq: incompatible: " + e.Message + where(nil, "", e.Field, "field")
}

// FormatError: a file image is not a valid version 2 image. Section is the
// file section that failed; Row the row index when a row is not canonical.
type FormatError struct {
	Row, Section *uint64
	Message      string
}

func (e *FormatError) Error() string {
	return "semq: format: " + e.Message + where(e.Row, "row", e.Section, "section")
}

// IntegrityError: a file image's digest does not match its footer. Which
// names the check that failed: "content" or "state".
type IntegrityError struct {
	Which   string
	Message string
}

func (e *IntegrityError) Error() string {
	if e.Which == "" {
		return "semq: integrity: " + e.Message
	}
	return "semq: integrity (" + e.Which + "): " + e.Message
}

// UnsupportedError: the operation, or the floating-point environment, is not
// supported.
type UnsupportedError struct {
	Operation, Message string
}

func (e *UnsupportedError) Error() string {
	return "semq: unsupported: " + e.Operation + ": " + e.Message
}

// NativeError: a defect in the core or the binding. It carries what a bug
// report needs and never input data.
type NativeError struct {
	Operation   string
	Status      int
	Row, Field  *uint64
	Message     string
	SDKVersion  string
	CoreVersion string
	BuildID     string
}

func (e *NativeError) Error() string {
	return fmt.Sprintf("semq: native: %s%s [operation=%s status=%d sdk=%s core=%s build=%s]",
		e.Message, where(e.Row, "row", e.Field, "field"),
		e.Operation, e.Status, e.SDKVersion, e.CoreVersion, e.BuildID)
}

func where(a *uint64, aName string, b *uint64, bName string) string {
	var parts []string
	if a != nil {
		parts = append(parts, fmt.Sprintf("%s %d", aName, *a))
	}
	if b != nil {
		parts = append(parts, fmt.Sprintf("%s %d", bName, *b))
	}
	if len(parts) == 0 {
		return ""
	}
	return " (" + strings.Join(parts, ", ") + ")"
}

// check maps a core status to the host error type. op names the verb for
// UnsupportedError and NativeError.
func check(status C.semq_status_t, e *C.semq_error_t, op string) error {
	if status == C.SEMQ_OK {
		return nil
	}
	msg := C.GoString(&e.message[0])
	row, field := optU64(e.row), optU64(e.field)
	switch status {
	case C.SEMQ_ERR_INVALID_INPUT:
		return &InvalidInputError{Row: row, Field: field, Message: msg}
	case C.SEMQ_ERR_INCOMPATIBLE:
		return &IncompatibleError{Field: field, Message: msg}
	case C.SEMQ_ERR_FORMAT:
		return &FormatError{Row: row, Section: field, Message: msg}
	case C.SEMQ_ERR_INTEGRITY:
		which := ""
		switch e.which {
		case C.SEMQ_WHICH_CONTENT:
			which = "content"
		case C.SEMQ_WHICH_STATE:
			which = "state"
		}
		return &IntegrityError{Which: which, Message: msg}
	case C.SEMQ_ERR_UNSUPPORTED:
		return &UnsupportedError{Operation: op, Message: msg}
	case C.SEMQ_ERR_NOMEM:
		return fmt.Errorf("semq: %s: %w", op, ErrNoMemory)
	}
	info := Info()
	return &NativeError{
		Operation: op, Status: int(status), Row: row, Field: field, Message: msg,
		SDKVersion: info.SDKVersion, CoreVersion: info.CoreVersion, BuildID: info.BuildID,
	}
}

// mustOK is check for calls that cannot fail on a live handle with arguments
// the binding produced itself; a failure there is a defect, so it panics.
func mustOK(status C.semq_status_t, e *C.semq_error_t, op string) {
	if err := check(status, e, op); err != nil {
		panic(err)
	}
}
