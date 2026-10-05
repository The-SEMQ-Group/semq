/*
 * Copyright (c) 2026 The SEMQ Group Inc.
 * Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
 */

/* File framing, digests, validation and publication. */
#include "semq_internal.h"
#include "semq_sha256.h"

semq_status_t semqi_encoding_finish(semq_encoding_t* enc, semq_error_t* err) {
    memcpy(enc->header, "SEMQ", 4u);
    semqi_wr16(enc->header + 4, (uint16_t)SEMQ_FILE_VERSION);
    semq_config_to_bytes(&enc->config, enc->header + 6);
    enc->header[19] = (uint8_t)enc->id_kind;
    semqi_wr64(enc->header + 20, enc->n);

    if (enc->pairs == NULL && enc->n_pairs == 0u) {
        const semq_status_t s = semqi_manifest_index(enc->manifest, enc->manifest_len,
                                                     &enc->n_pairs, &enc->pairs, err);
        if (s != SEMQ_OK) return s;
    }

    semq_sha256_ctx_t h;
    semq_sha256_init(&h);
    semq_sha256_update(&h, enc->header + SEMQI_S_OFFSET, SEMQI_HEADER_BYTES - SEMQI_S_OFFSET);
    semq_sha256_update(&h, enc->ids, (size_t)enc->ids_len);
    semq_sha256_update(&h, enc->rows, (size_t)enc->rows_len);
    semq_sha256_final(&h, enc->footer);

    semq_sha256_init(&h);
    semq_sha256_update(&h, enc->footer, 32u);
    semq_sha256_update(&h, enc->manifest, (size_t)enc->manifest_len);
    semq_sha256_final(&h, enc->footer + 32);
    return SEMQ_OK;
}

SEMQ_API uint64_t semq_encoding_file_size(const semq_encoding_t* enc) {
    if (enc == NULL) return 0u;
    return SEMQI_HEADER_BYTES + enc->ids_len + enc->rows_len + enc->manifest_len + SEMQI_FOOTER_BYTES;
}

SEMQ_API uint32_t semq_encoding_save_parts(const semq_encoding_t* enc, semq_part_t parts[5]) {
    parts[0].ptr = enc->header;   parts[0].len = SEMQI_HEADER_BYTES;
    parts[1].ptr = enc->ids;      parts[1].len = enc->ids_len;
    parts[2].ptr = enc->rows;     parts[2].len = enc->rows_len;
    parts[3].ptr = enc->manifest; parts[3].len = enc->manifest_len;
    parts[4].ptr = enc->footer;   parts[4].len = SEMQI_FOOTER_BYTES;
    return 5u;
}

SEMQ_API semq_status_t semq_encoding_save(const semq_encoding_t* enc, uint8_t* out, uint64_t cap,
                                          semq_error_t* err) {
    if (enc == NULL || out == NULL) return SEMQI_INVALID(err, SEMQ_NONE, SEMQ_NONE, "NULL argument");
    if (cap < semq_encoding_file_size(enc)) return SEMQI_INVALID(err, SEMQ_NONE, SEMQ_NONE, "output buffer is too small");
    semq_part_t parts[5];
    semq_encoding_save_parts(enc, parts);
    uint64_t pos = 0u;
    for (uint32_t i = 0u; i < 5u; i++) {
        if (parts[i].len > 0u) memcpy(out + pos, parts[i].ptr, (size_t)parts[i].len);
        pos += parts[i].len;
    }
    semqi_ok(err);
    return SEMQ_OK;
}

SEMQ_API semq_status_t semq_encoding_load(const uint8_t* buf, uint64_t len, semq_encoding_t** out,
                                          semq_error_t* err) {
    if (out == NULL) return SEMQI_INVALID(err, SEMQ_NONE, SEMQ_NONE, "output is NULL");
    *out = NULL;
    /* 1. Framing. An empty buffer is an image that is too short, whatever its
     * pointer; a NULL pointer with a positive length is a caller error. */
    const uint64_t min_len = SEMQI_HEADER_BYTES + 4u + SEMQI_FOOTER_BYTES;
    if (len < min_len) return SEMQI_FORMAT(err, SEMQ_SECTION_FRAMING, "buffer is shorter than the smallest image");
    if (buf == NULL) return SEMQI_INVALID(err, SEMQ_NONE, SEMQ_NONE, "buffer is NULL");
    if (memcmp(buf, "SEMQ", 4u) != 0) return SEMQI_FORMAT(err, SEMQ_SECTION_FRAMING, "magic bytes are not SEMQ");
    const uint16_t version = semqi_rd16(buf + 4);
    if (version == 1u) return SEMQI_FORMAT(err, SEMQ_SECTION_FRAMING, "unsupported version 1");
    if (version != SEMQ_FILE_VERSION) return SEMQI_FORMAT(err, SEMQ_SECTION_FRAMING, "unsupported file version");

    /* 2. Config. */
    semq_config_t cfg;
    semq_status_t s = semqi_config_from_file(buf + 6, &cfg, err);
    if (s != SEMQ_OK) return s;
    const uint32_t bpv   = semq_config_bytes_per_vector(&cfg);

    /* 3. Sizes and limits. */
    const uint8_t  kind = buf[19];
    const uint64_t n    = semqi_rd64(buf + 20);
    if (kind != SEMQ_ID_U64 && kind != SEMQ_ID_UTF8) return SEMQI_FORMAT(err, SEMQ_SECTION_SIZES, "unknown id kind");
    const uint64_t body = len - SEMQI_HEADER_BYTES - SEMQI_FOOTER_BYTES; /* ids + rows + manifest */
    uint64_t ids_len, rows_len;
    if (semqi_mul_ovf(n, bpv, &rows_len)) return SEMQI_FORMAT(err, SEMQ_SECTION_SIZES, "row section overflows");
    if (kind == SEMQ_ID_U64) {
        if (semqi_mul_ovf(n, 8u, &ids_len)) return SEMQI_FORMAT(err, SEMQ_SECTION_SIZES, "id section overflows");
    } else {
        uint64_t off_bytes;
        if (semqi_mul_ovf(n + 1u, 8u, &off_bytes) || n == UINT64_MAX) {
            return SEMQI_FORMAT(err, SEMQ_SECTION_SIZES, "id section overflows");
        }
        if (off_bytes > body) return SEMQI_FORMAT(err, SEMQ_SECTION_SIZES, "id offsets exceed the buffer");
        const uint64_t total = semqi_rd64(buf + SEMQI_HEADER_BYTES + n * 8u);
        if (semqi_add_ovf(off_bytes, total, &ids_len)) return SEMQI_FORMAT(err, SEMQ_SECTION_SIZES, "id section overflows");
    }
    uint64_t used;
    if (semqi_add_ovf(ids_len, rows_len, &used) || used > body) {
        return SEMQI_FORMAT(err, SEMQ_SECTION_SIZES, "sections exceed the buffer");
    }
    const uint64_t manifest_len = body - used;
    if (manifest_len < 4u) return SEMQI_FORMAT(err, SEMQ_SECTION_SIZES, "manifest section is missing");
    if (manifest_len > (uint64_t)SEMQ_MANIFEST_SECTION_MAX) return SEMQI_FORMAT(err, SEMQ_SECTION_SIZES, "manifest section exceeds 16 MiB");
    if (semqi_too_big(len)) return SEMQI_NOMEM(err);

    const uint8_t* ids_p = buf + SEMQI_HEADER_BYTES;
    const uint8_t* rows_p = ids_p + ids_len;
    const uint8_t* man_p = rows_p + rows_len;
    const uint8_t* foot_p = man_p + manifest_len;

    /* 4. Ids. */
    if (kind == SEMQ_ID_U64) {
        for (uint64_t i = 1u; i < n; i++) {
            if (semqi_rd64(ids_p + (i - 1u) * 8u) >= semqi_rd64(ids_p + i * 8u)) {
                return SEMQI_FORMAT(err, SEMQ_SECTION_IDS, "u64 ids are not strictly increasing");
            }
        }
    } else {
        const uint8_t* bytes = ids_p + (n + 1u) * 8u;
        const uint64_t total = ids_len - (n + 1u) * 8u;
        if (semqi_rd64(ids_p) != 0u) return SEMQI_FORMAT(err, SEMQ_SECTION_IDS, "utf8 offsets must start at 0");
        const uint8_t* prev = NULL;
        uint64_t prev_len = 0u;
        for (uint64_t i = 0u; i < n; i++) {
            const uint64_t a = semqi_rd64(ids_p + i * 8u), b = semqi_rd64(ids_p + (i + 1u) * 8u);
            if (b <= a || b > total) return SEMQI_FORMAT(err, SEMQ_SECTION_IDS, "utf8 offsets are not strictly increasing");
            const uint64_t l = b - a;
            if (l > SEMQ_ID_MAX_BYTES) return SEMQI_FORMAT(err, SEMQ_SECTION_IDS, "utf8 id exceeds 4096 bytes");
            if (!semqi_utf8_valid(bytes + a, l)) return SEMQI_FORMAT(err, SEMQ_SECTION_IDS, "utf8 id is not valid UTF-8");
            if (prev != NULL && semqi_cmp_bytes(prev, prev_len, bytes + a, l) >= 0) {
                return SEMQI_FORMAT(err, SEMQ_SECTION_IDS, "utf8 ids are not strictly increasing");
            }
            prev = bytes + a;
            prev_len = l;
        }
        if (n == 0u && total != 0u) return SEMQI_FORMAT(err, SEMQ_SECTION_IDS, "utf8 bytes without ids");
    }

    /* 5. Manifest. */
    uint32_t n_pairs = 0u;
    semqi_pair_index_t* pairs = NULL;
    s = semqi_manifest_index(man_p, manifest_len, &n_pairs, &pairs, err);
    if (s != SEMQ_OK) return s;

    /* 6. Identities. */
    uint8_t digest[64];
    {
        semq_sha256_ctx_t h;
        semq_sha256_init(&h);
        semq_sha256_update(&h, buf + SEMQI_S_OFFSET, SEMQI_HEADER_BYTES - SEMQI_S_OFFSET);
        semq_sha256_update(&h, ids_p, (size_t)ids_len);
        semq_sha256_update(&h, rows_p, (size_t)rows_len);
        semq_sha256_final(&h, digest);
        semq_sha256_init(&h);
        semq_sha256_update(&h, digest, 32u);
        semq_sha256_update(&h, man_p, (size_t)manifest_len);
        semq_sha256_final(&h, digest + 32);
    }
    if (memcmp(digest, foot_p, 32u) != 0) {
        semqi_free(pairs);
        return semqi_fail_integrity(err, SEMQ_WHICH_CONTENT, "content digest does not match the footer");
    }
    if (memcmp(digest + 32, foot_p + 32, 32u) != 0) {
        semqi_free(pairs);
        return semqi_fail_integrity(err, SEMQ_WHICH_STATE, "state id does not match the footer");
    }

    /* 7. Rows. */
    for (uint64_t i = 0u; i < n; i++) {
        uint64_t unit;
        if (!semqi_row_canonical(&cfg, rows_p + (size_t)i * bpv, &unit)) {
            semqi_free(pairs);
            return semqi_fail(err, SEMQ_ERR_FORMAT, i, (uint64_t)SEMQ_SECTION_ROWS, "row is not canonical");
        }
    }

    /* 8. Publication. */
    semq_encoding_t* enc = semqi_encoding_alloc();
    if (enc == NULL) { semqi_free(pairs); return SEMQI_NOMEM(err); }
    enc->config  = cfg;
    enc->bpv     = bpv;
    enc->units   = semq_config_units_per_row(&cfg);
    enc->id_kind = kind;
    enc->n       = n;
    enc->ids     = (uint8_t*)semqi_alloc(ids_len);
    enc->rows    = (uint8_t*)semqi_alloc(rows_len);
    enc->manifest = (uint8_t*)semqi_alloc(manifest_len);
    if (enc->ids == NULL || enc->rows == NULL || enc->manifest == NULL) {
        semqi_free(pairs);
        semq_encoding_free(enc);
        return SEMQI_NOMEM(err);
    }
    memcpy(enc->ids, ids_p, (size_t)ids_len);         enc->ids_len = ids_len;
    memcpy(enc->rows, rows_p, (size_t)rows_len);      enc->rows_len = rows_len;
    memcpy(enc->manifest, man_p, (size_t)manifest_len); enc->manifest_len = manifest_len;
    enc->n_pairs = n_pairs;
    enc->pairs   = pairs;
    memcpy(enc->header, buf, SEMQI_HEADER_BYTES);
    memcpy(enc->footer, foot_p, SEMQI_FOOTER_BYTES);
    *out = enc;
    semqi_ok(err);
    return SEMQ_OK;
}
