from __future__ import annotations

import hashlib
import json
import sqlite3

from .assignment_recommendation_models import AssignmentRecommendation
from .domain_models import new_id, utc_now_iso

MIGRATION_VERSION = "g05c_assignment_recommendation_1"
CONFLICT_ERROR_CODE = "ASSIGNMENT_RECOMMENDATION_IDEMPOTENCY_CONFLICT"

def init_assignment_recommendation_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("CREATE TABLE IF NOT EXISTS assignment_recommendations (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, source_document_id TEXT NOT NULL, contract_version TEXT NOT NULL, payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(tenant_id, source_document_id, contract_version))")
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
    conn.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?,?)", (MIGRATION_VERSION, utc_now_iso()))
    conn.commit()

class AssignmentRecommendationConflict(ValueError):
    error_code = CONFLICT_ERROR_CODE

class AssignmentRecommendationRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn; self.conn.row_factory = sqlite3.Row; init_assignment_recommendation_schema(conn)
    def _payload(self, value: AssignmentRecommendation) -> tuple[str, str]:
        data = {**value.__dict__, "source_proposal_ids": list(value.source_proposal_ids), "coordinating_units": list(value.coordinating_units), "source_rules": list(value.source_rules), "review_reasons": list(value.review_reasons), "action_items": list(value.action_items)}
        text = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return text, hashlib.sha256(text.encode()).hexdigest()
    def get_by_idempotency_key(self, tenant_id: str, source_document_id: str, contract_version: str):
        return self.conn.execute("SELECT * FROM assignment_recommendations WHERE tenant_id=? AND source_document_id=? AND contract_version=?", (tenant_id, source_document_id, contract_version)).fetchone()
    def get_active_for_document(self, tenant_id: str, source_document_id: str):
        return self.conn.execute("SELECT * FROM assignment_recommendations WHERE tenant_id=? AND source_document_id=? ORDER BY created_at DESC LIMIT 1", (tenant_id, source_document_id)).fetchone()
    def create_or_get(self, value: AssignmentRecommendation):
        text, digest = self._payload(value); existing = self.get_by_idempotency_key(value.tenant_id, value.source_document_id, value.contract_version)
        if existing:
            if existing["payload_sha256"] != digest: raise AssignmentRecommendationConflict(CONFLICT_ERROR_CODE)
            return existing
        try:
            self.conn.execute("INSERT INTO assignment_recommendations VALUES (?,?,?,?,?,?,?)", (new_id(), value.tenant_id, value.source_document_id, value.contract_version, text, digest, utc_now_iso()))
        except sqlite3.IntegrityError:
            return self.create_or_get(value)
        return self.get_by_idempotency_key(value.tenant_id, value.source_document_id, value.contract_version)
