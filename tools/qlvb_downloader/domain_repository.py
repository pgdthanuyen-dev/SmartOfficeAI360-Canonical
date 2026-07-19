from __future__ import annotations

import json
import sqlite3
from typing import Any

from .domain_models import (
    DOMAIN_SCHEMA_VERSION,
    ActionItem,
    Attachment,
    Document,
    ReviewDecision,
    SourceCitation,
    SyncEvent,
    UserUnitMapping,
    canonical_json,
    utc_now_iso,
)
from .domain_validation import (
    validate_action_item,
    validate_attachment,
    validate_citation,
    validate_document,
    validate_review_decision,
    validate_sync_event,
    validate_user_unit_mapping,
)


MIGRATION_VERSION = "g02_domain_schema_1"


_DOCUMENT_COLUMNS: dict[str, str] = {
    "direction": "TEXT",
    "doc_no": "TEXT",
    "doc_date": "TEXT",
    "issuing_agency": "TEXT",
    "title": "TEXT",
    "status": "TEXT",
    "source_url": "TEXT",
    "id": "TEXT",
    "tenant_id": "TEXT",
    "source_system": "TEXT",
    "source_document_id": "TEXT",
    "source_revision": "TEXT",
    "document_type": "TEXT",
    "document_number": "TEXT",
    "issued_date_domain": "TEXT",
    "received_date": "TEXT",
    "issuer": "TEXT",
    "signer": "TEXT",
    "subject": "TEXT",
    "summary_domain": "TEXT",
    "urgency": "TEXT",
    "source_url_domain": "TEXT",
    "content_sha256": "TEXT",
    "ingest_status": "TEXT",
    "created_at_utc": "TEXT",
    "updated_at_utc": "TEXT",
    "domain_schema_version": "TEXT",
}


_CREATE_TABLES_SQL = [
    """
    CREATE TABLE IF NOT EXISTS attachments (
        id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL,
        source_attachment_id TEXT,
        file_name TEXT NOT NULL,
        file_extension TEXT,
        mime_type TEXT,
        size_bytes INTEGER,
        sha256 TEXT,
        storage_path TEXT,
        validation_status TEXT NOT NULL,
        validation_error TEXT,
        download_source TEXT,
        page_count INTEGER,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(document_id) REFERENCES documents(doc_id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS action_items (
        id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL,
        ordinal INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        proposed_unit_id TEXT,
        proposed_assignee_id TEXT,
        proposed_supervisor_id TEXT,
        proposed_due_date TEXT,
        expected_output TEXT,
        expected_output_type TEXT,
        priority TEXT NOT NULL,
        complexity TEXT NOT NULL,
        ai_confidence REAL,
        ai_model TEXT,
        ai_prompt_version TEXT,
        status TEXT NOT NULL,
        version INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(document_id) REFERENCES documents(doc_id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS source_citations (
        id TEXT PRIMARY KEY,
        action_item_id TEXT NOT NULL,
        document_id TEXT NOT NULL,
        attachment_id TEXT,
        page_start INTEGER,
        page_end INTEGER,
        char_start INTEGER,
        char_end INTEGER,
        excerpt TEXT,
        excerpt_sha256 TEXT,
        source_text_sha256 TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(action_item_id) REFERENCES action_items(id) ON DELETE CASCADE,
        FOREIGN KEY(document_id) REFERENCES documents(doc_id) ON DELETE CASCADE,
        FOREIGN KEY(attachment_id) REFERENCES attachments(id) ON DELETE SET NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS review_decisions (
        id TEXT PRIMARY KEY,
        action_item_id TEXT NOT NULL,
        decision TEXT NOT NULL,
        reviewer_id TEXT,
        reviewer_display_name TEXT,
        comment TEXT,
        before_json TEXT,
        after_json TEXT,
        decided_at TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(action_item_id) REFERENCES action_items(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS sync_events (
        id TEXT PRIMARY KEY,
        action_item_id TEXT NOT NULL,
        target_system TEXT NOT NULL,
        idempotency_key TEXT NOT NULL UNIQUE,
        attempt_number INTEGER NOT NULL,
        status TEXT NOT NULL,
        http_status INTEGER,
        remote_id TEXT,
        remote_url TEXT,
        error_code TEXT,
        error_message TEXT,
        request_sha256 TEXT,
        response_sha256 TEXT,
        created_at TEXT NOT NULL,
        started_at TEXT,
        completed_at TEXT,
        next_retry_at TEXT,
        FOREIGN KEY(action_item_id) REFERENCES action_items(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS user_unit_mappings (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        source_system TEXT NOT NULL,
        source_key TEXT NOT NULL,
        source_display_name TEXT NOT NULL,
        target_unit_id TEXT,
        target_user_id TEXT,
        target_role TEXT,
        status TEXT NOT NULL,
        valid_from TEXT,
        valid_to TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(tenant_id, source_system, source_key, target_role)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version TEXT PRIMARY KEY,
        applied_at TEXT NOT NULL
    );
    """,
]


_INDEXES_SQL = [
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_documents_domain_source ON documents(tenant_id, source_system, source_document_id, source_revision) WHERE tenant_id IS NOT NULL AND source_system IS NOT NULL AND source_document_id IS NOT NULL;",
    "CREATE INDEX IF NOT EXISTS idx_documents_source_document_id ON documents(source_document_id);",
    "CREATE INDEX IF NOT EXISTS idx_documents_ingest_status ON documents(ingest_status);",
    "CREATE INDEX IF NOT EXISTS idx_attachments_document_id ON attachments(document_id);",
    "CREATE INDEX IF NOT EXISTS idx_attachments_validation_status ON attachments(validation_status);",
    "CREATE INDEX IF NOT EXISTS idx_action_items_document_id ON action_items(document_id);",
    "CREATE INDEX IF NOT EXISTS idx_action_items_status ON action_items(status);",
    "CREATE INDEX IF NOT EXISTS idx_source_citations_action_item_id ON source_citations(action_item_id);",
    "CREATE INDEX IF NOT EXISTS idx_source_citations_document_id ON source_citations(document_id);",
    "CREATE INDEX IF NOT EXISTS idx_review_decisions_action_item_id ON review_decisions(action_item_id);",
    "CREATE INDEX IF NOT EXISTS idx_sync_events_action_item_id ON sync_events(action_item_id);",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_sync_events_idempotency_key ON sync_events(idempotency_key);",
    "CREATE INDEX IF NOT EXISTS idx_sync_events_status ON sync_events(status);",
    "CREATE INDEX IF NOT EXISTS idx_user_unit_mappings_status ON user_unit_mappings(status);",
    "CREATE INDEX IF NOT EXISTS idx_user_unit_mappings_source ON user_unit_mappings(tenant_id, source_system, source_key);",
]


def _existing_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] if isinstance(row, sqlite3.Row) else row[1] for row in rows}


def init_domain_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys=ON;")
    columns = _existing_columns(conn, "documents")
    for name, column_type in _DOCUMENT_COLUMNS.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE documents ADD COLUMN {name} {column_type};")
    for sql in _CREATE_TABLES_SQL:
        conn.execute(sql)
    for sql in _INDEXES_SQL:
        conn.execute(sql)
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
        (MIGRATION_VERSION, utc_now_iso()),
    )
    conn.commit()


def _document_exists(conn: sqlite3.Connection, document_id: str) -> bool:
    return conn.execute("SELECT 1 FROM documents WHERE doc_id = ?", (document_id,)).fetchone() is not None


def _action_item_document_id(conn: sqlite3.Connection, action_item_id: str) -> str | None:
    row = conn.execute("SELECT document_id FROM action_items WHERE id = ?", (action_item_id,)).fetchone()
    if row is None:
        return None
    return row["document_id"] if isinstance(row, sqlite3.Row) else row[0]


def _attachment_document_id(conn: sqlite3.Connection, attachment_id: str | None) -> str | None:
    if not attachment_id:
        return None
    row = conn.execute("SELECT document_id FROM attachments WHERE id = ?", (attachment_id,)).fetchone()
    if row is None:
        return None
    return row["document_id"] if isinstance(row, sqlite3.Row) else row[0]


class DomainRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.execute("PRAGMA foreign_keys=ON;")
        init_domain_schema(conn)

    def save_document(self, document: Document) -> None:
        validate_document(document)
        self.conn.execute(
            """
            INSERT INTO documents (
                doc_id, id, tenant_id, source_system, source_document_id, source_revision,
                document_type, document_number, issued_date_domain, received_date, issuer,
                signer, subject, summary_domain, urgency, source_url_domain, content_sha256,
                ingest_status, created_at_utc, updated_at_utc, domain_schema_version,
                direction, doc_no, doc_date, issuing_agency, title, status, source_url
            ) VALUES (
                :doc_id, :id, :tenant_id, :source_system, :source_document_id, :source_revision,
                :document_type, :document_number, :issued_date_domain, :received_date, :issuer,
                :signer, :subject, :summary_domain, :urgency, :source_url_domain, :content_sha256,
                :ingest_status, :created_at_utc, :updated_at_utc, :domain_schema_version,
                :direction, :doc_no, :doc_date, :issuing_agency, :title, :status, :source_url
            )
            ON CONFLICT(doc_id) DO UPDATE SET
                tenant_id = excluded.tenant_id,
                source_system = excluded.source_system,
                source_document_id = excluded.source_document_id,
                source_revision = excluded.source_revision,
                document_type = excluded.document_type,
                document_number = excluded.document_number,
                issued_date_domain = excluded.issued_date_domain,
                received_date = excluded.received_date,
                issuer = excluded.issuer,
                signer = excluded.signer,
                subject = excluded.subject,
                summary_domain = excluded.summary_domain,
                urgency = excluded.urgency,
                source_url_domain = excluded.source_url_domain,
                content_sha256 = excluded.content_sha256,
                ingest_status = excluded.ingest_status,
                updated_at_utc = excluded.updated_at_utc,
                domain_schema_version = excluded.domain_schema_version,
                direction = excluded.direction,
                doc_no = excluded.doc_no,
                doc_date = excluded.doc_date,
                issuing_agency = excluded.issuing_agency,
                title = excluded.title,
                status = excluded.status,
                source_url = excluded.source_url
            """,
            {
                "doc_id": document.id,
                "id": document.id,
                "tenant_id": document.tenant_id,
                "source_system": document.source_system,
                "source_document_id": document.source_document_id,
                "source_revision": document.source_revision,
                "document_type": document.document_type.value,
                "document_number": document.document_number,
                "issued_date_domain": document.issued_date,
                "received_date": document.received_date,
                "issuer": document.issuer,
                "signer": document.signer,
                "subject": document.subject,
                "summary_domain": document.summary,
                "urgency": document.urgency,
                "source_url_domain": document.source_url,
                "content_sha256": document.content_sha256,
                "ingest_status": document.ingest_status.value,
                "created_at_utc": document.created_at,
                "updated_at_utc": document.updated_at,
                "domain_schema_version": document.schema_version or DOMAIN_SCHEMA_VERSION,
                "direction": document.document_type.value.lower(),
                "doc_no": document.document_number or "",
                "doc_date": document.issued_date or "",
                "issuing_agency": document.issuer or "",
                "title": document.subject or document.summary or "",
                "status": document.ingest_status.value,
                "source_url": document.source_url or "",
            },
        )
        self.conn.commit()

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM documents WHERE doc_id = ?", (document_id,)).fetchone()
        return dict(row) if row is not None else None

    def save_attachment(self, attachment: Attachment) -> None:
        validate_attachment(attachment)
        self.conn.execute(
            """
            INSERT INTO attachments (
                id, document_id, source_attachment_id, file_name, file_extension, mime_type,
                size_bytes, sha256, storage_path, validation_status, validation_error,
                download_source, page_count, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                source_attachment_id = excluded.source_attachment_id,
                file_name = excluded.file_name,
                file_extension = excluded.file_extension,
                mime_type = excluded.mime_type,
                size_bytes = excluded.size_bytes,
                sha256 = excluded.sha256,
                storage_path = excluded.storage_path,
                validation_status = excluded.validation_status,
                validation_error = excluded.validation_error,
                download_source = excluded.download_source,
                page_count = excluded.page_count,
                updated_at = excluded.updated_at
            """,
            (
                attachment.id,
                attachment.document_id,
                attachment.source_attachment_id,
                attachment.file_name,
                attachment.file_extension,
                attachment.mime_type,
                attachment.size_bytes,
                attachment.sha256,
                attachment.storage_path,
                attachment.validation_status.value,
                attachment.validation_error,
                attachment.download_source,
                attachment.page_count,
                attachment.created_at,
                attachment.updated_at,
            ),
        )
        self.conn.commit()

    def save_action_item(self, action_item: ActionItem) -> None:
        validate_action_item(action_item, document_exists=_document_exists(self.conn, action_item.document_id))
        self.conn.execute(
            """
            INSERT INTO action_items (
                id, document_id, ordinal, title, description, proposed_unit_id,
                proposed_assignee_id, proposed_supervisor_id, proposed_due_date,
                expected_output, expected_output_type, priority, complexity,
                ai_confidence, ai_model, ai_prompt_version, status, version,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                ordinal = excluded.ordinal,
                title = excluded.title,
                description = excluded.description,
                proposed_unit_id = excluded.proposed_unit_id,
                proposed_assignee_id = excluded.proposed_assignee_id,
                proposed_supervisor_id = excluded.proposed_supervisor_id,
                proposed_due_date = excluded.proposed_due_date,
                expected_output = excluded.expected_output,
                expected_output_type = excluded.expected_output_type,
                priority = excluded.priority,
                complexity = excluded.complexity,
                ai_confidence = excluded.ai_confidence,
                ai_model = excluded.ai_model,
                ai_prompt_version = excluded.ai_prompt_version,
                status = excluded.status,
                version = excluded.version,
                updated_at = excluded.updated_at
            """,
            (
                action_item.id,
                action_item.document_id,
                action_item.ordinal,
                action_item.title,
                action_item.description,
                action_item.proposed_unit_id,
                action_item.proposed_assignee_id,
                action_item.proposed_supervisor_id,
                action_item.proposed_due_date,
                action_item.expected_output,
                action_item.expected_output_type.value if action_item.expected_output_type else None,
                action_item.priority.value,
                action_item.complexity.value,
                action_item.ai_confidence,
                action_item.ai_model,
                action_item.ai_prompt_version,
                action_item.status.value,
                action_item.version,
                action_item.created_at,
                action_item.updated_at,
            ),
        )
        self.conn.commit()

    def list_action_items(self, document_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM action_items WHERE document_id = ? ORDER BY ordinal, id",
            (document_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def save_citation(self, citation: SourceCitation) -> None:
        action_doc_id = _action_item_document_id(self.conn, citation.action_item_id)
        attachment_doc_id = _attachment_document_id(self.conn, citation.attachment_id)
        validate_citation(citation, action_item_document_id=action_doc_id, attachment_document_id=attachment_doc_id)
        self.conn.execute(
            """
            INSERT INTO source_citations (
                id, action_item_id, document_id, attachment_id, page_start, page_end,
                char_start, char_end, excerpt, excerpt_sha256, source_text_sha256, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                citation.id,
                citation.action_item_id,
                citation.document_id,
                citation.attachment_id,
                citation.page_start,
                citation.page_end,
                citation.char_start,
                citation.char_end,
                citation.excerpt,
                citation.excerpt_sha256,
                citation.source_text_sha256,
                citation.created_at,
            ),
        )
        self.conn.commit()

    def append_review_decision(self, decision: ReviewDecision) -> None:
        validate_review_decision(decision)
        self.conn.execute(
            """
            INSERT INTO review_decisions (
                id, action_item_id, decision, reviewer_id, reviewer_display_name,
                comment, before_json, after_json, decided_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision.id,
                decision.action_item_id,
                decision.decision.value,
                decision.reviewer_id,
                decision.reviewer_display_name,
                decision.comment,
                _stable_json_or_none(decision.before_json),
                _stable_json_or_none(decision.after_json),
                decision.decided_at,
                decision.created_at,
            ),
        )
        self.conn.commit()

    def append_sync_event(self, event: SyncEvent) -> None:
        action_status = self._get_action_item_status(event.action_item_id)
        validate_sync_event(event, action_item_status=action_status)
        self.conn.execute(
            """
            INSERT INTO sync_events (
                id, action_item_id, target_system, idempotency_key, attempt_number, status,
                http_status, remote_id, remote_url, error_code, error_message,
                request_sha256, response_sha256, created_at, started_at, completed_at, next_retry_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.id,
                event.action_item_id,
                event.target_system,
                event.idempotency_key,
                event.attempt_number,
                event.status.value,
                event.http_status,
                event.remote_id,
                event.remote_url,
                event.error_code,
                event.error_message,
                event.request_sha256,
                event.response_sha256,
                event.created_at,
                event.started_at,
                event.completed_at,
                event.next_retry_at,
            ),
        )
        self.conn.commit()

    def save_user_unit_mapping(self, mapping: UserUnitMapping) -> None:
        validate_user_unit_mapping(mapping)
        self.conn.execute(
            """
            INSERT INTO user_unit_mappings (
                id, tenant_id, source_system, source_key, source_display_name,
                target_unit_id, target_user_id, target_role, status, valid_from,
                valid_to, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(tenant_id, source_system, source_key, target_role) DO UPDATE SET
                source_display_name = excluded.source_display_name,
                target_unit_id = excluded.target_unit_id,
                target_user_id = excluded.target_user_id,
                status = excluded.status,
                valid_from = excluded.valid_from,
                valid_to = excluded.valid_to,
                updated_at = excluded.updated_at
            """,
            (
                mapping.id,
                mapping.tenant_id,
                mapping.source_system,
                mapping.source_key,
                mapping.source_display_name,
                mapping.target_unit_id,
                mapping.target_user_id,
                mapping.target_role,
                mapping.status.value,
                mapping.valid_from,
                mapping.valid_to,
                mapping.created_at,
                mapping.updated_at,
            ),
        )
        self.conn.commit()

    def _get_action_item_status(self, action_item_id: str):
        from .domain_models import ActionItemStatus

        row = self.conn.execute("SELECT status FROM action_items WHERE id = ?", (action_item_id,)).fetchone()
        if row is None:
            return None
        status = row["status"] if isinstance(row, sqlite3.Row) else row[0]
        return ActionItemStatus(status)


def _stable_json_or_none(value: str | None) -> str | None:
    if value in (None, ""):
        return value
    try:
        return canonical_json(json.loads(value))
    except Exception:
        return value
