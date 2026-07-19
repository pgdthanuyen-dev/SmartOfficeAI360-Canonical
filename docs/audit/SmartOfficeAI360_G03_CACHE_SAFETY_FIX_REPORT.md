# SmartOfficeAI360 Canonical - G03 Cache Transaction Safety Fix Report

Thoi gian lap bao cao: 2026-07-19T10:37:08.0993588+07:00
Repository: D:\Laptrinh\SmartOfficeAI360-Canonical
Branch: feature/g03-extraction-ocr
G03 before fix: 5ed53731daac75477ce1f251a4d4f84d3adacc76
G03 after fix: a8d7b46d9f8b75046ef5e95ae41445660eef4f3f
Main unchanged: 8f36dcd360b136c1cff181f902a29804d1d76485
Old tag unchanged: canonical-g03-extraction-ocr-20260719 -> 5ed53731daac75477ce1f251a4d4f84d3adacc76
New tag: canonical-g03-extraction-ocr-r2-20260719 -> a8d7b46d9f8b75046ef5e95ae41445660eef4f3f

## 1. Old Bug

A forced refresh could delete a previous successful extraction cache and replace it with FAILED when a later page insert failed.

Pre-fix proof, using only SQLite memory DB and tempfile:

`	ext
FIRST_STATUS= SUCCEEDED
BEFORE_SUCCESS_COUNT= 1
SECOND_STATUS= FAILED
AFTER_SUCCESS_COUNT= 0
FAILED_COUNT= 1
TOTAL_PAGES= 0
`

Root cause:

- ExtractionService caught page insert failure and called save_failed_result().
- save_failed_result() deleted cache rows by the same cache key before inserting FAILED.
- This removed the old successful result and cascade-deleted old pages.

## 2. New Cache/Attempt Design

Cacheable output and run history are now separate:

- extraction_results and extracted_pages store usable/cacheable output.
- extraction_attempts stores run history for SUCCEEDED/FAILED attempts.
- FAILED attempts do not replace successful extraction cache rows.

New migration version:

`	ext
g03_extraction_cache_safety_1
`

New table:

`	ext
extraction_attempts(
  id, document_id, attachment_id, source_file_sha256,
  extractor_name, extractor_version, ocr_version,
  force_requested, status, result_id,
  error_code, error_message,
  started_at, completed_at, created_at
)
`

Indexes added:

- idx_extraction_attempts_attachment_id
- idx_extraction_attempts_status
- idx_extraction_attempts_created_at

## 3. Transaction Boundary

Successful force refresh is atomic:

1. delete previous cache row for the same key;
2. insert new extraction result;
3. insert all pages;
4. insert SUCCEEDED attempt linked to the new result;
5. commit.

If any page insert fails, the transaction rolls back and restores the previous successful result/pages. A separate FAILED attempt is then recorded outside the cache replacement transaction.

## 4. Behavior After Fix

Post-fix proof, using only SQLite memory DB and tempfile:

`	ext
FIRST_STATUS= SUCCEEDED
BEFORE_SUCCESS_COUNT= 1
SECOND_STATUS= FAILED
AFTER_SUCCESS_COUNT= 1
FAILED_CACHE_COUNT= 0
FAILED_ATTEMPT_COUNT= 1
TOTAL_PAGES= 1
`

Meaning:

- old success cache preserved: YES;
- failed attempt recorded: YES;
- partial pages after failure: NO;
- FAILED is not stored as cache result: YES.

## 5. Tests Added

New regression coverage in 	ests/test_g03_extraction_ocr.py:

- 	est_force_failure_preserves_previous_success_result
- 	est_force_failure_records_failed_attempt
- 	est_non_force_after_failed_force_returns_old_cache
- 	est_successful_force_atomically_replaces_old_cache
- 	est_failed_first_extraction_creates_attempt_not_cache
- 	est_attempt_migration_idempotent
- 	est_attempt_history_does_not_break_legacy_g03_cache

G03 tests increased from 26 to 33. Total suite increased from 159 to 166.

## 6. Verification

Commands run:

`	ext
python -m pytest tests/test_g03_extraction_ocr.py -q
python -m pytest tests -q
python -m compileall tools tests
git diff --check
git status --short
git diff --stat
git diff --name-only
`

Results:

- G03 tests: 33 passed in 2.06s
- Total tests: 166 passed in 58.29s
- Compile: PASS
- Diff check: PASS
- Final working tree after commits/tags: clean

## 7. Commits

`	ext
8f06610 fix: preserve successful extraction cache on failed refresh
a8d7b46 test: cover G03 cache replacement and failure preservation
`

## 8. Tags

Old tag unchanged:

`	ext
canonical-g03-extraction-ocr-20260719 -> 5ed53731daac75477ce1f251a4d4f84d3adacc76
`

New tag:

`	ext
canonical-g03-extraction-ocr-r2-20260719 -> a8d7b46d9f8b75046ef5e95ae41445660eef4f3f
`

## 9. Safety

- Did not merge into main.
- Did not move or delete old G03 tag.
- Did not edit Source A.
- Did not edit Source B.
- Did not install dependencies.
- Did not build.
- Did not use real data.
- Did not run live QLVB.
- Did not call AI.
- Did not call Planner KPI.
- Did not create remote or push.

Source B artifact check:

`	ext
tools\qlvb_downloader\extraction_models.py: False
tools\qlvb_downloader\extraction_repository.py: False
tools\qlvb_downloader\extraction_service.py: False
tools\qlvb_downloader\ocr_adapter.py: False
tests\test_g03_extraction_ocr.py: False
`

## 10. Residual Risks

- extraction_attempts is library-level migration through ExtractionRepository; runtime startup wiring remains a later review/merge concern.
- Old SUCCEEDED attempt rows can have esult_id set NULL after a later successful forced replacement deletes the old result; this preserves append-only attempt history while keeping only one active cache row for a cache key.
- Production OCR packaging and health checks remain outside this cache safety fix.

## 11. Recommendation

RECOMMENDATION: G03_CACHE_FIX_READY_FOR_REVIEW
