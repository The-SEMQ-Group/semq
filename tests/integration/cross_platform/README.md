# Docker architecture checks

This directory runs diagnostics and property tests on `linux/arm64` and
`linux/amd64` images. It complements the shared
[conformance vectors](../../conformance/README.md); it does not extend SEMQ's byte-identity
contract to different floating-point inputs.

## Runners

| Script | Purpose and interpretation |
| --- | --- |
| [build_images.py](build_images.py) | Stage the needed source files and build `semq:arm64` and `semq:amd64`. |
| [run_property_tests.py](run_property_tests.py) | Run the [cross-backend property suite](../../property/test_cross_backend.py) in each image; a failing architecture produces a nonzero runner exit. |
| [run_jitter.py](run_jitter.py) | Print per-stage hashes for a NumPy computation and subsequent CANON encoding across selected hosts. This is an exploratory comparison, not an assertion of cross-architecture equality. |
| [diag_avx2_vs_scalar.py](diag_avx2_vs_scalar.py) | Compare scalar and AVX2 encoding for a diagnostic vector in the amd64 image; inspect its JSON backend names and differences. |

## Prerequisites

Use a supported host Python and a running Docker daemon with both target
architectures available through native execution or emulation. Image creation
downloads a Python base image and build/test dependencies. Emulated builds can
be substantially slower than native builds.

The [Dockerfile](Dockerfile) builds the native library inside each image and
uses Python 3.13 with its declared NumPy/test dependencies. No host native build
is needed for container-only runs.

## Build and run

From the repository root:

```sh
python tests/integration/cross_platform/build_images.py
python tests/integration/cross_platform/run_property_tests.py
python tests/integration/cross_platform/run_jitter.py --platforms arm64 amd64
```

`build_images.py` and `run_property_tests.py` accept `--platforms arm64` or
`--platforms amd64` to select one architecture. The jitter runner also accepts
`host`; its default is `host arm64 amd64`.

For the standalone AVX2 diagnostic:

```sh
docker run --rm --platform linux/amd64 semq:amd64 \
  python /app/cross_platform/diag_avx2_vs_scalar.py
```

### Include the host in the jitter comparison

Install the Python SDK's dependencies locally and build a host library:

```sh
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DSEMQ_BUILD_TESTS=OFF -DSEMQ_BUILD_BENCHMARKS=OFF \
  -DSEMQ_ENABLE_SANITIZERS=OFF
cmake --build build
python tests/integration/cross_platform/run_jitter.py
```

The host runner defaults `PYTHONPATH` to `bindings/python`, `SEMQ_LIB_DIR` to
`build`, and `SEMQ_FORCE_BACKEND` to `scalar`, preserving values already set in
the host environment. Align host package versions with the image if architecture
is intended to be the only experimental variable.

## Interpret the results

A successful property run prints a pass for each architecture. The property
suite exercises available native backends and skips hardware-dependent paths
when unavailable. Inspect skips and backend names; a container cannot provide
CPU features its execution environment lacks.

The jitter report compares `A_random`, `B_random`, `C_gemm`,
`row_norms_reduction`, `D_normalized`, and `SEMQ_codes`. Depending on libraries
and hardware, all stages may match. If upstream FP32 values differ, their
quantized codes may match when the changes stay within bins, or differ when a
boundary is crossed. This observation is separate from the guarantee for the
**same** input bytes and configuration.

`run_jitter.py` returns zero after reporting comparisons, including comparisons
with differing code hashes. Do not use its exit code as an invariance gate;
use the property tests and shared fixtures for assertions.

## Backend selection

Container runners use native dispatch by default. The host jitter subprocess
defaults to scalar. Setting an environment variable on the host does not
forward it through the runners' `docker run` commands. To request a backend
inside an image, invoke Docker explicitly:

```sh
docker run --rm --platform linux/amd64 -e SEMQ_FORCE_BACKEND=scalar semq:amd64 \
  python /app/cross_platform/numpy_jitter_test.py
```

Recognized requests are `scalar`, `neon`, `avx2`, `avx512`, and `sve`.
A requested backend must be built and supported by the CPU; inspect the active
backend rather than assuming that an environment value selected it.

## Related documentation

- [SIMD stress checks](../../scale/README.md).
- [CI workflow](../../../.github/workflows/test.yml).
