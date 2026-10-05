# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

cmake_minimum_required(VERSION 3.20)

# The core version has one origin: the VERSION file at the repository root.
# It is SemVer (X.Y.Z or X.Y.Z-rc.N); project() takes only the numeric part,
# and the core reports the full string.
file(READ "${CMAKE_CURRENT_SOURCE_DIR}/VERSION" SEMQ_VERSION)
string(STRIP "${SEMQ_VERSION}" SEMQ_VERSION)
if(NOT SEMQ_VERSION MATCHES "^([0-9]+\\.[0-9]+\\.[0-9]+)(-rc\\.[1-9][0-9]*)?$")
    message(FATAL_ERROR "VERSION must be X.Y.Z or X.Y.Z-rc.N, found '${SEMQ_VERSION}'")
endif()
set(SEMQ_VERSION_NUMBER "${CMAKE_MATCH_1}")

project(semq
    VERSION ${SEMQ_VERSION_NUMBER}
    DESCRIPTION "SEMQ SDK — deterministic symbolic encoding of float32 vectors"
    LANGUAGES C CXX
)

# ---------------------------------------------------------------------------
# Project-wide settings
# ---------------------------------------------------------------------------

set(CMAKE_C_STANDARD          11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS        OFF)

set(CMAKE_CXX_STANDARD          17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS        OFF)

set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(CMAKE_C_VISIBILITY_PRESET hidden)
set(CMAKE_VISIBILITY_INLINES_HIDDEN ON)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

option(SEMQ_BUILD_TESTS      "Build unit and integration tests"         ON)
option(SEMQ_BUILD_BENCHMARKS "Build Google Benchmark performance suite" OFF)
option(SEMQ_BUILD_FUZZ       "Build libFuzzer targets"                  OFF)
option(SEMQ_BUILD_ABI_PROBE  "Build the C compiler ABI layout probe"    OFF)
option(SEMQ_ENABLE_SANITIZERS
       "Enable AddressSanitizer + UBSan in Debug builds"                ON)

# ---------------------------------------------------------------------------
# Compiler flags
# ---------------------------------------------------------------------------

if(MSVC)
    add_compile_options(/W4 /WX /permissive- /fp:precise)
else()
    add_compile_options(-Wall -Wextra -Werror -Wshadow -Wconversion -Wpedantic)
    # The byte contract forbids fused multiply-add where the rules say two
    # roundings happen; the phase kernel spells its fma() calls out.
    add_compile_options(-ffp-contract=off)
endif()

if(EMSCRIPTEN)
    # wasm32 has a 32-bit size_t, so the core's malloc(count) calls — with
    # 64-bit counts that are bounded by the < 4 GB wasm heap — trip
    # -Wshorten-64-to-32 under -Wconversion. The narrowing is safe there (an
    # over-4 GB allocation fails first), and the native 64-bit builds still
    # enforce the full warning set, so demote just this warning for wasm.
    add_compile_options(-Wno-error=shorten-64-to-32)
endif()

if(CMAKE_BUILD_TYPE STREQUAL "Release")
    if(NOT MSVC)
        # No global -march: the SIMD kernels carry their own per-file flags and
        # the dispatcher selects them at run time, so the baseline code runs on
        # every x86-64 and ARM64 host.
        add_compile_options(-O3 -DNDEBUG)
    endif()
endif()

if(CMAKE_BUILD_TYPE STREQUAL "Debug" AND SEMQ_ENABLE_SANITIZERS AND NOT MSVC)
    add_compile_options(-fsanitize=address -fsanitize=undefined
                        -fno-omit-frame-pointer -g)
    add_link_options(-fsanitize=address -fsanitize=undefined)
endif()

# ---------------------------------------------------------------------------
# Build identity
# ---------------------------------------------------------------------------
#
# build_id names a reproducible build recipe: version, commit, compiled
# backends, toolchain and build type. It is not a provenance proof.

set(SEMQ_GIT_COMMIT "nogit")
find_package(Git QUIET)
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/SOURCE_REVISION")
    # Packaged native sources have no .git directory. Preserve their source
    # identity instead of discovering an unrelated consumer's parent repo.
    file(READ "${CMAKE_CURRENT_SOURCE_DIR}/SOURCE_REVISION" SEMQ_GIT_COMMIT)
    string(STRIP "${SEMQ_GIT_COMMIT}" SEMQ_GIT_COMMIT)
elseif(GIT_FOUND)
    execute_process(
        COMMAND ${GIT_EXECUTABLE} rev-parse --short=12 HEAD
        WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
        OUTPUT_VARIABLE SEMQ_GIT_COMMIT_OUT
        OUTPUT_STRIP_TRAILING_WHITESPACE
        ERROR_QUIET
        RESULT_VARIABLE SEMQ_GIT_RESULT)
    if(SEMQ_GIT_RESULT EQUAL 0 AND NOT "${SEMQ_GIT_COMMIT_OUT}" STREQUAL "")
        set(SEMQ_GIT_COMMIT "${SEMQ_GIT_COMMIT_OUT}")
    endif()
endif()
if(CMAKE_SYSTEM_PROCESSOR MATCHES "arm64|aarch64")
    set(SEMQ_BACKENDS "scalar+neon+sve")
elseif(CMAKE_SYSTEM_PROCESSOR MATCHES "x86_64|AMD64")
    set(SEMQ_BACKENDS "scalar+avx2+avx512")
else()
    set(SEMQ_BACKENDS "scalar")
endif()
set(SEMQ_BUILD_ID
    "${SEMQ_VERSION}+${SEMQ_GIT_COMMIT}.${SEMQ_BACKENDS}.${CMAKE_C_COMPILER_ID}-${CMAKE_C_COMPILER_VERSION}.${CMAKE_SYSTEM_NAME}-${CMAKE_SYSTEM_PROCESSOR}.${CMAKE_BUILD_TYPE}")
configure_file(src/semq_build.h.in "${CMAKE_CURRENT_BINARY_DIR}/generated/semq_build.h" @ONLY)

# ---------------------------------------------------------------------------
# semq core library
# ---------------------------------------------------------------------------

set(SEMQ_CORE_SOURCES
    src/semq_build.c
    src/semq_alloc.c
    src/semq_codec.c
    src/semq_config.c
    src/semq_diff.c
    src/semq_encoding.c
    src/semq_file.c
    src/semq_floor.c
    src/semq_ids.c
    src/semq_manifest.c
    src/semq_sha256.c
    src/core/semq_dispatch.c
    src/core/semq_scalar.c
    src/core/semq_phase_scalar.c
    src/core/semq_quant_scalar.c
)

# Architecture-specific SIMD backends. Each file is gated on the host
# architecture; the dispatcher links the appropriate global at run time.

if(CMAKE_SYSTEM_PROCESSOR MATCHES "arm64|aarch64")
    list(APPEND SEMQ_CORE_SOURCES
        src/core/semq_neon.c
        src/core/semq_phase_neon.c
        src/core/semq_quant_neon.c
        src/semq_sha256_arm.c
        src/core/semq_sve.c)
    set_source_files_properties(src/core/semq_neon.c PROPERTIES
        COMPILE_OPTIONS "-march=armv8-a+simd")
    set_source_files_properties(src/core/semq_phase_neon.c PROPERTIES
        COMPILE_OPTIONS "-march=armv8-a+simd")
    set_source_files_properties(src/core/semq_quant_neon.c PROPERTIES
        COMPILE_OPTIONS "-march=armv8-a+simd")
    set_source_files_properties(src/semq_sha256_arm.c PROPERTIES
        COMPILE_OPTIONS "-march=armv8-a+crypto")
    set_source_files_properties(src/core/semq_sve.c PROPERTIES
        COMPILE_OPTIONS "-march=armv8-a+sve")
endif()

if(CMAKE_SYSTEM_PROCESSOR MATCHES "x86_64|AMD64")
    list(APPEND SEMQ_CORE_SOURCES
        src/core/semq_avx2.c
        src/core/semq_avx512.c
        src/core/semq_quant_avx2.c
        src/core/semq_quant_avx512.c)
    if(MSVC)
        # MSVC has no -mavx2/-mavx512f style per-feature flags; /arch:
        # is the closest equivalent and enables the intrinsic headers
        # this backend uses regardless of whether it also auto-defines
        # __AVX2__/__AVX512F__ (it does not need to: semq_avx2.c and
        # semq_avx512.c gate on architecture, not on those macros, and
        # semq_dispatch.c's runtime CPUID check — not the preprocessor
        # — decides which one actually runs).
        set_source_files_properties(src/core/semq_avx2.c PROPERTIES
            COMPILE_OPTIONS "/arch:AVX2")
        set_source_files_properties(src/core/semq_avx512.c PROPERTIES
            COMPILE_OPTIONS "/arch:AVX512")
        set_source_files_properties(src/core/semq_quant_avx2.c PROPERTIES
            COMPILE_OPTIONS "/arch:AVX2")
        set_source_files_properties(src/core/semq_quant_avx512.c PROPERTIES
            COMPILE_OPTIONS "/arch:AVX512")
    else()
        set_source_files_properties(src/core/semq_avx2.c PROPERTIES
            COMPILE_OPTIONS "-mavx2;-mfma")
        set_source_files_properties(src/core/semq_avx512.c PROPERTIES
            COMPILE_OPTIONS "-mavx512f;-mavx512bw;-mavx512vl")
        set_source_files_properties(src/core/semq_quant_avx2.c PROPERTIES
            COMPILE_OPTIONS "-mavx2;-mfma")
        set_source_files_properties(src/core/semq_quant_avx512.c PROPERTIES
            COMPILE_OPTIONS "-mavx512f;-mavx512bw;-mavx512vl")
    endif()
endif()

add_library(semq SHARED ${SEMQ_CORE_SOURCES})

target_include_directories(semq
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src
        ${CMAKE_CURRENT_BINARY_DIR}/generated
)

set_target_properties(semq PROPERTIES OUTPUT_NAME semq)
if(NOT DEFINED SKBUILD_PROJECT_NAME)
    # System installs get the versioned name and its symlinks. A wheel
    # stores symlinks as copies, so the Python package ships one unversioned
    # file, which cffi loads by path.
    set_target_properties(semq PROPERTIES
        VERSION   ${PROJECT_VERSION}
        SOVERSION ${PROJECT_VERSION_MAJOR}
    )
endif()

# libm is a separate link target on POSIX platforms; on Windows the
# math functions this library uses (isfinite, nearbyint, lrintf, ...)
# live in the standard C runtime and there is no "m" library to link.
if(NOT WIN32)
    target_link_libraries(semq PRIVATE m)
endif()

# Static archive variant — embedded by Rust/Go and the native tests.
add_library(semq_static STATIC ${SEMQ_CORE_SOURCES})
target_include_directories(semq_static
    PUBLIC  ${CMAKE_CURRENT_SOURCE_DIR}/include
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src
            ${CMAKE_CURRENT_BINARY_DIR}/generated
)
if(NOT WIN32)
    target_link_libraries(semq_static PRIVATE m)
endif()

if(WIN32 OR EMSCRIPTEN)
    # MSVC's static archives use the same .lib extension as a DLL's
    # auto-generated import library, and Emscripten emits a .a for the
    # shared target too. Both "semq" targets above (the shared semq
    # target's import library / archive, and this static one) would
    # otherwise try to write the same file into the output directory
    # -- confirmed on windows-latest CI: "ninja: error: multiple rules
    # generate semq.lib", and the same collision under emcc. Give the
    # static archive a distinct name there; every in-tree consumer links
    # against the CMake target name (semq_static), not this output file
    # name, so the rename is invisible to them.
    set_target_properties(semq_static PROPERTIES OUTPUT_NAME semq_static)
else()
    set_target_properties(semq_static PROPERTIES OUTPUT_NAME semq)
endif()

# Re-apply per-source SIMD compile options to the static target. CMake stores
# COMPILE_OPTIONS as a target-bound property, so the static and shared targets
# both pick them up via the SOURCE-scoped set_source_files_properties above.

# ---------------------------------------------------------------------------
# WebAssembly module (Emscripten only)
# ---------------------------------------------------------------------------
#
# Configure with `emcmake cmake ...` to select the Emscripten toolchain. The
# scalar backend compiles to wasm32 (the SIMD sources are gated on the host
# arch above and excluded here). Produces semq.mjs + a semq.wasm the
# TypeScript binding in bindings/ts loads.
if(EMSCRIPTEN)
    add_executable(semq_wasm ${SEMQ_CORE_SOURCES})
    target_include_directories(semq_wasm PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/include
        ${CMAKE_CURRENT_SOURCE_DIR}/src
        ${CMAKE_CURRENT_BINARY_DIR}/generated)
    set_target_properties(semq_wasm PROPERTIES OUTPUT_NAME semq SUFFIX ".mjs")
    target_link_options(semq_wasm PRIVATE
        "-sMODULARIZE=1"
        "-sEXPORT_ES6=1"
        "-sENVIRONMENT=node,web"
        "-sALLOW_MEMORY_GROWTH=1"
        "-sEXPORT_NAME=createSemqModule"
        "-sEXPORTED_RUNTIME_METHODS=ccall,cwrap,getValue,setValue,UTF8ToString,HEAPU8,HEAPF32,HEAPF64,HEAPU32,HEAP32"
        "-sEXPORTED_FUNCTIONS=_malloc,_free,_semq_config_orbit,_semq_config_phase,_semq_config_quant,_semq_config_validate,_semq_config_to_bytes,_semq_config_from_bytes,_semq_config_bytes_per_vector,_semq_config_units_per_row,_semq_config_max_magnitude,_semq_config_equal,_semq_codec_create,_semq_codec_free,_semq_codec_config,_semq_codec_backend,_semq_codec_encode,_semq_codec_decode,_semq_codec_unpack,_semq_encoding_create,_semq_encoding_free,_semq_encoding_config,_semq_encoding_id_kind,_semq_encoding_len,_semq_encoding_rows,_semq_encoding_ids_u64,_semq_encoding_ids_utf8_offsets,_semq_encoding_ids_utf8_bytes,_semq_encoding_manifest_len,_semq_encoding_manifest_pair,_semq_encoding_content_digest,_semq_encoding_state_id,_semq_encoding_find_u64,_semq_encoding_find_utf8,_semq_encoding_file_size,_semq_encoding_save_parts,_semq_encoding_save,_semq_encoding_load,_semq_encoding_concat,_semq_encoding_diff,_semq_diff_free,_semq_diff_config,_semq_diff_id_kind,_semq_diff_reference_id,_semq_diff_candidate_id,_semq_diff_count,_semq_diff_n_unchanged,_semq_diff_id,_semq_diff_hamming,_semq_diff_manifest_changes,_semq_diff_manifest_change,_semq_diff_units_u64,_semq_diff_units_utf8,_semq_floor_create,_semq_floor_free,_semq_floor_measure,_semq_floor_config,_semq_floor_id_kind,_semq_floor_reference_id,_semq_floor_nulls,_semq_floor_changed_rows,_semq_floor_total_rows,_semq_floor_hamming,_semq_diff_within,_semq_core_version,_semq_build_id,_semq_backend_name,_semq_status_name,_semq_sha256")
endif()

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

if(SEMQ_BUILD_TESTS OR SEMQ_BUILD_ABI_PROBE)
    add_executable(semq_abi tests/abi/layout.c)
    target_include_directories(semq_abi PRIVATE include)
endif()

if(SEMQ_BUILD_TESTS)
    enable_testing()
    include(FetchContent)

    # Unity — single-file C test framework. Permissive (MIT) license.
    FetchContent_Declare(unity
        GIT_REPOSITORY https://github.com/ThrowTheSwitch/Unity.git
        GIT_TAG        860062d51b2e8a75d150337b63ca2a472840d13c # v2.6.0
    )
    FetchContent_MakeAvailable(unity)

    # Unity's own CMakeLists.txt requests /Wall for itself on MSVC; combined
    # with our directory-wide /WX above, that promotes Unity's own
    # informational Spectre-mitigation notes (C5045) to hard build errors --
    # confirmed on windows-latest CI, and not something Unity's own upstream
    # CI hits since they don't build with /WX. A trailing /W0 does NOT undo
    # this (confirmed on CI too): MSVC tracks /Wall-enabled off-by-default
    # warnings separately from the /W0-/W4 level scale, so only an explicit
    # /wd<code> actually suppresses them regardless of /W level. C5045 is
    # the only code /Wall turns up in unity.c, so disable just that one --
    # vendored third-party code shouldn't be held to this project's bar.
    if(MSVC)
        target_compile_options(unity PRIVATE /wd5045)
    else()
        target_compile_options(unity PRIVATE -w)
    endif()

    # Fault injection never enters the production shared/static libraries.
    add_library(semq_fault STATIC ${SEMQ_CORE_SOURCES})
    target_include_directories(semq_fault PRIVATE include src tests/fault "${CMAKE_CURRENT_BINARY_DIR}/generated")
    target_compile_definitions(semq_fault PRIVATE SEMQ_TEST_ALLOCATOR)
    if(NOT WIN32)
        target_link_libraries(semq_fault PRIVATE m)
    endif()
    add_executable(test_alloc tests/fault/test_alloc.c)
    target_include_directories(test_alloc PRIVATE include tests/fault)
    target_link_libraries(test_alloc PRIVATE semq_fault)
    add_test(NAME fault.allocations COMMAND test_alloc)
    add_executable(test_self_test tests/fault/test_self_test.c)
    target_include_directories(test_self_test PRIVATE include tests/fault)
    target_link_libraries(test_self_test PRIVATE semq_fault)
    add_test(NAME fault.self_test COMMAND test_self_test)

    add_executable(fuzz_load_smoke tests/fuzz/load.c tests/fuzz/smoke.c)
    target_include_directories(fuzz_load_smoke PRIVATE include src)
    target_link_libraries(fuzz_load_smoke PRIVATE semq_static)
    file(GLOB_RECURSE SEMQ_FUZZ_SEEDS CONFIGURE_DEPENDS "tests/conformance/*.semq")
    add_test(NAME fuzz.reader_smoke COMMAND fuzz_load_smoke ${SEMQ_FUZZ_SEEDS})

    add_executable(test_core tests/unit/test_core.c)
    target_link_libraries(test_core PRIVATE semq_static unity)
    target_include_directories(test_core PRIVATE include src)
    target_compile_definitions(test_core PRIVATE UNITY_INCLUDE_DOUBLE)
    add_test(NAME unit.test_core COMMAND test_core)

    # The conformance vector generator: writes tests/conformance/NN-name/ from
    # the same sources as the library (see tests/conformance/README.md).
    add_executable(semq_vectors tests/conformance/semq_vectors.c)
    target_link_libraries(semq_vectors PRIVATE semq_static)
    target_include_directories(semq_vectors PRIVATE include src)
    if(NOT WIN32)
        target_link_libraries(semq_vectors PRIVATE m)
    endif()

    add_executable(test_dispatch_backends tests/unit/test_dispatch_backends.c)
    target_link_libraries(test_dispatch_backends PRIVATE semq_static unity)
    target_include_directories(test_dispatch_backends PRIVATE include src)
    add_test(NAME unit.test_dispatch_backends COMMAND test_dispatch_backends)

endif()

# ---------------------------------------------------------------------------
# Benchmarks
# ---------------------------------------------------------------------------

if(SEMQ_BUILD_BENCHMARKS)
    include(FetchContent)
    set(BENCHMARK_ENABLE_TESTING       OFF CACHE BOOL "" FORCE)
    set(BENCHMARK_ENABLE_INSTALL       OFF CACHE BOOL "" FORCE)
    set(BENCHMARK_ENABLE_GTEST_TESTS   OFF CACHE BOOL "" FORCE)

    FetchContent_Declare(googlebenchmark
        GIT_REPOSITORY https://github.com/google/benchmark.git
        GIT_TAG        a4cf155615c63e019ae549e31703bf367df5b471 # v1.8.4
    )
    FetchContent_MakeAvailable(googlebenchmark)

    add_executable(bench_encode tests/bench/bench_encode.cpp)
    target_link_libraries(bench_encode PRIVATE semq_static benchmark::benchmark)
    target_include_directories(bench_encode PRIVATE include)
endif()

# ---------------------------------------------------------------------------
# Install rules
# ---------------------------------------------------------------------------

if(DEFINED SKBUILD_PROJECT_NAME)
    # Wheel build via scikit-build-core. The shared library lands inside
    # the Python package directory (semq/) so the cffi binding finds it
    # at runtime without any environment variable.
    install(TARGETS semq
        LIBRARY DESTINATION semq
        RUNTIME DESTINATION semq
    )
else()
    # Plain system install (`sudo cmake --install build`) keeps the
    # traditional layout: libsemq.{so,dylib,dll} in libdir, header in
    # includedir, license in docdir.
    include(GNUInstallDirs)

    install(TARGETS semq
        LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
        ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
        RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
    )

    install(TARGETS semq_static
        ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR} COMPONENT NativeDevelopment
    )

    install(FILES include/semq.h
        DESTINATION ${CMAKE_INSTALL_INCLUDEDIR} COMPONENT NativeDevelopment
    )

    install(FILES LICENSE.md NOTICE
        DESTINATION ${CMAKE_INSTALL_DOCDIR} COMPONENT NativeDevelopment
    )
endif()

# Instrument the core itself as well as the reader harness.
if(SEMQ_BUILD_FUZZ)
    if(NOT CMAKE_C_COMPILER_ID MATCHES "Clang")
        message(FATAL_ERROR "SEMQ_BUILD_FUZZ requires a Clang libFuzzer toolchain")
    endif()
    add_executable(fuzz_load tests/fuzz/load.c ${SEMQ_CORE_SOURCES})
    target_include_directories(fuzz_load PRIVATE include src "${CMAKE_CURRENT_BINARY_DIR}/generated")
    target_compile_options(fuzz_load PRIVATE -fsanitize=fuzzer-no-link,undefined -fno-omit-frame-pointer)
    target_link_options(fuzz_load PRIVATE -fsanitize=fuzzer,undefined)
    if(SEMQ_ENABLE_SANITIZERS)
        target_compile_options(fuzz_load PRIVATE -fsanitize=address)
        target_link_options(fuzz_load PRIVATE -fsanitize=address)
    endif()
    if(NOT WIN32)
        target_link_libraries(fuzz_load PRIVATE m)
    endif()
endif()
