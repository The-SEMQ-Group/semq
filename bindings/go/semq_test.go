// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

package semq

import (
	"bytes"
	"encoding/hex"
	"encoding/json"
	"errors"
	"math"
	"os"
	"reflect"
	"strings"
	"testing"
)

// ---- helpers ---------------------------------------------------------------

func quant44(t *testing.T) CodecConfig {
	t.Helper()
	c, err := Quant(4, 4)
	if err != nil {
		t.Fatal(err)
	}
	return c
}

func hexOf(d [32]byte) string { return hex.EncodeToString(d[:]) }

// packQuant packs one symbol per unit into a row: LSB-first, bits per unit.
func packQuant(symbols []uint8, bits uint32, bpv int) []byte {
	out := make([]byte, bpv)
	pos := 0
	for _, s := range symbols {
		for b := uint32(0); b < bits; b++ {
			if (s>>b)&1 != 0 {
				out[pos>>3] |= 1 << (pos & 7)
			}
			pos++
		}
	}
	return out
}

func mustEncoding(t *testing.T, ids IDs, rows []byte, cfg CodecConfig, manifest map[string]string) *Encoding {
	t.Helper()
	e, err := NewEncoding(ids, rows, cfg, manifest)
	if err != nil {
		t.Fatal(err)
	}
	return e
}

func mustCodec(t *testing.T, cfg CodecConfig) *Codec {
	t.Helper()
	c, err := NewCodec(cfg)
	if err != nil {
		t.Fatal(err)
	}
	return c
}

func asInvalid(t *testing.T, err error) *InvalidInputError {
	t.Helper()
	var ie *InvalidInputError
	if !errors.As(err, &ie) {
		t.Fatalf("want *InvalidInputError, got %T: %v", err, err)
	}
	return ie
}

func wantU64(t *testing.T, name string, got *uint64, want uint64) {
	t.Helper()
	if got == nil || *got != want {
		t.Fatalf("%s: got %v, want %d", name, got, want)
	}
}

// ---- CodecConfig -----------------------------------------------------------

func TestConfigCanonicalForm(t *testing.T) {
	c := quant44(t)
	b := c.Bytes()
	if got := hex.EncodeToString(b[:]); got != "02040000000400000000000000" {
		t.Fatalf("canonical form %s", got)
	}
	back, err := ConfigFromBytes(b)
	if err != nil {
		t.Fatal(err)
	}
	if back != c {
		t.Fatalf("round trip %v != %v", back, c)
	}
	if c.Operator() != OperatorQuant || c.Dim() != 4 || c.Parameter() != 4 || c.RuleRevision() != 0 {
		t.Fatalf("fields %v", c)
	}
	if c.BytesPerVector() != 2 || c.UnitsPerRow() != 4 {
		t.Fatalf("derived %d %d", c.BytesPerVector(), c.UnitsPerRow())
	}
	m, ok := c.MaxMagnitude()
	if !ok || math.Float32bits(m) != 0x3f800000 {
		t.Fatalf("max magnitude %v %v", m, ok)
	}
	if s := c.String(); s != "quant(dim=4, bins=4)" {
		t.Fatalf("String %q", s)
	}
	if _, err := NewCodec(CodecConfig{}); err == nil {
		t.Fatal("zero config accepted")
	} else {
		asInvalid(t, err)
	}
}

func TestConfigDerivedQuantities(t *testing.T) {
	p, err := Phase(8, 16)
	if err != nil {
		t.Fatal(err)
	}
	if p.BytesPerVector() != 2 || p.UnitsPerRow() != 4 {
		t.Fatalf("phase(8,16): %d %d", p.BytesPerVector(), p.UnitsPerRow())
	}
	if _, ok := p.MaxMagnitude(); ok {
		t.Fatal("phase has a max magnitude")
	}
	p, _ = Phase(8, 17)
	if p.BytesPerVector() != 4 {
		t.Fatalf("phase(8,17): %d", p.BytesPerVector())
	}
	o, err := Orbit(5, 50)
	if err != nil {
		t.Fatal(err)
	}
	if o.BytesPerVector() != 5 || o.UnitsPerRow() != 5 || o.String() != "orbit(dim=5, scale=50)" {
		t.Fatalf("orbit(5,50): %d %d %s", o.BytesPerVector(), o.UnitsPerRow(), o)
	}
	q, _ := Quant(1024, 64)
	if q.BytesPerVector() != 896 {
		t.Fatalf("quant(1024,64): %d", q.BytesPerVector())
	}
	q, _ = Quant(3, 4)
	if q.BytesPerVector() != 2 {
		t.Fatalf("quant(3,4): %d", q.BytesPerVector())
	}
}

func TestConfigRejects(t *testing.T) {
	_, err := Quant(4, 1)
	wantU64(t, "quant(4,1) field", asInvalid(t, err).Field, 2)
	if _, err := Quant(4, 65); err == nil {
		t.Fatal("quant(4,65)")
	}
	_, err = Quant(0, 4)
	wantU64(t, "quant(0,4) field", asInvalid(t, err).Field, 1)
	if _, err := Quant(65537, 4); err == nil {
		t.Fatal("quant(65537,4)")
	}
	if _, err := Phase(7, 16); err == nil {
		t.Fatal("phase(7,16)")
	}
	if _, err := Phase(6, 16); err == nil {
		t.Fatal("phase(6,16)")
	}
	if _, err := Phase(6, 17); err != nil {
		t.Fatal(err)
	}
	if _, err := Phase(8, 1); err == nil {
		t.Fatal("phase(8,1)")
	}
	if _, err := Phase(8, 257); err == nil {
		t.Fatal("phase(8,257)")
	}
	if _, err := Orbit(8, 0); err == nil {
		t.Fatal("orbit(8,0)")
	}
	if _, err := Orbit(8, (1<<30)+1); err == nil {
		t.Fatal("orbit(8,2^30+1)")
	}
	if _, err := Orbit(8, 1<<30); err != nil {
		t.Fatal(err)
	}
	bad := [13]byte{3, 4, 0, 0, 0, 4, 0, 0, 0, 0, 0, 0, 0}
	if _, err := ConfigFromBytes(bad); err == nil {
		t.Fatal("operator 3 accepted")
	}
	rev := [13]byte{2, 4, 0, 0, 0, 4, 0, 0, 0, 1, 0, 0, 0}
	_, err = ConfigFromBytes(rev)
	wantU64(t, "rule revision field", asInvalid(t, err).Field, 3)
}

// ---- identities and the file image -----------------------------------------

func TestEmptyEncodingIdentitiesAndImage(t *testing.T) {
	c := quant44(t)
	e := mustEncoding(t, U64IDs(), nil, c, nil)
	defer e.Close()
	if got := hexOf(e.ContentDigest()); got != "4528e8a0422f5cde968847e021c85b4e6e78ce68da9e92b2981c62dd48f78f4a" {
		t.Fatalf("content %s", got)
	}
	if got := hexOf(e.StateID()); got != "ef4d1522eb158aa9b6b83cd5d51f80ea2cc59ac3aeb45b69a1c28c99375b55b9" {
		t.Fatalf("state %s", got)
	}
	img := e.Bytes()
	if len(img) != 96 {
		t.Fatalf("image length %d", len(img))
	}
	const want = "53454d51020002040000000400000000000000000000000000000000000000004528e8a0422f5cde968847e021c85b4e6e78ce68da9e92b2981c62dd48f78f4aef4d1522eb158aa9b6b83cd5d51f80ea2cc59ac3aeb45b69a1c28c99375b55b9"
	if got := hex.EncodeToString(img); got != want {
		t.Fatalf("image %s", got)
	}
	back, err := Load(img)
	if err != nil {
		t.Fatal(err)
	}
	defer back.Close()
	if back.Len() != 0 || back.IDKind() != IDU64 || back.StateID() != e.StateID() || back.Config() != c {
		t.Fatal("loaded empty encoding differs")
	}
	if len(back.Rows()) != 0 || len(back.IDsU64()) != 0 || back.IDsUTF8() != nil {
		t.Fatal("empty accessors")
	}
	// The codec path agrees with the constructor path.
	codec := mustCodec(t, c)
	defer codec.Close()
	enc, err := codec.Encode(U64IDs(), nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer enc.Close()
	if enc.StateID() != e.StateID() {
		t.Fatal("empty encode differs")
	}
	// An empty set still needs a valid kind.
	if _, err := NewEncoding(IDs{Kind: 7}, nil, c, nil); err == nil {
		t.Fatal("kind 7 accepted")
	} else {
		asInvalid(t, err)
	}
}

func TestOneRowIdentities(t *testing.T) {
	c := quant44(t)
	e := mustEncoding(t, U64IDs(7), []byte{0x07, 0x07}, c, map[string]string{"encoder": "x"})
	defer e.Close()
	if got := hexOf(e.ContentDigest()); got != "1a3d8e8bfbf3429525d0bc11e18a17b75ea49af40b6b441f6863444f71230489" {
		t.Fatalf("content %s", got)
	}
	if got := hexOf(e.StateID()); got != "07d119f5a0a76de95bd4b41110d6005e6fc38cfc398421dd15df2be68adf9f85" {
		t.Fatalf("state %s", got)
	}
	if m := e.Manifest(); !reflect.DeepEqual(m, map[string]string{"encoder": "x"}) {
		t.Fatalf("manifest %v", m)
	}
	row, ok, err := e.Get(U64ID(7))
	if err != nil || !ok || !bytes.Equal(row, []byte{7, 7}) {
		t.Fatalf("get 7: %v %v %v", row, ok, err)
	}
	if _, ok, err := e.Get(U64ID(8)); err != nil || ok {
		t.Fatalf("get 8: %v %v", ok, err)
	}
	if _, _, err := e.Get(UTF8ID("7")); err == nil {
		t.Fatal("utf8 lookup on a u64 encoding")
	} else {
		asInvalid(t, err)
	}
	if !bytes.Equal(e.Row(0), []byte{7, 7}) {
		t.Fatal("Row(0)")
	}
	back, err := Load(e.Bytes())
	if err != nil {
		t.Fatal(err)
	}
	defer back.Close()
	if back.StateID() != e.StateID() || back.Manifest()["encoder"] != "x" {
		t.Fatal("round trip")
	}
}

func TestNewEncodingRejects(t *testing.T) {
	c := quant44(t)
	_, err := NewEncoding(U64IDs(1), []byte{0x07, 0x17}, c, nil) // bit 12 is padding
	ie := asInvalid(t, err)
	wantU64(t, "padding row", ie.Row, 0)
	if ie.Field != nil {
		t.Fatalf("padding field %d", *ie.Field)
	}
	ph, _ := Phase(4, 8)
	_, err = NewEncoding(U64IDs(1), []byte{0x90}, ph, nil) // high nibble 9 >= 8 sectors
	wantU64(t, "bad sector field", asInvalid(t, err).Field, 1)
	_, err = NewEncoding(U64IDs(5, 9, 5), make([]byte, 6), c, nil)
	wantU64(t, "duplicate row", asInvalid(t, err).Row, 2)
	_, err = NewEncoding(U64IDs(1, 2), []byte{0, 0, 0}, c, nil)
	asInvalid(t, err)
	_, err = NewEncoding(IDs{U64: []uint64{1}, UTF8: []string{"a"}}, []byte{0, 0}, c, nil)
	asInvalid(t, err)
	if _, err := NewEncoding(U64IDs(1), []byte{0, 0}, CodecConfig{}, nil); err == nil {
		t.Fatal("zero config accepted")
	}
}

// ---- Codec -----------------------------------------------------------------

func TestEncodeSortsIDsAndMapsSymbols(t *testing.T) {
	c := quant44(t)
	codec := mustCodec(t, c)
	defer codec.Close()
	if codec.Backend() == "" || codec.Config() != c {
		t.Fatal("codec metadata")
	}
	vectors := []float32{
		0.5, 0.5, 0.5, 0.5, // id 3: all symbols 6
		-0.5, -0.5, -0.5, -0.5, // id 1: all symbols 2
		1, 0, 0, 0, // id 2: [7, 4, 4, 4]
	}
	e, err := codec.Encode(U64IDs(3, 1, 2), vectors, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer e.Close()
	if e.Len() != 3 || !reflect.DeepEqual(e.IDsU64(), []uint64{1, 2, 3}) {
		t.Fatalf("ids %v", e.IDsU64())
	}
	symbols, err := codec.Unpack(e)
	if err != nil {
		t.Fatal(err)
	}
	if want := []byte{2, 2, 2, 2, 7, 4, 4, 4, 6, 6, 6, 6}; !bytes.Equal(symbols, want) {
		t.Fatalf("symbols %v", symbols)
	}
	rep, err := codec.Decode(e)
	if err != nil {
		t.Fatal(err)
	}
	if len(rep) != 12 || rep[0] != -0.625 || rep[4] != 0.875 || rep[5] != 0.125 || rep[8] != 0.625 {
		t.Fatalf("representatives %v", rep)
	}
	e2, err := codec.Encode(U64IDs(3, 1, 2), vectors, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer e2.Close()
	if e2.StateID() != e.StateID() {
		t.Fatal("same input, different state")
	}
}

func TestEncodeThreeOperators(t *testing.T) {
	o, _ := Orbit(4, 50)
	p, _ := Phase(4, 16)
	co, cp := mustCodec(t, o), mustCodec(t, p)
	defer co.Close()
	defer cp.Close()
	v := []float32{0.5, 0.5, -0.5, 0.5}
	eo, err := co.Encode(U64IDs(1), v, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer eo.Close()
	ep, err := cp.Encode(U64IDs(1), v, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer ep.Close()
	so, _ := co.Unpack(eo)
	sp, _ := cp.Unpack(ep)
	if !bytes.Equal(so, []byte{7, 7, 16, 7}) { // 0.5 * 50 = 25 -> digital root 7; negative -> 9 + 7
		t.Fatalf("orbit symbols %v", so)
	}
	if !bytes.Equal(sp, []byte{10, 14}) { // 45 degrees starts sector 10, 135 degrees starts sector 14
		t.Fatalf("phase symbols %v", sp)
	}
	rep, err := co.Decode(eo)
	if err != nil {
		t.Fatal(err)
	}
	if math.Abs(float64(rep[0])-0.14) > 1e-6 || math.Abs(float64(rep[2])+0.14) > 1e-6 {
		t.Fatalf("orbit representatives %v", rep)
	}
	var inc *IncompatibleError
	if _, err := co.Decode(ep); !errors.As(err, &inc) {
		t.Fatalf("cross-config decode: %v", err)
	}
	if _, err := co.Unpack(ep); !errors.As(err, &inc) {
		t.Fatalf("cross-config unpack: %v", err)
	}
}

func TestEncodeCanonicalizesSubnormals(t *testing.T) {
	codec := mustCodec(t, quant44(t))
	defer codec.Close()
	a, err := codec.Encode(U64IDs(1), []float32{1, 1e-40, -1e-41, 0}, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer a.Close()
	b, err := codec.Encode(U64IDs(1), []float32{1, 0, 0, 0}, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer b.Close()
	if a.ContentDigest() != b.ContentDigest() {
		t.Fatal("subnormals change the content digest")
	}
}

func TestEncodeRejects(t *testing.T) {
	codec := mustCodec(t, quant44(t))
	defer codec.Close()
	ids := U64IDs(1, 2)
	v := []float32{1, 0, 0, 0, 0, 1, 0, 0}
	v[6] = float32(math.NaN())
	_, err := codec.Encode(ids, v, nil)
	ie := asInvalid(t, err)
	wantU64(t, "nan row", ie.Row, 1)
	wantU64(t, "nan field", ie.Field, 2)
	v[6] = 0
	v[0] = 0.9 // norm 0.81
	_, err = codec.Encode(ids, v, nil)
	wantU64(t, "norm row", asInvalid(t, err).Row, 0)
	v[0] = 1
	edge := []float32{1, 0.03125, 0, 0} // 0.03125^2 = 2^-10: admitted
	ok, err := codec.Encode(U64IDs(1), edge, nil)
	if err != nil {
		t.Fatal(err)
	}
	ok.Close()
	edge[1] = 0.0316 // just outside
	if _, err := codec.Encode(U64IDs(1), edge, nil); err == nil {
		t.Fatal("norm just outside the tolerance accepted")
	}
	_, err = codec.Encode(U64IDs(4, 4), v, nil)
	wantU64(t, "duplicate row", asInvalid(t, err).Row, 1)
	// Representation errors are the host's: no row.
	_, err = codec.Encode(ids, v[:7], nil)
	if ie := asInvalid(t, err); ie.Row != nil {
		t.Fatalf("length error carries a row: %v", err)
	}
	_, err = codec.Encode(ids, nil, nil)
	asInvalid(t, err)
	// utf8 ids: invalid UTF-8 is rejected with the row.
	_, err = codec.Encode(UTF8IDs("a", "\xffb"), v, nil)
	wantU64(t, "invalid utf8 row", asInvalid(t, err).Row, 1)
	_, err = codec.Encode(UTF8IDs("a", ""), v, nil)
	wantU64(t, "empty utf8 row", asInvalid(t, err).Row, 1)
	// A manifest with an empty key is the core's verdict, with the pair index.
	_, err = codec.Encode(U64IDs(1), v[:4], map[string]string{"": "x"})
	asInvalid(t, err)
	codec.Close()
	if _, err := codec.Encode(U64IDs(1), v[:4], nil); err == nil {
		t.Fatal("closed codec encodes")
	} else {
		asInvalid(t, err)
	}
}

// ---- utf8 ids, persistence ------------------------------------------------

func TestUTF8IDsRoundTripAndOrder(t *testing.T) {
	c := quant44(t)
	// "b", "a", "ab": bytewise order is a, ab, b.
	e := mustEncoding(t, UTF8IDs("b", "a", "ab"), []byte{1, 0, 2, 0, 3, 0}, c, nil)
	defer e.Close()
	if e.IDKind() != IDUTF8 || e.IDsU64() != nil {
		t.Fatal("kind")
	}
	if ids := e.IDsUTF8(); !reflect.DeepEqual(ids, []string{"a", "ab", "b"}) {
		t.Fatalf("ids %q", ids)
	}
	if rows := e.Rows(); !bytes.Equal(rows, []byte{2, 0, 3, 0, 1, 0}) {
		t.Fatalf("rows %v", rows)
	}
	row, ok, err := e.Get(UTF8ID("ab"))
	if err != nil || !ok || !bytes.Equal(row, []byte{3, 0}) {
		t.Fatalf("get ab: %v %v %v", row, ok, err)
	}
	if _, ok, err := e.Get(UTF8ID("c")); err != nil || ok {
		t.Fatalf("get c: %v %v", ok, err)
	}
	if _, _, err := e.Get(U64ID(1)); err == nil {
		t.Fatal("u64 lookup on a utf8 encoding")
	}
	var buf bytes.Buffer
	n, err := e.WriteTo(&buf)
	if err != nil {
		t.Fatal(err)
	}
	img := e.Bytes()
	if n != int64(len(img)) || !bytes.Equal(buf.Bytes(), img) {
		t.Fatal("WriteTo differs from Bytes")
	}
	back, err := Read(&buf)
	if err != nil {
		t.Fatal(err)
	}
	defer back.Close()
	if back.StateID() != e.StateID() || !reflect.DeepEqual(back.IDsUTF8(), []string{"a", "ab", "b"}) {
		t.Fatal("round trip through io.Reader")
	}
	d, err := e.Diff(back)
	if err != nil {
		t.Fatal(err)
	}
	defer d.Close()
	if d.NUnchanged() != 3 || len(d.Added()) != 0 {
		t.Fatal("identical states differ")
	}
	units, err := d.Units(UTF8ID("ab"))
	if err != nil || len(units) != 0 {
		t.Fatalf("units of an identical row: %v %v", units, err)
	}
}

func sampleTwoRows(t *testing.T, manifest map[string]string) *Encoding {
	t.Helper()
	return mustEncoding(t, U64IDs(10, 20), []byte{0x07, 0x07, 0x24, 0x01}, quant44(t), manifest)
}

func TestLoadDetectsCorruption(t *testing.T) {
	e := sampleTwoRows(t, nil)
	defer e.Close()
	img := e.Bytes()
	if len(img) != 28+16+4+4+64 {
		t.Fatalf("image length %d", len(img))
	}
	mutate := func(f func(b []byte)) []byte {
		b := append([]byte(nil), img...)
		f(b)
		return b
	}
	var integ *IntegrityError
	var format *FormatError

	// A row byte: the content digest fails.
	if _, err := Load(mutate(func(b []byte) { b[28+16] ^= 1 })); !errors.As(err, &integ) || integ.Which != "content" {
		t.Fatalf("row byte: %v", err)
	}
	// Truncation and trailing bytes.
	if _, err := Load(img[:len(img)-1]); !errors.As(err, &format) {
		t.Fatalf("truncated: %v", err)
	}
	if _, err := Load(append(mutate(func([]byte) {}), 0)); !errors.As(err, &format) {
		t.Fatalf("trailing: %v", err)
	}
	if _, err := Load(nil); !errors.As(err, &format) {
		t.Fatalf("empty: %v", err)
	}
	// Version 1, a future version, a bad magic.
	_, err := Load(mutate(func(b []byte) { b[4] = 1 }))
	if !errors.As(err, &format) {
		t.Fatalf("version 1: %v", err)
	}
	wantU64(t, "framing section", format.Section, 0)
	if _, err := Load(mutate(func(b []byte) { b[4] = 3 })); !errors.As(err, &format) {
		t.Fatalf("version 3: %v", err)
	}
	if _, err := Load(mutate(func(b []byte) { b[0] = 'X' })); !errors.As(err, &format) {
		t.Fatalf("magic: %v", err)
	}
	// n = 2^40 is rejected by the size checks before any allocation.
	_, err = Load(mutate(func(b []byte) { b[25] = 1 }))
	if !errors.As(err, &format) {
		t.Fatalf("huge n: %v", err)
	}
	wantU64(t, "sizes section", format.Section, 2)
	// A footer copied from another valid state: content digest fails.
	empty := mustEncoding(t, U64IDs(), nil, quant44(t), nil)
	defer empty.Close()
	oimg := empty.Bytes()
	_, err = Load(mutate(func(b []byte) { copy(b[len(b)-64:], oimg[len(oimg)-64:]) }))
	if !errors.As(err, &integ) || integ.Which != "content" {
		t.Fatalf("foreign footer: %v", err)
	}
	// A manifest byte with only the state id stale: which = state.
	m := sampleTwoRows(t, map[string]string{"k": "v"})
	defer m.Close()
	mimg := m.Bytes()
	mimg[len(mimg)-64-1] = 'w'
	if _, err := Load(mimg); !errors.As(err, &integ) || integ.Which != "state" {
		t.Fatalf("manifest byte: %v", err)
	}
}

// ---- concat ----------------------------------------------------------------

func TestConcatIsOrderIndependent(t *testing.T) {
	c := quant44(t)
	ids := []uint64{1, 2, 3}
	rows := []byte{0x07, 0x07, 0x24, 0x01, 0x11, 0x02}
	whole := mustEncoding(t, U64IDs(ids...), rows, c, nil)
	defer whole.Close()
	var p [3]*Encoding
	for i := range p {
		p[i] = mustEncoding(t, U64IDs(ids[i]), rows[2*i:2*i+2], c, nil)
		defer p[i].Close()
	}
	want := whole.StateID()
	ca, err := p[0].Concat(p[1], p[2])
	if err != nil {
		t.Fatal(err)
	}
	defer ca.Close()
	cb, err := p[2].Concat(p[0], p[1])
	if err != nil {
		t.Fatal(err)
	}
	defer cb.Close()
	if ca.StateID() != want || cb.StateID() != want {
		t.Fatal("concat depends on order")
	}
	empty := mustEncoding(t, U64IDs(), nil, c, nil)
	defer empty.Close()
	ce, err := whole.Concat(empty)
	if err != nil {
		t.Fatal(err)
	}
	defer ce.Close()
	if ce.StateID() != want {
		t.Fatal("empty is not neutral")
	}
	_, err = whole.Concat(p[1])
	wantU64(t, "overlap part", asInvalid(t, err).Field, 1)
	m := mustEncoding(t, U64IDs(3), rows[4:], c, map[string]string{"encoder": "x"})
	defer m.Close()
	_, err = p[0].Concat(m)
	asInvalid(t, err)
	c2, _ := Quant(4, 3)
	other := mustEncoding(t, U64IDs(3), rows[2:4], c2, nil) // symbols 4,4,4,0 < 6
	defer other.Close()
	var inc *IncompatibleError
	if _, err := p[0].Concat(other); !errors.As(err, &inc) {
		t.Fatalf("different config: %v", err)
	}
	if _, err := p[0].Concat(nil); err == nil {
		t.Fatal("nil part accepted")
	}
}

// ---- diff, within, measure -------------------------------------------------

func diffFixture(t *testing.T) *Diff {
	t.Helper()
	c := quant44(t)
	ref := mustEncoding(t, U64IDs(1, 2, 3), []byte{0x07, 0x07, 0x24, 0x01, 0x11, 0x02}, c,
		map[string]string{"encoder": "m1", "note": "a"})
	cand := mustEncoding(t, U64IDs(2, 3, 4), []byte{0x24, 0x01, 0x11, 0x06, 0x00, 0x00}, c,
		map[string]string{"encoder": "m1", "run": "7"}) // id 3: unit 3 symbol 1 -> 3
	d, err := ref.Diff(cand)
	if err != nil {
		t.Fatal(err)
	}
	// The diff outlives the encodings it was built from.
	ref.Close()
	cand.Close()
	return d
}

func TestDiffListsUnitsAndManifest(t *testing.T) {
	d := diffFixture(t)
	defer d.Close()
	if d.Config() != quant44(t) || d.IDKind() != IDU64 {
		t.Fatal("diff metadata")
	}
	if !reflect.DeepEqual(d.Added(), []ID{U64ID(4)}) || !reflect.DeepEqual(d.Removed(), []ID{U64ID(1)}) {
		t.Fatalf("added %v removed %v", d.Added(), d.Removed())
	}
	if !reflect.DeepEqual(d.Changed(), []Change{{ID: U64ID(3), Hamming: 1}}) || d.NUnchanged() != 1 {
		t.Fatalf("changed %v unchanged %d", d.Changed(), d.NUnchanged())
	}
	units, err := d.Units(U64ID(3))
	if err != nil || !reflect.DeepEqual(units, []Unit{{Unit: 3, Reference: 1, Candidate: 3}}) {
		t.Fatalf("units of 3: %v %v", units, err)
	}
	if units, err := d.Units(U64ID(2)); err != nil || len(units) != 0 {
		t.Fatalf("units of 2: %v %v", units, err)
	}
	if _, err := d.Units(U64ID(1)); err == nil {
		t.Fatal("units of a removed id")
	} else {
		asInvalid(t, err)
	}
	if _, err := d.Units(UTF8ID("3")); err == nil {
		t.Fatal("units with the wrong kind")
	}
	a, seven := "a", "7"
	want := map[string]ManifestChange{"note": {Before: &a}, "run": {After: &seven}}
	if got := d.ManifestChanges(); !reflect.DeepEqual(got, want) {
		t.Fatalf("manifest changes %v", got)
	}
	// removed is non-empty, so no floor admits this diff.
	f, err := NewFloor(d.Config(), d.IDKind(), d.ReferenceID(), 1, 4, 4, 4)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	if w, err := d.Within(f); err != nil || w {
		t.Fatalf("within: %v %v", w, err)
	}
	// Short circuit: identical states.
	c := quant44(t)
	same := mustEncoding(t, U64IDs(1, 2, 3), []byte{0x07, 0x07, 0x24, 0x01, 0x11, 0x02}, c, nil)
	defer same.Close()
	same2 := mustEncoding(t, U64IDs(1, 2, 3), []byte{0x07, 0x07, 0x24, 0x01, 0x11, 0x02}, c, nil)
	defer same2.Close()
	ds, err := same.Diff(same2)
	if err != nil {
		t.Fatal(err)
	}
	defer ds.Close()
	if ds.NUnchanged() != 3 || len(ds.Changed()) != 0 || ds.ReferenceID() != same.StateID() || ds.CandidateID() != same2.StateID() {
		t.Fatal("identical diff")
	}
	// Different kinds are incompatible.
	other := mustEncoding(t, UTF8IDs("a"), []byte{0x07, 0x07}, c, nil)
	defer other.Close()
	var inc *IncompatibleError
	if _, err := same.Diff(other); !errors.As(err, &inc) {
		t.Fatalf("different kinds: %v", err)
	}
}

func TestReportJSON(t *testing.T) {
	d := diffFixture(t)
	defer d.Close()
	r := d.Report()
	raw, err := json.Marshal(r)
	if err != nil {
		t.Fatal(err)
	}
	var got map[string]any
	if err := json.Unmarshal(raw, &got); err != nil {
		t.Fatal(err)
	}
	want := map[string]any{
		"reference_id": hexOf(d.ReferenceID()),
		"candidate_id": hexOf(d.CandidateID()),
		"id_kind":      "u64",
		"config":       map[string]any{"operator": "quant", "dim": 4.0, "bins": 4.0, "rule_revision": 0.0},
		"added":        []any{"4"},
		"removed":      []any{"1"},
		"changed":      []any{[]any{"3", 1.0}},
		"n_unchanged":  1.0,
		"manifest_changes": map[string]any{
			"note": []any{"a", nil},
			"run":  []any{nil, "7"},
		},
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("report\n got %s\nwant %v", raw, want)
	}
	// Empty lists serialize as [] and {}, never null.
	c := quant44(t)
	e := mustEncoding(t, U64IDs(), nil, c, nil)
	defer e.Close()
	de, err := e.Diff(e)
	if err != nil {
		t.Fatal(err)
	}
	defer de.Close()
	raw, _ = json.Marshal(de.Report())
	if !bytes.Contains(raw, []byte(`"added":[]`)) || !bytes.Contains(raw, []byte(`"manifest_changes":{}`)) {
		t.Fatalf("empty report %s", raw)
	}
}

// rowsWithChanges builds a quant(16, 4) encoding of n rows where every symbol
// is base, except the first nChanged rows whose first flip units are base+1.
func rowsWithChanges(t *testing.T, n, nChanged uint64, flip uint32, base uint8) *Encoding {
	t.Helper()
	c, err := Quant(16, 4)
	if err != nil {
		t.Fatal(err)
	}
	bpv := int(c.BytesPerVector()) // 6
	ids := make([]uint64, n)
	rows := make([]byte, 0, int(n)*bpv)
	for i := uint64(0); i < n; i++ {
		sym := make([]uint8, 16)
		for u := range sym {
			sym[u] = base
		}
		if i < nChanged {
			for u := uint32(0); u < flip; u++ {
				sym[u] = base + 1
			}
		}
		ids[i] = i
		rows = append(rows, packQuant(sym, 3, bpv)...)
	}
	return mustEncoding(t, U64IDs(ids...), rows, c, nil)
}

func mustDiff(t *testing.T, ref, cand *Encoding) *Diff {
	t.Helper()
	d, err := ref.Diff(cand)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(d.Close)
	return d
}

func asIncompatible(t *testing.T, err error) *IncompatibleError {
	t.Helper()
	var ie *IncompatibleError
	if !errors.As(err, &ie) {
		t.Fatalf("want *IncompatibleError, got %T: %v", err, err)
	}
	return ie
}

func TestFloorMeasureAndWithin(t *testing.T) {
	// Two nulls of one reference of 100 rows. A: 1 row changed by 1 unit.
	// B: 2 rows changed by 10 units each.
	ref := rowsWithChanges(t, 100, 0, 0, 4)
	a := rowsWithChanges(t, 100, 1, 1, 4)
	b := rowsWithChanges(t, 100, 2, 10, 4)
	defer ref.Close()
	defer a.Close()
	defer b.Close()
	c, rid := ref.Config(), ref.StateID()
	da, db := mustDiff(t, ref, a), mustDiff(t, ref, b)
	if len(da.Changed()) != 1 || da.NUnchanged() != 99 {
		t.Fatalf("null A: %v %d", da.Changed(), da.NUnchanged())
	}
	f, err := MeasureFloor([]*Diff{da, db})
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	// B has the worst ratio; the p99 is the max. The context is the nulls'.
	if f.Config() != c || f.IDKind() != IDU64 || f.ReferenceID() != rid || f.Nulls() != 2 ||
		f.ChangedRows() != 2 || f.TotalRows() != 100 || f.Hamming() != 10 {
		t.Fatalf("measure([A, B]) = %+v", f.Report())
	}
	for _, d := range []*Diff{da, db} {
		if w, err := d.Within(f); err != nil || !w {
			t.Fatalf("within: %v %v", w, err)
		}
	}
	// A alone: floor 1/100, hamming 1; B exceeds it on both counts.
	fa, err := MeasureFloor([]*Diff{da})
	if err != nil {
		t.Fatal(err)
	}
	defer fa.Close()
	if fa.Nulls() != 1 || fa.ChangedRows() != 1 || fa.TotalRows() != 100 || fa.Hamming() != 1 {
		t.Fatalf("measure([A]) = %+v", fa.Report())
	}
	if w, err := db.Within(fa); err != nil || w {
		t.Fatalf("B within A's floor: %v %v", w, err)
	}
	// Exact boundary: 2 of 100 against 1/100 fails; against 2/100 passes.
	a2 := rowsWithChanges(t, 100, 2, 1, 4)
	defer a2.Close()
	d2 := mustDiff(t, ref, a2)
	if w, err := d2.Within(fa); err != nil || w {
		t.Fatalf("2/100 within 1/100: %v %v", w, err)
	}
	f2, err := NewFloor(c, IDU64, rid, 1, 2, 100, 1)
	if err != nil {
		t.Fatal(err)
	}
	defer f2.Close()
	if w, err := d2.Within(f2); err != nil || !w {
		t.Fatalf("2/100 within 2/100: %v %v", w, err)
	}
	// n_common = 0 never passes, even under a floor of that reference that
	// admits every change; an empty candidate is not a rebuild.
	empty := mustEncoding(t, U64IDs(), nil, c, nil)
	defer empty.Close()
	de := mustDiff(t, empty, empty)
	fe, err := NewFloor(c, IDU64, empty.StateID(), 1, 1, 1, 16)
	if err != nil {
		t.Fatal(err)
	}
	defer fe.Close()
	if w, err := de.Within(fe); err != nil || w {
		t.Fatalf("empty within: %v %v", w, err)
	}
	// A change to encoder never passes and is no null.
	row := packQuant(bytes.Repeat([]byte{4}, 16), 3, 6)
	m1 := mustEncoding(t, U64IDs(1), row, c, map[string]string{"encoder": "m1"})
	defer m1.Close()
	m2 := mustEncoding(t, U64IDs(1), row, c, map[string]string{"encoder": "m2"})
	defer m2.Close()
	dm := mustDiff(t, m1, m2)
	fm, err := NewFloor(c, IDU64, m1.StateID(), 1, 1, 1, 16)
	if err != nil {
		t.Fatal(err)
	}
	defer fm.Close()
	if w, err := dm.Within(fm); err != nil || w {
		t.Fatalf("encoder change within: %v %v", w, err)
	}
	if _, err := MeasureFloor([]*Diff{dm}); err == nil {
		t.Fatal("encoder change accepted as a null")
	} else {
		wantU64(t, "null index", asInvalid(t, err).Field, 0)
	}
	// Removed rows are no null either.
	fewer := rowsWithChanges(t, 99, 0, 0, 4)
	defer fewer.Close()
	if _, err := MeasureFloor([]*Diff{mustDiff(t, ref, fewer)}); err == nil {
		t.Fatal("removed rows accepted as a null")
	} else {
		wantU64(t, "null index", asInvalid(t, err).Field, 0)
	}
	// The floor is bound to its reference, config and id kind: nulls of
	// another reference cannot be measured together, and a diff of another
	// context is incompatible rather than outside.
	other := rowsWithChanges(t, 1, 0, 0, 4)
	other1 := rowsWithChanges(t, 1, 1, 10, 4)
	defer other.Close()
	defer other1.Close()
	do := mustDiff(t, other, other1)
	if _, err := MeasureFloor([]*Diff{da, do}); err == nil {
		t.Fatal("nulls of two references accepted")
	} else {
		wantU64(t, "null index", asIncompatible(t, err).Field, 1)
	}
	if _, err := do.Within(fa); err == nil {
		t.Fatal("floor of another reference accepted")
	} else {
		asIncompatible(t, err)
	}
	c8, err := Quant(16, 8)
	if err != nil {
		t.Fatal(err)
	}
	fc, err := NewFloor(c8, IDU64, rid, 1, 1, 100, 1)
	if err != nil {
		t.Fatal(err)
	}
	defer fc.Close()
	if _, err := da.Within(fc); err == nil {
		t.Fatal("floor of another config accepted")
	} else {
		asIncompatible(t, err)
	}
	fk, err := NewFloor(c, IDUTF8, rid, 1, 1, 100, 1)
	if err != nil {
		t.Fatal(err)
	}
	defer fk.Close()
	if _, err := da.Within(fk); err == nil {
		t.Fatal("floor of another id kind accepted")
	} else {
		asIncompatible(t, err)
	}
	// Invalid floors are rejected at construction; invalid nulls at measure.
	for _, bad := range []struct {
		name                           string
		cfg                            CodecConfig
		kind                           IDKind
		nulls, changed, total, hamming uint64
	}{
		{"changed > total", c, IDU64, 1, 5, 4, 1},
		{"total 0", c, IDU64, 1, 0, 0, 1},
		{"hamming > units", c, IDU64, 1, 1, 1, 17},
		{"nulls 0", c, IDU64, 0, 1, 1, 1},
		{"unknown kind", c, IDKind(2), 1, 1, 1, 1},
		{"invalid config", CodecConfig{}, IDU64, 1, 1, 1, 1},
	} {
		if _, err := NewFloor(bad.cfg, bad.kind, rid, bad.nulls, bad.changed, bad.total, bad.hamming); err == nil {
			t.Fatalf("%s accepted", bad.name)
		} else {
			asInvalid(t, err)
		}
	}
	if _, err := MeasureFloor([]*Diff{de}); err == nil {
		t.Fatal("diff without common rows accepted")
	} else {
		wantU64(t, "null index", asInvalid(t, err).Field, 0)
	}
	if _, err := MeasureFloor(nil); err == nil {
		t.Fatal("empty measure accepted")
	}
	if _, err := MeasureFloor([]*Diff{da, nil}); err == nil {
		t.Fatal("nil diff accepted")
	}
}

// 200 rows; the null changes rows 0..99 by 2 units. The candidate changes
// rows 0..98 by 2 and row 150 by 10: its p99 ignores row 150, so it is
// within the floor, and only the per-row check catches it.
func TestEvaluateNamesEveryFailedCheckAndTheRowsAboveMax(t *testing.T) {
	ref := rowsWithChanges(t, 200, 0, 0, 4)
	null := rowsWithChanges(t, 200, 100, 2, 4)
	defer ref.Close()
	defer null.Close()
	f, err := MeasureFloor([]*Diff{mustDiff(t, ref, null)})
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	if m, ok := f.MaxHamming(); !ok || m != 2 || f.Hamming() != 2 {
		t.Fatalf("floor: %v", f.Report())
	}
	c := ref.Config()
	bpv := int(c.BytesPerVector())
	ids := make([]uint64, 200)
	rows := make([]byte, 0, 200*bpv)
	for i := range ids {
		sym := make([]uint8, 16)
		flip := 0
		if i < 99 {
			flip = 2
		} else if i == 150 {
			flip = 10
		}
		for u := range sym {
			sym[u] = 4
			if u < flip {
				sym[u] = 5
			}
		}
		ids[i] = uint64(i)
		rows = append(rows, packQuant(sym, 3, bpv)...)
	}
	cand := mustEncoding(t, U64IDs(ids...), rows, c, nil)
	defer cand.Close()
	d := mustDiff(t, ref, cand)
	if w, err := d.Within(f); err != nil || !w {
		t.Fatalf("within: %v %v", w, err)
	}
	plain, err := d.Evaluate(f, GateOptions{})
	if err != nil || !plain.Passed || len(plain.Reasons) != 0 || len(plain.Rows) != 0 {
		t.Fatalf("plain: %+v %v", plain, err)
	}
	strict, err := d.Evaluate(f, GateOptions{PerRow: true})
	if err != nil || strict.Passed || !reflect.DeepEqual(strict.Reasons, []Reason{ReasonRowAboveMax}) ||
		!reflect.DeepEqual(strict.Rows, []ID{U64ID(150)}) {
		t.Fatalf("per row: %+v %v", strict, err)
	}
	// Every failed check is named, not only the first.
	tight, err := NewFloor(c, IDU64, ref.StateID(), 1, 1, 200, 1)
	if err != nil {
		t.Fatal(err)
	}
	defer tight.Close()
	tightJSON, err := json.Marshal(tight)
	if err != nil {
		t.Fatal(err)
	}
	tightMax, err := LoadFloor(append(tightJSON[:len(tightJSON)-1], `,"max_hamming":1}`...))
	if err != nil {
		t.Fatal(err)
	}
	defer tightMax.Close()
	all, err := d.Evaluate(tightMax, GateOptions{PerRow: true})
	if err != nil || !reflect.DeepEqual(all.Reasons, []Reason{ReasonChangedRatio, ReasonHamming, ReasonRowAboveMax}) || len(all.Rows) != 100 {
		t.Fatalf("tight: %+v %v", all.Reasons, err)
	}
	// A floor without MaxHamming refuses the per-row check and keeps its plain verdict.
	if v, err := d.Evaluate(tight, GateOptions{}); err != nil || v.Passed {
		t.Fatalf("plain on a floor without max: %+v %v", v, err)
	}
	_, err = d.Evaluate(tight, GateOptions{PerRow: true})
	asIncompatible(t, err)
}

func TestFloorReportAndInverse(t *testing.T) {
	ref := rowsWithChanges(t, 100, 0, 0, 4)
	a := rowsWithChanges(t, 100, 1, 1, 4)
	defer ref.Close()
	defer a.Close()
	da := mustDiff(t, ref, a)
	f, err := MeasureFloor([]*Diff{da})
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	raw, err := json.Marshal(f.Report())
	if err != nil {
		t.Fatal(err)
	}
	want := `{"version":"semq-floor/1","config":{"operator":"quant","dim":16,"bins":4,"rule_revision":0},` +
		`"id_kind":"u64","reference_id":"` + hexOf(ref.StateID()) + `","nulls":1,"changed_rows":1,"total_rows":100,"hamming":1}`
	if string(raw) != want {
		t.Fatalf("report\n got %s\nwant %s", raw, want)
	}
	if m, ok := f.MaxHamming(); !ok || m != 1 {
		t.Fatalf("MaxHamming: %d %v", m, ok)
	}
	// The Floor's own JSON form, written and read by the core, carries max_hamming.
	full, err := json.Marshal(f)
	if err != nil || string(full) != want[:len(want)-1]+`,"max_hamming":1}` {
		t.Fatalf("floor json %s %v", full, err)
	}
	back, err := LoadFloor(full)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(back.Close)
	if m, ok := back.MaxHamming(); !ok || m != 1 || back.Report() != f.Report() {
		t.Fatalf("LoadFloor: %+v", back.Report())
	}
	withNote, err := LoadFloor([]byte(`{"note":[1,{}],` + string(full[1:])))
	if err != nil {
		t.Fatal(err)
	}
	withNote.Close()
	for _, bad := range []string{"", "{}", string(full) + " x", strings.Replace(string(full), `"max_hamming":1`, `"max_hamming":0`, 1)} {
		_, err := LoadFloor([]byte(bad))
		asInvalid(t, err)
	}
	closed, _ := LoadFloor(full)
	closed.Close()
	if _, err := json.Marshal(closed); err == nil {
		t.Fatal("marshaled a closed floor")
	}
	// The inverse, from the report and from its JSON, yields the same floor.
	var decoded FloorReport
	if err := json.Unmarshal(raw, &decoded); err != nil {
		t.Fatal(err)
	}
	for _, r := range []FloorReport{f.Report(), decoded} {
		g, err := FloorFromReport(r)
		if err != nil {
			t.Fatal(err)
		}
		t.Cleanup(g.Close)
		if g.Report() != f.Report() || g.Config() != f.Config() || g.IDKind() != IDU64 || g.ReferenceID() != ref.StateID() {
			t.Fatalf("inverse: %+v", g.Report())
		}
		if w, err := da.Within(g); err != nil || !w {
			t.Fatalf("within the rebuilt floor: %v %v", w, err)
		}
	}
	// Strict: every violation of the form is InvalidInputError.
	base := f.Report()
	for _, bad := range []struct {
		name   string
		mutate func(*FloorReport)
	}{
		{"version", func(r *FloorReport) { r.Version = "semq-floor/2" }},
		{"id_kind", func(r *FloorReport) { r.IDKind = "unknown" }},
		{"empty reference_id", func(r *FloorReport) { r.ReferenceID = "" }},
		{"short reference_id", func(r *FloorReport) { r.ReferenceID = r.ReferenceID[:63] }},
		{"odd-length reference_id", func(r *FloorReport) { r.ReferenceID += "0" }},
		{"66 hex characters", func(r *FloorReport) { r.ReferenceID += "00" }},
		{"128 hex characters", func(r *FloorReport) { r.ReferenceID += r.ReferenceID }},
		{"non-hex reference_id", func(r *FloorReport) { r.ReferenceID = "zz" + r.ReferenceID[2:] }},
		{"non-hex last character", func(r *FloorReport) { r.ReferenceID = r.ReferenceID[:63] + "g" }},
		{"operator", func(r *FloorReport) { r.Config.Operator = "other" }},
		{"config parameter", func(r *FloorReport) { r.Config.Parameter = 1 }},
		{"nulls 0", func(r *FloorReport) { r.Nulls = 0 }},
		{"changed > total", func(r *FloorReport) { r.ChangedRows = 101 }},
		{"hamming > units", func(r *FloorReport) { r.Hamming = 17 }},
	} {
		r := base
		bad.mutate(&r)
		if _, err := FloorFromReport(r); err == nil {
			t.Fatalf("%s accepted", bad.name)
		} else {
			asInvalid(t, err)
		}
	}
}

// The JSON reader of FloorReport applies the core's rules for the floor
// schema: the known keys strictly, other keys ignored. Any violation is
// InvalidInputError and leaves the target untouched.
func TestFloorReportJSONUsesTheCore(t *testing.T) {
	const ref = "c742dfed3bdd20edb3f5d3e4f7086528f56b95a33ae03048a228d216d2452ce1"
	valid := `{"version":"semq-floor/1","config":{"operator":"quant","dim":16,"bins":4,"rule_revision":0},` +
		`"id_kind":"u64","reference_id":"` + ref + `","nulls":1,"changed_rows":1,"total_rows":100,"hamming":1}`
	want := FloorReport{
		Version: FloorVersion, Config: ConfigReport{Operator: "quant", Dim: 16, Parameter: 4, RuleRevision: 0},
		IDKind: "u64", ReferenceID: ref, Nulls: 1, ChangedRows: 1, TotalRows: 100, Hamming: 1,
	}
	// Round trip: the document decodes, builds a floor and marshals back
	// byte for byte. Key order, whitespace and unknown keys are not part of
	// what is read.
	var r FloorReport
	if err := json.Unmarshal([]byte(valid), &r); err != nil || r != want {
		t.Fatalf("decoded %+v %v", r, err)
	}
	f, err := FloorFromReport(r)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	if out, err := json.Marshal(f.Report()); err != nil || string(out) != valid {
		t.Fatalf("round trip\n got %s\nwant %s (%v)", out, valid, err)
	}
	reordered := "{ \"hamming\" : 1 ,\"total_rows\":100, \"changed_rows\":1, \"nulls\":1, \"reference_id\":\"" + ref +
		"\", \"id_kind\":\"u64\", \"config\": { \"rule_revision\":0, \"bins\":4, \"dim\":16, \"operator\":\"quant\" }, " +
		"\"version\":\"semq-floor/1\", \"max_hamming\": 1, \"note\": [1, {\"a\": null}] }"
	var r2 FloorReport
	if err := json.Unmarshal([]byte(reordered), &r2); err != nil || r2 != want {
		t.Fatalf("reordered: %+v %v", r2, err)
	}
	for _, text := range []string{
		`null`, `[]`, `{}`, `"semq-floor/1"`,
		strings.Replace(valid, `"nulls":1`, `"nulls":1.0`, 1),
		strings.Replace(valid, `"nulls":1`, `"nulls":"1"`, 1),
		strings.Replace(valid, `"nulls":1`, `"nulls":-1`, 1),
		strings.Replace(valid, `"nulls":1`, `"nulls":18446744073709551616`, 1),
		strings.Replace(valid, `"hamming":1`, `"hamming":1,"hamming":1`, 1),
		strings.Replace(valid, `,"hamming":1`, ``, 1),
		strings.Replace(valid, "semq-floor/1", "semq-floor/2", 1),
		strings.Replace(valid, `"u64"`, `"u32"`, 1),
		strings.Replace(valid, `"rule_revision":0`, `"rule_revision":1`, 1),
	} {
		r := want
		err := json.Unmarshal([]byte(text), &r)
		if err == nil {
			t.Fatalf("%s decoded", text)
		}
		var ie *InvalidInputError
		if !errors.As(err, &ie) {
			t.Fatalf("%s: %T %v", text, err, err)
		}
		if r != want {
			t.Errorf("%s: target modified: %+v", text, r)
		}
	}
}

func TestFloorCloseIsIdempotentAndFieldsAreCached(t *testing.T) {
	ref := rowsWithChanges(t, 100, 0, 0, 4)
	a := rowsWithChanges(t, 100, 1, 1, 4)
	defer ref.Close()
	defer a.Close()
	da := mustDiff(t, ref, a)
	f, err := MeasureFloor([]*Diff{da})
	if err != nil {
		t.Fatal(err)
	}
	r := f.Report()
	f.Close()
	f.Close()
	if f.Report() != r || f.ReferenceID() != ref.StateID() || f.Config() != ref.Config() {
		t.Fatal("cached fields lost on close")
	}
	if _, err := da.Within(f); err == nil {
		t.Fatal("within a closed floor")
	} else {
		asInvalid(t, err)
	}
	if _, err := da.Within(nil); err == nil {
		t.Fatal("within a nil floor")
	} else {
		asInvalid(t, err)
	}
}

func TestP99NearestRank(t *testing.T) {
	// 101 changed rows with hammings 1..101: k = 101 - 1 = 100 -> value 100.
	c, _ := Quant(128, 4)
	bpv := int(c.BytesPerVector()) // 48
	const n = 101
	ids := make([]uint64, n)
	base := make([]byte, 0, n*bpv)
	cand := make([]byte, 0, n*bpv)
	for i := 0; i < n; i++ {
		sym := make([]uint8, 128)
		for u := range sym {
			sym[u] = 4
		}
		ids[i] = uint64(i)
		base = append(base, packQuant(sym, 3, bpv)...)
		for u := 0; u < i+1; u++ {
			sym[u] = 5 // hamming i + 1
		}
		cand = append(cand, packQuant(sym, 3, bpv)...)
	}
	a := mustEncoding(t, U64IDs(ids...), base, c, nil)
	defer a.Close()
	b := mustEncoding(t, U64IDs(ids...), cand, c, nil)
	defer b.Close()
	d, err := a.Diff(b)
	if err != nil {
		t.Fatal(err)
	}
	defer d.Close()
	f, err := MeasureFloor([]*Diff{d})
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	if f.ChangedRows() != 101 || f.TotalRows() != 101 || f.Hamming() != 100 {
		t.Fatalf("p99 floor %+v", f.Report())
	}
}

// ---- build info, handles ---------------------------------------------------

func TestInfo(t *testing.T) {
	info := Info()
	if info.SDKVersion == "" || info.CoreVersion == "" || info.BuildID == "" {
		t.Fatalf("empty field in %+v", info)
	}
	for _, op := range []string{"orbit", "phase", "quant"} {
		if info.Backend[op] == "" {
			t.Fatalf("no backend for %s", op)
		}
	}
	// CI forces each kernel the host has and names it here, so a kernel that
	// silently falls back to scalar fails instead of passing as scalar. Every
	// kernel implements orbit.
	if want := os.Getenv("SEMQ_EXPECT_BACKEND"); want != "" && info.Backend["orbit"] != want {
		t.Fatalf("orbit backend %q, want %q", info.Backend["orbit"], want)
	}
}

func TestCloseIsIdempotentAndUseAfterCloseIsInvalid(t *testing.T) {
	c := quant44(t)
	codec := mustCodec(t, c)
	e := mustEncoding(t, U64IDs(1), []byte{7, 7}, c, nil)
	d, err := e.Diff(e)
	if err != nil {
		t.Fatal(err)
	}
	e.Close()
	e.Close()
	if _, err := codec.Decode(e); err == nil {
		t.Fatal("decode of a closed encoding")
	} else {
		asInvalid(t, err)
	}
	if _, err := e.Concat(e); err == nil {
		t.Fatal("concat of a closed encoding")
	}
	if e.Len() != 1 || e.Config() != c || e.StateID() == ([32]byte{}) {
		t.Fatal("cached fields lost on close")
	}
	func() {
		defer func() {
			if recover() == nil {
				t.Fatal("Rows on a closed encoding did not panic")
			}
		}()
		e.Rows()
	}()
	// The diff still works after both encodings are closed.
	if d.NUnchanged() != 1 {
		t.Fatal("diff after close")
	}
	if units, err := d.Units(U64ID(1)); err != nil || len(units) != 0 {
		t.Fatalf("units after close: %v %v", units, err)
	}
	d.Close()
	d.Close()
	if _, err := d.Units(U64ID(1)); err == nil {
		t.Fatal("units of a closed diff")
	}
	if _, err := MeasureFloor([]*Diff{d}); err == nil {
		t.Fatal("measure of a closed diff")
	}
	codec.Close()
	codec.Close()
	var nilEnc *Encoding
	if _, err := codec.Unpack(nilEnc); err == nil {
		t.Fatal("nil encoding")
	}
}

// The first lines a reader writes, and what the String forms say: the same
// text every binding produces for this data.
func TestDirectConstructorsAndStringForms(t *testing.T) {
	vectors := []float32{0.6, 0.8, 0, 0, 0, 0.6, 0.8, 0, 0, 0, 0.6, 0.8}
	ids := UTF8IDs("doc-1", "doc-2", "doc-3")
	manifest := map[string]string{"encoder": "example-encoder", "encoder_revision": "1"}
	codec, err := NewQuantCodec(4, 4)
	if err != nil {
		t.Fatal(err)
	}
	defer codec.Close()
	if got := codec.Config().String(); got != "quant(dim=4, bins=4)" {
		t.Fatalf("config: %q", got)
	}
	if _, err := NewPhaseCodec(4, 16); err != nil {
		t.Fatal(err)
	}
	if _, err := NewOrbitCodec(4, 50); err != nil {
		t.Fatal(err)
	}
	encode := func(v []float32, ids IDs, m map[string]string) *Encoding {
		e, err := codec.Encode(ids, v, m)
		if err != nil {
			t.Fatal(err)
		}
		return e
	}
	state := encode(vectors, ids, manifest)
	defer state.Close()
	reference, err := Load(state.Bytes())
	if err != nil {
		t.Fatal(err)
	}
	defer reference.Close()
	if got := reference.String(); got != "Encoding(3 rows, quant(dim=4, bins=4), state_id 6e6f8a89bae4...)" {
		t.Fatalf("encoding: %q", got)
	}
	diffWith := func(candidate *Encoding) *Diff {
		d, err := reference.Diff(candidate)
		if err != nil {
			t.Fatal(err)
		}
		candidate.Close()
		return d
	}
	rebuilt := append([]float32(nil), vectors...)
	copy(rebuilt[8:12], []float32{0.8, 0, 0, 0.6})
	diff := diffWith(encode(rebuilt, ids, manifest))
	defer diff.Close()
	cases := []struct {
		name, want string
		diff       *Diff
	}{
		{"replaced", "1 of 3 rows changed: doc-3 (hamming 3). 0 added, 0 removed.", diff},
		{"same", "0 of 3 rows changed. 0 added, 0 removed.", diffWith(encode(vectors, ids, manifest))},
		{"manifest", "0 of 3 rows changed. 0 added, 0 removed. Manifest changed: encoder.", diffWith(encode(vectors, ids, map[string]string{"encoder": "other", "encoder_revision": "1"}))},
		{"added", "0 of 3 rows changed. 1 added, 0 removed.", diffWith(encode(append(append([]float32(nil), vectors...), 1, 0, 0, 0), UTF8IDs("doc-1", "doc-2", "doc-3", "doc-4"), manifest))},
	}
	for _, c := range cases {
		if got := c.diff.String(); got != c.want {
			t.Errorf("%s: %q", c.name, got)
		}
	}
	var nulls []*Diff
	for i := 0; i < 3; i++ {
		nulls = append(nulls, diffWith(encode(vectors, ids, manifest)))
	}
	floor, err := MeasureFloor(nulls)
	if err != nil {
		t.Fatal(err)
	}
	defer floor.Close()
	if got := floor.String(); got != "Floor(0 of 3 rows, hamming 0, from 3 nulls)" {
		t.Fatalf("floor: %q", got)
	}
	within, err := diff.Within(floor)
	if err != nil || within {
		t.Fatalf("within: %v %v", within, err)
	}
	closed := cases[1].diff
	closed.Close()
	if got := closed.String(); got != "Diff(closed)" {
		t.Fatalf("closed diff: %q", got)
	}
}
