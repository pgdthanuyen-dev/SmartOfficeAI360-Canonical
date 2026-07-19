from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from .domain_models import DomainModel, StrEnum, new_id, parse_utc_datetime, sha256_text, utc_now_iso


EXTRACTION_SCHEMA_VERSION = "1.0.0"
EXTRACTOR_NAME = "canonical_attachment_extractor"
EXTRACTOR_VERSION = "g03.1"
MAX_EXTRACTION_ERROR_CHARS = 1000
MAX_PAGE_TEXT_CHARS = 1_000_000
MAX_DOCUMENT_TEXT_CHARS = 5_000_000


class ExtractionMethod(StrEnum):
    DIRECT_TEXT = "DIRECT_TEXT"
    OCR = "OCR"
    MIXED = "MIXED"
    UNSUPPORTED = "UNSUPPORTED"


class ExtractionStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    SUCCEEDED_WITH_WARNINGS = "SUCCEEDED_WITH_WARNINGS"
    NO_TEXT = "NO_TEXT"
    UNSUPPORTED = "UNSUPPORTED"
    FAILED = "FAILED"


class DetectedFileType(StrEnum):
    PDF = "PDF"
    DOCX = "DOCX"
    TXT = "TXT"
    PNG = "PNG"
    JPEG = "JPEG"
    ZIP = "ZIP"
    HTML = "HTML"
    UNSUPPORTED = "UNSUPPORTED"


class ExtractionValidationError(ValueError):
    pass


@dataclass
class ExtractionResult(DomainModel):
    document_id: str
    attachment_id: str
    extractor_name: str
    extractor_version: str
    extraction_method: ExtractionMethod
    status: ExtractionStatus
    source_file_sha256: str
    id: str = ""
    normalized_text_sha256: str | None = None
    language: str | None = None
    page_count: int | None = None
    warnings: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    ocr_version: str = "none"
    started_at: str = ""
    completed_at: str | None = None
    schema_version: str = EXTRACTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.id:
            self.id = new_id()
        now = utc_now_iso()
        self.started_at = self.started_at or now
        self.completed_at = self.completed_at or now
        if self.error_message and len(self.error_message) > MAX_EXTRACTION_ERROR_CHARS:
            self.error_message = self.error_message[:MAX_EXTRACTION_ERROR_CHARS]


@dataclass
class ExtractedPage(DomainModel):
    extraction_result_id: str
    page_number: int
    text: str
    extraction_method: ExtractionMethod
    id: str = ""
    text_sha256: str | None = None
    character_count: int = 0
    confidence: float | None = None
    width: int | None = None
    height: int | None = None
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = new_id()
        self.created_at = self.created_at or utc_now_iso()
        self.text = normalize_extracted_text(self.text)
        if len(self.text) > MAX_PAGE_TEXT_CHARS:
            self.text = self.text[:MAX_PAGE_TEXT_CHARS]
        self.character_count = len(self.text)
        self.text_sha256 = self.text_sha256 or sha256_text(self.text)


def normalize_extracted_text(text: str | None) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFC", text)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    cleaned_chars: list[str] = []
    for char in normalized:
        category = unicodedata.category(char)
        if char in "\n\t":
            cleaned_chars.append(char)
        elif category.startswith("C"):
            continue
        else:
            cleaned_chars.append(char)
    cleaned = "".join(cleaned_chars)
    cleaned = re.sub(r"\n{4,}", "\n\n\n", cleaned)
    return cleaned.strip()


def validate_extraction_result(result: ExtractionResult) -> None:
    _require(bool(result.id), "extraction_result.id is required")
    _require(bool(result.document_id), "extraction_result.document_id is required")
    _require(bool(result.attachment_id), "extraction_result.attachment_id is required")
    _require(bool(result.extractor_name), "extraction_result.extractor_name is required")
    _require(bool(result.extractor_version), "extraction_result.extractor_version is required")
    _validate_sha(result.source_file_sha256, "extraction_result.source_file_sha256")
    _validate_sha(result.normalized_text_sha256, "extraction_result.normalized_text_sha256")
    if result.page_count is not None:
        _require(result.page_count >= 0, "extraction_result.page_count must be non-negative")
    _validate_datetime(result.started_at, "extraction_result.started_at")
    _validate_datetime(result.completed_at, "extraction_result.completed_at")
    if result.error_message is not None:
        _require(
            len(result.error_message) <= MAX_EXTRACTION_ERROR_CHARS,
            "extraction_result.error_message is too long",
        )


def validate_extracted_page(page: ExtractedPage) -> None:
    _require(bool(page.id), "extracted_page.id is required")
    _require(bool(page.extraction_result_id), "extracted_page.extraction_result_id is required")
    _require(page.page_number >= 1, "extracted_page.page_number must start at 1")
    _validate_sha(page.text_sha256, "extracted_page.text_sha256")
    if page.confidence is not None:
        _require(0.0 <= page.confidence <= 1.0, "extracted_page.confidence must be between 0.0 and 1.0")
    if page.width is not None:
        _require(page.width > 0, "extracted_page.width must be positive")
    if page.height is not None:
        _require(page.height > 0, "extracted_page.height must be positive")
    _validate_datetime(page.created_at, "extracted_page.created_at")


def combined_text_hash(pages: list[ExtractedPage]) -> str:
    text = "\n\f\n".join(page.text for page in pages)
    return sha256_text(normalize_extracted_text(text))


def truncate_document_pages(pages: list[ExtractedPage]) -> tuple[list[ExtractedPage], list[str]]:
    warnings: list[str] = []
    total = 0
    kept: list[ExtractedPage] = []
    for page in pages:
        if total >= MAX_DOCUMENT_TEXT_CHARS:
            warnings.append("DOCUMENT_TEXT_LIMIT_REACHED")
            break
        remaining = MAX_DOCUMENT_TEXT_CHARS - total
        if len(page.text) > remaining:
            page.text = page.text[:remaining]
            page.character_count = len(page.text)
            page.text_sha256 = sha256_text(page.text)
            warnings.append("PAGE_TEXT_TRUNCATED_BY_DOCUMENT_LIMIT")
        total += len(page.text)
        kept.append(page)
    return kept, warnings


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ExtractionValidationError(message)


_SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")


def _validate_sha(value: str | None, field_name: str) -> None:
    if value in (None, ""):
        return
    _require(bool(_SHA256_RE.match(value)), f"{field_name} must be a SHA-256 hex digest")


def _validate_datetime(value: str | None, field_name: str) -> None:
    if value in (None, ""):
        return
    try:
        parse_utc_datetime(value)
    except Exception as exc:
        raise ExtractionValidationError(f"{field_name} must be timezone-aware UTC ISO-8601 compatible") from exc


def enum_value(value: Any) -> Any:
    return value.value if isinstance(value, StrEnum) else value
