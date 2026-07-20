# G05C Assignment Draft Repository

## Scope

G05C-C persists and reads immutable Assignment Draft snapshots through the
existing `assignment_drafts` and `assignment_draft_personnel` tables. It accepts
only an `AssignmentDraftCandidate` produced by the G05C builder.

## Save and Versioning

Saving a candidate writes the parent and all proposed personnel in one SQLite
transaction. The same tenant, source system, source document, source revision,
and source-input fingerprint returns the existing snapshot without adding
personnel. A changed revision or source-input fingerprint creates the next
draft version and links it to the immediately previous version through
`supersedes_draft_id`. Existing versions are never updated or deleted.

## Read

Reads are tenant-scoped. `get_draft_by_id` returns the parent together with
personnel in stable item order. `list_pending_drafts` returns only
`PENDING_OFFICE_REVIEW` snapshots for the requested tenant, newest first, with a
bounded limit.

## Not Implemented

No Office Review, update, delete, state transition, audit, API/UI, Planner,
SharePoint, AI, or network operation is included.
