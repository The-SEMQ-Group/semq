# Python errors

Six classes cover every failure. Each core status maps to exactly one of
them; they share the base `semq.errors.SemqError` for callers who want one
`except`. Out of memory raises `MemoryError`; file I/O raises `OSError`.

| Error | Raised when | Payload |
| --- | --- | --- |
| `InvalidInput` | dtype, shape, non-finite or non-unit rows, duplicate or mixed ids, non-canonical rows, config out of range, invalid manifest or floor, invalid null diff | `row`, `field` |
| `Incompatible` | `decode`, `unpack`, `diff` or `concat` across different configs or id kinds | `field` (part index for `concat`) |
| `FormatError` | a file image is not a valid version 2 image | `section`, `row` |
| `IntegrityError` | a file's digest does not match its footer | `which` (`"content"` or `"state"`) |
| `Unsupported` | the floating-point rounding mode is not round-to-nearest | `operation` |
| `Native` | a defect in the core or binding, or the library could not be loaded | `operation`, `status`, `row`, `field`, `sdk_version`, `core_version`, `build_id` |

::: semq.errors.InvalidInput
    options:
      heading_level: 3
      show_root_full_path: false

::: semq.errors.Incompatible
    options:
      heading_level: 3
      show_root_full_path: false

::: semq.errors.FormatError
    options:
      heading_level: 3
      show_root_full_path: false

::: semq.errors.IntegrityError
    options:
      heading_level: 3
      show_root_full_path: false

::: semq.errors.Unsupported
    options:
      heading_level: 3
      show_root_full_path: false

::: semq.errors.Native
    options:
      heading_level: 3
      show_root_full_path: false

## Reproducing a native failure

Include the exception's complete message, `semq version` output, OS and CPU
architecture, and the affected codec's `backend` and
`codec.config.to_bytes().hex()`. `build_info().as_dict()` identifies both the
Python package and the core actually loaded; the codec's backend identifies
the selected implementation for that operation.

For a byte discrepancy, attach a minimal input saved with
`numpy.save(path, vectors, allow_pickle=False)` rather than rounded decimal
text. Include IDs, their kind, manifest, expected and actual `.semq` files,
and how the process's FP rounding mode was set before codec construction and
encoding. Preserve the original float32 bits. A build ID is diagnostic
identity, not proof of provenance.

## Next steps

- [Return to the Python API](python.md).
