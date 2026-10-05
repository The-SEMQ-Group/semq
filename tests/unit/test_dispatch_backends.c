/*
 * Copyright (c) 2026 The SEMQ Group Inc.
 * Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
 */

/*
 * test_dispatch_backends.c — fixed-seed cross-backend bit-identity.
 *
 * Calls each available backend's function table directly (bypassing
 * the public API) with a deterministic input and asserts byte-for-byte
 * equality of outputs against the scalar reference.
 *
 * Runs under ctest with AddressSanitizer + UBSan enabled, so any
 * out-of-bounds read in the SIMD path or any UB in the magic-multiply
 * path will fail the test.
 */

#include "unity.h"

#include "semq.h"
#include "core/semq_dispatch.h"
#include "semq_sha256.h"

#include <stdint.h>
#include <stdlib.h>
#include <string.h>

void setUp(void)    {}
void tearDown(void) {}

/* Deterministic float fill — values bounded in the equivalence band. */
static uint32_t lcg_next(uint32_t* state) {
    *state = (*state) * 1664525u + 1013904223u;
    return *state;
}

static float lcg_float(uint32_t* state, float lo, float hi) {
    uint32_t r = lcg_next(state);
    float    u = (float)r / (float)UINT32_MAX;          /* [0, 1] */
    return lo + (hi - lo) * u;
}

static void fill_floats(float* buf, uint32_t n, uint32_t seed) {
    uint32_t s = seed;
    for (uint32_t i = 0; i < n; ++i) {
        buf[i] = lcg_float(&s, -1.0f, 1.0f);             /* well inside band */
    }
}

/* -------------------------------------------------------------------------- */
/*  encode bit-identity at boundary-exercising dimensions                     */
/* -------------------------------------------------------------------------- */

static void run_encode_compare(uint32_t dim) {
    float*       in  = (float*)      malloc((size_t)dim * sizeof(float));
    semq_code_t* out_scalar = (semq_code_t*)malloc((size_t)dim);
    semq_code_t* out_simd   = (semq_code_t*)malloc((size_t)dim);
    TEST_ASSERT_NOT_NULL(in);
    TEST_ASSERT_NOT_NULL(out_scalar);
    TEST_ASSERT_NOT_NULL(out_simd);

    fill_floats(in, dim, 0xC0FFEEu ^ dim);

    const semq_backend_t* sc  = semq_dispatch_get(SEMQ_BACKEND_SCALAR);
    TEST_ASSERT_NOT_NULL(sc);
    TEST_ASSERT_EQUAL_INT(SEMQ_OK,
        sc->encode(in, dim, 50u, out_scalar));

#if defined(__aarch64__) || defined(_M_ARM64)
    const semq_backend_t* nb = semq_dispatch_get(SEMQ_BACKEND_NEON);
    TEST_ASSERT_NOT_NULL(nb);
    TEST_ASSERT_TRUE(nb != sc);  /* NEON is a distinct backend on ARM64 */
    TEST_ASSERT_EQUAL_INT(SEMQ_OK,
        nb->encode(in, dim, 50u, out_simd));
    TEST_ASSERT_EQUAL_UINT8_ARRAY(out_scalar, out_simd, dim);

    /* SVE: only run if dispatch_get actually resolves to a non-scalar
     * backend (i.e. the host CPU advertises FEAT_SVE). On Apple Silicon
     * dispatch_get(SVE) returns the scalar table — skip the comparison. */
    const semq_backend_t* vb = semq_dispatch_get(SEMQ_BACKEND_SVE);
    if (vb != sc) {
        TEST_ASSERT_EQUAL_INT(SEMQ_OK,
            vb->encode(in, dim, 50u, out_simd));
        TEST_ASSERT_EQUAL_UINT8_ARRAY(out_scalar, out_simd, dim);
    }
#endif

#if defined(__x86_64__) || defined(_M_X64)
    const semq_backend_t* ab = semq_dispatch_get(SEMQ_BACKEND_AVX2);
    if (ab != sc) {
        TEST_ASSERT_EQUAL_INT(SEMQ_OK,
            ab->encode(in, dim, 50u, out_simd));
        TEST_ASSERT_EQUAL_UINT8_ARRAY(out_scalar, out_simd, dim);
    }
    const semq_backend_t* zb = semq_dispatch_get(SEMQ_BACKEND_AVX512);
    if (zb != sc) {
        TEST_ASSERT_EQUAL_INT(SEMQ_OK,
            zb->encode(in, dim, 50u, out_simd));
        TEST_ASSERT_EQUAL_UINT8_ARRAY(out_scalar, out_simd, dim);
    }
#endif

    free(in);
    free(out_scalar);
    free(out_simd);
}

static void test_dispatch_backends_bit_identical_dim_1(void)    { run_encode_compare(1u); }
static void test_dispatch_backends_bit_identical_dim_15(void)   { run_encode_compare(15u); }
static void test_dispatch_backends_bit_identical_dim_16(void)   { run_encode_compare(16u); }
static void test_dispatch_backends_bit_identical_dim_17(void)   { run_encode_compare(17u); }
static void test_dispatch_backends_bit_identical_dim_31(void)   { run_encode_compare(31u); }
static void test_dispatch_backends_bit_identical_dim_32(void)   { run_encode_compare(32u); }
static void test_dispatch_backends_bit_identical_dim_33(void)   { run_encode_compare(33u); }
static void test_dispatch_backends_bit_identical_dim_63(void)   { run_encode_compare(63u); }
static void test_dispatch_backends_bit_identical_dim_64(void)   { run_encode_compare(64u); }
static void test_dispatch_backends_bit_identical_dim_65(void)   { run_encode_compare(65u); }
static void test_dispatch_backends_bit_identical_dim_127(void)  { run_encode_compare(127u); }
static void test_dispatch_backends_bit_identical_dim_768(void)  { run_encode_compare(768u); }
static void test_dispatch_backends_bit_identical_dim_1025(void) { run_encode_compare(1025u); }
static void test_dispatch_backends_bit_identical_dim_3072(void) { run_encode_compare(3072u); }

static void test_quant_auto_dispatch_prefers_avx2_on_avx512_host(void) {
#if defined(__x86_64__) || defined(_M_X64)
    const char* forced = getenv("SEMQ_FORCE_BACKEND");
    if (forced != NULL && *forced != '\0') TEST_IGNORE_MESSAGE("backend forced by caller");
    if (semq_dispatch_select() != SEMQ_BACKEND_AVX512)
        TEST_IGNORE_MESSAGE("AVX-512 is unavailable on this host");
    if (semq_dispatch_get_quant(SEMQ_BACKEND_AVX2) == &SEMQ_QUANT_SCALAR_BACKEND)
        TEST_IGNORE_MESSAGE("AVX2 is unavailable on this host");
    TEST_ASSERT_EQUAL_STRING("avx512", semq_backend_name(SEMQ_ORBIT));
    TEST_ASSERT_EQUAL_STRING("avx2", semq_backend_name(SEMQ_QUANT));
    semq_config_t cfg = {0};
    semq_error_t err = {0};
    semq_codec_t* codec = NULL;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_config_quant(768u, 4u, &cfg, &err));
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_codec_create(&cfg, &codec, &err));
    TEST_ASSERT_EQUAL_STRING("avx2", semq_codec_backend(codec));
    semq_codec_free(codec);
#else
    TEST_IGNORE_MESSAGE("x86-64 only");
#endif
}

/* -------------------------------------------------------------------------- */
/*  reconstruct cross-backend                                       */
/* -------------------------------------------------------------------------- */

static void test_reconstruct_matches_scalar_dim_768(void) {
#if defined(__aarch64__) || defined(_M_ARM64)
    const uint32_t dim = 768u;
    semq_code_t* codes = (semq_code_t*)malloc((size_t)dim);
    double*      r_sca = (double*)malloc((size_t)dim * sizeof(double));
    double*      r_neo = (double*)malloc((size_t)dim * sizeof(double));
    TEST_ASSERT_NOT_NULL(codes);
    TEST_ASSERT_NOT_NULL(r_sca);
    TEST_ASSERT_NOT_NULL(r_neo);

    /* Walk every legal code value over the buffer. */
    for (uint32_t i = 0; i < dim; ++i) {
        codes[i] = (semq_code_t)(i % 30u);
    }

    const semq_backend_t* sc = semq_dispatch_get(SEMQ_BACKEND_SCALAR);
    const semq_backend_t* nb = semq_dispatch_get(SEMQ_BACKEND_NEON);
    TEST_ASSERT_NOT_NULL(sc);
    TEST_ASSERT_NOT_NULL(nb);

    TEST_ASSERT_EQUAL_INT(SEMQ_OK,
        sc->reconstruct(codes, dim, 50u, r_sca));
    TEST_ASSERT_EQUAL_INT(SEMQ_OK,
        nb->reconstruct(codes, dim, 50u, r_neo));

    for (uint32_t i = 0; i < dim; ++i) {
        TEST_ASSERT_TRUE(r_sca[i] == r_neo[i]);
    }
    free(codes);
    free(r_sca);
    free(r_neo);
#endif
}

static void test_sha256_streaming_crosses_dispatch_boundary(void) {
    uint8_t input[1500];
    for (size_t i = 0u; i < sizeof(input); i++) input[i] = (uint8_t)(i * 73u);
    uint8_t expected[32], actual[32];
    semq_sha256(input, sizeof(input), expected);
    semq_sha256_ctx_t ctx;
    semq_sha256_init(&ctx);
    semq_sha256_update(&ctx, input, 31u);
    semq_sha256_update(&ctx, input + 31u, 449u);
    semq_sha256_update(&ctx, input + 480u, sizeof(input) - 480u);
    semq_sha256_final(&ctx, actual);
    TEST_ASSERT_EQUAL_UINT8_ARRAY(expected, actual, 32u);
}

#if defined(__aarch64__) || defined(_M_ARM64)
static void test_arm_sha256_block_matches_fips(void) {
    if (!semq_dispatch_has_sha256()) TEST_IGNORE_MESSAGE("ARM SHA2 is unavailable");
    uint32_t state[8] = {
        0x6a09e667u, 0xbb67ae85u, 0x3c6ef372u, 0xa54ff53au,
        0x510e527fu, 0x9b05688cu, 0x1f83d9abu, 0x5be0cd19u,
    };
    uint8_t block[64] = {0x80u}; /* padded empty message */
    const uint32_t expected[8] = {
        0xe3b0c442u, 0x98fc1c14u, 0x9afbf4c8u, 0x996fb924u,
        0x27ae41e4u, 0x649b934cu, 0xa495991bu, 0x7852b855u,
    };
    semqi_sha256_block_arm(state, block);
    TEST_ASSERT_EQUAL_UINT32_ARRAY(expected, state, 8u);
}
#endif

/* -------------------------------------------------------------------------- */

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_dispatch_backends_bit_identical_dim_1);
    RUN_TEST(test_dispatch_backends_bit_identical_dim_15);
    RUN_TEST(test_dispatch_backends_bit_identical_dim_16);
    RUN_TEST(test_dispatch_backends_bit_identical_dim_17);
    RUN_TEST(test_dispatch_backends_bit_identical_dim_31);
    RUN_TEST(test_dispatch_backends_bit_identical_dim_32);
    RUN_TEST(test_dispatch_backends_bit_identical_dim_33);
    RUN_TEST(test_dispatch_backends_bit_identical_dim_63);
    RUN_TEST(test_dispatch_backends_bit_identical_dim_64);
    RUN_TEST(test_dispatch_backends_bit_identical_dim_65);
    RUN_TEST(test_dispatch_backends_bit_identical_dim_127);
    RUN_TEST(test_dispatch_backends_bit_identical_dim_768);
    RUN_TEST(test_dispatch_backends_bit_identical_dim_1025);
    RUN_TEST(test_dispatch_backends_bit_identical_dim_3072);
    RUN_TEST(test_quant_auto_dispatch_prefers_avx2_on_avx512_host);
    RUN_TEST(test_reconstruct_matches_scalar_dim_768);
    RUN_TEST(test_sha256_streaming_crosses_dispatch_boundary);
#if defined(__aarch64__) || defined(_M_ARM64)
    RUN_TEST(test_arm_sha256_block_matches_fips);
#endif
    return UNITY_END();
}
