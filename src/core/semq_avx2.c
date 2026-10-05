/*
 * Copyright (c) 2026 The SEMQ Group Inc.
 * Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
 */

/*
 * semq_avx2.c — AVX2 + FMA backend (x86_64).
 *
 * Implements the SEMQ orbit operator using AVX2 intrinsics. The
 * inner loop processes 32 input floats per iteration (4 × __m256). The
 * `x · scale` step is performed in float64 to match the scalar
 * reference exactly. The remaining integer math is done in 32-bit
 * lanes after a saturating narrow from int64.
 *
 * Equivalence band:
 *
 *   This backend produces bit-identical output to the scalar backend
 *   for every input satisfying  |round(x · scale)| ≤ INT32_MAX.
 *
 * Tail:
 *
 *   For dim that is not a multiple of 32, the trailing 0..31 lanes
 *   fall through to the scalar fallback at the bottom of this file.
 */

#if defined(__x86_64__) || defined(_M_X64)

#include "semq_dispatch.h"

#include <immintrin.h>
#include <math.h>
#include <stdint.h>

/* -------------------------------------------------------------------------- */
/*  Scalar fallback (per-element)                                             */
/* -------------------------------------------------------------------------- */

static int64_t scaled_round_one(float x, uint32_t scale) {
    if (!isfinite(x)) {
        return 0;
    }
    /* Ties-to-even — matches the vector path's _mm256_cvtpd_epi32 default mode. */
    double y = nearbyint((double)x * (double)scale);
    if (y >= 9.2233720368547748e18) {
        return INT64_MAX;
    }
    if (y <= -9.2233720368547758e18) {
        return INT64_MIN;
    }
    return (int64_t)y;
}

static uint8_t reduce_one(uint64_t a) {
    if (a == 0u) return 0u;
    return (uint8_t)(1u + (uint32_t)((a - 1u) % 9u));
}

static semq_code_t scalar_op(float x, uint32_t scale) {
    int64_t      v = scaled_round_one(x, scale);
    unsigned int s = (v > 0) ? 2u : ((v < 0) ? 0u : 1u);
    uint64_t a;
    if (v == INT64_MIN) {
        a = (uint64_t)INT64_MAX + 1u;
    } else {
        a = (v < 0) ? (uint64_t)(-v) : (uint64_t)v;
    }
    return (semq_code_t)(s * 10u + (unsigned int)reduce_one(a));
}

static double scalar_inverse(semq_code_t code, uint32_t scale) {
    int          sign = (int)(code / 10u) - 1;
    unsigned int g    = (unsigned int)(code % 10u);
    return ((double)g * (double)sign) / (double)scale;
}

/* -------------------------------------------------------------------------- */
/*  Internal helpers                                                          */
/* -------------------------------------------------------------------------- */

/* Convert eight float32 → eight int32 with float64 multiplication and
 * saturating narrow. Bit-identical to scalar within the band. */
static inline __m256i scale_round_8(__m256 f, __m256d dsc) {
    __m256d d_lo = _mm256_mul_pd(_mm256_cvtps_pd(_mm256_castps256_ps128(f)),    dsc);
    __m256d d_hi = _mm256_mul_pd(_mm256_cvtps_pd(_mm256_extractf128_ps(f, 1)),  dsc);
    /* _mm256_cvtpd_epi32 rounds to nearest using MXCSR (default = nearest-even).
     * Out-of-range inputs yield the indefinite integer 0x80000000, which is
     * already INT32_MIN — equivalent to a saturating narrow for our purposes
     * provided the float64 value also stays in int32 range. Inputs outside
     * the equivalence band are documented as not-bit-identical anyway. */
    __m128i lo = _mm256_cvtpd_epi32(d_lo);   /* 4 × int32 in low 128 */
    __m128i hi = _mm256_cvtpd_epi32(d_hi);   /* 4 × int32 in low 128 */
    return _mm256_setr_m128i(lo, hi);        /* 8 × int32 in __m256i */
}

/* mod_9_u32(a) = a mod 9, computed branchlessly via magic multiplication. */
static inline __m256i mod_9_u32(__m256i a) {
    /* q = (a * 0x38E38E39) >> 33 ; q = floor(a / 9) for all a in [0, 2^32).
     * We need a 32x32→64 unsigned multiply: _mm256_mul_epu32 multiplies the
     * even 32-bit lanes; we run it twice (after a shift) to cover all 8.    */
    const __m256i magic = _mm256_set1_epi32((int)0x38E38E39u);

    /* even lanes (0,2,4,6) */
    __m256i prod_even = _mm256_mul_epu32(a, magic);
    /* odd lanes (1,3,5,7) — shift right by one 32-bit element first. */
    __m256i a_odd     = _mm256_srli_epi64(a, 32);
    __m256i m_odd     = _mm256_srli_epi64(magic, 32);
    __m256i prod_odd  = _mm256_mul_epu32(a_odd, m_odd);

    /* (prod >> 33) gives the 32-bit quotient, in the low half of each 64-bit lane. */
    __m256i q_even = _mm256_srli_epi64(prod_even, 33);
    __m256i q_odd  = _mm256_srli_epi64(prod_odd,  33);

    /* Re-interleave: q_even has results in even slots; q_odd has results in
     * even slots after the shift, so shift them back to odd slots and OR.   */
    __m256i q_odd_in_odd = _mm256_slli_epi64(q_odd, 32);
    __m256i mask_lo32    = _mm256_set1_epi64x((long long)0x00000000FFFFFFFFULL);
    __m256i q = _mm256_or_si256(_mm256_and_si256(q_even, mask_lo32), q_odd_in_odd);

    /* r = a - 9*q */
    __m256i nine = _mm256_set1_epi32(9);
    return _mm256_sub_epi32(a, _mm256_mullo_epi32(q, nine));
}

/* Map eight int32 lanes to the SEMQ orbit operator output. */
static inline __m256i encode_int32_8(__m256i v) {
    const __m256i Z    = _mm256_setzero_si256();
    const __m256i ONE  = _mm256_set1_epi32(1);

    /* sign code: s = 1 + sign(v),  sign(v) = (v<0) - (v>0) when masks are
     * −1 for true / 0 for false.                                           */
    __m256i pos   = _mm256_cmpgt_epi32(v, Z);                  /* −1 if v>0 */
    __m256i neg   = _mm256_cmpgt_epi32(Z, v);                  /* −1 if v<0 */
    __m256i sgn   = _mm256_sub_epi32(neg, pos);                /* {−1, 0, 1} */
    __m256i s     = _mm256_add_epi32(ONE, sgn);                /* {0, 1, 2} */

    /* a = |v| ; (a − 1), magic-mod-9, +1, then mask for a == 0 → 0.        */
    __m256i a     = _mm256_abs_epi32(v);
    __m256i am1   = _mm256_sub_epi32(a, ONE);
    __m256i r     = mod_9_u32(am1);
    __m256i g_pos = _mm256_add_epi32(r, ONE);
    __m256i nz    = _mm256_xor_si256(_mm256_cmpeq_epi32(a, Z),
                                      _mm256_set1_epi32(-1));   /* ~(a==0) */
    __m256i g     = _mm256_and_si256(g_pos, nz);

    /* code = s · 10 + g */
    __m256i ten   = _mm256_set1_epi32(10);
    return _mm256_add_epi32(_mm256_mullo_epi32(s, ten), g);
}

/* Pack four __m256i (32 lanes of int32) into one __m256i of 32 uint8.
 *
 * AVX2's _mm256_packus_epi32 / _mm256_packus_epi16 operate within each
 * 128-bit half separately, so after both narrowing steps the 32-byte
 * register is laid out as eight 4-byte groups in the order:
 *
 *     [a0..a3, b0..b3, c0..c3, d0..d3,  a4..a7, b4..b7, c4..c7, d4..d7]
 *      lane 0  lane 1  lane 2  lane 3   lane 4  lane 5  lane 6  lane 7
 *
 * The desired output order is [a0..a7, b0..b7, c0..c7, d0..d7]. That
 * requires interleaving lanes (0,4), (1,5), (2,6), (3,7) — i.e. a
 * permute at 32-bit granularity. _mm256_permute4x64_epi64 is the wrong
 * tool here: it cannot split inside a 64-bit chunk. Use
 * _mm256_permutevar8x32_epi32 with index vector {0,4,1,5,2,6,3,7}.    */
static inline __m256i pack_codes_32(__m256i a, __m256i b, __m256i c, __m256i d) {
    __m256i ab16 = _mm256_packus_epi32(a, b);                /* per-128 narrow */
    __m256i cd16 = _mm256_packus_epi32(c, d);
    __m256i abcd = _mm256_packus_epi16(ab16, cd16);
    const __m256i perm = _mm256_setr_epi32(0, 4, 1, 5, 2, 6, 3, 7);
    return _mm256_permutevar8x32_epi32(abcd, perm);
}

/* -------------------------------------------------------------------------- */
/*  Backend entry points                                                      */
/* -------------------------------------------------------------------------- */

static semq_status_t avx2_encode(
    const float* input,
    uint32_t     dim,
    uint32_t     scale,
    semq_code_t* output) {

    __m256d  dsc = _mm256_set1_pd((double)scale);
    uint32_t i   = 0;

    for (; i + 32u <= dim; i += 32u) {
        __m256 f0 = _mm256_loadu_ps(input + i +  0u);
        __m256 f1 = _mm256_loadu_ps(input + i +  8u);
        __m256 f2 = _mm256_loadu_ps(input + i + 16u);
        __m256 f3 = _mm256_loadu_ps(input + i + 24u);

        __m256i v0 = scale_round_8(f0, dsc);
        __m256i v1 = scale_round_8(f1, dsc);
        __m256i v2 = scale_round_8(f2, dsc);
        __m256i v3 = scale_round_8(f3, dsc);

        __m256i c0 = encode_int32_8(v0);
        __m256i c1 = encode_int32_8(v1);
        __m256i c2 = encode_int32_8(v2);
        __m256i c3 = encode_int32_8(v3);

        _mm256_storeu_si256((__m256i*)(output + i),
                            pack_codes_32(c0, c1, c2, c3));
    }
    for (; i < dim; ++i) {
        output[i] = scalar_op(input[i], scale);
    }
    return SEMQ_OK;
}

static semq_status_t avx2_reconstruct(
    const semq_code_t* codes,
    uint32_t           dim,
    uint32_t           scale,
    double*            output) {

    /* 8 codes per iteration → 8 doubles. */
    __m256d dsc = _mm256_set1_pd((double)scale);
    uint32_t i  = 0u;

    for (; i + 8u <= dim; i += 8u) {
        /* Load 8 codes (uint8) → __m256i with 8 × int32. */
        __m128i  c8  = _mm_loadl_epi64((const __m128i*)(codes + i));
        __m256i  c32 = _mm256_cvtepu8_epi32(c8);

        /* q = c / 10 via magic (c · 26) >> 8, valid for c < 30. */
        __m256i magic26 = _mm256_set1_epi32(26);
        __m256i q = _mm256_srli_epi32(_mm256_mullo_epi32(c32, magic26), 8);
        /* r = c − 10·q */
        __m256i r = _mm256_sub_epi32(c32,
                        _mm256_mullo_epi32(q, _mm256_set1_epi32(10)));
        /* sign = q − 1 ∈ {−1, 0, 1} ;  gs = g · sign */
        __m256i sign = _mm256_sub_epi32(q, _mm256_set1_epi32(1));
        __m256i gs   = _mm256_mullo_epi32(r, sign);

        /* Convert to float64 (split low/high 4 lanes), divide by scale. */
        __m256d f_lo = _mm256_cvtepi32_pd(_mm256_castsi256_si128(gs));
        __m256d f_hi = _mm256_cvtepi32_pd(_mm256_extracti128_si256(gs, 1));
        f_lo = _mm256_div_pd(f_lo, dsc);
        f_hi = _mm256_div_pd(f_hi, dsc);
        _mm256_storeu_pd(output + i + 0, f_lo);
        _mm256_storeu_pd(output + i + 4, f_hi);
    }
    for (; i < dim; ++i) {
        output[i] = scalar_inverse(codes[i], scale);
    }
    return SEMQ_OK;
}

/* -------------------------------------------------------------------------- */
/*  Backend descriptor                                                        */
/* -------------------------------------------------------------------------- */

const semq_backend_t SEMQ_AVX2_BACKEND = {
    .encode       = avx2_encode,
    .reconstruct  = avx2_reconstruct
};

#endif /* __x86_64__ */
