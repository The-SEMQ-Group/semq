# Installation

Install the binding for your language, then run the [quickstart](quickstart.md).
The [supported platforms and language versions](compatibility.md#supported-platforms)
are listed with the compatibility policy.

=== "Python"

    Python 3.11 or newer:

    ```sh
    python -m pip install semq
    ```

    The wheel includes the C core and provides the `semq` CLI. No C compiler
    is needed when a wheel is available for your platform.

    Save the Python example from the [quickstart](quickstart.md) as
    `quickstart.py`, then run `python quickstart.py`.

=== "Rust"

    Rust 1.77 or newer, a C compiler, and CMake 3.20 or newer:

    ```sh
    cargo new semq-quickstart
    cd semq-quickstart
    cargo add semq
    ```

    The single `semq` crate builds and links its bundled C core. Applications
    do not need a separate `semq-sys` dependency or a runtime library path.
    Save the Rust example from the [quickstart](quickstart.md) as
    `src/main.rs`, then run `cargo run`.

=== "Go"

    Go 1.21 or newer with cgo, and a C compiler (GCC or Clang; MinGW-w64 GCC
    on Windows):

    ```sh
    mkdir semq-quickstart
    cd semq-quickstart
    go mod init example.com/semq-quickstart
    go get github.com/The-SEMQ-Group/semq/bindings/go@v1.0.0
    ```

    The module includes the C core, and cgo compiles and links it statically
    on the first build. No native library or environment variables are
    needed. Save the Go example from the [quickstart](quickstart.md) as
    `main.go`, then run `go run .`.

=== "TypeScript / JavaScript"

    Node.js 22 or newer, or a browser build with a bundler that serves WASM:

    ```sh
    mkdir semq-quickstart
    cd semq-quickstart
    npm init -y
    npm pkg set type=module
    npm install @semq/sdk
    npm install --save-dev typescript @types/node
    ```

    The package includes the WASM module and TypeScript declarations. It
    needs no C compiler or Emscripten on the consumer's machine. In a browser,
    configure your bundler to serve the WASM asset.
    Save the TypeScript example from the [quickstart](quickstart.md) as
    `quickstart.ts`, then run:

    ```sh
    npx tsc quickstart.ts --target ES2022 --module NodeNext --moduleResolution NodeNext --strict --skipLibCheck
    node quickstart.js
    ```

## Verify the installation

Run your language's [quickstart](quickstart.md). Its first program prints
`1 of 3 rows changed: doc-3 (hamming 3)`, and its second ends with `true` for
a noisy rebuild and `false` for an edited row, checking native loading,
encoding, persistence, diff and the floor together.

To work on the SDK itself, or to build a binding from a source checkout, see
[Contributing](https://github.com/The-SEMQ-Group/semq/blob/main/CONTRIBUTING.md)
and the README of each binding.

## Next steps

- [Quickstart](quickstart.md): encode your first vectors.
- [API reference](reference/index.md): explore your binding.
- [Compatibility and migration](compatibility.md): file formats and SDK upgrades.
