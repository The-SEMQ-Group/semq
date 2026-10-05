/*
 * Copyright (c) 2026 The SEMQ Group Inc.
 * Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
 */

/* semq_build.c — build identity, backend names, status names. */

#include "semq_internal.h"
#include "semq_build.h"

SEMQ_API const char* semq_core_version(void) {
    return SEMQ_CORE_VERSION;
}

SEMQ_API const char* semq_build_id(void) {
    return SEMQ_BUILD_ID;
}

const char* semqi_backend_name_for(semq_backend_kind_t kind, uint32_t op) {
    switch (op) {
        case SEMQ_ORBIT: {
            const semq_backend_t* t = semq_dispatch_get(kind);
            return (t == &SEMQ_SCALAR_BACKEND) ? "scalar" : semq_backend_kind_name(kind);
        }
        case SEMQ_PHASE: {
            const semq_phase_backend_t* t = semq_dispatch_get_phase(kind);
            return (t == &SEMQ_PHASE_SCALAR_BACKEND) ? "scalar" : semq_backend_kind_name(kind);
        }
        case SEMQ_QUANT: {
            const semq_quant_backend_t* t = semq_dispatch_get_quant(kind);
            if (t == &SEMQ_QUANT_SCALAR_BACKEND) return "scalar";
#if defined(__aarch64__) || defined(_M_ARM64)
            if (t == &SEMQ_QUANT_NEON_BACKEND) return "neon";
#endif
            return semq_backend_kind_name(kind);
        }
        default:
            return "none";
    }
}

SEMQ_API const char* semq_backend_name(uint32_t op) {
    return semqi_backend_name_for(semq_dispatch_select_for(op), op);
}

SEMQ_API const char* semq_status_name(uint32_t status) {
    switch (status) {
        case SEMQ_OK:                return "ok";
        case SEMQ_ERR_INVALID_INPUT: return "invalid_input";
        case SEMQ_ERR_INCOMPATIBLE:  return "incompatible";
        case SEMQ_ERR_FORMAT:        return "format";
        case SEMQ_ERR_INTEGRITY:     return "integrity";
        case SEMQ_ERR_UNSUPPORTED:   return "unsupported";
        case SEMQ_ERR_NOMEM:         return "nomem";
        case SEMQ_ERR_INTERNAL:      return "internal";
        default:                     return "unknown";
    }
}
