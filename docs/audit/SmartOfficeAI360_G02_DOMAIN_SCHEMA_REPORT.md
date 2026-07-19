# SmartOfficeAI360 G02 Domain Schema Report

- Date: 2026-07-19
- Repository: `D:\Laptrinh\SmartOfficeAI360-Canonical`
- Branch: `feature/g02-domain-schema`
- Base commit: `7067eda3ab7c7b59001068da5f5763c3f3087628`
- HEAD: `2334c0728cf4242e1913094cfb81d001248becb3`
- Remote: none
- Recommendation: **G02_READY_FOR_REVIEW**

## 1. Legacy Model Analysis

Existing downloader model remains intact:

- `tools/qlvb_downloader/models.py`
  - `AttachmentInfo`: `text`, `href`, `saved_path`, `original_filename`, `status`, `error`, `validation_sha256`, `validation_size_bytes`, `validation_content_type`, `download_source`.
  - `DocumentRecord`: `direction`, `source_url`, `row_index`, `row_text`, `source_category`, `knowledge_candidate`, `planner_candidate`, `detail_url`, `doc_id`, `doc_no`, `doc_date`, `issuing_agency`, `title`, `summary`, `parser_version`, `mapping_warnings`, `metadata`, `attachments`, `status`, `error`, `created_at`, `updated_at`.
  - G01 statuses preserved: `DISCOVERED`, `DOWNLOAD_STARTED`, `DOWNLOADED_RAW`, `VALIDATED`, `INVALID_FILE`, `DOWNLOAD_FAILED`.

Existing manifest and queue remain compatible:

- `tools/qlvb_downloader/storage.py` keeps manifest `schema_version = 2.0.0`.
- `StorageManager.get_queue_item_files()` still supports new flat queue and old fallback `READY` format.
- `sync_client.py` continues to read manifest `sync.planner_kpi_status` and upload package shape; G02 does not call Planner KPI.

Existing SQLite index:

- `index_db.py` had a legacy `documents` table keyed by `doc_id`.
- G02 keeps that table, adds columns, and adds new related tables without deleting or renaming legacy columns.

## 2. New Files

- `tools/qlvb_downloader/domain_models.py`
- `tools/qlvb_downloader/domain_validation.py`
- `tools/qlvb_downloader/domain_repository.py`
- `tests/test_g02_domain_schema.py`
- `docs/architecture/G02_DOMAIN_SCHEMA.md`
- `docs/architecture/G02_SCHEMA_DECISIONS.md`

## 3. Modified Files

- `tools/qlvb_downloader/index_db.py`
  - Calls G02 additive migration from `init_db()` with graceful logging if migration fails.

## 4. Entities Created

- `Document`
- `Attachment`
- `ActionItem`
- `SourceCitation`
- `ReviewDecision`
- `SyncEvent`
- `UserUnitMapping`

Domain schema version: `1.0.0`.

## 5. Enums

- `DocumentType`: `INCOMING`, `OUTGOING`, `INTERNAL`, `OTHER`
- `IngestStatus`: `NEW`, `INGESTED`, `EXTRACTED`, `AI_ANALYZED`, `ERROR`
- `AttachmentValidationStatus`: G01-compatible statuses
- `ActionItemStatus`: `PROPOSED`, `PENDING_REVIEW`, `NEEDS_CORRECTION`, `APPROVED`, `REJECTED`, `SYNC_PENDING`, `SYNCING`, `SYNCED`, `SYNC_ERROR`
- `Priority`: `LOW`, `NORMAL`, `HIGH`, `URGENT`
- `Complexity`: `SIMPLE`, `MEDIUM`, `COMPLEX`
- `ReviewDecisionType`: `APPROVE`, `REJECT`, `REQUEST_CHANGES`, `EDIT_AND_APPROVE`
- `SyncEventStatus`: `PENDING`, `IN_PROGRESS`, `SUCCEEDED`, `RETRYABLE_FAILED`, `PERMANENT_FAILED`, `CANCELLED`
- `MappingStatus`: `ACTIVE`, `INACTIVE`, `NEEDS_REVIEW`

## 6. Database Tables, Indexes And Constraints

G02 extends the existing `documents` table and adds:

- `attachments`
- `action_items`
- `source_citations`
- `review_decisions`
- `sync_events`
- `user_unit_mappings`
- `schema_migrations`

Key constraints/indexes:

- Unique document source identity: `tenant_id`, `source_system`, `source_document_id`, `source_revision`.
- `sync_events.idempotency_key` unique.
- Foreign keys from attachments/action items/citations/review decisions/sync events back to document/action rows.
- Indexes on `source_document_id`, `document_id`, `action_item_id`, `status`, `idempotency_key`, and mapping source keys.

## 7. Migration

- Migration function: `init_domain_schema(conn)`
- Migration version: `g02_domain_schema_1`
- Idempotent: YES
- Preserves legacy data: YES
- Does not migrate real Data: YES
- Uses parameterized SQL for runtime inserts.

## 8. Backward Compatibility

- Manifest `2.0.0` is not upgraded.
- Existing downloader, storage queue, extractor enrichment and sync client behavior are preserved.
- G01 queue tests still pass.
- Old database table data remains after additive migration.

## 9. Validation

Implemented validation covers:

- Action item must reference an existing document before persistence.
- Citation must belong to the same document as action item and attachment.
- Approved action item requires title.
- `SYNC_PENDING` transition requires prior `APPROVED`.
- Rejected action item cannot receive sync event.
- ISO due dates and timezone-aware datetimes are checked.
- AI confidence range: `0.0 <= confidence <= 1.0`.
- Page/character ranges validated.
- SHA-256 hex format validated.
- Idempotency key required.
- Review decision requires reviewer trace.
- Ambiguous user/unit mapping must be `NEEDS_REVIEW`.

## 10. New Tests

New test file: `tests/test_g02_domain_schema.py`

New tests: `22 passed`.

Coverage includes serialization, G01 attachment status compatibility, multiple action items, multiple citations, citation document mismatch, confidence validation, approval title validation, rejected sync blocking, review append-only history, sync idempotency, user mapping review, migration first/idempotent runs, old DB preservation, foreign key behavior, cascade delete, stable hash, datetime roundtrip, manifest 2.0.0 read compatibility, and G01 queue compatibility.

## 11. Total Tests

Final test result:

```text
133 passed in 55.11s
```

Legacy tests: PASS.
G02 tests: PASS.

## 12. Compileall

Command:

```powershell
python -m compileall tools tests
```

Result: PASS.

## 13. Diff Check

Command:

```powershell
git diff --check
```

Result: PASS.

## 14. Commits

```text
edbc222 feat: add canonical document and action-item domain schema
9dfb5b6 feat: add additive persistence for review and sync domains
2334c07 test: validate G02 domain schema compatibility and migrations
```

## 15. Tag

```text
canonical-g02-domain-schema-20260719
```

## 16. Final Git Log

```text
2334c07 (HEAD -> feature/g02-domain-schema, tag: canonical-g02-domain-schema-20260719) test: validate G02 domain schema compatibility and migrations
9dfb5b6 feat: add additive persistence for review and sync domains
edbc222 feat: add canonical document and action-item domain schema
7067eda (main) docs: record canonical source decision and G01 validation
68acd4e (tag: canonical-g01-downloader-hardened-20260719) fix: harden QLVB downloads and queue readiness
0bbd63f chore: define canonical line ending policy
67efa84 (tag: canonical-baseline-a-pre-g01-20260718) chore: establish reviewed SmartOfficeAI360 canonical baseline
```

## 17. Final Git Status

`git status --short`: clean.

`git remote -v`: no output.

## 18. Not Implemented In G02

- OCR runtime
- AI calls or production prompts
- Review UI
- Real Planner KPI task sync
- SharePoint/OneDrive
- Real QLVB access
- EXE build
- G03 work
- Merge into main
- Push/remote

## 19. Risks

1. G02 persistence maps canonical `Document.id` to legacy `documents.doc_id` for FK compatibility with the existing table.
2. `source_url` redaction remains a caller/logging responsibility; domain entities do not log URLs.
3. User/unit mapping has no live directory lookup yet, so ambiguous mappings remain `NEEDS_REVIEW`.
4. Future Planner KPI payload shape is not finalized; `SyncEvent` stores audit state and hashes only.
5. No real QLVB/Planner integration was exercised by design.

## 20. Proposed G03

Recommended G03 scope: implement the AI proposal boundary and review queue storage without calling a production AI service. Suggested steps:

1. Add `ActionItemProposal` ingestion from mock parser/AI JSON.
2. Add review queue state transitions around `PENDING_REVIEW`, `NEEDS_CORRECTION`, `APPROVED`, `REJECTED`.
3. Add UI-independent service methods for approve/reject/edit-and-approve.
4. Add contract tests for future Planner KPI sync eligibility.

## 21. Terminal Summary

```text
G02_BRANCH: feature/g02-domain-schema
G02_BASE_COMMIT: 7067eda3ab7c7b59001068da5f5763c3f3087628
LEGACY_MODELS_MAPPED: YES
DOMAIN_SCHEMA_VERSION: 1.0.0
DOCUMENT_MODEL: PASS
ATTACHMENT_MODEL: PASS
ACTION_ITEM_MODEL: PASS
SOURCE_CITATION_MODEL: PASS
REVIEW_DECISION_MODEL: PASS
SYNC_EVENT_MODEL: PASS
USER_UNIT_MAPPING_MODEL: PASS
SQLITE_MIGRATION: PASS
MIGRATION_IDEMPOTENT: YES
MANIFEST_2_COMPATIBLE: YES
G01_QUEUE_COMPATIBLE: YES
LEGACY_TESTS: PASS
NEW_TESTS: 22 passed
TOTAL_TESTS: 133 passed in 55.11s
COMPILE_CHECK: PASS
DIFF_CHECK: PASS
COMMITS: edbc222, 9dfb5b6, 2334c07
TAG: canonical-g02-domain-schema-20260719
WORKTREE_CLEAN: YES
REMOTE_CONFIGURED: NO
SOURCE_A_CHANGED: NO
SOURCE_B_CHANGED: NO
REAL_DATA_USED: NO
REAL_QLVB_USED: NO
REAL_PLANNER_SYNC_USED: NO
RECOMMENDATION: G02_READY_FOR_REVIEW
```
