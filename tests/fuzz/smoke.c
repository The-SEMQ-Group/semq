/* Deterministic mutations of every reference image, using the libFuzzer
 * harness also on compilers without a libFuzzer runtime. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int LLVMFuzzerTestOneInput(const uint8_t* data, size_t size);
#define CHECK(x) do { if (!(x)) abort(); } while (0)

int main(int argc, char** argv) {
    CHECK(argc > 1);
    uint32_t random = 0x53454d51u;
    size_t calls = 0u;
    for (int i = 1; i < argc; i++) {
        FILE* f = fopen(argv[i], "rb");
        CHECK(f != NULL && fseek(f, 0, SEEK_END) == 0);
        const long length = ftell(f);
        CHECK(length > 0 && length < 4 * 1024 * 1024 && fseek(f, 0, SEEK_SET) == 0);
        const size_t n = (size_t)length;
        uint8_t* data = (uint8_t*)malloc(n);
        uint8_t* copy = (uint8_t*)malloc(n + 1u);
        CHECK(data != NULL && copy != NULL);
        CHECK(fread(data, 1u, n, f) == n && fclose(f) == 0);
        LLVMFuzzerTestOneInput(data, n); calls++;
        /* Every truncation for these small fixtures; bounded for future seeds. */
        for (size_t cut = 0u; cut < n && cut < 4096u; cut++) {
            LLVMFuzzerTestOneInput(data, cut); calls++;
        }
        memcpy(copy, data, n); copy[n] = 0u;
        LLVMFuzzerTestOneInput(copy, n + 1u); calls++;
        for (size_t mutation = 0u; mutation < 1024u; mutation++) {
            memcpy(copy, data, n);
            random = random * 1664525u + 1013904223u;
            const size_t at = (size_t)random % n;
            random = random * 1664525u + 1013904223u;
            copy[at] ^= (uint8_t)(random >> 24u);
            LLVMFuzzerTestOneInput(copy, n); calls++;
        }
        free(copy); free(data);
    }
    printf("reader smoke: %zu inputs from %d reference images\n", calls, argc - 1);
    return 0;
}
