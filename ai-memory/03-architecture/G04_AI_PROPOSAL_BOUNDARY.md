# G04 AI proposal boundary

Updated: 2026-07-25

## Evidence labels

- **CODE_FACT** is anchored to `ai_proposal_models.py`, `ai_proposal_validation.py`, `ai_proposal_service.py`, and `ai_proposal_repository.py`.
- **TEST_VERIFIED** is anchored to `tests/test_g04_ai_proposal_boundary.py`; the focused run recorded **42 passed**.
- **NOT_LIVE_VERIFIED** means source and focused tests do not establish a production provider or live AI acceptance.
- **KNOWN_GAP** identifies a boundary not established by source or focused tests.

## Ingest contract

**CODE_FACT:** `AiProposalService.ingest_ai_proposal_response` accepts a JSON envelope and validates it before proposal persistence. Strict mode rejects unknown envelope, proposal, and citation fields. Required fields, schema version, payload size, list limits, dates, enum values, confidence, and warning count/length are bounded. Empty envelopes are valid and create a completed batch without action items.

**CODE_FACT:** a valid proposal produces an `ActionItem` with status `PROPOSED`; AI output cannot set approval or synchronization statuses. Warnings are bounded by item count and string length before validation and persistence.

## Citation evidence

**CODE_FACT:** each citation attachment must belong to the requested document. Every requested page must exist in a successful G03 extraction result. Excerpts are checked exact first, then normalized whitespace, then loose normalized text; the loose path records `CITATION_FUZZY_MATCH`. Canonical recomputes source and excerpt hashes.

**TEST_VERIFIED:** focused cases cover correct and incorrect document, attachment, page, exact excerpt, normalized excerpt, and missing excerpt behavior.

## Dedupe, idempotency, and persistence

**CODE_FACT:** the stable proposal fingerprint uses document id, normalized proposal fields, and citation ranges. Exact fingerprints do not create another action item; title similarity yields a possible-duplicate warning. `external_proposal_id` is not the dedupe key.

**CODE_FACT:** `ai_proposal_batches.idempotency_key` is unique. A stable response hash returns the existing batch for the same key/body; the same key with a different body yields a bounded idempotency conflict. An SQLite unique-constraint race is reread as the winning batch.

**CODE_FACT:** action-item and citation inserts for one proposal use a SQLite transaction. Citation insert failure rolls back that proposal's action item and citations. Item/batch metadata may record rejection; a batch may intentionally contain accepted and rejected proposals. This is not whole-envelope atomicity.

**TEST_VERIFIED:** the focused suite covers exact and possible duplicates, idempotent repeat/conflict/race handling, citation rollback, bounded internal errors, and intentional partial batch success.

## Provider and safety boundary

**CODE_FACT:** G04 exposes an `AiProposalProvider` protocol and `FakeAiProposalProvider`; it has no production provider, prompt execution, remote call, or credential handling. Persistence stores response hashes and metadata, not raw response-body or token columns.

**NOT_LIVE_VERIFIED:** all focused evidence is local and fake-provider based. It does not establish provider behavior, model quality, or live AI acceptance. It does not establish a full-suite pass.

**KNOWN_GAP:** actual concurrent writers are not proven; the focused race case simulates a database integrity conflict.

**KNOWN_GAP:** no prompt-injection control is implemented for untrusted extracted content because G04 has no prompt construction/execution path.

**KNOWN_GAP:** source/test evidence does not establish a complete outbound-redaction, retention, or access-control policy for any future AI processing.
