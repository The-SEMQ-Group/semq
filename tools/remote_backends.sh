#!/usr/bin/env bash
# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
#
# Runs on the AVX-512 check instance, from the bundle tools/avx512_check.py
# uploads: installs the wheel in a fresh environment and runs the
# conformance vectors under every SIMD backend the CPU has, requiring the
# ones in EXPECT. Writes exit_code next to the log; the caller uploads both.
set -uo pipefail

BUNDLE="$(cd "$(dirname "$0")/.." && pwd)"
EXPECT="${EXPECT:-scalar,avx2,avx512}"
cd "$BUNDLE"
python3 -m venv venv
venv/bin/python -m pip install --quiet --upgrade pip
venv/bin/python -m pip install --quiet ./*.whl pytest
venv/bin/python -c "import semq, sys; print('semq', semq.__version__, semq.__file__, 'python', sys.version.split()[0])"
venv/bin/python tools/backends.py --run --expect "$EXPECT"
echo $? > exit_code
