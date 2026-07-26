# G06 Planner draft handoff contract v1

Updated: 2026-07-26

## Purpose and lifecycle

**APPROVED_BUSINESS_POLICY:** SmartOfficeAI360 proposes one reviewable Planner draft per tenant and source document. Planner KPI is the Office review, edit, approval, and official-task conversion boundary. SmartOfficeAI360 must not create an official task.

**CODE_FACT:** SmartOffice emits a credential-free G05C handoff payload for `POST /api/integrations/smartoffice/drafts`. The Planner receiver creates `PENDING_OFFICE_REVIEW` drafts; authenticated Office flows can edit, approve, reject, and convert only an approved draft. Sources: `assignment_draft_planner_handoff.py`, `planner_draft_handoff_client.py`, Planner `smartOfficeIntegration.ts`, `smartOfficeDrafts.ts`, and receiver/review/conversion services.

**TEST_VERIFIED:** the Planner receiver script passed with a fake store and localhost HTTP. This is not an end-to-end remote integration or production acceptance claim.

## Frozen v1 policy

**PLANNED_CONTRACT:** the v1 receiver remains `POST /api/integrations/smartoffice/drafts`. Intake returns a draft, never an official task. The required lifecycle is proposal -> `PENDING_OFFICE_REVIEW` -> Office edit -> approve or reject -> approved-only conversion.

**APPROVED_BUSINESS_POLICY:** cardinality is exactly one Planner draft for each `tenantId + sourceDocumentId`. The database must enforce that pair; idempotency alone is insufficient.

**PLANNED_CONTRACT:** calculate the stable idempotency key as SHA-256 of normalized tenant, the literal `SMARTOFFICE_AI360`, and normalized source document ID. It stays stable across retry and source-draft versions.

| Incoming condition | Required v1 result |
| --- | --- |
| No source document draft | 201; `duplicate=false`; `updated=false` |
| Same version and payload fingerprint | 200; `duplicate=true`; `updated=false` |
| Same version but different fingerprint | 409 `SOURCE_VERSION_PAYLOAD_CONFLICT` |
| Higher version while pending or rejected | 200; update the same draft; `updated=true` |
| Lower version | 409 `STALE_SOURCE_VERSION` |
| Approved or converted draft | 409 `SOURCE_DOCUMENT_ALREADY_FINALIZED` |
| Retry after uncertain network result | same request/key; no duplicate |

**KNOWN_GAP:** current Planner uniqueness is `tenantId + idempotencyKey`, not `tenantId + sourceDocumentId`; source-version update behavior is not verified by current code.

## Authentication and tenant boundary

**PLANNED_CONTRACT:** require `X-SmartOffice-Secret`, `X-SmartOffice-Issuer: smartofficeai360`, `Idempotency-Key`, and JSON content type. The server reads credentials only from its environment, allowlists the issuer, and binds the body tenant to the integration credential; it never trusts an arbitrary body tenant.

**CODE_FACT:** current Planner receiver validates `X-SmartOffice-Secret` against server configuration and rejects missing/invalid secrets. SmartOffice reads its handoff secret from environment configuration and does not serialize it into the body.

**KNOWN_GAP:** phase 1 uses a shared secret. Secret rotation, timestamp/HMAC replay protection, and credential-to-tenant binding are not verified. Idempotency reduces but does not eliminate replay risk.

## Planned request v1

**PLANNED_CONTRACT:** body fields are `contractVersion`, `tenantKey`, `sourceSystem`, `sourceDocumentId`, `sourceDraftId`, `sourceDraftVersion`, and SHA-256 `payloadFingerprint`.

- `sourceDocument`: document number, title, issuing agency, issued/received dates.
- `content`: bounded summary, required action, and deduplicated action items. Each item has source proposal ID, title, description, deliverable, and bounded citations. A citation carries attachment ID, nullable page number, short excerpt, and optional checksum.
- `assignmentProposal`: nullable lead unit/primary assignee source keys, deduplicated coordinating unit source keys, reason, confidence, source rules, manual-review flag, and review reasons.
- `schedule`: nullable due date and priority.
- `attachments`: ID, filename, safe URL, checksum, MIME type, size, and kind.
- `provenance`: source proposal IDs, contract version, generation time, and generator version.

Validation requires `sourceSystem=SMARTOFFICE_AI360`, a nonempty source document ID, positive source-draft version, valid SHA-256 payload fingerprint, no invented accounts/categories, and manual review when mappings are unresolved. It rejects raw document text, credentials, session URLs, and unnecessary personal data.

## Attachment, response, and errors

**PLANNED_CONTRACT:** accept metadata plus credential-free HTTPS safe links only. Reject session-bearing query links, local/private-network URLs outside an allowlist, `file:`, `javascript:`, `data:`, and binary upload. Planner does not download an attachment inside draft creation.

**CODE_FACT:** current Planner validation bounds payloads, rejects sensitive keys/local paths/suspicious base64, and validates safe HTTP(S) attachment URLs.

**PLANNED_CONTRACT:** success returns `success`, `draftId`, source document/version, status, `duplicate`, `updated`, contract version, and receipt time. Safe errors return `success=false`, error code, bounded message, optional field errors, retryability, and correlation ID. Minimum codes: `INVALID_PAYLOAD`, `INVALID_AUTHENTICATION`, `INVALID_ISSUER`, `TENANT_MISMATCH`, `SOURCE_VERSION_PAYLOAD_CONFLICT`, `STALE_SOURCE_VERSION`, `SOURCE_DOCUMENT_ALREADY_FINALIZED`, `PAYLOAD_TOO_LARGE`, `UNSAFE_ATTACHMENT_URL`, `INTEGRATION_UNAVAILABLE`, and `RECEIVER_FAILURE`.

## Compatibility matrix

| Contract control | SmartOffice sender now | Planner receiver now | Status |
| --- | --- | --- | --- |
| Endpoint and pending intake | Present | Present | PRESENT |
| Tenant + source-document unique | Missing | Missing | MISSING |
| Stable document idempotency key | Draft-content key | Tenant/key unique | INCOMPATIBLE |
| G05 action items and citation provenance | Missing from handoff | No matching receiver model | MISSING |
| Coordinating units | Missing from handoff | Generic participating-unit storage | PARTIAL |
| Manual review reasons | Draft warnings only | Warning storage only | PARTIAL |
| Source version update semantics | Missing | Not verified | MISSING |
| Safe attachment metadata | Present, limited fields | Present, validated | PARTIAL |
| Shared-secret rotation/replay controls | Environment secret | Shared-secret validation | PARTIAL |
| Dedicated integration audit trail | Handoff attempts | Receipt/review fields | PARTIAL |

## Implementation limits

**KNOWN_GAP:** this document freezes the approved and planned v1 contract; it does not implement the contract, create a migration, establish compatibility with a production Planner deployment, or prove live handoff success.
