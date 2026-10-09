/*
 * Copyright (c) 2026 The SEMQ Group Inc.
 * Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
 */

/*
 * The floor schema: one JSON object, written and read here so that every
 * binding shares one definition.
 *
 * Reading is strict on the keys it knows and ignores the others, so a file
 * written by a later version with an added key still reads. Known keys
 * appear at most once, counts are JSON integers without sign, fraction or
 * exponent, and the input must be valid JSON in valid UTF-8.
 */
#include "semq_internal.h"
#include <string.h>

static const char VERSION[] = "semq-floor/1";
static const char HEX[]     = "0123456789abcdef";

/* Nesting allowed inside an ignored value. */
#define JSON_MAX_DEPTH 64

/* -------------------------------------------------------------------------- */
/*  Writing                                                                   */
/* -------------------------------------------------------------------------- */

typedef struct {
    uint8_t* out; /* NULL to measure */
    uint64_t n;
} writer_t;

static void put(writer_t* w, const char* s) {
    const size_t len = strlen(s);
    if (w->out != NULL) memcpy(w->out + w->n, s, len);
    w->n += len;
}

static void put_u64(writer_t* w, uint64_t v) {
    char digits[20];
    int k = 0;
    do {
        digits[k++] = (char)('0' + (int)(v % 10u));
        v /= 10u;
    } while (v != 0u);
    while (k > 0) {
        if (w->out != NULL) w->out[w->n] = (uint8_t)digits[k - 1];
        w->n++;
        k--;
    }
}

static void put_count(writer_t* w, const char* key, uint64_t v) {
    put(w, ",\"");
    put(w, key);
    put(w, "\":");
    put_u64(w, v);
}

static void render(const semq_floor_t* f, writer_t* w) {
    const semq_config_t* c = &f->config;
    const char* op = c->op == SEMQ_ORBIT ? "orbit" : c->op == SEMQ_PHASE ? "phase" : "quant";
    const char* parameter = c->op == SEMQ_ORBIT ? "scale" : c->op == SEMQ_PHASE ? "sectors" : "bins";
    put(w, "{\"version\":\"");
    put(w, VERSION);
    put(w, "\",\"config\":{\"operator\":\"");
    put(w, op);
    put(w, "\",\"dim\":");
    put_u64(w, c->dim);
    put_count(w, parameter, c->p1);
    put_count(w, "rule_revision", c->p2);
    put(w, "},\"id_kind\":\"");
    put(w, f->id_kind == SEMQ_ID_U64 ? "u64" : "utf8");
    put(w, "\",\"reference_id\":\"");
    for (unsigned i = 0u; i < SEMQ_DIGEST_BYTES; i++) {
        if (w->out != NULL) {
            w->out[w->n]      = (uint8_t)HEX[f->reference_id[i] >> 4];
            w->out[w->n + 1u] = (uint8_t)HEX[f->reference_id[i] & 15u];
        }
        w->n += 2u;
    }
    put(w, "\"");
    put_count(w, "nulls", f->nulls);
    put_count(w, "changed_rows", f->changed_rows);
    put_count(w, "total_rows", f->total_rows);
    put_count(w, "hamming", f->hamming);
    if (f->max_hamming != SEMQ_NONE) put_count(w, "max_hamming", f->max_hamming);
    if (f->distinct_nulls != SEMQ_NONE) put_count(w, "distinct_nulls", f->distinct_nulls);
    put(w, "}");
}

SEMQ_API uint64_t semq_floor_json_size(const semq_floor_t* f) {
    writer_t w = { NULL, 0u };
    render(f, &w);
    return w.n;
}

SEMQ_API semq_status_t semq_floor_save(const semq_floor_t* f, uint8_t* out, uint64_t cap, semq_error_t* err) {
    if (f == NULL || out == NULL) return SEMQI_INVALID(err, SEMQ_NONE, SEMQ_NONE, "NULL argument");
    if (cap < semq_floor_json_size(f)) return SEMQI_INVALID(err, SEMQ_NONE, SEMQ_NONE, "output buffer is too small");
    writer_t w = { out, 0u };
    render(f, &w);
    semqi_ok(err);
    return SEMQ_OK;
}

/* -------------------------------------------------------------------------- */
/*  Reading                                                                   */
/* -------------------------------------------------------------------------- */

typedef struct {
    const uint8_t* p;
    const uint8_t* end;
    const char*    error; /* set on the first failure */
} reader_t;

static int fail(reader_t* r, const char* message) {
    if (r->error == NULL) r->error = message;
    return 0;
}

static void ws(reader_t* r) {
    while (r->p < r->end && (*r->p == ' ' || *r->p == '\t' || *r->p == '\n' || *r->p == '\r')) r->p++;
}

static int expect(reader_t* r, uint8_t c, const char* message) {
    ws(r);
    if (r->p >= r->end || *r->p != c) return fail(r, message);
    r->p++;
    return 1;
}

static int hex4(reader_t* r, uint32_t* out) {
    if (r->end - r->p < 4) return fail(r, "floor is not valid JSON: bad \\u escape");
    uint32_t v = 0u;
    for (int i = 0; i < 4; i++) {
        const uint8_t c = r->p[i];
        const int d = c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10
                    : c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
        if (d < 0) return fail(r, "floor is not valid JSON: bad \\u escape");
        v = (v << 4) | (uint32_t)d;
    }
    r->p += 4;
    *out = v;
    return 1;
}

/* A JSON string at r->p (after whitespace). The decoded bytes go to `buf`
 * up to `cap`; `*len` is the full decoded length, so a caller sees when
 * the string did not fit. */
static int string(reader_t* r, uint8_t* buf, size_t cap, size_t* len) {
    ws(r);
    if (r->p >= r->end || *r->p != '"') return fail(r, "floor is not valid JSON: expected a string");
    r->p++;
    size_t n = 0u;
    for (;;) {
        /* A run of plain bytes: '"' and '\\' are ASCII, so a run never splits a UTF-8 sequence. */
        const uint8_t* run = r->p;
        while (r->p < r->end && *r->p != '"' && *r->p != '\\') {
            if (*r->p < 0x20u) return fail(r, "floor is not valid JSON: control character in a string");
            r->p++;
        }
        if (r->p >= r->end) return fail(r, "floor is not valid JSON: unterminated string");
        const size_t k = (size_t)(r->p - run);
        if (k > 0u && !semqi_utf8_valid(run, k)) return fail(r, "floor is not valid UTF-8");
        for (size_t i = 0u; i < k; i++, n++) if (n < cap) buf[n] = run[i];
        if (*r->p == '"') {
            r->p++;
            *len = n;
            return 1;
        }
        r->p++; /* backslash */
        if (r->p >= r->end) return fail(r, "floor is not valid JSON: unterminated string");
        const uint8_t e = *r->p++;
        uint32_t cp;
        switch (e) {
        case '"': cp = '"'; break;
        case '\\': cp = '\\'; break;
        case '/': cp = '/'; break;
        case 'b': cp = 8u; break;
        case 'f': cp = 12u; break;
        case 'n': cp = 10u; break;
        case 'r': cp = 13u; break;
        case 't': cp = 9u; break;
        case 'u':
            if (!hex4(r, &cp)) return 0;
            if (cp >= 0xDC00u && cp <= 0xDFFFu) return fail(r, "floor is not valid JSON: lone surrogate");
            if (cp >= 0xD800u && cp <= 0xDBFFu) {
                uint32_t lo;
                if (r->end - r->p < 2 || r->p[0] != '\\' || r->p[1] != 'u') return fail(r, "floor is not valid JSON: lone surrogate");
                r->p += 2;
                if (!hex4(r, &lo)) return 0;
                if (lo < 0xDC00u || lo > 0xDFFFu) return fail(r, "floor is not valid JSON: lone surrogate");
                cp = 0x10000u + ((cp - 0xD800u) << 10) + (lo - 0xDC00u);
            }
            break;
        default: return fail(r, "floor is not valid JSON: bad escape");
        }
        uint8_t u[4];
        size_t m;
        if (cp < 0x80u) { u[0] = (uint8_t)cp; m = 1u; }
        else if (cp < 0x800u) { u[0] = (uint8_t)(0xC0u | (cp >> 6)); u[1] = (uint8_t)(0x80u | (cp & 63u)); m = 2u; }
        else if (cp < 0x10000u) {
            u[0] = (uint8_t)(0xE0u | (cp >> 12)); u[1] = (uint8_t)(0x80u | ((cp >> 6) & 63u));
            u[2] = (uint8_t)(0x80u | (cp & 63u)); m = 3u;
        } else {
            u[0] = (uint8_t)(0xF0u | (cp >> 18)); u[1] = (uint8_t)(0x80u | ((cp >> 12) & 63u));
            u[2] = (uint8_t)(0x80u | ((cp >> 6) & 63u)); u[3] = (uint8_t)(0x80u | (cp & 63u)); m = 4u;
        }
        for (size_t i = 0u; i < m; i++, n++) if (n < cap) buf[n] = u[i];
    }
}

static int digits(reader_t* r) {
    const uint8_t* start = r->p;
    while (r->p < r->end && *r->p >= '0' && *r->p <= '9') r->p++;
    return r->p > start;
}

/* Any JSON number (for ignored values). */
static int number(reader_t* r) {
    if (r->p < r->end && *r->p == '-') r->p++;
    if (r->p < r->end && *r->p == '0') r->p++;
    else if (!digits(r)) return fail(r, "floor is not valid JSON: bad number");
    if (r->p < r->end && *r->p == '.') {
        r->p++;
        if (!digits(r)) return fail(r, "floor is not valid JSON: bad number");
    }
    if (r->p < r->end && (*r->p == 'e' || *r->p == 'E')) {
        r->p++;
        if (r->p < r->end && (*r->p == '+' || *r->p == '-')) r->p++;
        if (!digits(r)) return fail(r, "floor is not valid JSON: bad number");
    }
    return 1;
}

static int literal(reader_t* r, const char* word) {
    const size_t n = strlen(word);
    if ((size_t)(r->end - r->p) < n || memcmp(r->p, word, n) != 0) return fail(r, "floor is not valid JSON");
    r->p += n;
    return 1;
}

/* Validate and skip one JSON value. */
static int skip(reader_t* r, int depth) {
    ws(r);
    if (r->p >= r->end) return fail(r, "floor is not valid JSON: expected a value");
    size_t len;
    switch (*r->p) {
    case '"': return string(r, NULL, 0u, &len);
    case 't': return literal(r, "true");
    case 'f': return literal(r, "false");
    case 'n': return literal(r, "null");
    case '{':
    case '[': {
        const uint8_t close = *r->p == '{' ? '}' : ']';
        const int object = close == '}';
        if (depth >= JSON_MAX_DEPTH) return fail(r, "floor is nested too deeply");
        r->p++;
        ws(r);
        if (r->p < r->end && *r->p == close) { r->p++; return 1; }
        for (;;) {
            if (object) {
                if (!string(r, NULL, 0u, &len) || !expect(r, ':', "floor is not valid JSON: expected ':'")) return 0;
            }
            if (!skip(r, depth + 1)) return 0;
            ws(r);
            if (r->p < r->end && *r->p == ',') { r->p++; continue; }
            return expect(r, close, "floor is not valid JSON: expected ',' or a closing bracket");
        }
    }
    default:
        if (*r->p == '-' || (*r->p >= '0' && *r->p <= '9')) return number(r);
        return fail(r, "floor is not valid JSON: expected a value");
    }
}

/* A count: a JSON integer in [0, 2^64), no sign, fraction or exponent. */
static int count(reader_t* r, uint64_t* out, const char* message) {
    ws(r);
    const uint8_t* start = r->p;
    if (r->p >= r->end || *r->p < '0' || *r->p > '9') {
        if (r->p < r->end && (*r->p == '-' || *r->p == '"' || *r->p == 't' || *r->p == 'f' || *r->p == 'n' ||
                              *r->p == '{' || *r->p == '[')) {
            return fail(r, message);
        }
        return fail(r, "floor is not valid JSON: expected a value");
    }
    uint64_t v = 0u;
    while (r->p < r->end && *r->p >= '0' && *r->p <= '9') {
        const uint64_t d = (uint64_t)(*r->p - '0');
        if (v > (UINT64_MAX - d) / 10u) return fail(r, message);
        v = v * 10u + d;
        r->p++;
    }
    if ((r->p - start > 1 && *start == '0') ||
        (r->p < r->end && (*r->p == '.' || *r->p == 'e' || *r->p == 'E'))) {
        return fail(r, message);
    }
    *out = v;
    return 1;
}

/* A key at r->p, matched against `names`; -1 when unknown. */
static int key(reader_t* r, const char* const* names, int n_names, int* index) {
    uint8_t buf[32];
    size_t len;
    if (!string(r, buf, sizeof(buf), &len) || !expect(r, ':', "floor is not valid JSON: expected ':'")) return 0;
    *index = -1;
    for (int i = 0; i < n_names && len <= sizeof(buf); i++) {
        if (strlen(names[i]) == len && memcmp(names[i], buf, len) == 0) *index = i;
    }
    return 1;
}

/* After a member: ',' to continue, or the closing brace. Sets *more. */
static int next(reader_t* r, int* more) {
    ws(r);
    if (r->p < r->end && *r->p == ',') {
        r->p++;
        *more = 1;
        return 1;
    }
    *more = 0;
    return expect(r, '}', "floor is not valid JSON: expected ',' or '}'");
}

/* A string value that must be one of `allowed`; its index in *out. */
static int choice(reader_t* r, const char* const* allowed, int n, int* out, const char* message) {
    uint8_t buf[16];
    size_t len;
    ws(r);
    if (r->p >= r->end || *r->p != '"') return fail(r, message);
    if (!string(r, buf, sizeof(buf), &len)) return 0;
    for (int i = 0; i < n; i++) {
        if (len <= sizeof(buf) && strlen(allowed[i]) == len && memcmp(allowed[i], buf, len) == 0) {
            *out = i;
            return 1;
        }
    }
    return fail(r, message);
}

enum { C_OPERATOR, C_DIM, C_SCALE, C_SECTORS, C_BINS, C_RULE_REVISION, C_KEYS };
static const char* const CONFIG_KEYS[C_KEYS] = { "operator", "dim", "scale", "sectors", "bins", "rule_revision" };

static int config(reader_t* r, semq_config_t* out) {
    static const char* const operators[3] = { "orbit", "phase", "quant" };
    uint64_t v[C_KEYS] = { 0u };
    unsigned seen = 0u;
    int op = -1;
    if (!expect(r, '{', "floor.config must be an object")) return 0;
    ws(r);
    if (r->p < r->end && *r->p == '}') {
        r->p++;
    } else {
        for (int more = 1; more;) {
            int k;
            if (!key(r, CONFIG_KEYS, C_KEYS, &k)) return 0;
            if (k < 0) {
                if (!skip(r, 2)) return 0;
            } else {
                if (seen & (1u << k)) return fail(r, "floor.config has a duplicate key");
                seen |= 1u << k;
                if (k == C_OPERATOR) {
                    if (!choice(r, operators, 3, &op, "floor.config.operator must be \"orbit\", \"phase\" or \"quant\"")) return 0;
                } else if (!count(r, &v[k], "floor.config fields must be integers in [0, 2^32)")) {
                    return 0;
                } else if (v[k] > UINT32_MAX) {
                    return fail(r, "floor.config fields must be integers in [0, 2^32)");
                }
            }
            if (!next(r, &more)) return 0;
        }
    }
    if (op < 0) return fail(r, "floor.config is missing operator");
    const int parameter = op == SEMQ_ORBIT ? C_SCALE : op == SEMQ_PHASE ? C_SECTORS : C_BINS;
    if (!(seen & (1u << C_DIM)) || !(seen & (1u << parameter)) || !(seen & (1u << C_RULE_REVISION))) {
        return fail(r, "floor.config is missing dim, its operator's parameter or rule_revision");
    }
    if (seen & ((1u << C_SCALE) | (1u << C_SECTORS) | (1u << C_BINS)) & ~(1u << parameter)) {
        return fail(r, "floor.config has a parameter of another operator");
    }
    out->op  = (uint32_t)op;
    out->dim = (uint32_t)v[C_DIM];
    out->p1  = (uint32_t)v[parameter];
    out->p2  = (uint32_t)v[C_RULE_REVISION];
    return 1;
}

/* The required keys come first; K_MAX_HAMMING and later are optional. */
enum { K_VERSION, K_CONFIG, K_ID_KIND, K_REFERENCE_ID, K_NULLS, K_CHANGED_ROWS, K_TOTAL_ROWS, K_HAMMING,
       K_MAX_HAMMING, K_DISTINCT_NULLS, K_KEYS };
static const char* const KEYS[K_KEYS] = { "version", "config", "id_kind", "reference_id", "nulls",
                                          "changed_rows", "total_rows", "hamming", "max_hamming",
                                          "distinct_nulls" };
static const char* const COUNT_ERRORS[K_KEYS] = {
    NULL, NULL, NULL, NULL,
    "floor.nulls must be an integer in [0, 2^64)",
    "floor.changed_rows must be an integer in [0, 2^64)",
    "floor.total_rows must be an integer in [0, 2^64)",
    "floor.hamming must be an integer in [0, 2^64)",
    "floor.max_hamming must be an integer in [0, 2^64)",
    "floor.distinct_nulls must be an integer in [0, 2^64)",
};
#define OPTIONAL_KEYS ((1u << K_MAX_HAMMING) | (1u << K_DISTINCT_NULLS))

SEMQ_API semq_status_t semq_floor_load(const uint8_t* buf, uint64_t len, semq_floor_t** out, semq_error_t* err) {
    if (out == NULL) return SEMQI_INVALID(err, SEMQ_NONE, SEMQ_NONE, "output is NULL");
    *out = NULL;
    if (buf == NULL && len > 0u) return SEMQI_INVALID(err, SEMQ_NONE, SEMQ_NONE, "NULL argument");
    static const char* const versions[1] = { VERSION };
    static const char* const kinds[2]    = { "u64", "utf8" };
    reader_t r = { buf, buf + len, NULL };
    semq_config_t cfg;
    memset(&cfg, 0, sizeof(cfg));
    uint8_t rid[32];
    uint64_t counts[K_KEYS] = { 0u };
    unsigned seen = 0u;
    int kind = 0, version = 0;
    int ok = expect(&r, '{', "floor must be a JSON object");
    ws(&r);
    if (ok && r.p < r.end && *r.p == '}') {
        r.p++;
    } else {
        for (int more = ok; more && ok;) {
            int k;
            ok = key(&r, KEYS, K_KEYS, &k);
            if (!ok) break;
            if (k >= 0 && (seen & (1u << k))) {
                ok = fail(&r, "floor has a duplicate key");
                break;
            }
            if (k >= 0) seen |= 1u << k;
            switch (k) {
            case K_VERSION: ok = choice(&r, versions, 1, &version, "floor.version must be \"semq-floor/1\""); break;
            case K_CONFIG: ok = config(&r, &cfg); break;
            case K_ID_KIND: ok = choice(&r, kinds, 2, &kind, "floor.id_kind must be \"u64\" or \"utf8\""); break;
            case K_REFERENCE_ID: {
                uint8_t text[64] = { 0 };
                size_t n = 0u;
                ws(&r);
                ok = r.p < r.end && *r.p == '"' ? string(&r, text, sizeof(text), &n)
                                                 : fail(&r, "floor.reference_id must be 64 hex characters");
                if (ok && n != 64u) ok = fail(&r, "floor.reference_id must be 64 hex characters");
                for (size_t i = 0u; ok && i < 64u; i++) {
                    const uint8_t c = text[i];
                    const int d = c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10
                                : c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
                    if (d < 0) {
                        ok = fail(&r, "floor.reference_id must be 64 hex characters");
                        break;
                    }
                    rid[i / 2u] = (uint8_t)(i % 2u == 0u ? d << 4 : rid[i / 2u] | d);
                }
                break;
            }
            case K_NULLS:
            case K_CHANGED_ROWS:
            case K_TOTAL_ROWS:
            case K_HAMMING:
            case K_MAX_HAMMING:
            case K_DISTINCT_NULLS: ok = count(&r, &counts[k], COUNT_ERRORS[k]); break;
            default: ok = skip(&r, 1); break; /* unknown key */
            }
            if (ok) ok = next(&r, &more);
        }
    }
    if (ok) {
        ws(&r);
        if (r.p != r.end) ok = fail(&r, "floor is not valid JSON: data after the object");
    }
    if (ok && (seen | OPTIONAL_KEYS) != (1u << K_KEYS) - 1u) {
        for (int k = 0; k < K_MAX_HAMMING; k++) {
            if (!(seen & (1u << k))) {
                static const char* const missing[K_MAX_HAMMING] = {
                    "floor is missing version", "floor is missing config", "floor is missing id_kind",
                    "floor is missing reference_id", "floor is missing nulls", "floor is missing changed_rows",
                    "floor is missing total_rows", "floor is missing hamming" };
                ok = fail(&r, missing[k]);
                break;
            }
        }
    }
    /* SEMQ_NONE marks an absent optional key, so the value itself is reserved. */
    if (ok && (seen & (1u << K_MAX_HAMMING)) && counts[K_MAX_HAMMING] == SEMQ_NONE) {
        ok = fail(&r, "floor.max_hamming is 18446744073709551615, which is reserved (SEMQ_NONE)");
    }
    if (ok && (seen & (1u << K_DISTINCT_NULLS)) && counts[K_DISTINCT_NULLS] == SEMQ_NONE) {
        ok = fail(&r, "floor.distinct_nulls is 18446744073709551615, which is reserved (SEMQ_NONE)");
    }
    if (!ok) return SEMQI_INVALID(err, SEMQ_NONE, SEMQ_NONE, r.error);
    (void)version;
    const semq_status_t s = semq_config_validate(&cfg, err);
    if (s != SEMQ_OK) return s;
    return semqi_floor_create(&cfg, kind == 0 ? SEMQ_ID_U64 : SEMQ_ID_UTF8, rid, counts[K_NULLS],
                              counts[K_CHANGED_ROWS], counts[K_TOTAL_ROWS], counts[K_HAMMING],
                              (seen & (1u << K_MAX_HAMMING)) ? counts[K_MAX_HAMMING] : SEMQ_NONE,
                              (seen & (1u << K_DISTINCT_NULLS)) ? counts[K_DISTINCT_NULLS] : SEMQ_NONE, out, err);
}
