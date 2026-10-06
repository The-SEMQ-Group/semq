/*
 * Copyright (c) 2026 The SEMQ Group Inc.
 * Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
 */

/*
 * test_core.c — the public C ABI against the specification examples:
 * SHA-256 (FIPS 180-4), the canonical config form, the input contract,
 * digests, the file image, concat, diff, floor and the FP environment.
 */

#include "unity.h"

#include "semq.h"
#include "core/semq_phase_atan2.h"

#include <fenv.h>
#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

void setUp(void)    {}
void tearDown(void) {}

/* -------------------------------------------------------------------------- */
/*  Helpers                                                                   */
/* -------------------------------------------------------------------------- */

static void assert_hex(const char* expected, const uint8_t* bytes, size_t len) {
    static const char digits[] = "0123456789abcdef";
    char got[2 * 256 + 1];
    TEST_ASSERT_TRUE(len <= 256u);
    for (size_t i = 0u; i < len; i++) {
        got[2u * i]      = digits[bytes[i] >> 4];
        got[2u * i + 1u] = digits[bytes[i] & 0x0Fu];
    }
    got[2u * len] = '\0';
    TEST_ASSERT_EQUAL_STRING(expected, got);
}

static semq_config_t quant44(void) {
    semq_config_t c;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_config_quant(4u, 4u, &c, NULL));
    return c;
}

/* Pack quant symbols (one per unit) into a canonical row. */
static void pack_quant(const uint8_t* symbols, uint32_t dim, uint32_t bits, uint8_t* out, uint32_t bpv) {
    memset(out, 0, bpv);
    uint64_t pos = 0u;
    for (uint32_t i = 0u; i < dim; i++) {
        for (uint32_t b = 0u; b < bits; b++, pos++) {
            if ((symbols[i] >> b) & 1u) out[pos >> 3] |= (uint8_t)(1u << (pos & 7u));
        }
    }
}

static semq_encoding_t* create_u64(const semq_config_t* cfg, const uint64_t* ids, uint64_t n,
                                   const uint8_t* rows, const semq_pair_t* manifest, uint32_t n_pairs) {
    semq_ids_t in = { SEMQ_ID_U64, n, ids, NULL, NULL };
    semq_encoding_t* e = NULL;
    semq_error_t err;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_encoding_create(cfg, &in, rows, manifest, n_pairs, &e, &err));
    TEST_ASSERT_NOT_NULL(e);
    return e;
}

static uint8_t* image_of(const semq_encoding_t* e, uint64_t* len) {
    *len = semq_encoding_file_size(e);
    uint8_t* buf = (uint8_t*)malloc((size_t)*len);
    TEST_ASSERT_NOT_NULL(buf);
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_encoding_save(e, buf, *len, NULL));
    return buf;
}

/* Recompute both digests of an image after a structural mutation. */
static void refresh_footer(uint8_t* img, uint64_t len) {
    const uint64_t s_len = len - 6u - 64u;  /* S ‖ manifest */
    /* manifest length: walk it from the end is not possible; the tests that
     * call this use an empty manifest (4 bytes). */
    const uint64_t man_len = 4u;
    semq_sha256(img + 6, s_len - man_len, img + len - 64u);
    uint8_t tmp[36];
    memcpy(tmp, img + len - 64u, 32u);
    memcpy(tmp + 32, img + len - 64u - man_len, 4u);
    semq_sha256(tmp, 36u, img + len - 32u);
}

/* -------------------------------------------------------------------------- */
/*  SHA-256                                                                   */
/* -------------------------------------------------------------------------- */

static void test_sha256_fips_vectors(void) {
    uint8_t d[32];
    semq_sha256((const uint8_t*)"abc", 3u, d);
    assert_hex("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", d, 32u);
    semq_sha256((const uint8_t*)"", 0u, d);
    assert_hex("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", d, 32u);
    const char* m56 = "abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq";
    semq_sha256((const uint8_t*)m56, strlen(m56), d);
    assert_hex("248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1", d, 32u);
    const char* m112 = "abcdefghbcdefghicdefghijdefghijkefghijklfghijklmghijklmnhijklmnoijklmnopjklmnopqklmnopqrlmnopqrsmnopqrstnopqrstu";
    semq_sha256((const uint8_t*)m112, strlen(m112), d);
    assert_hex("cf5b16a778af8380036ce59e7b0492370b249b11e8f07a51afac45037afee9d1", d, 32u);
    uint8_t* mega = (uint8_t*)malloc(1000000u);
    TEST_ASSERT_NOT_NULL(mega);
    memset(mega, 'a', 1000000u);
    semq_sha256(mega, 1000000u, d);
    assert_hex("cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0", d, 32u);
    free(mega);
}

/* -------------------------------------------------------------------------- */
/*  CodecConfig                                                               */
/* -------------------------------------------------------------------------- */

static void test_config_canonical_form(void) {
    semq_config_t c = quant44();
    uint8_t b[13];
    semq_config_to_bytes(&c, b);
    assert_hex("02040000000400000000000000", b, 13u);
    semq_config_t back;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_config_from_bytes(b, &back, NULL));
    TEST_ASSERT_TRUE(semq_config_equal(&c, &back));
    TEST_ASSERT_EQUAL_UINT32(2u, semq_config_bytes_per_vector(&c));
    TEST_ASSERT_EQUAL_UINT32(4u, semq_config_units_per_row(&c));
    float m = semq_config_max_magnitude(&c);
    uint32_t bits;
    memcpy(&bits, &m, 4u);
    TEST_ASSERT_EQUAL_HEX32(0x3f800000u, bits);  /* 2/sqrt(4) = 1.0 */
}

static void test_config_derived_quantities(void) {
    semq_config_t c;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_config_phase(8u, 16u, &c, NULL));
    TEST_ASSERT_EQUAL_UINT32(2u, semq_config_bytes_per_vector(&c));
    TEST_ASSERT_EQUAL_UINT32(4u, semq_config_units_per_row(&c));
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_config_phase(8u, 17u, &c, NULL));
    TEST_ASSERT_EQUAL_UINT32(4u, semq_config_bytes_per_vector(&c));
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_config_orbit(5u, 50u, &c, NULL));
    TEST_ASSERT_EQUAL_UINT32(5u, semq_config_bytes_per_vector(&c));
    TEST_ASSERT_EQUAL_UINT32(5u, semq_config_units_per_row(&c));
    TEST_ASSERT_EQUAL_FLOAT(0.0f, semq_config_max_magnitude(&c));
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_config_quant(1024u, 64u, &c, NULL));
    TEST_ASSERT_EQUAL_UINT32(896u, semq_config_bytes_per_vector(&c)); /* 1024 * 7 / 8 */
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_config_quant(3u, 4u, &c, NULL));
    TEST_ASSERT_EQUAL_UINT32(2u, semq_config_bytes_per_vector(&c));   /* ceil(9/8) */
}

static void test_config_rejects(void) {
    semq_config_t c;
    semq_error_t err;
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INVALID_INPUT, semq_config_quant(4u, 1u, &c, &err));
    TEST_ASSERT_EQUAL_UINT64((uint64_t)SEMQ_FIELD_P1, err.field);
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INVALID_INPUT, semq_config_quant(4u, 65u, &c, &err));
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INVALID_INPUT, semq_config_quant(0u, 4u, &c, &err));
    TEST_ASSERT_EQUAL_UINT64((uint64_t)SEMQ_FIELD_DIM, err.field);
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INVALID_INPUT, semq_config_quant(65537u, 4u, &c, &err));
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INVALID_INPUT, semq_config_phase(7u, 16u, &c, &err));
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INVALID_INPUT, semq_config_phase(6u, 16u, &c, &err));
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_config_phase(6u, 17u, &c, &err));
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INVALID_INPUT, semq_config_phase(8u, 1u, &c, &err));
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INVALID_INPUT, semq_config_phase(8u, 257u, &c, &err));
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INVALID_INPUT, semq_config_orbit(8u, 0u, &c, &err));
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INVALID_INPUT, semq_config_orbit(8u, (1u << 30) + 1u, &c, &err));
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_config_orbit(8u, 1u << 30, &c, &err));
    uint8_t bad[13] = { 3, 4, 0, 0, 0, 4, 0, 0, 0, 0, 0, 0, 0 };
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INVALID_INPUT, semq_config_from_bytes(bad, &c, &err));
    uint8_t rev[13] = { 2, 4, 0, 0, 0, 4, 0, 0, 0, 1, 0, 0, 0 };
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INVALID_INPUT, semq_config_from_bytes(rev, &c, &err));
    TEST_ASSERT_EQUAL_UINT64((uint64_t)SEMQ_FIELD_P2, err.field);
}

/* -------------------------------------------------------------------------- */
/*  Digests and file image against the specification examples                */
/* -------------------------------------------------------------------------- */

static void test_empty_encoding_identities_and_image(void) {
    semq_config_t c = quant44();
    semq_encoding_t* e = create_u64(&c, NULL, 0u, NULL, NULL, 0u);
    uint8_t d[32];
    semq_encoding_content_digest(e, d);
    assert_hex("4528e8a0422f5cde968847e021c85b4e6e78ce68da9e92b2981c62dd48f78f4a", d, 32u);
    semq_encoding_state_id(e, d);
    assert_hex("ef4d1522eb158aa9b6b83cd5d51f80ea2cc59ac3aeb45b69a1c28c99375b55b9", d, 32u);
    uint64_t len;
    uint8_t* img = image_of(e, &len);
    TEST_ASSERT_EQUAL_UINT64(96u, len);
    assert_hex("53454d51020002040000000400000000000000000000000000000000000000004528e8a0422f5cde968847e021c85b4e6e78ce68da9e92b2981c62dd48f78f4aef4d1522eb158aa9b6b83cd5d51f80ea2cc59ac3aeb45b69a1c28c99375b55b9", img, (size_t)len);
    semq_encoding_t* back = NULL;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_encoding_load(img, len, &back, NULL));
    TEST_ASSERT_EQUAL_UINT64(0u, semq_encoding_len(back));
    TEST_ASSERT_EQUAL_UINT32(SEMQ_ID_U64, semq_encoding_id_kind(back));
    free(img);
    semq_encoding_free(back);
    semq_encoding_free(e);
}

static void test_one_row_identities(void) {
    semq_config_t c = quant44();
    const uint64_t id = 7u;
    const uint8_t row[2] = { 0x07u, 0x07u };  /* symbols [7, 0, 4, 3] */
    semq_pair_t man = { (const uint8_t*)"encoder", 7u, (const uint8_t*)"x", 1u };
    semq_encoding_t* e = create_u64(&c, &id, 1u, row, &man, 1u);
    uint8_t d[32];
    semq_encoding_content_digest(e, d);
    assert_hex("1a3d8e8bfbf3429525d0bc11e18a17b75ea49af40b6b441f6863444f71230489", d, 32u);
    semq_encoding_state_id(e, d);
    assert_hex("07d119f5a0a76de95bd4b41110d6005e6fc38cfc398421dd15df2be68adf9f85", d, 32u);
    TEST_ASSERT_EQUAL_UINT32(1u, semq_encoding_manifest_len(e));
    semq_pair_t p;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_encoding_manifest_pair(e, 0u, &p, NULL));
    TEST_ASSERT_EQUAL_UINT32(7u, p.key_len);
    TEST_ASSERT_EQUAL_MEMORY("encoder", p.key, 7u);
    TEST_ASSERT_EQUAL_UINT32(1u, p.value_len);
    TEST_ASSERT_EQUAL_UINT8('x', p.value[0]);
    uint64_t idx = 0u;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_encoding_find_u64(e, 7u, &idx, NULL));
    TEST_ASSERT_EQUAL_UINT64(0u, idx);
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_encoding_find_u64(e, 8u, &idx, NULL));
    TEST_ASSERT_EQUAL_UINT64(SEMQ_NONE, idx);
    semq_error_t err;
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INVALID_INPUT, semq_encoding_find_utf8(e, (const uint8_t*)"7", 1u, &idx, &err));
    /* Round trip through the image. */
    uint64_t len;
    uint8_t* img = image_of(e, &len);
    semq_encoding_t* back = NULL;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_encoding_load(img, len, &back, NULL));
    uint8_t d2[32];
    semq_encoding_state_id(back, d2);
    TEST_ASSERT_EQUAL_MEMORY(d, d2, 32u);
    free(img);
    semq_encoding_free(back);
    semq_encoding_free(e);
}

static void test_constructor_rejects_non_canonical_rows(void) {
    semq_config_t c = quant44();
    semq_ids_t in = { SEMQ_ID_U64, 1u, NULL, NULL, NULL };
    const uint64_t id = 1u;
    in.u64 = &id;
    semq_encoding_t* e = NULL;
    semq_error_t err;
    const uint8_t padding_set[2] = { 0x07u, 0x17u };  /* bit 12 is padding */
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INVALID_INPUT, semq_encoding_create(&c, &in, padding_set, NULL, 0u, &e, &err));
    TEST_ASSERT_EQUAL_UINT64(0u, err.row);
    TEST_ASSERT_EQUAL_UINT64(SEMQ_NONE, err.field);
    /* Symbols must be < 2*bins = 8: a quant row cannot hold one, so use phase. */
    semq_config_t ph;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_config_phase(4u, 8u, &ph, NULL));
    const uint8_t bad_sector[1] = { 0x90u };  /* high nibble 9 >= 8 sectors */
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INVALID_INPUT, semq_encoding_create(&ph, &in, bad_sector, NULL, 0u, &e, &err));
    TEST_ASSERT_EQUAL_UINT64(1u, err.field);
    /* Duplicate ids report the later input row. */
    const uint64_t dup[3] = { 5u, 9u, 5u };
    in.n = 3u; in.u64 = dup;
    const uint8_t rows[6] = { 0 };
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INVALID_INPUT, semq_encoding_create(&c, &in, rows, NULL, 0u, &e, &err));
    TEST_ASSERT_EQUAL_UINT64(2u, err.row);
    /* An empty encoding still needs a valid kind. */
    semq_ids_t bad_kind = { 7u, 0u, NULL, NULL, NULL };
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INVALID_INPUT, semq_encoding_create(&c, &bad_kind, NULL, NULL, 0u, &e, &err));
}

/* -------------------------------------------------------------------------- */
/*  Codec: encode / decode / unpack and the input contract                    */
/* -------------------------------------------------------------------------- */

static semq_encoding_t* encode_u64(semq_codec_t* codec, const uint64_t* ids, uint64_t n,
                                   const float* vectors, semq_error_t* err) {
    semq_ids_t in = { SEMQ_ID_U64, n, ids, NULL, NULL };
    semq_encoding_t* e = NULL;
    semq_codec_encode(codec, &in, vectors, NULL, 0u, &e, err);
    return e;
}

static void test_encode_sorts_ids_and_maps_symbols(void) {
    semq_config_t c = quant44();
    semq_codec_t* codec = NULL;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_codec_create(&c, &codec, NULL));
    const uint64_t ids[3] = { 3u, 1u, 2u };
    const float vectors[12] = {
        0.5f, 0.5f, 0.5f, 0.5f,      /* id 3: all symbols 6 (sign 1, bin 2) */
        -0.5f, -0.5f, -0.5f, -0.5f,  /* id 1: all symbols 2 (sign 0, bin 2) */
        1.0f, 0.0f, 0.0f, 0.0f,      /* id 2: [7, 4, 4, 4] */
    };
    semq_error_t err;
    semq_encoding_t* e = encode_u64(codec, ids, 3u, vectors, &err);
    TEST_ASSERT_NOT_NULL(e);
    const uint64_t* sorted = semq_encoding_ids_u64(e);
    TEST_ASSERT_EQUAL_UINT64(1u, sorted[0]);
    TEST_ASSERT_EQUAL_UINT64(2u, sorted[1]);
    TEST_ASSERT_EQUAL_UINT64(3u, sorted[2]);
    uint8_t symbols[12];
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_codec_unpack(codec, e, symbols, &err));
    const uint8_t expected[12] = { 2, 2, 2, 2, 7, 4, 4, 4, 6, 6, 6, 6 };
    TEST_ASSERT_EQUAL_UINT8_ARRAY(expected, symbols, 12u);
    float rep[12];
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_codec_decode(codec, e, rep, &err));
    TEST_ASSERT_EQUAL_FLOAT(-0.625f, rep[0]);   /* -(2 + 0.5) * 1.0 / 4 */
    TEST_ASSERT_EQUAL_FLOAT(0.875f, rep[4]);    /* +(3 + 0.5) / 4 */
    TEST_ASSERT_EQUAL_FLOAT(0.125f, rep[5]);    /* +(0 + 0.5) / 4 */
    TEST_ASSERT_EQUAL_FLOAT(0.625f, rep[8]);
    /* Same input, same bytes, same state. */
    semq_encoding_t* e2 = encode_u64(codec, ids, 3u, vectors, &err);
    uint8_t a[32], b[32];
    semq_encoding_state_id(e, a);
    semq_encoding_state_id(e2, b);
    TEST_ASSERT_EQUAL_MEMORY(a, b, 32u);
    semq_encoding_free(e2);
    semq_encoding_free(e);
    semq_codec_free(codec);
}

static void test_encode_three_operators_round_trip_symbols(void) {
    /* orbit and phase through the same path; check unpack shapes and the
     * fixed point kernel_encode(decode(row)) == row via a second encode of
     * the normalized representative is not claimed, so only shapes here. */
    semq_config_t o, p;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_config_orbit(4u, 50u, &o, NULL));
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_config_phase(4u, 16u, &p, NULL));
    const float v[4] = { 0.5f, 0.5f, -0.5f, 0.5f };
    const uint64_t id = 1u;
    semq_error_t err;
    semq_codec_t* co = NULL; semq_codec_t* cp = NULL;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_codec_create(&o, &co, NULL));
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_codec_create(&p, &cp, NULL));
    semq_encoding_t* eo = encode_u64(co, &id, 1u, v, &err);
    semq_encoding_t* ep = encode_u64(cp, &id, 1u, v, &err);
    TEST_ASSERT_NOT_NULL(eo);
    TEST_ASSERT_NOT_NULL(ep);
    uint8_t so[4], sp[2];
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_codec_unpack(co, eo, so, &err));
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_codec_unpack(cp, ep, sp, &err));
    /* orbit: 0.5 * 50 = 25 -> digital root 7 -> symbol 7; -0.5 -> 9 + 7 = 16 */
    const uint8_t eso[4] = { 7, 7, 16, 7 };
    TEST_ASSERT_EQUAL_UINT8_ARRAY(eso, so, 4u);
    /* phase: (0.5, 0.5) is the +45 degree diagonal, where sector 10 of 16
     * over (-pi, pi] begins, and (-0.5, 0.5) is 135 degrees, where sector 14
     * begins. The polynomial meets pi/4 exactly at t = 1, so both land at
     * the start of their sector rather than one sector early. */
    TEST_ASSERT_EQUAL_UINT8(10u, sp[0]);
    TEST_ASSERT_EQUAL_UINT8(14u, sp[1]);
    float rep[4];
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_codec_decode(co, eo, rep, &err));
    TEST_ASSERT_EQUAL_FLOAT(0.14f, rep[0]);   /* 7 / 50 */
    TEST_ASSERT_EQUAL_FLOAT(-0.14f, rep[2]);
    /* Cross-config use is Incompatible. */
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INCOMPATIBLE, semq_codec_decode(co, ep, rep, &err));
    semq_encoding_free(eo);
    semq_encoding_free(ep);
    semq_codec_free(co);
    semq_codec_free(cp);
}

/* The error of the phase polynomial against atan on [0, 1], and its
 * derivative, for the stationary-point analysis below. */
static double poly_err(double t) { return semq_phase_atan_poly_unit(t) - atan(t); }
static double poly_err_prime(double t) {
    const double t2 = t * t;
    const double p_prime = SEMQ_PHASE_C1 + 3.0 * SEMQ_PHASE_C3 * t2 + 5.0 * SEMQ_PHASE_C5 * t2 * t2;
    return p_prime - 1.0 / (1.0 + t2);
}

static void test_phase_polynomial_is_continuous_monotone_and_accurate(void) {
    /* The two octants meet: p(1) is pi/4 to the bit, so atan2(1, 1) is exactly
     * pi/4 and the reflected octant continues it without a jump. */
    TEST_ASSERT_TRUE(semq_phase_atan_poly_unit(1.0) == SEMQ_PI_HALF / 2.0);
    TEST_ASSERT_TRUE(semq_phase_atan2_ref(1.0f, 1.0f) == SEMQ_PI_HALF / 2.0);
    /* Stationary points of the error: sign changes of its derivative on a
     * grid, refined by bisection. Three interior ones, each at 7.04e-4 rad. */
    const int grid = 200000;
    int found = 0;
    double worst = 0.0, prev = poly_err_prime(0.0), prev_p = semq_phase_atan_poly_unit(0.0);
    for (int i = 1; i <= grid; i++) {
        const double t = (double)i / (double)grid;
        const double d = poly_err_prime(t);
        if ((prev < 0.0) != (d < 0.0)) {
            double lo = (double)(i - 1) / (double)grid, hi = t;
            for (int k = 0; k < 80; k++) {
                const double mid = 0.5 * (lo + hi);
                if ((poly_err_prime(lo) < 0.0) != (poly_err_prime(mid) < 0.0)) hi = mid; else lo = mid;
            }
            const double e = fabs(poly_err(0.5 * (lo + hi)));
            TEST_ASSERT_TRUE(fabs(e - 7.0367e-4) < 1e-9);
            found++;
        }
        prev = d;
        /* Dense sampling: the error stays under the 0.05 degree bound and the
         * polynomial is strictly increasing (its inverse is well defined). */
        const double e = fabs(poly_err(t));
        if (e > worst) worst = e;
        const double pt = semq_phase_atan_poly_unit(t);
        TEST_ASSERT_TRUE(pt > prev_p);
        prev_p = pt;
    }
    TEST_ASSERT_EQUAL_INT(3, found);
    TEST_ASSERT_TRUE(worst <= 7.04e-4);
    TEST_ASSERT_TRUE(worst * 180.0 / SEMQ_PI <= 0.05);
    /* The derivative p'(t) = c1 + 3 c3 u + 5 c5 u^2 (u = t^2) is a parabola
     * whose vertex u = -3 c3 / (10 c5) lies beyond 1, so its minimum on
     * [0, 1] is p'(1) = 0.5188: the polynomial is strictly increasing. */
    const double vertex = -3.0 * SEMQ_PHASE_C3 / (10.0 * SEMQ_PHASE_C5);
    TEST_ASSERT_TRUE(vertex > 1.0);
    const double min_slope = SEMQ_PHASE_C1 + 3.0 * SEMQ_PHASE_C3 + 5.0 * SEMQ_PHASE_C5;
    TEST_ASSERT_TRUE(min_slope > 0.518 && min_slope < 0.519);
}

static void test_phase_sectors_are_monotone_across_the_diagonal_and_fixed_on_axes(void) {
    const uint32_t counts[9] = { 2u, 4u, 8u, 16u, 17u, 32u, 64u, 255u, 256u };
    for (int c = 0; c < 9; c++) {
        const uint32_t n = counts[c];
        /* Sweep the direction through the diagonal in float32 steps: the
         * angle and the sector never decrease (no reversal at ax == ay). */
        double prev_theta = -1.0;
        uint8_t prev_sector = 0u;
        for (int i = -2000; i <= 2000; i++) {
            const float y = i <= 0 ? 1.0f + (float)i * 1e-5f : 1.0f;
            const float x = i <= 0 ? 1.0f : 1.0f - (float)i * 1e-5f;
            const double theta = semq_phase_atan2_ref(y, x);
            const uint8_t s = semq_phase_sector(y, x, n);
            TEST_ASSERT_TRUE(theta >= prev_theta);
            TEST_ASSERT_TRUE(s >= prev_sector);
            prev_theta = theta;
            prev_sector = s;
        }
        /* Axes and the zero pair map to fixed sectors: angle 0 to floor(n / 2),
         * +pi/2 to floor(3n / 4), +pi to the last sector. A negative zero is
         * not distinguished from +0 (encode canonicalizes it away), so
         * (-0, -1) is +pi as well, never -pi. */
        TEST_ASSERT_EQUAL_UINT8((uint8_t)(n / 2u), semq_phase_sector(0.0f, 1.0f, n));
        TEST_ASSERT_EQUAL_UINT8((uint8_t)(n / 2u), semq_phase_sector(-0.0f, 1.0f, n));
        TEST_ASSERT_EQUAL_UINT8((uint8_t)(n / 2u), semq_phase_sector(0.0f, 0.0f, n));
        TEST_ASSERT_EQUAL_UINT8((uint8_t)(n / 2u), semq_phase_sector(-0.0f, -0.0f, n));
        TEST_ASSERT_EQUAL_UINT8((uint8_t)((3u * n) / 4u), semq_phase_sector(1.0f, 0.0f, n));
        TEST_ASSERT_EQUAL_UINT8((uint8_t)(n - 1u), semq_phase_sector(0.0f, -1.0f, n));
        TEST_ASSERT_EQUAL_UINT8((uint8_t)(n - 1u), semq_phase_sector(-0.0f, -1.0f, n));
        /* The reflected octant is the mirror of the first one. */
        TEST_ASSERT_TRUE(semq_phase_atan2_ref(0.25f, 1.0f) + semq_phase_atan2_ref(1.0f, 0.25f) == SEMQ_PI_HALF);
    }
}

static void test_encode_canonicalizes_subnormals(void) {
    semq_config_t c = quant44();
    semq_codec_t* codec = NULL;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_codec_create(&c, &codec, NULL));
    const uint64_t id = 1u;
    const float with_sub[4] = { 1.0f, 1e-40f, -1e-41f, 0.0f };
    const float with_zero[4] = { 1.0f, 0.0f, 0.0f, 0.0f };
    semq_error_t err;
    semq_encoding_t* a = encode_u64(codec, &id, 1u, with_sub, &err);
    semq_encoding_t* b = encode_u64(codec, &id, 1u, with_zero, &err);
    TEST_ASSERT_NOT_NULL(a);
    TEST_ASSERT_NOT_NULL(b);
    uint8_t da[32], db[32];
    semq_encoding_content_digest(a, da);
    semq_encoding_content_digest(b, db);
    TEST_ASSERT_EQUAL_MEMORY(da, db, 32u);
    semq_encoding_free(a);
    semq_encoding_free(b);
    semq_codec_free(codec);
}

static void test_encode_rejects(void) {
    semq_config_t c = quant44();
    semq_codec_t* codec = NULL;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_codec_create(&c, &codec, NULL));
    semq_error_t err;
    const uint64_t ids[2] = { 1u, 2u };
    float v[8] = { 1.0f, 0.0f, 0.0f, 0.0f, 0.0f, 1.0f, 0.0f, 0.0f };
    v[6] = NAN;
    TEST_ASSERT_NULL(encode_u64(codec, ids, 2u, v, &err));
    TEST_ASSERT_EQUAL_UINT32(SEMQ_ERR_INVALID_INPUT, err.status);
    TEST_ASSERT_EQUAL_UINT64(1u, err.row);
    TEST_ASSERT_EQUAL_UINT64(2u, err.field);
    v[6] = 0.0f;
    v[0] = 0.9f;  /* norm 0.81 */
    TEST_ASSERT_NULL(encode_u64(codec, ids, 2u, v, &err));
    TEST_ASSERT_EQUAL_UINT64(0u, err.row);
    v[0] = 1.0f;
    /* Norm at the tolerance boundary: sum of squares 1 + 2^-10 is admitted. */
    float edge[4] = { 1.0f, 0.03125f, 0.0f, 0.0f };  /* 0.03125^2 = 2^-10 */
    semq_encoding_t* ok = encode_u64(codec, ids, 1u, edge, &err);
    TEST_ASSERT_NOT_NULL(ok);
    semq_encoding_free(ok);
    edge[1] = 0.0316f;  /* just outside */
    TEST_ASSERT_NULL(encode_u64(codec, ids, 1u, edge, &err));
    /* Duplicate ids. */
    const uint64_t dup[2] = { 4u, 4u };
    TEST_ASSERT_NULL(encode_u64(codec, dup, 2u, v, &err));
    TEST_ASSERT_EQUAL_UINT64(1u, err.row);
    /* n = 0 with an explicit kind is fine. */
    semq_encoding_t* empty = encode_u64(codec, NULL, 0u, NULL, &err);
    TEST_ASSERT_NOT_NULL(empty);
    semq_encoding_free(empty);
    /* utf8 ids: invalid UTF-8 and an empty id are rejected with the row. */
    const uint8_t bytes[3] = { 'a', 0xFFu, 'b' };
    const uint64_t offsets[3] = { 0u, 1u, 3u };
    semq_ids_t utf = { SEMQ_ID_UTF8, 2u, NULL, offsets, bytes };
    semq_encoding_t* e = NULL;
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INVALID_INPUT, semq_codec_encode(codec, &utf, v, NULL, 0u, &e, &err));
    TEST_ASSERT_EQUAL_UINT64(1u, err.row);
    semq_codec_free(codec);
}

static void test_codec_construction_requires_round_to_nearest(void) {
    const int modes[] = { FE_DOWNWARD, FE_UPWARD, FE_TOWARDZERO };
    const semq_config_t configs[] = {
        { SEMQ_QUANT, 3u, 4u, SEMQ_RULE_REVISION },
        { SEMQ_PHASE, 4u, 16u, SEMQ_RULE_REVISION },
        { SEMQ_ORBIT, 3u, 50u, SEMQ_RULE_REVISION }
    };
    for (size_t op = 0u; op < 3u; op++) {
        for (size_t i = 0u; i < 3u; i++) {
            semq_codec_t* codec = NULL;
            semq_error_t err;
            const int saved = fegetround();
            TEST_ASSERT_EQUAL_INT(0, fesetround(modes[i]));
            const semq_status_t status = semq_codec_create(&configs[op], &codec, &err);
            const int unchanged = fegetround() == modes[i];
            fesetround(saved);
            semq_codec_free(codec);
            TEST_ASSERT_EQUAL_INT(SEMQ_ERR_UNSUPPORTED, status);
            TEST_ASSERT_NULL(codec);
            TEST_ASSERT_TRUE(unchanged);
            TEST_ASSERT_EQUAL_UINT64(SEMQ_NONE, err.row);
            TEST_ASSERT_EQUAL_UINT64(SEMQ_NONE, err.field);
        }
    }
}

static void test_encode_requires_round_to_nearest(void) {
    semq_config_t c = quant44();
    semq_codec_t* codec = NULL;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_codec_create(&c, &codec, NULL));
    const uint64_t id = 1u;
    const float v[4] = { 1.0f, 0.0f, 0.0f, 0.0f };
    semq_error_t err;
    const int saved = fegetround();
    TEST_ASSERT_EQUAL_INT(0, fesetround(FE_DOWNWARD));
    semq_encoding_t* e = encode_u64(codec, &id, 1u, v, &err);
    fesetround(saved);
    TEST_ASSERT_NULL(e);
    TEST_ASSERT_EQUAL_UINT32(SEMQ_ERR_UNSUPPORTED, err.status);
    semq_codec_free(codec);
}

/* -------------------------------------------------------------------------- */
/*  File reader                                                               */
/* -------------------------------------------------------------------------- */

static semq_encoding_t* sample_two_rows(void) {
    semq_config_t c = quant44();
    const uint64_t ids[2] = { 10u, 20u };
    const uint8_t rows[4] = { 0x07u, 0x07u, 0x24u, 0x01u };
    return create_u64(&c, ids, 2u, rows, NULL, 0u);
}

static void test_load_detects_corruption(void) {
    semq_encoding_t* e = sample_two_rows();
    uint64_t len;
    uint8_t* img = image_of(e, &len);
    TEST_ASSERT_EQUAL_UINT64(28u + 16u + 4u + 4u + 64u, len);
    semq_encoding_t* out = NULL;
    semq_error_t err;
    uint8_t* copy = (uint8_t*)malloc((size_t)len + 1u);
    TEST_ASSERT_NOT_NULL(copy);

    /* A row byte: content digest fails. */
    memcpy(copy, img, (size_t)len);
    copy[28u + 16u] ^= 0x01u;
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INTEGRITY, semq_encoding_load(copy, len, &out, &err));
    TEST_ASSERT_EQUAL_UINT32(SEMQ_WHICH_CONTENT, err.which);

    /* Truncation and trailing bytes. */
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_FORMAT, semq_encoding_load(img, len - 1u, &out, &err));
    memcpy(copy, img, (size_t)len);
    copy[len] = 0u;
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_FORMAT, semq_encoding_load(copy, len + 1u, &out, &err));

    /* Version 1 and a future version. */
    memcpy(copy, img, (size_t)len);
    copy[4] = 1u;
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_FORMAT, semq_encoding_load(copy, len, &out, &err));
    TEST_ASSERT_EQUAL_UINT64((uint64_t)SEMQ_SECTION_FRAMING, err.field);
    copy[4] = 3u;
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_FORMAT, semq_encoding_load(copy, len, &out, &err));
    memcpy(copy, img, (size_t)len);
    copy[0] = 'X';
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_FORMAT, semq_encoding_load(copy, len, &out, &err));

    /* n = 2^40: rejected by the size checks before any allocation. */
    memcpy(copy, img, (size_t)len);
    copy[25] = 0x01u;  /* n byte 5 */
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_FORMAT, semq_encoding_load(copy, len, &out, &err));
    TEST_ASSERT_EQUAL_UINT64((uint64_t)SEMQ_SECTION_SIZES, err.field);

    /* Ids out of order with digests recomputed: ids section. */
    memcpy(copy, img, (size_t)len);
    copy[28] = 30u;  /* first id becomes 30 > 20 */
    refresh_footer(copy, len);
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_FORMAT, semq_encoding_load(copy, len, &out, &err));
    TEST_ASSERT_EQUAL_UINT64((uint64_t)SEMQ_SECTION_IDS, err.field);

    /* A padding bit with digests recomputed: the row check, after integrity. */
    memcpy(copy, img, (size_t)len);
    copy[28u + 16u + 1u] |= 0x10u;
    refresh_footer(copy, len);
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_FORMAT, semq_encoding_load(copy, len, &out, &err));
    TEST_ASSERT_EQUAL_UINT64((uint64_t)SEMQ_SECTION_ROWS, err.field);
    TEST_ASSERT_EQUAL_UINT64(0u, err.row);

    /* A footer copied from another valid state: content digest fails. */
    semq_config_t c = quant44();
    semq_encoding_t* other = create_u64(&c, NULL, 0u, NULL, NULL, 0u);
    uint64_t olen;
    uint8_t* oimg = image_of(other, &olen);
    memcpy(copy, img, (size_t)len);
    memcpy(copy + len - 64u, oimg + olen - 64u, 64u);
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INTEGRITY, semq_encoding_load(copy, len, &out, &err));
    TEST_ASSERT_EQUAL_UINT32(SEMQ_WHICH_CONTENT, err.which);
    free(oimg);
    semq_encoding_free(other);

    /* A manifest byte with only the state id stale: which = state. */
    semq_pair_t man = { (const uint8_t*)"k", 1u, (const uint8_t*)"v", 1u };
    const uint64_t ids[2] = { 10u, 20u };
    const uint8_t rows[4] = { 0x07u, 0x07u, 0x24u, 0x01u };
    semq_encoding_t* with_man = create_u64(&c, ids, 2u, rows, &man, 1u);
    uint64_t mlen;
    uint8_t* mimg = image_of(with_man, &mlen);
    mimg[mlen - 64u - 1u] = 'w';  /* last manifest byte: the value */
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INTEGRITY, semq_encoding_load(mimg, mlen, &out, &err));
    TEST_ASSERT_EQUAL_UINT32(SEMQ_WHICH_STATE, err.which);
    free(mimg);
    semq_encoding_free(with_man);

    free(copy);
    free(img);
    semq_encoding_free(e);
}

static void test_utf8_ids_round_trip_and_order(void) {
    semq_config_t c = quant44();
    /* "b", "a", "ab": bytewise order is a, ab, b. */
    const uint8_t bytes[4] = { 'b', 'a', 'a', 'b' };
    const uint64_t offsets[4] = { 0u, 1u, 2u, 4u };
    semq_ids_t in = { SEMQ_ID_UTF8, 3u, NULL, offsets, bytes };
    const uint8_t rows[6] = { 1, 0, 2, 0, 3, 0 };
    semq_encoding_t* e = NULL;
    semq_error_t err;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_encoding_create(&c, &in, rows, NULL, 0u, &e, &err));
    const uint64_t* off = semq_encoding_ids_utf8_offsets(e);
    uint64_t blen;
    const uint8_t* b = semq_encoding_ids_utf8_bytes(e, &blen);
    TEST_ASSERT_EQUAL_UINT64(4u, blen);
    TEST_ASSERT_EQUAL_MEMORY("aabb", b, 4u);
    TEST_ASSERT_EQUAL_UINT64(0u, off[0]);
    TEST_ASSERT_EQUAL_UINT64(1u, off[1]);
    TEST_ASSERT_EQUAL_UINT64(3u, off[2]);
    TEST_ASSERT_EQUAL_UINT64(4u, off[3]);
    uint64_t rlen;
    const uint8_t* r = semq_encoding_rows(e, &rlen);
    TEST_ASSERT_EQUAL_UINT8(2u, r[0]);  /* row of "a" */
    TEST_ASSERT_EQUAL_UINT8(3u, r[2]);  /* row of "ab" */
    TEST_ASSERT_EQUAL_UINT8(1u, r[4]);  /* row of "b" */
    uint64_t idx;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_encoding_find_utf8(e, (const uint8_t*)"ab", 2u, &idx, NULL));
    TEST_ASSERT_EQUAL_UINT64(1u, idx);
    uint64_t len;
    uint8_t* img = image_of(e, &len);
    semq_encoding_t* back = NULL;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_encoding_load(img, len, &back, &err));
    uint8_t d1[32], d2[32];
    semq_encoding_state_id(e, d1);
    semq_encoding_state_id(back, d2);
    TEST_ASSERT_EQUAL_MEMORY(d1, d2, 32u);
    free(img);
    semq_encoding_free(back);
    semq_encoding_free(e);
}

/* -------------------------------------------------------------------------- */
/*  concat                                                                    */
/* -------------------------------------------------------------------------- */

static void test_concat_is_order_independent(void) {
    semq_config_t c = quant44();
    const uint64_t all_ids[3] = { 1u, 2u, 3u };
    const uint8_t all_rows[6] = { 0x07u, 0x07u, 0x24u, 0x01u, 0x11u, 0x02u };
    semq_encoding_t* whole = create_u64(&c, all_ids, 3u, all_rows, NULL, 0u);
    semq_encoding_t* p[3];
    for (uint32_t i = 0u; i < 3u; i++) p[i] = create_u64(&c, &all_ids[i], 1u, all_rows + 2u * i, NULL, 0u);
    uint8_t want[32];
    semq_encoding_state_id(whole, want);
    const semq_encoding_t* order_a[3] = { p[0], p[1], p[2] };
    const semq_encoding_t* order_b[3] = { p[2], p[0], p[1] };
    semq_encoding_t* ca = NULL; semq_encoding_t* cb = NULL;
    semq_error_t err;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_encoding_concat(order_a, 3u, &ca, &err));
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_encoding_concat(order_b, 3u, &cb, &err));
    uint8_t got[32];
    semq_encoding_state_id(ca, got);
    TEST_ASSERT_EQUAL_MEMORY(want, got, 32u);
    semq_encoding_state_id(cb, got);
    TEST_ASSERT_EQUAL_MEMORY(want, got, 32u);
    /* Empty is neutral. */
    semq_encoding_t* empty = create_u64(&c, NULL, 0u, NULL, NULL, 0u);
    const semq_encoding_t* with_empty[2] = { whole, empty };
    semq_encoding_t* ce = NULL;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_encoding_concat(with_empty, 2u, &ce, &err));
    semq_encoding_state_id(ce, got);
    TEST_ASSERT_EQUAL_MEMORY(want, got, 32u);
    /* Overlap. */
    const semq_encoding_t* overlap[2] = { whole, p[1] };
    semq_encoding_t* bad = NULL;
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INVALID_INPUT, semq_encoding_concat(overlap, 2u, &bad, &err));
    TEST_ASSERT_EQUAL_UINT64(1u, err.field);
    /* Different manifest. */
    semq_pair_t man = { (const uint8_t*)"encoder", 7u, (const uint8_t*)"x", 1u };
    semq_encoding_t* m = create_u64(&c, &all_ids[2], 1u, all_rows + 4u, &man, 1u);
    const semq_encoding_t* mixed[2] = { p[0], m };
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INVALID_INPUT, semq_encoding_concat(mixed, 2u, &bad, &err));
    /* Different config. */
    semq_config_t c2;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_config_quant(4u, 3u, &c2, NULL));
    semq_encoding_t* other = create_u64(&c2, &all_ids[2], 1u, all_rows + 2u, NULL, 0u); /* symbols 4,4,4,0 < 6 */
    const semq_encoding_t* incompatible[2] = { p[0], other };
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INCOMPATIBLE, semq_encoding_concat(incompatible, 2u, &bad, &err));
    semq_encoding_free(other);
    semq_encoding_free(m);
    semq_encoding_free(ce);
    semq_encoding_free(empty);
    semq_encoding_free(ca);
    semq_encoding_free(cb);
    for (uint32_t i = 0u; i < 3u; i++) semq_encoding_free(p[i]);
    semq_encoding_free(whole);
}

/* -------------------------------------------------------------------------- */
/*  diff, within, measure                                                     */
/* -------------------------------------------------------------------------- */

static void test_diff_lists_units_and_manifest(void) {
    semq_config_t c = quant44();
    const uint64_t ref_ids[3] = { 1u, 2u, 3u };
    const uint8_t ref_rows[6] = { 0x07u, 0x07u, 0x24u, 0x01u, 0x11u, 0x02u };
    const uint64_t cand_ids[3] = { 2u, 3u, 4u };
    const uint8_t cand_rows[6] = { 0x24u, 0x01u, 0x11u, 0x06u, 0x00u, 0x00u }; /* id 3: unit 3 symbol 1 -> 3 */
    semq_pair_t ref_man[2] = {
        { (const uint8_t*)"encoder", 7u, (const uint8_t*)"m1", 2u },
        { (const uint8_t*)"note", 4u, (const uint8_t*)"a", 1u },
    };
    semq_pair_t cand_man[2] = {
        { (const uint8_t*)"encoder", 7u, (const uint8_t*)"m1", 2u },
        { (const uint8_t*)"run", 3u, (const uint8_t*)"7", 1u },
    };
    semq_encoding_t* ref = create_u64(&c, ref_ids, 3u, ref_rows, ref_man, 2u);
    semq_encoding_t* cand = create_u64(&c, cand_ids, 3u, cand_rows, cand_man, 2u);
    semq_diff_t* d = NULL;
    semq_error_t err;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_encoding_diff(ref, cand, &d, &err));
    TEST_ASSERT_EQUAL_UINT64(1u, semq_diff_count(d, SEMQ_LIST_ADDED));
    TEST_ASSERT_EQUAL_UINT64(1u, semq_diff_count(d, SEMQ_LIST_REMOVED));
    TEST_ASSERT_EQUAL_UINT64(1u, semq_diff_count(d, SEMQ_LIST_CHANGED));
    TEST_ASSERT_EQUAL_UINT64(1u, semq_diff_n_unchanged(d));
    uint64_t id = 0u;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_diff_id(d, SEMQ_LIST_ADDED, 0u, &id, NULL, NULL, &err));
    TEST_ASSERT_EQUAL_UINT64(4u, id);
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_diff_id(d, SEMQ_LIST_REMOVED, 0u, &id, NULL, NULL, &err));
    TEST_ASSERT_EQUAL_UINT64(1u, id);
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_diff_id(d, SEMQ_LIST_CHANGED, 0u, &id, NULL, NULL, &err));
    TEST_ASSERT_EQUAL_UINT64(3u, id);
    uint64_t h = 0u;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_diff_hamming(d, 0u, &h, &err));
    TEST_ASSERT_EQUAL_UINT64(1u, h);
    uint32_t units[4]; uint8_t sr[4], sc[4]; uint64_t count = 0u;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_diff_units_u64(d, 3u, units, sr, sc, 4u, &count, &err));
    TEST_ASSERT_EQUAL_UINT64(1u, count);
    TEST_ASSERT_EQUAL_UINT32(3u, units[0]);
    TEST_ASSERT_EQUAL_UINT8(1u, sr[0]);
    TEST_ASSERT_EQUAL_UINT8(3u, sc[0]);
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_diff_units_u64(d, 2u, units, sr, sc, 4u, &count, &err));
    TEST_ASSERT_EQUAL_UINT64(0u, count);
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INVALID_INPUT, semq_diff_units_u64(d, 1u, units, sr, sc, 4u, &count, &err));
    /* Manifest: note removed, run added, encoder unchanged. */
    TEST_ASSERT_EQUAL_UINT32(2u, semq_diff_manifest_changes(d));
    semq_manifest_change_t m;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_diff_manifest_change(d, 0u, &m, &err));
    TEST_ASSERT_EQUAL_MEMORY("note", m.key, 4u);
    TEST_ASSERT_TRUE(m.has_before && !m.has_after);
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_diff_manifest_change(d, 1u, &m, &err));
    TEST_ASSERT_EQUAL_MEMORY("run", m.key, 3u);
    TEST_ASSERT_TRUE(!m.has_before && m.has_after);
    /* The diff outlives the encodings it was built from. */
    semq_encoding_free(ref);
    semq_encoding_free(cand);
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_diff_units_u64(d, 3u, units, sr, sc, 4u, &count, &err));
    TEST_ASSERT_EQUAL_UINT64(1u, count);
    /* removed is non-empty, so no floor admits this diff. */
    uint8_t rid[32];
    semq_diff_reference_id(d, rid);
    semq_floor_t* f = NULL;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_floor_create(&c, SEMQ_ID_U64, rid, 1u, 4u, 4u, 4u, &f, &err));
    int within = 1;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_diff_within(d, f, &within, &err));
    TEST_ASSERT_FALSE(within);
    semq_floor_free(f);
    semq_diff_free(d);
    /* Short circuit: identical states. */
    semq_encoding_t* same = create_u64(&c, ref_ids, 3u, ref_rows, ref_man, 2u);
    semq_encoding_t* same2 = create_u64(&c, ref_ids, 3u, ref_rows, ref_man, 2u);
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_encoding_diff(same, same2, &d, &err));
    TEST_ASSERT_EQUAL_UINT64(3u, semq_diff_n_unchanged(d));
    TEST_ASSERT_EQUAL_UINT64(0u, semq_diff_count(d, SEMQ_LIST_CHANGED));
    semq_diff_free(d);
    /* Different kinds are incompatible. */
    const uint8_t bytes[1] = { 'a' };
    const uint64_t offsets[2] = { 0u, 1u };
    semq_ids_t utf = { SEMQ_ID_UTF8, 1u, NULL, offsets, bytes };
    semq_encoding_t* other = NULL;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_encoding_create(&c, &utf, ref_rows, NULL, 0u, &other, &err));
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INCOMPATIBLE, semq_encoding_diff(same, other, &d, &err));
    semq_encoding_free(other);
    semq_encoding_free(same);
    semq_encoding_free(same2);
}

/* Build a quant(16, 4) encoding of `n` rows where row `i` has all symbols
 * equal to `base`, except the first `n_changed` rows whose first `flip`
 * units take symbol `base + 1`. */
static semq_encoding_t* rows_with_changes(uint64_t n, uint64_t n_changed, uint32_t flip, uint8_t base) {
    semq_config_t c;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_config_quant(16u, 4u, &c, NULL));
    const uint32_t bpv = semq_config_bytes_per_vector(&c);  /* 6 */
    uint64_t* ids = (uint64_t*)malloc((size_t)n * sizeof(uint64_t));
    uint8_t* rows = (uint8_t*)malloc((size_t)n * bpv);
    TEST_ASSERT_NOT_NULL(ids);
    TEST_ASSERT_NOT_NULL(rows);
    for (uint64_t i = 0u; i < n; i++) {
        uint8_t sym[16];
        for (uint32_t u = 0u; u < 16u; u++) sym[u] = base;
        if (i < n_changed) for (uint32_t u = 0u; u < flip; u++) sym[u] = (uint8_t)(base + 1u);
        ids[i] = i;
        pack_quant(sym, 16u, 3u, rows + i * bpv, bpv);
    }
    semq_encoding_t* e = create_u64(&c, ids, n, rows, NULL, 0u);
    free(ids);
    free(rows);
    return e;
}

/* The 100-row null base of rows_with_changes(n, 0, 0, 4) with one manifest pair. */
static semq_encoding_t* rows_with_manifest(uint64_t n, const char* key, const char* value) {
    semq_config_t c;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_config_quant(16u, 4u, &c, NULL));
    const uint32_t bpv = semq_config_bytes_per_vector(&c);
    uint64_t* ids = (uint64_t*)malloc((size_t)n * sizeof(uint64_t));
    uint8_t* rows = (uint8_t*)malloc((size_t)n * bpv);
    TEST_ASSERT_NOT_NULL(ids);
    TEST_ASSERT_NOT_NULL(rows);
    for (uint64_t i = 0u; i < n; i++) {
        uint8_t sym[16];
        for (uint32_t u = 0u; u < 16u; u++) sym[u] = 4u;
        ids[i] = i;
        pack_quant(sym, 16u, 3u, rows + i * bpv, bpv);
    }
    semq_pair_t man[1] = { { (const uint8_t*)key, (uint32_t)strlen(key), (const uint8_t*)value, (uint32_t)strlen(value) } };
    semq_encoding_t* e = create_u64(&c, ids, n, rows, man, 1u);
    free(ids);
    free(rows);
    return e;
}

/* A floor with the given counts, bound to the reference of `d`. */
static semq_floor_t* floor_for(const semq_diff_t* d, uint64_t nulls, uint64_t changed, uint64_t total, uint64_t hamming) {
    uint8_t rid[32];
    semq_diff_reference_id(d, rid);
    semq_floor_t* f = NULL;
    semq_error_t err;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_floor_create(semq_diff_config(d), semq_diff_id_kind(d), rid, nulls,
                                                     changed, total, hamming, &f, &err));
    return f;
}

static void test_floor_measure_and_within(void) {
    /* Null A: 100 rows, 1 changed by 1 unit. Null A2: 100 rows, 2 changed by 1 unit.
     * Null B: 1 row changed by 10 units, against a different reference. */
    semq_encoding_t* a0 = rows_with_changes(100u, 0u, 0u, 4u);
    semq_encoding_t* a1 = rows_with_changes(100u, 1u, 1u, 4u);
    semq_encoding_t* a2 = rows_with_changes(100u, 2u, 1u, 4u);
    semq_encoding_t* b0 = rows_with_changes(1u, 0u, 0u, 4u);
    semq_encoding_t* b1 = rows_with_changes(1u, 1u, 10u, 4u);
    semq_diff_t* da = NULL; semq_diff_t* da2 = NULL; semq_diff_t* db = NULL;
    semq_error_t err;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_encoding_diff(a0, a1, &da, &err));
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_encoding_diff(a0, a2, &da2, &err));
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_encoding_diff(b0, b1, &db, &err));
    TEST_ASSERT_EQUAL_UINT64(1u, semq_diff_count(da, SEMQ_LIST_CHANGED));
    TEST_ASSERT_EQUAL_UINT64(99u, semq_diff_n_unchanged(da));
    /* Two nulls of the same reference: the worst ratio and the max p99. */
    const semq_diff_t* nulls[2] = { da, da2 };
    semq_floor_t* f = NULL;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_floor_measure(nulls, 2u, &f, &err));
    TEST_ASSERT_EQUAL_UINT64(2u, semq_floor_changed_rows(f));
    TEST_ASSERT_EQUAL_UINT64(100u, semq_floor_total_rows(f));
    TEST_ASSERT_EQUAL_UINT64(1u, semq_floor_hamming(f));
    TEST_ASSERT_EQUAL_UINT64(2u, semq_floor_nulls(f));
    TEST_ASSERT_EQUAL_UINT32(SEMQ_ID_U64, semq_floor_id_kind(f));
    TEST_ASSERT_TRUE(semq_config_equal(semq_floor_config(f), semq_diff_config(da)));
    uint8_t rid[32], fid[32];
    semq_diff_reference_id(da, rid);
    semq_floor_reference_id(f, fid);
    TEST_ASSERT_EQUAL_MEMORY(rid, fid, 32u);
    int w = 0;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_diff_within(da, f, &w, &err));
    TEST_ASSERT_TRUE(w);
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_diff_within(da2, f, &w, &err));
    TEST_ASSERT_TRUE(w);
    /* A floor of another reference is incompatible, in measure and in within. */
    const semq_diff_t* mixed[2] = { da, db };
    semq_floor_t* none = NULL;
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INCOMPATIBLE, semq_floor_measure(mixed, 2u, &none, &err));
    TEST_ASSERT_EQUAL_UINT64(1u, err.field);
    TEST_ASSERT_NULL(none);
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INCOMPATIBLE, semq_diff_within(db, f, &w, &err));
    semq_floor_free(f);
    /* A alone: floor (1, 100, 1); A2 exceeds the ratio at the exact boundary. */
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_floor_measure(nulls, 1u, &f, &err));
    TEST_ASSERT_EQUAL_UINT64(1u, semq_floor_changed_rows(f));
    TEST_ASSERT_EQUAL_UINT64(100u, semq_floor_total_rows(f));
    TEST_ASSERT_EQUAL_UINT64(1u, semq_floor_nulls(f));
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_diff_within(da2, f, &w, &err));
    TEST_ASSERT_FALSE(w);
    semq_floor_free(f);
    f = floor_for(da, 1u, 2u, 100u, 1u);
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_diff_within(da2, f, &w, &err));
    TEST_ASSERT_TRUE(w);
    /* Another config or id kind is incompatible even with the same reference id. */
    semq_config_t other;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_config_orbit(16u, 50u, &other, NULL));
    semq_floor_t* fo = NULL;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_floor_create(&other, SEMQ_ID_U64, rid, 1u, 2u, 100u, 1u, &fo, &err));
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INCOMPATIBLE, semq_diff_within(da2, fo, &w, &err));
    semq_floor_free(fo);
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_floor_create(semq_diff_config(da), SEMQ_ID_UTF8, rid, 1u, 2u, 100u, 1u, &fo, &err));
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INCOMPATIBLE, semq_diff_within(da2, fo, &w, &err));
    semq_floor_free(fo);
    /* A change to a reserved manifest key is never within, even with no row changes. */
    semq_encoding_t* a0m = rows_with_manifest(100u, "encoder", "other");
    semq_diff_t* dm = NULL;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_encoding_diff(a0, a0m, &dm, &err));
    TEST_ASSERT_EQUAL_UINT64(0u, semq_diff_count(dm, SEMQ_LIST_CHANGED));
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_diff_within(dm, f, &w, &err));
    TEST_ASSERT_FALSE(w);
    const semq_diff_t* bad_null[1] = { dm };
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INVALID_INPUT, semq_floor_measure(bad_null, 1u, &none, &err));
    semq_diff_free(dm);
    semq_encoding_free(a0m);
    /* n_common = 0 never passes; an empty candidate is not a rebuild. */
    semq_config_t c;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_config_quant(16u, 4u, &c, NULL));
    semq_encoding_t* empty = create_u64(&c, NULL, 0u, NULL, NULL, 0u);
    semq_diff_t* de = NULL;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_encoding_diff(empty, empty, &de, &err));
    semq_floor_t* fe = floor_for(de, 1u, 1u, 1u, 16u);
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_diff_within(de, fe, &w, &err));
    TEST_ASSERT_FALSE(w);
    semq_floor_free(fe);
    /* Invalid floors are rejected at creation; invalid nulls at measure. */
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INVALID_INPUT, semq_floor_create(&c, SEMQ_ID_U64, rid, 1u, 5u, 4u, 1u, &none, &err));
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INVALID_INPUT, semq_floor_create(&c, SEMQ_ID_U64, rid, 1u, 0u, 0u, 1u, &none, &err));
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INVALID_INPUT, semq_floor_create(&c, SEMQ_ID_U64, rid, 1u, 1u, 1u, 17u, &none, &err));
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INVALID_INPUT, semq_floor_create(&c, SEMQ_ID_U64, rid, 0u, 1u, 1u, 1u, &none, &err));
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INVALID_INPUT, semq_floor_create(&c, 2u, rid, 1u, 1u, 1u, 1u, &none, &err));
    TEST_ASSERT_NULL(none);
    const semq_diff_t* with_empty[1] = { de };
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INVALID_INPUT, semq_floor_measure(with_empty, 1u, &none, &err));
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INVALID_INPUT, semq_floor_measure(nulls, 0u, &none, &err));
    semq_floor_free(f);
    semq_diff_free(de);
    semq_diff_free(da2);
    semq_diff_free(da);
    semq_diff_free(db);
    semq_encoding_free(empty);
    semq_encoding_free(a2);
    semq_encoding_free(a0);
    semq_encoding_free(a1);
    semq_encoding_free(b0);
    semq_encoding_free(b1);
}

static void test_p99_nearest_rank(void) {
    /* 101 changed rows with hammings 1..101: k = 101 - 1 = 100 -> value 100. */
    semq_config_t c;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_config_quant(128u, 4u, &c, NULL));
    const uint32_t bpv = semq_config_bytes_per_vector(&c);  /* 48 */
    const uint64_t n = 101u;
    uint64_t ids[101];
    uint8_t* base = (uint8_t*)calloc((size_t)n, bpv);
    uint8_t* cand = (uint8_t*)calloc((size_t)n, bpv);
    TEST_ASSERT_NOT_NULL(base);
    TEST_ASSERT_NOT_NULL(cand);
    for (uint64_t i = 0u; i < n; i++) {
        uint8_t sym[128];
        memset(sym, 4, sizeof(sym));
        ids[i] = i;
        pack_quant(sym, 128u, 3u, base + i * bpv, bpv);
        for (uint32_t u = 0u; u < (uint32_t)i + 1u; u++) sym[u] = 5u;  /* hamming i + 1 */
        pack_quant(sym, 128u, 3u, cand + i * bpv, bpv);
    }
    semq_encoding_t* a = create_u64(&c, ids, n, base, NULL, 0u);
    semq_encoding_t* b = create_u64(&c, ids, n, cand, NULL, 0u);
    semq_diff_t* d = NULL;
    semq_error_t err;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_encoding_diff(a, b, &d, &err));
    const semq_diff_t* nulls[1] = { d };
    semq_floor_t* f = NULL;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_floor_measure(nulls, 1u, &f, &err));
    TEST_ASSERT_EQUAL_UINT64(100u, semq_floor_hamming(f));
    TEST_ASSERT_EQUAL_UINT64(101u, semq_floor_changed_rows(f));
    TEST_ASSERT_EQUAL_UINT64(101u, semq_floor_total_rows(f));
    semq_floor_free(f);
    semq_diff_free(d);
    semq_encoding_free(a);
    semq_encoding_free(b);
    free(base);
    free(cand);
}

/* An encoding of n rows of quant(128, 4) where row i flips `flips[i]` units. */
static semq_encoding_t* rows_flipped(uint64_t n, const uint32_t* flips) {
    semq_config_t c;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_config_quant(128u, 4u, &c, NULL));
    const uint32_t bpv = semq_config_bytes_per_vector(&c);
    uint64_t* ids = (uint64_t*)malloc((size_t)n * sizeof(uint64_t));
    uint8_t* rows = (uint8_t*)calloc((size_t)n, bpv);
    TEST_ASSERT_NOT_NULL(ids);
    TEST_ASSERT_NOT_NULL(rows);
    for (uint64_t i = 0u; i < n; i++) {
        uint8_t sym[128];
        memset(sym, 4, sizeof(sym));
        for (uint32_t u = 0u; flips != NULL && u < flips[i]; u++) sym[u] = 5u;
        ids[i] = i;
        pack_quant(sym, 128u, 3u, rows + i * bpv, bpv);
    }
    semq_encoding_t* e = create_u64(&c, ids, n, rows, NULL, 0u);
    free(ids);
    free(rows);
    return e;
}

static void test_evaluate_per_row(void) {
    /* Null: rows 0..99 of 200 change by 2 units. Candidate: rows 0..98 change
     * by 2 and row 150 by 90. The candidate's p99 ignores its one most-changed
     * row, so it is within; the per-row check flags row 150. */
    uint32_t null_flips[200] = { 0 }, cand_flips[200] = { 0 };
    for (uint32_t i = 0u; i < 100u; i++) null_flips[i] = 2u;
    for (uint32_t i = 0u; i < 99u; i++) cand_flips[i] = 2u;
    cand_flips[150] = 90u;
    semq_encoding_t* ref = rows_flipped(200u, NULL);
    semq_encoding_t* nul = rows_flipped(200u, null_flips);
    semq_encoding_t* cand = rows_flipped(200u, cand_flips);
    semq_diff_t* dn = NULL; semq_diff_t* dc = NULL;
    semq_error_t err;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_encoding_diff(ref, nul, &dn, &err));
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_encoding_diff(ref, cand, &dc, &err));
    const semq_diff_t* nulls[1] = { dn };
    semq_floor_t* f = NULL;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_floor_measure(nulls, 1u, &f, &err));
    TEST_ASSERT_EQUAL_UINT64(2u, semq_floor_hamming(f));
    TEST_ASSERT_EQUAL_UINT64(2u, semq_floor_max_hamming(f));

    int w = 0;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_diff_within(dc, f, &w, &err));
    TEST_ASSERT_TRUE(w);
    /* No options: the same verdict as within, and no rows. */
    semq_verdict_t* v = NULL;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_diff_evaluate(dc, f, NULL, &v, &err));
    TEST_ASSERT_TRUE(semq_verdict_passed(v));
    TEST_ASSERT_EQUAL_UINT32(0u, semq_verdict_reasons(v));
    TEST_ASSERT_EQUAL_UINT64(0u, semq_verdict_row_count(v));
    semq_verdict_free(v);
    /* Per-row: fails on row 150, the 100th changed row in canonical order. */
    semq_gate_options_t* o = NULL;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_gate_options_create(&o, &err));
    semq_gate_options_set_per_row(o, 1);
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_diff_evaluate(dc, f, o, &v, &err));
    TEST_ASSERT_FALSE(semq_verdict_passed(v));
    TEST_ASSERT_EQUAL_UINT32((uint32_t)SEMQ_REASON_ROW_ABOVE_MAX, semq_verdict_reasons(v));
    TEST_ASSERT_EQUAL_UINT64(1u, semq_verdict_row_count(v));
    TEST_ASSERT_EQUAL_UINT64(99u, semq_verdict_row(v, 0u));
    TEST_ASSERT_EQUAL_UINT64(SEMQ_NONE, semq_verdict_row(v, 1u));
    uint64_t id = 0u;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_diff_id(dc, SEMQ_LIST_CHANGED, 99u, &id, NULL, NULL, &err));
    TEST_ASSERT_EQUAL_UINT64(150u, id);
    semq_verdict_free(v);
    /* Every null is within its floor under the per-row check too. */
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_diff_evaluate(dn, f, o, &v, &err));
    TEST_ASSERT_TRUE(semq_verdict_passed(v));
    semq_verdict_free(v);

    /* A floor without max_hamming (semq-floor/1) refuses the per-row check
     * and keeps its verdicts otherwise. */
    uint8_t rid[32];
    semq_diff_reference_id(dc, rid);
    semq_floor_t* f1 = NULL;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_floor_create(semq_diff_config(dc), SEMQ_ID_U64, rid, 1u, 100u, 200u, 2u, &f1, &err));
    TEST_ASSERT_EQUAL_UINT64(SEMQ_NONE, semq_floor_max_hamming(f1));
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INCOMPATIBLE, semq_diff_evaluate(dc, f1, o, &v, &err));
    TEST_ASSERT_NULL(v);
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_diff_evaluate(dc, f1, NULL, &v, &err));
    TEST_ASSERT_TRUE(semq_verdict_passed(v));
    semq_verdict_free(v);

    /* Every failed check is reported, not only the first. */
    semq_floor_t* tight = NULL;
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_floor_create_with_max(semq_diff_config(dc), SEMQ_ID_U64, rid, 1u, 1u, 200u, 1u, 1u, &tight, &err));
    TEST_ASSERT_EQUAL_INT(SEMQ_OK, semq_diff_evaluate(dc, tight, o, &v, &err));
    TEST_ASSERT_EQUAL_UINT32((uint32_t)(SEMQ_REASON_CHANGED_RATIO | SEMQ_REASON_HAMMING | SEMQ_REASON_ROW_ABOVE_MAX),
                             semq_verdict_reasons(v));
    TEST_ASSERT_EQUAL_UINT64(100u, semq_verdict_row_count(v));
    semq_verdict_free(v);
    semq_floor_free(tight);

    /* Construction rules of a floor with max_hamming. */
    semq_floor_t* none = NULL;
    const semq_config_t* c = semq_diff_config(dc);
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INVALID_INPUT, semq_floor_create_with_max(c, SEMQ_ID_U64, rid, 1u, 1u, 1u, 3u, 2u, &none, &err));
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INVALID_INPUT, semq_floor_create_with_max(c, SEMQ_ID_U64, rid, 1u, 1u, 1u, 3u, 129u, &none, &err));
    TEST_ASSERT_EQUAL_INT(SEMQ_ERR_INVALID_INPUT, semq_floor_create_with_max(c, SEMQ_ID_U64, rid, 1u, 1u, 1u, 3u, SEMQ_NONE, &none, &err));
    TEST_ASSERT_NULL(none);

    semq_gate_options_free(o);
    semq_floor_free(f1);
    semq_floor_free(f);
    semq_diff_free(dc);
    semq_diff_free(dn);
    semq_encoding_free(cand);
    semq_encoding_free(nul);
    semq_encoding_free(ref);
}

/* -------------------------------------------------------------------------- */
/*  Build info                                                                */
/* -------------------------------------------------------------------------- */

static void test_build_info(void) {
    TEST_ASSERT_TRUE(strlen(semq_core_version()) > 0u);
    TEST_ASSERT_TRUE(strlen(semq_build_id()) > 0u);
    TEST_ASSERT_TRUE(strlen(semq_backend_name(SEMQ_QUANT)) > 0u);
    TEST_ASSERT_EQUAL_STRING("none", semq_backend_name(9u));
    TEST_ASSERT_EQUAL_STRING("invalid_input", semq_status_name(SEMQ_ERR_INVALID_INPUT));
    TEST_ASSERT_EQUAL_STRING("unknown", semq_status_name(99u));
}

static void test_constructor_sizes_before_traversal(void) {
    semq_config_t cfg;
    semq_error_t err;
    semq_codec_t* codec = NULL;
    semq_encoding_t* out = NULL;
    const uint8_t row = 0u;
    const uint64_t id = 0u;
    const float vector = 1.0f;
    semq_ids_t ids = { SEMQ_ID_U64, UINT64_MAX, &id, NULL, NULL };
    TEST_ASSERT_EQUAL(SEMQ_OK, semq_config_quant(4u, 4u, &cfg, &err));
    TEST_ASSERT_EQUAL(SEMQ_ERR_NOMEM, semq_encoding_create(&cfg, &ids, &row, NULL, 0u, &out, &err));
    TEST_ASSERT_NULL(out);
    TEST_ASSERT_EQUAL(SEMQ_OK, semq_codec_create(&cfg, &codec, &err));
    TEST_ASSERT_EQUAL(SEMQ_ERR_NOMEM, semq_codec_encode(codec, &ids, &vector, NULL, 0u, &out, &err));
    TEST_ASSERT_NULL(out);
    semq_codec_free(codec);
    TEST_ASSERT_EQUAL(SEMQ_OK, semq_config_quant(1u, 4u, &cfg, &err));
    TEST_ASSERT_EQUAL(SEMQ_OK, semq_codec_create(&cfg, &codec, &err));
    ids.kind = SEMQ_ID_UTF8;
    ids.n = UINT64_MAX / 8u;
    ids.utf8_offsets = &id;
    ids.utf8_bytes = &row;
    TEST_ASSERT_EQUAL(SEMQ_ERR_NOMEM, semq_codec_encode(codec, &ids, &vector, NULL, 0u, &out, &err));
    TEST_ASSERT_NULL(out);
    semq_codec_free(codec);
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_constructor_sizes_before_traversal);
    RUN_TEST(test_sha256_fips_vectors);
    RUN_TEST(test_config_canonical_form);
    RUN_TEST(test_config_derived_quantities);
    RUN_TEST(test_config_rejects);
    RUN_TEST(test_empty_encoding_identities_and_image);
    RUN_TEST(test_one_row_identities);
    RUN_TEST(test_constructor_rejects_non_canonical_rows);
    RUN_TEST(test_encode_sorts_ids_and_maps_symbols);
    RUN_TEST(test_encode_three_operators_round_trip_symbols);
    RUN_TEST(test_phase_polynomial_is_continuous_monotone_and_accurate);
    RUN_TEST(test_phase_sectors_are_monotone_across_the_diagonal_and_fixed_on_axes);
    RUN_TEST(test_encode_canonicalizes_subnormals);
    RUN_TEST(test_encode_rejects);
    RUN_TEST(test_codec_construction_requires_round_to_nearest);
    RUN_TEST(test_encode_requires_round_to_nearest);
    RUN_TEST(test_load_detects_corruption);
    RUN_TEST(test_utf8_ids_round_trip_and_order);
    RUN_TEST(test_concat_is_order_independent);
    RUN_TEST(test_diff_lists_units_and_manifest);
    RUN_TEST(test_floor_measure_and_within);
    RUN_TEST(test_p99_nearest_rank);
    RUN_TEST(test_evaluate_per_row);
    RUN_TEST(test_build_info);
    return UNITY_END();
}
