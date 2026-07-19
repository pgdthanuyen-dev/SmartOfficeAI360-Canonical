# G05A Assignment Rule Engine

## Goal

G05A provides a deterministic, library-only rule engine that evaluates normalized document signals against persisted assignment rules and recommends source unit keys and role codes. It does not select people, create assignment drafts, call AI, call SharePoint, call Planner, call QLVB, or write runtime data outside explicit append-only match history.

Engine version: `g05a.engine.1`.

Conflict delta: `TOP_RULE_CONFLICT_DELTA = 3.0`.

## Input Contract

`DocumentAssignmentSignals` is the only engine input model. It carries:

- `tenant_id`
- `document_id`
- `document_revision`
- `document_type`
- `issuer_name`
- `issuer_group`
- `domain_codes`
- `subdomain_codes`
- `required_actions`
- `keywords`
- `target_entities`
- `expected_outputs`
- `title`
- `summary`
- `reference_date`

The engine reads only these normalized signals plus rules loaded from `AssignmentRuleRepository`.

## Normalization

Normalization is deterministic:

- Unicode NFC;
- lowercase with `casefold()`;
- Vietnamese accents are preserved;
- whitespace is collapsed;
- invalid control characters are removed;
- list signals are deduplicated in stable first-seen order;
- signal text and list counts are bounded.

The engine does not spell-correct, translate, or strip accents as a primary matching strategy.

## Fingerprint

The input fingerprint is a canonical JSON SHA-256 over:

- engine version;
- tenant id;
- document id;
- document revision;
- reference date;
- normalized scalar signals;
- normalized list signals.

The fingerprint is stable for equivalent normalized input and changes when the document revision or material signals change.

## Match Modes

Rules support these modes:

- `EXACT`: normalized signal equals normalized rule value.
- `CONTAINS`: normalized rule value appears inside the signal.
- `TOKEN`: normalized rule value matches a whole token and does not match partial words.
- `PREFIX`: signal starts with the normalized rule value.
- `REGEX_SAFE`: stored rule regex is validated by schema work and compiled by Python regex matching with no code execution. Runtime regex errors are contained and do not break other rules.

## Condition Mapping

Condition types read these input signals:

- `DOMAIN` -> `domain_codes`
- `SUBDOMAIN` -> `subdomain_codes`
- `DOCUMENT_TYPE` -> `document_type`
- `ISSUER_GROUP` -> `issuer_group`
- `REQUIRED_ACTION` -> `required_actions`
- `REQUIRED_KEYWORD` -> `title`, `summary`, `keywords`
- `PREFERRED_KEYWORD` -> `title`, `summary`, `keywords`
- `TARGET_ENTITY` -> `target_entities`
- `EXPECTED_OUTPUT` -> `expected_outputs`

## Exclusion Mapping

Exclusions are evaluated before positive scoring:

- `EXCLUDED_KEYWORD` -> `title`, `summary`, `keywords`
- `EXCLUDED_ACTION` -> `required_actions`
- `EXCLUDED_ISSUER` -> `issuer_name`, `issuer_group`
- `EXCLUDED_DOCUMENT_TYPE` -> `document_type`

Hard exclusions return `EXCLUDED` with score `0` and cannot become a primary recommendation. Excluded candidates remain in the candidate list and append-only match history only for audit and diagnostics. Soft exclusions subtract their configured penalty from the score.

## Scoring

The engine filters rules by tenant, `ACTIVE` status, and effective date range before evaluation.

For each non-excluded rule:

```text
base_score = round(100 * matched_positive_weight / total_positive_weight, 2)
final_score = clamp(base_score - soft_penalty_total, 0, 100)
```

Rules with no positive conditions return `NO_MATCH`.

Required condition policy:

- a missing required condition prevents `MATCHED` and `MATCHED_WITH_WARNING`;
- if the score is at least `75`, the decision becomes `NEEDS_CLASSIFICATION`;
- otherwise the decision is `NO_MATCH`;
- `MISSING_REQUIRED_SIGNAL` is emitted.

Thresholds:

- `>= 90`: `MATCHED` when no warning or conflict blocks it;
- `75..89`: `MATCHED_WITH_WARNING`;
- `>= 75` with missing required signals, unresolved required unit/role, or conflict: `NEEDS_CLASSIFICATION`;
- `< 75`: `NO_MATCH`.

`minimum_confidence` is enforced after scoring. A candidate below the rule's minimum confidence cannot be `MATCHED` or `MATCHED_WITH_WARNING`; it becomes `NEEDS_CLASSIFICATION` at or above `75`, otherwise `NO_MATCH`, and emits `LOW_CONFIDENCE`.

## Ranking

Candidates are sorted by:

- decision eligibility;
- score descending;
- priority descending;
- matched required condition count descending;
- total matched condition count descending;
- newer version;
- stable `rule_code`.

## Conflict Handling

The top eligible candidate is compared with nearby eligible candidates. If another eligible rule is within `TOP_RULE_CONFLICT_DELTA` points and has a different lead unit or required role group, the recommendation becomes `NEEDS_CLASSIFICATION`.

Only `MATCHED` and `MATCHED_WITH_WARNING` candidates participate in top-rule conflict detection. `EXCLUDED` and `NO_MATCH` candidates never create a conflict.

Conflict recommendations emit:

- `MULTIPLE_TOP_RULES`
- `CONFLICTING_RULES`

The final `lead_unit_key` is cleared and `conflicting_rules` are returned for reviewer classification.

## Output Contract

`AssignmentRuleEvaluation` contains:

- normalized `DocumentAssignmentSignals`;
- all ranked `AssignmentRuleCandidate` rows;
- one `AssignmentRecommendation`.

Each `AssignmentRuleCandidate` includes rule id/code/version, score, decision, matched conditions, missing required conditions, matched exclusions, soft penalty total, lead/coordinating unit keys, required role codes, warnings, explanation, priority, and required-condition counts.

`AssignmentRecommendation` includes document id/revision, input fingerprint, evaluated/eligible/excluded counts, primary rule, alternatives, conflicts, decision, confidence, lead unit key, coordinating unit keys, required roles, unresolved fields, warnings, explanation, engine version, and evaluation timestamp.

`primary_rule` can only be `MATCHED`, `MATCHED_WITH_WARNING`, or `NEEDS_CLASSIFICATION`. `EXCLUDED` and `NO_MATCH` candidates never become `primary_rule` and never provide final `lead_unit_key`, `coordinating_unit_keys`, `required_roles`, or assignment confidence. If no primary-eligible candidate exists, the recommendation returns `primary_rule = None`, no unit or role recommendation, and neutral confidence `0`.

## Unit And Role Boundary

G05A recommends only:

- source lead unit key;
- source coordinating unit keys;
- role codes for leader, monitor, lead executor, and co-executor style routing.

It never resolves a person, directory identity, Planner user id, SharePoint user, email account, or assignment draft.

## Persistence

`persist_matches=True` writes one append-only `AssignmentRuleMatch` per candidate. The history stores bounded explanation, bounded warnings JSON, score, decision, counts, rule identity, document id/revision, and input fingerprint.

Match history does not store full title, summary, extracted text, AI raw response, credentials, browser/session data, Planner payloads, or SharePoint data.

## Determinism

For the same repository state and same normalized input, candidate ordering, input fingerprint, scores, warnings, and selected rule are deterministic. Only the `evaluated_at` timestamp changes per evaluation.

## Tests

`tests/test_g05a_assignment_rule_engine.py` covers normalization, fingerprinting, match modes, active-date and tenant filtering, required condition policy, hard and soft exclusions, confidence thresholds, ranking, conflict handling, unit/role output, append-only persistence, bounded match history, rule error containment, and the no-person/no-external-call boundary.
