/*
 * Copyright (c) 2026 The SEMQ Group Inc.
 * Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
 */

/*
 * semq_bits.h — the packed bit layout, in one place.
 *
 * QUANT codes, and packed PHASE codes, are a contiguous little-endian bit
 * stream: symbol i occupies bits [i*bits, (i+1)*bits) counting from the LSB of
 * byte 0. These helpers are the single definition of that layout, shared by the
 * encoder/reconstructor and the public unpack path so the two can never drift.
 *
 * Internal to the library; not part of the public ABI.
 */

#ifndef SEMQ_CORE_SEMQ_BITS_H
#define SEMQ_CORE_SEMQ_BITS_H

#include <stdint.h>

/* Bits per QUANT symbol for a given n_bins: ceil(log2(2*n_bins)), the sign bit
 * folded into the bin index (alphabet = 2*n_bins). */
static inline uint32_t semq_bits_per_symbol_quant(uint32_t n_bins) {
    uint32_t alphabet = 2u * n_bins;
    uint32_t bits = 0u;
    uint32_t v = alphabet - 1u;
    while (v > 0u) {
        bits++;
        v >>= 1u;
    }
    return bits == 0u ? 1u : bits;
}

/* Read `bits` bits from `in` starting at global bit offset *bit_pos, LSB-first,
 * and advance *bit_pos. The exact inverse of the encoder's bit packing. */
static inline uint32_t semq_unpack_bits(const uint8_t* in, uint64_t* bit_pos,
                                        uint32_t bits) {
    uint64_t pos = *bit_pos;
    uint32_t out = 0u;
    for (uint32_t i = 0u; i < bits; i++) {
        uint64_t byte_idx    = (pos + i) >> 3u;
        uint32_t bit_in_byte = (uint32_t)((pos + i) & 7u);
        uint32_t bit = (uint32_t)((in[byte_idx] >> bit_in_byte) & 1u);
        out |= (bit << i);
    }
    *bit_pos = pos + bits;
    return out;
}

#endif /* SEMQ_CORE_SEMQ_BITS_H */
