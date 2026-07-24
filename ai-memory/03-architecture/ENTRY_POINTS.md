# QLVB entry points

Updated: 2026-07-24

## CLI route

- **CODE_FACT**: `python -m tools.qlvb_downloader.runner` enters `runner.main`.
- **CODE_FACT**: `--cdp-three-category-smoke` constructs `QLVBDownloader` and invokes `run_cdp_three_category_smoke`.
- **CODE_FACT**: `--cdp-output-dir` is optional; when omitted, the workflow creates a timestamped child of the configured data root.
- **CODE_FACT**: ordinary flags include `--config`, `--directions`, `--headless`, `--max-items`, `--print-config`, `--dry-run`, and `--login-only`; these belong to the general downloader path, not the CDP smoke contract.

## CDP call flow

1. **CODE_FACT**: `runner.main` loads configuration and delegates through `QLVBDownloader.run_cdp_three_category_smoke`.
2. **CODE_FACT**: `cdp_workflow.run_cdp_three_category_smoke` validates labels, creates the target directory, then attaches with `connect_over_cdp`.
3. **CODE_FACT**: it finds an existing QLVB page, processes the fixed three-category order, performs bounded post-click polling, discovers one eligible attachment, and validates its downloaded body.
4. **CODE_FACT**: the runner exits `0` only when summary key `LIVE_ACCEPTANCE` is `PASS`; otherwise it exits `1`.

## Output and failure behavior

- **CODE_FACT**: category output directories use stable slugs under the requested or default root.
- **CODE_FACT**: summary output includes connection, validation, HTTP, integrity, session-expiration, and exact-error fields.
- **CODE_FACT**: exceptions are converted to a redacted bounded error string in `BLOCKED_WITH_EXACT_ERROR`; the summary remains `LIVE_ACCEPTANCE: FAIL`.
- **TEST_VERIFIED**: `test_runner_exposes_explicit_source_level_smoke_flag` verifies the explicit flag and delegation source.
