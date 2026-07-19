# SmartOfficeAI360 Canonical - G03 Review And Merge Report

Thoi gian lap bao cao: 2026-07-19T09:55:56.5610511+07:00
Repository: D:\Laptrinh\SmartOfficeAI360-Canonical
Review branch: feature/g03-extraction-ocr
G03 branch head: 5ed53731daac75477ce1f251a4d4f84d3adacc76
Main before review: 8f36dcd360b136c1cff181f902a29804d1d76485
Tag: canonical-g03-extraction-ocr-20260719 -> 5ed53731daac75477ce1f251a4d4f84d3adacc76
Conclusion: BLOCKED, not merged.

## 1. Precheck

Commands run:

`	ext
git status --short
git branch --show-current
git log --oneline --decorate -10
git tag --list
git remote -v
git rev-parse main
git rev-parse feature/g03-extraction-ocr
git rev-parse 'canonical-g03-extraction-ocr-20260719^{}'
`

Result:

- Canonical working tree: clean.
- Current branch during review: eature/g03-extraction-ocr.
- No remote configured.
- main exists and points to 8f36dcd360b136c1cff181f902a29804d1d76485.
- G03 branch exists and points to 5ed53731daac75477ce1f251a4d4f84d3adacc76.
- G03 tag points to 5ed53731daac75477ce1f251a4d4f84d3adacc76.
- External G03 report exists: D:\Laptrinh\SmartOfficeAI360_G03_EXTRACTION_OCR_REPORT.md.

## 2. Scope Review

Commands run:

`	ext
git diff --stat main..feature/g03-extraction-ocr
git diff --name-status main..feature/g03-extraction-ocr
git diff --name-only main..feature/g03-extraction-ocr
git log --oneline main..feature/g03-extraction-ocr
`

Diff scope:

`	ext
docs/architecture/G03_EXTRACTION_OCR.md        | 139 ++++++++
docs/architecture/G03_OCR_PORTING_DECISIONS.md |  64 ++++
tests/test_g03_extraction_ocr.py               | 467 +++++++++++++++++++++++++
tools/qlvb_downloader/extraction_models.py     | 207 +++++++++++
tools/qlvb_downloader/extraction_repository.py | 242 +++++++++++++
tools/qlvb_downloader/extraction_service.py    | 389 ++++++++++++++++++++
tools/qlvb_downloader/ocr_adapter.py           | 105 ++++++
7 files changed, 1613 insertions(+)
`

Scope verdict: PASS. Only expected G03 files are present. No Data/session/token/build/runtime SQLite/launcher/version file is in the diff.

## 3. Extraction Architecture Review

Verdict: PASS for model/service/OCR architecture, with persistence blocker noted separately.

Evidence:

- 	ools/qlvb_downloader/extraction_models.py:11 has EXTRACTION_SCHEMA_VERSION = "1.0.0".
- 	ools/qlvb_downloader/extraction_models.py:52 defines ExtractionResult.
- 	ools/qlvb_downloader/extraction_models.py:83 defines ExtractedPage.
- 	ools/qlvb_downloader/extraction_service.py:38 defines ExtractionService.
- 	ools/qlvb_downloader/extraction_repository.py:93 defines ExtractionRepository.
- 	ools/qlvb_downloader/ocr_adapter.py:17 defines OcrAdapter.
- 	ools/qlvb_downloader/ocr_adapter.py:31 defines OptionalTesseractOcrAdapter.
- 	ools/qlvb_downloader/extraction_service.py:62-70 requires attachment VALIDATED, file exists, and SHA-256 match.
- 	ools/qlvb_downloader/extraction_service.py:211-229 detects file type by magic bytes for HTML/PDF/PNG/JPEG/ZIP/DOCX/TXT.
- 	ools/qlvb_downloader/extraction_service.py:290-333 extracts PDF page text and uses OCR fallback only when text is below threshold or orce_ocr is requested.
- 	ools/qlvb_downloader/extraction_service.py:259-279 reads DOCX paragraphs and basic tables through python-docx.
- 	ools/qlvb_downloader/extraction_service.py:250-253 reads TXT UTF-8/UTF-8-SIG.
- 	ools/qlvb_downloader/extraction_service.py:338-353 handles PNG/JPEG through OCR adapter, returning no pages with structured warning when unavailable.
- 	ools/qlvb_downloader/extraction_models.py:106-119 normalizes text to NFC/LF and removes unsupported control chars without summarizing or spelling correction.
- 	ools/qlvb_downloader/extraction_models.py:103-104 stores per-page text hash.
- No G03 code references or modifies ActionItem.

## 4. OCR Adapter Review

Verdict: PASS.

Evidence:

- 	ools/qlvb_downloader/ocr_adapter.py:32 default language is clean ie+eng.
- 	ools/qlvb_downloader/ocr_adapter.py:40-56 imports OCR dependencies optionally; no install command exists.
- 	ools/qlvb_downloader/ocr_adapter.py:62-63 is_available() is boolean and does not execute OCR.
- 	ools/qlvb_downloader/ocr_adapter.py:65-73 returns deterministic version string or ocr-unavailable.
- 	ests/test_g03_extraction_ocr.py:25-47 defines and uses FakeOcrAdapter.
- 	ests/test_g03_extraction_ocr.py:356-370 covers cache hit without re-OCR.
- 	ests/test_g03_extraction_ocr.py:374-388 covers orce=True bypassing cache.

## 5. Control Character Scan

Command run with Python byte scan over all seven new G03 files.

Result: PASS.

- No NULL byte.
- No bell byte.
- No vertical tab byte.
- No replacement character.
- No mojibake strings such as \x0bie+eng, \x07ttachment_id, or \x0bersion.

## 6. Persistence, Migration, Cache And Transaction Review

Verdict: FAIL/BLOCKED.

Passing evidence:

- 	ools/qlvb_downloader/extraction_repository.py:16 has migration version g03_extraction_schema_1.
- 	ools/qlvb_downloader/extraction_repository.py:22-45 creates extraction_results.
- 	ools/qlvb_downloader/extraction_repository.py:47-62 creates extracted_pages.
- 	ools/qlvb_downloader/extraction_repository.py:73-76 creates indexes by attachment, document, status and pages result id.
- 	ools/qlvb_downloader/extraction_repository.py:43 has cache unique key using attachment, source hash, extractor name/version and OCR version.
- 	ools/qlvb_downloader/extraction_repository.py:80-90 migration is additive/idempotent and records schema migration.

Blocking issue:

ExtractionService can delete a previous successful cached extraction when a forced re-extraction fails while inserting pages.

Evidence in code:

- 	ools/qlvb_downloader/extraction_repository.py:148-160 saves result/pages in a transaction and rolls back on error.
- 	ools/qlvb_downloader/extraction_service.py:118-135 catches that error and then calls self.repository.save_failed_result(failed).
- 	ools/qlvb_downloader/extraction_repository.py:162-168 save_failed_result() calls _delete_existing_cache(result) before inserting FAILED.
- 	ools/qlvb_downloader/extraction_repository.py:170-187 _delete_existing_cache() deletes rows by the same cache key.

Runtime proof command used an in-memory SQLite DB and temp file only. It first created a successful extraction, then simulated a page-2 insert failure on orce=True. Actual output:

`	ext
FIRST_STATUS= SUCCEEDED
BEFORE_SUCCESS_COUNT= 1
SECOND_STATUS= FAILED
AFTER_SUCCESS_COUNT= 0
FAILED_COUNT= 1
ROWS= [{'id': '...', 'status': 'FAILED'}]
`

This violates the G03 requirement: old valid results must not be lost when a new run fails, and no partial/failed replacement should destroy the prior successful cache entry.

Migration runtime entrypoint verdict: LIBRARY_ONLY.

Evidence:

- 	ools/qlvb_downloader/extraction_repository.py:98 calls init_extraction_schema(conn) when ExtractionRepository is instantiated.
- Search found no hook from index_db.init_db or app startup into init_extraction_schema.
- This is acceptable as G03 service/domain library only, but should remain documented until runtime wiring is introduced.

## 7. Source B Review

Command run: Test-Path only for the five G03 paths in Source B.

Result:

`	ext
D:\Laptrinh\SmartOfficeAI360_V18_9_5_FINAL_FULL_PILOT_TEST\tools\qlvb_downloader\extraction_models.py: False
D:\Laptrinh\SmartOfficeAI360_V18_9_5_FINAL_FULL_PILOT_TEST\tools\qlvb_downloader\extraction_repository.py: False
D:\Laptrinh\SmartOfficeAI360_V18_9_5_FINAL_FULL_PILOT_TEST\tools\qlvb_downloader\extraction_service.py: False
D:\Laptrinh\SmartOfficeAI360_V18_9_5_FINAL_FULL_PILOT_TEST\tools\qlvb_downloader\ocr_adapter.py: False
D:\Laptrinh\SmartOfficeAI360_V18_9_5_FINAL_FULL_PILOT_TEST\tests\test_g03_extraction_ocr.py: False
`

SOURCE_B_G03_ARTIFACTS_ABSENT: YES.

## 8. Branch Tests

Commands run on eature/g03-extraction-ocr:

`	ext
python -m pytest tests -q
python -m compileall tools tests
git diff --check
git status --short
`

Result:

- Branch tests: 159 passed in 58.18s.
- Compile: PASS.
- Diff check: PASS.
- Working tree: clean.

Coverage exists for the requested listed cases, but it does not cover the blocking old-success-preservation scenario above.

## 9. Merge Decision

Fast-forward availability was checked:

`	ext
git merge-base --is-ancestor main feature/g03-extraction-ocr
`

Result: exit code 0, fast-forward is available.

Merge was not performed because persistence/transaction review failed.

Main remains:

`	ext
8f36dcd360b136c1cff181f902a29804d1d76485
`

No audit report commit was created, because G03 was not merged.

## 10. Final Safety State

- Current branch: eature/g03-extraction-ocr.
- Canonical working tree: clean.
- Remote: none.
- G03 tag unchanged at 5ed53731daac75477ce1f251a4d4f84d3adacc76.
- No build.
- No real data used.
- No live QLVB used.
- No AI called.
- No Planner KPI called.
- Source A was status-read only and not edited by this review.
- Source B was checked with Test-Path only and not edited.

## 11. Required Fix Before Re-Review

Fix G03 so a failed forced re-extraction cannot delete or replace the previous successful cache entry. Add a regression test that starts with an existing successful extraction, forces a new extraction that fails during page insert, and asserts the old successful result and pages remain available.

Recommendation: BLOCKED.
