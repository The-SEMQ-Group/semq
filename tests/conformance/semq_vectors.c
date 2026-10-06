/*
 * Copyright (c) 2026 The SEMQ Group Inc.
 * Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
 */

/*
 * semq_vectors.c — the conformance vector generator.
 *
 * Built from the same sources as the library, it writes one directory per
 * vector under the output directory given as argv[1]: a manifest.json with
 * the cases and their expectations, plus the binary files the manifest
 * references. Hosts consume these directories; they never generate them.
 *
 * Kernel-level properties that no host can reach (the fixed point of
 * vector 5b, the FZ/DAZ and rounding-mode behavior of vector 15) are
 * checked here and recorded as booleans in the manifests.
 */

#if defined(_MSC_VER) && !defined(_CRT_SECURE_NO_WARNINGS)
#define _CRT_SECURE_NO_WARNINGS /* fopen on MSVC */
#endif

#include <fenv.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#include "semq.h"
#include "core/semq_dispatch.h"

#if defined(_WIN32)
  #include <direct.h>
  #define MKDIR(p) _mkdir(p)
#else
  #define MKDIR(p) mkdir((p), 0755)
#endif

static const char* OUT = ".";

static void die(const char* what) {
    fprintf(stderr, "semq_vectors: %s\n", what);
    exit(1);
}

static void* xmalloc(size_t n) {
    void* p = malloc(n == 0u ? 1u : n);
    if (p == NULL) die("out of memory");
    return p;
}

/* -------------------------------------------------------------------------- */
/*  Files                                                                     */
/* -------------------------------------------------------------------------- */

static char g_dir[512];

static void begin_vector(const char* name) {
    snprintf(g_dir, sizeof(g_dir), "%s/%s", OUT, name);
    if (MKDIR(g_dir) != 0) {
        struct stat st;
        if (stat(g_dir, &st) != 0) die("cannot create vector directory");
    }
}

static void write_file(const char* name, const void* data, size_t len) {
    char path[768];
    snprintf(path, sizeof(path), "%s/%s", g_dir, name);
    FILE* f = fopen(path, "wb");
    if (f == NULL) die("cannot open output file");
    if (len > 0u && fwrite(data, 1u, len, f) != len) die("short write");
    fclose(f);
}

/* `base` with the first occurrence of `from` replaced by `to`, NUL-terminated. */
static char* splice(const char* base, const char* from, const char* to) {
    const char* at = strstr(base, from);
    if (at == NULL) die("splice: pattern not found");
    const size_t head = (size_t)(at - base), n = strlen(base) - strlen(from) + strlen(to);
    char* out = (char*)xmalloc(n + 1u);
    memcpy(out, base, head);
    memcpy(out + head, to, strlen(to));
    strcpy(out + head + strlen(to), at + strlen(from));
    return out;
}

static FILE* g_json = NULL;
static int   g_first[32];
static int   g_depth = 0;

static void js_open(void) {
    char path[768];
    snprintf(path, sizeof(path), "%s/manifest.json", g_dir);
    g_json = fopen(path, "wb");
    if (g_json == NULL) die("cannot open manifest.json");
    g_depth = 0;
}

static void js_close(void) {
    fputc('\n', g_json);
    fclose(g_json);
    g_json = NULL;
}

static void js_sep(void) {
    if (g_depth > 0 && !g_first[g_depth - 1]) fputc(',', g_json);
    if (g_depth > 0) g_first[g_depth - 1] = 0;
}

static void js_string_raw(const char* s, size_t len) {
    fputc('"', g_json);
    for (size_t i = 0u; i < len; i++) {
        const unsigned char c = (unsigned char)s[i];
        if (c == '"' || c == '\\') { fputc('\\', g_json); fputc((int)c, g_json); }
        else if (c < 0x20u) fprintf(g_json, "\\u%04x", c);
        else fputc((int)c, g_json);
    }
    fputc('"', g_json);
}

static void js_key(const char* key) {
    js_sep();
    js_string_raw(key, strlen(key));
    fputc(':', g_json);
    /* The value that follows is the first item of nothing: mark so js_sep
     * does not emit a comma before it. */
    if (g_depth > 0) g_first[g_depth - 1] = 1;
}

static void js_begin_object(void) { js_sep(); fputc('{', g_json); g_first[g_depth++] = 1; }
static void js_end_object(void)   { g_depth--; fputc('}', g_json); }
static void js_begin_array(void)  { js_sep(); fputc('[', g_json); g_first[g_depth++] = 1; }
static void js_end_array(void)    { g_depth--; fputc(']', g_json); }
static void js_str(const char* s) { js_sep(); js_string_raw(s, strlen(s)); }
static void js_strn(const uint8_t* s, size_t n) { js_sep(); js_string_raw((const char*)s, n); }
static void js_u64(uint64_t v)    { js_sep(); fprintf(g_json, "%llu", (unsigned long long)v); }
static void js_bool(int b)        { js_sep(); fputs(b ? "true" : "false", g_json); }
static void js_null(void)         { js_sep(); fputs("null", g_json); }
static void js_hex(const uint8_t* b, size_t n) {
    js_sep();
    fputc('"', g_json);
    for (size_t i = 0u; i < n; i++) fprintf(g_json, "%02x", b[i]);
    fputc('"', g_json);
}
static void js_u64_str(uint64_t v) { js_sep(); fprintf(g_json, "\"%llu\"", (unsigned long long)v); }

static void js_kv_str(const char* k, const char* v) { js_key(k); js_str(v); }
static void js_kv_u64(const char* k, uint64_t v) { js_key(k); js_u64(v); }
static void js_kv_hex(const char* k, const uint8_t* b, size_t n) { js_key(k); js_hex(b, n); }
static void js_kv_bool(const char* k, int b) { js_key(k); js_bool(b); }

static void js_header(uint32_t number, const char* name) {
    js_begin_object();
    js_kv_u64("vector", number);
    js_kv_str("name", name);
    js_kv_str("spec_version", "2");
    js_kv_u64("rule_revision", SEMQ_RULE_REVISION);
    js_key("cases");
    js_begin_array();
}

static void js_footer(void) {
    js_end_array();
    js_end_object();
    js_close();
}

static const char* error_name(uint32_t status) {
    switch (status) {
        case SEMQ_ERR_INVALID_INPUT: return "InvalidInput";
        case SEMQ_ERR_INCOMPATIBLE:  return "Incompatible";
        case SEMQ_ERR_FORMAT:        return "FormatError";
        case SEMQ_ERR_INTEGRITY:     return "IntegrityError";
        case SEMQ_ERR_UNSUPPORTED:   return "Unsupported";
        default:                     return "Native";
    }
}

/* Write {"error": ..., "row": ..., "field": ..., "which": ...}. */
static void js_error(const semq_error_t* e) {
    js_begin_object();
    js_kv_str("error", error_name(e->status));
    js_key("row");
    if (e->row == SEMQ_NONE) js_null(); else js_u64(e->row);
    js_key("field");
    if (e->field == SEMQ_NONE) js_null(); else js_u64(e->field);
    js_key("which");
    if (e->which == SEMQ_WHICH_CONTENT) js_str("content");
    else if (e->which == SEMQ_WHICH_STATE) js_str("state");
    else js_null();
    js_end_object();
}

static void js_config(const semq_config_t* c) {
    js_begin_object();
    js_kv_str("operator", c->op == SEMQ_ORBIT ? "orbit" : c->op == SEMQ_PHASE ? "phase" : "quant");
    js_kv_u64("dim", c->dim);
    js_kv_u64(c->op == SEMQ_ORBIT ? "scale" : c->op == SEMQ_PHASE ? "sectors" : "bins", c->p1);
    js_kv_u64("rule_revision", c->p2);
    js_end_object();
}

/* The floor report: the fields of a floor as every host's `as_dict` emits them. */
static void js_floor_fields(const semq_config_t* c, uint32_t kind, const uint8_t rid[32], uint64_t nulls,
                            uint64_t changed, uint64_t total, uint64_t hamming, uint64_t max_hamming) {
    js_begin_object();
    js_kv_str("version", "semq-floor/1");
    js_key("config"); js_config(c);
    js_kv_str("id_kind", kind == SEMQ_ID_U64 ? "u64" : kind == SEMQ_ID_UTF8 ? "utf8" : "unknown");
    js_kv_hex("reference_id", rid, 32u);
    js_kv_u64("nulls", nulls);
    js_kv_u64("changed_rows", changed);
    js_kv_u64("total_rows", total);
    js_kv_u64("hamming", hamming);
    if (max_hamming != SEMQ_NONE) js_kv_u64("max_hamming", max_hamming);
    js_end_object();
}
static void js_floor(const semq_floor_t* f) {
    uint8_t rid[32];
    semq_floor_reference_id(f, rid);
    js_floor_fields(semq_floor_config(f), semq_floor_id_kind(f), rid, semq_floor_nulls(f), semq_floor_changed_rows(f),
                    semq_floor_total_rows(f), semq_floor_hamming(f), semq_floor_max_hamming(f));
}

/* -------------------------------------------------------------------------- */
/*  Deterministic inputs                                                      */
/* -------------------------------------------------------------------------- */

static uint32_t g_lcg = 20260909u;
static float lcg_unit(void) {
    g_lcg = g_lcg * 1664525u + 1013904223u;
    return ((float)(g_lcg >> 8) / 16777216.0f) * 2.0f - 1.0f;  /* [-1, 1) */
}

/* Fill `n` rows of `dim` with unit-norm float32 values. */
static void unit_rows(float* out, uint32_t n, uint32_t dim) {
    for (uint32_t r = 0u; r < n; r++) {
        float* row = out + (size_t)r * dim;
        double s = 0.0;
        for (uint32_t i = 0u; i < dim; i++) { row[i] = lcg_unit(); s += (double)row[i] * (double)row[i]; }
        const double inv = 1.0 / sqrt(s);
        for (uint32_t i = 0u; i < dim; i++) row[i] = (float)((double)row[i] * inv);
    }
}

/* Re-normalize in binary64 after edits, then cast. */
static void renorm(float* row, uint32_t dim) {
    double s = 0.0;
    for (uint32_t i = 0u; i < dim; i++) s += (double)row[i] * (double)row[i];
    if (s == 0.0) { row[0] = 1.0f; return; }
    const double inv = 1.0 / sqrt(s);
    for (uint32_t i = 0u; i < dim; i++) row[i] = (float)((double)row[i] * inv);
}

static semq_config_t cfg_of(uint32_t op, uint32_t dim, uint32_t p1) {
    semq_config_t c;
    semq_error_t err;
    semq_status_t s = op == SEMQ_ORBIT ? semq_config_orbit(dim, p1, &c, &err)
                    : op == SEMQ_PHASE ? semq_config_phase(dim, p1, &c, &err)
                    : semq_config_quant(dim, p1, &c, &err);
    if (s != SEMQ_OK) die("invalid config in generator");
    return c;
}

static semq_encoding_t* encode_u64(const semq_config_t* c, const uint64_t* ids, uint64_t n,
                                   const float* vectors, const semq_pair_t* man, uint32_t n_pairs,
                                   semq_error_t* err) {
    semq_codec_t* codec = NULL;
    if (semq_codec_create(c, &codec, err) != SEMQ_OK) die("codec");
    semq_ids_t in = { SEMQ_ID_U64, n, ids, NULL, NULL };
    semq_encoding_t* e = NULL;
    semq_codec_encode(codec, &in, vectors, man, n_pairs, &e, err);
    semq_codec_free(codec);
    return e;
}

static semq_encoding_t* create_rows(const semq_config_t* c, const semq_ids_t* ids, const uint8_t* rows,
                                    const semq_pair_t* man, uint32_t n_pairs, semq_error_t* err) {
    semq_encoding_t* e = NULL;
    semq_encoding_create(c, ids, rows, man, n_pairs, &e, err);
    return e;
}

static uint8_t* image_of(const semq_encoding_t* e, uint64_t* len) {
    *len = semq_encoding_file_size(e);
    uint8_t* buf = (uint8_t*)xmalloc((size_t)*len);
    if (semq_encoding_save(e, buf, *len, NULL) != SEMQ_OK) die("save");
    return buf;
}

/* -------------------------------------------------------------------------- */
/*  0: sha256-fips                                                            */
/* -------------------------------------------------------------------------- */

static void sha_case(const char* id, const uint8_t* msg, size_t len, const char* repeat, uint64_t count) {
    uint8_t d[32];
    semq_sha256(msg, len, d);
    js_begin_object();
    js_kv_str("id", id);
    js_key("input");
    js_begin_object();
    if (repeat) { js_kv_str("repeat", repeat); js_kv_u64("count", count); }
    else { js_key("ascii"); js_strn(msg, len); }
    js_end_object();
    js_key("expect");
    js_begin_object();
    js_kv_hex("digest", d, 32u);
    js_end_object();
    js_end_object();
}

static void vector_00(void) {
    begin_vector("00-sha256-fips");
    js_open();
    js_header(0u, "sha256-fips");
    sha_case("empty", (const uint8_t*)"", 0u, NULL, 0u);
    sha_case("abc", (const uint8_t*)"abc", 3u, NULL, 0u);
    const char* m56 = "abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq";
    sha_case("bytes-56", (const uint8_t*)m56, strlen(m56), NULL, 0u);
    const char* m112 = "abcdefghbcdefghicdefghijdefghijkefghijklfghijklmghijklmnhijklmnoijklmnopjklmnopqklmnopqrlmnopqrsmnopqrstnopqrstu";
    sha_case("bytes-112", (const uint8_t*)m112, strlen(m112), NULL, 0u);
    uint8_t* mega = (uint8_t*)xmalloc(1000000u);
    memset(mega, 'a', 1000000u);
    sha_case("million-a", mega, 1000000u, "a", 1000000u);
    free(mega);
    js_footer();
}

/* -------------------------------------------------------------------------- */
/*  1 and 2: config-canonical, config-derived                                 */
/* -------------------------------------------------------------------------- */

typedef struct { uint32_t op, dim, p1; } grid_t;

static const uint32_t DIMS[] = { 1u, 2u, 4u, 384u, 1024u, 4096u, 65536u };
static const uint32_t BINS[] = { 2u, 3u, 4u, 8u, 16u, 63u, 64u };
static const uint32_t SECTORS[] = { 2u, 15u, 16u, 17u, 255u, 256u };
static const uint32_t SCALES[] = { 1u, 50u, 1u << 30 };

static int grid_valid(uint32_t op, uint32_t dim, uint32_t p1) {
    semq_config_t c;
    c.op = op; c.dim = dim; c.p1 = p1; c.p2 = 0u;
    return semq_config_validate(&c, NULL) == SEMQ_OK;
}

static void each_valid(void (*fn)(uint32_t, uint32_t, uint32_t)) {
    for (size_t d = 0u; d < sizeof(DIMS) / sizeof(DIMS[0]); d++) {
        for (size_t i = 0u; i < sizeof(BINS) / sizeof(BINS[0]); i++) if (grid_valid(SEMQ_QUANT, DIMS[d], BINS[i])) fn(SEMQ_QUANT, DIMS[d], BINS[i]);
        for (size_t i = 0u; i < sizeof(SECTORS) / sizeof(SECTORS[0]); i++) if (grid_valid(SEMQ_PHASE, DIMS[d], SECTORS[i])) fn(SEMQ_PHASE, DIMS[d], SECTORS[i]);
        for (size_t i = 0u; i < sizeof(SCALES) / sizeof(SCALES[0]); i++) if (grid_valid(SEMQ_ORBIT, DIMS[d], SCALES[i])) fn(SEMQ_ORBIT, DIMS[d], SCALES[i]);
    }
}

static void config_case_input(uint32_t op, uint32_t dim, uint32_t p1) {
    js_key("input");
    js_begin_object();
    js_kv_str("operator", op == SEMQ_ORBIT ? "orbit" : op == SEMQ_PHASE ? "phase" : "quant");
    js_kv_u64("dim", dim);
    js_kv_u64("parameter", p1);
    js_end_object();
}

static void v01_valid(uint32_t op, uint32_t dim, uint32_t p1) {
    semq_config_t c = cfg_of(op, dim, p1);
    uint8_t b[13];
    semq_config_to_bytes(&c, b);
    js_begin_object();
    char id[64];
    snprintf(id, sizeof(id), "%s-%u-%u", op == SEMQ_ORBIT ? "orbit" : op == SEMQ_PHASE ? "phase" : "quant", dim, p1);
    js_kv_str("id", id);
    config_case_input(op, dim, p1);
    js_key("expect");
    js_begin_object();
    js_kv_hex("bytes", b, 13u);
    js_end_object();
    js_end_object();
}

static void v01_invalid(const char* id, uint32_t op, uint32_t dim, uint32_t p1) {
    semq_config_t c;
    semq_error_t err;
    semq_status_t s = op == SEMQ_ORBIT ? semq_config_orbit(dim, p1, &c, &err)
                    : op == SEMQ_PHASE ? semq_config_phase(dim, p1, &c, &err)
                    : semq_config_quant(dim, p1, &c, &err);
    if (s == SEMQ_OK) die("expected an invalid config");
    js_begin_object();
    js_kv_str("id", id);
    config_case_input(op, dim, p1);
    js_key("expect");
    js_error(&err);
    js_end_object();
}

static void vector_01(void) {
    begin_vector("01-config-canonical");
    js_open();
    js_header(1u, "config-canonical");
    each_valid(v01_valid);
    v01_invalid("quant-bins-1", SEMQ_QUANT, 4u, 1u);
    v01_invalid("quant-bins-65", SEMQ_QUANT, 4u, 65u);
    v01_invalid("quant-dim-0", SEMQ_QUANT, 0u, 4u);
    v01_invalid("quant-dim-65537", SEMQ_QUANT, 65537u, 4u);
    v01_invalid("phase-dim-odd", SEMQ_PHASE, 7u, 16u);
    v01_invalid("phase-dim-not-multiple-of-4", SEMQ_PHASE, 6u, 16u);
    v01_invalid("phase-sectors-1", SEMQ_PHASE, 8u, 1u);
    v01_invalid("phase-sectors-257", SEMQ_PHASE, 8u, 257u);
    v01_invalid("orbit-scale-0", SEMQ_ORBIT, 8u, 0u);
    v01_invalid("orbit-scale-2^30+1", SEMQ_ORBIT, 8u, (1u << 30) + 1u);
    js_footer();
}

static void v02_case(uint32_t op, uint32_t dim, uint32_t p1) {
    semq_config_t c = cfg_of(op, dim, p1);
    js_begin_object();
    char id[64];
    snprintf(id, sizeof(id), "%s-%u-%u", op == SEMQ_ORBIT ? "orbit" : op == SEMQ_PHASE ? "phase" : "quant", dim, p1);
    js_kv_str("id", id);
    config_case_input(op, dim, p1);
    js_key("expect");
    js_begin_object();
    js_kv_u64("bytes_per_vector", semq_config_bytes_per_vector(&c));
    js_kv_u64("units_per_row", semq_config_units_per_row(&c));
    if (op == SEMQ_QUANT) {
        const float m = semq_config_max_magnitude(&c);
        uint32_t bits;
        memcpy(&bits, &m, 4u);
        char hex[16];
        snprintf(hex, sizeof(hex), "%08x", bits);
        js_kv_str("max_magnitude_bits", hex);
    }
    js_end_object();
    js_end_object();
}

static void vector_02(void) {
    begin_vector("02-config-derived");
    js_open();
    js_header(2u, "config-derived");
    each_valid(v02_case);
    js_footer();
}

/* -------------------------------------------------------------------------- */
/*  3, 5: encode, decode (plus 5b inside the generator)                       */
/* -------------------------------------------------------------------------- */

typedef struct { const char* id; uint32_t op; uint32_t p1; } enc_cfg_t;

static const enc_cfg_t ENC_GRID[] = {
    { "quant-2", SEMQ_QUANT, 2u }, { "quant-4", SEMQ_QUANT, 4u }, { "quant-8", SEMQ_QUANT, 8u },
    { "quant-64", SEMQ_QUANT, 64u }, { "phase-16", SEMQ_PHASE, 16u }, { "phase-17", SEMQ_PHASE, 17u },
    { "phase-256", SEMQ_PHASE, 256u }, { "orbit-50", SEMQ_ORBIT, 50u }, { "orbit-1", SEMQ_ORBIT, 1u },
    { "orbit-2^30", SEMQ_ORBIT, 1u << 30 },
};

/* The two input sets: a seeded set and an edge set with coordinates on bin
 * edges, at +/- max_magnitude, on sector boundaries and with subnormals. */
static float* g_seeded;   /* 64 x 32 */
static float* g_edges;    /* 64 x 64 */
#define SEEDED_N 64u
#define SEEDED_DIM 32u
#define EDGE_N 64u
#define EDGE_DIM 64u

static void build_inputs(void) {
    g_seeded = (float*)xmalloc(SEEDED_N * SEEDED_DIM * sizeof(float));
    unit_rows(g_seeded, SEEDED_N, SEEDED_DIM);
    g_edges = (float*)xmalloc(EDGE_N * EDGE_DIM * sizeof(float));
    const float M4 = (float)(2.0 / sqrt((double)EDGE_DIM)); /* quant(64, bins) max magnitude */
    for (uint32_t r = 0u; r < EDGE_N; r++) {
        float* row = g_edges + (size_t)r * EDGE_DIM;
        for (uint32_t i = 0u; i < EDGE_DIM; i++) row[i] = 0.0f;
        switch (r % 8u) {
            case 0: /* one-hot: saturates quant, exact sector on an axis */
                row[r % EDGE_DIM] = 1.0f; break;
            case 1: /* +/- max_magnitude on a few coordinates, rest spread */
                row[0] = M4; row[1] = -M4; row[2] = M4 * 0.5f;
                for (uint32_t i = 3u; i < EDGE_DIM; i++) row[i] = lcg_unit() * 0.1f;
                renorm(row, EDGE_DIM); break;
            case 2: /* bin edges: k * M / bins for bins = 4 and 8 */
                for (uint32_t i = 0u; i < EDGE_DIM; i++) row[i] = (float)((double)(int32_t)(i % 9u) - 4.0) * M4 / 4.0f;
                renorm(row, EDGE_DIM); break;
            case 3: /* subnormals and both zeros mixed with a unit direction */
                row[0] = 1.0f; row[1] = 1e-40f; row[2] = -1e-41f; row[3] = -0.0f; row[4] = 0.0f; break;
            case 4: /* 45-degree and 135-degree pairs: sector boundaries */
                for (uint32_t i = 0u; i < EDGE_DIM; i += 2u) { row[i] = (i % 4u == 0u) ? 1.0f : -1.0f; row[i + 1u] = 1.0f; }
                renorm(row, EDGE_DIM); break;
            case 5: /* uniform magnitude, alternating sign */
                for (uint32_t i = 0u; i < EDGE_DIM; i++) row[i] = (i & 1u) ? -1.0f : 1.0f;
                renorm(row, EDGE_DIM); break;
            case 6: /* exact halves for orbit rounding ties at scale 50: x*50 = k + 0.5 */
                for (uint32_t i = 0u; i < EDGE_DIM; i++) row[i] = (float)(((double)(i % 7u) + 0.5) / 50.0);
                renorm(row, EDGE_DIM); break;
            default: /* random */
                for (uint32_t i = 0u; i < EDGE_DIM; i++) row[i] = lcg_unit();
                renorm(row, EDGE_DIM); break;
        }
    }
}

static void encode_set(const char* set, const float* vectors, uint32_t n, uint32_t dim, const enc_cfg_t* g,
                       int decode_vector) {
    if (!grid_valid(g->op, dim, g->p1)) return;
    semq_config_t c = cfg_of(g->op, dim, g->p1);
    uint64_t* ids = (uint64_t*)xmalloc(n * sizeof(uint64_t));
    for (uint32_t i = 0u; i < n; i++) ids[i] = i;
    semq_error_t err;
    semq_encoding_t* e = encode_u64(&c, ids, n, vectors, NULL, 0u, &err);
    if (e == NULL) die("encode failed in vector 3");
    semq_codec_t* codec = NULL;
    semq_codec_create(&c, &codec, NULL);
    const uint32_t units = semq_config_units_per_row(&c);
    uint8_t* symbols = (uint8_t*)xmalloc((size_t)n * units);
    semq_codec_unpack(codec, e, symbols, NULL);
    uint64_t rows_len;
    const uint8_t* rows = semq_encoding_rows(e, &rows_len);
    char f_rows[128], f_sym[128], f_rep[128], f_in[128];
    snprintf(f_in, sizeof(f_in), "%s-input.f32", set);
    snprintf(f_rows, sizeof(f_rows), "%s-%s-rows.bin", set, g->id);
    snprintf(f_sym, sizeof(f_sym), "%s-%s-symbols.bin", set, g->id);
    snprintf(f_rep, sizeof(f_rep), "%s-%s-representatives.f32", set, g->id);
    if (!decode_vector) {
        write_file(f_rows, rows, (size_t)rows_len);
        write_file(f_sym, symbols, (size_t)n * units);
    } else {
        float* rep = (float*)xmalloc((size_t)n * dim * sizeof(float));
        semq_codec_decode(codec, e, rep, NULL);
        write_file(f_rep, rep, (size_t)n * dim * sizeof(float));
        /* 5b: kernel_encode(representatives) == rows, without the norm check. */
        const semq_backend_kind_t kind = semq_dispatch_select();
        const uint32_t bpv = semq_config_bytes_per_vector(&c);
        uint8_t* again = (uint8_t*)xmalloc(bpv);
        for (uint32_t r = 0u; r < n; r++) {
            const float* row = rep + (size_t)r * dim;
            if (c.op == SEMQ_ORBIT) {
                static const uint8_t SPARSE_TO_DENSE[30] = {
                    0, 10, 11, 12, 13, 14, 15, 16, 17, 18, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9 };
                semq_dispatch_get(kind)->encode(row, dim, c.p1, again);
                for (uint32_t i = 0u; i < dim; i++) again[i] = SPARSE_TO_DENSE[again[i]];
            } else if (c.op == SEMQ_PHASE) {
                semq_dispatch_get_phase(kind)->encode(row, dim, c.p1, c.p1 <= 16u ? 1u : 0u, again);
            } else {
                semq_dispatch_get_quant(kind)->encode(row, dim, c.p1, semq_config_max_magnitude(&c), again);
            }
            if (memcmp(again, rows + (size_t)r * bpv, bpv) != 0) {
                fprintf(stderr, "fixed point failed: %s %s row %u\n", set, g->id, r);
                exit(1);
            }
        }
        free(again);
        free(rep);
    }
    js_begin_object();
    char id[160];
    snprintf(id, sizeof(id), "%s-%s", set, g->id);
    js_kv_str("id", id);
    js_key("input");
    js_begin_object();
    js_key("config"); js_config(&c);
    js_kv_str("vectors_file", f_in);
    js_key("shape"); js_begin_array(); js_u64(n); js_u64(dim); js_end_array();
    if (decode_vector) js_kv_str("rows_file", f_rows);
    js_end_object();
    js_key("expect");
    js_begin_object();
    if (!decode_vector) {
        js_kv_str("rows_file", f_rows);
        js_kv_str("symbols_file", f_sym);
    } else {
        js_kv_str("representatives_file", f_rep);
        js_kv_u64("tolerance_ulp", c.op == SEMQ_PHASE ? 4u : 1u);
        js_kv_bool("fixed_point", 1);
    }
    js_end_object();
    js_end_object();
    free(symbols);
    free(ids);
    semq_codec_free(codec);
    semq_encoding_free(e);
}

static void vector_03(void) {
    begin_vector("03-encode");
    write_file("seeded-input.f32", g_seeded, SEEDED_N * SEEDED_DIM * sizeof(float));
    write_file("edges-input.f32", g_edges, EDGE_N * EDGE_DIM * sizeof(float));
    js_open();
    js_header(3u, "encode");
    for (size_t g = 0u; g < sizeof(ENC_GRID) / sizeof(ENC_GRID[0]); g++) {
        encode_set("seeded", g_seeded, SEEDED_N, SEEDED_DIM, &ENC_GRID[g], 0);
        encode_set("edges", g_edges, EDGE_N, EDGE_DIM, &ENC_GRID[g], 0);
    }
    js_footer();
}

static void vector_05(void) {
    begin_vector("05-decode");
    js_open();
    js_header(5u, "decode");
    for (size_t g = 0u; g < sizeof(ENC_GRID) / sizeof(ENC_GRID[0]); g++) {
        /* Rows come from vector 3's files; hosts load them through
         * Encoding(ids, rows, config) and decode. */
        encode_set("../03-encode/seeded", g_seeded, SEEDED_N, SEEDED_DIM, &ENC_GRID[g], 1);
        encode_set("../03-encode/edges", g_edges, EDGE_N, EDGE_DIM, &ENC_GRID[g], 1);
    }
    js_footer();
}

/* -------------------------------------------------------------------------- */
/*  4: encode-rejects                                                         */
/* -------------------------------------------------------------------------- */

static void reject_case(const char* id, const semq_config_t* c, const float* vectors, uint32_t n,
                        const uint64_t* ids, uint32_t id_kind, int host_only, const char* host_note) {
    semq_error_t err;
    semq_encoding_t* e = NULL;
    if (!host_only) {
        semq_codec_t* codec = NULL;
        semq_codec_create(c, &codec, NULL);
        semq_ids_t in = { id_kind, n, ids, NULL, NULL };
        semq_codec_encode(codec, &in, vectors, NULL, 0u, &e, &err);
        semq_codec_free(codec);
    }
    js_begin_object();
    js_kv_str("id", id);
    js_key("input");
    js_begin_object();
    js_key("config"); js_config(c);
    js_key("vectors_f32"); js_begin_array();
    for (uint32_t i = 0u; i < n * c->dim; i++) {
        uint32_t bits; memcpy(&bits, &vectors[i], 4u);
        char hex[16]; snprintf(hex, sizeof(hex), "%08x", bits);
        js_str(hex);
    }
    js_end_array();
    js_key("ids"); js_begin_object();
    js_kv_str("kind", id_kind == SEMQ_ID_U64 ? "u64" : "utf8");
    js_key("values"); js_begin_array();
    for (uint32_t i = 0u; i < n; i++) js_u64_str(ids[i]);
    js_end_array();
    js_end_object();
    if (host_only) js_kv_str("host", host_note);
    js_end_object();
    js_key("expect");
    if (host_only) {
        js_begin_object(); js_kv_str("error", "InvalidInput"); js_key("row"); js_null(); js_key("field"); js_null(); js_key("which"); js_null(); js_end_object();
    } else if (e == NULL) {
        js_error(&err);
    } else {
        uint8_t d[32];
        semq_encoding_content_digest(e, d);
        js_begin_object(); js_kv_hex("content_digest", d, 32u); js_end_object();
        semq_encoding_free(e);
    }
    js_end_object();
}

static void vector_04(void) {
    begin_vector("04-encode-rejects");
    js_open();
    js_header(4u, "encode-rejects");
    semq_config_t q = cfg_of(SEMQ_QUANT, 4u, 4u);
    semq_config_t o = cfg_of(SEMQ_ORBIT, 4u, 1u << 30);
    const uint64_t ids2[2] = { 1u, 2u };
    const uint64_t dup[2] = { 4u, 4u };
    float v[8] = { 1.0f, 0.0f, 0.0f, 0.0f, 0.0f, 1.0f, 0.0f, 0.0f };
    float nan_row[8] = { 1.0f, 0.0f, 0.0f, 0.0f, 0.0f, 1.0f, 0.0f, 0.0f };
    nan_row[6] = NAN;
    reject_case("nan", &q, nan_row, 2u, ids2, SEMQ_ID_U64, 0, NULL);
    float inf_row[4] = { 1.0f, 0.0f, 0.0f, 0.0f };
    inf_row[1] = INFINITY;
    reject_case("positive-infinity", &q, inf_row, 1u, ids2, SEMQ_ID_U64, 0, NULL);
    inf_row[1] = -INFINITY;
    reject_case("negative-infinity", &q, inf_row, 1u, ids2, SEMQ_ID_U64, 0, NULL);
    float low[4] = { 0.9f, 0.0f, 0.0f, 0.0f };
    reject_case("norm-below", &q, low, 1u, ids2, SEMQ_ID_U64, 0, NULL);
    float edge_in[4] = { 1.0f, 0.03125f, 0.0f, 0.0f };   /* sum of squares = 1 + 2^-10 exactly */
    reject_case("norm-at-tolerance-inside", &q, edge_in, 1u, ids2, SEMQ_ID_U64, 0, NULL);
    float edge_out[4] = { 1.0f, 0.0316f, 0.0f, 0.0f };
    reject_case("norm-just-outside", &q, edge_out, 1u, ids2, SEMQ_ID_U64, 0, NULL);
    reject_case("duplicate-ids", &q, v, 2u, dup, SEMQ_ID_U64, 0, NULL);
    float big[4] = { 1.0f + 0.000244140625f, 0.0f, 0.0f, 0.0f }; /* 1 + 2^-12, within tolerance */
    reject_case("orbit-scale-2^30-accepts-1-plus-2^-12", &o, big, 1u, ids2, SEMQ_ID_U64, 0, NULL);
    reject_case("empty-without-kind", &q, v, 0u, ids2, 7u, 0, NULL);
    reject_case("float64-input", &q, v, 1u, ids2, SEMQ_ID_U64, 1, "vectors passed as float64 must be rejected before the core");
    reject_case("wrong-width", &q, v, 1u, ids2, SEMQ_ID_U64, 1, "a row of 3 values for dim 4 must be rejected before the core");
    js_footer();
}

/* -------------------------------------------------------------------------- */
/*  6: ids-canonical                                                          */
/* -------------------------------------------------------------------------- */

static void vector_06(void) {
    begin_vector("06-ids-canonical");
    js_open();
    js_header(6u, "ids-canonical");
    semq_config_t c = cfg_of(SEMQ_QUANT, 4u, 4u);
    const uint8_t zero_row[2] = { 0u, 0u };
    uint8_t rows[10] = { 0 };
    /* u64: shuffled, expect the sorted section. */
    {
        const uint64_t ids[5] = { 4294967296u, 0u, 18446744073709551615u, 1u, 9007199254740993u };
        semq_ids_t in = { SEMQ_ID_U64, 5u, ids, NULL, NULL };
        semq_error_t err;
        semq_encoding_t* e = create_rows(&c, &in, rows, NULL, 0u, &err);
        if (e == NULL) die("v6 u64");
        js_begin_object();
        js_kv_str("id", "u64-shuffled");
        js_key("input"); js_begin_object(); js_key("ids"); js_begin_object(); js_kv_str("kind", "u64");
        js_key("values"); js_begin_array(); for (int i = 0; i < 5; i++) js_u64_str(ids[i]); js_end_array();
        js_end_object(); js_end_object();
        js_key("expect"); js_begin_object();
        js_key("sorted"); js_begin_array();
        const uint64_t* s = semq_encoding_ids_u64(e);
        for (int i = 0; i < 5; i++) js_u64_str(s[i]);
        js_end_array();
        js_kv_hex("ids_section", (const uint8_t*)s, 40u);
        js_end_object();
        js_end_object();
        semq_encoding_free(e);
    }
    /* utf8: a leading U+FEFF is part of the id, never a byte-order mark to
     * strip; "x" and "﻿x" are two ids. */
    {
        const char* strs[2] = { "\xef\xbb\xbfx", "x" };
        uint8_t bytes[8];
        uint64_t offsets[3] = { 0u, 4u, 5u };
        memcpy(bytes, strs[0], 4u); memcpy(bytes + 4, strs[1], 1u);
        semq_ids_t in = { SEMQ_ID_UTF8, 2u, NULL, offsets, bytes };
        semq_error_t err;
        semq_encoding_t* e = create_rows(&c, &in, rows, NULL, 0u, &err);
        if (e == NULL) die("v6 bom");
        js_begin_object();
        js_kv_str("id", "utf8-bom-is-not-stripped");
        js_key("input"); js_begin_object(); js_key("ids"); js_begin_object(); js_kv_str("kind", "utf8");
        js_key("values"); js_begin_array(); js_str(strs[0]); js_str(strs[1]); js_end_array(); js_end_object(); js_end_object();
        js_key("expect"); js_begin_object();
        js_key("sorted"); js_begin_array();
        const uint64_t* off = semq_encoding_ids_utf8_offsets(e);
        uint64_t blen;
        const uint8_t* b = semq_encoding_ids_utf8_bytes(e, &blen);
        for (int i = 0; i < 2; i++) js_strn(b + off[i], (size_t)(off[i + 1] - off[i]));
        js_end_array();
        uint64_t len;
        uint8_t* img = image_of(e, &len);
        js_kv_hex("ids_section", img + 28, (size_t)(3u * 8u + blen));
        free(img);
        js_end_object();
        js_end_object();
        semq_encoding_free(e);
    }
    /* utf8: ASCII, non-ASCII, prefixes, a 4096-byte id. */
    {
        static uint8_t big[4096];
        memset(big, 'z', sizeof(big));
        const char* strs[5] = { "b", "a", "ab", "\xc3\xa9", "" };
        uint8_t* bytes = (uint8_t*)xmalloc(4096u + 16u);
        uint64_t offsets[6];
        uint64_t pos = 0u;
        offsets[0] = 0u;
        for (int i = 0; i < 5; i++) {
            const size_t l = (i == 4) ? 4096u : strlen(strs[i]);
            memcpy(bytes + pos, (i == 4) ? (const char*)big : strs[i], l);
            pos += l;
            offsets[i + 1] = pos;
        }
        semq_ids_t in = { SEMQ_ID_UTF8, 5u, NULL, offsets, bytes };
        semq_error_t err;
        semq_encoding_t* e = create_rows(&c, &in, rows, NULL, 0u, &err);
        if (e == NULL) die("v6 utf8");
        js_begin_object();
        js_kv_str("id", "utf8-mixed");
        js_key("input"); js_begin_object(); js_key("ids"); js_begin_object(); js_kv_str("kind", "utf8");
        js_key("values"); js_begin_array();
        for (int i = 0; i < 5; i++) { if (i == 4) js_strn(big, 4096u); else js_str(strs[i]); }
        js_end_array(); js_end_object(); js_end_object();
        js_key("expect"); js_begin_object();
        js_key("sorted"); js_begin_array();
        const uint64_t* off = semq_encoding_ids_utf8_offsets(e);
        uint64_t blen;
        const uint8_t* b = semq_encoding_ids_utf8_bytes(e, &blen);
        for (int i = 0; i < 5; i++) js_strn(b + off[i], (size_t)(off[i + 1] - off[i]));
        js_end_array();
        uint64_t rlen;
        (void)semq_encoding_rows(e, &rlen);
        uint64_t len;
        uint8_t* img = image_of(e, &len);
        js_kv_hex("ids_section", img + 28, (size_t)(6u * 8u + blen));
        free(img);
        js_end_object();
        js_end_object();
        semq_encoding_free(e);
        free(bytes);
    }
    /* Rejects. */
    {
        struct { const char* id; const char* bytes; size_t len; } bad[4] = {
            { "utf8-empty", "", 0u }, { "utf8-nul", "a\0b", 3u }, { "utf8-invalid", "a\xff", 2u },
            { "utf8-overlong", "\xc0\xaf", 2u },
        };
        for (int i = 0; i < 4; i++) {
            const uint64_t offsets[2] = { 0u, bad[i].len };
            semq_ids_t in = { SEMQ_ID_UTF8, 1u, NULL, offsets, (const uint8_t*)bad[i].bytes };
            semq_error_t err;
            semq_encoding_t* e = create_rows(&c, &in, zero_row, NULL, 0u, &err);
            if (e != NULL) die("v6 reject accepted");
            js_begin_object();
            js_kv_str("id", bad[i].id);
            js_key("input"); js_begin_object(); js_key("ids"); js_begin_object(); js_kv_str("kind", "utf8");
            js_key("values_hex"); js_begin_array(); js_hex((const uint8_t*)bad[i].bytes, bad[i].len); js_end_array();
            js_end_object(); js_end_object();
            js_key("expect"); js_error(&err);
            js_end_object();
        }
        js_begin_object();
        js_kv_str("id", "utf8-too-long");
        js_key("input"); js_begin_object(); js_kv_u64("length", 4097u); js_kv_str("host", "an id of 4097 bytes must be rejected"); js_end_object();
        js_key("expect"); js_begin_object(); js_kv_str("error", "InvalidInput"); js_key("row"); js_u64(0u); js_key("field"); js_null(); js_key("which"); js_null(); js_end_object();
        js_end_object();
        js_begin_object();
        js_kv_str("id", "lone-surrogate");
        js_key("input"); js_begin_object(); js_kv_str("host", "a host string containing a lone surrogate must be rejected, never replaced"); js_end_object();
        js_key("expect"); js_begin_object(); js_kv_str("error", "InvalidInput"); js_key("row"); js_null(); js_key("field"); js_null(); js_key("which"); js_null(); js_end_object();
        js_end_object();
    }
    js_footer();
}

/* -------------------------------------------------------------------------- */
/*  7: manifest-canonical                                                     */
/* -------------------------------------------------------------------------- */

static void manifest_case(const char* id, const semq_pair_t* pairs, uint32_t n) {
    semq_config_t c = cfg_of(SEMQ_QUANT, 4u, 4u);
    semq_ids_t in = { SEMQ_ID_U64, 0u, NULL, NULL, NULL };
    semq_error_t err;
    semq_encoding_t* e = create_rows(&c, &in, NULL, pairs, n, &err);
    /* Inputs that are not valid UTF-8 cannot travel as JSON strings: those
     * cases carry their pairs as hex. */
    int hex = 0;
    for (uint32_t i = 0u; i < n; i++) {
        for (uint32_t k = 0u; k < pairs[i].key_len; k++) if (pairs[i].key[k] >= 0x80u) hex = 1;
        for (uint32_t k = 0u; k < pairs[i].value_len; k++) if (pairs[i].value[k] >= 0x80u) hex = 1;
    }
    js_begin_object();
    js_kv_str("id", id);
    js_key("input"); js_begin_object(); js_key(hex ? "pairs_hex" : "pairs"); js_begin_array();
    for (uint32_t i = 0u; i < n; i++) {
        js_begin_array();
        if (hex) { js_hex(pairs[i].key, pairs[i].key_len); js_hex(pairs[i].value, pairs[i].value_len); }
        else { js_strn(pairs[i].key, pairs[i].key_len); js_strn(pairs[i].value, pairs[i].value_len); }
        js_end_array();
    }
    js_end_array(); js_end_object();
    js_key("expect");
    if (e == NULL) {
        js_error(&err);
    } else {
        uint64_t len;
        uint8_t* img = image_of(e, &len);
        const size_t man_len = (size_t)len - 28u - 64u;  /* n = 0: no ids, no rows */
        js_begin_object(); js_kv_hex("manifest_section", img + 28, man_len);
        uint8_t d[32]; semq_encoding_state_id(e, d); js_kv_hex("state_id", d, 32u);
        js_end_object();
        free(img);
        semq_encoding_free(e);
    }
    js_end_object();
}

static void vector_07(void) {
    begin_vector("07-manifest-canonical");
    js_open();
    js_header(7u, "manifest-canonical");
    manifest_case("empty", NULL, 0u);
    {
        semq_pair_t p[4] = {
            { (const uint8_t*)"encoder", 7u, (const uint8_t*)"x", 1u },
            { (const uint8_t*)"enc", 3u, (const uint8_t*)"", 0u },
            { (const uint8_t*)"\xc3\xa9", 2u, (const uint8_t*)"value", 5u },
            { (const uint8_t*)"encoder_revision", 16u, (const uint8_t*)"1", 1u },
        };
        manifest_case("prefixes-non-ascii-empty-value", p, 4u);
    }
    {
        /* A leading U+FEFF in a key or a value is content, not a byte-order mark. */
        semq_pair_t p[2] = {
            { (const uint8_t*)"\xef\xbb\xbfk", 4u, (const uint8_t*)"\xef\xbb\xbfv", 4u },
            { (const uint8_t*)"k", 1u, (const uint8_t*)"v", 1u },
        };
        manifest_case("bom-in-key-and-value", p, 2u);
    }
    {
        static uint8_t key[256], value[65536];
        memset(key, 'k', sizeof(key)); memset(value, 'v', sizeof(value));
        semq_pair_t p[1] = { { key, 256u, value, 65536u } };
        manifest_case("maximum-sizes", p, 1u);
    }
    {
        semq_pair_t p[1] = { { (const uint8_t*)"", 0u, (const uint8_t*)"v", 1u } };
        manifest_case("empty-key", p, 1u);
    }
    {
        semq_pair_t p[2] = { { (const uint8_t*)"k", 1u, (const uint8_t*)"1", 1u }, { (const uint8_t*)"k", 1u, (const uint8_t*)"2", 1u } };
        manifest_case("duplicate-key", p, 2u);
    }
    {
        static uint8_t key[257];
        memset(key, 'k', sizeof(key));
        semq_pair_t p[1] = { { key, 257u, (const uint8_t*)"v", 1u } };
        manifest_case("key-too-long", p, 1u);
    }
    {
        semq_pair_t p[1] = { { (const uint8_t*)"k", 1u, (const uint8_t*)"\xff", 1u } };
        manifest_case("value-invalid-utf8", p, 1u);
    }
    js_footer();
}

/* -------------------------------------------------------------------------- */
/*  8, 9: digests and file                                                    */
/* -------------------------------------------------------------------------- */

typedef struct {
    const char*       id;
    semq_config_t     config;
    semq_encoding_t*  enc;
} sample_t;

static sample_t g_samples[8];
static uint32_t g_n_samples = 0u;

static void add_sample(const char* id, semq_encoding_t* e, const semq_config_t* c) {
    g_samples[g_n_samples].id = id;
    g_samples[g_n_samples].config = *c;
    g_samples[g_n_samples].enc = e;
    g_n_samples++;
}

static void build_samples(void) {
    semq_error_t err;
    semq_pair_t man[2] = {
        { (const uint8_t*)"encoder", 7u, (const uint8_t*)"m", 1u },
        { (const uint8_t*)"encoder_revision", 16u, (const uint8_t*)"1", 1u },
    };
    for (uint32_t op = 0u; op < 3u; op++) {
        semq_config_t c = cfg_of(op, SEEDED_DIM, op == SEMQ_ORBIT ? 50u : op == SEMQ_PHASE ? 16u : 4u);
        uint64_t ids[8];
        for (uint32_t i = 0u; i < 8u; i++) ids[i] = (uint64_t)(i * 7u + 3u);
        semq_encoding_t* e = encode_u64(&c, ids, 8u, g_seeded, man, 2u, &err);
        if (e == NULL) die("sample encode");
        add_sample(op == SEMQ_ORBIT ? "orbit-u64" : op == SEMQ_PHASE ? "phase-u64" : "quant-u64", e, &c);
    }
    {
        semq_config_t c = cfg_of(SEMQ_QUANT, SEEDED_DIM, 4u);
        const char* strs[4] = { "doc-10", "doc-2", "doc-1", "\xc3\xa9t\xc3\xa9" };
        uint8_t bytes[64]; uint64_t offsets[5]; uint64_t pos = 0u; offsets[0] = 0u;
        for (int i = 0; i < 4; i++) { memcpy(bytes + pos, strs[i], strlen(strs[i])); pos += strlen(strs[i]); offsets[i + 1] = pos; }
        semq_codec_t* codec = NULL; semq_codec_create(&c, &codec, NULL);
        semq_ids_t in = { SEMQ_ID_UTF8, 4u, NULL, offsets, bytes };
        semq_encoding_t* e = NULL;
        if (semq_codec_encode(codec, &in, g_seeded, man, 2u, &e, &err) != SEMQ_OK) die("utf8 sample");
        semq_codec_free(codec);
        add_sample("quant-utf8", e, &c);
    }
    {
        semq_config_t c = cfg_of(SEMQ_QUANT, 4u, 4u);
        semq_ids_t in = { SEMQ_ID_U64, 0u, NULL, NULL, NULL };
        add_sample("empty-u64", create_rows(&c, &in, NULL, NULL, 0u, &err), &c);
        semq_ids_t in2 = { SEMQ_ID_UTF8, 0u, NULL, NULL, NULL };
        add_sample("empty-utf8", create_rows(&c, &in2, NULL, NULL, 0u, &err), &c);
    }
}

static void write_sample_files(void) {
    for (uint32_t i = 0u; i < g_n_samples; i++) {
        uint64_t len;
        uint8_t* img = image_of(g_samples[i].enc, &len);
        char name[64];
        snprintf(name, sizeof(name), "%s.semq", g_samples[i].id);
        write_file(name, img, (size_t)len);
        free(img);
    }
}

static void vector_08(void) {
    begin_vector("08-digests");
    js_open();
    js_header(8u, "digests");
    for (uint32_t i = 0u; i < g_n_samples; i++) {
        const sample_t* s = &g_samples[i];
        uint8_t cd[32], sid[32];
        semq_encoding_content_digest(s->enc, cd);
        semq_encoding_state_id(s->enc, sid);
        js_begin_object();
        js_kv_str("id", s->id);
        js_key("input"); js_begin_object();
        js_key("config"); js_config(&s->config);
        char name[64]; snprintf(name, sizeof(name), "../09-file/%s.semq", s->id);
        js_kv_str("file", name);
        js_end_object();
        js_key("expect"); js_begin_object();
        js_kv_hex("content_digest", cd, 32u);
        js_kv_hex("state_id", sid, 32u);
        js_end_object();
        js_end_object();
    }
    /* Insertion-order independence: three orders of the same rows. */
    {
        semq_config_t c = cfg_of(SEMQ_QUANT, SEEDED_DIM, 4u);
        const uint64_t orders[3][4] = { { 1u, 2u, 3u, 4u }, { 4u, 3u, 2u, 1u }, { 3u, 1u, 4u, 2u } };
        float rows_in[3][4 * SEEDED_DIM];
        uint8_t first[32];
        for (int o = 0; o < 3; o++) {
            for (uint32_t r = 0u; r < 4u; r++) memcpy(rows_in[o] + r * SEEDED_DIM, g_seeded + (orders[o][r] - 1u) * SEEDED_DIM, SEEDED_DIM * sizeof(float));
            semq_error_t err;
            semq_encoding_t* e = encode_u64(&c, orders[o], 4u, rows_in[o], NULL, 0u, &err);
            uint8_t d[32];
            semq_encoding_state_id(e, d);
            if (o == 0) memcpy(first, d, 32u);
            else if (memcmp(first, d, 32u) != 0) die("insertion order changed the state id");
            semq_encoding_free(e);
        }
        js_begin_object();
        js_kv_str("id", "insertion-order-independent");
        js_key("input"); js_begin_object();
        js_key("config"); js_config(&c);
        js_kv_str("vectors_file", "../03-encode/seeded-input.f32");
        js_key("orders"); js_begin_array();
        for (int o = 0; o < 3; o++) { js_begin_array(); for (int r = 0; r < 4; r++) js_u64_str(orders[o][r]); js_end_array(); }
        js_end_array();
        js_end_object();
        js_key("expect"); js_begin_object(); js_kv_hex("state_id", first, 32u); js_end_object();
        js_end_object();
    }
    js_footer();
}

static void mutation_case(const char* id, const char* base, const char* kind, uint64_t at, uint64_t value,
                          const semq_error_t* err) {
    js_begin_object();
    js_kv_str("id", id);
    js_key("input"); js_begin_object();
    js_kv_str("file", base);
    js_key("mutate"); js_begin_object();
    js_kv_str("kind", kind);
    js_kv_u64("at", at);
    js_kv_u64("value", value);
    js_end_object();
    js_end_object();
    js_key("expect"); js_error(err);
    js_end_object();
}

static void load_expect(const uint8_t* img, uint64_t len, semq_error_t* err) {
    semq_encoding_t* e = NULL;
    if (semq_encoding_load(img, len, &e, err) == SEMQ_OK) { semq_encoding_free(e); die("mutated image loaded"); }
}

static void refresh_footer(uint8_t* img, uint64_t len, uint64_t manifest_len) {
    semq_sha256(img + 6, (size_t)(len - 6u - 64u - manifest_len), img + len - 64u);
    uint8_t* tmp = (uint8_t*)xmalloc((size_t)(32u + manifest_len));
    memcpy(tmp, img + len - 64u, 32u);
    memcpy(tmp + 32, img + len - 64u - manifest_len, (size_t)manifest_len);
    semq_sha256(tmp, 32u + manifest_len, img + len - 32u);
    free(tmp);
}

static void vector_09(void) {
    begin_vector("09-file");
    write_sample_files();
    js_open();
    js_header(9u, "file");
    /* Round trips and the empty images of both kinds. */
    for (uint32_t i = 0u; i < g_n_samples; i++) {
        const sample_t* s = &g_samples[i];
        uint64_t len;
        uint8_t* img = image_of(s->enc, &len);
        uint8_t sid[32];
        semq_encoding_state_id(s->enc, sid);
        js_begin_object();
        char id[64]; snprintf(id, sizeof(id), "roundtrip-%s", s->id);
        js_kv_str("id", id);
        js_key("input"); js_begin_object(); char name[64]; snprintf(name, sizeof(name), "%s.semq", s->id); js_kv_str("file", name); js_end_object();
        js_key("expect"); js_begin_object();
        js_kv_u64("file_size", len);
        js_kv_hex("state_id", sid, 32u);
        js_kv_u64("n", semq_encoding_len(s->enc));
        js_kv_str("id_kind", semq_encoding_id_kind(s->enc) == SEMQ_ID_U64 ? "u64" : "utf8");
        js_end_object();
        js_end_object();
        free(img);
    }
    /* Mutations of quant-u64.semq: 8 rows of 12 bytes, ids 8 x 8, manifest with two pairs. */
    const sample_t* base = &g_samples[2];
    uint64_t len;
    uint8_t* img = image_of(base->enc, &len);
    const uint64_t ids_at = 28u, rows_at = 28u + 64u;
    const uint64_t man_at = rows_at + 8u * 12u;
    uint8_t* m = (uint8_t*)xmalloc((size_t)len + 1u);
    semq_error_t err;
    struct { const char* id; uint64_t at; } flips[5] = {
        { "flip-row-byte", rows_at + 5u }, { "flip-id-byte", ids_at + 3u }, { "flip-manifest-byte", man_at + 6u },
        { "flip-header-byte", 12u }, { "flip-footer-byte", len - 10u },
    };
    for (int i = 0; i < 5; i++) {
        memcpy(m, img, (size_t)len);
        m[flips[i].at] ^= 0x01u;
        load_expect(m, len, &err);
        mutation_case(flips[i].id, "quant-u64.semq", "xor_byte", flips[i].at, 1u, &err);
    }
    const uint64_t cuts[5] = { 0u, 27u, ids_at + 8u, rows_at + 12u, len - 64u };
    const char* cut_ids[5] = { "empty-image", "truncate-in-header", "truncate-in-ids", "truncate-in-rows", "truncate-before-footer" };
    for (int i = 0; i < 5; i++) {
        load_expect(img, cuts[i], &err);
        mutation_case(cut_ids[i], "quant-u64.semq", "truncate", cuts[i], 0u, &err);
    }
    memcpy(m, img, (size_t)len); m[0] = 'X'; load_expect(m, len, &err);
    mutation_case("wrong-magic", "quant-u64.semq", "set_byte", 0u, 'X', &err);
    memcpy(m, img, (size_t)len); m[4] = 1u; load_expect(m, len, &err);
    mutation_case("version-1", "quant-u64.semq", "set_byte", 4u, 1u, &err);
    memcpy(m, img, (size_t)len); m[4] = 3u; load_expect(m, len, &err);
    mutation_case("version-3", "quant-u64.semq", "set_byte", 4u, 3u, &err);
    memcpy(m, img, (size_t)len); m[len] = 0u; load_expect(m, len + 1u, &err);
    mutation_case("trailing-byte", "quant-u64.semq", "append_byte", len, 0u, &err);
    memcpy(m, img, (size_t)len); m[25] = 0x01u; load_expect(m, len, &err);
    mutation_case("n-2^40", "quant-u64.semq", "set_byte", 25u, 1u, &err);
    /* Non-canonical rows with recomputed digests, written as files. */
    memcpy(m, img, (size_t)len);
    m[rows_at + 12u * 8u - 1u] |= 0x80u;  /* quant(32, 4): 96 bits = 12 bytes, no padding; use phase instead */
    free(m);
    {
        /* phase-u64 rows are nibbles < 16 with sectors = 16, so every nibble is
         * valid; use the orbit sample to place a symbol outside the alphabet. */
        const sample_t* orb = &g_samples[0];
        uint64_t olen;
        uint8_t* o = image_of(orb->enc, &olen);
        const uint64_t o_rows_at = 28u + 64u;
        const uint64_t o_man_len = olen - 64u - o_rows_at - 8u * SEEDED_DIM;
        o[o_rows_at + 3u] = 19u;
        refresh_footer(o, olen, o_man_len);
        load_expect(o, olen, &err);
        write_file("orbit-symbol-19.semq", o, (size_t)olen);
        js_begin_object(); js_kv_str("id", "symbol-outside-alphabet");
        js_key("input"); js_begin_object(); js_kv_str("file", "orbit-symbol-19.semq"); js_end_object();
        js_key("expect"); js_error(&err); js_end_object();
        free(o);
        /* quant(4, 4) with padding: build a one-row image by hand from a valid one. */
        semq_config_t c = cfg_of(SEMQ_QUANT, 4u, 4u);
        const uint64_t one = 7u;
        const uint8_t row[2] = { 0x07u, 0x07u };
        semq_ids_t in = { SEMQ_ID_U64, 1u, &one, NULL, NULL };
        semq_encoding_t* e = create_rows(&c, &in, row, NULL, 0u, &err);
        uint64_t plen;
        uint8_t* p = image_of(e, &plen);
        p[28u + 8u + 1u] |= 0x10u;  /* bit 12 of the row is padding */
        refresh_footer(p, plen, 4u);
        load_expect(p, plen, &err);
        write_file("quant-padding-bit.semq", p, (size_t)plen);
        js_begin_object(); js_kv_str("id", "padding-bit-set");
        js_key("input"); js_begin_object(); js_kv_str("file", "quant-padding-bit.semq"); js_end_object();
        js_key("expect"); js_error(&err); js_end_object();
        free(p);
        semq_encoding_free(e);
    }
    /* Footer copied from another valid state. */
    {
        uint64_t olen;
        uint8_t* o = image_of(g_samples[4].enc, &olen); /* empty-u64 */
        uint8_t* f = (uint8_t*)xmalloc((size_t)len);
        memcpy(f, img, (size_t)len);
        memcpy(f + len - 64u, o + olen - 64u, 64u);
        load_expect(f, len, &err);
        write_file("quant-foreign-footer.semq", f, (size_t)len);
        js_begin_object(); js_kv_str("id", "footer-from-another-state");
        js_key("input"); js_begin_object(); js_kv_str("file", "quant-foreign-footer.semq"); js_end_object();
        js_key("expect"); js_error(&err); js_end_object();
        free(f); free(o);
    }
    free(img);
    js_footer();
}

/* -------------------------------------------------------------------------- */
/*  10: concat                                                                */
/* -------------------------------------------------------------------------- */

static void vector_10(void) {
    begin_vector("10-concat");
    js_open();
    js_header(10u, "concat");
    semq_config_t c = cfg_of(SEMQ_QUANT, SEEDED_DIM, 4u);
    semq_error_t err;
    semq_pair_t man[1] = { { (const uint8_t*)"encoder", 7u, (const uint8_t*)"m", 1u } };
    const uint64_t ids[6] = { 10u, 11u, 20u, 21u, 30u, 31u };
    semq_encoding_t* parts[3];
    for (uint32_t p = 0u; p < 3u; p++) parts[p] = encode_u64(&c, ids + 2u * p, 2u, g_seeded + 2u * p * SEEDED_DIM, man, 1u, &err);
    semq_encoding_t* whole = encode_u64(&c, ids, 6u, g_seeded, man, 1u, &err);
    uint8_t want[32];
    semq_encoding_state_id(whole, want);
    const int orders[6][3] = { {0,1,2},{0,2,1},{1,0,2},{1,2,0},{2,0,1},{2,1,0} };
    for (int o = 0; o < 6; o++) {
        const semq_encoding_t* seq[3] = { parts[orders[o][0]], parts[orders[o][1]], parts[orders[o][2]] };
        semq_encoding_t* r = NULL;
        if (semq_encoding_concat(seq, 3u, &r, &err) != SEMQ_OK) die("concat");
        uint8_t got[32];
        semq_encoding_state_id(r, got);
        if (memcmp(got, want, 32u) != 0) die("concat order changed the state");
        semq_encoding_free(r);
    }
    for (int p = 0; p < 3; p++) {
        uint64_t len; uint8_t* img = image_of(parts[p], &len);
        char name[32]; snprintf(name, sizeof(name), "part-%d.semq", p);
        write_file(name, img, (size_t)len); free(img);
    }
    js_begin_object(); js_kv_str("id", "three-parts-every-order");
    js_key("input"); js_begin_object(); js_key("files"); js_begin_array(); js_str("part-0.semq"); js_str("part-1.semq"); js_str("part-2.semq"); js_end_array(); js_end_object();
    js_key("expect"); js_begin_object(); js_kv_hex("state_id", want, 32u); js_kv_u64("n", 6u); js_end_object();
    js_end_object();
    /* Neutral element. */
    {
        semq_ids_t in = { SEMQ_ID_U64, 0u, NULL, NULL, NULL };
        semq_encoding_t* empty = create_rows(&c, &in, NULL, man, 1u, &err);
        uint64_t len; uint8_t* img = image_of(empty, &len); write_file("empty.semq", img, (size_t)len); free(img);
        const semq_encoding_t* seq[2] = { whole, empty };
        semq_encoding_t* r = NULL;
        semq_encoding_concat(seq, 2u, &r, &err);
        uint8_t got[32]; semq_encoding_state_id(r, got);
        if (memcmp(got, want, 32u) != 0) die("empty is not neutral");
        semq_encoding_free(r);
        semq_encoding_free(empty);
        js_begin_object(); js_kv_str("id", "empty-is-neutral");
        js_key("input"); js_begin_object(); js_key("files"); js_begin_array(); js_str("part-0.semq"); js_str("part-1.semq"); js_str("part-2.semq"); js_str("empty.semq"); js_end_array(); js_end_object();
        js_key("expect"); js_begin_object(); js_kv_hex("state_id", want, 32u); js_kv_u64("n", 6u); js_end_object();
        js_end_object();
    }
    /* Rejects: overlap, different manifest, different config, different kind. */
    {
        semq_encoding_t* r = NULL;
        const semq_encoding_t* overlap[2] = { parts[0], parts[0] };
        semq_encoding_concat(overlap, 2u, &r, &err);
        js_begin_object(); js_kv_str("id", "overlapping-ids");
        js_key("input"); js_begin_object(); js_key("files"); js_begin_array(); js_str("part-0.semq"); js_str("part-0.semq"); js_end_array(); js_end_object();
        js_key("expect"); js_error(&err); js_end_object();

        semq_encoding_t* other_man = encode_u64(&c, ids + 4, 2u, g_seeded + 4 * SEEDED_DIM, NULL, 0u, &err);
        { uint64_t len; uint8_t* img = image_of(other_man, &len); write_file("other-manifest.semq", img, (size_t)len); free(img); }
        const semq_encoding_t* mixed[2] = { parts[0], other_man };
        semq_encoding_concat(mixed, 2u, &r, &err);
        js_begin_object(); js_kv_str("id", "different-manifest");
        js_key("input"); js_begin_object(); js_key("files"); js_begin_array(); js_str("part-0.semq"); js_str("other-manifest.semq"); js_end_array(); js_end_object();
        js_key("expect"); js_error(&err); js_end_object();
        semq_encoding_free(other_man);

        semq_config_t c8 = cfg_of(SEMQ_QUANT, SEEDED_DIM, 8u);
        semq_encoding_t* other_cfg = encode_u64(&c8, ids + 4, 2u, g_seeded + 4 * SEEDED_DIM, man, 1u, &err);
        { uint64_t len; uint8_t* img = image_of(other_cfg, &len); write_file("other-config.semq", img, (size_t)len); free(img); }
        const semq_encoding_t* inc[2] = { parts[0], other_cfg };
        semq_encoding_concat(inc, 2u, &r, &err);
        js_begin_object(); js_kv_str("id", "different-config");
        js_key("input"); js_begin_object(); js_key("files"); js_begin_array(); js_str("part-0.semq"); js_str("other-config.semq"); js_end_array(); js_end_object();
        js_key("expect"); js_error(&err); js_end_object();
        semq_encoding_free(other_cfg);

        const uint8_t bytes[1] = { 'a' }; const uint64_t offsets[2] = { 0u, 1u };
        semq_ids_t in = { SEMQ_ID_UTF8, 1u, NULL, offsets, bytes };
        semq_codec_t* codec = NULL; semq_codec_create(&c, &codec, NULL);
        semq_encoding_t* other_kind = NULL;
        semq_codec_encode(codec, &in, g_seeded, man, 1u, &other_kind, &err);
        semq_codec_free(codec);
        { uint64_t len; uint8_t* img = image_of(other_kind, &len); write_file("other-kind.semq", img, (size_t)len); free(img); }
        const semq_encoding_t* kinds[2] = { parts[0], other_kind };
        semq_encoding_concat(kinds, 2u, &r, &err);
        js_begin_object(); js_kv_str("id", "different-kind");
        js_key("input"); js_begin_object(); js_key("files"); js_begin_array(); js_str("part-0.semq"); js_str("other-kind.semq"); js_end_array(); js_end_object();
        js_key("expect"); js_error(&err); js_end_object();
        semq_encoding_free(other_kind);
    }
    for (int p = 0; p < 3; p++) semq_encoding_free(parts[p]);
    semq_encoding_free(whole);
    js_footer();
}

/* -------------------------------------------------------------------------- */
/*  11, 12, 13: diff, floor, report                                           */
/* -------------------------------------------------------------------------- */

static void js_diff_report(const semq_diff_t* d) {
    uint8_t r[32], c[32];
    semq_diff_reference_id(d, r);
    semq_diff_candidate_id(d, c);
    const int u64 = semq_diff_id_kind(d) == SEMQ_ID_U64;
    js_begin_object();
    js_kv_hex("reference_id", r, 32u);
    js_kv_hex("candidate_id", c, 32u);
    js_kv_str("id_kind", u64 ? "u64" : "utf8");
    js_key("config"); js_config(semq_diff_config(d));
    for (uint32_t list = 0u; list < 3u; list++) {
        js_key(list == 0u ? "added" : list == 1u ? "removed" : "changed");
        js_begin_array();
        for (uint64_t i = 0u; i < semq_diff_count(d, list); i++) {
            uint64_t v = 0u, l = 0u; const uint8_t* b = NULL;
            semq_diff_id(d, list, i, &v, &b, &l, NULL);
            if (list == 2u) {
                uint64_t h = 0u; semq_diff_hamming(d, i, &h, NULL);
                js_begin_array();
                if (u64) js_u64_str(v); else js_strn(b, (size_t)l);
                js_u64(h);
                js_end_array();
            } else {
                if (u64) js_u64_str(v); else js_strn(b, (size_t)l);
            }
        }
        js_end_array();
    }
    js_kv_u64("n_unchanged", semq_diff_n_unchanged(d));
    js_key("manifest_changes"); js_begin_object();
    for (uint32_t i = 0u; i < semq_diff_manifest_changes(d); i++) {
        semq_manifest_change_t m;
        semq_diff_manifest_change(d, i, &m, NULL);
        char key[300]; memcpy(key, m.key, m.key_len); key[m.key_len] = '\0';
        js_key(key);
        js_begin_array();
        if (m.has_before) js_strn(m.before, m.before_len); else js_null();
        if (m.has_after) js_strn(m.after, m.after_len); else js_null();
        js_end_array();
    }
    js_end_object();
    js_end_object();
}

/* quant(16, 4) rows with `n_changed` rows differing from the base in the
 * first `flip` units. */
/* Rows 0..n_changed-1 flip `flip` units; row `outlier` (when < n) flips `outlier_flip` units. */
static semq_encoding_t* rows_with_outlier(uint64_t n, uint64_t n_changed, uint32_t flip, uint64_t outlier,
                                          uint32_t outlier_flip, uint8_t base) {
    semq_config_t c = cfg_of(SEMQ_QUANT, 16u, 4u);
    const uint32_t bpv = semq_config_bytes_per_vector(&c);
    uint64_t* ids = (uint64_t*)xmalloc((size_t)n * sizeof(uint64_t));
    uint8_t* rows = (uint8_t*)xmalloc((size_t)n * bpv);
    memset(rows, 0, (size_t)n * bpv);
    for (uint64_t i = 0u; i < n; i++) {
        ids[i] = i;
        uint64_t pos = 0u;
        for (uint32_t u = 0u; u < 16u; u++) {
            const uint32_t k = i == outlier ? outlier_flip : i < n_changed ? flip : 0u;
            const uint8_t sym = u < k ? (uint8_t)(base + 1u) : base;
            for (uint32_t b = 0u; b < 3u; b++, pos++) if ((sym >> b) & 1u) rows[i * bpv + (pos >> 3)] |= (uint8_t)(1u << (pos & 7u));
        }
    }
    semq_ids_t in = { SEMQ_ID_U64, n, ids, NULL, NULL };
    semq_error_t err;
    semq_encoding_t* e = create_rows(&c, &in, rows, NULL, 0u, &err);
    if (e == NULL) die("rows_with_outlier");
    free(ids); free(rows);
    return e;
}
static semq_encoding_t* rows_with_changes(uint64_t n, uint64_t n_changed, uint32_t flip, uint8_t base) {
    return rows_with_outlier(n, n_changed, flip, UINT64_MAX, 0u, base);
}

/* The verdict of evaluate: passed, the failed checks by name, and the ids of the rows above max_hamming. */
static void js_verdict(const semq_diff_t* d, const semq_verdict_t* v) {
    static const char* const names[6] = { "no_common_rows", "removed_rows", "changed_ratio", "hamming", "encoder", "row_above_max" };
    const int u64 = semq_diff_id_kind(d) == SEMQ_ID_U64;
    js_begin_object();
    js_kv_bool("passed", semq_verdict_passed(v));
    js_key("reasons"); js_begin_array();
    for (uint32_t b = 0u; b < 6u; b++) if (semq_verdict_reasons(v) & (1u << b)) js_str(names[b]);
    js_end_array();
    js_key("rows"); js_begin_array();
    for (uint64_t i = 0u; i < semq_verdict_row_count(v); i++) {
        uint64_t id = 0u, l = 0u; const uint8_t* b = NULL;
        semq_diff_id(d, SEMQ_LIST_CHANGED, semq_verdict_row(v, i), &id, &b, &l, NULL);
        if (u64) js_u64_str(id); else js_strn(b, (size_t)l);
    }
    js_end_array();
    js_end_object();
}

static semq_diff_t* g_null_a;
static semq_diff_t* g_null_a2;
static semq_diff_t* g_null_b;
static semq_encoding_t* g_base100;

static void vector_11_13(void) {
    /* ---- 11: diff ---- */
    begin_vector("11-diff");
    semq_error_t err;
    semq_config_t c = cfg_of(SEMQ_QUANT, SEEDED_DIM, 4u);
    semq_pair_t ref_man[2] = { { (const uint8_t*)"encoder", 7u, (const uint8_t*)"m", 1u }, { (const uint8_t*)"note", 4u, (const uint8_t*)"a", 1u } };
    semq_pair_t cand_man[2] = { { (const uint8_t*)"encoder", 7u, (const uint8_t*)"m", 1u }, { (const uint8_t*)"run", 3u, (const uint8_t*)"7", 1u } };
    semq_pair_t enc_man[1] = { { (const uint8_t*)"encoder", 7u, (const uint8_t*)"other", 5u } };
    const uint64_t ref_ids[4] = { 1u, 2u, 3u, 4u };
    const uint64_t cand_ids[4] = { 2u, 3u, 4u, 5u };
    float cand_rows[4 * SEEDED_DIM];
    memcpy(cand_rows, g_seeded + SEEDED_DIM, 3u * SEEDED_DIM * sizeof(float)); /* rows of 2, 3, 4 */
    memcpy(cand_rows + 3u * SEEDED_DIM, g_seeded + 8u * SEEDED_DIM, SEEDED_DIM * sizeof(float));
    cand_rows[SEEDED_DIM + 0] = -cand_rows[SEEDED_DIM + 0]; /* id 3 changes in unit 0 (and maybe more) */
    renorm(cand_rows + SEEDED_DIM, SEEDED_DIM);
    semq_encoding_t* ref = encode_u64(&c, ref_ids, 4u, g_seeded, ref_man, 2u, &err);
    semq_encoding_t* cand = encode_u64(&c, cand_ids, 4u, cand_rows, cand_man, 2u, &err);
    semq_encoding_t* same = encode_u64(&c, ref_ids, 4u, g_seeded, ref_man, 2u, &err);
    semq_encoding_t* enc_changed = encode_u64(&c, ref_ids, 4u, g_seeded, enc_man, 1u, &err);
    semq_encoding_t* empty_ref;
    { semq_ids_t in = { SEMQ_ID_U64, 0u, NULL, NULL, NULL }; empty_ref = create_rows(&c, &in, NULL, ref_man, 2u, &err); }
    struct { const char* name; semq_encoding_t* e; } files[5] = {
        { "ref.semq", ref }, { "cand.semq", cand }, { "same.semq", same }, { "encoder-changed.semq", enc_changed }, { "empty-ref.semq", empty_ref } };
    for (int i = 0; i < 5; i++) { uint64_t len; uint8_t* img = image_of(files[i].e, &len); write_file(files[i].name, img, (size_t)len); free(img); }
    js_open();
    js_header(11u, "diff");
    struct { const char* id; semq_encoding_t* a; semq_encoding_t* b; const char* fa; const char* fb; uint64_t unit_id; } pairs[5] = {
        { "added-removed-changed", ref, cand, "ref.semq", "cand.semq", 3u },
        { "identical-short-circuit", ref, same, "ref.semq", "same.semq", 2u },
        { "encoder-changed", ref, enc_changed, "ref.semq", "encoder-changed.semq", 1u },
        { "empty-reference", empty_ref, cand, "empty-ref.semq", "cand.semq", SEMQ_NONE },
        { "candidate-empty", ref, empty_ref, "ref.semq", "empty-ref.semq", SEMQ_NONE },
    };
    for (int i = 0; i < 5; i++) {
        semq_diff_t* d = NULL;
        if (semq_encoding_diff(pairs[i].a, pairs[i].b, &d, &err) != SEMQ_OK) die("diff");
        js_begin_object();
        js_kv_str("id", pairs[i].id);
        js_key("input"); js_begin_object(); js_kv_str("reference", pairs[i].fa); js_kv_str("candidate", pairs[i].fb);
        if (pairs[i].unit_id != SEMQ_NONE) js_kv_u64("units_of", pairs[i].unit_id);
        js_end_object();
        js_key("expect"); js_begin_object();
        js_key("report"); js_diff_report(d);
        if (pairs[i].unit_id != SEMQ_NONE) {
            uint32_t units[SEEDED_DIM]; uint8_t sr[SEEDED_DIM], sc[SEEDED_DIM]; uint64_t count = 0u;
            semq_diff_units_u64(d, pairs[i].unit_id, units, sr, sc, SEEDED_DIM, &count, NULL);
            js_key("units"); js_begin_array();
            for (uint64_t u = 0u; u < count; u++) { js_begin_array(); js_u64(units[u]); js_u64(sr[u]); js_u64(sc[u]); js_end_array(); }
            js_end_array();
        }
        js_end_object();
        js_end_object();
        semq_diff_free(d);
    }
    /* Incompatible: config and kind. */
    {
        semq_config_t c8 = cfg_of(SEMQ_QUANT, SEEDED_DIM, 8u);
        semq_encoding_t* other = encode_u64(&c8, ref_ids, 4u, g_seeded, ref_man, 2u, &err);
        { uint64_t len; uint8_t* img = image_of(other, &len); write_file("other-config.semq", img, (size_t)len); free(img); }
        semq_diff_t* d = NULL;
        semq_encoding_diff(ref, other, &d, &err);
        js_begin_object(); js_kv_str("id", "different-config");
        js_key("input"); js_begin_object(); js_kv_str("reference", "ref.semq"); js_kv_str("candidate", "other-config.semq"); js_end_object();
        js_key("expect"); js_error(&err); js_end_object();
        semq_encoding_free(other);
        const uint8_t bytes[1] = { '1' }; const uint64_t offsets[2] = { 0u, 1u };
        semq_ids_t in = { SEMQ_ID_UTF8, 1u, NULL, offsets, bytes };
        semq_codec_t* codec = NULL; semq_codec_create(&c, &codec, NULL);
        semq_encoding_t* kind = NULL; semq_codec_encode(codec, &in, g_seeded, ref_man, 2u, &kind, &err); semq_codec_free(codec);
        { uint64_t len; uint8_t* img = image_of(kind, &len); write_file("other-kind.semq", img, (size_t)len); free(img); }
        semq_encoding_diff(ref, kind, &d, &err);
        js_begin_object(); js_kv_str("id", "different-kind");
        js_key("input"); js_begin_object(); js_kv_str("reference", "ref.semq"); js_kv_str("candidate", "other-kind.semq"); js_end_object();
        js_key("expect"); js_error(&err); js_end_object();
        semq_encoding_free(kind);
    }
    js_footer();

    /* ---- 12: floor ---- */
    begin_vector("12-floor");
    g_base100 = rows_with_changes(100u, 0u, 0u, 4u);
    semq_encoding_t* a1 = rows_with_changes(100u, 1u, 1u, 4u);
    semq_encoding_t* a2 = rows_with_changes(100u, 2u, 1u, 4u);
    semq_encoding_t* b0 = rows_with_changes(1u, 0u, 0u, 4u);
    semq_encoding_t* b1 = rows_with_changes(1u, 1u, 10u, 4u);
    semq_encoding_t* removed = rows_with_changes(99u, 0u, 0u, 4u);
    semq_encoding_t* added = rows_with_changes(101u, 0u, 0u, 4u);
    semq_encoding_t* nothing = rows_with_changes(0u, 0u, 0u, 4u);
    /* 200 rows: a null that changes rows 0..99 by 2 units, and a candidate that changes rows 0..98 by 2
     * and row 150 by 10. The candidate's p99 is 2: it ignores its one most-changed row. */
    semq_encoding_t* base200 = rows_with_changes(200u, 0u, 0u, 4u);
    semq_encoding_t* null200 = rows_with_changes(200u, 100u, 2u, 4u);
    semq_encoding_t* hidden = rows_with_outlier(200u, 99u, 2u, 150u, 10u, 4u);
    struct { const char* name; semq_encoding_t* e; } ffiles[11] = {
        { "base100.semq", g_base100 }, { "null-a.semq", a1 }, { "two-changed.semq", a2 }, { "base1.semq", b0 },
        { "null-b.semq", b1 }, { "removed.semq", removed }, { "added.semq", added }, { "empty.semq", nothing },
        { "base200.semq", base200 }, { "null-200.semq", null200 }, { "hidden.semq", hidden } };
    for (int i = 0; i < 11; i++) { uint64_t len; uint8_t* img = image_of(ffiles[i].e, &len); write_file(ffiles[i].name, img, (size_t)len); free(img); }
    semq_encoding_diff(g_base100, a1, &g_null_a, &err);
    semq_encoding_diff(g_base100, a2, &g_null_a2, &err);
    semq_encoding_diff(b0, b1, &g_null_b, &err);
    uint8_t rid100[32], rid1[32], rid_ref[32], rid_empty[32], rid200[32];
    semq_encoding_state_id(g_base100, rid100);
    semq_encoding_state_id(base200, rid200);
    semq_encoding_state_id(b0, rid1);
    semq_encoding_state_id(ref, rid_ref);
    semq_encoding_state_id(nothing, rid_empty);
    js_open();
    js_header(12u, "floor");
    {
        /* measure */
        const semq_diff_t* one[1] = { g_null_a };
        const semq_diff_t* two[2] = { g_null_a, g_null_a2 };
        const semq_diff_t* mixed[2] = { g_null_a, g_null_b };
        semq_floor_t* f_a = NULL; semq_floor_t* f_two = NULL; semq_floor_t* f_hidden = NULL; semq_floor_t* f_none = NULL;
        semq_diff_t* d_hidden = NULL; semq_encoding_diff(base200, hidden, &d_hidden, &err);
        const semq_diff_t* hid[1] = { d_hidden };
        semq_floor_measure(one, 1u, &f_a, &err);
        semq_floor_measure(two, 2u, &f_two, &err);
        semq_floor_measure(hid, 1u, &f_hidden, &err);
        struct { const char* id; const char* nulls[2][2]; uint32_t k; const semq_floor_t* f; } ms[3] = {
            { "measure-a", { { "base100.semq", "null-a.semq" }, { NULL, NULL } }, 1u, f_a },
            { "measure-a-and-two-changed", { { "base100.semq", "null-a.semq" }, { "base100.semq", "two-changed.semq" } }, 2u, f_two },
            { "measure-records-max-hamming", { { "base200.semq", "hidden.semq" }, { NULL, NULL } }, 1u, f_hidden } };
        for (int i = 0; i < 3; i++) {
            js_begin_object(); js_kv_str("id", ms[i].id);
            js_key("input"); js_begin_object(); js_key("null_diffs"); js_begin_array();
            for (uint32_t k = 0u; k < ms[i].k; k++) { js_begin_array(); js_str(ms[i].nulls[k][0]); js_str(ms[i].nulls[k][1]); js_end_array(); }
            js_end_array(); js_end_object();
            js_key("expect"); js_begin_object(); js_key("floor"); js_floor(ms[i].f); js_end_object();
            js_end_object();
        }
        semq_floor_measure(mixed, 2u, &f_none, &err);
        js_begin_object(); js_kv_str("id", "measure-rejects-different-references");
        js_key("input"); js_begin_object(); js_key("null_diffs"); js_begin_array();
        js_begin_array(); js_str("base100.semq"); js_str("null-a.semq"); js_end_array();
        js_begin_array(); js_str("base1.semq"); js_str("null-b.semq"); js_end_array();
        js_end_array(); js_end_object();
        js_key("expect"); js_error(&err); js_end_object();
        /* within: the floor is given in full; hosts construct it, then apply it. */
        const semq_config_t* cq = semq_encoding_config(g_base100);
        semq_config_t orbit16; semq_config_orbit(16u, 50u, &orbit16, NULL);
        struct { const char* id; const char* ref; const char* cand; semq_encoding_t* r; semq_encoding_t* c;
                 const semq_config_t* fc; uint32_t kind; const uint8_t* rid; uint64_t nulls, changed, total, hamming, max_hamming;
                 int per_row; } ws[15] = {
            { "null-a-within-a", "base100.semq", "null-a.semq", g_base100, a1, cq, SEMQ_ID_U64, rid100, 1u, 1u, 100u, 1u, SEMQ_NONE, 0 },
            { "two-changed-within-both", "base100.semq", "two-changed.semq", g_base100, a2, cq, SEMQ_ID_U64, rid100, 2u, 2u, 100u, 1u, SEMQ_NONE, 0 },
            { "two-changed-at-boundary-fails", "base100.semq", "two-changed.semq", g_base100, a2, cq, SEMQ_ID_U64, rid100, 1u, 1u, 100u, 1u, SEMQ_NONE, 0 },
            { "two-changed-at-boundary-passes", "base100.semq", "two-changed.semq", g_base100, a2, cq, SEMQ_ID_U64, rid100, 1u, 2u, 100u, 1u, SEMQ_NONE, 0 },
            { "removed-never-passes", "base100.semq", "removed.semq", g_base100, removed, cq, SEMQ_ID_U64, rid100, 1u, 100u, 100u, 16u, SEMQ_NONE, 0 },
            { "added-does-not-affect", "base100.semq", "added.semq", g_base100, added, cq, SEMQ_ID_U64, rid100, 1u, 0u, 100u, 0u, SEMQ_NONE, 0 },
            { "encoder-change-never-passes", "../11-diff/ref.semq", "../11-diff/encoder-changed.semq", ref, enc_changed, semq_encoding_config(ref), SEMQ_ID_U64, rid_ref, 1u, 4u, 4u, 4u, SEMQ_NONE, 0 },
            { "no-common-rows-never-passes", "empty.semq", "empty.semq", nothing, nothing, cq, SEMQ_ID_U64, rid_empty, 1u, 1u, 1u, 16u, SEMQ_NONE, 0 },
            { "within-rejects-other-reference", "base1.semq", "null-b.semq", b0, b1, cq, SEMQ_ID_U64, rid100, 1u, 1u, 1u, 16u, SEMQ_NONE, 0 },
            { "within-rejects-other-config", "base100.semq", "null-a.semq", g_base100, a1, &orbit16, SEMQ_ID_U64, rid100, 1u, 1u, 100u, 1u, SEMQ_NONE, 0 },
            { "within-rejects-other-id-kind", "base100.semq", "null-a.semq", g_base100, a1, cq, SEMQ_ID_UTF8, rid100, 1u, 1u, 100u, 1u, SEMQ_NONE, 0 },
            /* per-row: the floor of null-200 records max_hamming 2 */
            { "per-row-flags-row-hidden-by-p99", "base200.semq", "hidden.semq", base200, hidden, cq, SEMQ_ID_U64, rid200, 1u, 100u, 200u, 2u, 2u, 1 },
            { "per-row-passes-at-max", "base200.semq", "hidden.semq", base200, hidden, cq, SEMQ_ID_U64, rid200, 1u, 100u, 200u, 2u, 10u, 1 },
            { "per-row-null-within-its-floor", "base200.semq", "null-200.semq", base200, null200, cq, SEMQ_ID_U64, rid200, 1u, 100u, 200u, 2u, 2u, 1 },
            { "per-row-needs-max-hamming", "base200.semq", "hidden.semq", base200, hidden, cq, SEMQ_ID_U64, rid200, 1u, 100u, 200u, 2u, SEMQ_NONE, 1 } };
        /* The expected error is that of evaluate; within is given when evaluate succeeds. */
        semq_gate_options_t* per_row = NULL;
        if (semq_gate_options_create(&per_row, &err) != SEMQ_OK) die("gate options");
        semq_gate_options_set_per_row(per_row, 1);
        for (int i = 0; i < 15; i++) {
            semq_floor_t* f = NULL;
            const semq_status_t fs = ws[i].max_hamming == SEMQ_NONE
                ? semq_floor_create(ws[i].fc, ws[i].kind, ws[i].rid, ws[i].nulls, ws[i].changed, ws[i].total, ws[i].hamming, &f, &err)
                : semq_floor_create_with_max(ws[i].fc, ws[i].kind, ws[i].rid, ws[i].nulls, ws[i].changed, ws[i].total, ws[i].hamming, ws[i].max_hamming, &f, &err);
            if (fs != SEMQ_OK) die("floor");
            semq_diff_t* d = NULL; semq_encoding_diff(ws[i].r, ws[i].c, &d, &err);
            semq_verdict_t* v = NULL;
            const semq_status_t st = semq_diff_evaluate(d, f, ws[i].per_row ? per_row : NULL, &v, &err);
            js_begin_object(); js_kv_str("id", ws[i].id);
            js_key("input"); js_begin_object(); js_kv_str("reference", ws[i].ref); js_kv_str("candidate", ws[i].cand);
            js_key("floor"); js_floor(f);
            if (ws[i].per_row) js_kv_bool("per_row", 1);
            js_end_object();
            js_key("expect");
            if (st == SEMQ_OK) {
                int w = 0; if (semq_diff_within(d, f, &w, &err) != SEMQ_OK) die("within");
                js_begin_object(); js_kv_bool("within", w); js_key("evaluate"); js_verdict(d, v); js_end_object();
            } else { js_error(&err); }
            js_end_object();
            semq_verdict_free(v);
            semq_diff_free(d);
            semq_floor_free(f);
        }
        semq_gate_options_free(per_row);
        /* invalid floors are rejected at construction */
        struct { const char* id; uint32_t kind; uint64_t nulls, changed, total, hamming, max_hamming; } bad[7] = {
            { "floor-changed-exceeds-total", SEMQ_ID_U64, 1u, 5u, 4u, 1u, SEMQ_NONE }, { "floor-total-zero", SEMQ_ID_U64, 1u, 0u, 0u, 1u, SEMQ_NONE },
            { "floor-hamming-exceeds-units", SEMQ_ID_U64, 1u, 1u, 1u, 17u, SEMQ_NONE }, { "floor-nulls-zero", SEMQ_ID_U64, 0u, 1u, 1u, 1u, SEMQ_NONE },
            { "floor-unknown-id-kind", 2u, 1u, 1u, 1u, 1u, SEMQ_NONE },
            { "floor-max-below-hamming", SEMQ_ID_U64, 1u, 1u, 1u, 3u, 2u }, { "floor-max-exceeds-units", SEMQ_ID_U64, 1u, 1u, 1u, 3u, 17u } };
        for (int i = 0; i < 7; i++) {
            semq_floor_t* f = NULL;
            if (bad[i].max_hamming == SEMQ_NONE)
                semq_floor_create(cq, bad[i].kind, rid100, bad[i].nulls, bad[i].changed, bad[i].total, bad[i].hamming, &f, &err);
            else
                semq_floor_create_with_max(cq, bad[i].kind, rid100, bad[i].nulls, bad[i].changed, bad[i].total, bad[i].hamming, bad[i].max_hamming, &f, &err);
            if (f != NULL) die("bad floor accepted");
            js_begin_object(); js_kv_str("id", bad[i].id);
            js_key("input"); js_begin_object(); js_kv_str("reference", "base100.semq"); js_kv_str("candidate", "null-a.semq");
            js_key("floor"); js_floor_fields(cq, bad[i].kind, rid100, bad[i].nulls, bad[i].changed, bad[i].total, bad[i].hamming, bad[i].max_hamming); js_end_object();
            js_key("expect"); js_error(&err); js_end_object();
        }
        /* invalid nulls */
        {
            semq_diff_t* d = NULL; semq_encoding_diff(g_base100, removed, &d, &err);
            const semq_diff_t* rm[1] = { d };
            semq_floor_measure(rm, 1u, &f_none, &err);
            js_begin_object(); js_kv_str("id", "measure-rejects-removed-rows");
            js_key("input"); js_begin_object(); js_key("null_diffs"); js_begin_array(); js_begin_array(); js_str("base100.semq"); js_str("removed.semq"); js_end_array(); js_end_array(); js_end_object();
            js_key("expect"); js_error(&err); js_end_object();
            semq_diff_free(d);
            semq_encoding_diff(ref, enc_changed, &d, &err);
            const semq_diff_t* ec[1] = { d };
            semq_floor_measure(ec, 1u, &f_none, &err);
            js_begin_object(); js_kv_str("id", "measure-rejects-encoder-change");
            js_key("input"); js_begin_object(); js_key("null_diffs"); js_begin_array(); js_begin_array(); js_str("../11-diff/ref.semq"); js_str("../11-diff/encoder-changed.semq"); js_end_array(); js_end_array(); js_end_object();
            js_key("expect"); js_error(&err); js_end_object();
            semq_diff_free(d);
        }
        /* The JSON form, read by the core in every binding: accepted texts give
         * the floor and its saved form; the others are InvalidInput. */
        {
            const uint64_t n = semq_floor_json_size(f_hidden);
            char* base = (char*)xmalloc((size_t)n + 1u);
            if (semq_floor_save(f_hidden, (uint8_t*)base, n, &err) != SEMQ_OK) die("floor save");
            base[n] = '\0';
            char deep[4096] = "{\"nested\":";
            for (int i = 0; i < 63; i++) strcat(deep, "[");
            for (int i = 0; i < 63; i++) strcat(deep, "]");
            strcat(deep, ",");
            char too_deep[4096] = "{\"nested\":[";
            strcat(too_deep, deep + strlen("{\"nested\":"));
            too_deep[strlen(too_deep) - 1] = '\0';
            strcat(too_deep, "],");
            char* unknown = splice(base, "\"rule_revision\":0", "\"rule_revision\":0, \"note\": [1.5e-3, -0, true]");
            struct { const char* id; char* text; } texts[] = {
                { "floor-saved", splice(base, "{", "{") },
                { "floor-without-max-hamming", splice(base, ",\"max_hamming\":10", "") },
                { "floor-ignores-unknown-keys", splice(unknown, "{\"version\"",
                  " {\n  \"comment\": {\"a\": [null, false, \"\\u00e9\\ud83d\\ude00\\n\"]},\n  \"version\"") },
                { "floor-escaped-key", splice(base, "\"version\"", "\"\\u0076ersion\"") },
                { "floor-uppercase-reference-id", splice(base, "\"reference_id\":\"69eb", "\"reference_id\":\"69EB") },
                { "floor-nesting-at-limit", splice(base, "{", deep) },
                { "floor-nesting-above-limit", splice(base, "{", too_deep) },
                { "floor-duplicate-key", splice(base, "\"hamming\":2", "\"hamming\":2,\"hamming\":2") },
                { "floor-duplicate-config-key", splice(base, "\"dim\":16", "\"dim\":16,\"dim\":16") },
                { "floor-other-version", splice(base, "semq-floor/1", "semq-floor/2") },
                { "floor-float-count", splice(base, "\"nulls\":1", "\"nulls\":1.0") },
                { "floor-exponent-count", splice(base, "\"nulls\":1", "\"nulls\":1e0") },
                { "floor-negative-count", splice(base, "\"hamming\":2", "\"hamming\":-2") },
                { "floor-string-count", splice(base, "\"nulls\":1", "\"nulls\":\"1\"") },
                { "floor-bool-count", splice(base, "\"nulls\":1", "\"nulls\":true") },
                { "floor-count-overflow", splice(base, "\"total_rows\":200", "\"total_rows\":18446744073709551616") },
                { "floor-missing-key", splice(base, "\"hamming\":2,", "") },
                { "floor-max-below-hamming", splice(base, "\"max_hamming\":10", "\"max_hamming\":1") },
                { "floor-other-operator-parameter", splice(base, "\"bins\":4", "\"bins\":4,\"sectors\":4") },
                { "floor-trailing-data", splice(base, "\"max_hamming\":10}", "\"max_hamming\":10} {}") },
                { "floor-trailing-comma", splice(base, "\"max_hamming\":10}", "\"max_hamming\":10,}") },
                { "floor-lone-surrogate", splice(base, "{", "{\"x\":\"\\ud800\",") },
                { "floor-invalid-utf8", splice(base, "{", "{\"x\":\"\xc3\x28\",") },
                { "floor-control-character", splice(base, "{", "{\"x\":\"\x01\",") },
                { "floor-nan", splice(base, "{", "{\"x\":NaN,") },
                { "floor-not-an-object", splice("[]", "[]", "[]") },
            };
            for (size_t i = 0u; i < sizeof(texts) / sizeof(texts[0]); i++) {
                char file[96];
                snprintf(file, sizeof(file), "%s.json", texts[i].id);
                write_file(file, texts[i].text, strlen(texts[i].text));
                semq_floor_t* g = NULL;
                const semq_status_t st = semq_floor_load((const uint8_t*)texts[i].text, strlen(texts[i].text), &g, &err);
                js_begin_object(); js_kv_str("id", texts[i].id);
                js_key("input"); js_begin_object(); js_kv_str("floor_json", file); js_end_object();
                js_key("expect");
                if (st == SEMQ_OK) {
                    const uint64_t m = semq_floor_json_size(g);
                    char* saved = (char*)xmalloc((size_t)m + 1u);
                    if (semq_floor_save(g, (uint8_t*)saved, m, &err) != SEMQ_OK) die("floor save");
                    saved[m] = '\0';
                    js_begin_object(); js_key("floor"); js_floor(g); js_kv_str("json", saved); js_end_object();
                    free(saved);
                    semq_floor_free(g);
                } else {
                    js_error(&err);
                }
                js_end_object();
                free(texts[i].text);
            }
            free(unknown);
            free(base);
        }
        semq_floor_free(f_a); semq_floor_free(f_two); semq_floor_free(f_hidden); semq_diff_free(d_hidden);
    }
    js_footer();

    /* ---- 13: report (structural) ---- */
    begin_vector("13-report");
    js_open();
    js_header(13u, "report");
    {
        semq_diff_t* d = NULL; semq_encoding_diff(ref, cand, &d, &err);
        js_begin_object(); js_kv_str("id", "added-removed-changed");
        js_key("input"); js_begin_object(); js_kv_str("reference", "../11-diff/ref.semq"); js_kv_str("candidate", "../11-diff/cand.semq"); js_end_object();
        js_key("expect"); js_begin_object(); js_key("report"); js_diff_report(d); js_end_object();
        js_end_object();
        semq_diff_free(d);
        const semq_diff_t* two[2] = { g_null_a, g_null_a2 }; semq_floor_t* f = NULL; semq_floor_measure(two, 2u, &f, &err);
        js_begin_object(); js_kv_str("id", "floor-json");
        js_key("input"); js_begin_object(); js_key("null_diffs"); js_begin_array();
        js_begin_array(); js_str("../12-floor/base100.semq"); js_str("../12-floor/null-a.semq"); js_end_array();
        js_begin_array(); js_str("../12-floor/base100.semq"); js_str("../12-floor/two-changed.semq"); js_end_array();
        js_end_array(); js_end_object();
        js_key("expect"); js_begin_object(); js_key("floor"); js_floor(f); js_end_object();
        js_end_object();
        semq_floor_free(f);
    }
    js_footer();

    semq_diff_free(g_null_a); semq_diff_free(g_null_a2); semq_diff_free(g_null_b);
    semq_encoding_free(a1); semq_encoding_free(a2); semq_encoding_free(b0); semq_encoding_free(b1);
    semq_encoding_free(removed); semq_encoding_free(added); semq_encoding_free(nothing); semq_encoding_free(g_base100);
    semq_encoding_free(base200); semq_encoding_free(null200); semq_encoding_free(hidden);
    semq_encoding_free(ref); semq_encoding_free(cand); semq_encoding_free(same); semq_encoding_free(enc_changed); semq_encoding_free(empty_ref);
}

/* -------------------------------------------------------------------------- */
/*  15: fp-environment                                                        */
/* -------------------------------------------------------------------------- */

#if defined(__aarch64__) || defined(_M_ARM64)
static void set_flush_to_zero(int on) {
#if defined(_MSC_VER)
    (void)on;
#else
    uint64_t fpcr;
    __asm__ volatile("mrs %0, fpcr" : "=r"(fpcr));
    if (on) fpcr |= (1ull << 24); else fpcr &= ~(1ull << 24);
    __asm__ volatile("msr fpcr, %0" : : "r"(fpcr));
#endif
}
static int can_set_fz(void) { return 1; }
#elif defined(__x86_64__) || defined(_M_X64)
#include <immintrin.h>
static void set_flush_to_zero(int on) {
    unsigned int csr = _mm_getcsr();
    if (on) csr |= 0x8040u; else csr &= ~0x8040u;  /* FZ and DAZ */
    _mm_setcsr(csr);
}
static int can_set_fz(void) { return 1; }
#else
static void set_flush_to_zero(int on) { (void)on; }
static int can_set_fz(void) { return 0; }
#endif

static void vector_15(void) {
    begin_vector("15-fp-environment");
    js_open();
    js_header(15u, "fp-environment");
    semq_error_t err;
    /* Subnormal rows encode to the same bytes with FZ/DAZ on and off. */
    float rows[4 * 4] = { 1.0f, 1e-40f, -1e-41f, 0.0f,  0.0f, 1.0f, 1e-45f, -0.0f,  1e-40f, 0.0f, 0.0f, 1.0f,  0.0f, -1.0f, 1e-39f, 1e-39f };
    const uint64_t ids[4] = { 1u, 2u, 3u, 4u };
    uint8_t off[32], on[32];
    for (uint32_t op = 0u; op < 3u; op++) {
        semq_config_t c = cfg_of(op, 4u, op == SEMQ_ORBIT ? 50u : op == SEMQ_PHASE ? 16u : 4u);
        set_flush_to_zero(0);
        semq_encoding_t* e0 = encode_u64(&c, ids, 4u, rows, NULL, 0u, &err);
        set_flush_to_zero(1);
        semq_encoding_t* e1 = encode_u64(&c, ids, 4u, rows, NULL, 0u, &err);
        set_flush_to_zero(0);
        if (e0 == NULL || e1 == NULL) die("v15 encode");
        semq_encoding_content_digest(e0, off);
        semq_encoding_content_digest(e1, on);
        if (can_set_fz() && memcmp(off, on, 32u) != 0) die("FZ/DAZ changed the bytes");
        js_begin_object();
        js_kv_str("id", op == SEMQ_ORBIT ? "subnormals-orbit" : op == SEMQ_PHASE ? "subnormals-phase" : "subnormals-quant");
        js_key("input"); js_begin_object(); js_key("config"); js_config(&c);
        js_key("vectors_f32"); js_begin_array();
        for (int i = 0; i < 16; i++) { uint32_t bits; memcpy(&bits, &rows[i], 4u); char hex[16]; snprintf(hex, sizeof(hex), "%08x", bits); js_str(hex); }
        js_end_array();
        js_key("ids"); js_begin_object(); js_kv_str("kind", "u64"); js_key("values"); js_begin_array(); for (int i = 0; i < 4; i++) js_u64_str(ids[i]); js_end_array(); js_end_object();
        js_end_object();
        js_key("expect"); js_begin_object(); js_kv_hex("content_digest", off, 32u); js_kv_bool("identical_under_fz_daz", can_set_fz()); js_end_object();
        js_end_object();
        semq_encoding_free(e0); semq_encoding_free(e1);
    }
    /* Rounding modes other than nearest are Unsupported. */
    {
        semq_config_t c = cfg_of(SEMQ_QUANT, 4u, 4u);
        semq_codec_t* codec = NULL;
        if (semq_codec_create(&c, &codec, &err) != SEMQ_OK) die("codec");
        const semq_ids_t in = { SEMQ_ID_U64, 4u, ids, NULL, NULL };
        const int modes[3] = { FE_DOWNWARD, FE_UPWARD, FE_TOWARDZERO };
        const char* names[3] = { "FE_DOWNWARD", "FE_UPWARD", "FE_TOWARDZERO" };
        for (int i = 0; i < 3; i++) {
            const int saved = fegetround();
            if (fesetround(modes[i]) != 0) die("fesetround");
            semq_encoding_t* e = NULL;
            semq_codec_encode(codec, &in, rows, NULL, 0u, &e, &err);
            fesetround(saved);
            if (e != NULL) die("encode accepted a rounding mode");
            js_begin_object(); js_kv_str("id", names[i]);
            js_key("input"); js_begin_object(); js_kv_str("rounding_mode", names[i]); js_key("config"); js_config(&c); js_end_object();
            js_key("expect"); js_error(&err); js_end_object();
        }
        semq_codec_free(codec);
    }
    /* A bad construction environment must not be cached and survive a
     * later restoration to nearest. dim=3 exposes the quant sqrt boundary. */
    {
        const semq_config_t c = cfg_of(SEMQ_QUANT, 3u, 4u);
        const int modes[3] = { FE_DOWNWARD, FE_UPWARD, FE_TOWARDZERO };
        const char* names[3] = { "FE_DOWNWARD", "FE_UPWARD", "FE_TOWARDZERO" };
        for (int i = 0; i < 3; i++) {
            semq_codec_t* codec = NULL;
            const int saved = fegetround();
            if (fesetround(modes[i]) != 0) die("fesetround");
            const semq_status_t status = semq_codec_create(&c, &codec, &err);
            const int unchanged = fegetround() == modes[i];
            fesetround(saved);
            if (status != SEMQ_ERR_UNSUPPORTED || codec != NULL || !unchanged)
                die("codec accepted or changed its construction rounding mode");
            char id[64]; snprintf(id, sizeof(id), "create-%s", names[i]);
            js_begin_object(); js_kv_str("id", id);
            js_key("input"); js_begin_object();
            js_kv_str("operation", "codec_create"); js_kv_str("rounding_mode", names[i]);
            js_key("config"); js_config(&c); js_end_object();
            js_key("expect"); js_error(&err); js_end_object();
            /* Restoring nearest makes a fresh construction valid again. */
            if (semq_codec_create(&c, &codec, &err) != SEMQ_OK) die("codec after restore");
            semq_codec_free(codec);
        }
    }
    js_footer();
}

/* -------------------------------------------------------------------------- */

int main(int argc, char** argv) {
    if (argc > 1) OUT = argv[1];
    if (MKDIR(OUT) != 0) { struct stat st; if (stat(OUT, &st) != 0) die("cannot create output directory"); }
    build_inputs();
    build_samples();
    vector_00();
    vector_01();
    vector_02();
    vector_03();
    vector_04();
    vector_05();
    vector_06();
    vector_07();
    vector_08();
    vector_09();
    vector_10();
    vector_11_13();
    vector_15();
    for (uint32_t i = 0u; i < g_n_samples; i++) semq_encoding_free(g_samples[i].enc);
    free(g_seeded);
    free(g_edges);
    printf("semq_vectors: wrote vectors to %s\n", OUT);
    return 0;
}
