# Contributing to SEMQ

The SDK is licensed under the
[PolyForm Noncommercial License 1.0.0](LICENSE.md). Contributions require a
signed [Contributor License Agreement](#sign-the-contributor-license-agreement).
Follow the [Code of Conduct](CODE_OF_CONDUCT.md), and report vulnerabilities
through the [security policy](SECURITY.md).

For documentation changes, use [Contributing to documentation](docs/contributing.md).
This guide covers SDK development and repository maintenance.

## Set up a development checkout

Use a C11/C++17 toolchain, CMake 3.20+, Ninja, and Python 3.11+. On Windows,
configure the native compiler environment before building. The
[installation guide](docs/installation.md) covers binding-specific requirements.

Create and activate a Python virtual environment, then install the developer
dependencies from the repository root:

```sh
python -m pip install -e ".[dev]"
```

Build the C library and its tests:

```sh
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Debug \
  -DSEMQ_BUILD_TESTS=ON -DSEMQ_ENABLE_SANITIZERS=ON
cmake --build build
ctest --test-dir build --output-on-failure
```

The sanitizer option enables ASan/UBSan on supported compilers. It has no effect
on MSVC. Rebuild the editable SDK after native source changes.

The Google Benchmark suite in `tests/bench/` is off by default. Build it in
Release with `-DSEMQ_BUILD_BENCHMARKS=ON -DSEMQ_ENABLE_SANITIZERS=OFF` and run
`build/bench_encode --benchmark_format=json`; the header of
`tests/bench/bench_encode.cpp` documents the benchmark names, the environment
variables and the sizes. CI builds and smoke-runs it on Linux.

## Run the checks relevant to your change

For Python and core changes:

```sh
python -m pytest tests/unit tests/property tests/integration tests/conformance \
  --ignore=tests/integration/cross_platform -q
python -m mypy
ruff check .
python tools/conformance.py build/semq_vectors
```

For core changes, run clang-tidy with the version CI pins in
[test.yml](.github/workflows/test.yml) and the checks in `.clang-tidy`:

```sh
cmake -B build -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
run-clang-tidy.py -p build -quiet "$PWD/src/"
```

On macOS, add `-extra-arg=-isysroot$(xcrun --show-sdk-path)` so it finds the
system headers.

The native library used by Python comes from the installed package. The CMake
test build above is separate; a passing C test does not replace reinstalling
and testing the Python binding.

| Area | Build or test instructions |
| --- | --- |
| Rust | [Rust reference](docs/reference/rust.md) and the Rust jobs in [CI](.github/workflows/test.yml) |
| Go | [Binding README](bindings/go/README.md) |
| TypeScript/WASM | [Binding README](bindings/ts/README.md) |
| FFI signatures and compiled layouts | [ABI checks](tests/abi/README.md) |
| Reader fuzzing | [Fuzz harness](tests/fuzz/README.md) |
| Resource failure cleanup | [Allocation failure tests](tests/fault/README.md) |
| Packaged artifacts outside the checkout | [External consumers](tests/install/README.md) |
| Shared bytes and verdicts | [Conformance vectors](tests/conformance/README.md) |
| Codec quality and cost benchmarks | [Benchmark suite](benchmarks/README.md) |
| Larger stress cases | [Scale tests](tests/scale/README.md) |
| SIMD diagnostics | [Cross-platform harness](tests/integration/cross_platform/README.md) |
| Published pages and Markdown checks | [Documentation contribution guide](docs/contributing.md) |

The configured [test workflow](.github/workflows/test.yml) runs C/Python and
Rust/Go matrices on Linux x86-64, Linux ARM64, macOS, and Windows, plus
TypeScript/WASM, mypy, ruff, clang-tidy, ESLint, and executable documentation examples. Linux jobs also
exercise selected Python boundary tests against a sanitized native library.
The [documentation workflow](.github/workflows/docs.yml) builds with
`mkdocs build --strict`.

## Preserve the public contracts

Read [`include/semq.h`](include/semq.h) before changing the core API. Within a
major version, preserve existing signatures, ownership rules, enum values,
and field types and offsets. Compatible new functions are allowed. The
current POD structs, including `semq_config_t`, have fixed layouts and no
`size`-based extension mechanism. Use a new API or type when extending them.

The [api-compat workflow](.github/workflows/api-compat.yml) enforces this for
every public surface: it compares the C ABI and the Python, Rust, Go and
TypeScript APIs of a pull request with its base branch, and fails on a removal
or an incompatible change. Additions pass. Run the same check locally with
`python tools/api_compat.py --base origin/main`; it skips a surface whose tool
is not installed and names it. An intended break needs the `breaking-change`
label and ships only in a new major version.

Identical inputs and configurations must retain their encoded bytes across
supported backends. An intentional change to committed fixture bytes requires
an explanation of the compatibility impact and checks in every affected
binding. Do not regenerate fixtures to hide a regression.

The Go module carries a generated copy of the core in
`bindings/go/internal/core`. After changing `include/` or `src/`, run
`python tools/gen_go_core.py` and commit the result with the change; CI fails
while the copy differs. Never edit the copy itself.

Add a regression test for a behavior change or bug fix. Document new public
symbols in the C header and affected bindings, and update the relevant guide
or reference. See [compatibility](docs/compatibility.md) for the distinction
between package versions and artifact schemas.

## Prepare a pull request

Work on a short-lived branch and target `main`. Keep the change focused, explain
the resulting behavior, and include relevant validation in the
[pull request template](.github/PULL_REQUEST_TEMPLATE.md). Update
[CHANGELOG.md](CHANGELOG.md) for user-visible SDK changes.

Use English and Conventional Commit subjects such as
`fix(python): reject mismatched batch dimensions` or
`docs: clarify the QUANT range`. Describe breaking changes explicitly.

### Sign the Contributor License Agreement

Before your first pull request can merge, sign the SEMQ Contributor License
Agreement (CLA). On your first pull request, the CLA assistant posts a
comment with a link to the agreement; sign it there with your GitHub account.
One signature covers your later pull requests unless the agreement changes.
The CLA check must pass before merge.

### Merge

CI must pass before merge. After approval, squash-merge and delete the
branch.

## Maintain the documentation

Give each page one purpose and a discoverable entry point. Keep SDK tutorials,
task guides, reference material, and explanations under `docs/`. A directory
README should explain that directory's setup, commands, or artifacts and link
to the main guides for shared concepts.

Preserve useful historical decisions and release records with their context.
Keep temporary inventories, review transcripts, implementation plans, and audit
reports in the pull request instead of adding permanent Markdown files.
Update existing pages before introducing another source for the same guidance.

## Releases

- [Release runbook](docs/RELEASING.md): packaging, publication, and verification.
