/*
 * Copyright (c) 2026 The SEMQ Group Inc.
 * Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
 */

#ifndef SEMQ_ALLOC_TEST_H
#define SEMQ_ALLOC_TEST_H
#include <stdint.h>
/* Reset attempts, fail exactly this allocation (0 disables injection).
 * Existing live allocations stay counted across a test operation. */
void semqi_test_fail_alloc(uint64_t ordinal);
uint64_t semqi_test_alloc_attempts(void);
uint64_t semqi_test_alloc_live(void);
/* Make every codec self-test fail (0 restores normal checking). */
void semqi_test_corrupt_self_test(uint32_t on);
#endif
