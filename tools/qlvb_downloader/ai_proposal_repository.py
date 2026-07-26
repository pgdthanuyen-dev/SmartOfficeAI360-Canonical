from __future__ import annotations

import json
import sqlite3
from typing import Any

from .ai_proposal_models import (
    MAX_ERROR_LENGTH,
    MAX_WARNING_LENGTH,
    ProposalDedupeStatus,
    ProposalPersistStatus,
    compact_error,
    compact_warning,
    new_batch_id,
    now_for_ai_proposal,
)
from .domain_models import ActionItem, SourceCitation, sha256_text, utc_now_iso
from .domain_repository import init_domain_schema
from .domain_validation import validate_action_item, validate_citation
from .extraction_models import ExtractionStatus, normalize_extracted_text
from .extraction_repository import init_extraction_schema


AI_PROPOSAL_MIGRATION_VERSION = "g04_ai_proposal_schema_1"


_CREATE_TABLES_SQL = [
    """
    CREATE TABLE IF NOT EXISTS ai_proposal_batches (
        id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL,
        idempotency_key TEXT NOT NULL UNIQUE,
        schema_version TEXT NOT NULL,
        model_name TEXT NOT NULL,
        model_version TEXT NOT NULL,
        prompt_version TEXT NOT NULL,
        generated_at TEXT NOT NULL,
        raw_response_sha256 TEXT NOT NULL,
        status TEXT NOT NULL,
        received_count INTEGER NOT NULL,
        accepted_count INTEGER NOT NULL,
        rejected_count INTEGER NOT NULL,
        duplicate_count INTEGER NOT NULL,
        warning_count INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        completed_at TEXT,
        FOREIGN KEY(document_id) REFERENCES documents(doc_id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_proposal_items (
        id TEXT PRIMARY KEY,
        batch_id TEXT NOT NULL,
        document_id TEXT NOT NULL,
        external_proposal_id TEXT NOT NULL,
        action_item_id TEXT,
        fingerprint TEXT NOT NULL,
        dedupe_status TEXT NOT NULL,
        persist_status TEXT NOT NULL,
        title TEXT,
        normalized_title TEXT,
        confidence REAL,
        warnings TEXT,
        error_code TEXT,
        error_message TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(batch_id) REFERENCES ai_proposal_batches(id) ON DELETE CASCADE,
        FOREIGN KEY(document_id) REFERENCES documents(doc_id) ON DELETE CASCADE,
        FOREIGN KEY(action_item_id) REFERENCES action_items(id) ON DELETE SET NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_proposal_warnings (
        id TEXT PRIMARY KEY,
        batch_id TEXT NOT NULL,
        proposal_item_id TEXT,
        warning_code TEXT NOT NULL,
        message TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(batch_id) REFERENCES ai_proposal_batches(id) ON DELETE CASCADE,
        FOREIGN KEY(proposal_item_id) REFERENCES ai_proposal_items(id) ON DELETE CASCADE
    );
    """,
]

_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_ai_proposal_batches_document_id ON ai_proposal_batches(document_id);",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_proposal_batches_idempotency_key ON ai_proposal_batches(idempotency_key);",
    "CREATE INDEX IF NOT EXISTS idx_ai_proposal_items_document_id ON ai_proposal_items(document_id);",
    "CREATE INDEX IF NOT EXISTS idx_ai_proposal_items_fingerprint ON ai_proposal_items(document_id, fingerprint);",
    "CREATE INDEX IF NOT EXISTS idx_ai_proposal_items_batch_id ON ai_proposal_items(batch_id);",
    "CREATE INDEX IF NOT EXISTS idx_ai_proposal_warnings_batch_id ON ai_proposal_warnings(batch_id);",
]


def init_ai_proposal_schema(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    init_domain_schema(conn)
    init_extraction_schema(conn)
    for sql in _CREATE_TABLES_SQL:
        conn.execute(sql)
    for sql in _INDEXES_SQL:
        conn.execute(sql)
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
        (AI_PROPOSAL_MIGRATION_VERSION, utc_now_iso()),
    )
    conn.commit()


class AiProposalRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON;")
        init_ai_proposal_schema(conn)

    def document_exists(self, document_id: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM documents WHERE doc_id = ?", (document_id,)).fetchone()
        return row is not None

    def attachment_document_id(self, attachment_id: str) -> str | None:
        row = self.conn.execute("SELECT document_id FROM attachments WHERE id = ?", (attachment_id,)).fetchone()
        return row["document_id"] if row is not None else None

    def next_action_ordinal(self, document_id: str) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(ordinal), 0) AS max_ordinal FROM action_items WHERE document_id = ?",
            (document_id,),
        ).fetchone()
        return int(row["max_ordinal"]) + 1

    def get_batch_by_idempotency_key(self, idempotency_key: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM ai_proposal_batches WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        return dict(row) if row is not None else None

    def get_batch_action_ids(self, batch_id: str) -> list[str]:
        rows = self.conn.execute(
            """
            SELECT action_item_id FROM ai_proposal_items
            WHERE batch_id = ? AND action_item_id IS NOT NULL
            ORDER BY created_at, id
            """,
            (batch_id,),
        ).fetchall()
        return [row["action_item_id"] for row in rows]

    def create_batch(
        self,
        *,
        document_id: str,
        idempotency_key: str,
        schema_version: str,
        model_name: str,
        model_version: str,
        prompt_version: str,
        generated_at: str,
        raw_response_sha256: str,
        received_count: int,
    ) -> str:
        batch_id = new_batch_id()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO ai_proposal_batches (
                    id, document_id, idempotency_key, schema_version, model_name,
                    model_version, prompt_version, generated_at, raw_response_sha256,
                    status, received_count, accepted_count, rejected_count, duplicate_count,
                    warning_count, created_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, ?, NULL)
                """,
                (
                    batch_id,
                    document_id,
                    idempotency_key,
                    schema_version,
                    model_name,
                    model_version,
                    prompt_version,
                    generated_at,
                    raw_response_sha256,
                    "PROCESSING",
                    received_count,
                    now_for_ai_proposal(),
                ),
            )
        return batch_id

    def complete_batch(
        self,
        *,
        batch_id: str,
        status: str,
        accepted_count: int,
        rejected_count: int,
        duplicate_count: int,
        warning_count: int,
    ) -> None:
        with self.conn:
            self.conn.execute(
                """
                UPDATE ai_proposal_batches
                SET status = ?, accepted_count = ?, rejected_count = ?, duplicate_count = ?,
                    warning_count = ?, completed_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    accepted_count,
                    rejected_count,
                    duplicate_count,
                    warning_count,
                    now_for_ai_proposal(),
                    batch_id,
                ),
            )

    def record_item(
        self,
        *,
        batch_id: str,
        document_id: str,
        external_proposal_id: str,
        action_item_id: str | None,
        fingerprint: str,
        dedupe_status: ProposalDedupeStatus,
        persist_status: ProposalPersistStatus,
        title: str | None,
        normalized_title: str | None,
        confidence: float | None,
        warnings: list[str],
        error_code: str | None,
        error_message: str | None,
    ) -> str:
        item_id = new_batch_id()
        bounded_warnings = [compact_warning(warning) for warning in warnings[:]]
        bounded_error = compact_error(error_message) if error_message else None
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO ai_proposal_items (
                    id, batch_id, document_id, external_proposal_id, action_item_id,
                    fingerprint, dedupe_status, persist_status, title, normalized_title,
                    confidence, warnings, error_code, error_message, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    batch_id,
                    document_id,
                    external_proposal_id,
                    action_item_id,
                    fingerprint,
                    dedupe_status.value,
                    persist_status.value,
                    title,
                    normalized_title,
                    confidence,
                    json.dumps(bounded_warnings, ensure_ascii=False),
                    error_code,
                    bounded_error,
                    now_for_ai_proposal(),
                ),
            )
        return item_id

    def record_warning(
        self,
        *,
        batch_id: str,
        proposal_item_id: str | None,
        warning_code: str,
        message: str,
    ) -> None:
        bounded_code = compact_warning(warning_code)[:MAX_WARNING_LENGTH]
        bounded_message = compact_warning(message)
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO ai_proposal_warnings (
                    id, batch_id, proposal_item_id, warning_code, message, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    new_batch_id(),
                    batch_id,
                    proposal_item_id,
                    bounded_code,
                    bounded_message,
                    now_for_ai_proposal(),
                ),
            )

    def list_existing_proposal_items(self, document_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM ai_proposal_items
            WHERE document_id = ? AND persist_status = ?
            ORDER BY created_at, id
            """,
            (document_id, ProposalPersistStatus.ACCEPTED.value),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_accepted_proposals_for_tenant_document(
        self, *, tenant_id: str, document_id: str
    ) -> list[dict[str, Any]]:
        """Return accepted G04 records only when the document belongs to ``tenant_id``.

        This is intentionally a read-only boundary for G05 orchestration.  It exposes
        identifiers and persisted provenance references, never an AI request payload.
        """
        rows = self.conn.execute(
            """
            SELECT i.id AS proposal_item_id, i.document_id, d.tenant_id,
                   i.external_proposal_id, i.action_item_id,
                   i.fingerprint, i.confidence, i.warnings,
                   a.id AS action_id,
                   a.title AS action_title, a.description AS action_description,
                   a.proposed_unit_id, a.proposed_assignee_id, a.proposed_due_date,
                   a.expected_output, a.priority,
                   COUNT(c.id) AS citation_count,
                   GROUP_CONCAT(c.id) AS citation_ids
            FROM ai_proposal_items i
            JOIN documents d ON d.doc_id = i.document_id
            LEFT JOIN action_items a ON a.id = i.action_item_id
            LEFT JOIN source_citations c ON c.action_item_id = a.id
            WHERE i.document_id = ?
              AND d.tenant_id = ?
              AND i.persist_status = ?
            GROUP BY i.id, a.id
            ORDER BY i.created_at, i.id
            """,
            (document_id, tenant_id, ProposalPersistStatus.ACCEPTED.value),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_successful_page_texts(
        self,
        *,
        document_id: str,
        attachment_id: str,
        page_start: int,
        page_end: int,
    ) -> dict[int, str]:
        rows = self.conn.execute(
            """
            SELECT p.page_number, p.text
            FROM extraction_results r
            JOIN extracted_pages p ON p.extraction_result_id = r.id
            WHERE r.document_id = ?
              AND r.attachment_id = ?
              AND r.status IN (?, ?, ?)
              AND p.page_number BETWEEN ? AND ?
            ORDER BY r.completed_at DESC, r.started_at DESC, p.page_number
            """,
            (
                document_id,
                attachment_id,
                ExtractionStatus.SUCCEEDED.value,
                ExtractionStatus.SUCCEEDED_WITH_WARNINGS.value,
                ExtractionStatus.NO_TEXT.value,
                page_start,
                page_end,
            ),
        ).fetchall()
        pages: dict[int, str] = {}
        for row in rows:
            pages.setdefault(int(row["page_number"]), row["text"])
        return pages

    def save_action_item_with_citations(self, action_item: ActionItem, citations: list[SourceCitation]) -> None:
        validate_action_item(action_item, document_exists=self.document_exists(action_item.document_id))
        for citation in citations:
            validate_citation(
                citation,
                action_item_document_id=action_item.document_id,
                attachment_document_id=self.attachment_document_id(citation.attachment_id) if citation.attachment_id else None,
            )
        with self.conn:
            self._insert_action_item(action_item)
            for citation in citations:
                self._insert_citation(citation)

    def _insert_action_item(self, action_item: ActionItem) -> None:
        self.conn.execute(
            """
            INSERT INTO action_items (
                id, document_id, ordinal, title, description, proposed_unit_id,
                proposed_assignee_id, proposed_supervisor_id, proposed_due_date,
                expected_output, expected_output_type, priority, complexity,
                ai_confidence, ai_model, ai_prompt_version, status, version,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    def _insert_citation(self, citation: SourceCitation) -> None:
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


def source_text_sha256_for_pages(pages: dict[int, str]) -> str:
    text = "\n\f\n".join(normalize_extracted_text(pages[number]) for number in sorted(pages))
    return sha256_text(normalize_extracted_text(text))
