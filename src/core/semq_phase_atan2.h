/*
 * Copyright (c) 2026 The SEMQ Group Inc.
 * Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
 */

/*
 * semq_phase_atan2.h — internal polynomial atan2 reference.
 *
 * Defines the CANONICAL atan2 used by every SEMQ phase backend (scalar,
 * NEON, AVX2, AVX-512, SVE). All backends must produce bit-identical
 * float64 output for the same float32 inputs by implementing this exact
 * polynomial — not libc atan2, which differs across libm
 * implementations and therefore breaks cross-platform replay.
 *
 * Method:
 *   1. Reduce |x|, |y| → t in [0, 1]:
 *         t = ay/ax if ax >= ay, else t = ax/ay
 *   2. Approximate atan(t) with a 5th-degree odd polynomial constrained
 *      to p(1) = π/4, with a maximum absolute error of 7.04e-4 rad
 *      (0.04°) over [0, 1]. Computation is performed in float64
 *      with strictly left-to-right Horner evaluation to fix the
 *      rounding sequence on every backend.
 *   3. Reflect the first-octant result back via:
 *         θ = π/2 − atan(t)        if ay > ax
 *      then quadrant-correct using the signs of x and y.
 *
 * Result is in (−π, π]. (atan2(0, 0) returns 0 by convention.)
 *
 * Internal header — never part of the public API.
 */

#ifndef SEMQ_PHASE_ATAN2_H
#define SEMQ_PHASE_ATAN2_H

#include <math.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Canonical constants. Reproduced here as float64 literals so every
 * backend uses the same bit pattern (no compiler-derived M_PI quirks). */
#define SEMQ_PI       3.141592653589793238462643383279502884
#define SEMQ_PI_HALF  1.570796326794896619231321691639751442

/*
 * 5th-degree odd polynomial for atan(t) over t in [0, 1]:
 *   atan(t) ≈ c1*t + c3*t³ + c5*t⁵
 * The coefficients are the minimax (L∞) fit under the endpoint constraint
 * p(1) = π/4, so the two octants meet continuously at ax == ay and the
 * angle is monotone across the diagonal. The error has three interior
 * stationary points (t ≈ 0.2105, 0.6097, 0.9140) with |err| ≈ 7.037e-4 rad
 * (0.0403°) at each, and p'(t) ≥ 0.5188 on [0, 1]. The polynomial is the
 * rule: inputs near a sector boundary may land in the neighbouring sector
 * of the exact atan2, and every backend must reproduce these bits.
 *
 * Coefficients (float64 literals — bit pattern fixed):
 */
#define SEMQ_PHASE_C1   0.9947660466480732
#define SEMQ_PHASE_C3  (-0.28543420102605926)
#define SEMQ_PHASE_C5   0.07606631777543432

/*
 * atan(t) for t in [0, 1], evaluated with strict left-to-right Horner
 * via explicit `fma()` calls. Cross-backend bit-identity requires that
 * SIMD versions (which use VFMA / VFMADD intrinsics) round identically
 * to the scalar reference — that only holds if scalar uses a single
 * fused multiply-add at every step, not a separate mul+add the
 * compiler might or might not contract.
 *
 * Inputs outside [0, 1] yield undefined output (the dispatcher reduces
 * arguments to this range before calling).
 */
static inline double semq_phase_atan_poly_unit(double t) {
    const double t2 = t * t;
    double r = SEMQ_PHASE_C5;
    r = fma(r, t2, SEMQ_PHASE_C3);   /* r·t² + C3, single rounding */
    r = fma(r, t2, SEMQ_PHASE_C1);   /* r·t² + C1, single rounding */
    return r * t;
}

/*
 * atan2(y, x) returning the angle in (−π, π], deterministic across
 * architectures. Inputs are float32 (matching the encoder's input
 * type) but every operation is performed in float64.
 */
static inline double semq_phase_atan2_ref(float yf, float xf) {
    const double y = (double)yf;
    const double x = (double)xf;
    const double ax = (x < 0.0) ? -x : x;
    const double ay = (y < 0.0) ? -y : y;

    if (ax == 0.0 && ay == 0.0) {
        return 0.0;
    }

    /* First-octant magnitude. */
    double theta;
    if (ax >= ay) {
        theta = semq_phase_atan_poly_unit(ay / ax);
    } else {
        theta = SEMQ_PI_HALF - semq_phase_atan_poly_unit(ax / ay);
    }

    /* Quadrant correction. */
    if (x < 0.0) {
        theta = SEMQ_PI - theta;
    }
    if (y < 0.0) {
        theta = -theta;
    }
    return theta;
}

/*
 * Encode a single (x, y) pair into a sector index in [0, n_bins).
 * The +π boundary (x < 0, y = +0) is clamped to the final sector.
 *
 * sector = min(floor((θ + π) * n_bins / (2π)), n_bins - 1)
 */
static inline uint8_t semq_phase_sector(float yf, float xf, uint32_t n_bins) {
    const double theta = semq_phase_atan2_ref(yf, xf);
    const double scale = (double)n_bins / (2.0 * SEMQ_PI);
    /* (theta + π) is in [0, 2π]; scaled it is in [0, n_bins]. */
    double raw = (theta + SEMQ_PI) * scale;
    /* Clamp the rare +π input that maps to exactly n_bins. */
    if (raw < 0.0) {
        raw = 0.0;
    }
    int64_t s = (int64_t)raw;  /* truncation = floor for non-negative. */
    if (s >= (int64_t)n_bins) {
        s = (int64_t)n_bins - 1;
    }
    return (uint8_t)s;
}

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* SEMQ_PHASE_ATAN2_H */
