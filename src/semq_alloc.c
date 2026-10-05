/*
 * Copyright (c) 2026 The SEMQ Group Inc.
 * Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
 */
/* Allocation boundary. Fault controls exist only in the test library. */
#include <stdlib.h>
#include "semq_internal.h"

#ifdef SEMQ_TEST_ALLOCATOR
#include "semq_alloc_test.h"
static uint64_t attempts;
static uint64_t fail_at;
static uint64_t live;
void semqi_test_fail_alloc(uint64_t ordinal) { attempts = 0u; fail_at = ordinal; }
uint64_t semqi_test_alloc_attempts(void) { return attempts; }
uint64_t semqi_test_alloc_live(void) { return live; }
#endif

void* semqi_alloc(uint64_t bytes) {
    if (semqi_too_big(bytes)) return NULL;
#ifdef SEMQ_TEST_ALLOCATOR
    attempts++;
    if (fail_at != 0u && attempts == fail_at) return NULL;
#endif
    void* p = malloc(bytes == 0u ? 1u : (size_t)bytes);
#ifdef SEMQ_TEST_ALLOCATOR
    if (p != NULL) live++;
#endif
    return p;
}

void* semqi_calloc(uint64_t count, uint64_t size) {
    uint64_t bytes;
    if (semqi_mul_ovf(count, size, &bytes)) return NULL;
    void* p = semqi_alloc(bytes);
    if (p != NULL) memset(p, 0, (size_t)bytes);
    return p;
}

void semqi_free(void* p) {
#ifdef SEMQ_TEST_ALLOCATOR
    if (p != NULL) {
        if (live == 0u) abort();
        live--;
    }
#endif
    free(p);
}
