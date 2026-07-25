# Focused test coverage map

Updated: 2026-07-24

Each row is **TEST_VERIFIED** at the named test/pattern level. It documents focused evidence, not line or branch coverage.

| Feature | Test file | Test name/pattern | Evidence |
| --- | --- | --- | --- |
| Unicode-safe exact labels | `tests/test_cdp_workflow.py` | `test_unicode_escape_labels_decode_and_mojibake_is_rejected` | Labels normalize and mojibake is rejected. |
| External CDP ownership | `tests/test_cdp_workflow.py` | `test_cdp_path_uses_connect_over_cdp_and_no_legacy_browser_creation`; `test_browser_context_page_close_calls_are_not_present` | Attach-only path and no close calls. |
| Menu/table stabilization | `tests/test_cdp_workflow.py` | `test_menu_flow_has_utf8_safe_expansion_guard_and_delayed_rescan`; `test_table_validator_uses_structural_div_data_list_scoring`; `test_post_click_stabilization_precedes_document_discovery` | Scoped navigation and structural validation precede discovery. |
| Legacy callback | `tests/test_cdp_workflow.py` | `test_neoremoting_legacy_call_contract_is_preserved` | Preserves `getRSet.call` form. |
| Atomic valid persistence | `tests/test_cdp_workflow.py` | `test_atomic_download_persists_valid_pdf_and_removes_temp_file`; `test_atomic_download_persists_valid_zip_and_ole` | PDF, ZIP, OLE, atomic persistence, and no leftover temp file. |
| Rejected download bodies | `tests/test_cdp_workflow.py` | `test_invalid_response_is_not_persisted` | Login HTML, 401/403, non-200, unknown signature, and empty body leave no final file. |
| Integrity and rename cleanup | `tests/test_cdp_workflow.py` | `test_integrity_failure_size_mismatch_and_rename_failure_leave_no_final_or_temp`; `test_existing_final_file_is_not_overwritten` | Integrity/size failure, rename failure, temp cleanup, and collision-safe final path. |
| CLI smoke entry | `tests/test_cdp_workflow.py` | `test_runner_exposes_explicit_source_level_smoke_flag` | Explicit CLI flag/delegation. |
| Identifier safety | `tests/test_neoremoting_download.py` | `test_document_id_*` pattern | Canonical/allowlisted row-scoped sources accepted; malformed values rejected. |
| Parser safety | `tests/test_neoremoting_download.py` | `test_parser_*` pattern | JSON-like bounded parsing and hostile payload rejection. |
| Download URL contract | `tests/test_neoremoting_download.py` | `test_legacy_download_url_*`; `test_download_url_rejects_*` | Endpoint/query allowlist and origin restrictions. |
| Runtime frame/callback | `tests/test_neoremoting_download.py` | `test_adapter_*`; `test_callback_*`; `test_about_blank_*` | Child-frame selection and callback classification. |
| Default category behavior | `tests/test_neoremoting_download.py` | `test_controlled_workflow_*`; `test_category_order_skips_pending_*` | Bounded three-category behavior excluding pending by default. |
| Redacted diagnostics | `tests/test_neoremoting_download.py` | `test_direct_transport_diagnostics_exclude_query_material`; `test_direct_category_navigation_does_not_log_session_query` | Query material is not logged. |
| G03 format and page extraction | `tests/test_g03_extraction_ocr.py` | `test_pdf_direct_text_multi_page`; `test_docx_*`; `test_*image*`; `test_page_numbering_starts_at_one` | PDF/DOCX/image paths, normalization, and ordered pages use generated fixtures and fake OCR. |
| G03 cache and forced extraction | `tests/test_g03_extraction_ocr.py` | `test_cache_hit_does_not_extract_again`; `test_force_extraction_bypasses_cache`; `test_successful_force_atomically_replaces_old_cache` | Cache identity, hit behavior, forced replacement, and atomic result/page refresh. |
| G03 failure safety | `tests/test_g03_extraction_ocr.py` | `test_force_failure_*`; `test_transaction_rollback_when_page_insert_fails`; `test_failed_result_does_not_store_partial_pages` | Failed work records an attempt and does not persist a partial page cache. |
| G04 JSON and citation boundary | `tests/test_g04_ai_proposal_boundary.py` | `test_unknown_field_rejected_in_strict_mode`; `test_citation_*`; `test_excerpt_*` | Strict envelope validation and document/page/excerpt checks. |
| G04 dedupe and idempotency | `tests/test_g04_ai_proposal_boundary.py` | `test_exact_duplicate_*`; `test_idempotency_*`; `test_same_key_*` | Duplicate, replay, conflict, and simulated unique-constraint race outcomes. |
| G04 transaction and bounds | `tests/test_g04_ai_proposal_boundary.py` | `test_citation_insert_failure_rolls_back_action_item`; `test_batch_partial_success`; `test_*warning*` | Per-proposal rollback, intentional partial batches, and bounded warnings/errors. |

G03 focused extraction/OCR tests: **TEST_VERIFIED** `33 passed` on 2026-07-25. The suite uses a fake OCR adapter; it is not real-Tesseract or live acceptance evidence.

G04 focused proposal-boundary tests: **TEST_VERIFIED** `42 passed` on 2026-07-25. The suite uses a fake provider; it is not production-provider or live-AI evidence.

G05 component tests cover rule matching, personnel selection, and draft construction; **KNOWN_GAP**: no focused end-to-end test yet enforces the approved document-level cardinality contract.

Focused QLVB/CDP/NeoRemoting tests recorded after R49: **HISTORICAL** `156 passed`. This does not establish complete repository coverage.
