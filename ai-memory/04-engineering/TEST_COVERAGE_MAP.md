# Focused test coverage map

Updated: 2026-07-24

Each row is **TEST_VERIFIED** at the named test/pattern level. It documents focused evidence, not line or branch coverage.

| Feature | Test file | Test name/pattern | Evidence |
| --- | --- | --- | --- |
| Unicode-safe exact labels | `tests/test_cdp_workflow.py` | `test_unicode_escape_labels_decode_and_mojibake_is_rejected` | Labels normalize and mojibake is rejected. |
| External CDP ownership | `tests/test_cdp_workflow.py` | `test_cdp_path_uses_connect_over_cdp_and_no_legacy_browser_creation`; `test_browser_context_page_close_calls_are_not_present` | Attach-only path and no close calls. |
| Menu/table stabilization | `tests/test_cdp_workflow.py` | `test_menu_flow_has_utf8_safe_expansion_guard_and_delayed_rescan`; `test_table_validator_uses_structural_div_data_list_scoring`; `test_post_click_stabilization_precedes_document_discovery` | Scoped navigation and structural validation precede discovery. |
| Legacy callback | `tests/test_cdp_workflow.py` | `test_neoremoting_legacy_call_contract_is_preserved` | Preserves `getRSet.call` form. |
| Direct download/integrity | `tests/test_cdp_workflow.py` | `test_authenticated_direct_download_and_integrity_contracts_are_integrated`; `test_integrity_validation_accepts_pdf_and_zip` | Authenticated request and PDF/ZIP checks. |
| CLI smoke entry | `tests/test_cdp_workflow.py` | `test_runner_exposes_explicit_source_level_smoke_flag` | Explicit CLI flag/delegation. |
| Identifier safety | `tests/test_neoremoting_download.py` | `test_document_id_*` pattern | Canonical/allowlisted row-scoped sources accepted; malformed values rejected. |
| Parser safety | `tests/test_neoremoting_download.py` | `test_parser_*` pattern | JSON-like bounded parsing and hostile payload rejection. |
| Download URL contract | `tests/test_neoremoting_download.py` | `test_legacy_download_url_*`; `test_download_url_rejects_*` | Endpoint/query allowlist and origin restrictions. |
| Runtime frame/callback | `tests/test_neoremoting_download.py` | `test_adapter_*`; `test_callback_*`; `test_about_blank_*` | Child-frame selection and callback classification. |
| Default category behavior | `tests/test_neoremoting_download.py` | `test_controlled_workflow_*`; `test_category_order_skips_pending_*` | Bounded three-category behavior excluding pending by default. |
| Redacted diagnostics | `tests/test_neoremoting_download.py` | `test_direct_transport_diagnostics_exclude_query_material`; `test_direct_category_navigation_does_not_log_session_query` | Query material is not logged. |

The recorded `146 passed` is **HISTORICAL** focused-suite evidence from the verified application work; it does not establish complete repository coverage.
