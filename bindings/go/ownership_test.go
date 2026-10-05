// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

package semq

import (
	"runtime"
	"testing"
)

// A Go value copy aliases a resource: closing either value closes all aliases.
// Check rejection before a second Close so the regression fails without a crash.
func TestCopiedOwnersShareClose(t *testing.T) {
	cfg := quant44(t)
	enc := mustEncoding(t, U64IDs(1), []byte{0, 0}, cfg, nil)
	defer enc.Close()
	t.Run("Codec", func(t *testing.T) {
		original := mustCodec(t, cfg)
		copied := *original
		original.Close()
		if _, err := copied.handle(); err == nil {
			t.Fatal("copy remained open")
		}
		copied.Close()
	})
	t.Run("Encoding", func(t *testing.T) {
		original := mustEncoding(t, U64IDs(1), []byte{0, 0}, cfg, nil)
		copied := *original
		original.Close()
		if _, err := copied.handle(); err == nil {
			t.Fatal("copy remained open")
		}
		copied.Close()
	})
	t.Run("Diff", func(t *testing.T) {
		original, err := enc.Diff(enc)
		if err != nil {
			t.Fatal(err)
		}
		copied := *original
		original.Close()
		if _, err := copied.handle(); err == nil {
			t.Fatal("copy remained open")
		}
		copied.Close()
	})
	t.Run("Floor", func(t *testing.T) {
		original, err := NewFloor(cfg, IDU64, enc.StateID(), 1, 0, 1, 0)
		if err != nil {
			t.Fatal(err)
		}
		copied := *original
		original.Close()
		if _, err := copied.handle(); err == nil {
			t.Fatal("copy remained open")
		}
		copied.Close()
	})
}

func TestCopiedEncodingRetainsResourceThroughGC(t *testing.T) {
	cfg := quant44(t)
	copied := func() Encoding {
		original := mustEncoding(t, U64IDs(1), []byte{0, 0}, cfg, nil)
		return *original
	}()
	defer copied.Close()
	for i := 0; i < 3; i++ {
		runtime.GC()
	}
	if _, ok, err := copied.Get(U64ID(1)); err != nil || !ok {
		t.Fatalf("copy lost its owner: %v", err)
	}
}
