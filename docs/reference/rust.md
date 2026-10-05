---
search:
  boost: 1.25
---

# Rust API

The `semq` crate wraps the C core with checked slices and owned results;
its private `sys` module holds the raw declarations. See the
[complete API on docs.rs](https://docs.rs/semq/latest/semq/).
For a complete program, use the [quickstart](../quickstart.md).

## Conventions

- Vectors are `&[f32]` of exactly `n * dim` unit-norm values, row-major.
- Ids are an `Ids<'_>` view: `Ids::u64(&[1, 2, 3])` or `Ids::utf8(&["a", "b"])`;
  slices and arrays of `u64`, `&str` and `String` convert with `Into`. A
  single id is `Id::U64(7)` or `Id::Utf8("doc-7".into())`.
- `Manifest` is `BTreeMap<String, String>`; pass `Option<&Manifest>`.
- `Codec`, `Encoding`, `Diff` and `Floor` are `Send + Sync` and freed on drop.
  `rows()`, `row(i)`, `get(&id)` and `u64` ids are zero-copy borrows of the
  `Encoding`.
- `Error` has six variants; `Result<T>` is the crate's alias. Out of memory in
  the core is `Error::Native` with status `6`; `Encoding::read` and `write`
  return `io::Result`, with the typed error as the `io::Error` source.

## Surface

| Item | Contract |
| --- | --- |
| `Operator::{Orbit, Phase, Quant}` | The operator values `0`, `1`, `2`; `name()`, `parameter_name()` |
| `CodecConfig::quant(dim, bins)?`, `::phase(dim, sectors)?`, `::orbit(dim, scale)?`, `::orbit_default(dim)?`, `::from_bytes(&[u8; 13])?` | Constructors; `Copy`, equality and hashing by the canonical bytes |
| `config.to_bytes()`, `operator()`, `dim()`, `rule_revision()`, `parameter()`, `bins()`/`sectors()`/`scale()` (`Option<u32>`), `bytes_per_vector()`, `units_per_row()`, `max_magnitude()` (`Option<f32>`, quant only) | Accessors |
| `Codec::quant(dim, bins)?`, `Codec::phase(dim, sectors)?`, `Codec::orbit(dim, scale)?`, `Codec::new(&config)?` | `config()`, `backend()`, `encode(ids, &vectors, manifest)?`, `decode(&e)? -> Vec<f32>`, `unpack(&e)? -> Vec<u8>` |
| `Encoding::new(ids, &rows, &config, manifest)?`, `Encoding::from_bytes(&bytes)?`, `Encoding::read(reader)?` | Constructors from canonical rows or a file image |
| `encoding.to_bytes()`, `write(writer)?`, `config()`, `id_kind()`, `len()`, `is_empty()`, `rows()`, `row(i)`, `ids()`, `get(&id)? -> Option<&[u8]>`, `manifest()`, `content_digest()`, `state_id()`, `iter()`, `concat(&[&e1, &e2])?`, `diff(&candidate)?` | Access and verbs; `PartialEq` compares `state_id` |
| `diff.reference_id()`, `candidate_id()`, `config()`, `id_kind()`, `added()`, `removed()`, `changed() -> Vec<(Id, u64)>`, `n_unchanged()`, `manifest_changes()`, `units(&id)?`, `within(&floor)?`, `as_report() -> DiffReport` | `DiffReport` holds the [report schema](contracts.md#report-schema) fields; `within` is `Incompatible` for a floor of another config, id kind or reference |
| `Floor::measure(&nulls)?` (any iterable of `Diff` or `&Diff`), `Floor::new(&config, id_kind, reference_id, nulls, changed_rows, total_rows, hamming)?`, `Floor::from_report(&report)?` | The floor, bound to the config, id kind and reference `state_id` of the nulls it was measured from; `new` and `from_report` validate every field |
| `floor.config()`, `id_kind()`, `reference_id() -> [u8; 32]`, `nulls()`, `changed_rows()`, `total_rows()`, `hamming()`, `as_report() -> FloorReport` | Accessors; `FloorReport` holds the `semq-floor/1` fields, `config` as in `DiffReport`, `reference_id` as hex; equality and hashing are by the seven fields |
| `build_info() -> BuildInfo` | `sdk_version`, `core_version`, `backend: BTreeMap<Operator, String>`, `build_id` |
| `Error::{InvalidInput, Incompatible, FormatError, IntegrityError, Unsupported, Native}` | See [Rust errors](rust-errors.md) |

## Next steps

- [Run the quickstart](../quickstart.md).
- [Handle errors](rust-errors.md).
