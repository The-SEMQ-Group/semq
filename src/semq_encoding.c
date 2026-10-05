/*
 * Copyright (c) 2026 The SEMQ Group Inc.
 * Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
 */

/* Encoding ownership, accessors and k-way concatenation. */

#include "semq_internal.h"

/* -------------------------------------------------------------------------- */
/*  Small helpers                                                             */
/* -------------------------------------------------------------------------- */

semq_encoding_t* semqi_encoding_alloc(void) {
    semq_encoding_t* e = (semq_encoding_t*)semqi_calloc(1u, sizeof(*e));
    if (e != NULL) semqi_ref_init(&e->refs);
    return e;
}

/* -------------------------------------------------------------------------- */
/*  Constructor from rows                                                     */
/* -------------------------------------------------------------------------- */

SEMQ_API semq_status_t semq_encoding_create(const semq_config_t* cfg, const semq_ids_t* ids,
                                            const uint8_t* rows, const semq_pair_t* manifest,
                                            uint32_t n_pairs, semq_encoding_t** out,
                                            semq_error_t* err) {
    if (out == NULL) return SEMQI_INVALID(err, SEMQ_NONE, SEMQ_NONE, "output is NULL");
    *out = NULL;
    semq_status_t s = semq_config_validate(cfg, err);
    if (s != SEMQ_OK) return s;
    if (ids == NULL) return SEMQI_INVALID(err, SEMQ_NONE, SEMQ_NONE, "ids is NULL");
    if (ids->n > 0u && rows == NULL) return SEMQI_INVALID(err, SEMQ_NONE, SEMQ_NONE, "rows is NULL");

    const uint32_t bpv = semq_config_bytes_per_vector(cfg);
    uint64_t rows_len;
    if (semqi_mul_ovf(ids->n, bpv, &rows_len) || semqi_too_big(rows_len)) {
        return SEMQI_NOMEM(err);
    }
    for (uint64_t i = 0u; i < ids->n; i++) {
        uint64_t unit;
        if (!semqi_row_canonical(cfg, rows + (size_t)i * bpv, &unit)) {
            return SEMQI_INVALID(err, i, unit, unit == SEMQ_NONE
                                 ? "row has a non-zero padding bit"
                                 : "row has a symbol outside the alphabet");
        }
    }
    uint64_t* perm = NULL;
    s = semqi_sort_ids(ids, &perm, err);
    if (s != SEMQ_OK) return s;

    semq_encoding_t* enc = semqi_encoding_alloc();
    if (enc == NULL) { semqi_free(perm); return SEMQI_NOMEM(err); }
    enc->config  = *cfg;
    enc->bpv     = bpv;
    enc->units   = semq_config_units_per_row(cfg);
    enc->id_kind = ids->kind;
    enc->n       = ids->n;
    if (!semqi_mul_ovf(ids->n, bpv, &enc->rows_len)) enc->rows = (uint8_t*)semqi_alloc(enc->rows_len);
    if (enc->rows == NULL) {
        enc->rows_len = 0u;
        s = SEMQI_NOMEM(err);
        goto fail;
    }
    for (uint64_t i = 0u; i < ids->n; i++) {
        memcpy(enc->rows + (size_t)i * bpv, rows + (size_t)perm[i] * bpv, bpv);
    }
    s = semqi_ids_section(ids, perm, &enc->ids, &enc->ids_len, err);
    if (s == SEMQ_OK) s = semqi_manifest_build(manifest, n_pairs, &enc->manifest, &enc->manifest_len, err);
    if (s == SEMQ_OK) s = semqi_encoding_finish(enc, err);
    if (s != SEMQ_OK) goto fail;
    semqi_free(perm);
    *out = enc;
    semqi_ok(err);
    return SEMQ_OK;
fail:
    semqi_free(perm);
    semq_encoding_free(enc);
    return s;
}

SEMQ_API void semq_encoding_free(semq_encoding_t* enc) {
    if (enc == NULL) return;
    if (!semqi_ref_dec(&enc->refs)) return;
    semqi_free(enc->ids);
    semqi_free(enc->rows);
    semqi_free(enc->manifest);
    semqi_free(enc->pairs);
    memset(enc, 0, sizeof(*enc));
    semqi_free(enc);
}

/* -------------------------------------------------------------------------- */
/*  Accessors                                                                 */
/* -------------------------------------------------------------------------- */

SEMQ_API const semq_config_t* semq_encoding_config(const semq_encoding_t* enc) {
    return enc == NULL ? NULL : &enc->config;
}
SEMQ_API uint32_t semq_encoding_id_kind(const semq_encoding_t* enc) {
    return enc == NULL ? 0u : enc->id_kind;
}
SEMQ_API uint64_t semq_encoding_len(const semq_encoding_t* enc) {
    return enc == NULL ? 0u : enc->n;
}
SEMQ_API const uint8_t* semq_encoding_rows(const semq_encoding_t* enc, uint64_t* len) {
    if (enc == NULL) { if (len) *len = 0u; return NULL; }
    if (len) *len = enc->rows_len;
    return enc->rows;
}
SEMQ_API const uint64_t* semq_encoding_ids_u64(const semq_encoding_t* enc) {
    if (enc == NULL || enc->id_kind != SEMQ_ID_U64) return NULL;
    return (const uint64_t*)(const void*)enc->ids;
}
SEMQ_API const uint64_t* semq_encoding_ids_utf8_offsets(const semq_encoding_t* enc) {
    if (enc == NULL || enc->id_kind != SEMQ_ID_UTF8) return NULL;
    return (const uint64_t*)(const void*)enc->ids;
}
SEMQ_API const uint8_t* semq_encoding_ids_utf8_bytes(const semq_encoding_t* enc, uint64_t* len) {
    if (enc == NULL || enc->id_kind != SEMQ_ID_UTF8) { if (len) *len = 0u; return NULL; }
    const uint64_t off = (enc->n + 1u) * 8u;
    if (len) *len = enc->ids_len - off;
    return enc->ids + off;
}
SEMQ_API uint32_t semq_encoding_manifest_len(const semq_encoding_t* enc) {
    return enc == NULL ? 0u : enc->n_pairs;
}
SEMQ_API semq_status_t semq_encoding_manifest_pair(const semq_encoding_t* enc, uint32_t i,
                                                   semq_pair_t* out, semq_error_t* err) {
    if (enc == NULL || out == NULL) return SEMQI_INVALID(err, SEMQ_NONE, SEMQ_NONE, "NULL argument");
    if (i >= enc->n_pairs) return SEMQI_INVALID(err, SEMQ_NONE, i, "manifest pair index out of range");
    out->key       = enc->manifest + enc->pairs[i].key_off;
    out->key_len   = enc->pairs[i].key_len;
    out->value     = enc->manifest + enc->pairs[i].value_off;
    out->value_len = enc->pairs[i].value_len;
    semqi_ok(err);
    return SEMQ_OK;
}
SEMQ_API void semq_encoding_content_digest(const semq_encoding_t* enc, uint8_t out[32]) {
    memcpy(out, enc->footer, 32u);
}
SEMQ_API void semq_encoding_state_id(const semq_encoding_t* enc, uint8_t out[32]) {
    memcpy(out, enc->footer + 32, 32u);
}

SEMQ_API semq_status_t semq_encoding_find_u64(const semq_encoding_t* enc, uint64_t id,
                                              uint64_t* index, semq_error_t* err) {
    if (enc == NULL || index == NULL) return SEMQI_INVALID(err, SEMQ_NONE, SEMQ_NONE, "NULL argument");
    if (enc->id_kind != SEMQ_ID_U64) return SEMQI_INVALID(err, SEMQ_NONE, SEMQ_NONE, "encoding ids are utf8, not u64");
    *index = semqi_find_u64(enc, id);
    semqi_ok(err);
    return SEMQ_OK;
}
SEMQ_API semq_status_t semq_encoding_find_utf8(const semq_encoding_t* enc, const uint8_t* id,
                                               uint64_t len, uint64_t* index, semq_error_t* err) {
    if (enc == NULL || index == NULL || (len > 0u && id == NULL)) {
        return SEMQI_INVALID(err, SEMQ_NONE, SEMQ_NONE, "NULL argument");
    }
    if (enc->id_kind != SEMQ_ID_UTF8) return SEMQI_INVALID(err, SEMQ_NONE, SEMQ_NONE, "encoding ids are u64, not utf8");
    *index = semqi_find_utf8(enc, id, len);
    semqi_ok(err);
    return SEMQ_OK;
}

SEMQ_API semq_status_t semq_encoding_concat(const semq_encoding_t* const* parts, uint32_t k,
                                            semq_encoding_t** out, semq_error_t* err) {
    if (out == NULL) return SEMQI_INVALID(err, SEMQ_NONE, SEMQ_NONE, "output is NULL");
    *out = NULL;
    if (parts == NULL || k == 0u) return SEMQI_INVALID(err, SEMQ_NONE, SEMQ_NONE, "concat needs at least one part");
    const semq_encoding_t* first = parts[0];
    if (first == NULL) return SEMQI_INVALID(err, SEMQ_NONE, 0u, "part is NULL");
    uint64_t total_n = 0u, total_bytes = 0u;
    for (uint32_t p = 0u; p < k; p++) {
        const semq_encoding_t* e = parts[p];
        if (e == NULL) return SEMQI_INVALID(err, SEMQ_NONE, p, "part is NULL");
        if (!semq_config_equal(&e->config, &first->config)) {
            return semqi_fail(err, SEMQ_ERR_INCOMPATIBLE, SEMQ_NONE, p, "parts have different configs");
        }
        if (e->id_kind != first->id_kind) {
            return semqi_fail(err, SEMQ_ERR_INCOMPATIBLE, SEMQ_NONE, p, "parts have different id kinds");
        }
        if (e->manifest_len != first->manifest_len
            || memcmp(e->manifest, first->manifest, (size_t)e->manifest_len) != 0) {
            return SEMQI_INVALID(err, SEMQ_NONE, p, "parts have different manifests");
        }
        if (semqi_add_ovf(total_n, e->n, &total_n)) return SEMQI_NOMEM(err);
        if (first->id_kind == SEMQ_ID_UTF8) {
            const uint64_t b = e->ids_len - (e->n + 1u) * 8u;
            if (semqi_add_ovf(total_bytes, b, &total_bytes)) return SEMQI_NOMEM(err);
        }
    }

    semq_encoding_t* enc = semqi_encoding_alloc();
    if (enc == NULL) return SEMQI_NOMEM(err);
    enc->config  = first->config;
    enc->bpv     = first->bpv;
    enc->units   = first->units;
    enc->id_kind = first->id_kind;
    enc->n       = total_n;
    uint64_t off_bytes = 0u;
    semq_status_t s = SEMQ_OK;
    if (semqi_mul_ovf(total_n, enc->bpv, &enc->rows_len)) { s = SEMQI_NOMEM(err); goto fail; }
    if (enc->id_kind == SEMQ_ID_U64) {
        if (semqi_mul_ovf(total_n, 8u, &enc->ids_len)) { s = SEMQI_NOMEM(err); goto fail; }
    } else {
        if (semqi_mul_ovf(total_n + 1u, 8u, &off_bytes)
            || semqi_add_ovf(off_bytes, total_bytes, &enc->ids_len)) { s = SEMQI_NOMEM(err); goto fail; }
    }
    enc->rows     = (uint8_t*)semqi_alloc(enc->rows_len);
    enc->ids      = (uint8_t*)semqi_alloc(enc->ids_len);
    enc->manifest = (uint8_t*)semqi_alloc(first->manifest_len);
    uint64_t* heads = (uint64_t*)semqi_alloc((uint64_t)k * sizeof(uint64_t));
    if (enc->rows == NULL || enc->ids == NULL || enc->manifest == NULL || heads == NULL) {
        semqi_free(heads);
        s = SEMQI_NOMEM(err);
        goto fail;
    }
    memcpy(enc->manifest, first->manifest, (size_t)first->manifest_len);
    enc->manifest_len = first->manifest_len;
    for (uint32_t p = 0u; p < k; p++) heads[p] = 0u;

    /* A binary min-heap of the parts that still have rows, ordered by the id
     * at their head, so every output row costs O(log k) comparisons. */
    uint32_t* heap = (uint32_t*)semqi_alloc((uint64_t)k * sizeof(uint32_t));
    if (heap == NULL) { semqi_free(heads); s = SEMQI_NOMEM(err); goto fail; }
    uint32_t heap_n = 0u;
    for (uint32_t p = 0u; p < k; p++) {
        if (parts[p]->n == 0u) continue;
        uint32_t i = heap_n++;
        heap[i] = p;
        while (i > 0u) {
            const uint32_t parent = (i - 1u) / 2u;
            if (semqi_id_cmp(parts[heap[i]], heads[heap[i]], parts[heap[parent]], heads[heap[parent]]) >= 0) break;
            const uint32_t t = heap[i]; heap[i] = heap[parent]; heap[parent] = t;
            i = parent;
        }
    }

    uint64_t written = 0u, byte_pos = 0u;
    uint32_t last_part = 0u;
    uint64_t last_row = 0u;
    if (enc->id_kind == SEMQ_ID_UTF8) semqi_wr64(enc->ids, 0u);
    while (heap_n > 0u) {
        const uint32_t best = heap[0];
        const semq_encoding_t* e = parts[best];
        const uint64_t i = heads[best];
        if (written > 0u && semqi_id_cmp(e, i, parts[last_part], last_row) == 0) {
            semqi_free(heap);
            semqi_free(heads);
            s = SEMQI_INVALID(err, i, best, "parts share an id");
            goto fail;
        }
        memcpy(enc->rows + (size_t)written * enc->bpv, e->rows + (size_t)i * enc->bpv, enc->bpv);
        if (enc->id_kind == SEMQ_ID_U64) {
            memcpy(enc->ids + written * 8u, e->ids + i * 8u, 8u);
        } else {
            uint64_t u = 0u, l = 0u;
            const uint8_t* ptr = NULL;
            semqi_id_at(e, i, &u, &ptr, &l);
            memcpy(enc->ids + off_bytes + byte_pos, ptr, (size_t)l);
            byte_pos += l;
            semqi_wr64(enc->ids + (written + 1u) * 8u, byte_pos);
        }
        last_part = best;
        last_row  = i;
        written++;
        /* Advance this part's head; drop the part when it is exhausted, then
         * restore the heap from the root. */
        heads[best] = i + 1u;
        if (heads[best] >= e->n) heap[0] = heap[--heap_n];
        uint32_t j = 0u;
        while (heap_n > 0u) {
            const uint32_t l = 2u * j + 1u, r = l + 1u;
            uint32_t m = j;
            if (l < heap_n && semqi_id_cmp(parts[heap[l]], heads[heap[l]], parts[heap[m]], heads[heap[m]]) < 0) m = l;
            if (r < heap_n && semqi_id_cmp(parts[heap[r]], heads[heap[r]], parts[heap[m]], heads[heap[m]]) < 0) m = r;
            if (m == j) break;
            const uint32_t t = heap[j]; heap[j] = heap[m]; heap[m] = t;
            j = m;
        }
    }
    semqi_free(heap);
    semqi_free(heads);
    s = semqi_encoding_finish(enc, err);
    if (s != SEMQ_OK) goto fail;
    *out = enc;
    semqi_ok(err);
    return SEMQ_OK;
fail:
    semq_encoding_free(enc);
    return s;
}
