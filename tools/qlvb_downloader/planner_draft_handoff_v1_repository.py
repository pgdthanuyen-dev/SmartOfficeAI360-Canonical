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
        existing = self.get_by_logical_key(projection.tenant_id, projection.source_document_id, projection.source_draft_version)
        if existing:
            if existing.payload_sha256 != envelope.payload_sha256:
                raise HandoffEnvelopeIntegrityError(CONFLICT_ERROR_CODE)
            return existing, False
        self.conn.execute("INSERT INTO planner_draft_handoff_envelopes_v1 VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
            envelope.envelope_id, envelope.tenant_id, envelope.tenant_key, envelope.source_document_id,
            envelope.source_draft_id, envelope.source_draft_version, envelope.contract_version, envelope.source_system,
            envelope.canonical_payload_json, envelope.payload_sha256, envelope.created_at))
        self.conn.commit()
        return envelope, True

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
