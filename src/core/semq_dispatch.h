/*
 * Copyright (c) 2026 The SEMQ Group Inc.
 * Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
 */

/*
 * semq_dispatch.h — internal header.
 *
 * Defines the function pointer table that every SIMD backend implements
 * and the keys that identify each backend. This header is private to the
 * native core and is NEVER part of the public API surface.
 */

#ifndef SEMQ_DISPATCH_H
#define SEMQ_DISPATCH_H

#include <stdint.h>

#include "semq.h"

/** One packed code byte. */
typedef uint8_t semq_code_t;

#ifdef __cplusplus
extern "C" {
#endif

/** Backend identifier. Used to label the active backend. */
typedef enum {
    SEMQ_BACKEND_NONE   = 0,
    SEMQ_BACKEND_SCALAR = 1,
    SEMQ_BACKEND_AVX2   = 2,
    SEMQ_BACKEND_AVX512 = 3,
    SEMQ_BACKEND_NEON   = 4,
    SEMQ_BACKEND_SVE    = 5
} semq_backend_kind_t;

/**
 * Function pointer table for the SEMQ_ORBIT operator.
 * Filled in at the top of each backend's implementation file
 * (semq_scalar.c, semq_avx2.c, ...).
 */
typedef struct {
    semq_status_t (*encode)(
        const float* input,
        uint32_t     dim,
        uint32_t     scale,
        semq_code_t* output);

    semq_status_t (*reconstruct)(
        const semq_code_t* codes,
        uint32_t           dim,
        uint32_t           scale,
        double*            output);
} semq_backend_t;

/**
 * Function pointer table for the SEMQ_PHASE operator.
 *
 * The phase operator pairs consecutive dimensions and emits one
 * sector index per pair. With `packed != 0` two sectors are bit-packed
 * per output byte (low nibble = even pair, high nibble = odd pair).
 *
 * `dim` is always the input dimensionality; the byte count written
 * is derived from CodecConfig before calling the kernel.
 */
typedef struct {
    semq_status_t (*encode)(
        const float* input,
        uint32_t     dim,
        uint32_t     n_bins,
        uint32_t     packed,
        semq_code_t* output);

    semq_status_t (*reconstruct)(
        const semq_code_t* codes,
        uint32_t           dim,
        uint32_t           n_bins,
        uint32_t           packed,
        double*            output);

} semq_phase_backend_t;

/**
 * Function pointer table for SEMQ_QUANT.
 *
 * QUANT encodes per-dimension sign+magnitude bins with dense bit packing.
 * The `scale_max` parameter is the upper bound of the magnitude range
 * (the config's max_magnitude).
 *
 * Codes are bit-packed at ceil(log2(2 * n_bins)) bits per dimension;
 * see semq_quant_scalar.c for the layout convention.
 */
typedef struct {
    semq_status_t (*encode)(
        const float* input,
        uint32_t     dim,
        uint32_t     n_bins,
        float        scale_max,
        semq_code_t* output);

    semq_status_t (*reconstruct)(
        const semq_code_t* codes,
        uint32_t           dim,
        uint32_t           n_bins,
        float              scale_max,
        double*            output);

} semq_quant_backend_t;

/**
 * Internal helper exported from semq_quant_scalar.c: the bin index the QUANT
 * encoder assigns to a magnitude, clamp included. Shared by every backend so
 * the bin decision has one definition.
 */
uint32_t semq_quant_bin_of_magnitude(
    float    mag,
    float    scale_max,
    uint32_t n_bins);

/** Run CPU detection and return the best backend available on this host. */
semq_backend_kind_t semq_dispatch_select(void);

/** Select for an operator; quant prefers AVX2 when both x86 kernels exist. */
semq_backend_kind_t semq_dispatch_select_for(uint32_t op);

/** Whether ARMv8 SHA-256 instructions can execute on this host. */
int semq_dispatch_has_sha256(void);

/** Return the orbit vtable for a given backend kind, or NULL. */
const semq_backend_t* semq_dispatch_get(semq_backend_kind_t kind);

/** Return the phase vtable for a given backend kind, or NULL. */
const semq_phase_backend_t* semq_dispatch_get_phase(semq_backend_kind_t kind);

/** Return the QUANT vtable for a given backend kind, or NULL. */
const semq_quant_backend_t* semq_dispatch_get_quant(semq_backend_kind_t kind);

/** Return a static name for a backend kind. Always non-NULL. */
const char* semq_backend_kind_name(semq_backend_kind_t kind);

/* The scalar backend is always linked and always usable.
 * Other backends are conditionally compiled and may not exist. */
extern const semq_backend_t       SEMQ_SCALAR_BACKEND;
extern const semq_phase_backend_t SEMQ_PHASE_SCALAR_BACKEND;

/* The phase representative of one sector (see semq_phase_scalar.c). */
void semq_phase_representative(uint32_t n_bins, uint32_t sector, double out[2]);
extern const semq_quant_backend_t  SEMQ_QUANT_SCALAR_BACKEND;

#if defined(__aarch64__) || defined(_M_ARM64)
extern const semq_backend_t       SEMQ_NEON_BACKEND;
extern const semq_backend_t       SEMQ_SVE_BACKEND;
extern const semq_phase_backend_t SEMQ_PHASE_NEON_BACKEND;
extern const semq_quant_backend_t SEMQ_QUANT_NEON_BACKEND;
#endif

#if defined(__x86_64__) || defined(_M_X64)
extern const semq_backend_t SEMQ_AVX2_BACKEND;
extern const semq_backend_t SEMQ_AVX512_BACKEND;
extern const semq_quant_backend_t SEMQ_QUANT_AVX2_BACKEND;
extern const semq_quant_backend_t SEMQ_QUANT_AVX512_BACKEND;
/* Phase backends for x86 are added in subsequent phases. */
#endif

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* SEMQ_DISPATCH_H */
