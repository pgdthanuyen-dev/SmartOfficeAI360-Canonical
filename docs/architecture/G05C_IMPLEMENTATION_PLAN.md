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
| assignment_draft_repository.py | Migration, append-only persistence, read history, idempotency race handling, state events, Office override versions, audit. | Rule/person selection and payload delivery. |

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
| assignment_drafts | id, tenant_id, source_system, source_document_id, required source_document_revision, source_identity_key, draft_version, immutable initial_status, task fields, overall_confidence, source_input_fingerprint, draft_fingerprint (the draft-content fingerprint), supersedes_draft_id, created_at, created_by_system, schema_version, builder_version. |
| assignment_draft_units | id, draft_id, unit_source_key, optional unit_id, assignment_role, source, confidence, warning metadata, item_order. |
| assignment_draft_personnel | id, draft_id, personnel_source_key, optional personnel_id, role_type, source, is_substitute, confidence, selection_decision, bounded display snapshot, item_order. No Planner user ID. |
| assignment_draft_deliverables | id, draft_id, item_order, text, source, confidence. |
| assignment_draft_checklist_items | id, draft_id, item_order, text, source, confidence. |
| assignment_draft_milestones | id, draft_id, item_order, title, proposed_due_date, source, confidence. |
| assignment_draft_warnings | id, draft_id, warning_code, severity, scope, related_role, related_field, message, source_engine, suggested_review_action, item_order. |
| assignment_draft_source_references | id, draft_id, source_kind, source_reference_id, source_document_revision, source_fingerprint, engine_version, bounded correlation reference, item_order. |
| assignment_draft_state_events | id, draft_id, event_sequence, from_status, to_status, actor_role, actor_reference, reason, source, created_at. |
| assignment_draft_audit | id, draft_id, action, field_name, bounded canonical before/after, actor_reference, reason, source, created_at. |
| assignment_draft_idempotency | id, tenant_id, operation_type, operation_scope_key, request_id, request_fingerprint, result_reference_type, result_reference_id, created_at. |

Every draft and child row is an immutable snapshot. A content-changing Office
override creates a successor snapshot version; it is never an amendment overlay.
State events and audit remain append-only operational history. The idempotency
registry is separate so creation, override, and state-transition retries cannot
share one undifferentiated key.

## 6. Constraint Plan

### Parent constraints

- Require nonblank tenant_id, source_system, source_document_id,
  source_document_revision, and source_identity_key. The revision is bounded,
  persisted on every immutable version, and must match both G05A and G05B output.
- Define identity as tenant_id plus source_system plus source_document_id.
  Validate source_identity_key as the canonical projection of those fields.
- Require draft_version >= 1, valid initial-status enum, confidence in 0.0 through
  100.0, and SHA-256 source-input and draft-content fingerprint formats.
- Add UNIQUE(tenant_id, source_system, source_document_id, draft_version). The
  operation registry instead owns replay uniqueness with
  UNIQUE(tenant_id, operation_type, operation_scope_key, request_id).
- Add a self-reference check for supersedes_draft_id and an ON DELETE RESTRICT FK.
  Repository validation additionally verifies tenant/source identity and predecessor
  version because SQLite cannot express that full cross-row rule alone.
- Reference documents(doc_id) and verify the document tenant in code before insert.

### Child, transition, and audit constraints

- Parent and child snapshot FKs use ON DELETE RESTRICT; history is never
  cascade-deleted.
- Item order is nonnegative and unique per draft/collection.
- Unit/personnel role and decision values use G05A/G05B-compatible enums.
  Optional directory IDs are tenant-verified and FK constrained when present.
- Warning code, severity, scope, source, and suggested action are bounded allowlists.
- State events have valid source/destination values, no self-transition, and a
  monotonic event_sequence unique within draft_id.
- SQLite triggers abort UPDATE and DELETE on assignment_drafts and every snapshot
  child, audit, state-event, and idempotency row. Repository exposes no historical
  update/delete method.

### Indexes

- Draft lookup: tenant_id, source_identity_key, draft_version DESC.
- Idempotency lookup: tenant_id, operation_type, operation_scope_key, request_id.
- State history: draft_id, event_sequence.
- Child rows: draft_id, item_order. Warning code and source-link fields receive
  dedicated lookup indexes.

## 7. State-Transition Plan

The parent stores immutable initial PENDING_OFFICE_REVIEW. Effective status is the
latest append-only state event ordered by event_sequence, or initial status when
no event exists. A mutable current-state projection is optional optimization only;
it is rebuildable from the immutable snapshot and events and is never source of
truth.

| From | To | Actor and reason | Validation/audit | New version |
| --- | --- | --- | --- | --- |
| PENDING_OFFICE_REVIEW | NEEDS_REVISION | Office reviewer; reason required | Append state event/audit. | No |
| PENDING_OFFICE_REVIEW | APPROVED_FOR_PLANNER | Office reviewer or authorized workflow administrator | Revalidate hard policy; audit confirmation. | No |
| PENDING_OFFICE_REVIEW | REJECTED | Office reviewer; NO_ACTION_REQUIRED or bounded reason | Append state event/audit. | No |
| PENDING_OFFICE_REVIEW | CANCELLED | Authorized actor; withdrawal reason | Require SOURCE_DOCUMENT_WITHDRAWN when applicable. | No |
| NEEDS_REVISION | PENDING_OFFICE_REVIEW | Office reviewer; resubmission reason | Append state event/audit. | No |
| NEEDS_REVISION | CANCELLED | Authorized actor; reason required | Append state event/audit. | No |
| APPROVED_FOR_PLANNER | SUPERSEDED | Office/system after material pre-handoff change | Insert successor then append state event/audit atomically. | Yes |
| Active state | CANCELLED | Authorized actor; policy reason | Append state event/audit; no downstream mutation. | No |

REJECTED, SUPERSEDED, and CANCELLED are terminal. APPROVED_FOR_PLANNER is terminal
for ordinary G05C review and becomes SUPERSEDED only when replaced before future
Planner handoff. No transition synchronizes Planner.

## 8. Validation Plan

### Models

Define immutable dataclasses and StrEnum values for draft status, priority, unit
assignment role, source type, warning severity/scope, review requirement, audit
action, operation type, and state-event request/result. Stable source keys and
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

Use compute_stable_hash over stable tenant/source identity, required document
revision, G05A/G05B fingerprints and versions, normalized task fields, source
keys, role decisions, canonical child values, warnings, and valid Office override
content.

Exclude created_at, database IDs, unstable display names, insertion row order,
tokens, temporary URLs, binary, and external task IDs. Canonicalize semantically
unordered arrays by stable key, while preserving user-significant item_order.

### Idempotency and concurrency

- Same operation scope, request id, and request fingerprint returns the existing
  immutable result with no new snapshot, child, audit, or state event.
- Same operation scope/request id with a different request fingerprint is a
  structured conflict, not a successful replay, and creates nothing.
- Changed G05A/G05B fingerprint, Office override content, or source revision is
  new business input and follows version policy.
- CREATE_FROM_AI_PROPOSAL, CREATE_OFFICE_OVERRIDE_VERSION, and STATE_TRANSITION
  use separate operation types and scope keys in assignment_draft_idempotency.
- Unique constraints are the race guard. On sqlite3.IntegrityError, re-read the
  winner in tenant scope: equal fingerprint is replay; different fingerprint is
  conflict. G05C-D/E prove this using two SQLite tempfile connections.

## 11. Versioning Plan

Initial creation is version 1. Source identity is tenant_id plus source_system
plus source_document_id; version identity adds draft_version. New source content,
source revision, G05A/G05B fingerprint, content-relevant warning, or content
override creates max(draft_version) + 1 inside the repository-owned transaction.
It links supersedes_draft_id to the prior same-source version. The unique source/
version constraint is the final race guard; the allocator does not trust an
application-side max calculation alone. Historical snapshots and child rows are
never updated.

## 12. Office Override Plan

An annotation that does not change business content may append an audit row or
state event without a new version. Any Office change to task title/description,
unit, personnel, due date, priority, outputs, deliverables, checklist, or
milestone creates a new immutable snapshot version. The audit links old/new
versions with canonical bounded before/after, reason, actor reference, timestamp,
and OFFICE_OVERRIDE source, preserving the original AI proposal snapshot.

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
4. submitted state event and audit, when applicable; and
5. successor/supersede records when creating a new version.

Validate models and cross-tenant references before first insert. Expose readonly
lookup/history plus append methods only.

## 14. Audit Plan

Audit actions include DRAFT_CREATED, OFFICE_OVERRIDE, REVIEW_REQUESTED,
APPROVED_FOR_PLANNER, REJECTED, CANCELLED, SUPERSEDED, and
SOURCE_DOCUMENT_WITHDRAWN. Store bounded canonical values, actor reference,
reason, source, and timestamp only.

## 15. Security Plan

- Reject sensitive patterns in persisted explanation, warning, Office override, display,
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
| G05C-A | Additive/idempotent core snapshot migration, marker, FK, unique source/version, enum/check constraints, bounds, supersedes self guard, immutable snapshot triggers. |
| G05C-B | Valid minimum, every hard error, every soft warning, security, date/tenant/fingerprint validation, bounds, deterministic normalization. |
| G05C-C | Complete proposal, missing personnel, conflicts, substitute only, missing/invalid due date, multiple deliverables, one document/one draft, no auto split, MIN confidence, deterministic output, zero external-call proof. |
| G05C-D | Equal input/fingerprint, order independence, meaningful-order preservation, changed upstream fingerprint/checklist/override, replay, conflict, new version, supersedes link, two-connection race. |
| G05C-E | Persist behavior, atomic child insert, injected rollback, append-only history, old version unchanged, state matrix, invalid transition, override audit, sensitive-data rejection. |
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
| Office edit loses proposal | Medium | High | Immutable successor version and old/new audit link. | Before/after history tests. | Roll back override transaction. |
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
| G05C | Local deterministic reviewed draft, provenance, immutable versions, states, and audit. |
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
- state events and Office override history are append-only and auditable;
- fingerprint/idempotency behavior is proven under replay and two-connection races;
- persistence rolls back fully on injected child failure;
- full tests, compile, and diff check pass with zero unexpected skips; and
- no G05D/G05E/G05F/G06 or external-integration behavior enters scope.

## 25. Recommended First Implementation Step

Start G05C-A only: add assignment_draft_models.py constants required by the schema,
assignment_draft_repository.py initializer, and focused
test_g05c_assignment_draft_schema.py coverage for additive/idempotent core schema,
FK, source revision, unique source/version, bounds, and immutable protections. Do
not begin G05C-B until G05C-A passes focused tests, full regression, compile, diff
check, and review.


## 26. R2 Finding Closure Matrix

| Finding | Closure decision | Testable closure criterion | G05C-A block |
| --- | --- | --- | --- |
| High H1: source revision absent | Every immutable parent snapshot stores nonblank bounded source_document_revision. G05A and G05B revisions must equal it. | Insert rejects absent/mismatched revision; changed revision has distinct source-input fingerprint and creates a successor under the version policy. | Closed |
| High H2: operation idempotency absent | assignment_draft_idempotency is the single registry of operation-scoped replay claims, with operation type, nonblank scope key, request id, and request fingerprint. | Equal request returns the recorded result; same key/scope with different request fingerprint conflicts; concurrent claims have one winner. | Closed |
| Medium M1: parent immutability implicit | assignment_drafts and all snapshot child rows are database-protected from UPDATE/DELETE after insertion. Current state is derived from ordered state events. | Direct parent/child mutation is rejected; state changes append events and old snapshots remain byte-for-byte unchanged. | Closed |

## 27. Final Persistence Model

The selected model is fixed:

1. Every Assignment Draft version is an immutable snapshot.
2. Snapshot tables are assignment_drafts, assignment_draft_units,
   assignment_draft_personnel, assignment_draft_deliverables,
   assignment_draft_checklist_items, assignment_draft_milestones,
   assignment_draft_warnings, and assignment_draft_source_references.
3. assignment_draft_state_events stores append-only state history.
4. assignment_draft_audit stores append-only field/action evidence.
5. assignment_draft_idempotency stores operation-scoped replay claims.
6. No snapshot row is updated after insertion.
7. Content-changing Office override creates a new snapshot version; it never edits
   the old snapshot.
8. A pure state transition appends a state event without creating a version.
9. Current state is the event with greatest event_sequence for the version; absent
   events mean the immutable initial_status. A mutable head/cache, if added later,
   is a rebuildable projection and never a source of truth.

This model replaces all amendment-overlay interpretations in this plan.

## 28. Source and Draft Version Identity

SOURCE_IDENTITY is the tuple:

tenant_id + source_system + source_document_id

DRAFT_VERSION_IDENTITY and CANONICAL_DRAFT_IDENTITY are:

tenant_id + source_system + source_document_id + draft_version

source_document_revision is required immutable provenance for each version but is
not part of SOURCE_IDENTITY. A source revision may change while the logical source
document remains the same; that change is a version-creation input.

Required parent rules:

- UNIQUE(tenant_id, source_system, source_document_id, draft_version).
- draft_version starts at 1.
- Version allocation and parent insertion occur in the same transaction.
- On a unique race, the repository reads the winning row and classifies replay or
  conflict through the operation registry; it never trusts a pre-insert max alone.
- Version 1 has null supersedes_draft_id. Version 2 and later require a
  supersedes_draft_id unless a future documented exception is approved.
- The predecessor must be same tenant, source_system, and source_document_id; it
  cannot self-reference or point across tenant/document.
- G05A document_id/document_revision and G05B document_id/document_revision must
  equal the parent source document/revision before the snapshot is accepted.

## 29. Fingerprint Contract

Three values have distinct semantics.

| Field | Source input fingerprint | Draft content fingerprint | Idempotency key | Reason |
| --- | --- | --- | --- | --- |
| Physical storage | assignment_drafts.source_input_fingerprint | assignment_drafts.draft_fingerprint; this is the contract draft_fingerprint | assignment_draft_idempotency.operation_scope_key plus request_id | Avoid conflating content identity with request replay. |
| Source identity | Included | Included | Scope-specific only | Provenance and versioning require source identity. |
| Source document revision | Included | Included | Not required unless caller chooses it in request id | Changed revision must not replay old content. |
| G05A fingerprint/version | Included | Included | Request fingerprint only | Rule evidence affects draft content. |
| G05B fingerprint/version | Included | Included | Request fingerprint only | Personnel evidence affects draft content. |
| Task, units, personnel, deliverables, checklist, milestones | Included after canonical normalization | Included after any valid Office content override | Request fingerprint only | Business content identity. |
| Content-relevant warnings | Included | Included | Request fingerprint only | Warning change from source input creates a new version. |
| Actor, created_at, database ID, token/session, unstable display name, binary, raw AI response, chain-of-thought | Excluded | Excluded | Excluded | Non-deterministic or prohibited data. |

Both fingerprints are SHA-256 of UTF-8 canonical JSON with sorted object keys.
Normalize permitted enum/date/text fields; dedupe set-like collections; preserve
item_order for deliverables, checklist items, and milestones because it has
business meaning. The registry also stores request_fingerprint, a bounded SHA-256
projection of the specific operation request, only to compare equal versus unequal
reuse of an idempotency claim.

## 30. Operation-Scoped Idempotency Model

The registry row has tenant_id, operation_type, operation_scope_key, request_id,
request_fingerprint, result_reference_type, result_reference_id, and created_at.
operation_scope_key is a nonblank canonical text key, avoiding SQLite NULL unique
semantics. It has this unique constraint:

UNIQUE(tenant_id, operation_type, operation_scope_key, request_id)

| Operation type | Scope key | Request id | Equal replay result | Different request fingerprint |
| --- | --- | --- | --- | --- |
| CREATE_FROM_AI_PROPOSAL | canonical SOURCE_IDENTITY | external_request_id or correlation_id | Return existing draft version; no child/audit/event duplicate. | Structured idempotency conflict; create nothing. |
| CREATE_OFFICE_OVERRIDE_VERSION | parent_draft_id | override_request_id | Return successor draft version; create nothing else. | Structured idempotency conflict; create nothing. |
| STATE_TRANSITION | draft_id | transition_request_id | Return existing state event; create no duplicate event/audit. | Structured idempotency conflict; create nothing. |
| SOURCE_DOCUMENT_UPDATE | canonical SOURCE_IDENTITY | source update request/correlation id | Return existing successor for equal request. | Changed input follows version creation, never old replay. |

For every operation, the repository first reads the scoped registry claim. If
absent, it validates, inserts the claim/result within one transaction, and commits
once. On unique IntegrityError it reads the winning claim: matching request
fingerprint returns its recorded result; different fingerprint raises a structured
conflict without leaking request content. Idempotency keys, request IDs, and scope
keys are bounded and pass the same sensitive-content guard as audit text.

## 31. Version Creation Decision Matrix

| Change | New draft version | State event | Required result |
| --- | --- | --- | --- |
| Same operation replay | No | No new event | Return recorded result. |
| Source document revision/content changes | Yes | Initial PENDING event for successor; supersede predecessor when policy applies | New immutable snapshot. |
| G05A fingerprint/version changes | Yes | Initial PENDING event | New immutable snapshot. |
| G05B fingerprint/version changes | Yes | Initial PENDING event | New immutable snapshot. |
| Content-relevant warning changes from source input | Yes | Initial PENDING event | New immutable snapshot. |
| Office business-content override | Yes | Initial PENDING event; old approved version gets SUPERSEDED event when applicable | New immutable snapshot and linked audit. |
| Review annotation only | No | Optional audit only | Existing snapshot unchanged. |
| Pure legal state transition | No | One state event and one audit action | Existing snapshot unchanged. |
| Mutable projection/cache refresh | No | No event | Projection rebuild only. |
| Planner task change | No | No G05C event | Outside G05C. |

## 32. Transaction Ownership Matrix

| Operation | Single transaction owner | Atomic writes | Retry/race behavior |
| --- | --- | --- | --- |
| CREATE_FROM_AI_PROPOSAL | AssignmentDraftRepository | Idempotency claim, version allocation, parent snapshot, all children/source references, initial PENDING state event, creation audit, result reference. | Unique claim/version winner readback. |
| CREATE_OFFICE_OVERRIDE_VERSION | AssignmentDraftRepository | Idempotency claim, successor allocation, successor snapshot/children, old/new linkage audit, old SUPERSEDED event when required, successor initial PENDING event. | Equal replay returns successor; unequal claim conflicts. |
| STATE_TRANSITION | AssignmentDraftRepository | Idempotency claim, next event_sequence, state event, audit, result reference. | Equal replay returns event; unequal claim conflicts. |

No child-row commit, nested commit, partial audit, partial state change, or
out-of-transaction version allocation is permitted. A failure in any insert rolls
back the entire operation and leaves old versions unchanged.

## 33. Office Override Decision Matrix

| Office action | Creates version | History effect | State effect |
| --- | --- | --- | --- |
| Read acknowledgement, non-business note, revision request | No | Append bounded audit evidence. | Optional legal state event only. |
| Change title, description, unit, personnel, due date, priority, output, deliverable, checklist, or milestone | Yes | Preserve old AI snapshot; append old/new audit link with OFFICE_OVERRIDE. | New version starts PENDING_OFFICE_REVIEW. |
| Content change after APPROVED_FOR_PLANNER but before Planner handoff | Yes | Preserve approved version and successor relation. | Old version gets SUPERSEDED event; successor starts PENDING. |
| Change after a Planner task exists | No G05C action | Record no Planner mutation. | Outside G05C/G05E-G06 policy. |

Audit field_path is allowlisted. Before/after values are canonical and bounded.
Actor reference is a bounded internal identity, never a token/session. Audit stores
no document full text, raw AI payload, secret, cookie, local path, or temporary
SharePoint URL.

## 34. Schema Ownership Matrix

| Table | Purpose | Mutability | First phase | Owner |
| --- | --- | --- | --- | --- |
| assignment_drafts | Immutable parent snapshot, required source revision and both content provenance fingerprints. | INSERT only; trigger rejects UPDATE/DELETE. | G05C-A core schema | assignment_draft_repository.py |
| assignment_draft_units/personnel/deliverables/checklist_items/milestones/warnings/source_references | Immutable ordered snapshot children. | INSERT only; trigger rejects UPDATE/DELETE. | G05C-A core schema | assignment_draft_repository.py |
| assignment_draft_idempotency | Operation-scoped replay claim and result reference. | INSERT only; trigger rejects UPDATE/DELETE. | G05C-D schema | assignment_draft_repository.py |
| assignment_draft_state_events | Append-only legal state history and event_sequence. | INSERT only; trigger rejects UPDATE/DELETE. | G05C-E schema | assignment_draft_repository.py |
| assignment_draft_audit | Append-only action/field evidence. | INSERT only; trigger rejects UPDATE/DELETE. | G05C-E schema | assignment_draft_repository.py |
| current-state projection | Optional query optimization rebuilt from snapshots/events. | Mutable derived projection only. | Not planned in G05C-A through E unless separately approved. | Future local query layer |

G05C-A creates only the core immutable snapshot tables, constraints, indexes, and
triggers needed to prove parent/child integrity. It does not create behavior for
fingerprint calculation, version allocation, state events, audit writes, or
idempotency replay. G05C-D/E introduce their owned tables through additive
migrations after their semantics and tests are implemented.

### Detailed schema decision matrix

| Table | PK and FK | Unique/check/index | Bounded fields | Update/delete policy and phase |
| --- | --- | --- | --- | --- |
| assignment_drafts | PK id; document FK; supersedes FK to parent draft. | Unique source/version; draft_version >= 1; initial status enum; confidence and both SHA checks; source/version and fingerprint indexes. | Source identity/revision, task fields, engine versions, builder/schema version. | Trigger reject UPDATE/DELETE; G05C-A. |
| assignment_draft_units | PK id; FK draft_id; optional unit FK. | Unique draft_id/item_order; nonnegative order; assignment role enum; draft/order index. | Source key, role, source, warning metadata. | Trigger reject UPDATE/DELETE; G05C-A. |
| assignment_draft_personnel | PK id; FK draft_id; optional personnel FK. | Unique draft_id/item_order; nonnegative order; role/decision enum; draft/order index. | Source key, display snapshot, source. | Trigger reject UPDATE/DELETE; G05C-A. |
| assignment_draft_deliverables | PK id; FK draft_id. | Unique draft_id/item_order; nonnegative order; draft/order index. | Text max 1000; source. | Trigger reject UPDATE/DELETE; G05C-A. |
| assignment_draft_checklist_items | PK id; FK draft_id. | Unique draft_id/item_order; nonnegative order; draft/order index. | Text max 1000; source. | Trigger reject UPDATE/DELETE; G05C-A. |
| assignment_draft_milestones | PK id; FK draft_id. | Unique draft_id/item_order; nonnegative order; date check; draft/order index. | Title/text max 1000; source. | Trigger reject UPDATE/DELETE; G05C-A. |
| assignment_draft_warnings | PK id; FK draft_id. | Unique draft_id/item_order; nonnegative order; code/severity/scope enum; draft/code index. | Code/message/source/action and related fields. | Trigger reject UPDATE/DELETE; G05C-A. |
| assignment_draft_source_references | PK id; FK draft_id. | Unique draft_id/item_order; nonnegative order; source/fingerprint index. | Source kind/reference/revision, engine/correlation values. | Trigger reject UPDATE/DELETE; G05C-A. |
| assignment_draft_idempotency | PK id; result reference is validated by operation owner. | Unique tenant/operation_type/scope_key/request_id; request fingerprint SHA; lookup index. | Operation type/scope/request/result reference. | Trigger reject UPDATE/DELETE; G05C-D. |
| assignment_draft_state_events | PK id; FK draft_id. | Unique draft_id/event_sequence; valid transition enum; event history index. | Actor/reason/source values. | Trigger reject UPDATE/DELETE; G05C-E. |
| assignment_draft_audit | PK id; FK draft_id. | Audit lookup index; allowlisted action/field path. | Canonical before/after, actor/reason/source. | Trigger reject UPDATE/DELETE; G05C-E. |

## 35. G05C-A Dependency Map

| Component | Required for G05C-A | Provided by | Blocking | Tested by |
| --- | --- | --- | --- | --- |
| Schema migration framework | Yes | Existing G02/G05A/G05B repository pattern | Yes | First-run/idempotent migration tests. |
| Schema version constant/table names | Yes | G05C-A models constants | Yes | Required tables/version marker tests. |
| SQLite foreign-key setup | Yes | Existing repository pattern | Yes | Parent/child and tenant fixture tests. |
| Tenant/source/version identity | Yes | G05C-A schema contract | Yes | Unique tenant/source/version tests. |
| Required source revision | Yes | Parent snapshot schema | Yes | Missing/mismatch/revision-change tests. |
| Status/role/severity enum constants | Yes | G05C-A minimal contract constants | Yes | CHECK constraint tests. |
| SHA-256 format and confidence/item bounds | Yes | G05C-A constraint constants | Yes | Database constraint tests. |
| Supersedes relation | Yes | Parent schema plus repository validation contract | Yes | Self/cross-tenant/cross-document negative tests. |
| Idempotency storage | No schema creation in A; ownership fixed for D | G05C-D | No | G05C-D replay/race tests. |
| State events/audit | No schema creation in A; ownership fixed for E | G05C-E | No | G05C-E event/audit transaction tests. |

## 36. G05C-A Exact Test Gate

The focused file is tests/test_g05c_assignment_draft_schema.py. It must prove
actual database behavior, not merely inspect SQL strings:

1. additive first-run migration and idempotent second run;
2. G02/G05A/G05B tables and data remain usable;
3. required core snapshot tables and columns exist;
4. foreign keys are enabled and parent/child references are enforced;
5. child rows cannot reference another draft or tenant;
6. same source document ID is valid across tenants;
7. source identity plus version is unique and draft_version is at least 1;
8. source_document_revision is nonblank/bounded and G05A/G05B revision agreement
   is represented by the schema/contract boundary;
9. initial status, role, warning severity, confidence, SHA-256, and item-order
   constraints reject invalid values;
10. supersedes self, cross-tenant, and cross-document relations are rejected;
11. parent and child snapshot UPDATE/DELETE attempts fail;
12. no Planner identity, SharePoint identity, binary, Base64, raw AI response, or
    document-full-text storage columns exist;
13. no destructive migration occurs.

G05C-A entry requires this R2 plan approved, core ownership decided, dependency map
complete, and this exact test list accepted. G05C-A exit requires focused tests,
343 legacy tests, compile, diff check, clean worktree, no Critical/High schema
review finding, and separate schema/test commits. It contains no builder,
validation engine, fingerprint behavior, version allocator, override service,
state-transition service, or persistence orchestration.

## 37. Updated Later-Phase Test and Execution Gates

- G05C-B owns domain models, enum/DTO contracts, hard/soft validation, bounds, and
  security.
- G05C-C owns the deterministic builder and confidence/warning aggregation.
- G05C-D owns canonical fingerprints, operation-scoped idempotency behavior,
  version allocation, and two-connection race tests.
- G05C-E owns transactional snapshot persistence, state events, Office override,
  audit, and injected rollback tests.
- G05C-F owns independent audit, full regression, merge, and tag procedure.

Each phase has an entry artifact, focused tests, full regression, compile, diff
check, clean worktree, scope review, separate commit, and no unresolved
Critical/High finding. No successor starts until its predecessor has its named
artifact and independent review gate.

## 38. R2 Risk Register Update

| Risk | Prevention | Detection test | Recovery/rollback |
| --- | --- | --- | --- |
| Source/content fingerprint conflated with idempotency | Separate the three contracts in section 29. | Equal/different replay and changed-content tests. | Reject conflict; do not alter winner. |
| State transition creates unnecessary version | Decision matrix separates state events from content change. | Transition-only snapshot count test. | Roll back state transaction on failure. |
| Office override overwrites snapshot | INSERT-only snapshots and parent/child triggers. | Direct mutation rejection and old/new audit tests. | Keep old version; revert failed successor transaction. |
| Version allocation race | Unique source/version and single transaction. | Two-connection concurrent version test. | Read winning version or raise conflict. |
| Supersedes crosses tenant/document | Repository validation and constrained FK. | Cross-tenant/document negative tests. | Reject before commit. |
| Audit/state differs from snapshot transaction | One owner and operation matrices. | Injected failure tests. | Automatic rollback. |
| Projection becomes source of truth | Projection explicitly derived/rebuildable only. | Rebuild-versus-projection equality test if projection is added. | Rebuild from immutable rows/events. |
| G05C-A creates premature tables | Ownership matrix limits A to core snapshots. | Required-table scope test/review. | Revert additive G05C-A migration before merge. |
| Application-only constraint mistaken for DB constraint | Test actual inserts/updates/deletes. | Constraint behavior tests. | Tighten migration/validation before next phase. |
