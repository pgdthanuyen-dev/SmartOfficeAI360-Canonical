# SmartOfficeAI360 G05A Exclusion Fix Report

## Baseline

- Repository: `D:\Laptrinh\SmartOfficeAI360-Canonical`
- Branch: `feature/g05a-assignment-rule-engine`
- Pre-fix HEAD: `46e5833e79dd86ab2519ea407d0304bdddc10ce2`
- Main: `66c70c56b2ab01357389b94119253a7ad52b5505`
- Old tag: `canonical-g05a-assignment-rule-engine-20260719`
- Old tag target: `46e5833e79dd86ab2519ea407d0304bdddc10ce2`
- Remote: none

## Fix

`AssignmentRuleEngine.build_recommendation()` now selects `primary_rule` only from candidates with decisions:

- `MATCHED`
- `MATCHED_WITH_WARNING`
- `NEEDS_CLASSIFICATION`

Candidates with `EXCLUDED` or `NO_MATCH` remain available in diagnostics, candidates, and match history, but they do not provide final lead unit, coordinating unit, role, or assignment confidence.

Fallback recommendation policy:

- all candidates `EXCLUDED` -> recommendation decision `EXCLUDED`, `primary_rule = None`;
- mixed `EXCLUDED` and `NO_MATCH` with no eligible candidate -> recommendation decision `NO_MATCH`, `primary_rule = None`;
- all `NO_MATCH` -> recommendation decision `NO_MATCH`, `primary_rule = None`.

Conflict detection remains limited to `MATCHED` and `MATCHED_WITH_WARNING` candidates, so `EXCLUDED` and `NO_MATCH` candidates do not create top-rule conflicts.

## Tests Added

- only hard-excluded rule has no primary assignment;
- high-priority excluded rule cannot beat a lower valid rule;
- all no-match rules have no primary assignment;
- mixed excluded/no-match rules have no primary assignment;
- excluded rule does not participate in top-rule conflict;
- excluded candidate is retained in match history;
- excluded fallback result is deterministic.

## Runtime Proof

- `ONLY_EXCLUDED_PRIMARY_IS_NONE: YES`
- `ONLY_EXCLUDED_DECISION: EXCLUDED`
- `ONLY_EXCLUDED_LEAD_UNIT_IS_NONE: YES`
- `EXCLUDED_HIGH_SCORE_SELECTED_PRIMARY: NO`
- `VALID_LOWER_RULE_SELECTED_PRIMARY: YES`
- `ALL_NO_MATCH_PRIMARY_IS_NONE: YES`
- `MIXED_EXCLUDED_NO_MATCH_PRIMARY_IS_NONE: YES`
- `EXCLUDED_PARTICIPATES_IN_CONFLICT: NO`
- `EXCLUDED_MATCH_HISTORY_RETAINED: YES`
- `RESULT_DETERMINISTIC: YES`

## Verification

- Engine tests: `47 passed`
- Schema tests: `24 passed`
- Total tests: `279 passed`
- Compile: PASS
- Diff check: PASS
- Working tree: clean
- AI API called: NO
- SharePoint called: NO
- Planner called: NO

## Commits And Tags

- `fbc47b1` - `fix: prevent excluded G05A rules from becoming primary`
- `664f0cb` - `test: cover G05A excluded candidate fallback behavior`
- R2 tag: `canonical-g05a-assignment-rule-engine-r2-20260719`
- R2 tag target: `664f0cb8b5ee1ae06895ee6062cd217a628f903d`

## Recommendation

`G05A_R2_READY_FOR_REVIEW`
