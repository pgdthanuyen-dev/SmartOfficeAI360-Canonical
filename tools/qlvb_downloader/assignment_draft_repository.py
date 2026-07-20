"""SQLite persistence for immutable G05C assignment draft snapshots."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .assignment_draft_models import AssignmentDraftCandidate, AssignmentDraftPersonnelProposal
from .domain_models import new_id, utc_now_iso
from .personnel_directory_repository import init_personnel_directory_schema


ASSIGNMENT_DRAFT_MVP_MIGRATION_VERSION = "g05c_assignment_draft_mvp_schema_1"
ASSIGNMENT_DRAFT_REVIEW_MIGRATION_VERSION = "g05c_assignment_draft_review_events_1"
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
        initial_status TEXT NOT NULL DEFAULT 'PENDING_OFFICE_REVIEW' CHECK(initial_status = 'PENDING_OFFICE_REVIEW'),
        task_title TEXT NOT NULL CHECK(length(task_title) <= 300),
        task_description TEXT NOT NULL DEFAULT '' CHECK(length(task_description) <= 10000),
        lead_unit_source_key TEXT CHECK(length(lead_unit_source_key) <= 500),
        proposed_start_date TEXT,
        proposed_due_date TEXT,
        priority TEXT NOT NULL CHECK(priority IN ('LOW', 'NORMAL', 'HIGH', 'URGENT')),
        overall_confidence REAL NOT NULL CHECK(typeof(overall_confidence) IN ('integer', 'real') AND overall_confidence >= 0 AND overall_confidence <= 100),
        source_input_fingerprint TEXT NOT NULL CHECK({_SHA256_CHECK.format(field='source_input_fingerprint')}),
        draft_content_fingerprint TEXT NOT NULL CHECK({_SHA256_CHECK.format(field='draft_content_fingerprint')}),
        participating_units_json TEXT NOT NULL DEFAULT '[]' CHECK(length(participating_units_json) <= 8000 AND json_valid(participating_units_json)),
        deliverables_json TEXT NOT NULL DEFAULT '[]' CHECK(length(deliverables_json) <= 24000 AND json_valid(deliverables_json)),
        checklist_items_json TEXT NOT NULL DEFAULT '[]' CHECK(length(checklist_items_json) <= 60000 AND json_valid(checklist_items_json)),
        milestones_json TEXT NOT NULL DEFAULT '[]' CHECK(length(milestones_json) <= 24000 AND json_valid(milestones_json)),
        warnings_json TEXT NOT NULL DEFAULT '[]' CHECK(length(warnings_json) <= 16000 AND json_valid(warnings_json)),
        unresolved_items_json TEXT NOT NULL DEFAULT '[]' CHECK(length(unresolved_items_json) <= 8000 AND json_valid(unresolved_items_json)),
        source_engine_versions_json TEXT NOT NULL DEFAULT '{{}}' CHECK(length(source_engine_versions_json) <= 4000 AND json_valid(source_engine_versions_json)),
        source_fingerprints_json TEXT NOT NULL DEFAULT '{{}}' CHECK(length(source_fingerprints_json) <= 4000 AND json_valid(source_fingerprints_json)),
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
        personnel_source_key TEXT NOT NULL CHECK(length(trim(personnel_source_key)) > 0 AND length(personnel_source_key) <= 500),
        role_type TEXT NOT NULL CHECK(role_type IN ('LEADER', 'MONITOR', 'LEAD_EXECUTOR', 'CO_EXECUTOR')),
        proposal_source TEXT NOT NULL CHECK(length(trim(proposal_source)) > 0 AND length(proposal_source) <= 100),
        is_substitute INTEGER NOT NULL DEFAULT 0 CHECK(is_substitute IN (0, 1)),
        confidence REAL NOT NULL CHECK(typeof(confidence) IN ('integer', 'real') AND confidence >= 0 AND confidence <= 100),
        item_order INTEGER NOT NULL CHECK(item_order >= 0),
        created_at TEXT NOT NULL CHECK(length(trim(created_at)) > 0 AND length(created_at) <= 64),
        UNIQUE(draft_id, item_order),
        FOREIGN KEY(draft_id) REFERENCES assignment_drafts(id) ON DELETE RESTRICT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS assignment_draft_review_events (
        id TEXT PRIMARY KEY,
        draft_id TEXT NOT NULL,
        tenant_id TEXT NOT NULL CHECK(length(trim(tenant_id)) > 0 AND length(tenant_id) <= 200),
        event_type TEXT NOT NULL CHECK(event_type IN ('APPROVED_FOR_PLANNER', 'REJECTED', 'SUPERSEDED')),
        reviewer_reference TEXT NOT NULL CHECK(length(trim(reviewer_reference)) > 0 AND length(reviewer_reference) <= 200),
        reason TEXT CHECK(length(reason) <= 1000),
        changes_json TEXT NOT NULL DEFAULT '{}' CHECK(length(changes_json) <= 16000 AND json_valid(changes_json)),
        created_at TEXT NOT NULL CHECK(length(trim(created_at)) > 0 AND length(created_at) <= 64),
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
    "CREATE INDEX IF NOT EXISTS idx_assignment_draft_review_events_current ON assignment_draft_review_events(tenant_id, draft_id, created_at DESC, id DESC);",
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
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
        (ASSIGNMENT_DRAFT_REVIEW_MIGRATION_VERSION, utc_now_iso()),
    )
    conn.commit()


ASSIGNMENT_DRAFT_SCHEMA_VERSION = "1.0.0"
MAX_PENDING_DRAFT_LIMIT = 100


@dataclass(frozen=True)
class StoredAssignmentDraftPersonnel:
    personnel_source_key: str
    role_type: str
    proposal_source: str
    is_substitute: bool
    confidence: float
    item_order: int


@dataclass(frozen=True)
class StoredAssignmentDraft:
    id: str
    tenant_id: str
    source_system: str
    source_document_id: str
    source_revision: str
    source_identity_key: str
    draft_version: int
    initial_status: str
    task_title: str
    task_description: str
    lead_unit_source_key: str | None
    proposed_start_date: str | None
    proposed_due_date: str | None
    priority: str
    overall_confidence: float
    source_input_fingerprint: str
    draft_content_fingerprint: str
    participating_unit_source_keys: tuple[str, ...]
    deliverables: tuple[str, ...]
    checklist_items: tuple[str, ...]
    milestones: tuple[str, ...]
    warnings: tuple[dict[str, Any], ...]
    unresolved_items: tuple[str, ...]
    source_engine_versions: dict[str, str]
    source_fingerprints: dict[str, str]
    supersedes_draft_id: str | None
    builder_version: str
    personnel: tuple[StoredAssignmentDraftPersonnel, ...]


class AssignmentDraftRepository:
    """Append-only storage and tenant-scoped reads for G05C-C."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON;")

    def save_draft_candidate(self, candidate: AssignmentDraftCandidate) -> StoredAssignmentDraft:
        if not isinstance(candidate, AssignmentDraftCandidate):
            raise TypeError("candidate must be an AssignmentDraftCandidate")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            duplicate = self._find_duplicate(candidate)
            if duplicate is not None:
                self.connection.rollback()
                return duplicate
            previous = self._latest_for_source(candidate)
            draft_id = new_id()
            draft_version = 1 if previous is None else previous.draft_version + 1
            self._insert_draft(candidate, draft_id, draft_version, previous.id if previous else None)
            for personnel in candidate.proposed_personnel:
                self._insert_personnel(draft_id, candidate.tenant_id, personnel)
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        stored = self.get_draft_by_id(candidate.tenant_id, draft_id)
        if stored is None:
            raise RuntimeError("Saved draft could not be read back.")
        return stored

    def get_draft_by_id(self, tenant_id: str, draft_id: str) -> StoredAssignmentDraft | None:
        row = self.connection.execute(
            "SELECT * FROM assignment_drafts WHERE id=? AND tenant_id=?",
            (draft_id, tenant_id),
        ).fetchone()
        return self._to_stored(row) if row else None

    def list_pending_drafts(self, tenant_id: str, limit: int = 50) -> list[StoredAssignmentDraft]:
        if not isinstance(limit, int):
            raise TypeError("limit must be an integer")
        safe_limit = max(1, min(limit, MAX_PENDING_DRAFT_LIMIT))
        rows = self.connection.execute(
            """
            SELECT * FROM assignment_drafts
            WHERE tenant_id=? AND initial_status='PENDING_OFFICE_REVIEW'
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (tenant_id, safe_limit),
        ).fetchall()
        return [self._to_stored(row) for row in rows]

    def _find_duplicate(self, candidate: AssignmentDraftCandidate) -> StoredAssignmentDraft | None:
        row = self.connection.execute(
            """
            SELECT * FROM assignment_drafts
            WHERE tenant_id=? AND source_system=? AND source_document_id=?
              AND source_revision=? AND source_input_fingerprint=?
            ORDER BY draft_version DESC LIMIT 1
            """,
            (candidate.tenant_id, candidate.source_system, candidate.source_document_id,
             candidate.source_revision, candidate.source_input_fingerprint),
        ).fetchone()
        return self._to_stored(row) if row else None

    def _latest_for_source(self, candidate: AssignmentDraftCandidate) -> StoredAssignmentDraft | None:
        row = self.connection.execute(
            """
            SELECT * FROM assignment_drafts
            WHERE tenant_id=? AND source_system=? AND source_document_id=?
            ORDER BY draft_version DESC LIMIT 1
            """,
            (candidate.tenant_id, candidate.source_system, candidate.source_document_id),
        ).fetchone()
        return self._to_stored(row) if row else None

    def _insert_draft(self, candidate: AssignmentDraftCandidate, draft_id: str, draft_version: int,
                      supersedes_draft_id: str | None) -> None:
        self.connection.execute(
            """
            INSERT INTO assignment_drafts (
                id, tenant_id, source_system, source_document_id, source_revision, source_identity_key,
                draft_version, initial_status, task_title, task_description, lead_unit_source_key,
                proposed_start_date, proposed_due_date, priority, overall_confidence,
                source_input_fingerprint, draft_content_fingerprint, participating_units_json,
                deliverables_json, checklist_items_json, milestones_json, warnings_json,
                unresolved_items_json, source_engine_versions_json, source_fingerprints_json,
                supersedes_draft_id, created_at, created_by_system, schema_version, builder_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                draft_id, candidate.tenant_id, candidate.source_system, candidate.source_document_id,
                candidate.source_revision, candidate.source_identity_key, draft_version, candidate.initial_status,
                candidate.task_title, candidate.task_description, candidate.lead_unit_source_key,
                candidate.proposed_start_date, candidate.proposed_due_date, candidate.priority,
                candidate.overall_confidence, candidate.source_input_fingerprint, candidate.draft_content_fingerprint,
                _json(candidate.participating_unit_source_keys), _json(candidate.deliverables),
                _json(candidate.checklist_items), _json(candidate.milestones),
                _json([asdict(warning) for warning in candidate.warnings]), _json(candidate.unresolved_items),
                _json(dict(candidate.source_engine_versions)), _json(dict(candidate.source_fingerprints)),
                supersedes_draft_id, self._next_created_at(), "g05c.assignment_draft_repository", ASSIGNMENT_DRAFT_SCHEMA_VERSION,
                candidate.builder_version,
            ),
        )

    def _next_created_at(self) -> str:
        """Keep pending-list chronology stable when snapshots share a second."""

        now = datetime.now(UTC)
        last = self.connection.execute("SELECT max(created_at) FROM assignment_drafts").fetchone()[0]
        if last:
            previous = datetime.fromisoformat(last.replace("Z", "+00:00"))
            if now <= previous:
                now = previous + timedelta(microseconds=1)
        return now.isoformat()

    def _insert_personnel(self, draft_id: str, tenant_id: str, personnel: AssignmentDraftPersonnelProposal) -> None:
        self.connection.execute(
            """
            INSERT INTO assignment_draft_personnel (
                id, draft_id, tenant_id, personnel_source_key, role_type, proposal_source,
                is_substitute, confidence, item_order, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id(), draft_id, tenant_id, personnel.personnel_source_key, personnel.role_type,
                personnel.proposal_source, int(personnel.is_substitute), personnel.confidence,
                personnel.item_order, utc_now_iso(),
            ),
        )

    def _to_stored(self, row: sqlite3.Row) -> StoredAssignmentDraft:
        personnel_rows = self.connection.execute(
            """
            SELECT personnel_source_key, role_type, proposal_source, is_substitute, confidence, item_order
            FROM assignment_draft_personnel WHERE draft_id=? ORDER BY item_order ASC, id ASC
            """,
            (row["id"],),
        ).fetchall()
        return StoredAssignmentDraft(
            id=row["id"], tenant_id=row["tenant_id"], source_system=row["source_system"],
            source_document_id=row["source_document_id"], source_revision=row["source_revision"],
            source_identity_key=row["source_identity_key"], draft_version=int(row["draft_version"]),
            initial_status=row["initial_status"], task_title=row["task_title"], task_description=row["task_description"],
            lead_unit_source_key=row["lead_unit_source_key"], proposed_start_date=row["proposed_start_date"],
            proposed_due_date=row["proposed_due_date"], priority=row["priority"],
            overall_confidence=float(row["overall_confidence"]), source_input_fingerprint=row["source_input_fingerprint"],
            draft_content_fingerprint=row["draft_content_fingerprint"],
            participating_unit_source_keys=tuple(_read_json(row["participating_units_json"])),
            deliverables=tuple(_read_json(row["deliverables_json"])), checklist_items=tuple(_read_json(row["checklist_items_json"])),
            milestones=tuple(_read_json(row["milestones_json"])), warnings=tuple(_read_json(row["warnings_json"])),
            unresolved_items=tuple(_read_json(row["unresolved_items_json"])),
            source_engine_versions=dict(_read_json(row["source_engine_versions_json"])),
            source_fingerprints=dict(_read_json(row["source_fingerprints_json"])),
            supersedes_draft_id=row["supersedes_draft_id"], builder_version=row["builder_version"],
            personnel=tuple(
                StoredAssignmentDraftPersonnel(
                    personnel_source_key=item["personnel_source_key"], role_type=item["role_type"],
                    proposal_source=item["proposal_source"], is_substitute=bool(item["is_substitute"]),
                    confidence=float(item["confidence"]), item_order=int(item["item_order"]),
                )
                for item in personnel_rows
            ),
        )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _read_json(value: str) -> Any:
    return json.loads(value)


def save_draft_candidate(connection: sqlite3.Connection, candidate: AssignmentDraftCandidate) -> StoredAssignmentDraft:
    return AssignmentDraftRepository(connection).save_draft_candidate(candidate)


def get_draft_by_id(connection: sqlite3.Connection, tenant_id: str, draft_id: str) -> StoredAssignmentDraft | None:
    return AssignmentDraftRepository(connection).get_draft_by_id(tenant_id, draft_id)


def list_pending_drafts(connection: sqlite3.Connection, tenant_id: str, limit: int = 50) -> list[StoredAssignmentDraft]:
    return AssignmentDraftRepository(connection).list_pending_drafts(tenant_id, limit)
