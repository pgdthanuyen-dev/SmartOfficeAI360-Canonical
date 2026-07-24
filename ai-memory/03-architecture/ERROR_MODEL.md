# QLVB error model

Updated: 2026-07-24

This is a source-derived error taxonomy. Labels are **CODE_FACT** unless a test is named.

| Boundary | Failure representation | Evidence |
| --- | --- | --- |
| CDP attach | `QLVB_CDP_CONNECTION_FAILED` | `run_cdp_three_category_smoke` wraps attach exceptions. |
| Existing page | `QLVB_CDP_SOURCE_PAGE_NOT_FOUND` | Source page selection returns no eligible page. |
| Menu navigation | `CATEGORY_MENU_CLICK_FAILED` | `ensure_category` fails when no actionable category result is clicked. |
| Post-click readiness | `CATEGORY_n_POST_CLICK_TARGET_STATE_TIMEOUT` | Bounded polling requires target state before discovery. |
| Table validation | No selected table/frame makes target state incomplete. | **TEST_VERIFIED**: structural table scoring is asserted by `test_table_validator_uses_structural_div_data_list_scoring`. |
| NeoRemoting availability/callback | `NeoRemotingDiscoveryError` codes include object unavailable, method/type unavailable, callback timeout, synchronous exception, invalid response, and no attachments. | **TEST_VERIFIED**: `test_adapter_classifies_expected_primary_failures`. |
| Attachment parsing | `NEOREMOTING_EMPTY_RESULT`, `NEOREMOTING_INVALID_RESPONSE`, or `NO_ATTACHMENTS`. | Parser bounds response size, list count, nesting, fields, and values. |
| HTTP authorization/session | `SESSION_EXPIRED` result code for 401/403. | **TEST_VERIFIED**: `test_invalid_response_is_not_persisted`. |
| HTTP non-200 | `HTTP_DOWNLOAD_FAILED` result code. | **CODE_FACT**: `download_one` rejects before temp creation. |
| Login or HTML | `LOGIN_HTML_DETECTED` result code. | **TEST_VERIFIED**: `test_invalid_response_is_not_persisted`. |
| Empty body | `EMPTY_RESPONSE_BODY` result code. | **TEST_VERIFIED**: `test_invalid_response_is_not_persisted`. |
| Unknown signature | `UNSUPPORTED_OR_UNKNOWN_FILE_SIGNATURE` result code. | **TEST_VERIFIED**: `test_invalid_response_is_not_persisted`. |
| Integrity/persistence | `INTEGRITY_CHECK_FAILED` or `ATOMIC_PERSISTENCE_FAILED`; the category wrapper reports a category-scoped failure. | **TEST_VERIFIED**: `test_integrity_failure_size_mismatch_and_rename_failure_leave_no_final_or_temp`. |
| PDF, ZIP, OLE policy | PDF EOF, ZIP archive, and OLE magic-header checks are distinct; unknown signatures fail. | **TEST_VERIFIED**: `test_integrity_validation_accepts_pdf_and_zip`; `test_atomic_download_persists_valid_zip_and_ole`. |

## Failure policy

- **CODE_FACT**: the CDP workflow catches exceptions, records a bounded error summary, and returns a failed acceptance result instead of emitting a false PASS.
- **CODE_FACT**: the CLI maps failed CDP acceptance to process exit code `1`.
- **CODE_FACT**: temporary files are cleaned in `finally`; a final file is returned only after atomic replacement succeeds.
