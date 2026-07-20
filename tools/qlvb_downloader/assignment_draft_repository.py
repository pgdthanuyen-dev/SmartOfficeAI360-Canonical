from __future__ import annotations

import sqlite3

from .domain_models import utc_now_iso
from .personnel_directory_repository import init_personnel_directory_schema


ASSIGNMENT_DRAFT_MVP_MIGRATION_VERSION = "g05c_assignment_draft_mvp_schema_1"
MIGRATION_RUNTIME_ENTRYPOINT = "LIBRARY_ONLY"

_SHA256_CHECK = "length({field}) = 64 AND {field} NOT GLOB '*[^0-9a-f]*'"

_CREATE_TABLES_SQL = [
    f"""
    CREATE TABLE IF NOT EXISTS assignment_drafts (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL CHECK(length(trim(tenant_id)) > 0 AND length(tenant_id) <= 200),
        source_system TEXT NOT NULL CHECK(length(trim(source_system)) > 0 AND length(source_system) <= 200),
        source_document_id TEXT NOT NULL CHECK(length(trim(source_document_id)) > 0 AND length(source_document_id) <= 500),
        source_revision TEXT NOT NULL CHECK(length(trim(source_revision)) > 0 AND length(source_revision) <= 200),
        source_identity_key TEXT NOT NULL CHECK(length(trim(source_identity_key)) > 0 AND length(source_identity_key) <= 1000),
        draft_version INTEGER NOT NULL CHECK(draft_version >= 1),
        initial_status TEXT NOT NULL DEFAULT 'PENDING_OFFICE_REVIEW'
            CHECK(initial_status = 'PENDING_OFFICE_REVIEW'),
        task_title TEXT NOT NULL CHECK(length(task_title) <= 300),
        task_description TEXT NOT NULL DEFAULT '' CHECK(length(task_description) <= 10000),
        lead_unit_source_key TEXT CHECK(length(lead_unit_source_key) <= 500),
        proposed_start_date TEXT,
        proposed_due_date TEXT,
        priority TEXT NOT NULL CHECK(priority IN ('LOW', 'NORMAL', 'HIGH', 'URGENT')),
        overall_confidence REAL NOT NULL
            CHECK(typeof(overall_confidence) IN ('integer', 'real') AND overall_confidence >= 0 AND overall_confidence <= 100),
        source_input_fingerprint TEXT NOT NULL CHECK({_SHA256_CHECK.format(field='source_input_fingerprint')}),
        draft_content_fingerprint TEXT NOT NULL CHECK({_SHA256_CHECK.format(field='draft_content_fingerprint')}),
        participating_units_json TEXT NOT NULL DEFAULT '[]'
            CHECK(length(participating_units_json) <= 8000 AND json_valid(participating_units_json)),
        deliverables_json TEXT NOT NULL DEFAULT '[]'
            CHECK(length(deliverables_json) <= 24000 AND json_valid(deliverables_json)),
        checklist_items_json TEXT NOT NULL DEFAULT '[]'
            CHECK(length(checklist_items_json) <= 60000 AND json_valid(checklist_items_json)),
        milestones_json TEXT NOT NULL DEFAULT '[]'
            CHECK(length(milestones_json) <= 24000 AND json_valid(milestones_json)),
        warnings_json TEXT NOT NULL DEFAULT '[]'
            CHECK(length(warnings_json) <= 16000 AND json_valid(warnings_json)),
        unresolved_items_json TEXT NOT NULL DEFAULT '[]'
            CHECK(length(unresolved_items_json) <= 8000 AND json_valid(unresolved_items_json)),
        source_engine_versions_json TEXT NOT NULL DEFAULT '{{}}'
            CHECK(length(source_engine_versions_json) <= 4000 AND json_valid(source_engine_versions_json)),
        source_fingerprints_json TEXT NOT NULL DEFAULT '{{}}'
            CHECK(length(source_fingerprints_json) <= 4000 AND json_valid(source_fingerprints_json)),
        supersedes_draft_id TEXT,
        created_at TEXT NOT NULL CHECK(length(trim(created_at)) > 0 AND length(created_at) <= 64),
        created_by_system TEXT NOT NULL CHECK(length(trim(created_by_system)) > 0 AND length(created_by_system) <= 200),
        schema_version TEXT NOT NULL CHECK(length(trim(schema_version)) > 0 AND length(schema_version) <= 50),
        builder_version TEXT NOT NULL CHECK(length(trim(builder_version)) > 0 AND length(builder_version) <= 100),
        UNIQUE(tenant_id, source_system, source_document_id, draft_version),
        CHECK(supersedes_draft_id IS NULL OR supersedes_draft_id <> id),
        FOREIGN KEY(supersedes_draft_id) REFERENCES assignment_drafts(id) ON DELETE RESTRICT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS assignment_draft_personnel (
        id TEXT PRIMARY KEY,
        draft_id TEXT NOT NULL,
        tenant_id TEXT NOT NULL CHECK(length(trim(tenant_id)) > 0 AND length(tenant_id) <= 200),
        personnel_source_key TEXT NOT NULL
            CHECK(length(trim(personnel_source_key)) > 0 AND length(personnel_source_key) <= 500),
        role_type TEXT NOT NULL CHECK(role_type IN ('LEADER', 'MONITOR', 'LEAD_EXECUTOR', 'CO_EXECUTOR')),
        proposal_source TEXT NOT NULL CHECK(length(trim(proposal_source)) > 0 AND length(proposal_source) <= 100),
        is_substitute INTEGER NOT NULL DEFAULT 0 CHECK(is_substitute IN (0, 1)),
        confidence REAL NOT NULL
            CHECK(typeof(confidence) IN ('integer', 'real') AND confidence >= 0 AND confidence <= 100),
        item_order INTEGER NOT NULL CHECK(item_order >= 0),
        created_at TEXT NOT NULL CHECK(length(trim(created_at)) > 0 AND length(created_at) <= 64),
        UNIQUE(draft_id, item_order),
        FOREIGN KEY(draft_id) REFERENCES assignment_drafts(id) ON DELETE RESTRICT
    );
    """,
]

_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_assignment_drafts_source_version ON assignment_drafts(tenant_id, source_system, source_document_id, draft_version DESC);",
    "CREATE INDEX IF NOT EXISTS idx_assignment_drafts_source_input_fingerprint ON assignment_drafts(tenant_id, source_input_fingerprint);",
    "CREATE INDEX IF NOT EXISTS idx_assignment_drafts_content_fingerprint ON assignment_drafts(tenant_id, draft_content_fingerprint);",
    "CREATE INDEX IF NOT EXISTS idx_assignment_draft_personnel_draft_order ON assignment_draft_personnel(draft_id, item_order);",
    "CREATE INDEX IF NOT EXISTS idx_assignment_draft_personnel_source_key ON assignment_draft_personnel(tenant_id, personnel_source_key);",
]


def init_assignment_draft_schema(conn: sqlite3.Connection) -> None:
    """Create the additive G05C-A immutable snapshot schema."""

    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    init_personnel_directory_schema(conn)
    for sql in _CREATE_TABLES_SQL:
        conn.execute(sql)
    for sql in _INDEXES_SQL:
        conn.execute(sql)
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
        (ASSIGNMENT_DRAFT_MVP_MIGRATION_VERSION, utc_now_iso()),
    )
    conn.commit()
