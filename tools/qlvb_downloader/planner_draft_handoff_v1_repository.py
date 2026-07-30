"""Immutable local SQLite history for Planner handoff envelopes."""
from __future__ import annotations

import hashlib
import json
import sqlite3

from .planner_draft_handoff_v1_envelope import build_planner_draft_handoff_envelope_v1
from .planner_draft_handoff_v1_models import CONTRACT_VERSION, SOURCE_SYSTEM, PlannerDraftHandoffEnvelopeV1, PlannerDraftHandoffProjectionV1

MIGRATION_VERSION = "g06_d0b2a_handoff_envelope_v1"
CONFLICT_ERROR_CODE = "HANDOFF_ENVELOPE_VERSION_CONFLICT"
MALFORMED_PAYLOAD_ERROR_CODE = "HANDOFF_ENVELOPE_MALFORMED_PAYLOAD"
FINGERPRINT_MISMATCH_ERROR_CODE = "HANDOFF_ENVELOPE_FINGERPRINT_MISMATCH"
IDENTITY_MISMATCH_ERROR_CODE = "HANDOFF_ENVELOPE_IDENTITY_MISMATCH"
UNSUPPORTED_CONTRACT_ERROR_CODE = "HANDOFF_ENVELOPE_UNSUPPORTED_CONTRACT"
UNSUPPORTED_SOURCE_SYSTEM_ERROR_CODE = "HANDOFF_ENVELOPE_UNSUPPORTED_SOURCE_SYSTEM"
TRANSACTION_STATE_ERROR_CODE = "HANDOFF_ENVELOPE_TRANSACTION_STATE_ERROR"
STORAGE_ERROR_CODE = "HANDOFF_ENVELOPE_STORAGE_ERROR"
DATABASE_BUSY_ERROR_CODE = "HANDOFF_ENVELOPE_DATABASE_BUSY"


class HandoffEnvelopeIntegrityError(ValueError):
    pass


def init_planner_draft_handoff_envelope_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS planner_draft_handoff_envelopes_v1 (
        envelope_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, tenant_key TEXT NOT NULL,
        source_document_id TEXT NOT NULL, source_draft_id TEXT NOT NULL, source_draft_version INTEGER NOT NULL,
        contract_version TEXT NOT NULL, source_system TEXT NOT NULL, canonical_payload_json TEXT NOT NULL,
        payload_sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
        UNIQUE(tenant_id, source_document_id, source_draft_version))""")
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
    conn.execute("INSERT OR IGNORE INTO schema_migrations VALUES (?, datetime('now'))", (MIGRATION_VERSION,))
    conn.commit()


class PlannerDraftHandoffEnvelopeRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn; self.conn.row_factory = sqlite3.Row; init_planner_draft_handoff_envelope_schema(conn)

    def create_or_get_from_projection(self, projection: PlannerDraftHandoffProjectionV1) -> tuple[PlannerDraftHandoffEnvelopeV1, bool]:
        envelope = build_planner_draft_handoff_envelope_v1(projection)
        if self.conn.in_transaction:
            raise HandoffEnvelopeIntegrityError(TRANSACTION_STATE_ERROR_CODE)
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            existing = self._find_exact(envelope)
            if existing is not None:
                self.conn.rollback()
                return self._classify_existing(existing, envelope)
            try:
                self.conn.execute("INSERT INTO planner_draft_handoff_envelopes_v1 VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
                    envelope.envelope_id, envelope.tenant_id, envelope.tenant_key, envelope.source_document_id,
                    envelope.source_draft_id, envelope.source_draft_version, envelope.contract_version, envelope.source_system,
                    envelope.canonical_payload_json, envelope.payload_sha256, envelope.created_at))
            except sqlite3.IntegrityError:
                self._rollback_if_needed()
                return self._classify_unique_race(envelope)
            self.conn.commit()
            return envelope, True
        except HandoffEnvelopeIntegrityError:
            self._rollback_if_needed()
            raise
        except sqlite3.OperationalError as exc:
            self._rollback_if_needed()
            raise HandoffEnvelopeIntegrityError(
                DATABASE_BUSY_ERROR_CODE if self._is_busy(exc) else STORAGE_ERROR_CODE
            ) from None
        except sqlite3.Error:
            self._rollback_if_needed()
            raise HandoffEnvelopeIntegrityError(STORAGE_ERROR_CODE) from None
        except Exception:
            self._rollback_if_needed()
            raise

    def _find_exact(self, envelope: PlannerDraftHandoffEnvelopeV1):
        row = self.conn.execute(
            "SELECT * FROM planner_draft_handoff_envelopes_v1 WHERE tenant_id=? AND source_document_id=? AND source_draft_version=?",
            (envelope.tenant_id, envelope.source_document_id, envelope.source_draft_version),
        ).fetchone()
        return self._read(row)

    @staticmethod
    def _classify_existing(existing: PlannerDraftHandoffEnvelopeV1, envelope: PlannerDraftHandoffEnvelopeV1):
        if existing.payload_sha256 != envelope.payload_sha256:
            raise HandoffEnvelopeIntegrityError(CONFLICT_ERROR_CODE)
        return existing, False

    def _classify_unique_race(self, envelope: PlannerDraftHandoffEnvelopeV1):
        existing = self._find_exact(envelope)
        if existing is None:
            raise HandoffEnvelopeIntegrityError(STORAGE_ERROR_CODE)
        return self._classify_existing(existing, envelope)

    def _rollback_if_needed(self) -> None:
        if self.conn.in_transaction:
            try:
                self.conn.rollback()
            except sqlite3.Error:
                pass

    @staticmethod
    def _is_busy(exc: sqlite3.OperationalError) -> bool:
        code = getattr(exc, "sqlite_errorcode", None)
        return code in {getattr(sqlite3, "SQLITE_BUSY", None), getattr(sqlite3, "SQLITE_LOCKED", None)} or any(
            marker in str(exc).casefold() for marker in ("database is locked", "database table is locked", "database is busy")
        )

    def _read(self, row):
        if row is None: return None
        try:
            payload = json.loads(row["canonical_payload_json"])
            if not isinstance(payload, dict):
                raise ValueError("payload is not an object")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise HandoffEnvelopeIntegrityError(MALFORMED_PAYLOAD_ERROR_CODE) from exc
        digest = hashlib.sha256(row["canonical_payload_json"].encode("utf-8")).hexdigest()
        if digest != row["payload_sha256"]: raise HandoffEnvelopeIntegrityError(FINGERPRINT_MISMATCH_ERROR_CODE)
        if row["contract_version"] != CONTRACT_VERSION or payload.get("contract_version") != CONTRACT_VERSION:
            raise HandoffEnvelopeIntegrityError(UNSUPPORTED_CONTRACT_ERROR_CODE)
        if row["source_system"] != SOURCE_SYSTEM or payload.get("source_system") != SOURCE_SYSTEM:
            raise HandoffEnvelopeIntegrityError(UNSUPPORTED_SOURCE_SYSTEM_ERROR_CODE)
        for name in ("tenant_id", "tenant_key", "source_document_id", "source_draft_id", "source_draft_version"):
            if name not in payload or payload[name] != row[name]:
                raise HandoffEnvelopeIntegrityError(IDENTITY_MISMATCH_ERROR_CODE)
        return PlannerDraftHandoffEnvelopeV1(**dict(row))

    def get_by_logical_key(self, tenant_id, source_document_id, source_draft_version):
        return self._read(self.conn.execute("SELECT * FROM planner_draft_handoff_envelopes_v1 WHERE tenant_id=? AND source_document_id=? AND source_draft_version=?", (tenant_id, source_document_id, source_draft_version)).fetchone())

    def list_versions_for_document(self, tenant_id, source_document_id):
        return [self._read(row) for row in self.conn.execute("SELECT * FROM planner_draft_handoff_envelopes_v1 WHERE tenant_id=? AND source_document_id=? ORDER BY source_draft_version ASC", (tenant_id, source_document_id))]
