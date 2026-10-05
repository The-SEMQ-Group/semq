# Rust errors

`Error` is an enum with exactly six variants; `Result<T>` aliases
`std::result::Result<T, Error>`.

| Variant | Fields |
| --- | --- |
| `InvalidInput` | `row: Option<u64>`, `field: Option<u64>`, `message` |
| `Incompatible` | `field: Option<u64>`, `message` |
| `FormatError` | `row: Option<u64>`, `section: Option<u64>`, `message` |
| `IntegrityError` | `which: Option<Which>` (`Which::Content` or `Which::State`), `message` |
| `Unsupported` | `operation`, `message` |
| `Native` | `operation`, `status`, `row`, `field`, `message`, `sdk_version`, `core_version`, `build_id` |

Out of memory in the core is `Native` with status `6`. `Encoding::read` and
`Encoding::write` return `io::Result`; a malformed image is an `io::Error`
of kind `InvalidData` whose source is the typed `Error`. `From<Error> for
io::Error` is implemented for callers that mix both.

<!-- docs-test: skip -->
```rust,ignore
match codec.encode(ids, &vectors, None) {
    Err(semq::Error::InvalidInput { row: Some(row), .. }) => eprintln!("row {row} is not encodable"),
    Err(e) => return Err(e.into()),
    Ok(state) => { /* ... */ }
}
```

## Next steps

- [Return to the Rust API](rust.md).
