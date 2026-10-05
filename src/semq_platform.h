/*
 * Copyright (c) 2026 The SEMQ Group Inc.
 * Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
 */
/* Internal build preconditions: every supported target must preserve them. */
#ifndef SEMQ_PLATFORM_H
#define SEMQ_PLATFORM_H

#include <float.h>
#include <limits.h>
#include <stdint.h>
#include <stddef.h>
#include "semq.h"

#if defined(__FAST_MATH__) || (defined(__FINITE_MATH_ONLY__) && __FINITE_MATH_ONLY__ != 0) || defined(_M_FP_FAST)
#error "SEMQ requires strict floating-point semantics (no fast-math)"
#endif
#if defined(__BYTE_ORDER__) && __BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__
#error "SEMQ requires a little-endian target"
#elif !defined(__BYTE_ORDER__) && !defined(_WIN32)
#error "SEMQ cannot establish target byte order"
#endif
#if defined(__STDC_NO_ATOMICS__) && !defined(_MSC_VER)
#error "SEMQ requires C11 atomics or MSVC interlocked operations"
#endif

_Static_assert(CHAR_BIT == 8, "SEMQ requires 8-bit bytes");
_Static_assert(sizeof(float) == 4 && FLT_RADIX == 2 && FLT_MANT_DIG == 24 &&
               FLT_MIN_EXP == -125 && FLT_MAX_EXP == 128, "SEMQ requires binary32");
_Static_assert(sizeof(double) == 8 && DBL_MANT_DIG == 53 &&
               DBL_MIN_EXP == -1021 && DBL_MAX_EXP == 1024, "SEMQ requires binary64");
_Static_assert(FLT_EVAL_METHOD == 0, "SEMQ requires evaluation at the declared precision");
_Static_assert(sizeof(int) == 4, "SEMQ bindings require 32-bit C int");
_Static_assert(sizeof(semq_status_t) == 4, "SEMQ ABI requires 32-bit enums");
_Static_assert(sizeof(size_t) == 4 || sizeof(size_t) == 8, "SEMQ requires 32/64-bit size_t");

#endif
