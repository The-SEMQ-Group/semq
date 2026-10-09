/*
 * Copyright (c) 2026 The SEMQ Group Inc.
 * Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
 */

/* Generated from semq.h by tools/check_abi.py; do not edit. */
#include "semq.h"
#include <stdio.h>
int main(void) {
    printf("pointer.size=%llu\n", (unsigned long long)(sizeof(void*)));
    printf("semq_error_t.size=%llu\n", (unsigned long long)(sizeof(semq_error_t)));
    printf("semq_error_t.align=%llu\n", (unsigned long long)(_Alignof(semq_error_t)));
    printf("semq_error_t.status=%llu\n", (unsigned long long)(offsetof(semq_error_t, status)));
    printf("semq_error_t.which=%llu\n", (unsigned long long)(offsetof(semq_error_t, which)));
    printf("semq_error_t.row=%llu\n", (unsigned long long)(offsetof(semq_error_t, row)));
    printf("semq_error_t.field=%llu\n", (unsigned long long)(offsetof(semq_error_t, field)));
    printf("semq_error_t.message=%llu\n", (unsigned long long)(offsetof(semq_error_t, message)));
    printf("semq_config_t.size=%llu\n", (unsigned long long)(sizeof(semq_config_t)));
    printf("semq_config_t.align=%llu\n", (unsigned long long)(_Alignof(semq_config_t)));
    printf("semq_config_t.op=%llu\n", (unsigned long long)(offsetof(semq_config_t, op)));
    printf("semq_config_t.dim=%llu\n", (unsigned long long)(offsetof(semq_config_t, dim)));
    printf("semq_config_t.p1=%llu\n", (unsigned long long)(offsetof(semq_config_t, p1)));
    printf("semq_config_t.p2=%llu\n", (unsigned long long)(offsetof(semq_config_t, p2)));
    printf("semq_pair_t.size=%llu\n", (unsigned long long)(sizeof(semq_pair_t)));
    printf("semq_pair_t.align=%llu\n", (unsigned long long)(_Alignof(semq_pair_t)));
    printf("semq_pair_t.key=%llu\n", (unsigned long long)(offsetof(semq_pair_t, key)));
    printf("semq_pair_t.key_len=%llu\n", (unsigned long long)(offsetof(semq_pair_t, key_len)));
    printf("semq_pair_t.value=%llu\n", (unsigned long long)(offsetof(semq_pair_t, value)));
    printf("semq_pair_t.value_len=%llu\n", (unsigned long long)(offsetof(semq_pair_t, value_len)));
    printf("semq_ids_t.size=%llu\n", (unsigned long long)(sizeof(semq_ids_t)));
    printf("semq_ids_t.align=%llu\n", (unsigned long long)(_Alignof(semq_ids_t)));
    printf("semq_ids_t.kind=%llu\n", (unsigned long long)(offsetof(semq_ids_t, kind)));
    printf("semq_ids_t.n=%llu\n", (unsigned long long)(offsetof(semq_ids_t, n)));
    printf("semq_ids_t.u64=%llu\n", (unsigned long long)(offsetof(semq_ids_t, u64)));
    printf("semq_ids_t.utf8_offsets=%llu\n", (unsigned long long)(offsetof(semq_ids_t, utf8_offsets)));
    printf("semq_ids_t.utf8_bytes=%llu\n", (unsigned long long)(offsetof(semq_ids_t, utf8_bytes)));
    printf("semq_part_t.size=%llu\n", (unsigned long long)(sizeof(semq_part_t)));
    printf("semq_part_t.align=%llu\n", (unsigned long long)(_Alignof(semq_part_t)));
    printf("semq_part_t.ptr=%llu\n", (unsigned long long)(offsetof(semq_part_t, ptr)));
    printf("semq_part_t.len=%llu\n", (unsigned long long)(offsetof(semq_part_t, len)));
    printf("semq_manifest_change_t.size=%llu\n", (unsigned long long)(sizeof(semq_manifest_change_t)));
    printf("semq_manifest_change_t.align=%llu\n", (unsigned long long)(_Alignof(semq_manifest_change_t)));
    printf("semq_manifest_change_t.key=%llu\n", (unsigned long long)(offsetof(semq_manifest_change_t, key)));
    printf("semq_manifest_change_t.key_len=%llu\n", (unsigned long long)(offsetof(semq_manifest_change_t, key_len)));
    printf("semq_manifest_change_t.has_before=%llu\n", (unsigned long long)(offsetof(semq_manifest_change_t, has_before)));
    printf("semq_manifest_change_t.before=%llu\n", (unsigned long long)(offsetof(semq_manifest_change_t, before)));
    printf("semq_manifest_change_t.before_len=%llu\n", (unsigned long long)(offsetof(semq_manifest_change_t, before_len)));
    printf("semq_manifest_change_t.has_after=%llu\n", (unsigned long long)(offsetof(semq_manifest_change_t, has_after)));
    printf("semq_manifest_change_t.after=%llu\n", (unsigned long long)(offsetof(semq_manifest_change_t, after)));
    printf("semq_manifest_change_t.after_len=%llu\n", (unsigned long long)(offsetof(semq_manifest_change_t, after_len)));
    printf("semq_status_t.size=%llu\n", (unsigned long long)(sizeof(semq_status_t)));
    printf("semq_status_t.align=%llu\n", (unsigned long long)(_Alignof(semq_status_t)));
    printf("SEMQ_ORBIT=%llu\n", (unsigned long long)(SEMQ_ORBIT));
    printf("SEMQ_PHASE=%llu\n", (unsigned long long)(SEMQ_PHASE));
    printf("SEMQ_QUANT=%llu\n", (unsigned long long)(SEMQ_QUANT));
    printf("SEMQ_ID_U64=%llu\n", (unsigned long long)(SEMQ_ID_U64));
    printf("SEMQ_ID_UTF8=%llu\n", (unsigned long long)(SEMQ_ID_UTF8));
    printf("SEMQ_OK=%llu\n", (unsigned long long)(SEMQ_OK));
    printf("SEMQ_ERR_INVALID_INPUT=%llu\n", (unsigned long long)(SEMQ_ERR_INVALID_INPUT));
    printf("SEMQ_ERR_INCOMPATIBLE=%llu\n", (unsigned long long)(SEMQ_ERR_INCOMPATIBLE));
    printf("SEMQ_ERR_FORMAT=%llu\n", (unsigned long long)(SEMQ_ERR_FORMAT));
    printf("SEMQ_ERR_INTEGRITY=%llu\n", (unsigned long long)(SEMQ_ERR_INTEGRITY));
    printf("SEMQ_ERR_UNSUPPORTED=%llu\n", (unsigned long long)(SEMQ_ERR_UNSUPPORTED));
    printf("SEMQ_ERR_NOMEM=%llu\n", (unsigned long long)(SEMQ_ERR_NOMEM));
    printf("SEMQ_ERR_INTERNAL=%llu\n", (unsigned long long)(SEMQ_ERR_INTERNAL));
    printf("SEMQ_WHICH_NONE=%llu\n", (unsigned long long)(SEMQ_WHICH_NONE));
    printf("SEMQ_WHICH_CONTENT=%llu\n", (unsigned long long)(SEMQ_WHICH_CONTENT));
    printf("SEMQ_WHICH_STATE=%llu\n", (unsigned long long)(SEMQ_WHICH_STATE));
    printf("SEMQ_SECTION_FRAMING=%llu\n", (unsigned long long)(SEMQ_SECTION_FRAMING));
    printf("SEMQ_SECTION_CONFIG=%llu\n", (unsigned long long)(SEMQ_SECTION_CONFIG));
    printf("SEMQ_SECTION_SIZES=%llu\n", (unsigned long long)(SEMQ_SECTION_SIZES));
    printf("SEMQ_SECTION_IDS=%llu\n", (unsigned long long)(SEMQ_SECTION_IDS));
    printf("SEMQ_SECTION_MANIFEST=%llu\n", (unsigned long long)(SEMQ_SECTION_MANIFEST));
    printf("SEMQ_SECTION_FOOTER=%llu\n", (unsigned long long)(SEMQ_SECTION_FOOTER));
    printf("SEMQ_SECTION_ROWS=%llu\n", (unsigned long long)(SEMQ_SECTION_ROWS));
    printf("SEMQ_FIELD_OPERATOR=%llu\n", (unsigned long long)(SEMQ_FIELD_OPERATOR));
    printf("SEMQ_FIELD_DIM=%llu\n", (unsigned long long)(SEMQ_FIELD_DIM));
    printf("SEMQ_FIELD_P1=%llu\n", (unsigned long long)(SEMQ_FIELD_P1));
    printf("SEMQ_FIELD_P2=%llu\n", (unsigned long long)(SEMQ_FIELD_P2));
    printf("SEMQ_LIST_ADDED=%llu\n", (unsigned long long)(SEMQ_LIST_ADDED));
    printf("SEMQ_LIST_REMOVED=%llu\n", (unsigned long long)(SEMQ_LIST_REMOVED));
    printf("SEMQ_LIST_CHANGED=%llu\n", (unsigned long long)(SEMQ_LIST_CHANGED));
    printf("SEMQ_CHECK_PER_ROW=%llu\n", (unsigned long long)(SEMQ_CHECK_PER_ROW));
    printf("SEMQ_REASON_NO_COMMON_ROWS=%llu\n", (unsigned long long)(SEMQ_REASON_NO_COMMON_ROWS));
    printf("SEMQ_REASON_REMOVED_ROWS=%llu\n", (unsigned long long)(SEMQ_REASON_REMOVED_ROWS));
    printf("SEMQ_REASON_CHANGED_RATIO=%llu\n", (unsigned long long)(SEMQ_REASON_CHANGED_RATIO));
    printf("SEMQ_REASON_HAMMING=%llu\n", (unsigned long long)(SEMQ_REASON_HAMMING));
    printf("SEMQ_REASON_ENCODER=%llu\n", (unsigned long long)(SEMQ_REASON_ENCODER));
    printf("SEMQ_REASON_ROW_ABOVE_MAX=%llu\n", (unsigned long long)(SEMQ_REASON_ROW_ABOVE_MAX));
    printf("SEMQ_FILE_VERSION=%llu\n", (unsigned long long)(SEMQ_FILE_VERSION));
    printf("SEMQ_RULE_REVISION=%llu\n", (unsigned long long)(SEMQ_RULE_REVISION));
    printf("SEMQ_CONFIG_BYTES=%llu\n", (unsigned long long)(SEMQ_CONFIG_BYTES));
    printf("SEMQ_DIGEST_BYTES=%llu\n", (unsigned long long)(SEMQ_DIGEST_BYTES));
    printf("SEMQ_MAX_DIM=%llu\n", (unsigned long long)(SEMQ_MAX_DIM));
    printf("SEMQ_ID_MAX_BYTES=%llu\n", (unsigned long long)(SEMQ_ID_MAX_BYTES));
    printf("SEMQ_MANIFEST_MAX_PAIRS=%llu\n", (unsigned long long)(SEMQ_MANIFEST_MAX_PAIRS));
    printf("SEMQ_MANIFEST_KEY_MAX=%llu\n", (unsigned long long)(SEMQ_MANIFEST_KEY_MAX));
    printf("SEMQ_MANIFEST_VALUE_MAX=%llu\n", (unsigned long long)(SEMQ_MANIFEST_VALUE_MAX));
    printf("SEMQ_MANIFEST_SECTION_MAX=%llu\n", (unsigned long long)(SEMQ_MANIFEST_SECTION_MAX));
    printf("SEMQ_NONE=%llu\n", (unsigned long long)(SEMQ_NONE));
    return 0;
}
