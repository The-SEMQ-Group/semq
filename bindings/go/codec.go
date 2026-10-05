// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

package semq

/*
#include "semq.h"
*/
import "C"

import (
	"fmt"
	"math"
	"runtime"
	"unsafe"
)

// Codec applies one CodecConfig. It is immutable after construction and safe
// for concurrent use. Call Close when done; a finalizer is the fallback.
// Copies share ownership: closing any copy closes them all.
// Close must not race with another method on the same Codec.
type Codec struct {
	owner   *nativeOwner
	cfg     CodecConfig
	backend string
}

// NewCodec builds the codec for cfg.
func NewCodec(cfg CodecConfig) (*Codec, error) {
	cc := cfg.toC()
	var (
		p *C.semq_codec_t
		e C.semq_error_t
	)
	if err := check(C.semq_codec_create(&cc, &p, &e), &e, "codec"); err != nil {
		return nil, err
	}
	c := &Codec{owner: newOwner(unsafe.Pointer(p), func(p unsafe.Pointer) { C.semq_codec_free((*C.semq_codec_t)(p)) }), cfg: cfg, backend: C.GoString(C.semq_codec_backend(p))}
	return c, nil
}

// Close releases the native handle. It is idempotent.
func (c *Codec) Close() {
	if c != nil {
		c.owner.close()
	}
}

func (c *Codec) handle() (*C.semq_codec_t, error) {
	if c == nil {
		return nil, &InvalidInputError{Message: "codec is nil"}
	}
	p := (*C.semq_codec_t)(c.owner.pointer())
	if p == nil {
		return nil, &InvalidInputError{Message: "codec is closed"}
	}
	return p, nil
}

// Config reports the config the codec applies.
func (c *Codec) Config() CodecConfig { return c.cfg }

// Backend names the kernel the core runs for this operator on this host
// ("scalar", "neon", "avx2", ...).
func (c *Codec) Backend() string { return c.backend }

// Encode encodes len(ids) rows of dim float32 values (contiguous, row-major,
// unit norm) under ids. manifest may be nil. Row errors carry the input row
// index in InvalidInputError.Row and the coordinate in Field. The ids may be
// in any order; the Encoding holds them sorted.
func (c *Codec) Encode(ids IDs, vectors []float32, manifest map[string]string) (*Encoding, error) {
	h, err := c.handle()
	if err != nil {
		return nil, err
	}
	cids, err := idsToC(ids)
	if err != nil {
		return nil, err
	}
	defer cids.release()
	n, dim := cids.n(), uint64(c.cfg.dim)
	if n > math.MaxUint64/dim || uint64(len(vectors)) != n*dim {
		return nil, &InvalidInputError{Message: fmt.Sprintf(
			"%d ids need %d float32 values (dim %d), got %d", n, n*dim, dim, len(vectors))}
	}
	man, err := manifestToC(manifest)
	if err != nil {
		return nil, err
	}
	defer man.release()
	var vp *C.float
	if len(vectors) > 0 {
		vp = (*C.float)(unsafe.Pointer(&vectors[0]))
	}
	var (
		out *C.semq_encoding_t
		e   C.semq_error_t
	)
	s := C.semq_codec_encode(h, &cids.s, vp, man.ptr(), man.n(), &out, &e)
	runtime.KeepAlive(c)
	if err := check(s, &e, "encode"); err != nil {
		return nil, err
	}
	return newEncoding(out), nil
}

// Decode returns the representatives of enc as n*dim float32 values, row i
// for the i-th sorted id. They are not normalized and are outside the byte
// contract. IncompatibleError when enc.Config() differs from the codec's.
func (c *Codec) Decode(enc *Encoding) ([]float32, error) {
	h, err := c.handle()
	if err != nil {
		return nil, err
	}
	eh, err := enc.handle()
	if err != nil {
		return nil, err
	}
	out := make([]float32, enc.Len()*int(c.cfg.dim))
	var op *C.float
	if len(out) > 0 {
		op = (*C.float)(unsafe.Pointer(&out[0]))
	}
	var e C.semq_error_t
	s := C.semq_codec_decode(h, eh, op, &e)
	runtime.KeepAlive(c)
	runtime.KeepAlive(enc)
	if err := check(s, &e, "decode"); err != nil {
		return nil, err
	}
	return out, nil
}

// Unpack returns the symbols of enc as n*UnitsPerRow bytes, one per unit.
// IncompatibleError when enc.Config() differs from the codec's.
func (c *Codec) Unpack(enc *Encoding) ([]byte, error) {
	h, err := c.handle()
	if err != nil {
		return nil, err
	}
	eh, err := enc.handle()
	if err != nil {
		return nil, err
	}
	out := make([]byte, enc.Len()*int(c.cfg.UnitsPerRow()))
	var op *C.uint8_t
	if len(out) > 0 {
		op = (*C.uint8_t)(unsafe.Pointer(&out[0]))
	}
	var e C.semq_error_t
	s := C.semq_codec_unpack(h, eh, op, &e)
	runtime.KeepAlive(c)
	runtime.KeepAlive(enc)
	if err := check(s, &e, "unpack"); err != nil {
		return nil, err
	}
	return out, nil
}

// NewQuantCodec builds the codec for Quant(dim, bins): sign and magnitude
// bin per coordinate.
func NewQuantCodec(dim, bins uint32) (*Codec, error) {
	cfg, err := Quant(dim, bins)
	if err != nil {
		return nil, err
	}
	return NewCodec(cfg)
}

// NewPhaseCodec builds the codec for Phase(dim, sectors): angular sector per
// coordinate pair.
func NewPhaseCodec(dim, sectors uint32) (*Codec, error) {
	cfg, err := Phase(dim, sectors)
	if err != nil {
		return nil, err
	}
	return NewCodec(cfg)
}

// NewOrbitCodec builds the codec for Orbit(dim, scale): one discrete symbol
// per coordinate.
func NewOrbitCodec(dim, scale uint32) (*Codec, error) {
	cfg, err := Orbit(dim, scale)
	if err != nil {
		return nil, err
	}
	return NewCodec(cfg)
}
