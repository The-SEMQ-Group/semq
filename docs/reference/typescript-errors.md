# TypeScript errors

Six classes extend `Error`. Each core status maps to exactly one of them.

| Class | Fields |
| --- | --- |
| `InvalidInput` | `row?`, `field?` |
| `Incompatible` | `field?` |
| `FormatError` | `row?`, `section?` (0 framing, 1 config, 2 sizes, 3 ids, 4 manifest, 5 footer, 6 rows) |
| `IntegrityError` | `which?` (`"content"` or `"state"`) |
| `Unsupported` | `operation?` |
| `Native` | `operation?`, `status?`, `row?`, `field?`, `sdkVersion`, `coreVersion`, `buildId` |

Out of memory throws a `RangeError`. Calling the synchronous surface before
the runtime is loaded throws `Native` with `operation: "load"`.

<!-- docs-test: skip -->
```ts
try {
  codec.encode({ ids, vectors });
} catch (e) {
  if (e instanceof InvalidInput && e.row !== undefined) {
    console.error(`row ${e.row} is not encodable: ${e.message}`);
  }
}
```

## Next steps

- [Return to the TypeScript API](typescript.md).
