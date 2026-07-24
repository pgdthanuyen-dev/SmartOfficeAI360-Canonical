# Schema migration and compatibility

Updated: 2026-07-24

## Evidence boundary

Implementation is **CODE_FACT** from `domain_repository.py`, `storage.py`, and `index_db.py`; tests are **TEST_VERIFIED** from `tests/test_g02_domain_schema.py`. The source supports a migration path. No live evidence establishes a production migration, commit, or database change.

## G02 flow and idempotency

`MIGRATION_VERSION` is `g02_domain_schema_1`; the model default is schema `1.0.0`. `init_domain_schema` enables foreign keys, reads existing legacy `documents` columns, adds missing additive columns, creates tables/indexes with `IF NOT EXISTS`, writes a marker through `INSERT OR IGNORE`, then commits.

It targets attachments, action items, citations, review decisions, sync events, user/unit mappings, and migration markers. Unique source identity, sync idempotency, and mapping keys are database constraints. `test_domain_migration_is_idempotent` calls initialization twice and observes one marker; `test_old_database_opens_without_losing_legacy_data` preserves a legacy row. These are in-memory SQLite tests, not production upgrade proof.

`DomainRepository` validates each entity before saving and commits each save method. Source does not expose one aggregate transaction for a document plus its attachments/actions/citations/reviews/sync events.

## Manifest/queue compatibility and failure limits

`StorageManager.get_queue_item_files` reads the current flat queue only when readiness and manifest markers exist, then accepts the older `READY` fallback. A G02 test reads a schema `2.0.0` legacy manifest and verifies a validated legacy record creates a ready manifest. This is reader/writer compatibility, not a general manifest migration engine.

Foreign keys and unique constraints reject invalid relations and duplicate sync keys. No explicit whole-migration rollback wrapper is established in source. Legacy queue writes copy files, write manifest, attempt index upsert, then write readiness in sequence; no complete cross-filesystem/database atomic transaction is established. Backup/restore, retention, production rollback, and production migration status remain gaps.
