// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

package semq_test

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"math"
	"os"
	"path/filepath"
	"sort"
	"testing"

	semq "github.com/The-SEMQ-Group/semq/bindings/go"
)

// The Go host of the reproducibility fixture: encodes the 1,000 real
// embeddings of tests/reproducibility with every configuration of its
// expected.json and compares content_digest, state_id and the saved file's
// bytes. The other bindings run the same comparison.

var reproducibilityRoot = filepath.Join("..", "..", "tests", "reproducibility")

type reproducibilityExpected struct {
	Manifest map[string]string `json:"manifest"`
	IDKind   string            `json:"id_kind"`
	Configs  map[string]struct {
		Config struct {
			Operator  string `json:"operator"`
			Dim       uint32 `json:"dim"`
			Parameter uint32 `json:"parameter"`
		} `json:"config"`
		ContentDigest string `json:"content_digest"`
		StateID       string `json:"state_id"`
		FileSize      int    `json:"file_size"`
		FileSHA256    string `json:"file_sha256"`
	} `json:"configs"`
}

func TestReproducibility(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join(reproducibilityRoot, "vectors.f32"))
	if err != nil {
		t.Skipf("reproducibility fixture missing: %v", err)
	}
	var meta struct {
		Values []string `json:"values"`
	}
	var expected reproducibilityExpected
	for name, into := range map[string]any{"ids.json": &meta, "expected.json": &expected} {
		text, err := os.ReadFile(filepath.Join(reproducibilityRoot, name))
		if err != nil {
			t.Fatal(err)
		}
		if err := json.Unmarshal(text, into); err != nil {
			t.Fatalf("%s: %v", name, err)
		}
	}
	if expected.IDKind != "utf8" {
		t.Fatalf("id kind %q", expected.IDKind)
	}
	vectors := make([]float32, len(raw)/4)
	for i := range vectors {
		vectors[i] = math.Float32frombits(binary.LittleEndian.Uint32(raw[4*i:]))
	}

	names := make([]string, 0, len(expected.Configs))
	for name := range expected.Configs {
		names = append(names, name)
	}
	sort.Strings(names)
	for _, name := range names {
		expect := expected.Configs[name]
		t.Run(name, func(t *testing.T) {
			spec := expect.Config
			var cfg semq.CodecConfig
			var err error
			switch spec.Operator {
			case "quant":
				cfg, err = semq.Quant(spec.Dim, spec.Parameter)
			case "phase":
				cfg, err = semq.Phase(spec.Dim, spec.Parameter)
			case "orbit":
				cfg, err = semq.Orbit(spec.Dim, spec.Parameter)
			default:
				t.Fatalf("unknown operator %q", spec.Operator)
			}
			if err != nil {
				t.Fatal(err)
			}
			codec, err := semq.NewCodec(cfg)
			if err != nil {
				t.Fatal(err)
			}
			defer codec.Close()
			state, err := codec.Encode(semq.UTF8IDs(meta.Values...), vectors, expected.Manifest)
			if err != nil {
				t.Fatal(err)
			}
			defer state.Close()
			var file bytes.Buffer
			if _, err := state.WriteTo(&file); err != nil {
				t.Fatal(err)
			}
			data := file.Bytes()
			content, id := state.ContentDigest(), state.StateID()
			sum := sha256.Sum256(data)
			if got := hex.EncodeToString(content[:]); got != expect.ContentDigest {
				t.Errorf("content_digest %s, want %s", got, expect.ContentDigest)
			}
			if got := hex.EncodeToString(id[:]); got != expect.StateID {
				t.Errorf("state_id %s, want %s", got, expect.StateID)
			}
			if len(data) != expect.FileSize {
				t.Errorf("file size %d, want %d", len(data), expect.FileSize)
			}
			if got := hex.EncodeToString(sum[:]); got != expect.FileSHA256 {
				t.Errorf("file sha256 %s, want %s", got, expect.FileSHA256)
			}
			loaded, err := semq.Load(data)
			if err != nil {
				t.Fatal(err)
			}
			defer loaded.Close()
			if loaded.StateID() != id {
				t.Errorf("loaded state_id differs")
			}
		})
	}
}
