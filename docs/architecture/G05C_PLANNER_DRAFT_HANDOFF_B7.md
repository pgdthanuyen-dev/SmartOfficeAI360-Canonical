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
Planner approval, callbacks, SharePoint activity, or a G05C persistence change.
