# API reference

Choose your language for types, signatures, and return values. All four bindings
expose the same five types: `CodecConfig`, `Codec`, `Encoding`, `Diff` and
`Floor`, plus the build information. For a first integration, start with the
[quickstart](../quickstart.md).

## Choose your reference

<div class="grid cards" markdown>

- **[Python](python.md)**

    NumPy arrays and zero-copy row views.

- **[Rust](rust.md)**

    Checked slices and ownership.

- **[Go](go.md)**

    Float32 slices and explicit handle cleanup through cgo.

- **[TypeScript](typescript.md)**

    Typed arrays and asynchronous WASM setup.

</div>

Each language has a **Core API** page and an **Errors** page.

## Shared operations, language-specific shapes

| Operation | Python | Rust | Go | TypeScript |
| --- | --- | --- | --- | --- |
| Config | `CodecConfig.quant(dim, bins)` | `CodecConfig::quant(dim, bins)?` | `semq.Quant(dim, bins)` | `CodecConfig.quant(dim, bins)` |
| Codec | `Codec.quant(dim, bins)` or `Codec(config)` | `Codec::quant(dim, bins)?` or `Codec::new(&config)?` | `semq.NewQuantCodec(dim, bins)` or `semq.NewCodec(config)` | `await Codec.quant(dim, bins)` or `await Codec.create(config)` |
| Encode | `codec.encode(vectors, ids=, manifest=)` | `codec.encode(ids, &vectors, manifest)?` | `codec.Encode(ids, vectors, manifest)` | `codec.encode({ ids, vectors, manifest })` |
| Decode / unpack | `codec.decode(e)`, `codec.unpack(e)` | `codec.decode(&e)?`, `codec.unpack(&e)?` | `codec.Decode(e)`, `codec.Unpack(e)` | `codec.decode(e)`, `codec.unpack(e)` |
| Save / load | `e.save(path)`, `Encoding.load(path)` | `e.to_bytes()`, `Encoding::from_bytes(&b)?` | `e.WriteTo(w)`, `semq.Load(b)` | `e.toBytes()`, `Encoding.fromBytes(u8)` |
| Concat / diff | `a.concat(b, c)`, `a.diff(b)` | `a.concat(&[&b, &c])?`, `a.diff(&b)?` | `a.Concat(b, c)`, `a.Diff(b)` | `a.concat(b, c)`, `a.diff(b)` |
| Within / measure | `d.within(f)`, `Floor.measure([d1, d2])` | `d.within(&f)?`, `Floor::measure(&nulls)?` | `d.Within(f)`, `semq.MeasureFloor(ds)` | `d.within(f)`, `Floor.measure([d1, d2])` |
| Evaluate | `d.evaluate(f, per_row=True)` | `d.evaluate(&f, &GateOptions::new().per_row(true))?` | `d.Evaluate(f, semq.GateOptions{PerRow: true})` | `d.evaluate(f, { perRow: true })` |
| Measure for per-row | `Floor.measure(ds, per_row=True)` | `Floor::measure_for(&nulls, &GateOptions::new().per_row(true))?` | `semq.MeasureFloorFor(ds, semq.GateOptions{PerRow: true})` | `Floor.measure(ds, { perRow: true })` |
| Ids `u64` / `utf8` | `int` / `str` | `u64` / `&str` | `uint64` / `string` | `bigint` / `string` |
| Digests | `bytes` (32) | `[u8; 32]` | `[32]byte` | `Uint8Array` (32) |
| Release | garbage collector | `Drop` | `Close()` | `dispose()` |
| Print | `str(x)` | `x.to_string()` | `x.String()` | `String(x)` |

## Differences that affect application code

| Concern | Python | Rust | Go | TypeScript |
| --- | --- | --- | --- | --- |
| Vectors | NumPy float32 `[n, dim]` | `&[f32]` of `n * dim` | `[]float32` of `n * dim` | `Float32Array` of `n * dim` |
| Rows and `get(id)` | zero-copy read-only views | borrowed slices | copies | copies |
| Async | none | none | none | one `await` to load the module |
| Out of memory | `MemoryError` | `Error::Native` | `errors.Is(err, ErrNoMemory)` | `RangeError` |

## Source and generated reference

Python signatures come directly from docstrings through mkdocstrings. The
[TypeDoc reference](typescript-api/index.html) covers the TypeScript package
entry point. For full language API signatures, see
[Rust on docs.rs](https://docs.rs/semq/latest/semq/), and for Go run
`go doc -all github.com/The-SEMQ-Group/semq/bindings/go`.
Use matching SDK versions across bindings.

## Next steps

- [Run the quickstart](../quickstart.md).
- [Choose an operator and configuration](../guides/choosing-a-config.md).
- [Check compatibility guarantees](../compatibility.md).
