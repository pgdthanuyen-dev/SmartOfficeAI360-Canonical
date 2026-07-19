# SmartOfficeAI360 G05A Schema Report

Date: 2026-07-19
Repository: D:\Laptrinh\SmartOfficeAI360-Canonical
Branch: feature/g05a-assignment-rule-engine
Base commit: 66c70c56b2ab01357389b94119253a7ad52b5505
Head: e950f8e85e07568f3a5bfc49e59dc793813174b9

## Scope

G05A adds library-only assignment rule schema and persistence. It does not implement the full scoring engine, does not select specific people, does not call AI, QLVB, SharePoint, or Planner, and does not create build/runtime artifacts.

Changed files:

- docs/architecture/G05A_ASSIGNMENT_RULE_SCHEMA.md
- tests/test_g05a_assignment_rule_schema.py
- tools/qlvb_downloader/assignment_rule_models.py
- tools/qlvb_downloader/assignment_rule_repository.py
- tools/qlvb_downloader/assignment_rule_validation.py

## Domain And Schema

- ASSIGNMENT_RULE_SCHEMA_VERSION: 1.0.0
- Migration: g05a_assignment_rule_schema_1
- Runtime entrypoint: LIBRARY_ONLY through AssignmentRuleRepository initialization

Entities implemented:

- AssignmentRule
- AssignmentRuleCondition
- AssignmentRuleExclusion
- AssignmentRuleUnit
- AssignmentRuleRole
- AssignmentRuleMatch

Enums implemented:

- RuleStatus
- ConditionType
- ExclusionType
- RuleUnitType
- RuleRoleType
- MatchDecision
- MatchWarningCode
- MatchMode

SQLite tables created:

- assignment_rules
- assignment_rule_conditions
- assignment_rule_exclusions
- assignment_rule_units
- assignment_rule_roles
- assignment_rule_matches

Key constraints/indexes:

- UNIQUE(tenant_id, rule_code, version)
- status/effective date index on assignment_rules
- rule/type indexes for child tables
- document/revision, rule_id, and input_fingerprint indexes for match history
- foreign keys from child rows to assignment_rules
- match document FK to documents(doc_id)
- match rule FK uses ON DELETE RESTRICT, preserving rule rows with match history

## Repository

Implemented operations:

- create_rule(...)
- get_rule(...)
- list_rules(...)
- update_rule(...)
- supersede_rule(...)
- add_condition(...)
- add_exclusion(...)
- add_unit(...)
- add_role(...)
- get_rule_bundle(...)
- list_active_rules(as_of_date, tenant_id)
- append_match(...)
- list_matches_for_document(...)

Repository behavior:

- create_rule writes rule and children in one transaction.
- update_rule uses updated_at optimistic conflict detection.
- supersede_rule updates status and preserves match history.
- append_match is insert-only.
- list_active_rules filters tenant, ACTIVE status, effective_from, and effective_to.

## Validation

Validators cover:

- non-empty rule_code and version;
- confidence range 0..100;
- effective date ordering;
- condition/exclusion/unit/role enum types through dataclass coercion;
- non-negative days, weights, penalties, and scores where applicable;
- REGEX_SAFE pattern length and compile validation;
- SHA-256 input_fingerprint;
- explanation and warnings_json bounds;
- duplicate conditions in one rule;
- duplicate lead unit;
- duplicate required role type.

## Compatibility

G04 compatibility is covered by seeding ai_proposal_batches and then initializing the G05A migration. The G04 row remains present. No G01-G04 schema drop/delete is performed by the G05A migration.

## Verification

- python -m pytest tests/test_g05a_assignment_rule_schema.py -q: 24 passed
- python -m pytest tests -q: 232 passed
- python -m compileall tools tests: PASS
- git diff --check: PASS
- working tree: clean
- remote: none

The baseline suite had 208 tests; all previous tests remain passing as part of the 232-test total.

## Commits

- 8b527ed2037561e3166258a65e562f33715d3c94 feat: add G05A assignment rule domain schema
- e950f8e85e07568f3a5bfc49e59dc793813174b9 test: validate G05A rule persistence and compatibility

## Recommendation

Continue to G05A engine implementation. The schema/persistence layer is ready for independent review.
