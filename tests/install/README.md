# Artifact consumers

Build the SDK's publication payloads, then execute only those payloads on a
host without the checkout. Python 3.11+ is required for the packaging tools;
the binding's runtime minimum stays 3.10.

```sh
npm ci --prefix bindings/ts
npm run build --prefix bindings/ts
python -m pip install build
python tools/package_artifacts.py /tmp/semq-artifacts
python /tmp/semq-artifacts/run_artifacts.py /tmp/semq-consumers
```

Both output directories must be empty. The first command uses the normal
wheel/sdist, Cargo workspace packaging, Go module ZIP and npm pack formats.
The native source copy in `semq-sys` is generated from `include/`, `src/` and
the root CMake project at packaging time; it is not a second maintained core.
`SOURCE_REVISION` keeps the build identity meaningful outside git.

The four consumers exercise all operators and both ID kinds through encode,
save/load, diff and floor. The runner compares all six resulting file images
byte for byte. Python also executes the installed CLI with passing and failing
floors. Checksums in `artifacts.json` ensure the tested payloads are unchanged.

The `external-consumers` CI job has **no checkout step**, no previously built
core and no reused native build directory. Rust builds the C sources inside
the `.crate`; Go downloads the ZIP from a file proxy and compiles the core
copy inside it with cgo; Python installs a wheel in a fresh venv; npm installs its
tarball and typechecks a strict TypeScript consumer against emitted declarations.
Python also builds and runs the source distribution in a second fresh venv.
Registry dependencies such as NumPy and the Rust CMake helper still require
network access. This test does not publish packages or claim registry access.

Rust/npm still use the pre-release package versions. The test resolves the
unpublished Rust pair from extracted archives, not from local source crates.
Go's module version is taken from the root `VERSION` for the local proxy.
The external CI host is Linux x86-64; native in-tree tests separately cover
Linux ARM64, macOS and Windows. A local macOS artifact run covers arm64.

The older editable-install test is separate:

```sh
pytest -m install tests/install/test_editable_install.py
```

It proves development installation, not external distribution. See also the
[installation guide](../../docs/installation.md).
