---
search:
  boost: 1.25
---

# Go API

Import `github.com/The-SEMQ-Group/semq/bindings/go` as `semq`. The module
includes the C core, which cgo compiles and links statically; see
[installation](../installation.md).
For a complete program, use the [quickstart](../quickstart.md).

## Conventions

- A vector is `[]float32` with exactly `n * dim` unit-norm values, row-major.
- Ids are `IDs`: `semq.U64IDs(1, 2, 3)` or `semq.UTF8IDs("a", "b")`; an
  empty set names its kind (`IDs{Kind: semq.IDUTF8}`). Single ids are
  `semq.U64ID(7)` / `semq.UTF8ID("doc-7")`.
- `Codec`, `Encoding`, `Diff` and `Floor` own native handles: immutable after
  construction, safe for concurrent use, released with `Close()` (idempotent,
  with a finalizer as fallback). Accessors return copies.
- Errors are six types matched with `errors.As`; allocation failure wraps
  `ErrNoMemory` (`errors.Is`).

## Surface

| Symbol | Contract |
| --- | --- |
| `Quant(dim, bins uint32) (CodecConfig, error)`, `Phase(dim, sectors uint32)`, `Orbit(dim, scale uint32)`, `ConfigFromBytes([13]byte)` | Constructors; a `CodecConfig` is a comparable value (`==` compares the canonical bytes) |
| `(CodecConfig) Operator() Operator`, `Dim()`, `Parameter()`, `RuleRevision()`, `BytesPerVector()`, `UnitsPerRow()`, `MaxMagnitude() (float32, bool)`, `Bytes() [13]byte`, `String()` | Accessors; `MaxMagnitude` reports `false` for non-quant configs |
| `OperatorOrbit`, `OperatorPhase`, `OperatorQuant` | The operator values `0`, `1`, `2` |
| `IDKind`: `IDU64`, `IDUTF8` | The id kinds `0` and `1`; the values are pinned in files |
| `NewQuantCodec(dim, bins uint32)`, `NewPhaseCodec(dim, sectors uint32)`, `NewOrbitCodec(dim, scale uint32)`, `NewCodec(cfg CodecConfig) (*Codec, error)` | `Config()`, `Backend()`, `Encode(ids IDs, vectors []float32, manifest map[string]string) (*Encoding, error)`, `Decode(e) ([]float32, error)`, `Unpack(e) ([]byte, error)`, `Close()` |
| `NewEncoding(ids IDs, rows []byte, cfg CodecConfig, manifest map[string]string) (*Encoding, error)` | The low-level constructor from canonical rows |
| `Load(b []byte)`, `Read(r io.Reader)` | Parse a file image |
| `(*Encoding) WriteTo(w io.Writer) (int64, error)`, `Bytes() []byte` | Write the file image |
| `(*Encoding) Config()`, `IDKind()`, `Len()`, `Rows()`, `Row(i)`, `IDsU64()`, `IDsUTF8()`, `Get(id ID) (row []byte, ok bool, err error)`, `Manifest()`, `ContentDigest() [32]byte`, `StateID() [32]byte` | Access |
| `(*Encoding) Concat(others ...*Encoding) (*Encoding, error)`, `Diff(candidate *Encoding) (*Diff, error)` | Verbs |
| `(*Diff) ReferenceID()`, `CandidateID()`, `Config()`, `IDKind()`, `Added() []ID`, `Removed() []ID`, `Changed() []Change`, `NUnchanged() uint64`, `ManifestChanges() map[string]ManifestChange`, `Units(id ID) ([]Unit, error)`, `Within(f *Floor) (bool, error)`, `Report() Report`, `Close()` | `Report` marshals to the [report schema](contracts.md#report-schema); `Within` returns `*IncompatibleError` when the floor was measured against another config, id kind or reference |
| `Report`, `ConfigReport`, `ChangeReport` | The report value types; `ConfigReport` marshals as `{operator, dim, bins \| sectors \| scale, rule_revision}` and `ChangeReport` as `[id, hamming]` |
| `NewFloor(config CodecConfig, kind IDKind, referenceID [32]byte, nulls, changedRows, totalRows, hamming uint64) (*Floor, error)`, `MeasureFloor(nulls []*Diff) (*Floor, error)`, `FloorFromReport(r FloorReport) (*Floor, error)` | Constructors; every field is validated by the core, and the nulls of a measure must share config, id kind and reference |
| `(*Floor) Config()`, `IDKind()`, `ReferenceID() [32]byte`, `Nulls()`, `ChangedRows()`, `TotalRows()`, `Hamming()`, `Report() FloorReport`, `Close()` | `FloorReport` marshals to the [floor schema](contracts.md#floor-schema) (`semq-floor/1`, the constant `FloorVersion`) and decodes it strictly (exactly its keys, integer counts; any other shape is `*InvalidInputError`); `FloorFromReport` is its strict inverse |
| `Info() BuildInfo` | `SDKVersion`, `CoreVersion`, `Backend map[string]string`, `BuildID` |
| `*InvalidInputError`, `*IncompatibleError`, `*FormatError`, `*IntegrityError`, `*UnsupportedError`, `*NativeError`, `ErrNoMemory` | Errors; see [Go errors](go-errors.md) |

To read every exported symbol with its doc comment, run `go doc` in a module
that requires the binding:

```sh
go doc -all github.com/The-SEMQ-Group/semq/bindings/go
```

## Next steps

- [Run the quickstart](../quickstart.md).
- [Handle errors](go-errors.md).
