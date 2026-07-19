from __future__ import annotations

import sqlite3
from typing import Any

from .domain_models import utc_now_iso
from .extraction_models import (
    ExtractionResult,
    ExtractionStatus,
    ExtractedPage,
    enum_value,
    validate_extracted_page,
    validate_extraction_result,
)


MIGRATION_VERSION = "g03_extraction_schema_1"


_CREATE_TABLES_SQL = [
    """
    CREATE TABLE IF NOT EXISTS extraction_results (
        id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL,
        attachment_id TEXT NOT NULL,
        extractor_name TEXT NOT NULL,
        extractor_version TEXT NOT NULL,
        extraction_method TEXT NOT NULL,
        status TEXT NOT NULL,
        source_file_sha256 TEXT NOT NULL,
        normalized_text_sha256 TEXT,
        language TEXT,
        page_count INTEGER,
        warnings TEXT,
        error_code TEXT,
        error_message TEXT,
        ocr_version TEXT NOT NULL,
        started_at TEXT NOT NULL,
        completed_at TEXT,
        schema_version TEXT NOT NULL,
        FOREIGN KEY(document_id) REFERENCES documents(doc_id) ON DELETE CASCADE,
        FOREIGN KEY(attachment_id) REFERENCES attachments(id) ON DELETE CASCADE,
        UNIQUE(attachment_id, source_file_sha256, extractor_name, extractor_version, ocr_version)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS extracted_pages (
        id TEXT PRIMARY KEY,
        extraction_result_id TEXT NOT NULL,
        page_number INTEGER NOT NULL,
        text TEXT NOT NULL,
        text_sha256 TEXT NOT NULL,
        character_count INTEGER NOT NULL,
        extraction_method TEXT NOT NULL,
        confidence REAL,
        width INTEGER,
        height INTEGER,
        created_at TEXT NOT NULL,
        FOREIGN KEY(extraction_result_id) REFERENCES extraction_results(id) ON DELETE CASCADE,
        UNIQUE(extraction_result_id, page_number)
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
    "CREATE INDEX IF NOT EXISTS idx_extraction_results_attachment_id ON extraction_results(attachment_id);",
    "CREATE INDEX IF NOT EXISTS idx_extraction_results_document_id ON extraction_results(document_id);",
    "CREATE INDEX IF NOT EXISTS idx_extraction_results_status ON extraction_results(status);",
    "CREATE INDEX IF NOT EXISTS idx_extracted_pages_result_id ON extracted_pages(extraction_result_id);",
]


def init_extraction_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys=ON;")
    for sql in _CREATE_TABLES_SQL:
        conn.execute(sql)
    for sql in _INDEXES_SQL:
        conn.execute(sql)
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
        (MIGRATION_VERSION, utc_now_iso()),
    )
    conn.commit()


class ExtractionRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON;")
        init_extraction_schema(conn)

    def get_attachment(self, attachment_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM attachments WHERE id = ?", (attachment_id,)).fetchone()
        return dict(row) if row is not None else None

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM documents WHERE doc_id = ?", (document_id,)).fetchone()
        return dict(row) if row is not None else None

    def find_cached_success(
        self,
        *,
        attachment_id: str,
        source_file_sha256: str,
        extractor_name: str,
        extractor_version: str,
        ocr_version: str,
    ) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT * FROM extraction_results
            WHERE attachment_id = ?
              AND source_file_sha256 = ?
              AND extractor_name = ?
              AND extractor_version = ?
              AND ocr_version = ?
              AND status IN (?, ?)
            ORDER BY completed_at DESC, started_at DESC
            LIMIT 1
            """,
            (
                attachment_id,
                source_file_sha256,
                extractor_name,
                extractor_version,
                ocr_version,
                ExtractionStatus.SUCCEEDED.value,
                ExtractionStatus.SUCCEEDED_WITH_WARNINGS.value,
            ),
        ).fetchone()
        return dict(row) if row is not None else None

    def list_pages(self, extraction_result_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM extracted_pages WHERE extraction_result_id = ? ORDER BY page_number",
            (extraction_result_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def save_result_with_pages(self, result: ExtractionResult, pages: list[ExtractedPage]) -> None:
        validate_extraction_result(result)
        for page in pages:
            validate_extracted_page(page)
        try:
            with self.conn:
                self._delete_existing_cache(result)
                self._insert_result(result)
                for page in pages:
                    self._insert_page(page)
        except Exception:
            self.conn.rollback()
            raise

    def save_failed_result(self, result: ExtractionResult) -> None:
        result.status = ExtractionStatus.FAILED
        result.page_count = 0
        validate_extraction_result(result)
        with self.conn:
            self._delete_existing_cache(result)
            self._insert_result(result)

    def _delete_existing_cache(self, result: ExtractionResult) -> None:
        self.conn.execute(
            """
            DELETE FROM extraction_results
            WHERE attachment_id = ?
              AND source_file_sha256 = ?
              AND extractor_name = ?
              AND extractor_version = ?
              AND ocr_version = ?
            """,
            (
                result.attachment_id,
                result.source_file_sha256,
                result.extractor_name,
                result.extractor_version,
                result.ocr_version,
            ),
        )

    def _insert_result(self, result: ExtractionResult) -> None:
        self.conn.execute(
            """
            INSERT INTO extraction_results (
                id, document_id, attachment_id, extractor_name, extractor_version,
                extraction_method, status, source_file_sha256, normalized_text_sha256,
                language, page_count, warnings, error_code, error_message, ocr_version,
                started_at, completed_at, schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.id,
                result.document_id,
                result.attachment_id,
                result.extractor_name,
                result.extractor_version,
                result.extraction_method.value,
                result.status.value,
                result.source_file_sha256,
                result.normalized_text_sha256,
                result.language,
                result.page_count,
                result.warnings,
                result.error_code,
                result.error_message,
                result.ocr_version,
                result.started_at,
                result.completed_at,
                result.schema_version,
            ),
        )

    def _insert_page(self, page: ExtractedPage) -> None:
        self.conn.execute(
            """
            INSERT INTO extracted_pages (
                id, extraction_result_id, page_number, text, text_sha256, character_count,
                extraction_method, confidence, width, height, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                page.id,
                page.extraction_result_id,
                page.page_number,
                page.text,
                page.text_sha256,
                page.character_count,
                enum_value(page.extraction_method),
                page.confidence,
                page.width,
                page.height,
                page.created_at,
            ),
        )
