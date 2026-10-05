# semq

Rust bindings to the SEMQ core: deterministic symbolic encoding of float32
vectors into states with content-addressed identities. The C core owns every
rule that determines bytes or verdicts; this crate wraps it in safe Rust types.

## Install

Rust 1.77 or newer, a C compiler, and CMake 3.20 or newer:

```sh
cargo add semq
```

The crate builds and links its bundled C core through `semq-sys`. No runtime
library path is needed.

## Use

The [crate documentation](https://docs.rs/semq) starts with a quickstart that
encodes vectors, writes and reads a state, and diffs it against a rebuild. The
[SEMQ documentation](https://github.com/The-SEMQ-Group/semq/blob/main/docs/index.md)
covers the concepts, the other bindings and the file format.

## License

PolyForm Noncommercial License 1.0.0. Production use by companies, and any
other use the license does not permit, requires a separate license from
The SEMQ Group Inc.; write to licensing@thesemqgroup.ai.
