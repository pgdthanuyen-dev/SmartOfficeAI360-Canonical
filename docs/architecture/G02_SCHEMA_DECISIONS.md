# G02 Schema Decisions

## ADR-001: One Document Can Produce Many Action Items

A single official document can contain several independent responsibilities, deadlines or follow-up products. Modeling action items as children of documents lets review and sync happen per task instead of forcing all work into one coarse document-level record.

## ADR-002: AI Output Does Not Automatically Create Official Tasks

AI output is stored as a proposal. It must pass review before it becomes eligible for future sync. This reduces the risk of creating incorrect Planner KPI tasks from ambiguous or partially extracted text.

## ADR-003: Citation Is A Separate Entity

Citation has its own page/character ranges, excerpt hash and attachment relation. Keeping it separate supports multiple citations per action item and lets future OCR/extractor work improve traceability without rewriting task rows.

## ADR-004: Review History Is Append-Only

Review decisions are appended instead of overwritten. This preserves audit history and makes later approval, rejection, correction and edit-and-approve flows traceable.

## ADR-005: Sync Event Stores Hashes, Not Tokens Or Raw Bodies

Sync events capture idempotency, status, HTTP metadata and hashes of request/response content. They do not store bearer tokens or raw request/response bodies, reducing exposure if logs or databases are inspected.

## ADR-006: Manifest 2.0.0 Is Not Upgraded In G02

Manifest `2.0.0` is already used by G01 queue and sync paths. G02 adds a domain schema version (`1.0.0`) for the new model layer but keeps existing manifests backward-compatible until a future migration explicitly needs a manifest version bump.
