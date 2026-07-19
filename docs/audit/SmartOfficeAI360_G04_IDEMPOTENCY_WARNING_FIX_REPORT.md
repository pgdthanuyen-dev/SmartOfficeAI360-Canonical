# SmartOfficeAI360 G04 R2 Idempotency And Warning Bounds Fix Report

Date: 2026-07-19
Repository: D:\Laptrinh\SmartOfficeAI360-Canonical
Branch: fix/g04-idempotency-warning-bounds

## Scope

G04 R2 fixes the review blockers found after the original G04 merge:

- same idempotency key with different response body now returns a structured conflict;
- idempotency insert races are handled by rereading the winning batch and comparing response hashes;
- AI warning length and warning count limits are enforced at runtime;
- internal warnings/errors are bounded before persistence;
- G04 JSON Schema and prompt/boundary docs now match runtime limits.

Only G04 modules, G04 tests, and G04 architecture documents were changed.

## Commits

- 8ba99cb63a2c20c8abf7ba44d3db38f0de91a0b5 fix: enforce G04 idempotency conflicts and warning bounds
- b3dae8ddfcbab395bfe8c5480690de214e9a6ab2 test: cover G04 payload conflicts and bounded diagnostics

## Runtime Proof

- SAME_KEY_SAME_BODY_IDEMPOTENT: YES
- SAME_KEY_DIFFERENT_BODY_CONFLICT: YES
- CONFLICT_CREATED_NEW_BATCH: NO
- CONFLICT_CREATED_NEW_ACTION_ITEM: NO
- CONCURRENT_SAME_BODY_BATCH_COUNT: 1
- CONCURRENT_DIFFERENT_BODY_CONFLICT: YES
- WARNING_RUNTIME_LIMIT: PASS
- ERROR_PERSISTENCE_LIMIT: PASS
- JSON_SCHEMA_WARNING_MAX_LENGTH: PASS
- JSON_SCHEMA_WARNING_MAX_ITEMS: PASS

## Verification

- python -m pytest tests/test_g04_ai_proposal_boundary.py -q: 42 passed
- python -m pytest tests -q: 208 passed
- python -m compileall tools tests: PASS
- git diff --check: PASS
- working tree: clean before tag

## Tags

- canonical-g04-ai-proposal-boundary-20260719 remains at 2870f7098e90e43ad3fc7023c3d9ea250ac0c556
- canonical-g04-ai-proposal-boundary-r2-20260719 created at b3dae8ddfcbab395bfe8c5480690de214e9a6ab2

## External Systems

No real data, QLVB, AI provider API, Planner sync, build artifact, push, or remote was used.
