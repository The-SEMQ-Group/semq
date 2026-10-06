// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

package semq_test

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
	"testing"
	"unicode/utf8"

	semq "github.com/The-SEMQ-Group/semq/bindings/go"
)

// The Go host runner: every conformance case through the public surface.
//
// Each vector directory under tests/conformance holds a manifest.json of
// cases; this test executes them with the exported API only and compares
// with the expectations. Cases a host cannot execute (setting the FP
// rounding mode, sending a duplicate manifest key) are skipped as
// unsupported, as the vector document allows.

// conformanceRoot is the vector directory: SEMQ_CONFORMANCE_DIR when set (a
// published module tested outside the checkout), else the checkout's
// tests/conformance relative to this package.
func conformanceRoot() string {
	if dir := os.Getenv("SEMQ_CONFORMANCE_DIR"); dir != "" {
		return dir
	}
	return filepath.Join("..", "..", "tests", "conformance")
}

type conformanceManifest struct {
	Vector int               `json:"vector"`
	Name   string            `json:"name"`
	Cases  []conformanceCase `json:"cases"`
}

type conformanceCase struct {
	ID     string          `json:"id"`
	Input  json.RawMessage `json:"input"`
	Expect json.RawMessage `json:"expect"`
}

// expectError is the {error, row, field, which} form of an expected error.
type expectError struct {
	Error string  `json:"error"`
	Row   *uint64 `json:"row"`
	Field *uint64 `json:"field"`
	Which *string `json:"which"`
}

// configSpec is a config as the manifests spell it: the parameter under
// its operator key or under "parameter".
type configSpec struct {
	Operator  string  `json:"operator"`
	Dim       uint32  `json:"dim"`
	Bins      *uint32 `json:"bins"`
	Sectors   *uint32 `json:"sectors"`
	Scale     *uint32 `json:"scale"`
	Parameter *uint32 `json:"parameter"`
}

type idsSpec struct {
	Kind      string   `json:"kind"`
	Values    []string `json:"values"`
	ValuesHex []string `json:"values_hex"`
}

var conformanceRunners = map[string]func(*testing.T, string, conformanceCase){
	"00-sha256-fips":        conformance00,
	"01-config-canonical":   conformance01,
	"02-config-derived":     conformance02,
	"03-encode":             conformance03,
	"04-encode-rejects":     conformance04,
	"05-decode":             conformance05,
	"06-ids-canonical":      conformance06,
	"07-manifest-canonical": conformance07,
	"08-digests":            conformance08,
	"09-file":               conformance09,
	"10-concat":             conformance10,
	"11-diff":               conformance11,
	"12-floor":              conformance12,
	"13-report":             conformance13,
	"15-fp-environment":     conformance15,
}

func TestConformance(t *testing.T) {
	root := conformanceRoot()
	if os.Getenv("SEMQ_CONFORMANCE_DIR") != "" {
		// An explicit vector directory must hold every vector this runner knows.
		for name := range conformanceRunners {
			if _, err := os.Stat(filepath.Join(root, name, "manifest.json")); err != nil {
				t.Fatalf("SEMQ_CONFORMANCE_DIR lacks vector %s: %v", name, err)
			}
		}
	}
	entries, err := os.ReadDir(root)
	if err != nil {
		t.Skipf("conformance vectors not found: %v", err)
	}
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		dir := filepath.Join(root, entry.Name())
		raw, err := os.ReadFile(filepath.Join(dir, "manifest.json"))
		if err != nil {
			continue
		}
		var m conformanceManifest
		if err := json.Unmarshal(raw, &m); err != nil {
			t.Errorf("%s: %v", entry.Name(), err)
			continue
		}
		run := conformanceRunners[entry.Name()]
		if run == nil {
			t.Errorf("%s: no runner for vector %d (%s)", entry.Name(), m.Vector, m.Name)
			continue
		}
		for _, c := range m.Cases {
			c := c
			t.Run(entry.Name()+"/"+c.ID, func(t *testing.T) { run(t, dir, c) })
		}
	}
}

// ---- helpers ---------------------------------------------------------------

func decodeJSON(t *testing.T, raw json.RawMessage, v any) {
	t.Helper()
	if err := json.Unmarshal(raw, v); err != nil {
		t.Fatalf("manifest: %v", err)
	}
}

func readVectorFile(t *testing.T, dir, name string) []byte {
	t.Helper()
	b, err := os.ReadFile(filepath.Join(dir, name))
	if err != nil {
		t.Fatal(err)
	}
	return b
}

// readF32 reads a little-endian float32 file and checks it against shape.
func readF32(t *testing.T, dir, name string, shape []int) []float32 {
	t.Helper()
	b := readVectorFile(t, dir, name)
	if len(b)%4 != 0 {
		t.Fatalf("%s: %d bytes is not a float32 array", name, len(b))
	}
	out := make([]float32, len(b)/4)
	for i := range out {
		out[i] = math.Float32frombits(binary.LittleEndian.Uint32(b[4*i:]))
	}
	if shape != nil && len(out) != shape[0]*shape[1] {
		t.Fatalf("%s: %d values, shape %v", name, len(out), shape)
	}
	return out
}

// f32FromHex parses 8-character bit patterns into float32 values.
func f32FromHex(t *testing.T, words []string) []float32 {
	t.Helper()
	out := make([]float32, len(words))
	for i, w := range words {
		bits, err := strconv.ParseUint(w, 16, 32)
		if err != nil {
			t.Fatalf("vectors_f32[%d] = %q: %v", i, w, err)
		}
		out[i] = math.Float32frombits(uint32(bits))
	}
	return out
}

func configOf(t *testing.T, spec configSpec) semq.CodecConfig {
	t.Helper()
	cfg, err := tryConfig(spec)
	if err != nil {
		t.Fatal(err)
	}
	return cfg
}

func tryConfig(spec configSpec) (semq.CodecConfig, error) {
	var p1 uint32
	switch {
	case spec.Bins != nil:
		p1 = *spec.Bins
	case spec.Sectors != nil:
		p1 = *spec.Sectors
	case spec.Scale != nil:
		p1 = *spec.Scale
	case spec.Parameter != nil:
		p1 = *spec.Parameter
	}
	switch spec.Operator {
	case "quant":
		return semq.Quant(spec.Dim, p1)
	case "phase":
		return semq.Phase(spec.Dim, p1)
	case "orbit":
		return semq.Orbit(spec.Dim, p1)
	}
	return semq.CodecConfig{}, fmt.Errorf("unknown operator %q", spec.Operator)
}

func idsOf(t *testing.T, spec idsSpec) semq.IDs {
	t.Helper()
	if spec.Kind == "u64" {
		ids := make([]uint64, len(spec.Values))
		for i, v := range spec.Values {
			u, err := strconv.ParseUint(v, 10, 64)
			if err != nil {
				t.Fatalf("ids[%d] = %q: %v", i, v, err)
			}
			ids[i] = u
		}
		return semq.U64IDs(ids...)
	}
	return semq.UTF8IDs(spec.Values...)
}

func rangeIDs(n int) semq.IDs {
	ids := make([]uint64, n)
	for i := range ids {
		ids[i] = uint64(i)
	}
	return semq.U64IDs(ids...)
}

func hexDigest(d [32]byte) string { return hex.EncodeToString(d[:]) }

func mustCodecOf(t *testing.T, cfg semq.CodecConfig) *semq.Codec {
	t.Helper()
	codec, err := semq.NewCodec(cfg)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(codec.Close)
	return codec
}

func loadVectorEncoding(t *testing.T, dir, name string) *semq.Encoding {
	t.Helper()
	enc, err := semq.Load(readVectorFile(t, dir, name))
	if err != nil {
		t.Fatalf("%s: %v", name, err)
	}
	t.Cleanup(enc.Close)
	return enc
}

func diffVectorFiles(t *testing.T, dir, ref, cand string) *semq.Diff {
	t.Helper()
	d, err := loadVectorEncoding(t, dir, ref).Diff(loadVectorEncoding(t, dir, cand))
	if err != nil {
		t.Fatalf("diff %s %s: %v", ref, cand, err)
	}
	t.Cleanup(d.Close)
	return d
}

// expectsError reports the error expectation of a case, if it has one.
func expectsError(t *testing.T, expect json.RawMessage) (expectError, bool) {
	t.Helper()
	var probe struct {
		Error *string `json:"error"`
	}
	decodeJSON(t, expect, &probe)
	if probe.Error == nil {
		return expectError{}, false
	}
	var e expectError
	decodeJSON(t, expect, &e)
	return e, true
}

// assertError checks err against an expected {error, row, field, which}.
// field is Section for FormatError, as in the Python runner.
func assertError(t *testing.T, err error, want expectError) {
	t.Helper()
	if err == nil {
		t.Fatalf("want %s, got no error", want.Error)
	}
	var (
		row, field *uint64
		which      *string
		ok         bool
	)
	switch want.Error {
	case "InvalidInput":
		var e *semq.InvalidInputError
		if ok = errors.As(err, &e); ok {
			row, field = e.Row, e.Field
		}
	case "Incompatible":
		var e *semq.IncompatibleError
		if ok = errors.As(err, &e); ok {
			field = e.Field
		}
	case "FormatError":
		var e *semq.FormatError
		if ok = errors.As(err, &e); ok {
			row, field = e.Row, e.Section
		}
	case "IntegrityError":
		var e *semq.IntegrityError
		if ok = errors.As(err, &e); ok {
			which = &e.Which
		}
	case "Unsupported":
		var e *semq.UnsupportedError
		ok = errors.As(err, &e)
	case "Native":
		var e *semq.NativeError
		if ok = errors.As(err, &e); ok {
			row, field = e.Row, e.Field
		}
	default:
		t.Fatalf("manifest: unknown error %q", want.Error)
	}
	if !ok {
		t.Fatalf("want %s, got %T: %v", want.Error, err, err)
	}
	if want.Row != nil && (row == nil || *row != *want.Row) {
		t.Errorf("row: got %s, want %d (%v)", optStr(row), *want.Row, err)
	}
	if want.Field != nil && (field == nil || *field != *want.Field) {
		t.Errorf("field: got %s, want %d (%v)", optStr(field), *want.Field, err)
	}
	if want.Which != nil && (which == nil || *which != *want.Which) {
		t.Errorf("which: got %v, want %q (%v)", which, *want.Which, err)
	}
}

func optStr(v *uint64) string {
	if v == nil {
		return "none"
	}
	return strconv.FormatUint(*v, 10)
}

// outcome applies the case's expectation to err: when an error is expected
// it is asserted and true is returned; otherwise err must be nil and the
// caller continues with the value.
func outcome(t *testing.T, expect json.RawMessage, err error) (done bool) {
	t.Helper()
	if want, ok := expectsError(t, expect); ok {
		assertError(t, err, want)
		return true
	}
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	return false
}

// assertReport compares d.Report() with the expected JSON structurally.
func assertReport(t *testing.T, d *semq.Diff, want json.RawMessage) {
	t.Helper()
	got, err := json.Marshal(d.Report())
	if err != nil {
		t.Fatal(err)
	}
	var g, w map[string]any
	decodeJSON(t, got, &g)
	decodeJSON(t, want, &w)
	if !reflect.DeepEqual(g, w) {
		t.Errorf("report:\n got %s\nwant %s", got, want)
	}
}

// ---- vectors ---------------------------------------------------------------

func conformance00(t *testing.T, _ string, c conformanceCase) {
	var in struct {
		ASCII  *string `json:"ascii"`
		Repeat string  `json:"repeat"`
		Count  int     `json:"count"`
	}
	var expect struct {
		Digest string `json:"digest"`
	}
	decodeJSON(t, c.Input, &in)
	decodeJSON(t, c.Expect, &expect)
	msg := strings.Repeat(in.Repeat, in.Count)
	if in.ASCII != nil {
		msg = *in.ASCII
	}
	// The host has no SHA-256 entry point; the identity contract is pinned
	// through state ids. crypto/sha256 is the platform reference here.
	sum := sha256.Sum256([]byte(msg))
	if got := hex.EncodeToString(sum[:]); got != expect.Digest {
		t.Errorf("digest: got %s, want %s", got, expect.Digest)
	}
}

func conformance01(t *testing.T, _ string, c conformanceCase) {
	var in configSpec
	var expect struct {
		Bytes string `json:"bytes"`
	}
	decodeJSON(t, c.Input, &in)
	cfg, err := tryConfig(in)
	if outcome(t, c.Expect, err) {
		return
	}
	decodeJSON(t, c.Expect, &expect)
	b := cfg.Bytes()
	if got := hex.EncodeToString(b[:]); got != expect.Bytes {
		t.Errorf("bytes: got %s, want %s", got, expect.Bytes)
	}
	back, err := semq.ConfigFromBytes(b)
	if err != nil {
		t.Fatalf("ConfigFromBytes: %v", err)
	}
	if back != cfg {
		t.Errorf("round trip: got %v, want %v", back, cfg)
	}
}

func conformance02(t *testing.T, _ string, c conformanceCase) {
	var in configSpec
	var expect struct {
		BytesPerVector   uint32 `json:"bytes_per_vector"`
		UnitsPerRow      uint32 `json:"units_per_row"`
		MaxMagnitudeBits string `json:"max_magnitude_bits"`
	}
	decodeJSON(t, c.Input, &in)
	decodeJSON(t, c.Expect, &expect)
	cfg := configOf(t, in)
	if got := cfg.BytesPerVector(); got != expect.BytesPerVector {
		t.Errorf("bytes_per_vector: got %d, want %d", got, expect.BytesPerVector)
	}
	if got := cfg.UnitsPerRow(); got != expect.UnitsPerRow {
		t.Errorf("units_per_row: got %d, want %d", got, expect.UnitsPerRow)
	}
	if in.Operator == "quant" {
		m, ok := cfg.MaxMagnitude()
		if !ok {
			t.Fatal("MaxMagnitude: not available for quant")
		}
		if got := fmt.Sprintf("%08x", math.Float32bits(m)); got != expect.MaxMagnitudeBits {
			t.Errorf("max_magnitude_bits: got %s, want %s", got, expect.MaxMagnitudeBits)
		}
	}
}

func conformance03(t *testing.T, dir string, c conformanceCase) {
	var in struct {
		Config      configSpec `json:"config"`
		VectorsFile string     `json:"vectors_file"`
		Shape       []int      `json:"shape"`
	}
	var expect struct {
		RowsFile    string `json:"rows_file"`
		SymbolsFile string `json:"symbols_file"`
	}
	decodeJSON(t, c.Input, &in)
	decodeJSON(t, c.Expect, &expect)
	codec := mustCodecOf(t, configOf(t, in.Config))
	vectors := readF32(t, dir, in.VectorsFile, in.Shape)
	enc, err := codec.Encode(rangeIDs(in.Shape[0]), vectors, nil)
	if err != nil {
		t.Fatalf("Encode: %v", err)
	}
	defer enc.Close()
	if got, want := enc.Rows(), readVectorFile(t, dir, expect.RowsFile); !bytes.Equal(got, want) {
		t.Errorf("rows differ from %s", expect.RowsFile)
	}
	symbols, err := codec.Unpack(enc)
	if err != nil {
		t.Fatalf("Unpack: %v", err)
	}
	if want := readVectorFile(t, dir, expect.SymbolsFile); !bytes.Equal(symbols, want) {
		t.Errorf("symbols differ from %s", expect.SymbolsFile)
	}
}

func conformance04(t *testing.T, _ string, c conformanceCase) {
	var in struct {
		Config     configSpec `json:"config"`
		VectorsF32 []string   `json:"vectors_f32"`
		IDs        idsSpec    `json:"ids"`
		Host       string     `json:"host"`
	}
	var expect struct {
		ContentDigest string `json:"content_digest"`
	}
	decodeJSON(t, c.Input, &in)
	cfg := configOf(t, in.Config)
	codec := mustCodecOf(t, cfg)
	dim := int(cfg.Dim())
	if in.Host != "" {
		// Representation checks the host performs before the core.
		switch c.ID {
		case "float64-input":
			// A []float64 cannot be passed to Encode: the type system rejects
			// it at compile time, so there is nothing to execute.
			return
		case "wrong-width":
			_, err := codec.Encode(semq.U64IDs(1), make([]float32, dim-1), nil)
			var ie *semq.InvalidInputError
			if !errors.As(err, &ie) {
				t.Fatalf("want *InvalidInputError, got %T: %v", err, err)
			}
			return
		}
		t.Fatalf("unknown host case %q", c.ID)
	}
	if c.ID == "empty-without-kind" {
		// An IDs value always states a kind: the zero value is the empty
		// u64 set (IDU64 is 0). The host cannot send an id set without a
		// kind, so the core's rejection is exercised by the C tests.
		t.Skip("unsupported: an empty IDs value states its kind")
	}
	ids := idsOf(t, in.IDs)
	n := len(in.IDs.Values)
	var vectors []float32
	if len(in.VectorsF32) > 0 {
		vectors = f32FromHex(t, in.VectorsF32)
		if len(vectors)%dim != 0 {
			t.Fatalf("vectors_f32: %d values for dim %d", len(vectors), dim)
		}
		if len(vectors) > n*dim {
			vectors = vectors[:n*dim]
		}
	}
	enc, err := codec.Encode(ids, vectors, nil)
	if outcome(t, c.Expect, err) {
		return
	}
	defer enc.Close()
	decodeJSON(t, c.Expect, &expect)
	if got := hexDigest(enc.ContentDigest()); got != expect.ContentDigest {
		t.Errorf("content_digest: got %s, want %s", got, expect.ContentDigest)
	}
}

// ulpClose compares float32 arrays as int64 differences of their (signed
// int32) bit patterns, as the Python runner does.
func ulpClose(got, want []float32, ulps int64) (int, bool) {
	for i := range want {
		g := int64(int32(math.Float32bits(got[i])))
		w := int64(int32(math.Float32bits(want[i])))
		d := g - w
		if d < 0 {
			d = -d
		}
		if d > ulps {
			return i, false
		}
	}
	return -1, true
}

func conformance05(t *testing.T, dir string, c conformanceCase) {
	var in struct {
		Config   configSpec `json:"config"`
		Shape    []int      `json:"shape"`
		RowsFile string     `json:"rows_file"`
	}
	var expect struct {
		RepresentativesFile string `json:"representatives_file"`
		ToleranceULP        int64  `json:"tolerance_ulp"`
	}
	decodeJSON(t, c.Input, &in)
	decodeJSON(t, c.Expect, &expect)
	cfg := configOf(t, in.Config)
	codec := mustCodecOf(t, cfg)
	n := in.Shape[0]
	rows := readVectorFile(t, dir, in.RowsFile)
	if len(rows) != n*int(cfg.BytesPerVector()) {
		t.Fatalf("%s: %d bytes for %d rows of %d", in.RowsFile, len(rows), n, cfg.BytesPerVector())
	}
	enc, err := semq.NewEncoding(rangeIDs(n), rows, cfg, nil)
	if err != nil {
		t.Fatalf("NewEncoding: %v", err)
	}
	defer enc.Close()
	got, err := codec.Decode(enc)
	if err != nil {
		t.Fatalf("Decode: %v", err)
	}
	want := readF32(t, dir, expect.RepresentativesFile, in.Shape)
	if len(got) != len(want) {
		t.Fatalf("Decode: %d values, want %d", len(got), len(want))
	}
	if i, ok := ulpClose(got, want, expect.ToleranceULP); !ok {
		t.Errorf("representative %d: got %08x, want %08x (tolerance %d ulp, backend %s)",
			i, math.Float32bits(got[i]), math.Float32bits(want[i]), expect.ToleranceULP, codec.Backend())
	}
}

func conformance06(t *testing.T, _ string, c conformanceCase) {
	var in struct {
		IDs    idsSpec `json:"ids"`
		Length int     `json:"length"`
		Host   string  `json:"host"`
	}
	var expect struct {
		Sorted     []string `json:"sorted"`
		IDsSection string   `json:"ids_section"`
	}
	decodeJSON(t, c.Input, &in)
	cfg, err := semq.Quant(4, 4)
	if err != nil {
		t.Fatal(err)
	}
	bpv := int(cfg.BytesPerVector())
	zeroRows := func(n int) []byte { return make([]byte, n*bpv) }
	switch c.ID {
	case "utf8-too-long":
		_, err := semq.NewEncoding(semq.UTF8IDs(strings.Repeat("x", in.Length)), zeroRows(1), cfg, nil)
		want, _ := expectsError(t, c.Expect)
		assertError(t, err, want)
		return
	case "lone-surrogate":
		// Go strings hold arbitrary bytes: the UTF-8 encoding of U+D800 goes
		// to the core, which must reject it rather than replace it.
		_, err := semq.NewEncoding(semq.UTF8IDs("\xed\xa0\x80"), zeroRows(1), cfg, nil)
		want, _ := expectsError(t, c.Expect)
		assertError(t, err, want)
		return
	}
	if in.IDs.ValuesHex != nil {
		// Ids that are not valid UTF-8 travel as hex. Go strings carry the
		// raw bytes, so the core's rejection is exercised directly.
		raw := make([]string, len(in.IDs.ValuesHex))
		for i, h := range in.IDs.ValuesHex {
			b, err := hex.DecodeString(h)
			if err != nil {
				t.Fatalf("values_hex[%d]: %v", i, err)
			}
			raw[i] = string(b)
		}
		_, err := semq.NewEncoding(semq.UTF8IDs(raw...), zeroRows(len(raw)), cfg, nil)
		want, _ := expectsError(t, c.Expect)
		assertError(t, err, want)
		return
	}
	decodeJSON(t, c.Expect, &expect)
	ids := idsOf(t, in.IDs)
	enc, err := semq.NewEncoding(ids, zeroRows(len(in.IDs.Values)), cfg, nil)
	if err != nil {
		t.Fatalf("NewEncoding: %v", err)
	}
	defer enc.Close()
	var got []string
	if in.IDs.Kind == "u64" {
		for _, v := range enc.IDsU64() {
			got = append(got, strconv.FormatUint(v, 10))
		}
	} else {
		got = enc.IDsUTF8()
	}
	if len(got) != len(expect.Sorted) {
		t.Fatalf("sorted: %d ids, want %d", len(got), len(expect.Sorted))
	}
	for i := range got {
		if got[i] != expect.Sorted[i] {
			t.Errorf("sorted[%d]: got %q, want %q", i, got[i], expect.Sorted[i])
		}
	}
	image := enc.Bytes()
	end := 28 + len(expect.IDsSection)/2
	if len(image) < end {
		t.Fatalf("image: %d bytes, ids section ends at %d", len(image), end)
	}
	if got := hex.EncodeToString(image[28:end]); got != expect.IDsSection {
		t.Errorf("ids_section:\n got %s\nwant %s", got, expect.IDsSection)
	}
}

func conformance07(t *testing.T, _ string, c conformanceCase) {
	var in struct {
		Pairs    [][2]string `json:"pairs"`
		PairsHex [][2]string `json:"pairs_hex"`
	}
	var expect struct {
		ManifestSection string `json:"manifest_section"`
		StateID         string `json:"state_id"`
	}
	decodeJSON(t, c.Input, &in)
	cfg, err := semq.Quant(4, 4)
	if err != nil {
		t.Fatal(err)
	}
	rawPairs := in.Pairs
	if in.Pairs == nil {
		// Non-ASCII inputs travel as hex. Go strings carry any bytes, so
		// invalid UTF-8 reaches the core, which must reject it.
		valid := true
		for i, kv := range in.PairsHex {
			var pair [2]string
			for j, h := range kv {
				b, err := hex.DecodeString(h)
				if err != nil {
					t.Fatalf("pairs_hex[%d][%d]: %v", i, j, err)
				}
				pair[j] = string(b)
				valid = valid && utf8.Valid(b)
			}
			rawPairs = append(rawPairs, pair)
		}
		if !valid {
			want, ok := expectsError(t, c.Expect)
			if !ok || want.Error != "InvalidInput" {
				t.Fatalf("invalid UTF-8 input expects %v, want InvalidInput", want)
			}
		}
	}
	pairs := map[string]string{}
	duplicate := false
	for _, kv := range rawPairs {
		_, seen := pairs[kv[0]]
		duplicate = duplicate || seen
		pairs[kv[0]] = kv[1]
	}
	if duplicate {
		// A Go map cannot carry a duplicate key; the host has no way to
		// send one, so the core's rejection is exercised by the C tests.
		t.Skip("unsupported: map keys are unique")
	}
	enc, err := semq.NewEncoding(semq.U64IDs(), nil, cfg, pairs)
	if outcome(t, c.Expect, err) {
		return
	}
	defer enc.Close()
	decodeJSON(t, c.Expect, &expect)
	image := enc.Bytes()
	if len(image) < 28+64 {
		t.Fatalf("image: %d bytes", len(image))
	}
	if got := hex.EncodeToString(image[28 : len(image)-64]); got != expect.ManifestSection {
		t.Errorf("manifest_section:\n got %s\nwant %s", got, expect.ManifestSection)
	}
	if got := hexDigest(enc.StateID()); got != expect.StateID {
		t.Errorf("state_id: got %s, want %s", got, expect.StateID)
	}
	if got := enc.Manifest(); !reflect.DeepEqual(got, pairs) {
		t.Errorf("manifest: got %v, want %v", got, pairs)
	}
}

func conformance08(t *testing.T, dir string, c conformanceCase) {
	var in struct {
		Config      configSpec `json:"config"`
		File        string     `json:"file"`
		VectorsFile string     `json:"vectors_file"`
		Orders      [][]string `json:"orders"`
	}
	var expect struct {
		ContentDigest string `json:"content_digest"`
		StateID       string `json:"state_id"`
	}
	decodeJSON(t, c.Input, &in)
	decodeJSON(t, c.Expect, &expect)
	cfg := configOf(t, in.Config)
	if in.File != "" {
		enc := loadVectorEncoding(t, dir, in.File)
		if enc.Config() != cfg {
			t.Errorf("config: got %v, want %v", enc.Config(), cfg)
		}
		if got := hexDigest(enc.ContentDigest()); got != expect.ContentDigest {
			t.Errorf("content_digest: got %s, want %s", got, expect.ContentDigest)
		}
		if got := hexDigest(enc.StateID()); got != expect.StateID {
			t.Errorf("state_id: got %s, want %s", got, expect.StateID)
		}
		return
	}
	codec := mustCodecOf(t, cfg)
	dim := int(cfg.Dim())
	vectors := readF32(t, dir, in.VectorsFile, nil)
	if len(vectors)%dim != 0 {
		t.Fatalf("%s: %d values for dim %d", in.VectorsFile, len(vectors), dim)
	}
	for _, order := range in.Orders {
		ids := idsOf(t, idsSpec{Kind: "u64", Values: order})
		rows := make([]float32, 0, len(order)*dim)
		for _, v := range ids.U64 {
			rows = append(rows, vectors[(v-1)*uint64(dim):v*uint64(dim)]...)
		}
		enc, err := codec.Encode(ids, rows, nil)
		if err != nil {
			t.Fatalf("Encode %v: %v", order, err)
		}
		got := hexDigest(enc.StateID())
		enc.Close()
		if got != expect.StateID {
			t.Errorf("order %v: state_id got %s, want %s", order, got, expect.StateID)
		}
	}
}

func conformance09(t *testing.T, dir string, c conformanceCase) {
	var in struct {
		File   string `json:"file"`
		Mutate *struct {
			Kind  string `json:"kind"`
			At    int    `json:"at"`
			Value byte   `json:"value"`
		} `json:"mutate"`
	}
	var expect struct {
		FileSize int    `json:"file_size"`
		StateID  string `json:"state_id"`
		N        int    `json:"n"`
		IDKind   string `json:"id_kind"`
	}
	decodeJSON(t, c.Input, &in)
	buf := readVectorFile(t, dir, in.File)
	if m := in.Mutate; m != nil {
		switch m.Kind {
		case "xor_byte":
			buf[m.At] ^= m.Value
		case "set_byte":
			buf[m.At] = m.Value
		case "truncate":
			buf = buf[:m.At]
		case "append_byte":
			buf = append(buf, m.Value)
		default:
			t.Fatalf("unknown mutation %q", m.Kind)
		}
	}
	enc, err := semq.Load(buf)
	if outcome(t, c.Expect, err) {
		return
	}
	defer enc.Close()
	decodeJSON(t, c.Expect, &expect)
	if len(buf) != expect.FileSize {
		t.Errorf("file_size: got %d, want %d", len(buf), expect.FileSize)
	}
	if got := hexDigest(enc.StateID()); got != expect.StateID {
		t.Errorf("state_id: got %s, want %s", got, expect.StateID)
	}
	if enc.Len() != expect.N {
		t.Errorf("n: got %d, want %d", enc.Len(), expect.N)
	}
	if got := enc.IDKind().String(); got != expect.IDKind {
		t.Errorf("id_kind: got %s, want %s", got, expect.IDKind)
	}
	if !bytes.Equal(enc.Bytes(), buf) {
		t.Error("round trip: Bytes() differs from the file")
	}
}

func conformance10(t *testing.T, dir string, c conformanceCase) {
	var in struct {
		Files []string `json:"files"`
	}
	var expect struct {
		StateID string `json:"state_id"`
		N       int    `json:"n"`
	}
	decodeJSON(t, c.Input, &in)
	parts := make([]*semq.Encoding, len(in.Files))
	for i, f := range in.Files {
		parts[i] = loadVectorEncoding(t, dir, f)
	}
	result, err := parts[0].Concat(parts[1:]...)
	if outcome(t, c.Expect, err) {
		return
	}
	defer result.Close()
	decodeJSON(t, c.Expect, &expect)
	if got := hexDigest(result.StateID()); got != expect.StateID {
		t.Errorf("state_id: got %s, want %s", got, expect.StateID)
	}
	if result.Len() != expect.N {
		t.Errorf("n: got %d, want %d", result.Len(), expect.N)
	}
}

func conformance11(t *testing.T, dir string, c conformanceCase) {
	var in struct {
		Reference string  `json:"reference"`
		Candidate string  `json:"candidate"`
		UnitsOf   *uint64 `json:"units_of"`
	}
	var expect struct {
		Report json.RawMessage `json:"report"`
		Units  [][3]uint64     `json:"units"`
	}
	decodeJSON(t, c.Input, &in)
	ref := loadVectorEncoding(t, dir, in.Reference)
	cand := loadVectorEncoding(t, dir, in.Candidate)
	d, err := ref.Diff(cand)
	if outcome(t, c.Expect, err) {
		return
	}
	defer d.Close()
	decodeJSON(t, c.Expect, &expect)
	assertReport(t, d, expect.Report)
	if in.UnitsOf == nil {
		return
	}
	units, err := d.Units(semq.U64ID(*in.UnitsOf))
	if err != nil {
		t.Fatalf("Units(%d): %v", *in.UnitsOf, err)
	}
	if len(units) != len(expect.Units) {
		t.Fatalf("units: got %v, want %v", units, expect.Units)
	}
	for i, u := range units {
		got := [3]uint64{uint64(u.Unit), uint64(u.Reference), uint64(u.Candidate)}
		if got != expect.Units[i] {
			t.Errorf("units[%d]: got %v, want %v", i, got, expect.Units[i])
		}
	}
}

// assertFloor compares the report form of f with the manifest's floor.
func assertFloor(t *testing.T, f *semq.Floor, want json.RawMessage) {
	t.Helper()
	got, err := json.Marshal(f.Report())
	if err != nil {
		t.Fatal(err)
	}
	var g, w map[string]any
	decodeJSON(t, got, &g)
	decodeJSON(t, want, &w)
	if !reflect.DeepEqual(g, w) {
		t.Errorf("floor:\n got %s\nwant %s", got, want)
	}
}

// floorOf reads the floor a manifest gives in the report form and
// constructs it; the error, from the reader or the constructor, is the
// host's verdict on that form.
func floorOf(t *testing.T, raw json.RawMessage) (*semq.Floor, error) {
	t.Helper()
	var r semq.FloorReport
	if err := json.Unmarshal(raw, &r); err != nil {
		return nil, err
	}
	f, err := semq.FloorFromReport(r)
	if err == nil {
		t.Cleanup(f.Close)
	}
	return f, err
}

func nullDiffs(t *testing.T, dir string, pairs [][2]string) []*semq.Diff {
	t.Helper()
	diffs := make([]*semq.Diff, len(pairs))
	for i, p := range pairs {
		diffs[i] = diffVectorFiles(t, dir, p[0], p[1])
	}
	return diffs
}

func conformance12(t *testing.T, dir string, c conformanceCase) {
	var in struct {
		NullDiffs [][2]string     `json:"null_diffs"`
		Reference string          `json:"reference"`
		Candidate string          `json:"candidate"`
		Floor     json.RawMessage `json:"floor"`
		PerRow    bool            `json:"per_row"`
	}
	decodeJSON(t, c.Input, &in)
	if in.NullDiffs != nil {
		var expect struct {
			Floor json.RawMessage `json:"floor"`
		}
		diffs := nullDiffs(t, dir, in.NullDiffs)
		floor, err := semq.MeasureFloor(diffs)
		if outcome(t, c.Expect, err) {
			return
		}
		defer floor.Close()
		decodeJSON(t, c.Expect, &expect)
		assertFloor(t, floor, expect.Floor)
		for i, d := range diffs {
			within, err := d.Within(floor)
			if err != nil {
				t.Fatalf("Within(null %d): %v", i, err)
			}
			if !within {
				t.Errorf("null diff %d is not within its own floor", i)
			}
		}
		return
	}
	var expect struct {
		Within   bool `json:"within"`
		Evaluate struct {
			Passed  bool     `json:"passed"`
			Reasons []string `json:"reasons"`
			Rows    []string `json:"rows"`
		} `json:"evaluate"`
	}
	d := diffVectorFiles(t, dir, in.Reference, in.Candidate)
	// A floor is validated at construction, so an invalid one is rejected
	// before it is applied.
	floor, err := floorOf(t, in.Floor)
	if err != nil {
		outcome(t, c.Expect, err)
		return
	}
	assertFloor(t, floor, in.Floor)
	verdict, err := d.Evaluate(floor, semq.GateOptions{PerRow: in.PerRow})
	if outcome(t, c.Expect, err) {
		return
	}
	decodeJSON(t, c.Expect, &expect)
	reasons := []string{}
	for _, r := range verdict.Reasons {
		reasons = append(reasons, string(r))
	}
	rows := []string{}
	for _, id := range verdict.Rows {
		rows = append(rows, id.String())
	}
	e := expect.Evaluate
	if verdict.Passed != e.Passed || !reflect.DeepEqual(reasons, e.Reasons) || !reflect.DeepEqual(rows, e.Rows) {
		t.Errorf("evaluate: got %v %v %v, want %v %v %v", verdict.Passed, reasons, rows, e.Passed, e.Reasons, e.Rows)
	}
	within, err := d.Within(floor)
	if err != nil {
		t.Fatalf("Within: %v", err)
	}
	if within != expect.Within {
		t.Errorf("within: got %v, want %v", within, expect.Within)
	}
}

func conformance13(t *testing.T, dir string, c conformanceCase) {
	var in struct {
		NullDiffs [][2]string `json:"null_diffs"`
		Reference string      `json:"reference"`
		Candidate string      `json:"candidate"`
	}
	var expect struct {
		Report json.RawMessage `json:"report"`
		Floor  json.RawMessage `json:"floor"`
	}
	decodeJSON(t, c.Input, &in)
	decodeJSON(t, c.Expect, &expect)
	if expect.Report != nil {
		assertReport(t, diffVectorFiles(t, dir, in.Reference, in.Candidate), expect.Report)
		return
	}
	floor, err := semq.MeasureFloor(nullDiffs(t, dir, in.NullDiffs))
	if err != nil {
		t.Fatalf("MeasureFloor: %v", err)
	}
	defer floor.Close()
	assertFloor(t, floor, expect.Floor)
}

func conformance15(t *testing.T, _ string, c conformanceCase) {
	var in struct {
		RoundingMode string     `json:"rounding_mode"`
		Config       configSpec `json:"config"`
		VectorsF32   []string   `json:"vectors_f32"`
		IDs          idsSpec    `json:"ids"`
	}
	var expect struct {
		ContentDigest string `json:"content_digest"`
	}
	decodeJSON(t, c.Input, &in)
	if in.RoundingMode != "" {
		t.Skip("unsupported: Go cannot set the FP rounding mode")
	}
	decodeJSON(t, c.Expect, &expect)
	codec := mustCodecOf(t, configOf(t, in.Config))
	enc, err := codec.Encode(idsOf(t, in.IDs), f32FromHex(t, in.VectorsF32), nil)
	if err != nil {
		t.Fatalf("Encode: %v", err)
	}
	defer enc.Close()
	if got := hexDigest(enc.ContentDigest()); got != expect.ContentDigest {
		t.Errorf("content_digest: got %s, want %s", got, expect.ContentDigest)
	}
}
