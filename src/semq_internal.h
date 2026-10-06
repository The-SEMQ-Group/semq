/*
 * Copyright (c) 2026 The SEMQ Group Inc.
 * Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
 */

/*
 * semq_internal.h — handle layouts and helpers shared by the core's
 * translation units. Never installed, never part of the ABI.
 */

#ifndef SEMQ_INTERNAL_H
#define SEMQ_INTERNAL_H

#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "semq.h"
#include "semq_platform.h"
#include "core/semq_dispatch.h"

/* -------------------------------------------------------------------------- */
/*  Reference counting (a Diff keeps its two Encodings alive)                 */
/* -------------------------------------------------------------------------- */

#if defined(_MSC_VER)
  #include <intrin.h>
  typedef volatile long semqi_refcount_t;
  static inline void semqi_ref_init(semqi_refcount_t* r) { *r = 1; }
  static inline void semqi_ref_inc(semqi_refcount_t* r) { _InterlockedIncrement(r); }
  static inline int  semqi_ref_dec(semqi_refcount_t* r) { return _InterlockedDecrement(r) == 0; }
#elif !defined(__STDC_NO_ATOMICS__)
  #include <stdatomic.h>
  typedef atomic_int semqi_refcount_t;
  static inline void semqi_ref_init(semqi_refcount_t* r) { atomic_init(r, 1); }
  static inline void semqi_ref_inc(semqi_refcount_t* r) { atomic_fetch_add(r, 1); }
  static inline int  semqi_ref_dec(semqi_refcount_t* r) { return atomic_fetch_sub(r, 1) == 1; }
#else
  #error "SEMQ requires atomic reference counting"
#endif

/* -------------------------------------------------------------------------- */
/*  Handle layouts                                                            */
/* -------------------------------------------------------------------------- */

#define SEMQI_HEADER_BYTES 28u  /* magic(4) version(2) config(13) kind(1) n(8) */
#define SEMQI_FOOTER_BYTES 64u
#define SEMQI_S_OFFSET      6u  /* S starts after magic + version */

/* Offsets of one manifest pair inside the manifest section. */
typedef struct {
    uint32_t key_off;
    uint32_t key_len;
    uint32_t value_off;
    uint32_t value_len;
} semqi_pair_index_t;

struct semq_encoding {
    semqi_refcount_t    refs;
    semq_config_t       config;
    uint32_t            bpv;       /* bytes per vector */
    uint32_t            units;     /* units per row */
    uint32_t            id_kind;
    uint64_t            n;
    uint8_t             header[SEMQI_HEADER_BYTES];
    uint8_t*            ids;       /* ids_section */
    uint64_t            ids_len;
    uint8_t*            rows;      /* rows_section, id order */
    uint64_t            rows_len;
    uint8_t*            manifest;  /* manifest_section */
    uint64_t            manifest_len;
    uint32_t            n_pairs;
    semqi_pair_index_t* pairs;
    uint8_t             footer[SEMQI_FOOTER_BYTES]; /* content_digest ‖ state_id */
};

struct semq_codec {
    semq_config_t               config;
    uint32_t                    bpv;
    uint32_t                    units;
    uint32_t                    phase_packed;
    float                       max_magnitude;
    semq_backend_kind_t         kind;
    const semq_backend_t*       orbit;
    const semq_phase_backend_t* phase;
    const semq_quant_backend_t* quant;
    /* phase only: the representative of every sector, as binary32 (x, y),
     * computed once at creation so decode is a table lookup per pair. */
    float                       phase_rep[2u * 256u];
};

struct semq_floor {
    semq_config_t config;
    uint32_t      id_kind;
    uint8_t       reference_id[32];
    uint64_t      nulls;
    uint64_t      changed_rows;
    uint64_t      total_rows;
    uint64_t      hamming;
    uint64_t      max_hamming;  /* SEMQ_NONE when not recorded */
};

/* Every floor is built here: the construction rules, with `max_hamming`
 * SEMQ_NONE when the floor does not record it. */
semq_status_t semqi_floor_create(const semq_config_t* config, uint32_t id_kind, const uint8_t reference_id[32],
                                 uint64_t nulls, uint64_t changed_rows, uint64_t total_rows, uint64_t hamming,
                                 uint64_t max_hamming, semq_floor_t** out, semq_error_t* err);

struct semq_gate_options {
    int per_row;
};

struct semq_verdict {
    uint32_t  reasons;
    uint64_t  n_rows;
    uint64_t* rows;  /* indices in the diff's changed list */
};

struct semq_diff {
    semq_encoding_t*        ref;
    semq_encoding_t*        cand;
    uint64_t                n_added;
    uint64_t                n_removed;
    uint64_t                n_changed;
    uint64_t                n_unchanged;
    uint64_t*               added;        /* candidate row indices */
    uint64_t*               removed;      /* reference row indices */
    uint64_t*               changed_ref;  /* reference row indices */
    uint64_t*               changed_cand; /* candidate row indices */
    uint64_t*               hamming;
    uint32_t                n_mchanges;
    semq_manifest_change_t* mchanges;
};

/* -------------------------------------------------------------------------- */
/*  Errors                                                                    */
/* -------------------------------------------------------------------------- */

static inline semq_status_t semqi_fail(semq_error_t* err, semq_status_t status, uint64_t row,
                                       uint64_t field, const char* message) {
    if (err != NULL) {
        err->status = (uint32_t)status;
        err->which  = (uint32_t)SEMQ_WHICH_NONE;
        err->row    = row;
        err->field  = field;
        size_t i = 0u;
        for (; i + 1u < sizeof(err->message) && message[i] != '\0'; i++) {
            err->message[i] = message[i];
        }
        err->message[i] = '\0';
    }
    return status;
}

static inline semq_status_t semqi_fail_integrity(semq_error_t* err, semq_which_t which,
                                                 const char* message) {
    const semq_status_t s = semqi_fail(err, SEMQ_ERR_INTEGRITY, SEMQ_NONE, SEMQ_NONE, message);
    if (err != NULL) err->which = (uint32_t)which;
    return s;
}

static inline void semqi_ok(semq_error_t* err) {
    if (err != NULL) {
        err->status = (uint32_t)SEMQ_OK;
        err->which  = (uint32_t)SEMQ_WHICH_NONE;
        err->row    = SEMQ_NONE;
        err->field  = SEMQ_NONE;
        err->message[0] = '\0';
    }
}

#define SEMQI_INVALID(err, row, field, msg) semqi_fail((err), SEMQ_ERR_INVALID_INPUT, (row), (field), (msg))
#define SEMQI_FORMAT(err, section, msg)     semqi_fail((err), SEMQ_ERR_FORMAT, SEMQ_NONE, (uint64_t)(section), (msg))
#define SEMQI_NOMEM(err)                    semqi_fail((err), SEMQ_ERR_NOMEM, SEMQ_NONE, SEMQ_NONE, "allocation failed")

/* -------------------------------------------------------------------------- */
/*  Little-endian access and checked arithmetic                               */
/* -------------------------------------------------------------------------- */

static inline uint16_t semqi_rd16(const uint8_t* p) { uint16_t v; memcpy(&v, p, 2u); return v; }
static inline uint32_t semqi_rd32(const uint8_t* p) { uint32_t v; memcpy(&v, p, 4u); return v; }
static inline uint64_t semqi_rd64(const uint8_t* p) { uint64_t v; memcpy(&v, p, 8u); return v; }
static inline void semqi_wr16(uint8_t* p, uint16_t v) { memcpy(p, &v, 2u); }
static inline void semqi_wr32(uint8_t* p, uint32_t v) { memcpy(p, &v, 4u); }
static inline void semqi_wr64(uint8_t* p, uint64_t v) { memcpy(p, &v, 8u); }

/* 1 when a * b overflows uint64. */
static inline int semqi_mul_ovf(uint64_t a, uint64_t b, uint64_t* out) {
    if (a != 0u && b > UINT64_MAX / a) return 1;
    *out = a * b;
    return 0;
}
static inline int semqi_add_ovf(uint64_t a, uint64_t b, uint64_t* out) {
    if (b > UINT64_MAX - a) return 1;
    *out = a + b;
    return 0;
}
/* 1 when a uint64 byte count is not representable in size_t on this host. */
static inline int semqi_too_big(uint64_t bytes) {
    return bytes > (uint64_t)SIZE_MAX;
}

/* Private cross-module declarations; none are installed or exported. */
semq_status_t semqi_config_from_file(const uint8_t in[13], semq_config_t* out, semq_error_t* err);
const char* semqi_backend_name_for(semq_backend_kind_t kind, uint32_t op);
uint64_t semqi_find_u64(const semq_encoding_t* enc, uint64_t id);
uint64_t semqi_find_utf8(const semq_encoding_t* enc, const uint8_t* id, uint64_t len);
int semqi_id_cmp(const semq_encoding_t* a, uint64_t i, const semq_encoding_t* b, uint64_t j);
void semqi_id_at(const semq_encoding_t* e, uint64_t i, uint64_t* u, const uint8_t** p, uint64_t* l);

/* 128-bit product compare: 1 when a*b <= c*d, exact. */
int semqi_mul_le(uint64_t a, uint64_t b, uint64_t c, uint64_t d);

/* -------------------------------------------------------------------------- */
/*  Ids, manifests, rows                                                      */
/* -------------------------------------------------------------------------- */

/* RFC 3629 validity; rejects NUL bytes. */
int semqi_utf8_valid(const uint8_t* s, uint64_t len);
/* Bytewise order: memcmp over the shorter length, shorter first on a tie. */
int semqi_cmp_bytes(const uint8_t* a, uint64_t alen, const uint8_t* b, uint64_t blen);

/* Sort `ids` by canonical order. Writes an index permutation (sorted
 * position → input index) into *perm (caller frees). Validates every id and
 * rejects duplicates with the repeated row. */
semq_status_t semqi_sort_ids(const semq_ids_t* ids, uint64_t** perm, semq_error_t* err);

/* Build a canonical manifest section from unordered pairs. */
semq_status_t semqi_manifest_build(const semq_pair_t* pairs, uint32_t n_pairs, uint8_t** section,
                                   uint64_t* len, semq_error_t* err);
/* Validate a manifest section (limits, order, UTF-8) and index its pairs.
 * *index is caller-freed; for a section with no pairs it is NULL. */
semq_status_t semqi_manifest_index(const uint8_t* section, uint64_t len, uint32_t* n_pairs,
                                   semqi_pair_index_t** index, semq_error_t* err);

/* Bits per unit for the config's packing. */
uint32_t semqi_bits_per_unit(const semq_config_t* cfg);
/* Unpack one canonical row to `units_per_row` symbols. */
void semqi_unpack_row(const semq_config_t* cfg, const uint8_t* row, uint8_t* symbols);
/* 1 when every symbol is in the alphabet and every padding bit is zero.
 * On failure *unit is the first offending unit (or SEMQ_NONE for padding). */
int semqi_row_canonical(const semq_config_t* cfg, const uint8_t* row, uint64_t* unit);

/* Allocate a zeroed handle with refcount 1. */
semq_encoding_t* semqi_encoding_alloc(void);
/* Given config/kind/n/ids/rows/manifest already filled, compute the header,
 * the pair index and both digests. */
semq_status_t semqi_encoding_finish(semq_encoding_t* enc, semq_error_t* err);
/* Build the ids section from a permutation of input ids. */
semq_status_t semqi_ids_section(const semq_ids_t* ids, const uint64_t* perm, uint8_t** section,
                                uint64_t* len, semq_error_t* err);
/* malloc that never returns NULL for a zero size. */
void* semqi_alloc(uint64_t bytes);
void* semqi_calloc(uint64_t count, uint64_t size);
void semqi_free(void* p);

#endif /* SEMQ_INTERNAL_H */
