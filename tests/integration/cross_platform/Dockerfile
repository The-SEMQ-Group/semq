# SEMQ SDK cross-platform test image.
#
# Build (use build_images.py for the staged context):
#   python tests/integration/cross_platform/build_images.py
#
# Run scenarios from the host runners:
#   python tests/integration/cross_platform/run_jitter.py
#   python tests/integration/cross_platform/run_property_tests.py

FROM python:3.13-slim

# Build prerequisites for the C library.
RUN apt-get update && apt-get install -y --no-install-recommends \
        cmake \
        ninja-build \
        gcc \
        g++ \
        make \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the C library sources and build it.
COPY CMakeLists.txt /app/CMakeLists.txt
COPY include        /app/include
COPY src            /app/src

RUN cmake -G Ninja -DCMAKE_BUILD_TYPE=Release -DSEMQ_BUILD_TESTS=OFF \
        -B /app/build \
 && cmake --build /app/build

# Copy the Python binding source (no install — we run via PYTHONPATH).
COPY bindings /app/bindings

# Pin Python deps to match the host venv exactly. The only variable
# across containers must be the CPU architecture.
RUN pip install --no-cache-dir --quiet \
        "numpy==2.1.3" \
        "cffi" \
        "pytest>=8" \
        "hypothesis>=6"

# Cross-platform scripts (jitter counterfactual, dispatch diagnostic).
COPY tests/integration/cross_platform /app/cross_platform

# Property tests — `test_cross_backend.py` exercises every linked SIMD
# backend through SEMQ_FORCE_BACKEND. Running this inside `linux/amd64`
# is the only way to validate the AVX2 path from a macOS-arm64 host.
COPY tests/property /app/tests/property
RUN touch /app/tests/__init__.py /app/tests/property/__init__.py

ENV PYTHONPATH=/app/bindings/python
ENV SEMQ_LIB_DIR=/app/build

# No default CMD — runners pick the scenario to execute via
# `docker run ... tag <python script ...>`.
