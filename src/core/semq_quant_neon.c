/*
 * Copyright (c) 2026 The SEMQ Group Inc.
 * Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
 */

/* Four independent binary32 bin decisions per iteration. Keep multiplication
 * and division as separate IEEE operations: replacing division by a
 * reciprocal multiplication changes symbols at bin boundaries. */

#if defined(__aarch64__) || defined(_M_ARM64)

#include "semq_dispatch.h"
#include "semq_bits.h"
#include "semq_quant_packing.h"

#include <arm_neon.h>
#include <math.h>
#include <string.h>

static semq_status_t quant_encode_neon(const float* input, uint32_t dim,
                                       uint32_t n_bins, float scale_max,
                                       semq_code_t* output) {
    if (n_bins < 2u || scale_max <= 0.0f) {
        return SEMQ_ERR_INVALID_INPUT;
    }

    const uint32_t bits = semq_bits_per_symbol_quant(n_bins);
    const uint32_t bytes = (uint32_t)(((uint64_t)dim * bits + 7u) / 8u);
    memset(output, 0, bytes);

    const float32x4_t zero = vdupq_n_f32(0.0f);
    const float32x4_t bins_f = vdupq_n_f32((float)n_bins);
    const float32x4_t max_f = vdupq_n_f32(scale_max);
    const uint32x4_t last_bin = vdupq_n_u32(n_bins - 1u);
    const uint32x4_t sign_value = vdupq_n_u32(n_bins);
    uint64_t pos = 0u;
    uint32_t i = 0u;
    for (; i + 4u <= dim; i += 4u) {
        const float32x4_t x = vld1q_f32(input + i);
        const float32x4_t magnitude = vabsq_f32(x);
        const float32x4_t product = vmulq_f32(magnitude, bins_f);
        const float32x4_t quotient = vdivq_f32(product, max_f);
        const uint32x4_t bin = vminq_u32(vcvtq_u32_f32(quotient), last_bin);
        const uint32x4_t negative = vcltq_f32(x, zero);
        const uint32x4_t symbol = vaddq_u32(bin, vbicq_u32(sign_value, negative));
        uint32_t lanes[4];
        vst1q_u32(lanes, symbol);
        for (uint32_t lane = 0u; lane < 4u; lane++) {
            semqi_quant_pack_symbol(output, &pos, lanes[lane], bits);
        }
    }
    for (; i < dim; i++) {
        const float x = input[i];
        const uint32_t bin = semq_quant_bin_of_magnitude(fabsf(x), scale_max, n_bins);
        const uint32_t symbol = bin + ((x < 0.0f) ? 0u : n_bins);
        semqi_quant_pack_symbol(output, &pos, symbol, bits);
    }
    return SEMQ_OK;
}

static semq_status_t quant_reconstruct_neon(const semq_code_t* codes,
                                            uint32_t dim, uint32_t n_bins,
                                            float scale_max, double* output) {
    return SEMQ_QUANT_SCALAR_BACKEND.reconstruct(codes, dim, n_bins, scale_max, output);
}

const semq_quant_backend_t SEMQ_QUANT_NEON_BACKEND = {
    .encode = quant_encode_neon,
    .reconstruct = quant_reconstruct_neon,
};

#endif /* ARM64 */
