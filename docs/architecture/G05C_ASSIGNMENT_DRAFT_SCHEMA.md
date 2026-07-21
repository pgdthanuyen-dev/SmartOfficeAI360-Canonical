# G05C-A Assignment Draft MVP Schema

## Scope

G05C-A creates an additive, idempotent SQLite schema for immutable Assignment
Draft snapshots. It remains a library-only migration and creates no runtime
database, builder, review workflow, API, UI, Planner, or SharePoint behavior.

## Tables

assignment_drafts stores one immutable draft version. Its source identity is
tenant_id, source_system, and source_document_id; source_revision records
immutable provenance for that version. The database enforces one draft version per
source identity, positive version numbers, the mandatory initial
PENDING_OFFICE_REVIEW state, priority/confidence/fingerprint constraints, and a
non-self-referencing supersedes_draft_id.

assignment_draft_personnel stores ordered personnel proposals. It has a required
draft FK, allowed G05A role types, nonnegative order, substitute flag, and bounded
confidence. It stores only the personnel source key and no Planner, SharePoint,
email, or authentication identity.

## Bounded JSON

The parent stores canonical bounded JSON placeholders for participating units,
deliverables, checklist items, milestones, warnings, unresolved items, source
engine versions, and source fingerprints. G05C-A validates JSON syntax and length;
later G05B/C validation and builder phases own canonical-content behavior.

## Immutability and Boundaries

Each row represents a snapshot. G05C-A provides no UPDATE business behavior;
content changes are planned as successor versions in later phases. State events,
audit, and operation idempotency tables/services are not created in this MVP.

Not implemented: Assignment Draft Builder, Office Review, state transition service,
Planner, SharePoint, API, UI, identity mapping, or external integration.

## B8B Source Metadata Migration

`g05c_assignment_draft_source_metadata_1` is additive and idempotent. It adds
nullable, bounded `document_number`, `subject`, and `issuing_agency` columns to
`assignment_drafts`; it does not rewrite legacy rows or create Planner or task
identifiers. Existing rows read these values as `NULL` and remain handoff
compatible with the nullable Planner receiver fields.
