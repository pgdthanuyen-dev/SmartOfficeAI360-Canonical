# G05C Assignment Draft Implementation Plan

## 1. Baseline

- Repository: D:\Laptrinh\SmartOfficeAI360-Canonical
- Branch: feature/g05c-assignment-draft-contract
- Main baseline: df983c111a24339470e24038f70db9d20d49e250
- Contract commit: b15fc4120b2b5c3d7a18d8a6f26cd39b77761299
- Business-review commit: 4be743fe19f91f662c02cb0dc06a4ac66122de3d
- Baseline verification: 343 tests passed, zero unexpected skips, clean worktree,
  no remote, and git diff --check passed.

This is a planning artifact only. It creates no runtime contract, migration, table,
production module, UI, or external integration.

## 2. Approved Business Decisions

- One source document produces one logical Assignment Draft; each draft can create
  at most one future Planner task.
- New drafts begin in PENDING_OFFICE_REVIEW. Office reviewers or authorized
  workflow administrators may confirm; no separate leadership state is required.
- Missing due date, personnel, substitute, deliverable, or low confidence is a
  bounded soft warning. Due dates use document, normalized extraction, then Office
  input precedence, with no fabricated default.
- Priority defaults to NORMAL. HIGH and URGENT require explicit urgency.
- Office edits remain traceable. Draft versions and audit are append-only.
- Material pre-handoff edits after approval create a pending successor version.
- All limits, withdrawal/replacement, no-action, warning, and substitute policies
  in G05C_BUSINESS_DECISIONS.md are binding.

## 3. Current Architecture Findings

### Reusable components

| Component | Actual pattern | G05C use |
| --- | --- | --- |
| Canonical JSON and SHA-256 | domain_models.canonical_json, compute_stable_hash, sha256_text | Draft fingerprint, idempotency, audit comparison. |
| Identity/time | domain_models.new_id and utc_now_iso | Immutable IDs and UTC timestamps. |
| Domain source | init_domain_schema and documents(doc_id) | Source-document FK plus tenant validation. |
| G05A output | AssignmentRecommendation and its input_fingerprint | Rule decision, unit keys, roles, warnings, confidence, engine version. |
| G05B output | PersonnelSelectionRecommendation and its input_fingerprint | Personnel proposal, alternatives, conflicts, substitute flag, confidence. |
| Migration shape | CREATE TABLE/INDEX IF NOT EXISTS, INSERT OR IGNORE schema_migrations | Additive, idempotent G05C migration. |
| Transaction shape | with self.conn in G04/G05A/G05B repositories | One owned transaction for a complete draft operation. |
| Validation style | Explicit ValueError subclasses, enum/date/SHA/bound checks | Hard errors and structured soft warnings. |

### Existing constraints

- G05A and G05B enable PRAGMA foreign_keys=ON during both initialization and
  repository construction. G05C must match this.
- G05A and G05B both declare MIGRATION_RUNTIME_ENTRYPOINT = LIBRARY_ONLY.
  index_db initializes G02 only, so G05C is also LIBRARY_ONLY initially.
- G05A fingerprints canonical normalized signals. G05B fingerprints canonical
  request input and persists append-only selection history when requested.
- G05B warns/persists bounded allowlisted diagnostics and rejects sensitive text.

### Helpers not suitable for direct reuse

- G05A default_due_days cannot set a G05C due date because approved policy forbids
  silently inventing a deadline.
- G05B display_name is presentation, not stable identity. G05C must use source
  keys and directory IDs as identity.
- G04 batch/idempotency storage is AI-response-specific and must not be reused.
- index_db upsert behavior is mutable indexing, not append-only lifecycle history.

### Dependencies to avoid

Do not import or call an AI client, QLVB downloader, SharePoint client, Planner
client, Planner identity mapping, Excel importer, or notification service. G05C
consumes caller-supplied G05A/G05B outputs and never invokes their engines.

## 4. Proposed Modules

| Module | Responsibility | Excluded responsibility |
| --- | --- | --- |
| assignment_draft_models.py | Enums, immutable records, request/result DTOs, task/unit/personnel/warning/audit/transition values. | SQL, UI, external calls. |
| assignment_draft_validation.py | Hard validation, soft-warning production, bounds, enum/date/tenant/fingerprint checks, sensitive-content guard. | Persistence and approval. |
| assignment_draft_builder.py | Deterministically merge validated G05A/G05B outputs into a candidate. | Database writes, AI, Planner, SharePoint. |
| assignment_draft_fingerprint.py | Canonical ordering, normalization, SHA-256 and idempotency projections. | Random IDs and timestamps in identity. |
| assignment_draft_repository.py | Migration, append-only persistence, read history, idempotency race handling, amendments, transitions, audit. | Rule/person selection and payload delivery. |

A later local service facade may orchestrate these modules, but no module should
combine builder, validation, SQL, and workflow in one large file.

## 5. G05C-A Schema and Migration Plan

Use an additive migration version such as g05c_assignment_draft_schema_1.
Its initializer sets row_factory, turns on foreign keys, calls
init_personnel_directory_schema, creates tables/indexes with IF NOT EXISTS,
records schema_migrations with INSERT OR IGNORE, then commits. Its runtime
entrypoint remains LIBRARY_ONLY.

### Storage decision

Use normalized parent/child rows, not an unbounded opaque JSON blob. Review needs
queryable state, due date, priority, source identity, units, personnel, warnings,
ordering, versions, and audit. A bounded canonical projection can support
fingerprinting, but it is not authoritative storage.

### Proposed tables

| Table | Minimum purpose and columns |
| --- | --- |
| assignment_drafts | id, tenant_id, source_system, source_document_id, source_identity_key, draft_version, initial status, task fields, overall_confidence, draft_fingerprint, idempotency_key, supersedes_draft_id, created_at, created_by_system, schema_version, builder_version. |
| assignment_draft_units | id, draft_id, unit_source_key, optional unit_id, assignment_role, source, confidence, warning metadata, item_order. |
| assignment_draft_personnel | id, draft_id, personnel_source_key, optional personnel_id, role_type, source, is_substitute, confidence, selection_decision, bounded display snapshot, item_order. No Planner user ID. |
| assignment_draft_deliverables | id, draft_id, item_order, text, source, confidence. |
| assignment_draft_checklist_items | id, draft_id, item_order, text, source, confidence. |
| assignment_draft_milestones | id, draft_id, item_order, title, proposed_due_date, source, confidence. |
| assignment_draft_warnings | id, draft_id, warning_code, severity, scope, related_role, related_field, message, source_engine, suggested_review_action, item_order. |
| assignment_draft_source_links | id, draft_id, source_kind, source_reference_id, source_fingerprint, engine_version, bounded correlation reference, item_order. |
| assignment_draft_amendments | id, draft_id, field_path, bounded canonical before/after, reason, actor_reference, source, created_at. |
| assignment_draft_state_transitions | id, draft_id, from_status, to_status, actor_role, actor_reference, reason, source, created_at. |
| assignment_draft_audit | id, draft_id, action, field_name, bounded canonical before/after, actor_reference, reason, source, created_at. |

Amendment and transition tables are required additions: audit alone cannot safely
reconstruct the effective Office-reviewed projection or prove legal state history.

## 6. Constraint Plan

### Parent constraints

- Require nonblank tenant_id, source_system, source_document_id, and
  source_identity_key.
- Define identity as tenant_id plus source_system plus source_document_id.
  Validate source_identity_key as the canonical projection of those fields.
- Require draft_version >= 1, valid enum status, confidence in 0.0 through 100.0,
  SHA-256 fingerprint format, and bounded idempotency key.
- Add UNIQUE(tenant_id, source_system, source_document_id, draft_version) and
  UNIQUE(tenant_id, idempotency_key).
- Add a unique exact-replay index on tenant_id, source_identity_key, and
  draft_fingerprint where SQLite-compatible migration design permits it.
- Add a self-reference check for supersedes_draft_id and an ON DELETE RESTRICT FK.
  Repository validation additionally verifies tenant/source identity and predecessor
  version because SQLite cannot express that full cross-row rule alone.
- Reference documents(doc_id) and verify the document tenant in code before insert.

### Child, transition, and audit constraints

- Child FKs use ON DELETE RESTRICT; history is never cascade-deleted.
- Item order is nonnegative and unique per draft/collection.
- Unit/personnel role and decision values use G05A/G05B-compatible enums.
  Optional directory IDs are tenant-verified and FK constrained when present.
- Warning code, severity, scope, source, and suggested action are bounded allowlists.
- State transitions have valid source/destination values and no self-transition.
- SQLite triggers abort UPDATE and DELETE on audit, transition, amendment, and
  immutable child rows. Repository exposes no history update/delete method.

### Indexes

- Draft lookup: tenant_id, source_identity_key, draft_version DESC.
- Idempotency/fingerprint lookup: tenant_id plus idempotency_key/fingerprint.
- State history: draft_id, created_at, id.
- Child rows: draft_id, item_order. Warning code and source-link fields receive
  dedicated lookup indexes.

## 7. State-Transition Plan

The parent stores immutable initial PENDING_OFFICE_REVIEW. Effective status is the
latest append-only transition, or initial status when none exists.

| From | To | Actor and reason | Validation/audit | New version |
| --- | --- | --- | --- | --- |
| PENDING_OFFICE_REVIEW | NEEDS_REVISION | Office reviewer; reason required | Append transition/audit. | No |
| PENDING_OFFICE_REVIEW | APPROVED_FOR_PLANNER | Office reviewer or authorized workflow administrator | Revalidate hard policy; audit confirmation. | No |
| PENDING_OFFICE_REVIEW | REJECTED | Office reviewer; NO_ACTION_REQUIRED or bounded reason | Append decision audit. | No |
| PENDING_OFFICE_REVIEW | CANCELLED | Authorized actor; withdrawal reason | Require SOURCE_DOCUMENT_WITHDRAWN when applicable. | No |
| NEEDS_REVISION | PENDING_OFFICE_REVIEW | Office reviewer; resubmission reason | Revalidate effective amended view. | No |
| NEEDS_REVISION | CANCELLED | Authorized actor; reason required | Append audit. | No |
| APPROVED_FOR_PLANNER | SUPERSEDED | Office/system after material pre-handoff change | Insert successor then append audit atomically. | Yes |
| Active state | CANCELLED | Authorized actor; policy reason | No downstream mutation. | No |

REJECTED, SUPERSEDED, and CANCELLED are terminal. APPROVED_FOR_PLANNER is terminal
for ordinary G05C review and becomes SUPERSEDED only when replaced before future
Planner handoff. No transition synchronizes Planner.

## 8. Validation Plan

### Models

Define immutable dataclasses and StrEnum values for draft status, priority, unit
assignment role, source type, warning severity/scope, review requirement, audit
action, amendment source, and transition request/result. Stable source keys and
IDs remain separate from optional display snapshots.

### Hard validation

Reject with stable structured codes for absent tenant/source identity, malformed
types/dates/enums/SHA/idempotency, cross-tenant references, mismatch of canonical
source identity, unsafe or over-limit values, sensitive content, invalid state
transition, invalid predecessor/successor, and missing required successor.

### Soft validation

Define a G05C-specific bounded allowlist, distinct from G05B internal warnings:
DUE_DATE_REVIEW_REQUIRED, INVALID_PROPOSED_DUE_DATE, LEAD_EXECUTOR_UNRESOLVED,
LEADER_UNRESOLVED, PERSONNEL_CONFLICT, UNIT_CONFLICT, PERSONNEL_UNAVAILABLE,
SUBSTITUTE_SUGGESTED, DELIVERABLE_REVIEW_REQUIRED,
FILE_REFERENCE_REVIEW_REQUIRED, LOW_CONFIDENCE, NO_ACTION_REVIEW_REQUIRED, and
DRAFT_REVIEW_OVERDUE.

Warnings are canonical, deduplicated, structured, and length-bounded. They never
persist raw exceptions, tokens, URLs, authorization headers, cookies, paths, SQL,
or tracebacks.

### Approved payload bounds

- Deliverables 20; checklist items 50; milestones 20; participating units 20;
  co-executors 30; warnings 50.
- Title 300 characters; description 10000; deliverable/checklist/milestone text
  1000 each; Office note 4000.
- G05C-B sets explicit limits for source correlation, display snapshot, audit
  before/after values, and warning diagnostics before persistence is implemented.
- Over-limit values are hard errors, never silently truncated.

## 9. Builder Plan

The pure builder pipeline is:

validate request -> normalize source identity -> validate G05A output -> validate
G05B output -> build task -> build unit proposal -> build personnel proposal ->
build deliverables/checklist/milestones -> collect soft warnings -> collect
unresolved items -> compute components -> MIN overall confidence -> canonicalize ->
fingerprint -> immutable candidate.

Rules:

- Consume caller-supplied AssignmentRecommendation and
  PersonnelSelectionRecommendation; never invoke their engines/repositories.
- Preserve G05A unit source keys and G05B personnel source keys. Missing/conflict
  produces unresolved roles/warnings, not invented personnel.
- Substitute evidence is non-blocking proposal evidence only.
- One source document remains one candidate even with many requirements; use ordered
  child items and never auto-split.
- Do not invent due dates or correct invalid proposed dates silently.
- Return no database effect, approval transition, external API call, Planner value,
  or identity mapping.

## 10. Fingerprint and Idempotency Plan

### Fingerprint

Use compute_stable_hash over stable tenant/source identity, document revision where
available, G05A/G05B fingerprints and versions, normalized task fields, source
keys, role decisions, canonical child values, warnings, and Office amendment
projection.

Exclude created_at, database IDs, unstable display names, insertion row order,
tokens, temporary URLs, binary, and external task IDs. Canonicalize semantically
unordered arrays by stable key, while preserving user-significant item_order.

### Idempotency and concurrency

- Same tenant/source identity/canonical input/idempotency key returns the existing
  immutable version with no new children, audit, or transition.
- Same key with different fingerprint is a structured conflict, not a successful
  replay, and creates nothing.
- Changed G05A/G05B fingerprint, effective Office amendment, or source revision is
  new business input and follows version policy.
- State-transition idempotency is separate from draft creation to avoid duplicate
  audit rows.
- Unique constraints are the race guard. On sqlite3.IntegrityError, re-read the
  winner in tenant scope: equal fingerprint is replay; different fingerprint is
  conflict. G05C-D/E prove this using two SQLite tempfile connections.

## 11. Versioning Plan

Initial creation is version 1. New material business input creates
max(draft_version) + 1 inside the repository-owned transaction and links
supersedes_draft_id. Historical content is never updated.

## 12. Office Override Plan

Office edits before approval append assignment_draft_amendments with field path,
canonical bounded before/after, reason, actor reference, timestamp, and
OFFICE_OVERRIDE source. The effective review view is generated proposal plus
ordered amendments, preserving the original proposal.

A material edit after approval but before future Planner handoff creates a new
pending version and supersedes the approved version atomically. Planner-side
changes are outside G05C.

## 13. Persistence Plan

AssignmentDraftRepository owns all writes. One with self.conn transaction inserts
or rolls back together:

1. parent draft;
2. units, personnel, deliverables, checklist items, milestones, warnings, and
   source links;
3. creation audit;
4. submitted amendment or state transition; and
5. successor/supersede records when creating a new version.

Validate models and cross-tenant references before first insert. Expose readonly
lookup/history plus append methods only.

## 14. Audit Plan

Audit actions include DRAFT_CREATED, OFFICE_OVERRIDE, REVIEW_REQUESTED,
APPROVED_FOR_PLANNER, REJECTED, CANCELLED, SUPERSEDED, and
SOURCE_DOCUMENT_WITHDRAWN. Store bounded canonical values, actor reference,
reason, source, and timestamp only.

## 15. Security Plan

- Reject sensitive patterns in persisted explanation, warning, amendment, display,
  and audit fields before SQL execution.
- Parameterize every SQL value; table names are static code constants.
- Validate tenant ownership for document, source link, unit, personnel, and
  predecessor before FK insert.
- Persist hashes and bounded identifiers, not raw AI request/output, credentials,
  token, cookie, session, SharePoint URL, Planner user ID, or binary/file content.

## 16. Determinism Plan

- Normalize only where semantics permit; preserve Office text and ordered items.
- Sort alternatives and warnings by stable identity/code before fingerprinting.
- Deduplicate exact warnings by stable structured fields.
- Use item_order, created_at, and id as deterministic query tie-breaks.
- Fingerprints/idempotency projections never include wall-clock creation time or
  generated database ID.

## 17. Test Matrix

| Phase | Focused coverage |
| --- | --- |
| G05C-A | Additive/idempotent migration, marker, FK, unique source/version/idempotency, enum/check constraints, bounds, supersedes self guard, append-only triggers. |
| G05C-B | Valid minimum, every hard error, every soft warning, security, date/tenant/fingerprint validation, bounds, deterministic normalization. |
| G05C-C | Complete proposal, missing personnel, conflicts, substitute only, missing/invalid due date, multiple deliverables, one document/one draft, no auto split, MIN confidence, deterministic output, zero external-call proof. |
| G05C-D | Equal input/fingerprint, order independence, meaningful-order preservation, changed upstream fingerprint/checklist/amendment, replay, conflict, new version, supersedes link, two-connection race. |
| G05C-E | Persist behavior, atomic child insert, injected rollback, append-only history, old version unchanged, state matrix, invalid transition, amendment audit, sensitive-data rejection. |
| G05C-F | Full regression, compileall, diff check, boundary/security review, docs, independent review, merge/tag procedure. |

Use sqlite3 memory databases for isolated tests and a tempfile SQLite database with
two connections for races. Every connection sets sqlite3.Row and
PRAGMA foreign_keys=ON. Seed source documents through DomainRepository.save_document
to exercise real document tenant/FK behavior. Use no real data or external API.

## 18. Commit Sequence

1. feat: add G05C assignment draft schema
2. test: validate G05C assignment draft schema
3. feat: add G05C assignment draft domain validation
4. test: validate G05C assignment draft contracts
5. feat: build deterministic G05C assignment drafts
6. test: validate G05C assignment draft builder
7. feat: add G05C draft fingerprint and versioning
8. test: validate G05C idempotency and versioning
9. feat: persist G05C drafts and audit history
10. test: validate G05C draft persistence and transitions

Commit count may vary only when every commit remains focused, tested, reviewable,
and reversible. No commit may mix Planner, SharePoint, identity mapping, Excel,
or unrelated source refactoring.

## 19. Execution Gates

G05C-A -> G05C-B -> G05C-C -> G05C-D -> G05C-E -> G05C-F.

Before a successor phase, the prior phase must have focused tests, full regression,
clean worktree, clean diff check, no High/Critical finding, and no contract or
business-decision change awaiting review. A failed gate blocks forward work.

## 20. Risk Register

| Risk | Probability | Impact | Prevention | Detection | Rollback |
| --- | --- | --- | --- | --- | --- |
| Over-JSON schema | Medium | High | Normalize query/audit children. | Schema/query tests. | Revert isolated G05C migration commit before merge. |
| Over-normalized schema | Medium | Medium | Keep one parent task plus focused children. | Repository review. | Remove unused G05C-only table before merge. |
| Duplicate draft | Medium | High | Unique constraints and winner readback. | Two-connection race test. | Roll back transaction; retain winner only. |
| Unstable fingerprint | Medium | High | Canonical projection and stable keys. | Repeat/order tests. | Revert fingerprint change before merge. |
| Version overwrite | Low | High | Insert-only rows and triggers. | History tests. | Roll back operation; preserve old rows. |
| Invalid transition | Medium | High | Explicit matrix and validator. | Negative transition tests. | Reject before writes. |
| Cross-tenant leakage | Low | Critical | Tenant checks before FKs. | Cross-tenant fixtures. | Roll back transaction. |
| Sensitive audit data | Medium | Critical | Bounds, allowlists, sensitive guard. | Security negatives. | Reject persistence. |
| Warning overflow | Medium | Medium | Count/length limits and dedupe. | Boundary tests. | Reject candidate; do not truncate. |
| G05A/G05B drift | Medium | High | Typed adapters and source versions. | Compatibility tests. | Block phase pending review. |
| One document split | Low | High | Logical identity/version invariant. | Builder/version tests. | Roll back duplicate version. |
| Planner field leak | Low | High | Model/SQL boundary review. | Column/import audit. | Revert G05C-only change. |
| G05D file leak | Medium | Medium | Warning only; no file persistence. | Boundary review. | Remove field before merge. |
| Office edit loses proposal | Medium | High | Amendment overlay. | Before/after history tests. | Roll back amendment. |
| Partial transaction | Medium | High | One owned transaction. | Injected child failure. | Automatic DB rollback. |

## 21. Rollback Plan

Each phase is confined to G05C modules, focused tests, and one additive migration
version. Before merge, revert focused commits rather than changing/deleting
G02-G05B tables. Failed operations rollback through the repository transaction.
Logical withdrawal/replacement is represented by history, never destructive removal.
G05C has no Planner or SharePoint effect to undo.

## 22. Non-goals

G05C does not implement SharePoint, Planner, Planner identity mapping, Excel v1,
real QLVB collection, AI generation, notifications, auto-expiry, automatic Planner
updates, runtime reassignment, or a separate leadership workflow.

## 23. G05C/G05D/G05E/G05F/G06 Boundaries

| Boundary | Ownership |
| --- | --- |
| G05C | Local deterministic reviewed draft, provenance, versions, amendments, states, audit. |
| G05D | File/reference contract and file lifecycle; G05C emits only bounded file-review warning. |
| G05E | Future Planner review payload after APPROVED_FOR_PLANNER; no task creation in G05C. |
| G05F | Office workbench UI and interaction flow. |
| G06 | Planner/SharePoint identity mapping and external identity governance. |

## 24. Acceptance Criteria

Implementation is ready for independent review only when:

- approved business decisions are represented by models, validation, tests, and docs;
- one logical source identity has deterministic append-only versions;
- hard errors reject unsafe/cross-tenant/over-limit data and soft warnings stay
  bounded/deterministic/non-blocking where approved;
- transitions and amendments are append-only and auditable;
- fingerprint/idempotency behavior is proven under replay and two-connection races;
- persistence rolls back fully on injected child failure;
- full tests, compile, and diff check pass with zero unexpected skips; and
- no G05D/G05E/G05F/G06 or external-integration behavior enters scope.

## 25. Recommended First Implementation Step

Start G05C-A only: add assignment_draft_models.py constants required by the schema,
assignment_draft_repository.py initializer, and focused
test_g05c_assignment_draft_schema.py coverage for additive/idempotent migration,
FK, unique source/version, idempotency, bounds, and append-only protections. Do
not begin G05C-B until G05C-A passes focused tests, full regression, compile, diff
check, and review.
