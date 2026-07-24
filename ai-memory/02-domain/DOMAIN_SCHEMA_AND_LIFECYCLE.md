# Domain schema and lifecycle

Updated: 2026-07-24

## Scope and provenance

**CODE_FACT**: `domain_models.py`, `domain_validation.py`, and `domain_repository.py`. **TEST_VERIFIED**: `tests/test_g02_domain_schema.py`. This is an in-repository contract, not production migration or live database evidence.

## Purpose, identifiers, and ownership

G02 connects `Document` to `Attachment`, `ActionItem`, `SourceCitation`, `ReviewDecision`, `SyncEvent`, and `UserUnitMapping`. A document requires tenant, source system, and source document id; entity ids default to UUIDs. The repository persists the domain id and source fields as additive columns while the legacy documents table remains keyed by `doc_id`.

Documents own source identity and ingest state; attachments and action items belong to one document; citations point to action/document and optionally attachment; review and sync records point to action items. User/unit mappings are tenant/source scoped and unresolved targets require `NEEDS_REVIEW`.

## Entity and validation contract

| Entity | Required core | Bounded/optional fields | Source validation |
| --- | --- | --- | --- |
| Document | id, tenant, source system, source document id | revision, dates, metadata, source URL, content hash | date/hash checks and unique source identity |
| Attachment | id, document id, file name | source id, type, size, hash, storage path, page count | non-negative size, positive page count, FK |
| ActionItem | id, document id, positive ordinal, title | proposal metadata, due date, confidence, state | existing document, 0..1 confidence, title for approved/sync-pending |
| SourceCitation | id, action item id, document id | attachment/page/character ranges and hashes | document/attachment ownership, range/hash checks |
| ReviewDecision | id, action id, decision | reviewer, comment, before/after JSON | reviewer identity or display name is required; append API |
| SyncEvent | id, action id, target, idempotency key, attempt, state | remote/error/hash metadata | rejected action blocked; idempotency key unique |
| UserUnitMapping | id, tenant, source system/key/display name | target references, role, effective dates | unresolved target stays `NEEDS_REVIEW` |

No standalone G02 `Page` entity exists. G03 owns extracted pages; G02 citations only store optional page/character ranges and hashes.

## Lifecycle, serialization, and legacy data

Document ingest states are `NEW`, `INGESTED`, `EXTRACTED`, `AI_ANALYZED`, and `ERROR`. Attachment status preserves the legacy discovered/download/raw/validated/invalid/failure vocabulary. Action items begin `PROPOSED`; the explicit transition check only requires `APPROVED` before `SYNC_PENDING`, not a complete workflow machine.

`DomainModel.to_dict` and `from_dict` serialize/coerce known dataclass fields. Canonical sorted JSON supports stable hashes; tests cover reordered-data stability and changed-content hashes. G02 maps compatibility fields such as direction, document number/date, issuer, title, status, and source URL into additive legacy columns.

The separate queue manifest is schema `2.0.0`. Tests show that its legacy shape remains readable and that a validated legacy record writes a ready manifest. Queue manifests are not G02 entities.

## Memory exclusions

Do not record document identifiers, subjects, summaries, filenames, session-bearing URLs, storage paths, reviewer identities, citation text, raw payloads, credentials, cookies, or database contents.
