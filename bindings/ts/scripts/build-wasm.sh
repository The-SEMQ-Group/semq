#!/usr/bin/env bash
# Build the SEMQ WebAssembly module (scalar backend) and stage it into the TS
# package. Requires the Emscripten toolchain (emcmake / emcc) on PATH.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ts_dir="$(dirname "$here")"
repo_root="$(cd "$ts_dir/../.." && pwd)"
build_dir="$repo_root/build-wasm"

emcmake cmake -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DSEMQ_BUILD_TESTS=OFF \
  -DSEMQ_BUILD_ABI_PROBE=ON \
  -DSEMQ_BUILD_BENCHMARKS=OFF \
  -DCMAKE_DISABLE_FIND_PACKAGE_OpenMP=ON \
  -B "$build_dir" \
  -S "$repo_root"
cmake --build "$build_dir" --target semq_wasm semq_abi

mkdir -p "$ts_dir/src/wasm"
cp "$build_dir/semq.mjs" "$ts_dir/src/wasm/semq.mjs"
cp "$build_dir/semq.wasm" "$ts_dir/src/wasm/semq.wasm"
echo "staged semq.mjs + semq.wasm into src/wasm/"

python3 "$repo_root/tools/check_abi.py" --wasm-probe "$build_dir/semq_abi.js"
