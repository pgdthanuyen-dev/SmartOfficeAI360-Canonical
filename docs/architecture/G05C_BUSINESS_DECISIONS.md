# G05C Assignment Draft Business Decisions

**Decision date:** 2026-07-20
**Decision maker:** BUSINESS_OWNER
**Scope:** Assignment-draft contract only. This record does not authorize
Planner, SharePoint, AI, QLVB, or runtime personnel-selection integration.

## G05C-BD-001: Office Review Authority

- **Source question:** Which Office or leadership roles may approve for Planner?
- **Decision:** An Office reviewer or authorized workflow administrator may
  confirm a draft. The system does not replace leadership approval and has no
  mandatory leadership-approval state in G05C.
- **Reason:** Office owns the operational review before a later handoff.
- **Contract impact:** `APPROVED_FOR_PLANNER` means payload preparation is
  allowed, not that a Planner task exists.
- **State impact:** `PENDING_OFFICE_REVIEW` may transition to
  `APPROVED_FOR_PLANNER`.
- **Audit impact:** Record reviewer identity, decision, timestamp, and edit
  history.
- **Backlog:** A separate leadership-approval workflow may be added later.

## G05C-BD-002: Due Date and Priority Defaults

- **Source question:** What default deadline and priority policy applies?
- **Decision:** Due-date precedence is explicit document date, normalized
  extracted date, then Office input or adjustment. No date remains pending with
  `DUE_DATE_REVIEW_REQUIRED`; no default date is fabricated. Priority defaults
  to `NORMAL`; `HIGH` or `URGENT` needs explicit urgency.
- **Reason:** Deadlines and urgency must remain traceable to an authorized
  source or Office judgement.
- **Contract impact:** Invalid proposed dates retain their value and emit
  `INVALID_PROPOSED_DUE_DATE`; low confidence or missing personnel cannot raise
  priority.
- **State impact:** Missing dates do not block `PENDING_OFFICE_REVIEW`.
- **Audit impact:** Record Office date and priority overrides with reason.
- **Backlog:** None blocking.

## G05C-BD-003: Post-Approval Change Control

- **Source question:** Who may edit after approval?
- **Decision:** A material pre-Planner change creates a new draft version in
  `PENDING_OFFICE_REVIEW`; it never overwrites the approved history.
- **Reason:** The reviewed payload must remain reproducible.
- **Contract impact:** New versions link to the superseded version and retain
  immutable audit history.
- **State impact:** The prior approved version becomes `SUPERSEDED`.
- **Audit impact:** Record actor, reason, before/after references, and version
  linkage.
- **Backlog:** Planner-side changes after future handoff belong to later
  integration work.

## G05C-BD-004: Withdrawal, Replacement, and Expiration

- **Source question:** How are withdrawal, replacement, and draft expiry confirmed?
- **Decision:** A withdrawn source cancels an unhanded-off draft with
  `SOURCE_DOCUMENT_WITHDRAWN`. A replacement source creates a successor draft
  and supersedes the prior one. V1 has no auto-expiration; overdue review is a
  warning only.
- **Reason:** Source history must be preserved without silent lifecycle changes.
- **Contract impact:** Replacement carries predecessor and replacement-source
  references; `DRAFT_REVIEW_OVERDUE` does not change state.
- **State impact:** Withdrawal uses `CANCELLED`; replacement uses `SUPERSEDED`.
- **Audit impact:** Record source reference, lifecycle reason, and successor
  linkage.
- **Backlog:** Future downstream Planner cases require warning/audit only until
  an integration policy exists.

## G05C-BD-005: Leadership Gate Before Planner

- **Source question:** Is leadership approval mandatory before any Planner payload?
- **Decision:** No mandatory leadership gate is required in G05C. Office
  confirmation authorizes only preparation of a future Planner payload.
- **Reason:** G05C remains an internal reviewed-draft boundary.
- **Contract impact:** No Planner task identifier or sync state is introduced.
- **State impact:** `APPROVED_FOR_PLANNER` is terminal within G05C.
- **Audit impact:** Confirmation is auditable and distinguishable from future
  Planner handoff.
- **Backlog:** A separate leadership gate can be introduced by a future phase.

## G05C-BD-006: No Local Action Required

- **Source question:** Which documents must not create work for local units?
- **Decision:** A reviewed document with no local-unit task is rejected with
  `NO_ACTION_REQUIRED`; it is not cancelled and creates no Planner task.
- **Reason:** Rejection communicates a deliberate scope decision, while
  cancellation is reserved for withdrawn source work.
- **Contract impact:** The reason is a bounded audit code.
- **State impact:** Draft transitions to terminal `REJECTED`.
- **Audit impact:** Record reviewer, decision reason, and source reference.
- **Backlog:** None blocking.

## G05C-BD-007: Deliverables, Checklist, and Substitute Suggestions

- **Source question:** How are deliverables and expected outputs verified?
- **Decision:** AI proposals are editable by Office: add, edit, delete, and
  reorder deliverables, checklist items, and milestones. Missing deliverables
  emit `DELIVERABLE_REVIEW_REQUIRED` without blocking. Multiple requirements
  remain in one draft and are not auto-split. Substitute information is a
  non-blocking suggestion only.
- **Reason:** Office retains control over operational detail; G05C does not
  perform runtime reassignment.
- **Contract impact:** Missing or unavailable substitutes are warnings only;
  Planner can change assignments later.
- **State impact:** These warnings keep the draft reviewable.
- **Audit impact:** Record Office changes to proposed content and personnel.
- **Backlog:** Runtime reassignment and Planner assignment changes are later
  integration work.

## G05C-BD-008: Payload Limits

- **Source question:** What checklist/deliverable/milestone/file limits are approved?
- **Decision:** Approve hard limits: 20 deliverables, 50 checklist items, 20
  milestones, 20 participating units, 30 co-executors, 50 warnings, 300 title
  characters, 10,000 description characters, 1,000 characters per list item,
  and 4,000 Office-note characters.
- **Reason:** Bounds protect persistence, review usability, and future payload
  construction.
- **Contract impact:** Over-limit values fail clear validation; they are never
  silently truncated.
- **State impact:** Invalid payloads cannot advance for review or approval.
- **Audit impact:** Store bounded validation diagnostics only.
- **Backlog:** File-attachment policy is outside this draft contract.

## G05C-BD-009: Warning Policy and Review SLA

- **Source question:** What warning severity taxonomy and review SLA are approved?
- **Decision:** The contract uses bounded structured warning codes, messages,
  sources, and suggested actions. Exact review-SLA timing and notification
  channels are explicitly non-blocking for G05C.
- **Reason:** The contract needs deterministic diagnostics now without creating
  a notification or escalation subsystem.
- **Contract impact:** Warnings remain soft validation and do not silently alter
  state; `DRAFT_REVIEW_OVERDUE` is advisory only.
- **State impact:** A warning alone never approves, rejects, cancels, or expires
  a draft.
- **Audit impact:** Persist only bounded diagnostics and reviewer decisions.
- **Backlog:** SLA reminders and multi-channel notifications.

## Final State and Validation Policy

Final states are `PENDING_OFFICE_REVIEW`, `NEEDS_REVISION`,
`APPROVED_FOR_PLANNER`, `REJECTED`, `SUPERSEDED`, and `CANCELLED`. The approved
state is terminal in G05C and future input to G05E/G06. `REJECTED`,
`SUPERSEDED`, and `CANCELLED` are terminal in G05C. Hard validation rejects
unsafe or over-limit payloads; soft validation produces bounded warnings for
Office review. Versioning and audit records are append-only.

## Non-blocking Backlog

- Review-SLA reminders and `DRAFT_REVIEW_OVERDUE` notification timing.
- Multi-channel notifications.
- Automatic Planner updates after handoff.
- Runtime reassignment.
- A future separate leadership-approval workflow.
