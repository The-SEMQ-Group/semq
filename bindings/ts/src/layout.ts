// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

// Generated from the wasm32 C compiler by tools/check_abi.py --write-layout.
export const ABI = {
  "error": {
    "size": 152,
    "align": 8,
    "status": 0,
    "which": 4,
    "row": 8,
    "field": 16,
    "message": 24
  },
  "config": {
    "size": 16,
    "align": 4,
    "op": 0,
    "dim": 4,
    "p1": 8,
    "p2": 12
  },
  "pair": {
    "size": 16,
    "align": 4,
    "key": 0,
    "key_len": 4,
    "value": 8,
    "value_len": 12
  },
  "ids": {
    "size": 32,
    "align": 8,
    "kind": 0,
    "n": 8,
    "u64": 16,
    "utf8_offsets": 20,
    "utf8_bytes": 24
  },
  "part": {
    "size": 16,
    "align": 8,
    "ptr": 0,
    "len": 8
  },
  "manifest_change": {
    "size": 32,
    "align": 4,
    "key": 0,
    "key_len": 4,
    "has_before": 8,
    "before": 12,
    "before_len": 16,
    "has_after": 20,
    "after": 24,
    "after_len": 28
  },
  "constants": {
    "SEMQ_ORBIT": 0,
    "SEMQ_PHASE": 1,
    "SEMQ_QUANT": 2,
    "SEMQ_ID_U64": 0,
    "SEMQ_ID_UTF8": 1,
    "SEMQ_OK": 0,
    "SEMQ_ERR_INVALID_INPUT": 1,
    "SEMQ_ERR_INCOMPATIBLE": 2,
    "SEMQ_ERR_FORMAT": 3,
    "SEMQ_ERR_INTEGRITY": 4,
    "SEMQ_ERR_UNSUPPORTED": 5,
    "SEMQ_ERR_NOMEM": 6,
    "SEMQ_ERR_INTERNAL": 7,
    "SEMQ_WHICH_NONE": 0,
    "SEMQ_WHICH_CONTENT": 1,
    "SEMQ_WHICH_STATE": 2,
    "SEMQ_SECTION_FRAMING": 0,
    "SEMQ_SECTION_CONFIG": 1,
    "SEMQ_SECTION_SIZES": 2,
    "SEMQ_SECTION_IDS": 3,
    "SEMQ_SECTION_MANIFEST": 4,
    "SEMQ_SECTION_FOOTER": 5,
    "SEMQ_SECTION_ROWS": 6,
    "SEMQ_FIELD_OPERATOR": 0,
    "SEMQ_FIELD_DIM": 1,
    "SEMQ_FIELD_P1": 2,
    "SEMQ_FIELD_P2": 3,
    "SEMQ_LIST_ADDED": 0,
    "SEMQ_LIST_REMOVED": 1,
    "SEMQ_LIST_CHANGED": 2,
    "SEMQ_REASON_NO_COMMON_ROWS": 1,
    "SEMQ_REASON_REMOVED_ROWS": 2,
    "SEMQ_REASON_CHANGED_RATIO": 4,
    "SEMQ_REASON_HAMMING": 8,
    "SEMQ_REASON_ENCODER": 16,
    "SEMQ_REASON_ROW_ABOVE_MAX": 32,
    "SEMQ_FILE_VERSION": 2,
    "SEMQ_RULE_REVISION": 0,
    "SEMQ_CONFIG_BYTES": 13,
    "SEMQ_DIGEST_BYTES": 32,
    "SEMQ_MAX_DIM": 65536,
    "SEMQ_ID_MAX_BYTES": 4096,
    "SEMQ_MANIFEST_MAX_PAIRS": 4096,
    "SEMQ_MANIFEST_KEY_MAX": 256,
    "SEMQ_MANIFEST_VALUE_MAX": 65536,
    "SEMQ_MANIFEST_SECTION_MAX": 16777216
  }
} as const;
