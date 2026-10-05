/*
 * Copyright (c) 2026 The SEMQ Group Inc.
 * Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
 */

/*
 * semq_sve.c — SVE backend (ARM64 with FEAT_SVE).
 *
 * Implements the SEMQ orbit operator using base SVE intrinsics
 * (Armv8.2-A SVE; no SVE2 dependency). The backend is fully scalable —
 * a single loop with the svwhilelt_b32 predicate handles every dim
 * including dim < hardware vector width, with no separate scalar tail.
 *
 * The same source compiles for any SVE vector length the hardware
 * provides (128, 256, 512, 1024, or 2048 bits).
 *
 * Equivalence band:
 *
 *   Bit-identical output to scalar for every input satisfying
 *   |round(x · scale)| ≤ INT32_MAX.
 *
 *   Float64 multiplication of `x · scale` is preserved by widening
 *   each svfloat32_t into two svfloat64_t halves (svzip1 + svcvt_f64_x
 *   for the lower half; svzip2 + svcvt_f64_x for the upper half), which
 *   is the base-SVE equivalent of SVE2's svcvtlb / svcvtlt.
 *
 * Build / run:
 *
 *   Compiled into the dylib on every ARM64 host (Apple Silicon, Linux,
 *   Windows-ARM). On Apple Silicon (M-series), runtime detection
 *   reports no FEAT_SVE — the dispatcher routes to NEON automatically
 *   and this file is dead code on that platform. On Graviton 3 / 4,
 *   Neoverse V1 / V2, and similar SVE-capable cores, the dispatcher
 *   routes here.
 */

#if defined(__aarch64__) || defined(_M_ARM64)

#include "semq_dispatch.h"

#include <arm_sve.h>
#include <stddef.h>
#include <stdint.h>

/*
 * No scalar fallback in this file: the predicated SVE loop in every entry
 * point already handles dim ∈ [1, ∞) including dim < hardware vector width,
 * with no separate tail step required. The other backends (scalar, NEON,
 * AVX2, AVX-512) carry their own per-element fallbacks for their tail loops.
 */

/* -------------------------------------------------------------------------- */
/*  Internal helpers                                                          */
/* -------------------------------------------------------------------------- */

/* Widen the lower N/2 lanes of an svfloat32_t to svfloat64_t. Reads
 * f[0], f[1], ..., f[N/2 − 1] and produces N/2 doubles.
 *
 * Mechanism: svzip1(f, f) duplicates each of the lower N/2 lanes,
 * giving [f[0], f[0], f[1], f[1], …, f[N/2−1], f[N/2−1]]. svcvt_f64_x
 * then reads the bottom (even-indexed) element of every 64-bit pair,
 * yielding [(double)f[0], (double)f[1], …, (double)f[N/2−1]].         */
static inline svfloat64_t widen_lo_f32(svbool_t p64, svfloat32_t f) {
    return svcvt_f64_x(p64, svzip1_f32(f, f));
}

/* Widen the upper N/2 lanes of an svfloat32_t to svfloat64_t. Reads
 * f[N/2], f[N/2+1], …, f[N−1]. Mirror of widen_lo_f32 using svzip2.   */
static inline svfloat64_t widen_hi_f32(svbool_t p64, svfloat32_t f) {
    return svcvt_f64_x(p64, svzip2_f32(f, f));
}

/* Same widen idiom for int32 → float64 (used in reconstruct). */
static inline svfloat64_t widen_lo_s32(svbool_t p64, svint32_t v) {
    return svcvt_f64_x(p64, svzip1_s32(v, v));
}
static inline svfloat64_t widen_hi_s32(svbool_t p64, svint32_t v) {
    return svcvt_f64_x(p64, svzip2_s32(v, v));
}

/* Recombine two svint64_t halves into one svint32_t in original lane
 * order, after each int64 lane has been saturated to int32 range.
 *
 * Reinterpret each svint64_t as svint32_t — each int64 lane becomes
 * two int32 lanes [lo, hi]. After saturation the "hi" half is sign-
 * extension; the actual value sits in the even-indexed lanes of the
 * reinterpreted vector. svuzp1 takes even lanes from the concatenation
 * [r_lo; r_hi], which precisely re-interleaves the two halves into
 * original lane order [v[0], v[1], …, v[N−1]].                         */
static inline svint32_t pack_64_to_32(svbool_t p64, svint64_t lo, svint64_t hi) {
    /* Saturate each int64 to int32 range. */
    svint64_t imin = svdup_n_s64((int64_t)INT32_MIN);
    svint64_t imax = svdup_n_s64((int64_t)INT32_MAX);
    lo = svmax_s64_x(p64, svmin_s64_x(p64, lo, imax), imin);
    hi = svmax_s64_x(p64, svmin_s64_x(p64, hi, imax), imin);

    return svuzp1_s32(svreinterpret_s32_s64(lo),
                      svreinterpret_s32_s64(hi));
}

/* Convert svfloat32_t → svint32_t with float64 multiply by `scale` and
 * saturating narrow. Bit-identical to scalar within the equivalence band. */
static inline svint32_t scale_round_lane(
        svbool_t p32, svbool_t p64, svfloat32_t f, svfloat64_t dsc) {

    svfloat64_t d_lo = svmul_f64_x(p64, widen_lo_f32(p64, f), dsc);
    svfloat64_t d_hi = svmul_f64_x(p64, widen_hi_f32(p64, f), dsc);
    /* ACLE says svcvt_s64_f64_x uses the FPCR.RMode rounding mode, but
     * GCC and Clang emit FCVTZS (round-toward-zero) here to avoid the
     * dynamic FPCR read. That diverges from the scalar reference
     * (nearbyint, ties-to-even) and the NEON path (FCVTNS) whenever
     * x * scale lands exactly on a half-integer (and, because of
     * float32 rounding, on values like 0.02f*50 = 0.9999997 that should
     * round to 1). Force round-to-nearest-ties-to-even up-front via
     * FRINTN; the subsequent FCVTZS is then a no-op truncation of an
     * already-integer-valued float. Confirmed byte-identical to the
     * scalar reference on Graviton3 via the cross-arch differential
     * fuzz (tests/scale/test_simd_differential_fuzz.py). */
    d_lo = svrintn_f64_x(p64, d_lo);
    d_hi = svrintn_f64_x(p64, d_hi);
    svint64_t   v_lo = svcvt_s64_f64_x(p64, d_lo);
    svint64_t   v_hi = svcvt_s64_f64_x(p64, d_hi);
    (void)p32;
    return pack_64_to_32(p64, v_lo, v_hi);
}

/* mod_9_u32(a) = a mod 9, branchless via magic multiplication.
 *
 *   q = (a * 0x38E38E39) >> 33  for all a in [0, 2^32).
 *
 * svmulh_u32 returns the high 32 bits of the unsigned 32×32→64 product,
 * i.e. bits [32..63]. A further right-shift by 1 yields the (>> 33) result. */
static inline svuint32_t mod_9_u32(svbool_t p32, svuint32_t a) {
    svuint32_t high = svmulh_u32_x(p32, a, svdup_n_u32(0x38E38E39u));
    svuint32_t q    = svlsr_n_u32_x(p32, high, 1);
    return svmls_n_u32_x(p32, a, q, 9u);
}

/* Map active int32 lanes to the SEMQ orbit operator output, returning
 * the codes still as 32-bit values. The final saturating narrow-to-uint8
 * happens during the store (svst1b_u32). */
static inline svuint32_t encode_int32_lane(svbool_t p32, svint32_t v) {
    /* Sign code s ∈ {0, 1, 2}. Build by merging onto a starting vector of 1. */
    svbool_t pos = svcmpgt_n_s32(p32, v, 0);
    svbool_t neg = svcmplt_n_s32(p32, v, 0);
    svint32_t s  = svdup_n_s32(1);
    s = svadd_n_s32_m(pos, s, 1);   /* +1 where v > 0  → s = 2 */
    s = svsub_n_s32_m(neg, s, 1);   /* −1 where v < 0  → s = 0 */

    /* a = |v| ; (a − 1), magic-mod-9, +1, masked by (a != 0). */
    svuint32_t a   = svreinterpret_u32_s32(svabs_s32_x(p32, v));
    svuint32_t am1 = svsub_n_u32_x(p32, a, 1u);
    svuint32_t r   = mod_9_u32(p32, am1);
    svuint32_t g_p = svadd_n_u32_x(p32, r, 1u);

    svbool_t   nz_mask = svcmpne_n_u32(p32, a, 0u);
    svuint32_t g       = svsel_u32(nz_mask, g_p, svdup_n_u32(0u));

    /* code = s · 10 + g. */
    svuint32_t s_u = svreinterpret_u32_s32(s);
    return svmla_n_u32_x(p32, g, s_u, 10u);
}

/* -------------------------------------------------------------------------- */
/*  Backend entry points                                                      */
/* -------------------------------------------------------------------------- */

static semq_status_t sve_encode(
    const float* input,
    uint32_t     dim,
    uint32_t     scale,
    semq_code_t* output) {

    svfloat64_t dsc = svdup_n_f64((double)scale);
    svbool_t    p64 = svptrue_b64();
    uint64_t    n   = (uint64_t)dim;

    for (uint64_t i = 0; i < n; i += svcntw()) {
        svbool_t    p32 = svwhilelt_b32(i, n);
        svfloat32_t f   = svld1_f32(p32, input + i);

        svint32_t  v    = scale_round_lane(p32, p64, f, dsc);
        svuint32_t code = encode_int32_lane(p32, v);

        /* svst1b_u32 stores the bottom 8 bits of each active 32-bit lane
         * to consecutive bytes in `output + i`. Single instruction.       */
        svst1b_u32(p32, output + i, code);
    }
    return SEMQ_OK;
}

static semq_status_t sve_reconstruct(
    const semq_code_t* codes,
    uint32_t           dim,
    uint32_t           scale,
    double*            output) {

    svfloat64_t dsc = svdup_n_f64((double)scale);
    svbool_t    p64 = svptrue_b64();
    uint64_t    n   = (uint64_t)dim;

    for (uint64_t i = 0; i < n; i += svcntw()) {
        svbool_t  p32 = svwhilelt_b32(i, n);

        /* Load uint8 → int32 with widening load. */
        svint32_t c32 = svld1ub_s32(p32, codes + i);

        /* q = c / 10  via magic (c · 26) >> 8 ; valid for c ≤ 29.           */
        svint32_t q    = svasr_n_s32_x(p32,
                            svmul_n_s32_x(p32, c32, 26), 8);
        /* r = c − 10·q ; sign = q − 1 ∈ {−1, 0, 1} ; gs = r · sign.         */
        svint32_t r    = svmls_n_s32_x(p32, c32, q, 10);
        svint32_t sign = svsub_n_s32_x(p32, q, 1);
        svint32_t gs   = svmul_s32_x(p32, r, sign);

        /* Widen to float64 in two halves; divide by scale.                  */
        svfloat64_t f_lo = svdiv_f64_x(p64, widen_lo_s32(p64, gs), dsc);
        svfloat64_t f_hi = svdiv_f64_x(p64, widen_hi_s32(p64, gs), dsc);

        /* Store with separate predicates for the two halves.                */
        svbool_t p64_lo = svwhilelt_b64(i,             n);
        svbool_t p64_hi = svwhilelt_b64(i + svcntd(),  n);
        svst1_f64(p64_lo, output + i,             f_lo);
        svst1_f64(p64_hi, output + i + svcntd(),  f_hi);
    }
    return SEMQ_OK;
}

/* -------------------------------------------------------------------------- */
/*  Backend descriptor                                                        */
/* -------------------------------------------------------------------------- */

const semq_backend_t SEMQ_SVE_BACKEND = {
    .encode       = sve_encode,
    .reconstruct  = sve_reconstruct
};

#endif /* __aarch64__ */
