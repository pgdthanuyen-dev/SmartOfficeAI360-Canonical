# SmartOfficeAI360 G05A Assignment Rule Engine Design

Date: 2026-07-19
Repository surveyed: D:\Laptrinh\SmartOfficeAI360-Canonical
Baseline: 66c70c56b2ab01357389b94119253a7ad52b5505 on main
Scope: design only, no repo changes

## 1. Baseline Result

Precheck passed:

- branch: main
- HEAD/main: 66c70c56b2ab01357389b94119253a7ad52b5505
- remote: none
- worktree: clean
- tests: 208 passed

## 2. G02-G04 Model Mapping

G02 provides the canonical business layer:

- Document: source identity, revision, type, number, issuer, subject, summary, dates, source URL, and content hash.
- Attachment: document-bound file metadata and validation status.
- ActionItem: proposed task fields including title, description, proposed_unit_id, assignee/supervisor, due date, expected output, output type, priority, complexity, AI confidence, model/prompt metadata, status, and version.
- SourceCitation: traceability from action item back to document, attachment, page/character range, excerpt hash, and source text hash.
- UserUnitMapping: existing place to map source display keys to target unit/user IDs and roles.

G03 provides extracted_pages and extraction_results, which are the canonical text surface for matching keyword, exclusion, product, action, and source-reference evidence.

G04 provides AI proposals and citations. G05A should not call AI; it should consume existing Document, ActionItem, SourceCitation, and extracted page text to recommend assignment fields before human review or later sync.

## 3. Proposed G05A Entities

AssignmentRule

- id: text primary key
- tenant_id: text
- name: text
- description: text nullable
- status: RuleStatus
- priority: integer, higher wins after mandatory filters
- effective_from: ISO date nullable
- effective_to: ISO date nullable
- minimum_confidence: real 0.0..1.0
- source_reference: text nullable, for policy/document/rule source
- version: integer
- created_at, updated_at: UTC ISO datetime

AssignmentRuleCondition

- id: text primary key
- rule_id: FK AssignmentRule
- condition_type: ConditionType
- field_name: text nullable, for mapped fields such as issuer, document_type, subject, extracted_text, expected_output
- operator: text, initial values CONTAINS_ANY, CONTAINS_ALL, EXACT, REGEX, EQUALS, IN
- value_json: canonical JSON payload
- weight: integer, additive score when matched
- required: boolean
- case_sensitive: boolean default false
- normalize_vietnamese: boolean default true
- created_at: UTC ISO datetime

AssignmentRuleExclusion

- id: text primary key
- rule_id: FK AssignmentRule
- exclusion_type: ConditionType
- field_name: text nullable
- operator: text
- value_json: canonical JSON payload
- warning_code: MatchWarningCode nullable
- created_at: UTC ISO datetime

AssignmentRuleUnit

- id: text primary key
- rule_id: FK AssignmentRule
- unit_id: text
- unit_display_name: text nullable
- is_primary: boolean
- confidence_boost: real default 0
- created_at: UTC ISO datetime

AssignmentRuleRole

- id: text primary key
- rule_id: FK AssignmentRule
- role_type: RuleRoleType
- target_user_id: text nullable
- target_unit_id: text nullable
- source_mapping_key: text nullable
- display_name: text nullable
- required: boolean default false
- created_at: UTC ISO datetime

AssignmentRuleMatch

- id: text primary key
- action_item_id: FK action_items(id)
- document_id: FK documents(doc_id)
- rule_id: FK AssignmentRule nullable when no rule matched
- decision: MatchDecision
- score: integer
- confidence: real 0.0..1.0
- matched_condition_ids_json: canonical JSON array
- missing_required_condition_ids_json: canonical JSON array
- warnings_json: canonical JSON array of MatchWarningCode
- proposed_unit_id: text nullable
- proposed_assignee_id: text nullable
- proposed_supervisor_id: text nullable
- proposed_follower_ids_json: canonical JSON array
- source_reference: text nullable
- rule_version: integer nullable
- input_fingerprint: SHA-256 of normalized rule input context
- created_at: UTC ISO datetime

## 4. Proposed Enums

RuleStatus

- DRAFT
- ACTIVE
- INACTIVE
- ARCHIVED

ConditionType

- REQUIRED_KEYWORD
- EXCLUDED_KEYWORD
- SENDER_AGENCY
- DOCUMENT_TYPE
- ACTION_KEYWORD
- PRODUCT_KEYWORD
- PRIMARY_UNIT
- EXPECTED_OUTPUT_TYPE
- PRIORITY
- SOURCE_REFERENCE
- AI_CONFIDENCE

RuleRoleType

- LEADERSHIP
- FOLLOWER
- EXECUTOR
- SUPERVISOR

MatchDecision

- MATCHED
- POSSIBLE_MATCH
- NO_MATCH
- EXCLUDED
- NEEDS_REVIEW

MatchWarningCode

- LOW_CONFIDENCE
- MISSING_REQUIRED_KEYWORD
- EXCLUDED_KEYWORD_PRESENT
- AMBIGUOUS_UNIT
- AMBIGUOUS_ROLE
- MISSING_SOURCE_TEXT
- STALE_RULE_VERSION
- OUTSIDE_EFFECTIVE_DATE
- NO_ACTIVE_RULE

## 5. Required Rule Semantics

Effective dates:

- A rule is eligible when status is ACTIVE and today is within effective_from/effective_to if provided.
- Outside-date rules are ignored and may emit OUTSIDE_EFFECTIVE_DATE only in diagnostic mode.

Required keywords:

- REQUIRED_KEYWORD conditions must match normalized ActionItem title/description/expected_output and optionally extracted page text.
- A missing required condition makes the rule NO_MATCH, regardless of score.

Excluded keywords:

- EXCLUDED_KEYWORD exclusions run before scoring.
- Any hit makes the rule EXCLUDED and no assignment output is applied.

Sender agency:

- Match against Document.issuer and legacy issuing_agency/doc fields where present.

Document type:

- Match against Document.document_type and legacy direction.

Action and product:

- Action keywords match title/description and extracted page context.
- Product keywords match expected_output and expected_output_type.

Primary unit:

- AssignmentRuleUnit provides proposed_unit_id.
- If multiple primary units match at same score, decision becomes NEEDS_REVIEW with AMBIGUOUS_UNIT.

Roles:

- AssignmentRuleRole emits proposed_assignee_id, proposed_supervisor_id, and follower IDs.
- UserUnitMapping can resolve source_mapping_key to target_user_id or target_unit_id.
- Ambiguous mappings become warnings and do not force APPROVED status.

Priority and minimum confidence:

- Rule priority sorts candidate rules after mandatory filters.
- minimum_confidence gates final result. Below threshold returns POSSIBLE_MATCH or NEEDS_REVIEW.

Source reference and version:

- Each rule carries source_reference and version.
- AssignmentRuleMatch stores source_reference and rule_version so review can audit why a suggestion was made.

## 6. Scoring Model

Inputs:

- Document metadata: tenant, source system/id/revision, document_type, issuer, subject, summary, dates.
- ActionItem: title, description, expected_output, expected_output_type, priority, ai_confidence, current proposed unit/person fields.
- SourceCitation and extracted_pages: page text for cited evidence and optional broader attachment context.
- UserUnitMapping: source key to target unit/user resolution.

Algorithm:

1. Build normalized RuleInputContext from Document + ActionItem + citation/extracted page snippets.
2. Select ACTIVE rules for tenant and effective date.
3. Apply exclusions. Excluded rules are diagnostic only and cannot assign.
4. Evaluate required conditions. Missing required conditions produce NO_MATCH.
5. Sum weights for optional matched conditions.
6. Add confidence boosts from unit/role resolution only when mappings are unambiguous.
7. Normalize confidence as min(1.0, base + score/max_possible_score), then cap by ActionItem.ai_confidence when present.
8. Sort candidates by decision strength, score, rule priority, version, and updated_at.
9. Emit one AssignmentRuleMatch for the top candidate plus warnings when ties or missing mappings require review.

Suggested defaults:

- REQUIRED_KEYWORD: required, weight 40
- SENDER_AGENCY: weight 20
- DOCUMENT_TYPE: weight 15
- ACTION_KEYWORD: weight 15
- PRODUCT_KEYWORD: weight 15
- EXPECTED_OUTPUT_TYPE: weight 10
- PRIORITY: weight 5
- AI_CONFIDENCE threshold: minimum_confidence default 0.65

No rule should change ActionItem.status. G05A may populate proposed assignment fields in a future implementation, but all output remains reviewable and traceable.

## 7. Persistence Design

Migration version proposal: g05_assignment_rules_schema_1.

Tables:

- assignment_rules
- assignment_rule_conditions
- assignment_rule_exclusions
- assignment_rule_units
- assignment_rule_roles
- assignment_rule_matches

Indexes and uniqueness:

- idx_assignment_rules_tenant_status on tenant_id, status
- idx_assignment_rules_effective_dates on effective_from, effective_to
- idx_assignment_conditions_rule_id on rule_id
- idx_assignment_exclusions_rule_id on rule_id
- idx_assignment_roles_rule_id on rule_id
- idx_assignment_matches_action_item_id on action_item_id
- unique assignment_rules(tenant_id, name, version)
- unique assignment_rule_matches(action_item_id, rule_id, input_fingerprint) where rule_id is not null

All SQL should be parameterized. Migration must be additive and idempotent, following G02-G04 style.

## 8. Service Design

AssignmentRuleRepository

- init_assignment_rule_schema(conn)
- save_rule(rule, conditions, exclusions, units, roles)
- list_active_rules(tenant_id, effective_date)
- record_match(match)
- list_matches(action_item_id)

AssignmentRuleService

- build_context(document_id, action_item_id)
- evaluate_action_item(action_item_id, effective_date=None)
- evaluate_rule(rule, context)
- recommend_assignment(action_item_id)

The service must be library-only in G05A. It should not call QLVB, AI providers, SharePoint, Planner, or external services.

## 9. Validation And Safety

- Dates use ISO YYYY-MM-DD and timezone-aware UTC datetimes for created/updated fields.
- Confidence is bounded 0.0..1.0.
- Rule text/value_json size should be bounded.
- Warnings and errors should reuse bounded diagnostic patterns from G04 R2.
- Matches store hashes/fingerprints, not raw large prompts or credentials.
- Source references are descriptive strings or document IDs, not bearer URLs with tokens.

## 10. G05A Test Plan

Minimum tests for the next implementation step:

1. migration creates all six tables and records g05_assignment_rules_schema_1.
2. migration is idempotent and preserves G02-G04 data.
3. active effective-date rule matches within range.
4. expired/future rule does not match.
5. required keyword missing prevents assignment.
6. excluded keyword blocks assignment.
7. sender agency condition matches Document.issuer.
8. document type condition matches Document.document_type.
9. action and product keywords contribute score.
10. primary unit is emitted from matching rule.
11. leadership/follower/executor roles are emitted.
12. ambiguous role mapping produces warning and NEEDS_REVIEW/POSSIBLE_MATCH.
13. minimum confidence threshold gates match decision.
14. source_reference and version persist on AssignmentRuleMatch.
15. no ActionItem status becomes APPROVED or sync-ready.
16. no AI, QLVB, SharePoint, Planner, real data, build, push, or remote is used.

## 11. Recommendation

Proceed to G05A schema implementation on a new branch only after this design is accepted. Keep the first implementation additive and library-only, with focused SQLite memory/tempfile tests and no runtime integration into GUI, QLVB, AI, or Planner flows.
