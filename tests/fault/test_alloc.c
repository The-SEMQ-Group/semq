/*
 * Copyright (c) 2026 The SEMQ Group Inc.
 * Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "semq.h"
#include "semq_alloc_test.h"

#define REQUIRE(x) do { if (!(x)) { fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, #x); abort(); } } while (0)

static void exercise(uint32_t kind) {
    const semq_config_t cfg = { SEMQ_QUANT, 4u, 4u, SEMQ_RULE_REVISION };
    const uint64_t uids[] = { 1u, 2u }, offs[] = { 0u, 1u, 2u };
    const uint8_t text[] = { 'a', 'b' }, rows[] = { 0u, 0u, 1u, 0u }, changed[] = { 2u, 0u, 1u, 0u };
    const float vectors[] = { 1, 0, 0, 0, 0, 1, 0, 0 };
    const semq_ids_t ids = { kind, 2u, uids, offs, text };
    const semq_pair_t man = { (const uint8_t*)"note", 4u, (const uint8_t*)"value", 5u };
    semq_codec_t* codec = NULL;
    semq_encoding_t *a = NULL, *b = NULL, *empty = NULL;
    semq_diff_t* diff = NULL;
    semq_floor_t* floor = NULL;
    semq_error_t err;
    REQUIRE(semq_codec_create(&cfg, &codec, &err) == SEMQ_OK);
    REQUIRE(semq_encoding_create(&cfg, &ids, rows, &man, 1u, &a, &err) == SEMQ_OK);
    REQUIRE(semq_encoding_create(&cfg, &ids, changed, &man, 1u, &b, &err) == SEMQ_OK);
    const semq_ids_t none = { kind, 0u, NULL, NULL, NULL };
    REQUIRE(semq_encoding_create(&cfg, &none, NULL, &man, 1u, &empty, &err) == SEMQ_OK);
    REQUIRE(semq_encoding_diff(a, b, &diff, &err) == SEMQ_OK);
    const semq_diff_t* nulls[] = { diff };
    REQUIRE(semq_floor_measure(nulls, 1u, &floor, &err) == SEMQ_OK);
    uint8_t rid[32]; semq_encoding_state_id(a, rid);
    const uint64_t image_size = semq_encoding_file_size(a);
    uint8_t* image = (uint8_t*)malloc((size_t)image_size);
    REQUIRE(image != NULL);
    REQUIRE(semq_encoding_save(a, image, image_size, &err) == SEMQ_OK);
    const semq_encoding_t* parts[] = { a, empty };
    const uint64_t baseline = semqi_test_alloc_live();

    /* Every allocation of every allocating public path is failed in turn.
     * The first non-failing ordinal terminates each sweep. */
    for (int operation = 0; operation < 10; operation++) {
        uint64_t ordinal;
        for (ordinal = 1u; ordinal < 100u; ordinal++) {
            semq_codec_t* c = NULL; semq_encoding_t* e = NULL;
            semq_diff_t* d = NULL; semq_floor_t* f = NULL;
            float representatives[8]; uint64_t count = 99u; int within = -1;
            semqi_test_fail_alloc(ordinal);
            semq_status_t status;
            switch (operation) {
                case 0: status = semq_codec_create(&cfg, &c, &err); break;
                case 1: status = semq_codec_encode(codec, &ids, vectors, &man, 1u, &e, &err); break;
                case 2: status = semq_encoding_create(&cfg, &ids, rows, &man, 1u, &e, &err); break;
                case 3: status = semq_encoding_load(image, image_size, &e, &err); break;
                case 4: status = semq_encoding_concat(parts, 2u, &e, &err); break;
                case 5: status = semq_encoding_diff(a, b, &d, &err); break;
                case 6: status = semq_floor_measure(nulls, 1u, &f, &err); break;
                case 7: status = semq_diff_within(diff, floor, &within, &err); break;
                case 8: status = semq_codec_decode(codec, a, representatives, &err); break;
                default:
                    status = kind == SEMQ_ID_U64
                        ? semq_diff_units_u64(diff, 1u, NULL, NULL, NULL, 0u, &count, &err)
                        : semq_diff_units_utf8(diff, text, 1u, NULL, NULL, NULL, 0u, &count, &err);
            }
            const uint64_t attempts = semqi_test_alloc_attempts();
            if (attempts >= ordinal) {
                REQUIRE(status == SEMQ_ERR_NOMEM && err.status == SEMQ_ERR_NOMEM);
                REQUIRE(c == NULL && e == NULL && d == NULL && f == NULL);
            } else REQUIRE(status == SEMQ_OK);
            semq_codec_free(c); semq_encoding_free(e); semq_diff_free(d); semq_floor_free(f);
            REQUIRE(semqi_test_alloc_live() == baseline);
            semqi_test_fail_alloc(0u);
            uint8_t after[32]; semq_encoding_state_id(a, after);
            REQUIRE(memcmp(rid, after, 32u) == 0);
            if (attempts < ordinal) break;
        }
        REQUIRE(ordinal < 100u);
        printf("kind=%u operation=%d allocations=%llu checked\n", kind, operation, (unsigned long long)(ordinal - 1u));
    }
    free(image);
    semq_floor_free(floor); semq_diff_free(diff);
    semq_encoding_free(a); semq_encoding_free(b); semq_encoding_free(empty); semq_codec_free(codec);
    REQUIRE(semqi_test_alloc_live() == 0u);
}

int main(void) { exercise(SEMQ_ID_U64); exercise(SEMQ_ID_UTF8); return 0; }
