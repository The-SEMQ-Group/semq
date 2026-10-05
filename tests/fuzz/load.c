#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "semq.h"
#include "semq_sha256.h"

#define CHECK(x) do { if (!(x)) abort(); } while (0)

static void try_image(const uint8_t* data, size_t size, int repair) {
    semq_encoding_t* enc = NULL;
    semq_error_t err;
    const semq_status_t status = semq_encoding_load(data, (uint64_t)size, &enc, &err);
    CHECK(err.status == (uint32_t)status);
    if (status != SEMQ_OK) {
        CHECK(enc == NULL && status != SEMQ_ERR_INTERNAL);
        /* An integrity error means framing, config, lengths, ids and manifest
         * already validated. Repair identities to reach row validation too. */
        if (repair && status == SEMQ_ERR_INTEGRITY) {
            uint64_t n; memcpy(&n, data + 20u, 8u);
            semq_config_t cfg;
            CHECK(semq_config_from_bytes(data + 6u, &cfg, NULL) == SEMQ_OK);
            uint64_t ids_len = n * 8u;
            if (data[19] == SEMQ_ID_UTF8) {
                uint64_t last; memcpy(&last, data + 28u + n * 8u, 8u);
                ids_len = (n + 1u) * 8u + last;
            }
            const size_t manifest = 28u + (size_t)ids_len + (size_t)n * semq_config_bytes_per_vector(&cfg);
            CHECK(manifest <= size - 64u);
            uint8_t* copy = (uint8_t*)malloc(size);
            if (copy == NULL) return;
            memcpy(copy, data, size);
            semq_sha256(copy + 6u, (uint64_t)(manifest - 6u), copy + size - 64u);
            semq_sha256_ctx_t h;
            semq_sha256_init(&h);
            semq_sha256_update(&h, copy + size - 64u, 32u);
            semq_sha256_update(&h, copy + manifest, size - 64u - manifest);
            semq_sha256_final(&h, copy + size - 32u);
            try_image(copy, size, 0);
            free(copy);
        }
        return;
    }
    CHECK(enc != NULL && semq_encoding_file_size(enc) == size);
    uint8_t* image = (uint8_t*)malloc(size);
    if (image != NULL) {
        CHECK(semq_encoding_save(enc, image, (uint64_t)size, &err) == SEMQ_OK);
        CHECK(memcmp(image, data, size) == 0);
        free(image);
    }
    semq_encoding_free(enc);
}

int LLVMFuzzerTestOneInput(const uint8_t* data, size_t size);
int LLVMFuzzerTestOneInput(const uint8_t* data, size_t size) {
    try_image(data, size, 1);
    return 0;
}
