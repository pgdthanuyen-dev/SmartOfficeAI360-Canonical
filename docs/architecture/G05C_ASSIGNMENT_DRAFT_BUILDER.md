# G05C Assignment Draft Builder

## Goal

`g05c.builder.1` is a deterministic, library-only builder. It merges the
source-document envelope with the actual `AssignmentRecommendation` from G05A
and `PersonnelSelectionRecommendation` from G05B into exactly one
`PENDING_OFFICE_REVIEW` candidate per build request.

## Input and Output

`AssignmentDraftBuildRequest` contains bounded source and proposed-work fields,
the G05A/G05B proposals, and an optional opaque file-reference placeholder.
`AssignmentDraftCandidate` contains proposed units, selected personnel source
keys, warnings, unresolved roles, confidence, and SHA-256 fingerprints. It has
no database id, Planner id, SharePoint id, credential, raw AI response, binary,
or Base64 field.

## Validation and Warnings

Hard validation rejects missing tenant/source/revision, identity mismatch,
cross-tenant G05A context, invalid ISO dates/priority/fingerprints, over-limit
text or lists, and token, cookie, SharePoint URL, Base64, or local/UNC-path
content. It never silently truncates data.

Missing units, people, due date, deliverables, file placeholder, low confidence,
personnel conflict, and substitute suggestions produce bounded, deterministic
review warnings. Missing personnel never blocks candidate creation. A due date
before received or start date remains visible with
`INVALID_PROPOSED_DUE_DATE`; the builder does not fabricate a replacement date.

## Mapping and Determinism

G05A supplies lead/participating units, required roles, confidence, warnings,
engine version, and input fingerprint. G05B supplies selected source-person
keys, role confidence, unresolved/conflicting roles, warnings, engine version,
and input fingerprint. Alternatives are never promoted to assignments. G05B's
`SUBSTITUTE_USED` warning preserves a substitute suggestion label.

Overall confidence is the minimum available component value. Source-input and
content fingerprints use canonical JSON and SHA-256. Unit and personnel sets are
sorted and deduplicated; business-order lists (deliverables, checklist, and
milestones) retain their order.

## Not Implemented

This builder performs no database write, version allocation, idempotency
registry, state transition, audit persistence, API/UI work, Planner payload,
SharePoint operation, AI call, or network call.
