/*
 * Copyright (c) 2026 The SEMQ Group Inc.
 * Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
 */

#if defined(__x86_64__) || defined(_M_X64)

#include "semq_dispatch.h"
#include "semq_bits.h"
#include "semq_quant_packing.h"

#include <immintrin.h>
#include <math.h>
#include <string.h>

static semq_status_t quant_encode_avx2(const float* input, uint32_t dim,
                                       uint32_t n_bins, float scale_max,
                                       semq_code_t* output) {
    if (n_bins < 2u || scale_max <= 0.0f) return SEMQ_ERR_INVALID_INPUT;

    const uint32_t bits = semq_bits_per_symbol_quant(n_bins);
    const uint32_t bytes = (uint32_t)(((uint64_t)dim * bits + 7u) / 8u);
    memset(output, 0, bytes);

    const __m256 zero = _mm256_setzero_ps();
    const __m256 abs_mask = _mm256_castsi256_ps(_mm256_set1_epi32(0x7fffffff));
    const __m256 bins_f = _mm256_set1_ps((float)n_bins);
    const __m256 max_f = _mm256_set1_ps(scale_max);
    const __m256i last_bin = _mm256_set1_epi32((int)n_bins - 1);
    const __m256i sign_value = _mm256_set1_epi32((int)n_bins);
    uint64_t pos = 0u;
    uint32_t i = 0u;
    for (; i + 8u <= dim; i += 8u) {
        const __m256 x = _mm256_loadu_ps(input + i);
        const __m256 magnitude = _mm256_and_ps(x, abs_mask);
        const __m256 product = _mm256_mul_ps(magnitude, bins_f);
        const __m256 quotient = _mm256_div_ps(product, max_f);
        const __m256i bin = _mm256_min_epi32(_mm256_cvttps_epi32(quotient), last_bin);
        const __m256i negative = _mm256_castps_si256(_mm256_cmp_ps(x, zero, _CMP_LT_OQ));
        const __m256i symbol = _mm256_add_epi32(bin, _mm256_andnot_si256(negative, sign_value));
        uint32_t lanes[8];
        _mm256_storeu_si256((__m256i*)lanes, symbol);
        for (uint32_t lane = 0u; lane < 8u; lane++) {
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

static semq_status_t quant_reconstruct_avx2(const semq_code_t* codes,
                                            uint32_t dim, uint32_t n_bins,
                                            float scale_max, double* output) {
    return SEMQ_QUANT_SCALAR_BACKEND.reconstruct(codes, dim, n_bins, scale_max, output);
}

const semq_quant_backend_t SEMQ_QUANT_AVX2_BACKEND = {
    .encode = quant_encode_avx2,
    .reconstruct = quant_reconstruct_avx2,
};

#endif /* x86_64 */
