# Mechanical ABI checks

`tools/check_abi.py` extracts functions and POD declarations from `semq.h` and
checks the cffi, Rust and TypeScript mirrors and the Emscripten export list.
Go consumes the header directly through cgo and has no declaration mirror.

The generated `layout.c` runs on the target C compiler. With `--probe
build/semq_abi --rust`, its sizes, alignments, offsets and constants are compared
with cffi and a compiled Rust probe. All four native CI platforms run this gate.
The wasm build runs the same C probe under Node and checks `src/layout.ts`, which
the TypeScript memory adapters use. This covers pointer width independently of
the build host. Negative unit tests deliberately break mirrors and require the
gate to reject them.

After an intentional header change, regenerate the **probe source** with
`python tools/check_abi.py --write-probe`, compile it, and regenerate the wasm
layout with `--wasm-probe build-wasm/semq_abi.js --write-layout`. Regular builds
only check these files; they never silently accept drift.
