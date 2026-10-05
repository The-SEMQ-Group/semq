/*
 * Copyright (c) 2026 The SEMQ Group Inc.
 * Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
 */
/* A codec is refused when its kernel fails the known-answer self-test. The
 * test library can force that failure; a production build cannot. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "semq.h"
#include "semq_alloc_test.h"

static void expect(int ok, const char* what) {
    if (!ok) {
        fprintf(stderr, "FAIL: %s\n", what);
        exit(1);
    }
}

int main(void) {
    semq_config_t cfgs[3];
    expect(semq_config_orbit(16u, 50u, &cfgs[0], NULL) == SEMQ_OK, "orbit config");
    expect(semq_config_phase(16u, 8u, &cfgs[1], NULL) == SEMQ_OK, "phase config");
    expect(semq_config_quant(16u, 4u, &cfgs[2], NULL) == SEMQ_OK, "quant config");
    for (int i = 0; i < 3; i++) {
        semq_codec_t* codec = NULL;
        semq_error_t err;
        expect(semq_codec_create(&cfgs[i], &codec, &err) == SEMQ_OK, "a sound build passes the self-test");
        semq_codec_free(codec);

        semqi_test_corrupt_self_test(1u);
        codec = NULL;
        expect(semq_codec_create(&cfgs[i], &codec, &err) == SEMQ_ERR_INTERNAL, "a failed self-test is SEMQ_ERR_INTERNAL");
        expect(codec == NULL, "a failed self-test returns no codec");
        expect(strstr(err.message, "self-test failed") != NULL, "the error names the self-test");
        semqi_test_corrupt_self_test(0u);
    }
    expect(semqi_test_alloc_live() == 0u, "no allocation is leaked");
    puts("self-test: ok");
    return 0;
}
