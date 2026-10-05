/*
 * Copyright (c) 2026 The SEMQ Group Inc.
 * Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
 */

/*
 * semq_config.c — CodecConfig: validation, canonical form, derived
 * quantities, and the row layout every other unit relies on.
 */

#include <math.h>
#include <stdlib.h>

#include "semq_internal.h"
#include "core/semq_bits.h"

#define SEMQ_ORBIT_ALPHABET 19u
#define SEMQ_ORBIT_SCALE_MAX (1u << 30)

static semq_status_t validate(const semq_config_t* c, semq_error_t* err, semq_status_t bad,
                              uint64_t section) {
    /* `bad` is INVALID_INPUT from a constructor, FORMAT from a file reader;
     * `section` is the config field (constructor) or file section (reader). */
    const uint64_t f_op  = (bad == SEMQ_ERR_FORMAT) ? section : (uint64_t)SEMQ_FIELD_OPERATOR;
    const uint64_t f_dim = (bad == SEMQ_ERR_FORMAT) ? section : (uint64_t)SEMQ_FIELD_DIM;
    const uint64_t f_p1  = (bad == SEMQ_ERR_FORMAT) ? section : (uint64_t)SEMQ_FIELD_P1;
    const uint64_t f_p2  = (bad == SEMQ_ERR_FORMAT) ? section : (uint64_t)SEMQ_FIELD_P2;

    if (c->op > (uint32_t)SEMQ_QUANT) {
        return semqi_fail(err, bad, SEMQ_NONE, f_op, "operator must be orbit (0), phase (1) or quant (2)");
    }
    if (c->dim < 1u || c->dim > SEMQ_MAX_DIM) {
        return semqi_fail(err, bad, SEMQ_NONE, f_dim, "dim must be in [1, 65536]");
    }
    if (c->p2 != SEMQ_RULE_REVISION) {
        return semqi_fail(err, bad, SEMQ_NONE, f_p2, "unknown rule revision");
    }
    switch (c->op) {
        case SEMQ_ORBIT:
            if (c->p1 < 1u || c->p1 > SEMQ_ORBIT_SCALE_MAX) {
                return semqi_fail(err, bad, SEMQ_NONE, f_p1, "scale must be in [1, 2^30]");
            }
            break;
        case SEMQ_PHASE:
            if (c->p1 < 2u || c->p1 > 256u) {
                return semqi_fail(err, bad, SEMQ_NONE, f_p1, "sectors must be in [2, 256]");
            }
            if ((c->dim & 1u) != 0u) {
                return semqi_fail(err, bad, SEMQ_NONE, f_dim, "phase needs an even dim");
            }
            if (c->p1 <= 16u && (c->dim & 3u) != 0u) {
                return semqi_fail(err, bad, SEMQ_NONE, f_dim,
                                  "phase with sectors <= 16 needs dim divisible by 4");
            }
            break;
        default: /* SEMQ_QUANT */
            if (c->p1 < 2u || c->p1 > 64u) {
                return semqi_fail(err, bad, SEMQ_NONE, f_p1, "bins must be in [2, 64]");
            }
            break;
    }
    semqi_ok(err);
    return SEMQ_OK;
}

SEMQ_API semq_status_t semq_config_validate(const semq_config_t* cfg, semq_error_t* err) {
    if (cfg == NULL) return SEMQI_INVALID(err, SEMQ_NONE, SEMQ_NONE, "config is NULL");
    return validate(cfg, err, SEMQ_ERR_INVALID_INPUT, 0u);
}

static semq_status_t make(uint32_t op, uint32_t dim, uint32_t p1, semq_config_t* out,
                          semq_error_t* err) {
    if (out == NULL) return SEMQI_INVALID(err, SEMQ_NONE, SEMQ_NONE, "output is NULL");
    semq_config_t c;
    c.op  = op;
    c.dim = dim;
    c.p1  = p1;
    c.p2  = SEMQ_RULE_REVISION;
    const semq_status_t s = validate(&c, err, SEMQ_ERR_INVALID_INPUT, 0u);
    if (s == SEMQ_OK) *out = c;
    return s;
}

SEMQ_API semq_status_t semq_config_orbit(uint32_t dim, uint32_t scale, semq_config_t* out,
                                         semq_error_t* err) {
    return make((uint32_t)SEMQ_ORBIT, dim, scale, out, err);
}
SEMQ_API semq_status_t semq_config_phase(uint32_t dim, uint32_t sectors, semq_config_t* out,
                                         semq_error_t* err) {
    return make((uint32_t)SEMQ_PHASE, dim, sectors, out, err);
}
SEMQ_API semq_status_t semq_config_quant(uint32_t dim, uint32_t bins, semq_config_t* out,
                                         semq_error_t* err) {
    return make((uint32_t)SEMQ_QUANT, dim, bins, out, err);
}

SEMQ_API void semq_config_to_bytes(const semq_config_t* cfg, uint8_t out[13]) {
    out[0] = (uint8_t)cfg->op;
    semqi_wr32(out + 1, cfg->dim);
    semqi_wr32(out + 5, cfg->p1);
    semqi_wr32(out + 9, cfg->p2);
}

SEMQ_API semq_status_t semq_config_from_bytes(const uint8_t in[13], semq_config_t* out,
                                              semq_error_t* err) {
    if (in == NULL || out == NULL) return SEMQI_INVALID(err, SEMQ_NONE, SEMQ_NONE, "NULL argument");
    semq_config_t c;
    c.op  = in[0];
    c.dim = semqi_rd32(in + 1);
    c.p1  = semqi_rd32(in + 5);
    c.p2  = semqi_rd32(in + 9);
    const semq_status_t s = validate(&c, err, SEMQ_ERR_INVALID_INPUT, 0u);
    if (s == SEMQ_OK) *out = c;
    return s;
}

/* Used by the file reader: the same rules, reported as a format error. */
semq_status_t semqi_config_from_file(const uint8_t in[13], semq_config_t* out, semq_error_t* err) {
    semq_config_t c;
    c.op  = in[0];
    c.dim = semqi_rd32(in + 1);
    c.p1  = semqi_rd32(in + 5);
    c.p2  = semqi_rd32(in + 9);
    const semq_status_t s = validate(&c, err, SEMQ_ERR_FORMAT, (uint64_t)SEMQ_SECTION_CONFIG);
    if (s == SEMQ_OK) *out = c;
    return s;
}

SEMQ_API int semq_config_equal(const semq_config_t* a, const semq_config_t* b) {
    uint8_t x[13], y[13];
    semq_config_to_bytes(a, x);
    semq_config_to_bytes(b, y);
    return memcmp(x, y, 13u) == 0;
}

uint32_t semqi_bits_per_unit(const semq_config_t* cfg) {
    switch (cfg->op) {
        case SEMQ_ORBIT: return 8u;
        case SEMQ_PHASE: return (cfg->p1 <= 16u) ? 4u : 8u;
        default:         return semq_bits_per_symbol_quant(cfg->p1);
    }
}

SEMQ_API uint32_t semq_config_units_per_row(const semq_config_t* cfg) {
    return (cfg->op == SEMQ_PHASE) ? cfg->dim / 2u : cfg->dim;
}

SEMQ_API uint32_t semq_config_bytes_per_vector(const semq_config_t* cfg) {
    switch (cfg->op) {
        case SEMQ_ORBIT: return cfg->dim;
        case SEMQ_PHASE: return (cfg->p1 <= 16u) ? cfg->dim / 4u : cfg->dim / 2u;
        default: {
            const uint64_t bits = (uint64_t)cfg->dim * (uint64_t)semqi_bits_per_unit(cfg);
            return (uint32_t)((bits + 7u) / 8u);
        }
    }
}

SEMQ_API float semq_config_max_magnitude(const semq_config_t* cfg) {
    if (cfg->op != SEMQ_QUANT) return 0.0f;
    return (float)(2.0 / sqrt((double)cfg->dim));
}

void semqi_unpack_row(const semq_config_t* cfg, const uint8_t* row, uint8_t* symbols) {
    const uint32_t units = semq_config_units_per_row(cfg);
    switch (cfg->op) {
        case SEMQ_ORBIT:
            memcpy(symbols, row, units);
            return;
        case SEMQ_PHASE:
            if (cfg->p1 <= 16u) {
                for (uint32_t u = 0u; u < units; u++) {
                    symbols[u] = (uint8_t)(((uint32_t)row[u >> 1] >> (4u * (u & 1u))) & 0x0Fu);
                }
            } else {
                memcpy(symbols, row, units);
            }
            return;
        default: {
            const uint32_t bits = semqi_bits_per_unit(cfg);
            uint64_t pos = 0u;
            for (uint32_t u = 0u; u < units; u++) {
                symbols[u] = (uint8_t)semq_unpack_bits(row, &pos, bits);
            }
            return;
        }
    }
}

int semqi_row_canonical(const semq_config_t* cfg, const uint8_t* row, uint64_t* unit) {
    const uint32_t units = semq_config_units_per_row(cfg);
    switch (cfg->op) {
        case SEMQ_ORBIT:
            for (uint32_t u = 0u; u < units; u++) {
                if (row[u] >= SEMQ_ORBIT_ALPHABET) { *unit = u; return 0; }
            }
            return 1;
        case SEMQ_PHASE:
            /* 16 sectors in a nibble and 256 in a byte use every value: no
             * symbol can be out of the alphabet, and phase rows have no
             * padding. */
            if (cfg->p1 == 16u || cfg->p1 == 256u) return 1;
            if (cfg->p1 <= 16u) {
                for (uint32_t u = 0u; u < units; u++) {
                    const uint8_t s = (uint8_t)(((uint32_t)row[u >> 1] >> (4u * (u & 1u))) & 0x0Fu);
                    if (s >= cfg->p1) { *unit = u; return 0; }
                }
            } else {
                for (uint32_t u = 0u; u < units; u++) {
                    if (row[u] >= cfg->p1) { *unit = u; return 0; }
                }
            }
            return 1;
        default: {
            const uint32_t bits     = semqi_bits_per_unit(cfg);
            const uint32_t alphabet = 2u * cfg->p1;
            uint64_t pos = 0u;
            if (alphabet == (1u << bits)) {
                /* Every bit pattern is a symbol: only the padding can be wrong. */
                pos = (uint64_t)units * bits;
            } else {
                for (uint32_t u = 0u; u < units; u++) {
                    if (semq_unpack_bits(row, &pos, bits) >= alphabet) { *unit = u; return 0; }
                }
            }
            /* Padding bits from dim*bits to 8*bytes_per_vector must be zero. */
            const uint64_t total = (uint64_t)semq_config_bytes_per_vector(cfg) * 8u;
            for (; pos < total; pos++) {
                if ((((uint32_t)row[pos >> 3] >> (pos & 7u)) & 1u) != 0u) { *unit = SEMQ_NONE; return 0; }
            }
            return 1;
        }
    }
}
