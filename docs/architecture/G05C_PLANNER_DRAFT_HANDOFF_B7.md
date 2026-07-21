# B7 Planner Draft Handoff

The local SmartOffice UI supplies only a tenant-scoped `draft_id` to
`AssignmentDraftService`. The service reads the immutable G05C snapshot, maps
it to the B6 receiver contract, and makes one backend-to-backend `POST` to
`/api/integrations/smartoffice/drafts` with `X-SmartOffice-Secret`.

Runtime configuration is environment-only: `SMARTOFFICE_PLANNER_HANDOFF_ENABLED`,
`SMARTOFFICE_PLANNER_BASE_URL`, and `SMARTOFFICE_PLANNER_HANDOFF_SECRET`.
`SMARTOFFICE_PLANNER_DRAFT_URL_TEMPLATE` is optional and may contain only the
`{draft_id}` placeholder. No secret is exposed to the UI or included in logs.

The stable G05C idempotency key is sent as JSON `idempotencyKey`. A receiver
`201` is `CREATED`, while its idempotent `200` result is `DUPLICATE`. Validation
and authentication failures are explicit. Timeouts, connection failures, and
unrecognised replies are `UNKNOWN_RESULT`; the client never automatically
retries a POST. This handoff creates no official Planner task and does not add
Planner approval, callbacks, or SharePoint activity.

## B8B Source Metadata

Each immutable G05C snapshot stores the source document number or signature,
official source subject, and issuing agency. The B7 adapter sends them exactly
as `documentNumber`, `subject`, and `issuingAgency`; it never substitutes the
proposed task title, lead unit, tenant, or source identifier. The fields remain
nullable for legacy snapshots and Office edits cannot overwrite them. They are
not part of the existing B7 idempotency material, so enriching a source record
with this display metadata cannot create a second Planner draft.

## B8A Persistence

The same SQLite G05C storage records a bounded handoff summary on each stored
draft and an append-only `assignment_draft_planner_handoff_attempts` row for
every send. A successful `CREATED` or `DUPLICATE` result is returned only after
that transaction commits. The stored link never changes silently if Planner
returns a different draft id. Failed and unknown outcomes keep a previous valid
link and store only a bounded, safe message; attempts never include secrets,
headers, cookies, tokens, request bodies, or response bodies.
