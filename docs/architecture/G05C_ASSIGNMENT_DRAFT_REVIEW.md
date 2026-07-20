# G05C Assignment Draft Office Review

Office may revise task title, description, lead unit, dates, priority,
personnel, deliverables, checklist items, and milestones. Every edit creates a
new immutable `PENDING_OFFICE_REVIEW` version and records a `SUPERSEDED` event
on the prior draft. The old snapshot is never updated.

Approval and rejection are append-only review events. Approval and rejection
require a pending draft; rejection requires a reason. Review status uses the
latest event, otherwise the draft initial status. This MVP has no API/UI,
detailed authorization, Planner handoff, SharePoint operation, or network call.
