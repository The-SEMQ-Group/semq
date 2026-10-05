// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

package semq

import (
	"errors"
	"io"
	"testing"
)

type shortWriter struct{ written int }

func (w *shortWriter) Write(p []byte) (int, error) {
	n := len(p) / 2
	w.written += n
	return n, nil
}

func TestEncodingWriteToReportsShortWrite(t *testing.T) {
	cfg := quant44(t)
	e := mustEncoding(t, U64IDs(1), packQuant([]uint8{1, 2, 3, 4}, 3, int(cfg.BytesPerVector())), cfg, nil)
	defer e.Close()

	w := &shortWriter{}
	n, err := e.WriteTo(w)
	if !errors.Is(err, io.ErrShortWrite) {
		t.Fatalf("WriteTo error = %v, want io.ErrShortWrite", err)
	}
	if n != int64(w.written) {
		t.Fatalf("WriteTo bytes = %d, writer accepted %d", n, w.written)
	}
}
