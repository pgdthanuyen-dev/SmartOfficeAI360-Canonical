# SmartOfficeAI360 G05A R2 Independent Review Report

## Precheck

- Branch: `feature/g05a-assignment-rule-engine`
- HEAD: `664f0cb8b5ee1ae06895ee6062cd217a628f903d`
- Main: `66c70c56b2ab01357389b94119253a7ad52b5505`
- Old tag `canonical-g05a-assignment-rule-engine-20260719`: `46e5833e79dd86ab2519ea407d0304bdddc10ce2`
- R2 tag `canonical-g05a-assignment-rule-engine-r2-20260719`: `664f0cb8b5ee1ae06895ee6062cd217a628f903d`
- Remote: none
- Working tree: clean

## R2 Scope

R2 changes are limited to:

- `tools/qlvb_downloader/assignment_rule_engine.py`
- `tests/test_g05a_assignment_rule_engine.py`
- `docs/architecture/G05A_ASSIGNMENT_RULE_ENGINE.md`

R2 contains the expected commits:

- `fbc47b1 fix: prevent excluded G05A rules from becoming primary`
- `664f0cb test: cover G05A excluded candidate fallback behavior`

## Primary And Fallback Review

`build_recommendation()` now limits `primary_rule` to candidates with `MATCHED`, `MATCHED_WITH_WARNING`, or `NEEDS_CLASSIFICATION`. `EXCLUDED` and `NO_MATCH` candidates do not provide final lead unit, coordinating units, required roles, or assignment confidence.

Fallback behavior:

- all candidates `EXCLUDED` -> `primary_rule = None`, decision `EXCLUDED`;
- all candidates `NO_MATCH` -> `primary_rule = None`, decision `NO_MATCH`;
- mixed `EXCLUDED` and `NO_MATCH` without eligible candidate -> `primary_rule = None`, decision `NO_MATCH`.

Conflict detection uses only `MATCHED` and `MATCHED_WITH_WARNING` candidates, so `EXCLUDED` and `NO_MATCH` candidates cannot create top-rule conflicts.

Excluded candidates remain available in candidates, append-only match history, explanations, and diagnostic counts.

## Runtime Proof

- `ONLY_EXCLUDED_PRIMARY_IS_NONE: YES`
- `ONLY_EXCLUDED_DECISION: EXCLUDED`
- `ONLY_EXCLUDED_LEAD_UNIT_IS_NONE: YES`
- `ONLY_EXCLUDED_REQUIRED_ROLES_EMPTY: YES`
- `ALL_NO_MATCH_PRIMARY_IS_NONE: YES`
- `ALL_NO_MATCH_DECISION: NO_MATCH`
- `ALL_NO_MATCH_LEAD_UNIT_IS_NONE: YES`
- `MIXED_EXCLUDED_NO_MATCH_PRIMARY_IS_NONE: YES`
- `MIXED_EXCLUDED_NO_MATCH_DECISION: NO_MATCH`
- `EXCLUDED_HIGH_SCORE_SELECTED_PRIMARY: NO`
- `VALID_LOWER_RULE_SELECTED_PRIMARY: YES`
- `VALID_RULE_CONFLICT_DETECTED: YES`
- `EXCLUDED_PARTICIPATES_IN_CONFLICT: NO`
- `EXCLUDED_MATCH_HISTORY_RETAINED: YES`
- `FINGERPRINT_STABLE: YES`
- `RESULT_DETERMINISTIC: YES`

## Full G05A Review

Verified tenant isolation, effective-date filtering, required condition policy, hard and soft exclusions, score clamping to `0..100`, minimum confidence in `0..100`, conflict delta `3.0`, unit/role-only boundary, no person selection, append-only match history, no ActionItem creation, and no AI/SharePoint/Planner calls.

## Verification

- Schema tests: `24 passed`
- Engine tests: `47 passed`
- Total tests: `279 passed`
- Compile: PASS
- Diff check: PASS
- Working tree: clean

## Recommendation

`G05A_R2_READY_TO_MERGE`
