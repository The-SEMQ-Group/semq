/*
 * Copyright (c) 2026 The SEMQ Group Inc.
 * Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
 */

/*
 * semq_quant_scalar.c — scalar reference implementation of SEMQ_OP_QUANT.
 *
 * QUANT is a per-dimension sign + magnitude-bin quantizer.
 *
 *   forward map φ:  x_i  →  symbol = sign_flag(x_i) * quant_n_bins + bin(|x_i|)
 *                    with bin(m) = clamp(floor(m * n_bins / scale_max), n_bins-1)
 *                    and sign_flag(x) = 1 if x >= 0 else 0
 *
 *   inverse map φ⁻¹: symbol → (sign × bin_centre)
 *                    where bin_centre = (b + 0.5) * scale_max / n_bins
 *                    and sign = +1 if symbol >= n_bins else -1
 *
 * Codes are dense bit-packed into the output byte stream at
 * ceil(log2(2 * n_bins)) bits per dimension. The pack order is
 * little-endian within each byte: the first bits go to the LSBs of the
 * first byte; once a byte fills up, packing moves to the next byte.
 * This matches the unpack convention used by Python references and
 * keeps the scalar code SIMD-friendly for later backends.
 *
 * Compare uses symbol-level Hamming distance — proportion of dimensions
 * where the (sign, bin) pair differs between two encoded vectors —
 * normalized to [0, 1]. That is rank-monotone with the post-reconstruct
 * cosine similarity and avoids the float-reconstruction round-trip.
 */

#include "semq_dispatch.h"
#include "semq_bits.h"
#include "semq_quant_packing.h"

#include <stdint.h>
#include <math.h>
#include <string.h>

/* -------------------------------------------------------------------------- */
/*  Helpers                                                                   */
/* -------------------------------------------------------------------------- */

/* Number of bits needed per dim for a given n_bins (sign + log2(n_bins)).
 * Defined once in semq_bits.h so encode/reconstruct and the public unpack
 * agree on the layout. */
static uint32_t quant_bits_per_dim(uint32_t n_bins) {
    return semq_bits_per_symbol_quant(n_bins);
}

/* Output byte count for a given (dim, n_bins) pair. Always rounds up. */
static uint32_t quant_output_bytes(uint32_t dim, uint32_t n_bins) {
    uint32_t bpd = quant_bits_per_dim(n_bins);
    uint64_t total_bits = (uint64_t)dim * (uint64_t)bpd;
    return (uint32_t)((total_bits + 7u) / 8u);
}

/* Magnitude -> bin index. The single definition of the QUANT bin decision,
 * shared by every encoder backend. */
uint32_t semq_quant_bin_of_magnitude(float mag, float scale_max, uint32_t n_bins) {
    /* m >= M saturates into the top bin. Below M: t = (m * bins) / M with
     * both operations in binary32, round-to-nearest-even, no contraction
     * (the build passes -ffp-contract=off); bin = min(floor(t), bins - 1). */
    if (mag >= scale_max) {
        return n_bins - 1u;
    }
    const float t = (mag * (float)n_bins) / scale_max;
    uint32_t b = (uint32_t)floorf(t);
    if (b >= n_bins) b = n_bins - 1u;
    return b;
}

/* Per-dim symbol: bin index folded with sign bit. */
static uint32_t quant_symbol(float x, float scale_max, uint32_t n_bins) {
    uint32_t b = semq_quant_bin_of_magnitude(fabsf(x), scale_max, n_bins);
    uint32_t sign_flag = (x < 0.0f) ? 0u : 1u;
    return sign_flag * n_bins + b;
}

/* Reconstructed float for a given symbol. */
static double quant_centre(uint32_t symbol, float scale_max, uint32_t n_bins) {
    uint32_t sign_flag = symbol / n_bins;       /* 0 = negative, 1 = positive */
    uint32_t b         = symbol % n_bins;
    double centre = ((double)b + 0.5) * (double)scale_max / (double)n_bins;
    return sign_flag ? centre : -centre;
}

/* Unpack `bits` bits from `in` starting at global bit offset `*bit_pos`.
 * Delegates to the shared layout definition in semq_bits.h. */
static uint32_t unpack_bits(const semq_code_t* in, uint64_t* bit_pos,
                            uint32_t bits) {
    return semq_unpack_bits(in, bit_pos, bits);
}

/* -------------------------------------------------------------------------- */
/*  Public-equivalent vtable functions                                        */
/* -------------------------------------------------------------------------- */

static semq_status_t quant_encode_scalar(
    const float* input,
    uint32_t     dim,
    uint32_t     n_bins,
    float        scale_max,
    semq_code_t* output)
{
    if (n_bins < 2u || scale_max <= 0.0f) {
        return SEMQ_ERR_INVALID_INPUT;
    }
    uint32_t bpd = quant_bits_per_dim(n_bins);
    uint32_t bytes = quant_output_bytes(dim, n_bins);

    /* Zero the output so pack_bits' OR-in semantics produce the right
     * value without depending on caller-supplied memory state. */
    memset(output, 0, bytes);

    uint64_t pos = 0;
    for (uint32_t i = 0; i < dim; i++) {
        uint32_t sym = quant_symbol(input[i], scale_max, n_bins);
        semqi_quant_pack_symbol(output, &pos, sym, bpd);
    }
    return SEMQ_OK;
}

static semq_status_t quant_reconstruct_scalar(
    const semq_code_t* codes,
    uint32_t           dim,
    uint32_t           n_bins,
    float              scale_max,
    double*            output)
{
    if (n_bins < 2u || scale_max <= 0.0f) {
        return SEMQ_ERR_INVALID_INPUT;
    }
    uint32_t bpd = quant_bits_per_dim(n_bins);
    uint64_t pos = 0;
    for (uint32_t i = 0; i < dim; i++) {
        uint32_t sym = unpack_bits(codes, &pos, bpd);
        output[i] = quant_centre(sym, scale_max, n_bins);
    }
    return SEMQ_OK;
}

/* -------------------------------------------------------------------------- */
/*  Vtable                                                                    */
/* -------------------------------------------------------------------------- */

const semq_quant_backend_t SEMQ_QUANT_SCALAR_BACKEND = {
    .encode       = quant_encode_scalar,
    .reconstruct  = quant_reconstruct_scalar,
};
