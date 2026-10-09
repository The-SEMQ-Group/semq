---
description: Understand SDK versions, the file format version, the rule revision, and how to migrate states.
---

# Compatibility and migration

**Goal:** upgrade a binding or exchange `.semq` files without losing the
ability to reproduce identities and verdicts.

## What is versioned

| Surface | Compatibility scope |
| --- | --- |
| Public C ABI and the root exports of each binding | The project's SemVer policy covers `include/semq.h` and the root exports of every binding: the five types, the build information and the six errors, in each host's idiom. |
| `.semq` file format | Version `2`, written into every file. Readers reject other versions. |
| Operator rules | The rule revision `p2` inside every config, currently `0`. A change to a symbol mapping increments it; states with different revisions are incompatible. |
| Floor JSON | Version `semq-floor/1`, written into every floor. Added keys are optional and ignored by readers that do not know them; the version changes only when the meaning of a key changes. See the [floor schema](reference/contracts.md#floor-schema). |
| Conformance vectors | Every byte and verdict pinned under `tests/conformance/`; a change requires a version or revision bump in the same change. |

CI enforces the first row: every pull request's C ABI and binding APIs are
compared with its base branch, and a removal or incompatible change fails
unless it is marked for the next major version.

The four packages share one version per release. A version does not identify
a build, though: a source build of the same version can use another compiler.
`build_info()` reports the core version and a build id in every binding.

## Supported platforms

| Platform | Architectures | Python | Rust, Go | TypeScript |
| --- | --- | --- | --- | --- |
| Linux with glibc 2.17 or newer | x86_64, arm64 | Wheel | Built from source | WebAssembly |
| macOS 11 or newer | arm64 | Wheel | Built from source | WebAssembly |
| Windows 10 or newer | x86_64 | Wheel | Built from source | WebAssembly |
| Browsers | Any | — | — | WebAssembly, through a bundler that serves the module |

CI tests every binding on Ubuntu 24.04 (x86_64 and arm64), macOS 26 (arm64)
and Windows Server 2025 (x86_64), and every published package against the
[conformance vectors](https://github.com/The-SEMQ-Group/semq/tree/main/tests/conformance)
before release. Rust and Go compile the core from source and need a C
compiler; Rust also needs CMake 3.20 or newer.

The native core picks its kernels at runtime: AVX2 or AVX-512 on x86_64, NEON
or SVE on arm64, and a scalar kernel otherwise. WebAssembly runs the scalar
kernel. Every kernel produces the same bytes.

Before it creates a codec, the core encodes a few fixed rows with the kernel
it selected and hashes a fixed message, and compares the bytes with known
answers. This covers builds CI never sees, such as a Rust or Go build made
with your compiler. If a check fails, creating the codec fails with the
binding's native error (`Native` in Python and TypeScript, `Error::Native` in
Rust, `*NativeError` in Go), and no bytes are produced. Report it with the
build information the error carries.

macOS on Intel, Windows on ARM, Linux distributions based on musl such as
Alpine, and 32-bit or big-endian systems are not supported. The core may build
there from source, but it is not tested.

## Supported language versions

| Binding | Minimum | Tested in CI |
| --- | --- | --- |
| Python | 3.11 | 3.11 with numpy 1.24 and cffi 1.16, and 3.14 |
| Rust | 1.77 | 1.77 and 1.99 |
| Go | 1.21, with cgo and a C11 compiler | 1.21 and 1.27 |
| Node.js | 22 | 22 and 26 |

The Python package requires numpy 1.24 or newer and cffi 1.16 or newer; CI
tests those lowest versions on Python 3.11. One Python wheel per platform
serves every Python 3 from the minimum on, including releases after it.

## Support policy

- **SDK releases.** Fixes, including security fixes, ship in a new release of
  the latest minor version of the current major version. Upgrading within a
  major version is compatible, so that is the supported path.
- **Language versions.** A minimum rises only in a minor release, announced in
  the changelog. Python and Node.js versions stay supported until their
  upstream end of life: Python 3.11 until October 2027, Node.js 22 until
  April 2027. Rust and Go minimums rise only when a dependency or a language
  feature requires it.
- **Platforms.** A platform leaves the table above only in a minor release,
  announced in the changelog.

## 1. Record the producer

For each state, record the embedding model and revision in the manifest
(`encoder`, `encoder_revision`) and keep the config in the file, where the
core writes it. For a source installation, keep the Git revision together
with dependency lockfiles and toolchain versions; `semq version --json`
prints the loaded core's build identity.

## 2. Preserve a working baseline

Keep the original inputs, the `.semq` files, and the environment that
produced them. Pin the package version in each language and record the core
build identity reported by its binding. In Python, `semq version --json`
prints it. A package version alone does not identify the exact core build.

## 3. Check identities before promotion

Encode the same float32 inputs and ids under the same config in the old and
new environments and compare `state_id`. The
[conformance vectors](https://github.com/The-SEMQ-Group/semq/tree/main/tests/conformance)
do this for representative configurations in every binding; run your own
inputs the same way. Identity equality does not establish suitability for a
new embedding model; evaluate quality separately.

## 4. Handle an intentional change

Changing dimension, embedding model, operator or parameter changes every
row. Regenerate the vectors from your source data and re-encode; a diff
between the old and the new state reports what moved, and a floor measured
from null rebuilds of the new configuration gates later rebuilds.

## Next steps

- [Choose a configuration](guides/choosing-a-config.md).
- [Gate a rebuild](guides/gate-a-rebuild.md).
