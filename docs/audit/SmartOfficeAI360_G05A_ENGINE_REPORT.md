# SmartOfficeAI360 G05A Assignment Rule Engine Report

## Baseline

- Repository: `D:\Laptrinh\SmartOfficeAI360-Canonical`
- Branch: `feature/g05a-assignment-rule-engine`
- Base commit before engine work: `e950f8e85e07568f3a5bfc49e59dc793813174b9`
- Main commit: `66c70c56b2ab01357389b94119253a7ad52b5505`
- Remote: none
- Precheck tests: `232 passed`

## Implementation

- Added deterministic engine module: `tools/qlvb_downloader/assignment_rule_engine.py`
- Added engine architecture document: `docs/architecture/G05A_ASSIGNMENT_RULE_ENGINE.md`
- Updated schema architecture document to reference implemented engine behavior.
- Added engine tests: `tests/test_g05a_assignment_rule_engine.py`

## Engine Contract

- Engine version: `g05a.engine.1`
- Input model: `DocumentAssignmentSignals`
- Output models: `AssignmentRuleEvaluation`, `AssignmentRuleCandidate`, `AssignmentRecommendation`
- Match modes: `EXACT`, `CONTAINS`, `TOKEN`, `PREFIX`, `REGEX_SAFE`
- Conflict delta: `TOP_RULE_CONFLICT_DELTA = 3.0`

## Normalization And Fingerprint

Signals are normalized with Unicode NFC, casefold lowercase, whitespace collapse, stable list dedupe, invalid control removal, bounded text lengths, bounded list size, and preserved Vietnamese accents. The input fingerprint is canonical JSON plus SHA-256 over tenant, document id, revision, reference date, engine version, and normalized signals.

## Scoring

Rules are filtered by tenant, `ACTIVE` status, and effective dates. Hard exclusions return `EXCLUDED` score `0`. Non-hard exclusions subtract their penalty. Positive conditions use:

```text
base_score = round(100 * matched_positive_weight / total_positive_weight, 2)
final_score = clamp(base_score - soft_penalty_total, 0, 100)
```

Missing required conditions cannot return `MATCHED` or `MATCHED_WITH_WARNING`. Scores at or above `75` with missing required signal become `NEEDS_CLASSIFICATION`; below `75` becomes `NO_MATCH`.

`minimum_confidence` prevents matched decisions below the rule threshold and emits `LOW_CONFIDENCE`.

## Ranking And Conflict

Candidates are ranked by decision eligibility, score, priority, matched required count, total matched count, newer version, and stable rule code. Top eligible rules within `3.0` points with different lead unit or role group cause `NEEDS_CLASSIFICATION`, clear the final lead unit, and emit conflict warnings.

## Unit And Role Boundary

G05A recommends source unit keys and role codes only. It does not select personnel, Planner users, SharePoint users, emails, or assignment drafts.

## Persistence

When `persist_matches=True`, the engine appends one `AssignmentRuleMatch` per candidate. It stores bounded explanation, bounded warnings JSON, score, decision, counts, rule identity, document id/revision, and input fingerprint. It does not store full title, summary, extracted text, raw AI response, secrets, Planner payloads, or SharePoint data.

## Tests

- G05A engine tests: `40 passed`
- G05A schema tests: `24 passed`
- Total tests: `272 passed`
- Compile: PASS
- Diff check: PASS

## Commits And Tag

- `3f37e9686b27ab1ac65c3054a72c3e952c2fb8bd` - `feat: add deterministic G05A assignment rule engine`
- `46e5833e79dd86ab2519ea407d0304bdddc10ce2` - `test: validate G05A scoring exclusions and conflict handling`
- Tag: `canonical-g05a-assignment-rule-engine-20260719`
- Tag target: `46e5833e79dd86ab2519ea407d0304bdddc10ce2`

## Boundary

- Source A changed: NO
- Source B changed: NO
- AI API called: NO
- SharePoint called: NO
- Planner called: NO
- QLVB called: NO
- Build created: NO
- Remote configured: NO

## Recommendation

`G05A_READY_FOR_REVIEW`
