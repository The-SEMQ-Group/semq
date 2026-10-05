# SEMQ Go binding

Go package for the SEMQ core: deterministic symbolic encoding of float32
vectors with content-addressed identities. The core (C) owns every rule that
determines bytes or verdicts; this package validates Go representations, maps
errors and does I/O.

Module: `github.com/The-SEMQ-Group/semq/bindings/go`, package `semq`, Go 1.21+,
cgo.

## Build

```sh
go get github.com/The-SEMQ-Group/semq/bindings/go
```

The module carries the C core and cgo compiles it, so no native library,
CMake or environment variables are needed: only a C11 compiler, which cgo
always requires (GCC or Clang; MinGW-w64 GCC on Windows). The core is linked
statically and needs only libc and libm at run time.

`internal/core` is a copy of the repository's `include/` and `src/`, written
by `tools/gen_go_core.py`; CI fails if it differs from them. Change the core
in `src/`, never in the copy, and then regenerate it:

```sh
python tools/gen_go_core.py
cd bindings/go && go test ./...
```

Each SIMD kernel is compiled with the instruction-set flags CMake gives it,
and the core checks the selected kernels against known answers whenever it
creates a codec, so a compiler that breaks determinism (for example through
`CGO_CFLAGS=-ffast-math`) is reported as a native error rather than producing
different bytes.

## Surface

| concept | Go |
|---|---|
| config | `semq.Quant(dim, bins)`, `semq.Phase(dim, sectors)`, `semq.Orbit(dim, scale)` → `(CodecConfig, error)`; `ConfigFromBytes([13]byte)` |
| codec | `semq.NewCodec(cfg) (*Codec, error)`; `Encode(ids, vectors, manifest)`, `Decode(e)`, `Unpack(e)`, `Backend()`, `Close()` |
| encoding | `semq.NewEncoding(ids, rows, cfg, manifest)`, `semq.Load(b)`, `semq.Read(r)`; `WriteTo(w)`, `Bytes()`, `Rows()`, `Row(i)`, `IDsU64()`, `IDsUTF8()`, `Get(id)`, `Manifest()`, `ContentDigest()`, `StateID()`, `Concat(others...)`, `Diff(candidate)`, `Close()` |
| diff | `Added()`, `Removed()`, `Changed()`, `NUnchanged()`, `ManifestChanges()`, `Units(id)`, `Within(floor)`, `Report()`, `Close()` |
| floor | `semq.NewFloor(cfg, kind, referenceID, nulls, changed, total, hamming)`, `semq.MeasureFloor(nulls)`, `semq.FloorFromReport(r)`; `Config()`, `IDKind()`, `ReferenceID()`, `Nulls()`, `ChangedRows()`, `TotalRows()`, `Hamming()`, `Report()`, `Close()` |
| build | `semq.Info() BuildInfo` |
| ids | `semq.U64IDs(...)`, `semq.UTF8IDs(...)` for sets; `semq.U64ID(v)`, `semq.UTF8ID(s)` for one id |
| errors | `*InvalidInputError`, `*IncompatibleError`, `*FormatError`, `*IntegrityError`, `*UnsupportedError`, `*NativeError` via `errors.As`; `ErrNoMemory` via `errors.Is` |

`CodecConfig` is a comparable value. `Codec`, `Encoding`, `Diff` and `Floor`
hold native handles: immutable, safe for concurrent use, released with
`Close` (idempotent; a finalizer is the fallback). Accessors return copies.
A `Floor` is bound to the config, id kind and reference state its nulls were
measured against; `Within` returns `*IncompatibleError` for any other diff.

## Example

```go
cfg, err := semq.Quant(4, 4)
if err != nil { return err }
codec, err := semq.NewCodec(cfg)
if err != nil { return err }
defer codec.Close()

vectors := []float32{1, 0, 0, 0, 0, 1, 0, 0} // 2 rows of dim 4, unit norm
enc, err := codec.Encode(semq.U64IDs(2, 1), vectors, map[string]string{"encoder": "demo"})
if err != nil { return err }
defer enc.Close()

var buf bytes.Buffer
if _, err := enc.WriteTo(&buf); err != nil { return err }
back, err := semq.Load(buf.Bytes())
if err != nil { return err }
defer back.Close()

d, err := enc.Diff(back)
if err != nil { return err }
defer d.Close()
id := back.StateID()
fmt.Printf("%d unchanged, state %x\n", d.NUnchanged(), id[:])
```

Errors from the input contract name the failing row and coordinate:

```go
var ie *semq.InvalidInputError
if errors.As(err, &ie) && ie.Row != nil { fmt.Println("row", *ie.Row) }
```

## License

[PolyForm Noncommercial License 1.0.0](LICENSE.md). Production use by
companies, and any other use the license does not permit, requires a separate
license from The SEMQ Group Inc.; write to licensing@thesemqgroup.ai.
