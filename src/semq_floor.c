/*
 * Copyright (c) 2026 The SEMQ Group Inc.
 * Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
 */

/* Contextual noise envelopes and exact integer verdicts. */
#include "semq_internal.h"
#include <stdlib.h>

static const char RESERVED_ENCODER[]  = "encoder";
static const char RESERVED_REVISION[] = "encoder_revision";

int semqi_mul_le(uint64_t a, uint64_t b, uint64_t c, uint64_t d) {
    /* 64x64 -> 128 via 32-bit limbs; compare (hi, lo) pairs. */
    const uint64_t a0 = a & 0xFFFFFFFFu, a1 = a >> 32, b0 = b & 0xFFFFFFFFu, b1 = b >> 32;
    const uint64_t c0 = c & 0xFFFFFFFFu, c1 = c >> 32, d0 = d & 0xFFFFFFFFu, d1 = d >> 32;
    uint64_t lo, hi, lo2, hi2;
    {
        const uint64_t p00 = a0 * b0, p01 = a0 * b1, p10 = a1 * b0, p11 = a1 * b1;
        const uint64_t mid = (p00 >> 32) + (p01 & 0xFFFFFFFFu) + (p10 & 0xFFFFFFFFu);
        lo = (p00 & 0xFFFFFFFFu) | (mid << 32);
        hi = p11 + (p01 >> 32) + (p10 >> 32) + (mid >> 32);
    }
    {
        const uint64_t p00 = c0 * d0, p01 = c0 * d1, p10 = c1 * d0, p11 = c1 * d1;
        const uint64_t mid = (p00 >> 32) + (p01 & 0xFFFFFFFFu) + (p10 & 0xFFFFFFFFu);
        lo2 = (p00 & 0xFFFFFFFFu) | (mid << 32);
        hi2 = p11 + (p01 >> 32) + (p10 >> 32) + (mid >> 32);
    }
    if (hi != hi2) return hi < hi2;
    return lo <= lo2;
}

static int cmp_u64(const void* a, const void* b) {
    const uint64_t x = *(const uint64_t*)a, y = *(const uint64_t*)b;
    return (x < y) ? -1 : (x > y) ? 1 : 0;
}

/* Nearest-rank p99: 0 for m = 0, otherwise the k-th smallest (1-based)
 * with k = m - floor(m / 100). */
static semq_status_t p99(const uint64_t* values, uint64_t m, uint64_t* out, semq_error_t* err) {
    if (m == 0u) { *out = 0u; return SEMQ_OK; }
    uint64_t* tmp = (uint64_t*)semqi_alloc(m * sizeof(uint64_t));
    if (tmp == NULL) return SEMQI_NOMEM(err);
    memcpy(tmp, values, (size_t)m * sizeof(uint64_t));
    qsort(tmp, (size_t)m, sizeof(uint64_t), cmp_u64);
    const uint64_t k = m - m / 100u;
    *out = tmp[k - 1u];
    semqi_free(tmp);
    return SEMQ_OK;
}

static int is_reserved(const semq_manifest_change_t* m) {
    return (m->key_len == sizeof(RESERVED_ENCODER) - 1u && memcmp(m->key, RESERVED_ENCODER, m->key_len) == 0)
        || (m->key_len == sizeof(RESERVED_REVISION) - 1u && memcmp(m->key, RESERVED_REVISION, m->key_len) == 0);
}

static int has_reserved_change(const semq_diff_t* d) {
    for (uint32_t m = 0u; m < d->n_mchanges; m++) {
        if (is_reserved(&d->mchanges[m])) return 1;
    }
    return 0;
}

/* Reference state_id of a diff: the second half of the reference footer. */
static const uint8_t* reference_state_id(const semq_diff_t* d) {
    return d->ref->footer + SEMQ_DIGEST_BYTES;
}

SEMQ_API semq_status_t semq_floor_create(const semq_config_t* config, uint32_t id_kind,
                                         const uint8_t reference_id[32], uint64_t nulls,
                                         uint64_t changed_rows, uint64_t total_rows,
                                         uint64_t hamming, semq_floor_t** out,
                                         semq_error_t* err) {
    if (out == NULL) return SEMQI_INVALID(err, SEMQ_NONE, SEMQ_NONE, "output is NULL");
    *out = NULL;
    if (config == NULL || reference_id == NULL) return SEMQI_INVALID(err, SEMQ_NONE, SEMQ_NONE, "NULL argument");
    semq_status_t s = semq_config_validate(config, err);
    if (s != SEMQ_OK) return s;
    if (id_kind != (uint32_t)SEMQ_ID_U64 && id_kind != (uint32_t)SEMQ_ID_UTF8) {
        return SEMQI_INVALID(err, SEMQ_NONE, SEMQ_NONE, "floor.id_kind must be u64 or utf8");
    }
    if (nulls == 0u) return SEMQI_INVALID(err, SEMQ_NONE, SEMQ_NONE, "floor.nulls must be > 0");
    if (total_rows == 0u) return SEMQI_INVALID(err, SEMQ_NONE, SEMQ_NONE, "floor.total_rows must be > 0");
    if (changed_rows > total_rows) return SEMQI_INVALID(err, SEMQ_NONE, SEMQ_NONE, "floor.changed_rows exceeds total_rows");
    if (hamming > (uint64_t)semq_config_units_per_row(config)) {
        return SEMQI_INVALID(err, SEMQ_NONE, SEMQ_NONE, "floor.hamming exceeds units_per_row");
    }
    semq_floor_t* f = (semq_floor_t*)semqi_alloc(sizeof(*f));
    if (f == NULL) return SEMQI_NOMEM(err);
    f->config       = *config;
    f->id_kind      = id_kind;
    memcpy(f->reference_id, reference_id, SEMQ_DIGEST_BYTES);
    f->nulls        = nulls;
    f->changed_rows = changed_rows;
    f->total_rows   = total_rows;
    f->hamming      = hamming;
    *out = f;
    semqi_ok(err);
    return SEMQ_OK;
}

SEMQ_API void semq_floor_free(semq_floor_t* f) { semqi_free(f); }

SEMQ_API const semq_config_t* semq_floor_config(const semq_floor_t* f) { return &f->config; }
SEMQ_API uint32_t semq_floor_id_kind(const semq_floor_t* f) { return f->id_kind; }
SEMQ_API void semq_floor_reference_id(const semq_floor_t* f, uint8_t out[32]) {
    memcpy(out, f->reference_id, SEMQ_DIGEST_BYTES);
}
SEMQ_API uint64_t semq_floor_nulls(const semq_floor_t* f) { return f->nulls; }
SEMQ_API uint64_t semq_floor_changed_rows(const semq_floor_t* f) { return f->changed_rows; }
SEMQ_API uint64_t semq_floor_total_rows(const semq_floor_t* f) { return f->total_rows; }
SEMQ_API uint64_t semq_floor_hamming(const semq_floor_t* f) { return f->hamming; }

SEMQ_API semq_status_t semq_diff_within(const semq_diff_t* d, const semq_floor_t* f, int* out,
                                        semq_error_t* err) {
    if (d == NULL || f == NULL || out == NULL) return SEMQI_INVALID(err, SEMQ_NONE, SEMQ_NONE, "NULL argument");
    if (!semq_config_equal(&f->config, &d->ref->config)) {
        return semqi_fail(err, SEMQ_ERR_INCOMPATIBLE, SEMQ_NONE, SEMQ_NONE, "floor was measured with a different config");
    }
    if (f->id_kind != (uint32_t)d->ref->id_kind) {
        return semqi_fail(err, SEMQ_ERR_INCOMPATIBLE, SEMQ_NONE, SEMQ_NONE, "floor was measured with a different id kind");
    }
    if (memcmp(f->reference_id, reference_state_id(d), SEMQ_DIGEST_BYTES) != 0) {
        return semqi_fail(err, SEMQ_ERR_INCOMPATIBLE, SEMQ_NONE, SEMQ_NONE, "floor was measured against a different reference");
    }
    const uint64_t n_common = d->n_unchanged + d->n_changed;
    uint64_t p = 0u;
    const semq_status_t s = p99(d->hamming, d->n_changed, &p, err);
    if (s != SEMQ_OK) return s;
    *out = n_common > 0u && d->n_removed == 0u
        && semqi_mul_le(d->n_changed, f->total_rows, f->changed_rows, n_common)
        && p <= f->hamming
        && !has_reserved_change(d);
    semqi_ok(err);
    return SEMQ_OK;
}

SEMQ_API semq_status_t semq_floor_measure(const semq_diff_t* const* diffs, uint32_t k,
                                          semq_floor_t** out, semq_error_t* err) {
    if (out == NULL) return SEMQI_INVALID(err, SEMQ_NONE, SEMQ_NONE, "output is NULL");
    *out = NULL;
    if (diffs == NULL || k == 0u) return SEMQI_INVALID(err, SEMQ_NONE, SEMQ_NONE, "measure needs at least one null diff");
    uint64_t best_changed = 0u, best_common = 1u, max_p = 0u;
    for (uint32_t i = 0u; i < k; i++) {
        const semq_diff_t* d = diffs[i];
        if (d == NULL) return SEMQI_INVALID(err, SEMQ_NONE, i, "null diff is NULL");
        if (!semq_config_equal(&d->ref->config, &diffs[0]->ref->config)) {
            return semqi_fail(err, SEMQ_ERR_INCOMPATIBLE, SEMQ_NONE, i, "null diffs have different configs");
        }
        if (d->ref->id_kind != diffs[0]->ref->id_kind) {
            return semqi_fail(err, SEMQ_ERR_INCOMPATIBLE, SEMQ_NONE, i, "null diffs have different id kinds");
        }
        if (memcmp(reference_state_id(d), reference_state_id(diffs[0]), SEMQ_DIGEST_BYTES) != 0) {
            return semqi_fail(err, SEMQ_ERR_INCOMPATIBLE, SEMQ_NONE, i, "null diffs have different references");
        }
        const uint64_t n_common = d->n_unchanged + d->n_changed;
        if (n_common == 0u) return SEMQI_INVALID(err, SEMQ_NONE, i, "null diff has no rows in common");
        if (d->n_added != 0u || d->n_removed != 0u) {
            return SEMQI_INVALID(err, SEMQ_NONE, i, "null diff adds or removes rows");
        }
        if (has_reserved_change(d)) {
            return SEMQI_INVALID(err, SEMQ_NONE, i, "null diff changes encoder or encoder_revision");
        }
        /* Largest ratio changed / common, compared exactly. */
        if (i == 0u || !semqi_mul_le(d->n_changed, best_common, best_changed, n_common)) {
            best_changed = d->n_changed;
            best_common  = n_common;
        }
        uint64_t p = 0u;
        const semq_status_t s = p99(d->hamming, d->n_changed, &p, err);
        if (s != SEMQ_OK) return s;
        if (p > max_p) max_p = p;
    }
    return semq_floor_create(&diffs[0]->ref->config, (uint32_t)diffs[0]->ref->id_kind,
                             reference_state_id(diffs[0]), k, best_changed, best_common, max_p, out, err);
}
