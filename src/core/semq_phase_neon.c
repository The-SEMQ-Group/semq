/*
 * Copyright (c) 2026 The SEMQ Group Inc.
 * Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
 */

/*
 * semq_phase_neon.c — NEON backend for the SEMQ phase operator.
 *
 * Vectorises the polynomial atan2 from semq_phase_atan2.h using
 * float64x2_t (two doubles per lane). Bit-identical to scalar by
 * construction:
 *
 *   - Every float64 operation is IEEE-754 compliant on ARMv8 NEON,
 *     matching scalar double semantics lane-for-lane.
 *   - The polynomial uses vfmaq_f64 — the same single-rounding FMA
 *     the scalar path now uses via fma() (see semq_phase_atan2.h).
 *   - Branches are replaced with vbslq_f64 / vbslq_s64 selects, so
 *     the chosen lane carries the same numeric value the scalar
 *     branch would have produced.
 *
 * Inner-loop layout: 4 pairs per iteration. One float32x4x2 load
 * (vld2q_f32) deinterleaves 4 (x, y) pairs into xs and ys vectors;
 * each is widened to two float64x2_t (low + high halves); two
 * atan2 calls produce 4 angles; sector binning + packing finalises
 * 4 output codes (or 2 packed bytes).
 *
 * Tail (pairs not divisible by 4) falls through to the per-pair
 * scalar path at the bottom of this file.
 */

#if defined(__aarch64__) || defined(_M_ARM64)

#include "semq_dispatch.h"
#include "semq_phase_atan2.h"

#include <arm_neon.h>
#include <stddef.h>
#include <stdint.h>

/* -------------------------------------------------------------------------- */
/*  Per-pair scalar fallback used for tail and small dims.                    */
/*  semq_phase_sector() lives in semq_phase_atan2.h.                          */
/* -------------------------------------------------------------------------- */

/* -------------------------------------------------------------------------- */
/*  Vectorised polynomial atan2                                               */
/* -------------------------------------------------------------------------- */

static inline float64x2_t neon_atan_poly_unit_v2(float64x2_t t) {
    const float64x2_t c1 = vdupq_n_f64(SEMQ_PHASE_C1);
    const float64x2_t c3 = vdupq_n_f64(SEMQ_PHASE_C3);
    const float64x2_t c5 = vdupq_n_f64(SEMQ_PHASE_C5);
    const float64x2_t t2 = vmulq_f64(t, t);
    /* r = C5;  r = r·t² + C3;  r = r·t² + C1;  return r·t.
     * Each line is one vfmaq_f64, i.e. a single-rounding FMA — exactly
     * what the scalar path emits via fma(). */
    float64x2_t r = c5;
    r = vfmaq_f64(c3, r, t2);
    r = vfmaq_f64(c1, r, t2);
    return vmulq_f64(r, t);
}

/* atan2 for two (y, x) double-precision pairs. Returns the two angles
 * in (−π, π], bit-identical to two scalar semq_phase_atan2_ref calls. */
static inline float64x2_t neon_atan2_v2(float64x2_t y, float64x2_t x) {
    const float64x2_t zero = vdupq_n_f64(0.0);
    const float64x2_t one  = vdupq_n_f64(1.0);
    const float64x2_t pi   = vdupq_n_f64(SEMQ_PI);
    const float64x2_t pih  = vdupq_n_f64(SEMQ_PI_HALF);

    const float64x2_t ax = vabsq_f64(x);
    const float64x2_t ay = vabsq_f64(y);

    /* mask: ax >= ay → use t = ay/ax with base = 0 (or π).
     *       else      → use t = ax/ay with base = π/2 − atan(t). */
    const uint64x2_t use_x = vcgeq_f64(ax, ay);

    /* "Safe" divisions: ensure no NaN/Inf can poison the unused branch.
     * Replace a zero denominator with 1.0 — the both_zero mask at the
     * end overwrites the corresponding output with 0 anyway. */
    const uint64x2_t ax_zero = vceqq_f64(ax, zero);
    const uint64x2_t ay_zero = vceqq_f64(ay, zero);
    const float64x2_t denom_x = vbslq_f64(ax_zero, one, ax);
    const float64x2_t denom_y = vbslq_f64(ay_zero, one, ay);

    const float64x2_t t1 = vdivq_f64(ay, denom_x);  /* ax >= ay branch */
    const float64x2_t t2 = vdivq_f64(ax, denom_y);  /* ay >  ax branch */

    const float64x2_t theta1 = neon_atan_poly_unit_v2(t1);
    const float64x2_t theta2 = vsubq_f64(pih, neon_atan_poly_unit_v2(t2));

    float64x2_t theta = vbslq_f64(use_x, theta1, theta2);

    /* x < 0  → theta = π − theta. */
    const uint64x2_t x_neg = vcltq_f64(x, zero);
    theta = vbslq_f64(x_neg, vsubq_f64(pi, theta), theta);

    /* y < 0  → theta = −theta. */
    const uint64x2_t y_neg = vcltq_f64(y, zero);
    theta = vbslq_f64(y_neg, vnegq_f64(theta), theta);

    /* x == 0 && y == 0  → return 0. */
    const uint64x2_t both_zero = vandq_u64(ax_zero, ay_zero);
    theta = vbslq_f64(both_zero, zero, theta);

    return theta;
}

/* Bin two angles into sector indices in [0, n_bins).
 *
 * sector = floor((θ + π) · n_bins / (2π))   clamped to [0, n_bins-1]
 *
 * Bit-identical to semq_phase_sector(): vmulq + vaddq + vcvtq_s64_f64
 * (rounding toward zero, same as (int64_t)). */
static inline int64x2_t neon_sector_v2(
    float64x2_t theta, uint32_t n_bins) {

    const float64x2_t pi        = vdupq_n_f64(SEMQ_PI);
    const double      bin_scale = (double)n_bins / (2.0 * SEMQ_PI);
    const float64x2_t scale_v   = vdupq_n_f64(bin_scale);
    const float64x2_t zero      = vdupq_n_f64(0.0);
    const int64x2_t   max_idx   = vdupq_n_s64((int64_t)n_bins - 1);

    float64x2_t raw = vmulq_f64(vaddq_f64(theta, pi), scale_v);
    /* Clamp to >= 0 (matches scalar's `if (raw < 0.0) raw = 0.0`). */
    raw = vmaxq_f64(raw, zero);
    /* FCVTZS: truncate toward zero. Matches scalar (int64_t)raw. */
    int64x2_t s = vcvtq_s64_f64(raw);
    /* min(s, n_bins-1). */
    const uint64x2_t over = vcgtq_s64(s, max_idx);
    s = vbslq_s64(over, max_idx, s);
    return s;
}

/* -------------------------------------------------------------------------- */
/*  Output size — identical to scalar phase backend.                          */
/* -------------------------------------------------------------------------- */

static uint32_t neon_phase_output_size(
    uint32_t dim, uint32_t n_bins, uint32_t packed) {
    (void)n_bins;
    if (dim == 0u) return 0u;
    if ((dim & 1u) != 0u) return 0u;
    const uint32_t pairs = dim / 2u;
    if (packed != 0u) {
        if ((pairs & 1u) != 0u) return 0u;
        return pairs / 2u;
    }
    return pairs;
}

/* -------------------------------------------------------------------------- */
/*  Encode                                                                    */
/* -------------------------------------------------------------------------- */

static semq_status_t neon_phase_encode(
    const float* input,
    uint32_t     dim,
    uint32_t     n_bins,
    uint32_t     packed,
    semq_code_t* output) {

    if (neon_phase_output_size(dim, n_bins, packed) == 0u) {
        return SEMQ_ERR_INVALID_INPUT;
    }
    const uint32_t pairs = dim / 2u;

    uint32_t p = 0u;
    /* Vector body: 4 pairs (= 8 floats) per iteration. */
    for (; p + 4u <= pairs; p += 4u) {
        /* Deinterleaved load: xs = [x0,x1,x2,x3], ys = [y0,y1,y2,y3]. */
        const float32x4x2_t pair = vld2q_f32(input + (size_t)p * 2u);
        const float32x4_t xs_f = pair.val[0];
        const float32x4_t ys_f = pair.val[1];

        /* Widen each float32x4_t to two float64x2_t (low + high halves). */
        const float64x2_t xs_lo = vcvt_f64_f32(vget_low_f32(xs_f));
        const float64x2_t xs_hi = vcvt_high_f64_f32(xs_f);
        const float64x2_t ys_lo = vcvt_f64_f32(vget_low_f32(ys_f));
        const float64x2_t ys_hi = vcvt_high_f64_f32(ys_f);

        /* Two parallel atan2 calls → 4 angles. */
        const float64x2_t th_lo = neon_atan2_v2(ys_lo, xs_lo);
        const float64x2_t th_hi = neon_atan2_v2(ys_hi, xs_hi);

        /* Sector indices. */
        const int64x2_t s_lo = neon_sector_v2(th_lo, n_bins);
        const int64x2_t s_hi = neon_sector_v2(th_hi, n_bins);

        const uint8_t s0 = (uint8_t)vgetq_lane_s64(s_lo, 0);
        const uint8_t s1 = (uint8_t)vgetq_lane_s64(s_lo, 1);
        const uint8_t s2 = (uint8_t)vgetq_lane_s64(s_hi, 0);
        const uint8_t s3 = (uint8_t)vgetq_lane_s64(s_hi, 1);

        if (packed == 0u) {
            output[p + 0u] = s0;
            output[p + 1u] = s1;
            output[p + 2u] = s2;
            output[p + 3u] = s3;
        } else {
            output[(p + 0u) / 2u] = (semq_code_t)(s0 | (uint8_t)(s1 << 4u));
            output[(p + 2u) / 2u] = (semq_code_t)(s2 | (uint8_t)(s3 << 4u));
        }
    }

    /* Tail: any remaining pairs handled per-pair via the scalar reference. */
    if (packed == 0u) {
        for (; p < pairs; ++p) {
            output[p] = semq_phase_sector(
                input[(size_t)p * 2u + 1u],
                input[(size_t)p * 2u + 0u],
                n_bins);
        }
    } else {
        /* Packed tail always lands at a pair-pair boundary (pairs is
         * known divisible by 2 in packed mode); fall through similarly. */
        for (; p < pairs; p += 2u) {
            const uint8_t lo = semq_phase_sector(
                input[(size_t)p * 2u + 1u],
                input[(size_t)p * 2u + 0u],
                n_bins);
            const uint8_t hi = semq_phase_sector(
                input[(size_t)(p + 1u) * 2u + 1u],
                input[(size_t)(p + 1u) * 2u + 0u],
                n_bins);
            output[p / 2u] = (semq_code_t)(lo | (uint8_t)(hi << 4u));
        }
    }
    return SEMQ_OK;
}

/* -------------------------------------------------------------------------- */
/*  Reconstruct — delegated to scalar representatives (outside the bytes   */
/*  contract). The vectorised reconstruct can be added later if needed.       */
/* -------------------------------------------------------------------------- */

static semq_status_t neon_phase_reconstruct(
    const semq_code_t* codes,
    uint32_t           dim,
    uint32_t           n_bins,
    uint32_t           packed,
    double*            output) {
    return SEMQ_PHASE_SCALAR_BACKEND.reconstruct(
        codes, dim, n_bins, packed, output);
}

/* -------------------------------------------------------------------------- */
/*  Backend descriptor                                                        */
/* -------------------------------------------------------------------------- */

const semq_phase_backend_t SEMQ_PHASE_NEON_BACKEND = {
    .encode       = neon_phase_encode,
    .reconstruct  = neon_phase_reconstruct,
};

#endif /* __aarch64__ */
