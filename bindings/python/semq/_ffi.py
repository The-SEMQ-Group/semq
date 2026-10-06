# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""cffi declarations for the SEMQ core and the loader for the native library.

Nothing here decides bytes or verdicts. The declarations mirror
``include/semq.h``; the loader finds ``libsemq`` next to the package, under
``SEMQ_LIBRARY_PATH``, or in the build directories of a checkout.
"""

from __future__ import annotations

import importlib.resources
import os
import re
import sys
import sysconfig
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cffi import FFI

if TYPE_CHECKING:
    from .errors import Native

_CDEF = """
typedef int semq_status_t;

typedef struct {
    uint32_t status;
    uint32_t which;
    uint64_t row;
    uint64_t field;
    char     message[128];
} semq_error_t;

typedef struct {
    uint32_t op;
    uint32_t dim;
    uint32_t p1;
    uint32_t p2;
} semq_config_t;

typedef struct semq_codec    semq_codec_t;
typedef struct semq_encoding semq_encoding_t;
typedef struct semq_diff     semq_diff_t;

typedef struct {
    const uint8_t* key;
    uint32_t       key_len;
    const uint8_t* value;
    uint32_t       value_len;
} semq_pair_t;

typedef struct {
    uint32_t        kind;
    uint64_t        n;
    const uint64_t* u64;
    const uint64_t* utf8_offsets;
    const uint8_t*  utf8_bytes;
} semq_ids_t;

typedef struct {
    const uint8_t* ptr;
    uint64_t       len;
} semq_part_t;

typedef struct {
    const uint8_t* key;
    uint32_t       key_len;
    int            has_before;
    const uint8_t* before;
    uint32_t       before_len;
    int            has_after;
    const uint8_t* after;
    uint32_t       after_len;
} semq_manifest_change_t;

typedef struct semq_floor semq_floor_t;

semq_status_t semq_config_orbit(uint32_t dim, uint32_t scale, semq_config_t* out, semq_error_t* err);
semq_status_t semq_config_phase(uint32_t dim, uint32_t sectors, semq_config_t* out, semq_error_t* err);
semq_status_t semq_config_quant(uint32_t dim, uint32_t bins, semq_config_t* out, semq_error_t* err);
semq_status_t semq_config_validate(const semq_config_t* cfg, semq_error_t* err);
void          semq_config_to_bytes(const semq_config_t* cfg, uint8_t* out);
semq_status_t semq_config_from_bytes(const uint8_t* in, semq_config_t* out, semq_error_t* err);
uint32_t      semq_config_bytes_per_vector(const semq_config_t* cfg);
uint32_t      semq_config_units_per_row(const semq_config_t* cfg);
float         semq_config_max_magnitude(const semq_config_t* cfg);
int           semq_config_equal(const semq_config_t* a, const semq_config_t* b);

semq_status_t semq_codec_create(const semq_config_t* cfg, semq_codec_t** out, semq_error_t* err);
void          semq_codec_free(semq_codec_t* codec);
const semq_config_t* semq_codec_config(const semq_codec_t* codec);
const char*   semq_codec_backend(const semq_codec_t* codec);
semq_status_t semq_codec_encode(const semq_codec_t* codec, const semq_ids_t* ids, const float* vectors,
                                const semq_pair_t* manifest, uint32_t n_pairs, semq_encoding_t** out,
                                semq_error_t* err);
semq_status_t semq_codec_decode(const semq_codec_t* codec, const semq_encoding_t* enc, float* out,
                                semq_error_t* err);
semq_status_t semq_codec_unpack(const semq_codec_t* codec, const semq_encoding_t* enc, uint8_t* out,
                                semq_error_t* err);

semq_status_t semq_encoding_create(const semq_config_t* cfg, const semq_ids_t* ids, const uint8_t* rows,
                                   const semq_pair_t* manifest, uint32_t n_pairs, semq_encoding_t** out,
                                   semq_error_t* err);
void          semq_encoding_free(semq_encoding_t* enc);
const semq_config_t* semq_encoding_config(const semq_encoding_t* enc);
uint32_t      semq_encoding_id_kind(const semq_encoding_t* enc);
uint64_t      semq_encoding_len(const semq_encoding_t* enc);
const uint8_t* semq_encoding_rows(const semq_encoding_t* enc, uint64_t* len);
const uint64_t* semq_encoding_ids_u64(const semq_encoding_t* enc);
const uint64_t* semq_encoding_ids_utf8_offsets(const semq_encoding_t* enc);
const uint8_t* semq_encoding_ids_utf8_bytes(const semq_encoding_t* enc, uint64_t* len);
uint32_t      semq_encoding_manifest_len(const semq_encoding_t* enc);
semq_status_t semq_encoding_manifest_pair(const semq_encoding_t* enc, uint32_t i, semq_pair_t* out,
                                          semq_error_t* err);
void          semq_encoding_content_digest(const semq_encoding_t* enc, uint8_t* out);
void          semq_encoding_state_id(const semq_encoding_t* enc, uint8_t* out);
semq_status_t semq_encoding_find_u64(const semq_encoding_t* enc, uint64_t id, uint64_t* index,
                                     semq_error_t* err);
semq_status_t semq_encoding_find_utf8(const semq_encoding_t* enc, const uint8_t* id, uint64_t len,
                                      uint64_t* index, semq_error_t* err);
uint64_t      semq_encoding_file_size(const semq_encoding_t* enc);
uint32_t      semq_encoding_save_parts(const semq_encoding_t* enc, semq_part_t* parts);
semq_status_t semq_encoding_save(const semq_encoding_t* enc, uint8_t* out, uint64_t cap, semq_error_t* err);
semq_status_t semq_encoding_load(const uint8_t* buf, uint64_t len, semq_encoding_t** out, semq_error_t* err);
semq_status_t semq_encoding_concat(const semq_encoding_t* const* parts, uint32_t k, semq_encoding_t** out,
                                   semq_error_t* err);
semq_status_t semq_encoding_diff(const semq_encoding_t* reference, const semq_encoding_t* candidate,
                                 semq_diff_t** out, semq_error_t* err);

void          semq_diff_free(semq_diff_t* diff);
const semq_config_t* semq_diff_config(const semq_diff_t* diff);
uint32_t      semq_diff_id_kind(const semq_diff_t* diff);
void          semq_diff_reference_id(const semq_diff_t* diff, uint8_t* out);
void          semq_diff_candidate_id(const semq_diff_t* diff, uint8_t* out);
uint64_t      semq_diff_count(const semq_diff_t* diff, uint32_t list);
uint64_t      semq_diff_n_unchanged(const semq_diff_t* diff);
semq_status_t semq_diff_id(const semq_diff_t* diff, uint32_t list, uint64_t i, uint64_t* u64,
                           const uint8_t** bytes, uint64_t* len, semq_error_t* err);
semq_status_t semq_diff_hamming(const semq_diff_t* diff, uint64_t i, uint64_t* out, semq_error_t* err);
uint32_t      semq_diff_manifest_changes(const semq_diff_t* diff);
semq_status_t semq_diff_manifest_change(const semq_diff_t* diff, uint32_t i, semq_manifest_change_t* out,
                                        semq_error_t* err);
semq_status_t semq_diff_units_u64(const semq_diff_t* diff, uint64_t id, uint32_t* units, uint8_t* ref_symbols,
                                  uint8_t* cand_symbols, uint64_t cap, uint64_t* count, semq_error_t* err);
semq_status_t semq_diff_units_utf8(const semq_diff_t* diff, const uint8_t* id, uint64_t len, uint32_t* units,
                                   uint8_t* ref_symbols, uint8_t* cand_symbols, uint64_t cap, uint64_t* count,
                                   semq_error_t* err);

semq_status_t semq_floor_create(const semq_config_t* config, uint32_t id_kind, const uint8_t* reference_id,
                                uint64_t nulls, uint64_t changed_rows, uint64_t total_rows, uint64_t hamming,
                                semq_floor_t** out, semq_error_t* err);
void          semq_floor_free(semq_floor_t* floor);
semq_status_t semq_floor_measure(const semq_diff_t* const* nulls, uint32_t k, semq_floor_t** out,
                                 semq_error_t* err);
const semq_config_t* semq_floor_config(const semq_floor_t* floor);
uint32_t      semq_floor_id_kind(const semq_floor_t* floor);
void          semq_floor_reference_id(const semq_floor_t* floor, uint8_t* out);
uint64_t      semq_floor_nulls(const semq_floor_t* floor);
uint64_t      semq_floor_changed_rows(const semq_floor_t* floor);
uint64_t      semq_floor_total_rows(const semq_floor_t* floor);
uint64_t      semq_floor_hamming(const semq_floor_t* floor);
semq_status_t semq_diff_within(const semq_diff_t* diff, const semq_floor_t* floor, int* out, semq_error_t* err);
semq_status_t semq_floor_create_with_max(const semq_config_t* config, uint32_t id_kind, const uint8_t* reference_id,
                                   uint64_t nulls, uint64_t changed_rows, uint64_t total_rows, uint64_t hamming,
                                   uint64_t max_hamming, semq_floor_t** out, semq_error_t* err);
uint64_t      semq_floor_max_hamming(const semq_floor_t* floor);
uint64_t      semq_floor_json_size(const semq_floor_t* floor);
semq_status_t semq_floor_save(const semq_floor_t* floor, uint8_t* out, uint64_t cap, semq_error_t* err);
semq_status_t semq_floor_load(const uint8_t* buf, uint64_t len, semq_floor_t** out, semq_error_t* err);
typedef struct semq_gate_options semq_gate_options_t;
typedef struct semq_verdict      semq_verdict_t;
semq_status_t semq_gate_options_create(semq_gate_options_t** out, semq_error_t* err);
void          semq_gate_options_free(semq_gate_options_t* options);
void          semq_gate_options_set_per_row(semq_gate_options_t* options, int enabled);
semq_status_t semq_diff_evaluate(const semq_diff_t* diff, const semq_floor_t* floor,
                                 const semq_gate_options_t* options, semq_verdict_t** out, semq_error_t* err);
void          semq_verdict_free(semq_verdict_t* verdict);
int           semq_verdict_passed(const semq_verdict_t* verdict);
uint32_t      semq_verdict_reasons(const semq_verdict_t* verdict);
uint64_t      semq_verdict_row_count(const semq_verdict_t* verdict);
uint64_t      semq_verdict_row(const semq_verdict_t* verdict, uint64_t i);

const char*   semq_core_version(void);
const char*   semq_build_id(void);
const char*   semq_backend_name(uint32_t op);
const char*   semq_status_name(uint32_t status);
void          semq_sha256(const uint8_t* data, uint64_t len, uint8_t* out);
"""

ffi = FFI()
ffi.cdef(_CDEF)

# Status codes, mirrored from semq.h.
OK = 0
ERR_INVALID_INPUT = 1
ERR_INCOMPATIBLE = 2
ERR_FORMAT = 3
ERR_INTEGRITY = 4
ERR_UNSUPPORTED = 5
ERR_NOMEM = 6
ERR_INTERNAL = 7

NONE = 2**64 - 1

ID_U64 = 0
ID_UTF8 = 1

LIST_ADDED = 0
LIST_REMOVED = 1
LIST_CHANGED = 2


def _platform_lib_name() -> str:
    if sys.platform == "darwin":
        return "libsemq.dylib"
    if sys.platform.startswith("win"):
        return "semq.dll"
    return "libsemq.so"


def _candidate_paths() -> Iterable[Path]:
    # Every built-in candidate is an absolute path. A bare file name would
    # let the dynamic loader search further, which on Windows and macOS can
    # include the current directory, so a libsemq planted there would run.
    lib = _platform_lib_name()
    env = os.environ.get("SEMQ_LIBRARY_PATH")
    if env:
        yield Path(env)
    sp = sysconfig.get_path("platlib")
    if sp:
        yield Path(sp) / "semq" / lib
    try:
        yield Path(str(importlib.resources.files("semq"))) / lib
    except Exception:
        pass
    here = Path(__file__).resolve().parent
    yield here / lib
    yield here.parent / "build" / lib
    yield here.parent.parent.parent / "build" / lib


_LIBSEMQ_PATH: Path | None = None


def _load() -> Any:
    global _LIBSEMQ_PATH
    last_error: Exception | None = None
    for candidate in _candidate_paths():
        try:
            lib = ffi.dlopen(str(candidate))
        except OSError as err:
            last_error = err
            continue
        # Resolving a library is not evidence that it has this ABI. Admit it
        # before any caller can create a handle or pass a POD to native code.
        try:
            version = ffi.string(lib.semq_core_version()).decode("ascii")
            if version.split(".", 1)[0] != "1":
                raise ValueError(f"unsupported ABI major: {version}")
            for name in re.findall(r"\b(semq_\w+)\s*\(", _CDEF):
                getattr(lib, name)
        except (AttributeError, OSError, ValueError, UnicodeError) as err:
            raise native_error(f"incompatible SEMQ library at {candidate}: {err}", operation="load") from err
        try:
            _LIBSEMQ_PATH = candidate.resolve()
        except OSError:
            _LIBSEMQ_PATH = candidate
        return lib
    raise native_error(
        "could not load the SEMQ native library; set SEMQ_LIBRARY_PATH or install a built "
        f"libsemq next to the package (last error: {last_error})",
        operation="load",
    )


_LIB: Any = None
_LOCK = threading.Lock()


def lib() -> Any:
    """The loaded cffi handle, loaded once per process."""
    global _LIB
    if _LIB is not None:
        return _LIB
    with _LOCK:
        if _LIB is None:
            _LIB = _load()
        return _LIB


def library_path() -> Path | None:
    return _LIBSEMQ_PATH


def loaded() -> Any:
    """The handle when the library is loaded, else ``None``; never loads."""
    return _LIB


def new_error() -> Any:
    return ffi.new("semq_error_t*")


def check(status: int, err: Any, operation: str) -> None:
    """Raise the exception that corresponds to a non-OK status."""
    if status == OK:
        return
    from . import errors

    message = ffi.string(err.message).decode("utf-8", "replace")
    row = None if err.row == NONE else int(err.row)
    field = None if err.field == NONE else int(err.field)
    if status == ERR_INVALID_INPUT:
        raise errors.InvalidInput(message, row=row, field=field)
    if status == ERR_INCOMPATIBLE:
        raise errors.Incompatible(message, field=field)
    if status == ERR_FORMAT:
        raise errors.FormatError(message, row=row, section=field)
    if status == ERR_INTEGRITY:
        which = "content" if err.which == 1 else "state" if err.which == 2 else None
        raise errors.IntegrityError(message, which=which)
    if status == ERR_UNSUPPORTED:
        raise errors.Unsupported(message, operation=operation)
    if status == ERR_NOMEM:
        raise MemoryError(message)
    raise native_error(message, operation=operation, status=status, row=row, field=field)


def string(ptr: Any) -> str:
    raw: bytes = ffi.string(ptr)
    return raw.decode("utf-8", "replace")


def native_error(message: str, *, operation: str | None = None, status: int | None = None,
                 row: int | None = None, field: int | None = None) -> Native:
    """Collect diagnostics at the translation boundary; never trigger a load."""
    from .build import build_info_safe
    from .errors import Native

    info = build_info_safe()
    return Native(message, operation=operation, status=status, row=row, field=field,
                  sdk_version=info.sdk_version, core_version=info.core_version, build_id=info.build_id)
