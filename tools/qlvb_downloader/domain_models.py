from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, date, datetime
from enum import Enum
from typing import Any, TypeVar, get_args, get_origin, get_type_hints

from .models import (
    ATTACHMENT_DISCOVERED,
    ATTACHMENT_DOWNLOAD_FAILED,
    ATTACHMENT_DOWNLOAD_STARTED,
    ATTACHMENT_DOWNLOADED_RAW,
    ATTACHMENT_INVALID_FILE,
    ATTACHMENT_VALIDATED,
)


DOMAIN_SCHEMA_VERSION = "1.0.0"
MAX_CITATION_EXCERPT_CHARS = 2000
MAX_ERROR_MESSAGE_CHARS = 1000


class StrEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class DocumentType(StrEnum):
    INCOMING = "INCOMING"
    OUTGOING = "OUTGOING"
    INTERNAL = "INTERNAL"
    OTHER = "OTHER"


class IngestStatus(StrEnum):
    NEW = "NEW"
    INGESTED = "INGESTED"
    EXTRACTED = "EXTRACTED"
    AI_ANALYZED = "AI_ANALYZED"
    ERROR = "ERROR"


class AttachmentValidationStatus(StrEnum):
    DISCOVERED = ATTACHMENT_DISCOVERED
    DOWNLOAD_STARTED = ATTACHMENT_DOWNLOAD_STARTED
    DOWNLOADED_RAW = ATTACHMENT_DOWNLOADED_RAW
    VALIDATED = ATTACHMENT_VALIDATED
    INVALID_FILE = ATTACHMENT_INVALID_FILE
    DOWNLOAD_FAILED = ATTACHMENT_DOWNLOAD_FAILED


class ActionItemStatus(StrEnum):
    PROPOSED = "PROPOSED"
    PENDING_REVIEW = "PENDING_REVIEW"
    NEEDS_CORRECTION = "NEEDS_CORRECTION"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SYNC_PENDING = "SYNC_PENDING"
    SYNCING = "SYNCING"
    SYNCED = "SYNCED"
    SYNC_ERROR = "SYNC_ERROR"


class Priority(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"


class Complexity(StrEnum):
    SIMPLE = "SIMPLE"
    MEDIUM = "MEDIUM"
    COMPLEX = "COMPLEX"


class ExpectedOutputType(StrEnum):
    DOCUMENT = "DOCUMENT"
    REPORT = "REPORT"
    MEETING = "MEETING"
    DATA = "DATA"
    OTHER = "OTHER"


class ReviewDecisionType(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    EDIT_AND_APPROVE = "EDIT_AND_APPROVE"


class SyncEventStatus(StrEnum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCEEDED = "SUCCEEDED"
    RETRYABLE_FAILED = "RETRYABLE_FAILED"
    PERMANENT_FAILED = "PERMANENT_FAILED"
    CANCELLED = "CANCELLED"


class MappingStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    NEEDS_REVIEW = "NEEDS_REVIEW"


T = TypeVar("T")


def new_id() -> str:
    return str(uuid.uuid4())


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def parse_utc_datetime(value: str | datetime | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError("datetime must include timezone")
    return dt.astimezone(UTC)


def _is_iso_date(value: str | date | None) -> bool:
    if value in (None, ""):
        return True
    if isinstance(value, date):
        return True
    try:
        date.fromisoformat(str(value))
        return True
    except ValueError:
        return False


def _enum_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return value


def _serialize_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.astimezone(UTC).replace(microsecond=0).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value):
        return value.to_dict()
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _serialize_value(v) for k, v in value.items()}
    return value


def canonical_json(payload: Any) -> str:
    return json.dumps(_serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def compute_stable_hash(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _coerce_enum(enum_type: type[StrEnum], value: Any) -> StrEnum:
    if isinstance(value, enum_type):
        return value
    return enum_type(value)


def _coerce_field(field_type: Any, value: Any) -> Any:
    if value is None:
        return None
    origin = get_origin(field_type)
    args = get_args(field_type)
    if origin is list:
        return list(value)
    if origin is dict:
        return dict(value)
    if origin is not None and type(None) in args:
        non_none = [arg for arg in args if arg is not type(None)]
        if non_none:
            return _coerce_field(non_none[0], value)
    if isinstance(field_type, type) and issubclass(field_type, StrEnum):
        return _coerce_enum(field_type, value)
    if field_type is datetime:
        return parse_utc_datetime(value)
    return value


class DomainModel:
    def to_dict(self) -> dict[str, Any]:
        return {field.name: _serialize_value(getattr(self, field.name)) for field in fields(self)}

    @classmethod
    def from_dict(cls: type[T], payload: dict[str, Any]) -> T:
        values: dict[str, Any] = {}
        hints = get_type_hints(cls)
        for field in fields(cls):
            if field.name in payload:
                values[field.name] = _coerce_field(hints.get(field.name, field.type), payload[field.name])
        return cls(**values)  # type: ignore[arg-type]

    def canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def compute_stable_hash(self) -> str:
        return compute_stable_hash(self.to_dict())

    def validate(self) -> None:
        from .domain_validation import validate_entity

        validate_entity(self)


@dataclass
class Document(DomainModel):
    tenant_id: str
    source_system: str
    source_document_id: str
    id: str = ""
    source_revision: str | None = None
    document_type: DocumentType = DocumentType.OTHER
    document_number: str | None = None
    issued_date: str | None = None
    received_date: str | None = None
    issuer: str | None = None
    signer: str | None = None
    subject: str | None = None
    summary: str | None = None
    urgency: str | None = None
    source_url: str | None = None
    content_sha256: str | None = None
    ingest_status: IngestStatus = IngestStatus.NEW
    created_at: str = ""
    updated_at: str = ""
    schema_version: str = DOMAIN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.id:
            self.id = new_id()
        if self.source_revision is None:
            self.source_revision = "1"
        now = utc_now_iso()
        self.created_at = self.created_at or now
        self.updated_at = self.updated_at or now


@dataclass
class Attachment(DomainModel):
    document_id: str
    file_name: str
    id: str = ""
    source_attachment_id: str | None = None
    file_extension: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    storage_path: str | None = None
    validation_status: AttachmentValidationStatus = AttachmentValidationStatus.DISCOVERED
    validation_error: str | None = None
    download_source: str | None = None
    page_count: int | None = None
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = new_id()
        if not self.file_extension and "." in self.file_name:
            self.file_extension = self.file_name.rsplit(".", 1)[-1].lower()
        now = utc_now_iso()
        self.created_at = self.created_at or now
        self.updated_at = self.updated_at or now


@dataclass
class ActionItem(DomainModel):
    document_id: str
    ordinal: int
    title: str
    id: str = ""
    description: str | None = None
    proposed_unit_id: str | None = None
    proposed_assignee_id: str | None = None
    proposed_supervisor_id: str | None = None
    proposed_due_date: str | None = None
    expected_output: str | None = None
    expected_output_type: ExpectedOutputType | None = None
    priority: Priority = Priority.NORMAL
    complexity: Complexity = Complexity.MEDIUM
    ai_confidence: float | None = None
    ai_model: str | None = None
    ai_prompt_version: str | None = None
    status: ActionItemStatus = ActionItemStatus.PROPOSED
    version: int = 1
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = new_id()
        now = utc_now_iso()
        self.created_at = self.created_at or now
        self.updated_at = self.updated_at or now


@dataclass
class SourceCitation(DomainModel):
    action_item_id: str
    document_id: str
    id: str = ""
    attachment_id: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    excerpt: str | None = None
    excerpt_sha256: str | None = None
    source_text_sha256: str | None = None
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = new_id()
        self.created_at = self.created_at or utc_now_iso()
        if self.excerpt and len(self.excerpt) > MAX_CITATION_EXCERPT_CHARS:
            self.excerpt = self.excerpt[:MAX_CITATION_EXCERPT_CHARS]
        if self.excerpt and not self.excerpt_sha256:
            self.excerpt_sha256 = sha256_text(self.excerpt)


@dataclass
class ReviewDecision(DomainModel):
    action_item_id: str
    decision: ReviewDecisionType
    id: str = ""
    reviewer_id: str | None = None
    reviewer_display_name: str | None = None
    comment: str | None = None
    before_json: str | None = None
    after_json: str | None = None
    decided_at: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        now = utc_now_iso()
        if not self.id:
            self.id = new_id()
        self.decided_at = self.decided_at or now
        self.created_at = self.created_at or now


@dataclass
class SyncEvent(DomainModel):
    action_item_id: str
    target_system: str
    idempotency_key: str
    attempt_number: int
    status: SyncEventStatus
    id: str = ""
    http_status: int | None = None
    remote_id: str | None = None
    remote_url: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    request_sha256: str | None = None
    response_sha256: str | None = None
    created_at: str = ""
    started_at: str | None = None
    completed_at: str | None = None
    next_retry_at: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            self.id = new_id()
        self.created_at = self.created_at or utc_now_iso()
        if self.error_message and len(self.error_message) > MAX_ERROR_MESSAGE_CHARS:
            self.error_message = self.error_message[:MAX_ERROR_MESSAGE_CHARS]


@dataclass
class UserUnitMapping(DomainModel):
    tenant_id: str
    source_system: str
    source_key: str
    source_display_name: str
    id: str = ""
    target_unit_id: str | None = None
    target_user_id: str | None = None
    target_role: str | None = None
    status: MappingStatus = MappingStatus.NEEDS_REVIEW
    valid_from: str | None = None
    valid_to: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = new_id()
        now = utc_now_iso()
        self.created_at = self.created_at or now
        self.updated_at = self.updated_at or now


def is_valid_iso_date(value: str | date | None) -> bool:
    return _is_iso_date(value)
