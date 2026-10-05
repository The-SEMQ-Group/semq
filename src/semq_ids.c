/*
 * Copyright (c) 2026 The SEMQ Group Inc.
 * Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
 */

/* ID admission, canonical ordering and lookup. */
#include "semq_internal.h"

int semqi_utf8_valid(const uint8_t* s, uint64_t len) {
    uint64_t i = 0u;
    while (i < len) {
        const uint8_t c = s[i];
        if (c == 0x00u) return 0;
        if (c < 0x80u) { i++; continue; }
        uint32_t need, cp, min;
        if ((c & 0xE0u) == 0xC0u)      { need = 1u; cp = c & 0x1Fu; min = 0x80u; }
        else if ((c & 0xF0u) == 0xE0u) { need = 2u; cp = c & 0x0Fu; min = 0x800u; }
        else if ((c & 0xF8u) == 0xF0u) { need = 3u; cp = c & 0x07u; min = 0x10000u; }
        else { return 0; }
        if (i + need >= len + 0u && i + need > len - 1u) return 0;
        if (len - i - 1u < need) return 0;
        for (uint32_t k = 1u; k <= need; k++) {
            const uint8_t cc = s[i + k];
            if ((cc & 0xC0u) != 0x80u) return 0;
            cp = (cp << 6) | (cc & 0x3Fu);
        }
        if (cp < min) return 0;                         /* overlong */
        if (cp >= 0xD800u && cp <= 0xDFFFu) return 0;   /* surrogate */
        if (cp > 0x10FFFFu) return 0;
        i += need + 1u;
    }
    return 1;
}

int semqi_cmp_bytes(const uint8_t* a, uint64_t alen, const uint8_t* b, uint64_t blen) {
    const uint64_t m = alen < blen ? alen : blen;
    const int c = (m == 0u) ? 0 : memcmp(a, b, (size_t)m);
    if (c != 0) return c;
    if (alen < blen) return -1;
    if (alen > blen) return 1;
    return 0;
}

static int id_less(const semq_ids_t* ids, uint64_t a, uint64_t b) {
    if (ids->kind == SEMQ_ID_U64) return ids->u64[a] < ids->u64[b];
    const uint64_t ao = ids->utf8_offsets[a], al = ids->utf8_offsets[a + 1u] - ao;
    const uint64_t bo = ids->utf8_offsets[b], bl = ids->utf8_offsets[b + 1u] - bo;
    return semqi_cmp_bytes(ids->utf8_bytes + ao, al, ids->utf8_bytes + bo, bl) < 0;
}

static int id_equal(const semq_ids_t* ids, uint64_t a, uint64_t b) {
    if (ids->kind == SEMQ_ID_U64) return ids->u64[a] == ids->u64[b];
    const uint64_t ao = ids->utf8_offsets[a], al = ids->utf8_offsets[a + 1u] - ao;
    const uint64_t bo = ids->utf8_offsets[b], bl = ids->utf8_offsets[b + 1u] - bo;
    return semqi_cmp_bytes(ids->utf8_bytes + ao, al, ids->utf8_bytes + bo, bl) == 0;
}

/* Stable sort preserves the input row used in duplicate-ID errors. */
static void merge_sort(const semq_ids_t* ids, uint64_t* perm, uint64_t* tmp, uint64_t n) {
    if (n < 2u) return;
    const uint64_t h = n / 2u;
    merge_sort(ids, perm, tmp, h);
    merge_sort(ids, perm + h, tmp, n - h);
    uint64_t i = 0u, j = h, k = 0u;
    while (i < h && j < n) {
        if (id_less(ids, perm[j], perm[i])) tmp[k++] = perm[j++];
        else                                tmp[k++] = perm[i++];
    }
    while (i < h) tmp[k++] = perm[i++];
    while (j < n) tmp[k++] = perm[j++];
    memcpy(perm, tmp, (size_t)n * sizeof(uint64_t));
}

static semq_status_t validate_ids(const semq_ids_t* ids, semq_error_t* err) {
    if (ids->kind != SEMQ_ID_U64 && ids->kind != SEMQ_ID_UTF8) {
        return SEMQI_INVALID(err, SEMQ_NONE, SEMQ_NONE, "id_kind must be u64 (0) or utf8 (1)");
    }
    if (ids->n == 0u) return SEMQ_OK;
    uint64_t count, bytes;
    if (semqi_add_ovf(ids->n, ids->kind == SEMQ_ID_UTF8 ? 1u : 0u, &count) ||
        semqi_mul_ovf(count, sizeof(uint64_t), &bytes) || semqi_too_big(bytes)) {
        return SEMQI_NOMEM(err);
    }
    if (ids->kind == SEMQ_ID_U64) {
        if (ids->u64 == NULL) return SEMQI_INVALID(err, SEMQ_NONE, SEMQ_NONE, "u64 ids are NULL");
        return SEMQ_OK;
    }
    if (ids->utf8_offsets == NULL) return SEMQI_INVALID(err, SEMQ_NONE, SEMQ_NONE, "utf8 offsets are NULL");
    if (ids->utf8_offsets[0] != 0u) return SEMQI_INVALID(err, 0u, SEMQ_NONE, "utf8 offsets must start at 0");
    for (uint64_t i = 0u; i < ids->n; i++) {
        const uint64_t a = ids->utf8_offsets[i], b = ids->utf8_offsets[i + 1u];
        if (b < a) return SEMQI_INVALID(err, i, SEMQ_NONE, "utf8 offsets must be non-decreasing");
        if (semqi_too_big(b)) return SEMQI_NOMEM(err);
        const uint64_t len = b - a;
        if (len < 1u) return SEMQI_INVALID(err, i, SEMQ_NONE, "utf8 id is empty");
        if (len > SEMQ_ID_MAX_BYTES) return SEMQI_INVALID(err, i, SEMQ_NONE, "utf8 id exceeds 4096 bytes");
        if (ids->utf8_bytes == NULL) return SEMQI_INVALID(err, i, SEMQ_NONE, "utf8 bytes are NULL");
        if (!semqi_utf8_valid(ids->utf8_bytes + a, len)) {
            return SEMQI_INVALID(err, i, SEMQ_NONE, "utf8 id is not valid UTF-8 or contains NUL");
        }
    }
    return SEMQ_OK;
}

semq_status_t semqi_sort_ids(const semq_ids_t* ids, uint64_t** perm_out, semq_error_t* err) {
    *perm_out = NULL;
    semq_status_t s = validate_ids(ids, err);
    if (s != SEMQ_OK) return s;
    uint64_t bytes;
    if (semqi_mul_ovf(ids->n, sizeof(uint64_t), &bytes)) return SEMQI_NOMEM(err);
    uint64_t* perm = (uint64_t*)semqi_alloc(bytes);
    uint64_t* tmp  = (uint64_t*)semqi_alloc(bytes);
    if (perm == NULL || tmp == NULL) { semqi_free(perm); semqi_free(tmp); return SEMQI_NOMEM(err); }
    for (uint64_t i = 0u; i < ids->n; i++) perm[i] = i;
    merge_sort(ids, perm, tmp, ids->n);
    semqi_free(tmp);
    for (uint64_t i = 1u; i < ids->n; i++) {
        if (id_equal(ids, perm[i - 1u], perm[i])) {
            /* The sort is stable, so perm[i] is the later input row. */
            const uint64_t repeated = perm[i];
            semqi_free(perm);
            return SEMQI_INVALID(err, repeated, SEMQ_NONE, "duplicate id");
        }
    }
    *perm_out = perm;
    return SEMQ_OK;
}

semq_status_t semqi_ids_section(const semq_ids_t* ids, const uint64_t* perm, uint8_t** section,
                                uint64_t* len, semq_error_t* err) {
    *section = NULL;
    *len = 0u;
    if (ids->kind == SEMQ_ID_U64) {
        uint64_t bytes;
        if (semqi_mul_ovf(ids->n, 8u, &bytes)) return SEMQI_NOMEM(err);
        uint8_t* out = (uint8_t*)semqi_alloc(bytes);
        if (out == NULL) return SEMQI_NOMEM(err);
        for (uint64_t i = 0u; i < ids->n; i++) semqi_wr64(out + i * 8u, ids->u64[perm[i]]);
        *section = out;
        *len = bytes;
        return SEMQ_OK;
    }
    const uint64_t total = (ids->n == 0u) ? 0u : ids->utf8_offsets[ids->n];
    uint64_t off_bytes, bytes;
    if (semqi_mul_ovf(ids->n + 1u, 8u, &off_bytes) || semqi_add_ovf(off_bytes, total, &bytes)) {
        return SEMQI_NOMEM(err);
    }
    uint8_t* out = (uint8_t*)semqi_alloc(bytes);
    if (out == NULL) return SEMQI_NOMEM(err);
    uint64_t pos = 0u;
    semqi_wr64(out, 0u);
    for (uint64_t i = 0u; i < ids->n; i++) {
        const uint64_t src = perm[i];
        const uint64_t a = ids->utf8_offsets[src], l = ids->utf8_offsets[src + 1u] - a;
        memcpy(out + off_bytes + pos, ids->utf8_bytes + a, (size_t)l);
        pos += l;
        semqi_wr64(out + (i + 1u) * 8u, pos);
    }
    *section = out;
    *len = bytes;
    return SEMQ_OK;
}

uint64_t semqi_find_u64(const semq_encoding_t* enc, uint64_t id) {
    uint64_t lo = 0u, hi = enc->n;
    while (lo < hi) {
        const uint64_t mid = lo + (hi - lo) / 2u;
        const uint64_t v = semqi_rd64(enc->ids + mid * 8u);
        if (v < id) lo = mid + 1u;
        else if (v > id) hi = mid;
        else return mid;
    }
    return SEMQ_NONE;
}

uint64_t semqi_find_utf8(const semq_encoding_t* enc, const uint8_t* id, uint64_t len) {
    const uint8_t* bytes = enc->ids + (enc->n + 1u) * 8u;
    uint64_t lo = 0u, hi = enc->n;
    while (lo < hi) {
        const uint64_t mid = lo + (hi - lo) / 2u;
        const uint64_t a = semqi_rd64(enc->ids + mid * 8u), b = semqi_rd64(enc->ids + (mid + 1u) * 8u);
        const int c = semqi_cmp_bytes(bytes + a, b - a, id, len);
        if (c < 0) lo = mid + 1u;
        else if (c > 0) hi = mid;
        else return mid;
    }
    return SEMQ_NONE;
}

/* Caller supplies every output; only the field for the ID kind is set. */
void semqi_id_at(const semq_encoding_t* e, uint64_t i, uint64_t* u, const uint8_t** p, uint64_t* l) {
    if (e->id_kind == SEMQ_ID_U64) { *u = semqi_rd64(e->ids + i * 8u); return; }
    const uint64_t a = semqi_rd64(e->ids + i * 8u), b = semqi_rd64(e->ids + (i + 1u) * 8u);
    *p = e->ids + (e->n + 1u) * 8u + a;
    *l = b - a;
}

int semqi_id_cmp(const semq_encoding_t* a, uint64_t i, const semq_encoding_t* b, uint64_t j) {
    uint64_t ua = 0u, ub = 0u, la = 0u, lb = 0u;
    const uint8_t *pa = NULL, *pb = NULL;
    semqi_id_at(a, i, &ua, &pa, &la);
    semqi_id_at(b, j, &ub, &pb, &lb);
    if (a->id_kind == SEMQ_ID_U64) return (ua < ub) ? -1 : (ua > ub) ? 1 : 0;
    return semqi_cmp_bytes(pa, la, pb, lb);
}
