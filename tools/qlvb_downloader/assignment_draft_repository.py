"""SQLite persistence for immutable G05C assignment draft snapshots."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .assignment_draft_models import AssignmentDraftCandidate, AssignmentDraftPersonnelProposal, AssignmentDraftSourceAttachment
from .domain_models import new_id, utc_now_iso
from .personnel_directory_repository import init_personnel_directory_schema


ASSIGNMENT_DRAFT_MVP_MIGRATION_VERSION = "g05c_assignment_draft_mvp_schema_1"
ASSIGNMENT_DRAFT_REVIEW_MIGRATION_VERSION = "g05c_assignment_draft_review_events_1"
ASSIGNMENT_DRAFT_HANDOFF_MIGRATION_VERSION = "g05c_assignment_draft_planner_handoff_1"
ASSIGNMENT_DRAFT_SOURCE_METADATA_MIGRATION_VERSION = "g05c_assignment_draft_source_metadata_1"
ASSIGNMENT_DRAFT_EXTENDED_SOURCE_PAYLOAD_MIGRATION_VERSION = "g05c_assignment_draft_extended_source_payload_1"
ASSIGNMENT_DRAFT_ACTIVE_CONSTRAINT_MIGRATION_VERSION = "g05c_assignment_draft_one_active_1"
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
        document_number TEXT CHECK(length(document_number) <= 500),
        subject TEXT CHECK(length(subject) <= 1000),
        issuing_agency TEXT CHECK(length(issuing_agency) <= 500),
        issued_date TEXT,
        summary TEXT CHECK(length(summary) <= 10000),
        source_attachments_json TEXT NOT NULL DEFAULT '[]' CHECK(length(source_attachments_json) <= 24000 AND json_valid(source_attachments_json)),
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
        planner_handoff_status TEXT NOT NULL DEFAULT 'NOT_SENT' CHECK(planner_handoff_status IN ('NOT_SENT', 'SENT', 'UNKNOWN', 'FAILED')),
        planner_draft_id TEXT CHECK(length(planner_draft_id) <= 200),
        planner_handoff_at TEXT CHECK(length(planner_handoff_at) <= 64),
        planner_handoff_result TEXT CHECK(length(planner_handoff_result) <= 64),
        planner_handoff_correlation_id TEXT CHECK(length(planner_handoff_correlation_id) <= 100),
        planner_handoff_error TEXT CHECK(length(planner_handoff_error) <= 500),
        is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
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
    """
    CREATE TABLE IF NOT EXISTS assignment_draft_planner_handoff_attempts (
        id TEXT PRIMARY KEY,
        draft_id TEXT NOT NULL,
        tenant_id TEXT NOT NULL CHECK(length(trim(tenant_id)) > 0 AND length(tenant_id) <= 200),
        started_at TEXT NOT NULL CHECK(length(started_at) <= 64),
        completed_at TEXT NOT NULL CHECK(length(completed_at) <= 64),
        result TEXT NOT NULL CHECK(length(result) <= 64),
        planner_draft_id TEXT CHECK(length(planner_draft_id) <= 200),
        correlation_id TEXT CHECK(length(correlation_id) <= 100),
        http_status INTEGER CHECK(http_status IS NULL OR (http_status >= 100 AND http_status <= 599)),
        duration_ms INTEGER NOT NULL CHECK(duration_ms >= 0 AND duration_ms <= 120000),
        error_code TEXT CHECK(length(error_code) <= 100),
        error_message TEXT CHECK(length(error_message) <= 500),
        idempotency_key_hash TEXT NOT NULL CHECK(length(idempotency_key_hash) = 64 AND idempotency_key_hash NOT GLOB '*[^0-9a-f]*'),
        FOREIGN KEY(draft_id) REFERENCES assignment_drafts(id) ON DELETE RESTRICT
    );
    """,
]

_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_assignment_drafts_source_version ON assignment_drafts(tenant_id, source_system, source_document_id, draft_version DESC);",
    "CREATE INDEX IF NOT EXISTS idx_assignment_drafts_source_input_fingerprint ON assignment_drafts(tenant_id, source_input_fingerprint);",
    "CREATE INDEX IF NOT EXISTS idx_assignment_drafts_content_fingerprint ON assignment_drafts(tenant_id, draft_content_fingerprint);",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_assignment_drafts_one_active ON assignment_drafts(tenant_id, source_document_id) WHERE is_active=1;",
    "CREATE INDEX IF NOT EXISTS idx_assignment_draft_personnel_draft_order ON assignment_draft_personnel(draft_id, item_order);",
    "CREATE INDEX IF NOT EXISTS idx_assignment_draft_personnel_source_key ON assignment_draft_personnel(tenant_id, personnel_source_key);",
    "CREATE INDEX IF NOT EXISTS idx_assignment_draft_review_events_current ON assignment_draft_review_events(tenant_id, draft_id, created_at DESC, id DESC);",
    "CREATE INDEX IF NOT EXISTS idx_assignment_draft_handoff_attempts_draft ON assignment_draft_planner_handoff_attempts(tenant_id, draft_id, completed_at ASC, id ASC);",
]


def init_assignment_draft_schema(conn: sqlite3.Connection) -> None:
    """Create the additive G05C-A immutable snapshot schema."""

    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    init_personnel_directory_schema(conn)
    for sql in _CREATE_TABLES_SQL:
        conn.execute(sql)
    _upgrade_handoff_columns(conn)
    _upgrade_source_metadata_columns(conn)
    _upgrade_active_draft_column(conn)
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
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
        (ASSIGNMENT_DRAFT_HANDOFF_MIGRATION_VERSION, utc_now_iso()),
    )
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
        (ASSIGNMENT_DRAFT_SOURCE_METADATA_MIGRATION_VERSION, utc_now_iso()),
    )
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
        (ASSIGNMENT_DRAFT_EXTENDED_SOURCE_PAYLOAD_MIGRATION_VERSION, utc_now_iso()),
    )
    conn.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)", (ASSIGNMENT_DRAFT_ACTIVE_CONSTRAINT_MIGRATION_VERSION, utc_now_iso()))
    conn.commit()


def _upgrade_handoff_columns(conn: sqlite3.Connection) -> None:
    """Add B8A metadata to databases created before the handoff contract."""

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(assignment_drafts)").fetchall()}
    additions = {
        "planner_handoff_status": "TEXT NOT NULL DEFAULT 'NOT_SENT'",
        "planner_draft_id": "TEXT",
        "planner_handoff_at": "TEXT",
        "planner_handoff_result": "TEXT",
        "planner_handoff_correlation_id": "TEXT",
        "planner_handoff_error": "TEXT",
    }
    for name, definition in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE assignment_drafts ADD COLUMN {name} {definition}")


def _upgrade_source_metadata_columns(conn: sqlite3.Connection) -> None:
    """Add nullable source metadata without rewriting legacy snapshots."""

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(assignment_drafts)").fetchall()}
    additions = {
        "document_number": "TEXT", "subject": "TEXT", "issuing_agency": "TEXT",
        "issued_date": "TEXT", "summary": "TEXT",
        "source_attachments_json": "TEXT NOT NULL DEFAULT '[]'",
    }
    for name, definition in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE assignment_drafts ADD COLUMN {name} {definition}")

def _upgrade_active_draft_column(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(assignment_drafts)").fetchall()}
    if "is_active" not in columns:
        conn.execute("ALTER TABLE assignment_drafts ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")


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
class StoredPlannerHandoffAttempt:
    id: str
    started_at: str
    completed_at: str
    result: str
    planner_draft_id: str | None
    correlation_id: str | None
    http_status: int | None
    duration_ms: int
    error_code: str | None
    error_message: str | None
    idempotency_key_hash: str


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
    current_status: str
    task_title: str
    task_description: str
    document_number: str | None
    subject: str | None
    issuing_agency: str | None
    issued_date: str | None
    summary: str | None
    source_attachments: tuple[AssignmentDraftSourceAttachment, ...]
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
    planner_handoff_status: str
    planner_draft_id: str | None
    planner_handoff_at: str | None
    planner_handoff_result: str | None
    planner_handoff_correlation_id: str | None
    planner_handoff_error: str | None
    planner_handoff_attempts: tuple[StoredPlannerHandoffAttempt, ...]


@dataclass(frozen=True)
class PlannerHandoffAttempt:
    started_at: str
    completed_at: str
    result: str
    planner_draft_id: str | None
    correlation_id: str | None
    http_status: int | None
    duration_ms: int
    error_code: str | None
    error_message: str | None
    idempotency_key_hash: str


class PlannerHandoffPersistenceConflict(ValueError):
    pass


class AssignmentDraftProjectionError(ValueError):
    """A persisted draft cannot safely be used for a handoff projection."""


class AssignmentDraftRepository:
    """Append-only storage and tenant-scoped reads for G05C-C."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON;")

    def save_draft_candidate(self, candidate: AssignmentDraftCandidate, *, manage_transaction: bool = True) -> StoredAssignmentDraft:
        if not isinstance(candidate, AssignmentDraftCandidate):
            raise TypeError("candidate must be an AssignmentDraftCandidate")
        if manage_transaction:
            self.connection.execute("BEGIN IMMEDIATE")
        try:
            duplicate = self._find_duplicate(candidate)
            if duplicate is not None:
                if manage_transaction:
                    self.connection.rollback()
                return duplicate
            previous = self._latest_for_source(candidate)
            if previous is not None:
                self.connection.execute("UPDATE assignment_drafts SET is_active=0 WHERE id=?", (previous.id,))
            draft_id = new_id()
            draft_version = 1 if previous is None else previous.draft_version + 1
            self._insert_draft(candidate, draft_id, draft_version, previous.id if previous else None)
            for personnel in candidate.proposed_personnel:
                self._insert_personnel(draft_id, candidate.tenant_id, personnel)
            if manage_transaction:
                self.connection.commit()
        except Exception:
            if manage_transaction:
                self.connection.rollback()
            raise
        stored = self.get_draft_by_id(candidate.tenant_id, draft_id)
        if stored is None:
            raise RuntimeError("Saved draft could not be read back.")
        return stored

    def get_active_for_document(self, tenant_id: str, source_document_id: str) -> StoredAssignmentDraft | None:
        row = self.connection.execute(
            """SELECT * FROM assignment_drafts WHERE tenant_id=? AND source_document_id=?
               AND is_active=1 ORDER BY created_at DESC, id DESC LIMIT 1""",
            (tenant_id, source_document_id),
        ).fetchone()
        return self._to_stored(row) if row else None

    def get_draft_for_projection(self, tenant_id: str, source_document_id: str, source_draft_version: int) -> StoredAssignmentDraft | None:
        """Read exactly one active draft version; never select an unconstrained latest row."""
        if not tenant_id or not source_document_id or not isinstance(source_draft_version, int):
            raise AssignmentDraftProjectionError("MALFORMED_PERSISTED_DATA")
        rows = self.connection.execute(
            """SELECT * FROM assignment_drafts WHERE tenant_id=? AND source_document_id=?
               AND draft_version=? AND is_active=1 ORDER BY id ASC""",
            (tenant_id, source_document_id, source_draft_version),
        ).fetchall()
        if len(rows) > 1:
            raise AssignmentDraftProjectionError("IRRECONCILABLE_SOURCE_CONFLICT")
        if not rows:
            return None
        try:
            stored = self._to_stored(rows[0])
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise AssignmentDraftProjectionError("MALFORMED_PERSISTED_DATA") from exc
        # ``supersedes_draft_id`` belongs to the replacement draft and points
        # backwards to its historical predecessor.  The SQL ``is_active=1``
        # predicate above is the authoritative guard that this draft has not
        # itself been superseded.
        if stored.draft_version != source_draft_version:
            raise AssignmentDraftProjectionError("SOURCE_DRAFT_NOT_ACTIVE")
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
              AND COALESCE((
                  SELECT event_type FROM assignment_draft_review_events
                  WHERE tenant_id=assignment_drafts.tenant_id AND draft_id=assignment_drafts.id
                  ORDER BY created_at DESC, id DESC LIMIT 1
              ), 'PENDING_OFFICE_REVIEW') = 'PENDING_OFFICE_REVIEW'
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (tenant_id, safe_limit),
        ).fetchall()
        return [self._to_stored(row) for row in rows]

    def record_planner_handoff_attempt(self, tenant_id: str, draft_id: str,
                                       attempt: PlannerHandoffAttempt) -> StoredAssignmentDraft:
        """Append one attempt and atomically refresh only the handoff summary."""

        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.connection.execute(
                "SELECT planner_draft_id FROM assignment_drafts WHERE id=? AND tenant_id=?", (draft_id, tenant_id)
            ).fetchone()
            if row is None:
                raise ValueError("draft is unavailable")
            existing_id = row["planner_draft_id"]
            conflict = bool(existing_id and attempt.planner_draft_id and existing_id != attempt.planner_draft_id)
            error_code = "PLANNER_DRAFT_ID_CONFLICT" if conflict else attempt.error_code
            error_message = "Planner returned a different draft id for this stored draft." if conflict else _safe_handoff_message(attempt.error_message)
            self.connection.execute(
                """INSERT INTO assignment_draft_planner_handoff_attempts
                   (id, draft_id, tenant_id, started_at, completed_at, result, planner_draft_id,
                    correlation_id, http_status, duration_ms, error_code, error_message, idempotency_key_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (new_id(), draft_id, tenant_id, attempt.started_at, attempt.completed_at, attempt.result,
                 attempt.planner_draft_id, attempt.correlation_id, attempt.http_status, attempt.duration_ms,
                 error_code, error_message, attempt.idempotency_key_hash),
            )
            if conflict:
                self.connection.execute(
                    """UPDATE assignment_drafts SET planner_handoff_result=?, planner_handoff_correlation_id=?,
                       planner_handoff_error=? WHERE id=? AND tenant_id=?""",
                    ("LOCAL_PERSISTENCE_ERROR", attempt.correlation_id, error_message, draft_id, tenant_id),
                )
                self.connection.commit()
                raise PlannerHandoffPersistenceConflict(error_message)
            status = _handoff_status(attempt.result)
            successful = status == "SENT"
            self.connection.execute(
                """UPDATE assignment_drafts SET planner_handoff_status=?,
                   planner_draft_id=COALESCE(?, planner_draft_id),
                   planner_handoff_at=CASE WHEN ? THEN ? ELSE planner_handoff_at END,
                   planner_handoff_result=?, planner_handoff_correlation_id=?, planner_handoff_error=?
                   WHERE id=? AND tenant_id=?""",
                (status, attempt.planner_draft_id, int(successful), attempt.completed_at, attempt.result,
                 attempt.correlation_id, None if successful else error_message, draft_id, tenant_id),
            )
            self.connection.commit()
        except PlannerHandoffPersistenceConflict:
            raise
        except Exception:
            self.connection.rollback()
            raise
        stored = self.get_draft_by_id(tenant_id, draft_id)
        if stored is None:
            raise RuntimeError("Persisted handoff could not be read back.")
        return stored

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
                document_number, subject, issuing_agency, issued_date, summary, source_attachments_json,
                proposed_start_date, proposed_due_date, priority, overall_confidence,
                source_input_fingerprint, draft_content_fingerprint, participating_units_json,
                deliverables_json, checklist_items_json, milestones_json, warnings_json,
                unresolved_items_json, source_engine_versions_json, source_fingerprints_json,
                supersedes_draft_id, created_at, created_by_system, schema_version, builder_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                draft_id, candidate.tenant_id, candidate.source_system, candidate.source_document_id,
                candidate.source_revision, candidate.source_identity_key, draft_version, candidate.initial_status,
                candidate.task_title, candidate.task_description, candidate.lead_unit_source_key,
                candidate.document_number, candidate.subject, candidate.issuing_agency,
                candidate.issued_date, candidate.summary, _json([asdict(item) for item in candidate.source_attachments]),
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
        status_row = self.connection.execute(
            """SELECT event_type FROM assignment_draft_review_events
               WHERE tenant_id=? AND draft_id=? ORDER BY created_at DESC, id DESC LIMIT 1""",
            (row["tenant_id"], row["id"]),
        ).fetchone()
        personnel_rows = self.connection.execute(
            """
            SELECT personnel_source_key, role_type, proposal_source, is_substitute, confidence, item_order
            FROM assignment_draft_personnel WHERE draft_id=? ORDER BY item_order ASC, id ASC
            """,
            (row["id"],),
        ).fetchall()
        attempt_rows = self.connection.execute(
            """SELECT id, started_at, completed_at, result, planner_draft_id, correlation_id, http_status,
                      duration_ms, error_code, error_message, idempotency_key_hash
               FROM assignment_draft_planner_handoff_attempts
               WHERE tenant_id=? AND draft_id=? ORDER BY rowid ASC""",
            (row["tenant_id"], row["id"]),
        ).fetchall()
        return StoredAssignmentDraft(
            id=row["id"], tenant_id=row["tenant_id"], source_system=row["source_system"],
            source_document_id=row["source_document_id"], source_revision=row["source_revision"],
            source_identity_key=row["source_identity_key"], draft_version=int(row["draft_version"]),
            initial_status=row["initial_status"], current_status=status_row["event_type"] if status_row else row["initial_status"],
            task_title=row["task_title"], task_description=row["task_description"],
            document_number=row["document_number"], subject=row["subject"], issuing_agency=row["issuing_agency"],
            issued_date=row["issued_date"], summary=row["summary"],
            source_attachments=tuple(AssignmentDraftSourceAttachment(**item) for item in _read_json(row["source_attachments_json"])),
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
            planner_handoff_status=row["planner_handoff_status"], planner_draft_id=row["planner_draft_id"],
            planner_handoff_at=row["planner_handoff_at"], planner_handoff_result=row["planner_handoff_result"],
            planner_handoff_correlation_id=row["planner_handoff_correlation_id"],
            planner_handoff_error=row["planner_handoff_error"],
            planner_handoff_attempts=tuple(
                StoredPlannerHandoffAttempt(
                    id=item["id"], started_at=item["started_at"], completed_at=item["completed_at"],
                    result=item["result"], planner_draft_id=item["planner_draft_id"],
                    correlation_id=item["correlation_id"], http_status=item["http_status"],
                    duration_ms=int(item["duration_ms"]), error_code=item["error_code"],
                    error_message=item["error_message"], idempotency_key_hash=item["idempotency_key_hash"],
                )
                for item in attempt_rows
            ),
        )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _read_json(value: str) -> Any:
    return json.loads(value)


def _handoff_status(result: str) -> str:
    if result in {"CREATED", "DUPLICATE"}:
        return "SENT"
    if result == "UNKNOWN_RESULT":
        return "UNKNOWN"
    return "FAILED"


def _safe_handoff_message(value: str | None) -> str | None:
    if not value:
        return None
    message = " ".join(value.split())[:500]
    if any(marker in message.lower() for marker in ("secret", "token", "cookie", "authorization", "password")):
        return "Planner handoff failed."
    return message


def save_draft_candidate(connection: sqlite3.Connection, candidate: AssignmentDraftCandidate) -> StoredAssignmentDraft:
    return AssignmentDraftRepository(connection).save_draft_candidate(candidate)


def get_draft_by_id(connection: sqlite3.Connection, tenant_id: str, draft_id: str) -> StoredAssignmentDraft | None:
    return AssignmentDraftRepository(connection).get_draft_by_id(tenant_id, draft_id)


def list_pending_drafts(connection: sqlite3.Connection, tenant_id: str, limit: int = 50) -> list[StoredAssignmentDraft]:
    return AssignmentDraftRepository(connection).list_pending_drafts(tenant_id, limit)
