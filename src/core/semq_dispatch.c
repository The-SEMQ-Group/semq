/*
 * Copyright (c) 2026 The SEMQ Group Inc.
 * Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
 */

/*
 * semq_dispatch.c — runtime dispatcher.
 *
 * Detects the host's CPU features when a codec is created and selects an
 * operator-specific backend.
 * Detection runs when a codec is created and the result is cached in
 * the codec. Every subsequent encode call is a single indirect jump into
 * the chosen backend.
 *
 * Backend selection priority:
 *   x86_64 orbit:  AVX-512  →  AVX2 + FMA  →  Scalar
 *   x86_64 quant:  AVX2 + FMA  →  AVX-512  →  Scalar
 *   ARM64  :  SVE      →  NEON        →  Scalar
 *
 * The environment variable SEMQ_FORCE_BACKEND, when set to one of
 * "scalar", "neon", "avx2", "avx512", or "sve", short-circuits the
 * detection and forces the dispatcher to that backend (falling back to
 * scalar if the requested backend is not linked into this build). It
 * exists solely for testing — production deployments rely on automatic
 * detection and must not depend on this variable.
 */

#include "semq_dispatch.h"

#include <stddef.h>
#include <stdlib.h>
#include <string.h>

#if defined(__x86_64__) || defined(_M_X64)
  #define SEMQ_ARCH_X86_64 1
#elif defined(__aarch64__) || defined(_M_ARM64)
  #define SEMQ_ARCH_ARM64 1
#endif

#if defined(SEMQ_ARCH_X86_64)
  #if defined(_MSC_VER)
    #include <intrin.h>
  #else
    #include <cpuid.h>
  #endif
#endif

#if defined(SEMQ_ARCH_ARM64)
  #if defined(__APPLE__)
    #include <sys/sysctl.h>
  #elif defined(__linux__)
    #include <sys/auxv.h>
    #include <asm/hwcap.h>
  #endif
#endif

/* -------------------------------------------------------------------------- */
/*  CPU feature detection                                                     */
/* -------------------------------------------------------------------------- */

#if defined(SEMQ_ARCH_X86_64)

typedef struct {
    int avx2;
    int fma;
    int avx512f;
    int avx512bw;
    int avx512vl;
    int sse4_2;
    int os_ymm;   /* OS saves YMM state (XCR0 bits 1-2) */
    int os_zmm;   /* OS saves ZMM/opmask state (XCR0 bits 5-7) */
} x86_features_t;

/* XCR0 via xgetbv; only valid when CPUID.1:ECX.OSXSAVE is set. */
static uint64_t read_xcr0(void) {
#if defined(_MSC_VER)
    return (uint64_t)_xgetbv(0);
#else
    unsigned int lo, hi;
    __asm__ volatile("xgetbv" : "=a"(lo), "=d"(hi) : "c"(0));
    return ((uint64_t)hi << 32) | lo;
#endif
}

static void detect_x86_features(x86_features_t* f) {
    f->avx2 = 0;
    f->fma = 0;
    f->avx512f = 0;
    f->avx512bw = 0;
    f->avx512vl = 0;
    f->sse4_2 = 0;
    f->os_ymm = 0;
    f->os_zmm = 0;

    unsigned int eax, ebx, ecx, edx;

#if defined(_MSC_VER)
    int regs[4] = {0};
    __cpuid(regs, 1);
    eax = (unsigned)regs[0]; ebx = (unsigned)regs[1];
    ecx = (unsigned)regs[2]; edx = (unsigned)regs[3];
#else
    if (!__get_cpuid(1u, &eax, &ebx, &ecx, &edx)) {
        return;
    }
#endif

    f->sse4_2 = (ecx & (1u << 20)) != 0u;
    f->fma    = (ecx & (1u << 12)) != 0u;
    /* An AVX kernel is only safe when the OS restores the wide registers:
     * CPUID advertising AVX2 is not enough (OSXSAVE + XCR0 must agree). */
    if ((ecx & (1u << 27)) != 0u) {
        const uint64_t xcr0 = read_xcr0();
        f->os_ymm = (xcr0 & 0x6u) == 0x6u;
        f->os_zmm = f->os_ymm && (xcr0 & 0xE0u) == 0xE0u;
    }

#if defined(_MSC_VER)
    __cpuidex(regs, 7, 0);
    eax = (unsigned)regs[0]; ebx = (unsigned)regs[1];
    ecx = (unsigned)regs[2]; edx = (unsigned)regs[3];
#else
    if (!__get_cpuid_count(7u, 0u, &eax, &ebx, &ecx, &edx)) {
        return;
    }
#endif

    f->avx2     = ((ebx & (1u <<  5)) != 0u) && f->os_ymm;
    f->avx512f  = ((ebx & (1u << 16)) != 0u) && f->os_zmm;
    f->avx512bw = ((ebx & (1u << 30)) != 0u) && f->os_zmm;
    f->avx512vl = ((ebx & (1u << 31)) != 0u) && f->os_zmm;
}

#elif defined(SEMQ_ARCH_ARM64)

typedef struct {
    int neon;
    int sve;
} arm_features_t;

static void detect_arm_features(arm_features_t* f) {
    /* NEON is mandatory on ARMv8-A — assume present. */
    f->neon = 1;
    f->sve  = 0;

#if defined(__APPLE__)
    int has_sve = 0;
    size_t sz = sizeof(has_sve);
    if (sysctlbyname("hw.optional.arm.FEAT_SVE", &has_sve, &sz, NULL, 0) == 0) {
        f->sve = has_sve != 0;
    }
#elif defined(__linux__)
  #ifdef HWCAP_SVE
    unsigned long hwcap = getauxval(AT_HWCAP);
    f->sve = (hwcap & HWCAP_SVE) != 0ul;
  #endif
#endif
}

#endif /* arch */

int semq_dispatch_has_sha256(void) {
#if defined(SEMQ_ARCH_ARM64)
  #if defined(__APPLE__)
    int available = 0;
    size_t size = sizeof(available);
    return sysctlbyname("hw.optional.arm.FEAT_SHA256", &available, &size, NULL, 0) == 0
        && size == sizeof(available) && available != 0;
  #elif defined(__linux__) && defined(HWCAP_SHA2)
    return (getauxval(AT_HWCAP) & HWCAP_SHA2) != 0ul;
  #endif
#endif
    return 0;
}

/* -------------------------------------------------------------------------- */
/*  Force-backend override (testing only)                                     */
/* -------------------------------------------------------------------------- */

static int force_backend_from_env(semq_backend_kind_t* out) {
    const char* v = getenv("SEMQ_FORCE_BACKEND");
    if (v == NULL || *v == '\0') return 0;
    if (strcmp(v, "scalar") == 0) { *out = SEMQ_BACKEND_SCALAR; return 1; }
    if (strcmp(v, "neon")   == 0) { *out = SEMQ_BACKEND_NEON;   return 1; }
    if (strcmp(v, "avx2")   == 0) { *out = SEMQ_BACKEND_AVX2;   return 1; }
    if (strcmp(v, "avx512") == 0) { *out = SEMQ_BACKEND_AVX512; return 1; }
    if (strcmp(v, "sve")    == 0) { *out = SEMQ_BACKEND_SVE;    return 1; }
    return 0;
}

/* Resolve a requested backend kind to the best one actually usable on this
 * host. This is the policy that protects forced-backend selections from
 * SIGILL on incapable hardware: forcing AVX-512 on Haswell, or SVE on Apple
 * Silicon, downgrades the kind itself (not just the function table) to
 * SCALAR. Callers that ask for a wrong-arch backend (AVX2 on ARM, NEON on
 * x86) likewise end up at SCALAR. */
static semq_backend_kind_t resolve_available(semq_backend_kind_t k) {
    if (k == SEMQ_BACKEND_SCALAR) return SEMQ_BACKEND_SCALAR;
#if defined(SEMQ_ARCH_X86_64)
    if (k == SEMQ_BACKEND_AVX2) {
        x86_features_t f; detect_x86_features(&f);
        if (f.avx2 && f.fma) return SEMQ_BACKEND_AVX2;
        return SEMQ_BACKEND_SCALAR;
    }
    if (k == SEMQ_BACKEND_AVX512) {
        x86_features_t f; detect_x86_features(&f);
        if (f.avx512f && f.avx512bw && f.avx512vl) return SEMQ_BACKEND_AVX512;
        return SEMQ_BACKEND_SCALAR;
    }
#endif
#if defined(SEMQ_ARCH_ARM64)
    if (k == SEMQ_BACKEND_NEON) return SEMQ_BACKEND_NEON;  /* mandatory on ARMv8 */
    if (k == SEMQ_BACKEND_SVE) {
        arm_features_t f; detect_arm_features(&f);
        if (f.sve) return SEMQ_BACKEND_SVE;
        return SEMQ_BACKEND_SCALAR;
    }
#endif
    /* Wrong-arch request (e.g. avx2 on ARM, sve on x86): scalar. */
    return SEMQ_BACKEND_SCALAR;
}

/* -------------------------------------------------------------------------- */
/*  Public dispatcher API                                                     */
/* -------------------------------------------------------------------------- */

semq_backend_kind_t semq_dispatch_select(void) {
    semq_backend_kind_t forced;
    if (force_backend_from_env(&forced)) {
        return resolve_available(forced);
    }

#if defined(SEMQ_ARCH_X86_64)
    x86_features_t f;
    detect_x86_features(&f);
    if (f.avx512f && f.avx512bw && f.avx512vl) return SEMQ_BACKEND_AVX512;
    if (f.avx2 && f.fma)                       return SEMQ_BACKEND_AVX2;
    return SEMQ_BACKEND_SCALAR;
#elif defined(SEMQ_ARCH_ARM64)
    arm_features_t f;
    detect_arm_features(&f);
    if (f.sve)  return SEMQ_BACKEND_SVE;
    if (f.neon) return SEMQ_BACKEND_NEON;
    return SEMQ_BACKEND_SCALAR;
#else
    return SEMQ_BACKEND_SCALAR;
#endif
}

semq_backend_kind_t semq_dispatch_select_for(uint32_t op) {
    semq_backend_kind_t forced;
    if (force_backend_from_env(&forced)) return resolve_available(forced);

    const semq_backend_kind_t best = semq_dispatch_select();
#if defined(SEMQ_ARCH_X86_64)
    /* End-to-end quant encode on Xeon Platinum 8573C, 100k x 768:
     * AVX2 342,601 vectors/s, AVX-512 331,162. Keep AVX-512 available
     * through SEMQ_FORCE_BACKEND for other CPUs and differential tests. */
    if (op == SEMQ_QUANT && best == SEMQ_BACKEND_AVX512
        && resolve_available(SEMQ_BACKEND_AVX2) == SEMQ_BACKEND_AVX2) {
        return SEMQ_BACKEND_AVX2;
    }
#else
    (void)op;
#endif
    return best;
}

const semq_backend_t* semq_dispatch_get(semq_backend_kind_t kind) {
#if defined(SEMQ_ARCH_ARM64)
    if (kind == SEMQ_BACKEND_NEON) return &SEMQ_NEON_BACKEND;
    if (kind == SEMQ_BACKEND_SVE) {
        /* Defensive: if the host doesn't actually have SVE, refuse to
         * route there (would SIGILL on the first scalable instruction).
         * The forced override path lands here on non-SVE ARM hosts. */
        arm_features_t f;
        detect_arm_features(&f);
        if (f.sve) return &SEMQ_SVE_BACKEND;
        return &SEMQ_SCALAR_BACKEND;
    }
#endif
#if defined(SEMQ_ARCH_X86_64)
    if (kind == SEMQ_BACKEND_AVX2)   return &SEMQ_AVX2_BACKEND;
    if (kind == SEMQ_BACKEND_AVX512) {
        /* Defensive fall-through: AVX-512 instructions on a host that
         * lacks F+BW+VL would SIGILL. */
        x86_features_t f;
        detect_x86_features(&f);
        if (f.avx512f && f.avx512bw && f.avx512vl) return &SEMQ_AVX512_BACKEND;
        return &SEMQ_SCALAR_BACKEND;
    }
#endif
    /* Scalar handles every other kind, including wrong-arch resolutions. */
    (void)kind;
    return &SEMQ_SCALAR_BACKEND;
}

const semq_phase_backend_t* semq_dispatch_get_phase(semq_backend_kind_t kind) {
#if defined(SEMQ_ARCH_ARM64)
    if (kind == SEMQ_BACKEND_NEON) return &SEMQ_PHASE_NEON_BACKEND;
    /* SVE phase backend is not yet implemented — fall through to scalar. */
#endif
    /* x86 phase backends (AVX2, AVX-512) land in subsequent sessions.
     * Every other kind, including wrong-arch resolutions, returns scalar. */
    (void)kind;
    return &SEMQ_PHASE_SCALAR_BACKEND;
}

const semq_quant_backend_t* semq_dispatch_get_quant(semq_backend_kind_t kind) {
#if defined(SEMQ_ARCH_ARM64)
    /* Every SVE host also has NEON. Use the NEON quant kernel until a
     * distinct SVE implementation earns its place. */
    if (kind == SEMQ_BACKEND_NEON || kind == SEMQ_BACKEND_SVE) return &SEMQ_QUANT_NEON_BACKEND;
#endif
#if defined(SEMQ_ARCH_X86_64)
    if (kind == SEMQ_BACKEND_AVX2 || kind == SEMQ_BACKEND_AVX512) {
        x86_features_t f;
        detect_x86_features(&f);
        if (kind == SEMQ_BACKEND_AVX2 && f.avx2 && f.fma) return &SEMQ_QUANT_AVX2_BACKEND;
        if (kind == SEMQ_BACKEND_AVX512 && f.avx512f && f.avx512bw && f.avx512vl) {
            return &SEMQ_QUANT_AVX512_BACKEND;
        }
    }
#endif
    /* Other kinds fall back to scalar. */
    (void)kind;
    return &SEMQ_QUANT_SCALAR_BACKEND;
}

const char* semq_backend_kind_name(semq_backend_kind_t kind) {
    switch (kind) {
        case SEMQ_BACKEND_SCALAR: return "scalar";
        case SEMQ_BACKEND_AVX2:   return "avx2";
        case SEMQ_BACKEND_AVX512: return "avx512";
        case SEMQ_BACKEND_NEON:   return "neon";
        case SEMQ_BACKEND_SVE:    return "sve";
        case SEMQ_BACKEND_NONE:   /* fall through */
        default:                  return "none";
    }
}
