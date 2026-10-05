# Go errors

Six exported types implement `error`; match them with `errors.As`. Fields
that do not apply are `nil` pointers.

| Type | Fields |
| --- | --- |
| `*InvalidInputError` | `Row, Field *uint64; Message string` |
| `*IncompatibleError` | `Field *uint64; Message string` |
| `*FormatError` | `Row, Section *uint64; Message string` |
| `*IntegrityError` | `Which string` (`"content"` or `"state"`); `Message` |
| `*UnsupportedError` | `Operation, Message string` |
| `*NativeError` | `Operation string; Status int; Row, Field *uint64; Message, SDKVersion, CoreVersion, BuildID string` |

Allocation failure is reported as an error that wraps `ErrNoMemory`, so
`errors.Is(err, semq.ErrNoMemory)` matches it. Methods on a closed handle
return `*InvalidInputError`; accessors without an error result panic, like a
slice index out of range.

<!-- docs-test: skip -->
```go
var invalid *semq.InvalidInputError
if errors.As(err, &invalid) && invalid.Row != nil {
    fmt.Printf("row %d is not encodable: %s\n", *invalid.Row, invalid.Message)
}
```

## Next steps

- [Return to the Go API](go.md).
