/*
 * Copyright (c) 2026 The SEMQ Group Inc.
 * Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
 */

#ifndef SEMQ_QUANT_PACKING_H
#define SEMQ_QUANT_PACKING_H

#include <stdint.h>

/* Rows must be zeroed before packing. Config validation bounds symbols to
 * seven bits; a symbol therefore spans at most two bytes. */
static inline void semqi_quant_pack_symbol(uint8_t* out, uint64_t* bit_pos,
                                           uint32_t symbol, uint32_t bits) {
    const uint64_t pos = *bit_pos;
    const uint32_t shift = (uint32_t)(pos & 7u);
    const uint32_t value = symbol << shift;
    out[pos >> 3u] |= (uint8_t)value;
    if (shift + bits > 8u) {
        out[(pos >> 3u) + 1u] |= (uint8_t)(value >> 8u);
    }
    *bit_pos = pos + bits;
}

#endif /* SEMQ_QUANT_PACKING_H */
