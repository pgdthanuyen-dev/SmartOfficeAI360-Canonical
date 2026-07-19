# SmartOfficeAI360 G05A Rule Engine Review Report

## Precheck

- Branch: `feature/g05a-assignment-rule-engine`
- HEAD: `46e5833e79dd86ab2519ea407d0304bdddc10ce2`
- Main: `66c70c56b2ab01357389b94119253a7ad52b5505`
- Tag `canonical-g05a-assignment-rule-engine-20260719`: `46e5833e79dd86ab2519ea407d0304bdddc10ce2`
- Remote: none
- Working tree: clean

## Scope

Changed files are limited to G05A schema, repository, validation, engine, tests, and architecture documents. The branch contains the expected four G05A commits:

- `8b527ed feat: add G05A assignment rule domain schema`
- `e950f8e test: validate G05A rule persistence and compatibility`
- `3f37e96 feat: add deterministic G05A assignment rule engine`
- `46e5833 test: validate G05A scoring exclusions and conflict handling`

## Blocking Issue

`tools/qlvb_downloader/assignment_rule_engine.py:315` selects `primary = eligible[0] if eligible else (candidates[0] if candidates else None)`. Since ranked candidates may contain only hard-excluded rules, a hard-excluded candidate can become `recommendation.primary_rule`.

Runtime proof confirmed this with fake SQLite data:

- `HARD_EXCLUSION_DECISION: EXCLUDED`
- `HARD_EXCLUSION_SCORE: 0`
- `HARD_EXCLUSION_PRIMARY_RULE: CDS-HARD`

This conflicts with the review requirement and the architecture statement that hard exclusions cannot become a primary recommendation.

## Runtime Proof

- `VALID_RULE_DECISION: MATCHED`
- `VALID_RULE_SCORE: 100`
- `VALID_LEAD_UNIT: VP-CDS`
- `VALID_REQUIRED_ROLES: LEADER,MONITOR,LEAD_EXECUTOR`
- `HARD_EXCLUSION_DECISION: EXCLUDED`
- `HARD_EXCLUSION_SCORE: 0`
- `MISSING_REQUIRED_DECISION: NEEDS_CLASSIFICATION`
- `TOP_RULE_CONFLICT: YES`
- `CONFLICT_FINAL_LEAD_UNIT_EMPTY: YES`
- `FINGERPRINT_STABLE: YES`
- `RESULT_DETERMINISTIC: YES`
- `MATCH_HISTORY_APPEND_ONLY: YES`
- `PERSON_SELECTED: NO`
- `ACTION_ITEM_CREATED: NO`
- `AI_API_CALL_COUNT: 0`
- `SHAREPOINT_CALL_COUNT: 0`
- `PLANNER_CALL_COUNT: 0`

## Test Results

- Schema tests: `24 passed`
- Engine tests: `40 passed`
- Total tests: `272 passed`
- Compile: PASS
- Diff check: PASS
- Working tree: clean

## Recommendation

`BLOCKED` until hard-excluded candidates are prevented from becoming the recommendation primary rule.
