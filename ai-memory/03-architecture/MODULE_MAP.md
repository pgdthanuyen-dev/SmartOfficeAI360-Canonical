# QLVB module map

Updated: 2026-07-24

Evidence labels: **CODE_FACT** is read directly from source; **TEST_VERIFIED** names a matching focused test. This map is not a coverage claim.

| Module | Responsibility and primary API | Direct dependencies | CDP smoke boundary | Test evidence |
| --- | --- | --- | --- | --- |
| `cdp_workflow.py` | **CODE_FACT**: external CDP three-category workflow. Main APIs: `run_cdp_three_category_smoke`, `find_qlvb_page`, `ensure_category`, `poll_category_target_state`, `discover_attachment`, `download_one`. | Playwright sync API, `QLVBConfig`, NeoRemoting helpers, `Path`. | **CODE_FACT**: owns CDP attachment only; it does not call legacy browser launch, browser/context/page close, OCR, AI, or Planner. | `test_cdp_workflow.py` covers attach, menu, table, polling, callback, download, integrity, and CLI exposure. |
| `config.py` | **CODE_FACT**: configuration dataclasses and JSON/config discovery. Main APIs: `BrowserConfig`, `DownloadConfig`, `QLVBConfig`, `find_config_file`, `load_config`, `save_config`. | JSON, environment, project path utilities. | **CODE_FACT**: supplies `QLVBConfig`; it does not connect to CDP. | `test_neoremoting_download.py::test_config_maps_incoming_registry_without_reusing_legacy_pending_url`. |
| `downloader.py` | **CODE_FACT**: legacy downloader façade. `QLVBDownloader.run_cdp_three_category_smoke` delegates to the CDP workflow. | Config, models, NeoRemoting adapter, storage/reporting, legacy Playwright flow. | **CODE_FACT**: CDP entry calls only the CDP workflow; legacy methods are not invoked by that delegation. | `test_cdp_workflow.py::test_runner_exposes_explicit_source_level_smoke_flag`. |
| `models.py` | **CODE_FACT**: data records/status constants and redaction helpers. Main APIs: `AttachmentInfo`, `DocumentRecord`, `mask_url_query`, `safe_slug`. | Standard library only. | **CODE_FACT**: provides models/utilities; no browser, CDP, NeoRemoting, or download calls. | NeoRemoting/download focused tests exercise attachment fields and query masking indirectly. |
| `neoremoting.py` | **CODE_FACT**: row-scoped identifier extraction, safe response normalization, legacy URL construction, callback adapter. Main APIs: `extract_document_id`, `parse_attachment_response`, `build_legacy_download_url`, `NeoRemotingAttachmentDiscoveryAdapter`. | `ast.literal_eval`, JSON, URL parsing, `AttachmentInfo`. | **CODE_FACT**: does not launch or close a browser; it evaluates only against an already supplied page/frame. | `test_neoremoting_download.py` tests identifier, parser, URL, runtime-scope, callback, and failure cases. |
| `runner.py` | **CODE_FACT**: CLI entry module. Main API: `main`; parses flags then invokes `QLVBDownloader`. | argparse, config, downloader, `mask_url_query`. | **CODE_FACT**: CDP smoke is opt-in through one explicit flag. | `test_cdp_workflow.py::test_runner_exposes_explicit_source_level_smoke_flag`. |

## Non-calls in the CDP smoke

- **CODE_FACT**: no `chromium.launch`, persistent-context launch, or browser/context/page close call is present in `cdp_workflow.py`.
- **TEST_VERIFIED**: `test_cdp_path_uses_connect_over_cdp_and_no_legacy_browser_creation` and `test_browser_context_page_close_calls_are_not_present` assert these boundaries.
