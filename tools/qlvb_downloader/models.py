from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


ATTACHMENT_DISCOVERED = "DISCOVERED"
ATTACHMENT_DOWNLOAD_STARTED = "DOWNLOAD_STARTED"
ATTACHMENT_DOWNLOADED_RAW = "DOWNLOADED_RAW"
ATTACHMENT_VALIDATED = "VALIDATED"
ATTACHMENT_INVALID_FILE = "INVALID_FILE"
ATTACHMENT_DOWNLOAD_FAILED = "DOWNLOAD_FAILED"

DOCUMENT_PROCESSING = "PROCESSING"
DOCUMENT_READY = "READY"
DOCUMENT_READY_WITH_WARNINGS = "READY_WITH_WARNINGS"
DOCUMENT_NO_VALID_ATTACHMENT = "NO_VALID_ATTACHMENT"
DOCUMENT_INVALID_DOCUMENT = "INVALID_DOCUMENT"
DOCUMENT_FAILED = "FAILED"
DOCUMENT_SESSION_EXPIRED = "SESSION_EXPIRED"
DOCUMENT_QUEUEABLE_STATUSES = {DOCUMENT_READY, DOCUMENT_READY_WITH_WARNINGS}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def mask_url_query(url: str) -> str:
    if not url:
        return ""
    if "?" in url:
        return url.split("?", 1)[0] + "?[REDACTED]"
    return url


def safe_slug(value: str, max_len: int = 90) -> str:
    value = value or "khong_tieu_de"
    normalized = unicodedata.normalize("NFD", value)
    value = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("._-")
    return (value[:max_len] or "khong_tieu_de")


def short_hash(value: str, length: int = 12) -> str:
    return hashlib.sha1((value or "").encode("utf-8", errors="ignore")).hexdigest()[:length]


@dataclass
class AttachmentInfo:
    text: str
    href: str
    attachment_id: str | None = None
    source_method: str | None = None
    saved_path: str | None = None
    original_filename: str | None = None
    status: str = ATTACHMENT_DISCOVERED
    error: str | None = None
    validation_sha256: str | None = None
    validation_size_bytes: int | None = None
    validation_content_type: str | None = None
    download_source: str | None = None


@dataclass
class DocumentRecord:
    direction: str
    source_url: str
    row_index: int
    row_text: str
    source_category: str = ""
    knowledge_candidate: bool = False
    planner_candidate: bool = False
    detail_url: str | None = None
    doc_id: str = ""
    doc_no: str = ""
    doc_date: str = ""
    issuing_agency: str = ""
    title: str = ""
    summary: str = ""
    parser_version: str = ""
    mapping_warnings: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    attachments: list[AttachmentInfo] = field(default_factory=list)
    status: str = "NEW"
    error: str | None = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def ensure_doc_id(self) -> str:
        if not self.doc_id:
            seed = "|".join([self.direction, self.detail_url or "", self.doc_no, self.doc_date, self.title, self.row_text])
            self.doc_id = f"{self.direction}_{short_hash(seed)}"
        return self.doc_id

    @property
    def folder_name(self) -> str:
        self.ensure_doc_id()
        title_part = safe_slug(self.title or self.summary or self.doc_no or self.doc_id, 70)
        return f"{self.doc_id}_{title_part}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": "V22.2.2-QC",
            "direction": self.direction,
            "source_category": self.source_category,
            "knowledge_candidate": self.knowledge_candidate,
            "planner_candidate": self.planner_candidate,
            "source_url": self.source_url,
            "row_index": self.row_index,
            "row_text": self.row_text,
            "detail_url": self.detail_url,
            "doc_id": self.doc_id,
            "doc_no": self.doc_no,
            "doc_date": self.doc_date,
            "issuing_agency": self.issuing_agency,
            "title": self.title,
            "summary": self.summary,
            "metadata": self.metadata,
            "attachments": [a.__dict__ for a in self.attachments],
            "status": self.status,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": now_iso(),
        }
