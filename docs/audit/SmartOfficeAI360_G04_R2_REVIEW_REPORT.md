# SmartOfficeAI360 G04 R2 Review Report

Date: 2026-07-19
Repository: D:\Laptrinh\SmartOfficeAI360-Canonical
Branch: fix/g04-idempotency-warning-bounds
Head: b3dae8ddfcbab395bfe8c5480690de214e9a6ab2

## Review Scope

R2 changes are limited to the expected G04 modules, G04 tests, and G04 architecture documents:

- docs/architecture/G04_AI_OUTPUT_SCHEMA.json
- docs/architecture/G04_AI_PROPOSAL_BOUNDARY.md
- docs/architecture/G04_PROMPT_CONTRACT.md
- tests/test_g04_ai_proposal_boundary.py
- tools/qlvb_downloader/ai_proposal_models.py
- tools/qlvb_downloader/ai_proposal_repository.py
- tools/qlvb_downloader/ai_proposal_service.py
- tools/qlvb_downloader/ai_proposal_validation.py

## Static Review

- Same idempotency key and same raw_response_sha256 returns the existing batch.
- Same idempotency key and different raw_response_sha256 returns IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD.
- Conflict result carries idempotency_key and existing_batch_id only; it does not include raw response content.
- Conflict path returns batch_id="" and does not create action items or citations.
- ai_proposal_batches keeps idempotency_key TEXT NOT NULL UNIQUE and a unique index.
- create_batch still performs INSERT; IntegrityError is caught, the winning batch is reread, and hash comparison is applied. This is not SELECT-only protection.
- Runtime validator enforces warning max length and max warning counts for envelope and proposal warnings.
- Repository bounds persisted warning_code/message and error_message.
- JSON Schema warning maxLength/maxItems match runtime constants.

## Runtime Proof

SQLite tempfile with two connections produced:

- SAME_KEY_SAME_BODY_BATCH_COUNT=1
- SAME_KEY_SAME_BODY_ACTION_ITEM_COUNT=1
- SAME_KEY_DIFFERENT_BODY_CONFLICT=YES
- DIFFERENT_BODY_NEW_BATCH_COUNT=0
- DIFFERENT_BODY_NEW_ACTION_ITEM_COUNT=0
- CONCURRENT_SAME_BODY_BATCH_COUNT=1
- CONCURRENT_DIFFERENT_BODY_CONFLICT=YES
- OVERLONG_WARNING_REJECTED=YES
- TOO_MANY_WARNINGS_REJECTED=YES
- PERSISTED_ERROR_MAX_LENGTH_ENFORCED=YES

## Verification

- python -m pytest tests/test_g04_ai_proposal_boundary.py -q: 42 passed
- python -m pytest tests -q: 208 passed
- python -m compileall tools tests: PASS
- git diff --check: PASS
- git status --short: clean

## Tags

- canonical-g04-ai-proposal-boundary-20260719 remains at 2870f7098e90e43ad3fc7023c3d9ea250ac0c556.
- canonical-g04-ai-proposal-boundary-r2-20260719 points to b3dae8ddfcbab395bfe8c5480690de214e9a6ab2.

## Recommendation

G04 R2 is ready to merge.
