"""
index_db.py — Phase 3: SQLite Index Layer
==========================================
Quản lý SQLite index cho toàn bộ manifest trong hàng đợi,
hỗ trợ tìm kiếm, lọc và phân trang nhanh mà không cần quét filesystem.

Thiết kế:
  - Tất cả hàm đều graceful: không crash pipeline nếu SQLite lỗi
  - Backward-compatible: GUI cũ không cần sử dụng ngay
  - upsert_document: tạo hoặc cập nhật bản ghi theo doc_id
  - search_documents: tìm kiếm full-text + filter + phân trang
  - rebuild_index_from_queue: scan toàn bộ queue và rebuild index
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Generator

logger = logging.getLogger("qlvb.index_db")

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id                TEXT PRIMARY KEY,
    direction             TEXT,
    doc_no                TEXT,
    doc_date              TEXT,
    issuing_agency        TEXT,
    title                 TEXT,
    status                TEXT,
    sync_status           TEXT,
    planner_doc_id        TEXT,
    downloaded_at         TEXT,
    synced_at             TEXT,
    audit_label           TEXT,
    validation_status     TEXT,
    confidence_score      INTEGER,
    manifest_path         TEXT,
    full_text_excerpt     TEXT,
    full_text_status      TEXT,
    updated_at            TEXT,
    source_category       TEXT,
    source_url            TEXT,
    knowledge_candidate   INTEGER,
    planner_candidate     INTEGER,
    parser_version        TEXT,
    mapping_profile       TEXT,
    mapping_warnings      TEXT,
    raw_source_category   TEXT,
    canonicalized_at      TEXT
);
"""

_CREATE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_documents_sync_status ON documents(sync_status);",
    "CREATE INDEX IF NOT EXISTS idx_documents_direction ON documents(direction);",
    "CREATE INDEX IF NOT EXISTS idx_documents_doc_date ON documents(doc_date);",
    "CREATE INDEX IF NOT EXISTS idx_documents_audit_label ON documents(audit_label);",
    "CREATE INDEX IF NOT EXISTS idx_documents_validation_status ON documents(validation_status);",
    "CREATE INDEX IF NOT EXISTS idx_documents_title ON documents(title);",
]

# Thư mục DB mặc định
_DEFAULT_DB_SUBPATH = "index/documents.db"


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------
def init_db(db_path: str | Path) -> sqlite3.Connection:
    """
    Khởi tạo SQLite database và tạo bảng/index nếu chưa có.

    Trả về connection đã mở. Caller phải close hoặc dùng context manager.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row  # cho phép truy cập theo tên cột
    conn.execute("PRAGMA journal_mode=WAL;")   # ghi đồng thời tốt hơn
    conn.execute("PRAGMA foreign_keys=ON;")

    conn.execute(_CREATE_TABLE_SQL)
    for idx_sql in _CREATE_INDEXES_SQL:
        conn.execute(idx_sql)
        
    _upgrade_db_schema(conn)
    conn.commit()

    logger.debug("[index_db] DB khởi tạo tại %s", db_path)
    return conn


def _upgrade_db_schema(conn: sqlite3.Connection):
    """Thực hiện lệnh ALTER TABLE để migrate nếu DB là bản cũ."""
    try:
        cursor = conn.execute("PRAGMA table_info(documents);")
        columns = [row["name"] for row in cursor.fetchall()]
        
        new_columns = {
            "source_category": "TEXT",
            "source_url": "TEXT",
            "knowledge_candidate": "INTEGER",
            "planner_candidate": "INTEGER",
            "parser_version": "TEXT",
            "mapping_profile": "TEXT",
            "mapping_warnings": "TEXT",
            "raw_source_category": "TEXT",
            "canonicalized_at": "TEXT",
        }
        
        for col_name, col_type in new_columns.items():
            if col_name not in columns:
                try:
                    conn.execute(f"ALTER TABLE documents ADD COLUMN {col_name} {col_type};")
                    logger.info(f"[index_db] Thêm cột {col_name} vào documents.")
                except sqlite3.OperationalError as e:
                    logger.warning(f"[index_db] Lỗi thêm cột {col_name}: {e}")
    except Exception as e:
        logger.warning(f"[index_db] Lỗi _upgrade_db_schema: {e}")

def get_default_db_path(data_dir: str | Path) -> Path:
    """Trả về đường dẫn DB mặc định từ data_dir."""
    return Path(data_dir) / _DEFAULT_DB_SUBPATH


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
def upsert_document(conn: sqlite3.Connection, document_dict: dict[str, Any]) -> bool:
    """
    Tạo hoặc cập nhật bản ghi document trong index.

    document_dict nên có ít nhất: doc_id, direction.
    Tất cả trường khác là optional — dùng .get() với default None.

    Trả về True nếu thành công, False nếu lỗi (không raise).
    """
    try:
        doc = document_dict
        sync_block = doc.get("sync") or {}

        conn.execute(
            """
            INSERT INTO documents (
                doc_id, direction, doc_no, doc_date, issuing_agency, title,
                status, sync_status, planner_doc_id, downloaded_at, synced_at,
                audit_label, validation_status, confidence_score, manifest_path, full_text_excerpt,
                full_text_status, updated_at, source_category, source_url,
                knowledge_candidate, planner_candidate, parser_version, mapping_profile,
                mapping_warnings, raw_source_category, canonicalized_at
            ) VALUES (
                :doc_id, :direction, :doc_no, :doc_date, :issuing_agency, :title,
                :status, :sync_status, :planner_doc_id, :downloaded_at, :synced_at,
                :audit_label, :validation_status, :confidence_score,
                :manifest_path, :full_text_excerpt, :full_text_status, :updated_at,
                :source_category, :source_url, :knowledge_candidate, :planner_candidate,
                :parser_version, :mapping_profile, :mapping_warnings, :raw_source_category,
                :canonicalized_at
            )
            ON CONFLICT(doc_id) DO UPDATE SET
                direction           = excluded.direction,
                doc_no              = excluded.doc_no,
                doc_date            = excluded.doc_date,
                issuing_agency      = excluded.issuing_agency,
                title               = excluded.title,
                status              = excluded.status,
                sync_status         = excluded.sync_status,
                planner_doc_id      = excluded.planner_doc_id,
                downloaded_at       = excluded.downloaded_at,
                synced_at           = excluded.synced_at,
                audit_label         = excluded.audit_label,
                validation_status   = excluded.validation_status,
                confidence_score    = excluded.confidence_score,
                manifest_path       = excluded.manifest_path,
                full_text_excerpt   = excluded.full_text_excerpt,
                full_text_status    = excluded.full_text_status,
                updated_at          = excluded.updated_at,
                source_category     = excluded.source_category,
                source_url          = excluded.source_url,
                knowledge_candidate = excluded.knowledge_candidate,
                planner_candidate   = excluded.planner_candidate,
                parser_version      = excluded.parser_version,
                mapping_profile     = excluded.mapping_profile,
                mapping_warnings    = excluded.mapping_warnings,
                raw_source_category = excluded.raw_source_category,
                canonicalized_at    = excluded.canonicalized_at
            """,
            {
                "doc_id":             doc.get("doc_id") or doc.get("external_doc_id") or "",
                "direction":          doc.get("direction", ""),
                "doc_no":             doc.get("document_number") or doc.get("doc_no") or "",
                "doc_date":           doc.get("issued_date") or doc.get("doc_date") or "",
                "issuing_agency":     doc.get("issuing_agency", ""),
                "title":              doc.get("summary") or doc.get("title") or "",
                "status":             doc.get("status", ""),
                "sync_status":        "BLOCKED" if doc.get("validation_status") in ["INVALID", "INVALID_MAPPING", "STRUCTURAL_MAPPING_ERROR", "INVALID_DOC_DATE", "TECHNICAL_ROW_DETECTED", "HEADER_ROW_DETECTED", "SOURCE_CATEGORY_MISMATCH", "POSSIBLE_TECHNICAL_DOC_NO", "INVALID_ISSUING_AGENCY", "TECHNICAL_TITLE"] else sync_block.get("planner_kpi_status", "PENDING"),
                "planner_doc_id":     sync_block.get("planner_kpi_document_id"),
                "downloaded_at":      doc.get("downloaded_at"),
                "synced_at":          sync_block.get("last_sync_at"),
                "audit_label":        doc.get("audit_label"),
                "validation_status":  doc.get("validation_status"),
                "confidence_score":   doc.get("confidence_score"),
                "manifest_path":      doc.get("manifest_path"),
                "full_text_excerpt":  doc.get("full_text_excerpt"),
                "full_text_status":   doc.get("full_text_status"),
                "updated_at":         datetime.now().isoformat(),
                "source_category":    doc.get("source_category", ""),
                "source_url":         doc.get("source_url", ""),
                "knowledge_candidate": 1 if doc.get("knowledge_candidate") else 0,
                "planner_candidate":  1 if doc.get("planner_candidate") else 0,
                "parser_version":      doc.get("parser_version", ""),
                "mapping_profile":     doc.get("mapping_profile", ""),
                "mapping_warnings":    doc.get("mapping_warnings", ""),
                "raw_source_category": doc.get("raw_source_category", ""),
                "canonicalized_at":    doc.get("canonicalized_at", ""),
            },
        )
        conn.commit()
        return True
    except Exception as exc:
        logger.warning("[index_db] upsert_document lỗi: %s", exc)
        return False


def get_document(conn: sqlite3.Connection, doc_id: str) -> dict[str, Any] | None:
    """
    Lấy bản ghi theo doc_id.
    Trả về dict hoặc None nếu không tìm thấy.
    """
    try:
        cursor = conn.execute(
            "SELECT * FROM documents WHERE doc_id = ?", (doc_id,)
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(row)
    except Exception as exc:
        logger.warning("[index_db] get_document lỗi: %s", exc)
        return None


def search_documents(
    conn: sqlite3.Connection,
    query: str = "",
    filters: dict[str, Any] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """
    Tìm kiếm tài liệu trong index với full-text LIKE và filter.

    Parameters:
        query   : chuỗi tìm kiếm (khớp title, doc_no, issuing_agency)
        filters : dict các điều kiện lọc chính xác, ví dụ:
                  {"sync_status": "PENDING", "direction": "incoming"}
                  Các key hợp lệ: direction, sync_status, validation_status,
                                  audit_label, status
        limit   : số bản ghi tối đa trả về (mặc định 50)
        offset  : phân trang, bỏ qua N bản ghi đầu

    Trả về:
        {
            "total": int,
            "items": [dict, ...],
            "limit": int,
            "offset": int,
        }
    """
    try:
        where_clauses: list[str] = []
        params: list[Any] = []

        # Full-text LIKE search
        if query and query.strip():
            q = f"%{query.strip()}%"
            where_clauses.append(
                "(title LIKE ? OR doc_no LIKE ? OR issuing_agency LIKE ?)"
            )
            params.extend([q, q, q])

        # Exact match filters
        _allowed_filter_keys = {
            "direction", "sync_status", "validation_status",
            "audit_label", "status",
        }
        for key, val in (filters or {}).items():
            if key in _allowed_filter_keys and val is not None:
                where_clauses.append(f"{key} = ?")
                params.append(val)

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        # Count total
        count_sql = f"SELECT COUNT(*) FROM documents {where_sql}"
        total = conn.execute(count_sql, params).fetchone()[0]

        # Fetch page
        data_sql = (
            f"SELECT * FROM documents {where_sql} "
            f"ORDER BY downloaded_at DESC, updated_at DESC "
            f"LIMIT ? OFFSET ?"
        )
        rows = conn.execute(data_sql, params + [limit, offset]).fetchall()
        items = [dict(r) for r in rows]

        return {"total": total, "items": items, "limit": limit, "offset": offset}

    except Exception as exc:
        logger.warning("[index_db] search_documents lỗi: %s", exc)
        return {"total": 0, "items": [], "limit": limit, "offset": offset}


def delete_document(conn: sqlite3.Connection, doc_id: str) -> bool:
    """Xóa bản ghi theo doc_id. Trả về True nếu thành công."""
    try:
        conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
        conn.commit()
        return True
    except Exception as exc:
        logger.warning("[index_db] delete_document lỗi: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Rebuild index từ queue
# ---------------------------------------------------------------------------
def _iter_manifest_paths(data_dir: Path) -> Generator[tuple[str, Path], None, None]:
    """Duyệt tất cả manifest.json trong queue/incoming và queue/outgoing."""
    queue_root = data_dir / "queue"
    for direction in ("incoming", "outgoing"):
        dir_path = queue_root / direction
        if not dir_path.exists():
            continue
        for item in dir_path.iterdir():
            if item.is_dir():
                manifest_path = item / "manifest.json"
                if manifest_path.exists():
                    yield direction, manifest_path


def rebuild_index_from_queue(
    data_dir: str | Path,
    db_path: str | Path | None = None,
) -> dict[str, int]:
    """
    Quét toàn bộ queue và rebuild SQLite index từ đầu.

    Parameters:
        data_dir : thư mục Data/ của project
        db_path  : đường dẫn file .db (mặc định: data_dir/index/documents.db)

    Trả về:
        {"total": int, "indexed": int, "errors": int}
    """
    data_dir = Path(data_dir)
    if db_path is None:
        db_path = get_default_db_path(data_dir)

    stats = {"total": 0, "indexed": 0, "errors": 0}

    try:
        conn = init_db(db_path)
    except Exception as exc:
        logger.error("[index_db] Không khởi tạo được DB: %s", exc)
        return stats

    try:
        for direction, manifest_path in _iter_manifest_paths(data_dir):
            stats["total"] += 1
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
                manifest["manifest_path"] = str(manifest_path)
                manifest["direction"] = manifest.get("direction") or direction
                ok = upsert_document(conn, manifest)
                if ok:
                    stats["indexed"] += 1
                else:
                    stats["errors"] += 1
            except Exception as exc:
                logger.warning(
                    "[index_db] Lỗi đọc manifest %s: %s", manifest_path, exc
                )
                stats["errors"] += 1

        logger.info(
            "[index_db] Rebuild hoàn tất | total=%d indexed=%d errors=%d",
            stats["total"],
            stats["indexed"],
            stats["errors"],
        )
    finally:
        conn.close()

    return stats


# ---------------------------------------------------------------------------
# Context manager helper
# ---------------------------------------------------------------------------
def open_db(data_dir: str | Path, db_path: str | Path | None = None) -> sqlite3.Connection:
    """
    Mở kết nối DB, tạo nếu chưa có.
    Trả về connection — caller có trách nhiệm close.
    """
    data_dir = Path(data_dir)
    if db_path is None:
        db_path = get_default_db_path(data_dir)
    return init_db(db_path)
