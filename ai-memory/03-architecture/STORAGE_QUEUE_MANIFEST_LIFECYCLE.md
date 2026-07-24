# Storage, queue, and manifest lifecycle

Updated: 2026-07-24

## Evidence and boundary

**CODE_FACT**: `storage.py`, `index_db.py`, `audit_queue.py`, `repair_queue_mapping.py`, and `sync_client.py`. **TEST_VERIFIED**: `test_storage_queue.py`, `test_audit_validation.py`, `test_index_db.py`, and the G02 compatibility tests. This documents local behavior; it is not evidence of a production retention policy, remote sync success, or complete recovery guarantee.

## Lifecycle

`StorageManager.write_document_outputs` writes metadata and status under a direction-specific files directory. Only records with validated attachments and a queueable status enter a ready queue. It copies validated files, derives manifest metadata, writes `manifest.json`, attempts an SQLite index upsert, then writes `.ready` as the final readiness signal; `READY.ok` is retained for compatibility.

The current manifest contract declares schema version `2.0.0`, source, direction, record identifiers, document metadata, selected main document, attachments, and bounded sync status. `get_queue_item_files` reads the flat ready layout first and supports the older nested `READY` layout as fallback. `index_db` provides a separate SQLite index; queue files and the index are separate stores.

## Trust, validation, and recovery limits

Ready queue creation requires at least one validated attachment; otherwise the record becomes an error queue item without readiness or manifest. File metadata includes size and checksum after copy. Queue audit can classify items and, when explicitly applied, quarantine invalid or suspicious queue/file directories. Repair tooling proposes or applies legacy metadata mapping changes; it is not a universal rollback service.

Writes span filesystem, JSON, and SQLite. Source writes these stages in sequence and catches index/extraction errors to avoid crashing the legacy pipeline. Therefore this code does not establish atomic commit/rollback across files, manifest, index, audit, and sync state. No retention, deletion, backup, or operator restore policy is approved in current memory.

## Data handling

Manifests can contain document metadata, filenames, checksums, and sync state; they are operational data, not AI memory. Never copy their real contents into memory, diagnostics shared outside the operator scope, or test narratives. Keep credentials, session URLs, document text, personal data, and local paths outside memory.
