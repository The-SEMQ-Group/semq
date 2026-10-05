---
search:
  boost: 1.25
---

# Python API

The root exports fifteen names: `Operator`, `CodecConfig`, `Codec`,
`Encoding`, `Diff`, `Floor`, `BuildInfo`, `build_info`, the six errors and
`__version__`. Start with the [quickstart](../quickstart.md) for a complete
program.

## Conventions

- `Codec.encode` takes the vectors first and the rest by name: `encode(vectors, ids=..., manifest=None, id_kind=None)`.
  `vectors` must be a float32 array of shape `[n, dim]` (float64 is rejected,
  a non-contiguous view is copied); `ids` a sequence of ints (`u64`) or strs
  (`utf8`); `id_kind` is required when `n = 0`.
- `Encoding.rows` and `get(id)` are read-only zero-copy views that keep the
  native memory alive; `ids` is a read-only uint64 view for `u64` and a tuple
  of str for `utf8`. Iteration yields `(id, row)` in canonical order.
- `save(target)` takes a path (written atomically) or a binary stream;
  atomic replacement does not promise durability of the directory entry
  after a system crash. Partial stream writes are completed; a stream that
  cannot advance raises `BlockingIOError`.
  `Encoding.load(source)` takes a path, a binary stream or bytes.
- Errors are the six classes below; out of memory raises `MemoryError` and
  file I/O raises `OSError`. Objects are released by the garbage collector.
- Native calls release the GIL.
- `str()` of an `Encoding`, a `Diff` or a `Floor` is a one-line summary, the same text in every binding; `repr()` is the debugging form.

::: semq.Operator
    options:
      heading_level: 2
      show_root_full_path: false

::: semq.CodecConfig
    options:
      show_if_no_docstring: true
      heading_level: 2
      show_root_full_path: false

::: semq.Codec
    options:
      show_if_no_docstring: true
      heading_level: 2
      show_root_full_path: false

::: semq.Encoding
    options:
      show_if_no_docstring: true
      heading_level: 2
      show_root_full_path: false

::: semq.Diff
    options:
      show_if_no_docstring: true
      heading_level: 2
      show_root_full_path: false

::: semq.Floor
    options:
      show_if_no_docstring: true
      heading_level: 2
      show_root_full_path: false

::: semq.BuildInfo
    options:
      show_if_no_docstring: true
      heading_level: 2
      show_root_full_path: false

::: semq.build_info
    options:
      heading_level: 2
      show_root_full_path: false

## Next steps

- [Handle errors](python-errors.md).
- [Use the command line](cli.md).
