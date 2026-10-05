// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

package semq

/*
#include "semq.h"
*/
import "C"

import (
	"fmt"
	"unsafe"
)

// Operator selects the rule a CodecConfig applies. Values are pinned: they
// appear in the canonical config form and in files.
type Operator uint32

const (
	// OperatorOrbit: one digital-root symbol per coordinate, alphabet of 19.
	OperatorOrbit Operator = 0
	// OperatorPhase: one angular sector per coordinate pair.
	OperatorPhase Operator = 1
	// OperatorQuant: sign and magnitude bin per coordinate.
	OperatorQuant Operator = 2
)

// String returns the report name of the operator.
func (o Operator) String() string {
	switch o {
	case OperatorOrbit:
		return "orbit"
	case OperatorPhase:
		return "phase"
	case OperatorQuant:
		return "quant"
	}
	return fmt.Sprintf("Operator(%d)", uint32(o))
}

// parameterName is the report key of the operator's parameter.
func (o Operator) parameterName() string {
	switch o {
	case OperatorOrbit:
		return "scale"
	case OperatorPhase:
		return "sectors"
	case OperatorQuant:
		return "bins"
	}
	return "parameter"
}

// CodecConfig is an immutable value: operator, dimension and the operator's
// parameter. Build one with Quant, Phase, Orbit or ConfigFromBytes. The
// fields are the canonical form, so == compares the 13 canonical bytes. The
// zero value is not a valid config and is rejected by NewCodec and
// NewEncoding.
type CodecConfig struct {
	op, dim, p1, p2 uint32
}

func configFromC(c *C.semq_config_t) CodecConfig {
	return CodecConfig{op: uint32(c.op), dim: uint32(c.dim), p1: uint32(c.p1), p2: uint32(c.p2)}
}

func (c CodecConfig) toC() C.semq_config_t {
	return C.semq_config_t{op: C.uint32_t(c.op), dim: C.uint32_t(c.dim), p1: C.uint32_t(c.p1), p2: C.uint32_t(c.p2)}
}

// validate runs the core's config check; it rejects the zero value.
func (c CodecConfig) validate() error {
	cc := c.toC()
	var e C.semq_error_t
	return check(C.semq_config_validate(&cc, &e), &e, "config")
}

func newConfig(op Operator, dim, p1 uint32) (CodecConfig, error) {
	var (
		c C.semq_config_t
		e C.semq_error_t
		s C.semq_status_t
	)
	switch op {
	case OperatorOrbit:
		s = C.semq_config_orbit(C.uint32_t(dim), C.uint32_t(p1), &c, &e)
	case OperatorPhase:
		s = C.semq_config_phase(C.uint32_t(dim), C.uint32_t(p1), &c, &e)
	default:
		s = C.semq_config_quant(C.uint32_t(dim), C.uint32_t(p1), &c, &e)
	}
	if err := check(s, &e, "config"); err != nil {
		return CodecConfig{}, err
	}
	return configFromC(&c), nil
}

// Quant builds a quant config: dim in [1, 65536], bins in [2, 64].
func Quant(dim, bins uint32) (CodecConfig, error) { return newConfig(OperatorQuant, dim, bins) }

// Phase builds a phase config: dim even, sectors in [2, 256], and dim a
// multiple of 4 when sectors <= 16.
func Phase(dim, sectors uint32) (CodecConfig, error) { return newConfig(OperatorPhase, dim, sectors) }

// Orbit builds an orbit config: dim in [1, 65536], scale in [1, 2^30]. The
// conventional scale is 50; Go applies no default.
func Orbit(dim, scale uint32) (CodecConfig, error) { return newConfig(OperatorOrbit, dim, scale) }

// ConfigFromBytes parses the 13-byte canonical form.
func ConfigFromBytes(b [13]byte) (CodecConfig, error) {
	var (
		c C.semq_config_t
		e C.semq_error_t
	)
	s := C.semq_config_from_bytes((*C.uint8_t)(unsafe.Pointer(&b[0])), &c, &e)
	if err := check(s, &e, "config"); err != nil {
		return CodecConfig{}, err
	}
	return configFromC(&c), nil
}

// Operator reports the operator.
func (c CodecConfig) Operator() Operator { return Operator(c.op) }

// Dim reports the vector dimension.
func (c CodecConfig) Dim() uint32 { return c.dim }

// Parameter reports the operator's parameter: bins (quant), sectors (phase)
// or scale (orbit).
func (c CodecConfig) Parameter() uint32 { return c.p1 }

// RuleRevision reports the operator rule revision written into the config.
func (c CodecConfig) RuleRevision() uint32 { return c.p2 }

// BytesPerVector reports the size of one canonical row.
func (c CodecConfig) BytesPerVector() uint32 {
	cc := c.toC()
	return uint32(C.semq_config_bytes_per_vector(&cc))
}

// UnitsPerRow reports the number of symbols in one row: dim, or dim/2 for
// phase.
func (c CodecConfig) UnitsPerRow() uint32 {
	cc := c.toC()
	return uint32(C.semq_config_units_per_row(&cc))
}

// MaxMagnitude reports the quant clamp (float)(2/sqrt(dim)) as computed by
// the core. ok is false for the other operators.
func (c CodecConfig) MaxMagnitude() (m float32, ok bool) {
	if c.Operator() != OperatorQuant {
		return 0, false
	}
	cc := c.toC()
	return float32(C.semq_config_max_magnitude(&cc)), true
}

// Bytes returns the 13-byte canonical form.
func (c CodecConfig) Bytes() [13]byte {
	var out [13]byte
	cc := c.toC()
	C.semq_config_to_bytes(&cc, (*C.uint8_t)(unsafe.Pointer(&out[0])))
	return out
}

// String renders the config as operator(dim=..., parameter=...).
func (c CodecConfig) String() string {
	op := c.Operator()
	return fmt.Sprintf("%s(dim=%d, %s=%d)", op, c.dim, op.parameterName(), c.p1)
}

// report renders the config for the Diff report schema.
func (c CodecConfig) report() ConfigReport {
	return ConfigReport{Operator: c.Operator().String(), Dim: c.dim, Parameter: c.p1, RuleRevision: c.p2}
}
