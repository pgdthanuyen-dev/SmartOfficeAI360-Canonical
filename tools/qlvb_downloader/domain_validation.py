from __future__ import annotations

import re
from typing import Any

from .domain_models import (
    ActionItem,
    ActionItemStatus,
    Attachment,
    Document,
    MappingStatus,
    ReviewDecision,
    SourceCitation,
    SyncEvent,
    UserUnitMapping,
    is_valid_iso_date,
    parse_utc_datetime,
)


_SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")


class DomainValidationError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DomainValidationError(message)


def _validate_datetime(value: str | None, field_name: str) -> None:
    if value in (None, ""):
        return
    try:
        parse_utc_datetime(value)
    except Exception as exc:
        raise DomainValidationError(f"{field_name} must be timezone-aware UTC ISO-8601 compatible") from exc


def _validate_sha(value: str | None, field_name: str) -> None:
    if value in (None, ""):
        return
    _require(bool(_SHA256_RE.match(value)), f"{field_name} must be a SHA-256 hex digest")


def validate_document(document: Document) -> None:
    _require(bool(document.id), "document.id is required")
    _require(bool(document.tenant_id), "document.tenant_id is required")
    _require(bool(document.source_system), "document.source_system is required")
    _require(bool(document.source_document_id), "document.source_document_id is required")
    _require(is_valid_iso_date(document.issued_date), "document.issued_date must be ISO date when provided")
    _require(is_valid_iso_date(document.received_date), "document.received_date must be ISO date when provided")
    _validate_sha(document.content_sha256, "document.content_sha256")
    _validate_datetime(document.created_at, "document.created_at")
    _validate_datetime(document.updated_at, "document.updated_at")


def validate_attachment(attachment: Attachment) -> None:
    _require(bool(attachment.id), "attachment.id is required")
    _require(bool(attachment.document_id), "attachment.document_id is required")
    _require(bool(attachment.file_name), "attachment.file_name is required")
    if attachment.size_bytes is not None:
        _require(attachment.size_bytes >= 0, "attachment.size_bytes must be non-negative")
    if attachment.page_count is not None:
        _require(attachment.page_count > 0, "attachment.page_count must be positive")
    _validate_sha(attachment.sha256, "attachment.sha256")
    _validate_datetime(attachment.created_at, "attachment.created_at")
    _validate_datetime(attachment.updated_at, "attachment.updated_at")


def validate_action_item(action_item: ActionItem, *, document_exists: bool = True) -> None:
    _require(bool(action_item.id), "action_item.id is required")
    _require(bool(action_item.document_id), "action_item.document_id is required")
    _require(document_exists, "action_item.document_id must reference an existing document")
    _require(action_item.ordinal > 0, "action_item.ordinal must be positive")
    if action_item.status == ActionItemStatus.APPROVED:
        _require(bool(action_item.title and action_item.title.strip()), "approved action_item requires title")
    else:
        _require(action_item.title is not None, "action_item.title cannot be None")
    if action_item.status == ActionItemStatus.SYNC_PENDING:
        _require(bool(action_item.title and action_item.title.strip()), "sync pending action_item requires title")
    if action_item.ai_confidence is not None:
        _require(0.0 <= action_item.ai_confidence <= 1.0, "action_item.ai_confidence must be between 0.0 and 1.0")
    _require(is_valid_iso_date(action_item.proposed_due_date), "action_item.proposed_due_date must be ISO date when provided")
    _validate_datetime(action_item.created_at, "action_item.created_at")
    _validate_datetime(action_item.updated_at, "action_item.updated_at")


def validate_action_item_transition(old_status: ActionItemStatus, new_status: ActionItemStatus) -> None:
    if new_status == ActionItemStatus.SYNC_PENDING:
        _require(old_status == ActionItemStatus.APPROVED, "SYNC_PENDING requires prior APPROVED status")


def is_action_item_sync_eligible(status: ActionItemStatus) -> bool:
    return status in {ActionItemStatus.APPROVED, ActionItemStatus.SYNC_PENDING}


def validate_citation(
    citation: SourceCitation,
    *,
    action_item_document_id: str | None = None,
    attachment_document_id: str | None = None,
) -> None:
    _require(bool(citation.id), "citation.id is required")
    _require(bool(citation.action_item_id), "citation.action_item_id is required")
    _require(bool(citation.document_id), "citation.document_id is required")
    if action_item_document_id is not None:
        _require(citation.document_id == action_item_document_id, "citation must belong to the same document as action item")
    if attachment_document_id is not None and citation.attachment_id:
        _require(citation.document_id == attachment_document_id, "citation attachment must belong to the same document")
    if citation.page_start is not None:
        _require(citation.page_start > 0, "citation.page_start must be positive")
    if citation.page_end is not None:
        _require(citation.page_end > 0, "citation.page_end must be positive")
    if citation.page_start is not None and citation.page_end is not None:
        _require(citation.page_end >= citation.page_start, "citation.page_end cannot be less than page_start")
    if citation.char_start is not None:
        _require(citation.char_start >= 0, "citation.char_start must be non-negative")
    if citation.char_end is not None:
        _require(citation.char_end >= 0, "citation.char_end must be non-negative")
    if citation.char_start is not None and citation.char_end is not None:
        _require(citation.char_end >= citation.char_start, "citation.char_end cannot be less than char_start")
    _validate_sha(citation.excerpt_sha256, "citation.excerpt_sha256")
    _validate_sha(citation.source_text_sha256, "citation.source_text_sha256")
    _validate_datetime(citation.created_at, "citation.created_at")


def validate_review_decision(decision: ReviewDecision) -> None:
    _require(bool(decision.id), "review_decision.id is required")
    _require(bool(decision.action_item_id), "review_decision.action_item_id is required")
    _require(
        bool(decision.reviewer_id or decision.reviewer_display_name),
        "review_decision requires reviewer_id or reviewer_display_name",
    )
    _validate_datetime(decision.decided_at, "review_decision.decided_at")
    _validate_datetime(decision.created_at, "review_decision.created_at")


def validate_sync_event(sync_event: SyncEvent, *, action_item_status: ActionItemStatus | None = None) -> None:
    _require(bool(sync_event.id), "sync_event.id is required")
    _require(bool(sync_event.action_item_id), "sync_event.action_item_id is required")
    _require(bool(sync_event.target_system), "sync_event.target_system is required")
    _require(bool(sync_event.idempotency_key and sync_event.idempotency_key.strip()), "sync_event.idempotency_key is required")
    _require(sync_event.attempt_number > 0, "sync_event.attempt_number must be positive")
    if action_item_status is not None:
        _require(action_item_status != ActionItemStatus.REJECTED, "cannot create SyncEvent for REJECTED action item")
    _validate_sha(sync_event.request_sha256, "sync_event.request_sha256")
    _validate_sha(sync_event.response_sha256, "sync_event.response_sha256")
    _validate_datetime(sync_event.created_at, "sync_event.created_at")
    _validate_datetime(sync_event.started_at, "sync_event.started_at")
    _validate_datetime(sync_event.completed_at, "sync_event.completed_at")
    _validate_datetime(sync_event.next_retry_at, "sync_event.next_retry_at")


def validate_user_unit_mapping(mapping: UserUnitMapping) -> None:
    _require(bool(mapping.id), "mapping.id is required")
    _require(bool(mapping.tenant_id), "mapping.tenant_id is required")
    _require(bool(mapping.source_system), "mapping.source_system is required")
    _require(bool(mapping.source_key), "mapping.source_key is required")
    _require(bool(mapping.source_display_name), "mapping.source_display_name is required")
    ambiguous = not mapping.target_unit_id and not mapping.target_user_id
    if ambiguous:
        _require(mapping.status == MappingStatus.NEEDS_REVIEW, "ambiguous mapping must be NEEDS_REVIEW")
    _validate_datetime(mapping.valid_from, "mapping.valid_from")
    _validate_datetime(mapping.valid_to, "mapping.valid_to")
    _validate_datetime(mapping.created_at, "mapping.created_at")
    _validate_datetime(mapping.updated_at, "mapping.updated_at")


def validate_entity(entity: Any) -> None:
    if isinstance(entity, Document):
        validate_document(entity)
    elif isinstance(entity, Attachment):
        validate_attachment(entity)
    elif isinstance(entity, ActionItem):
        validate_action_item(entity)
    elif isinstance(entity, SourceCitation):
        validate_citation(entity)
    elif isinstance(entity, ReviewDecision):
        validate_review_decision(entity)
    elif isinstance(entity, SyncEvent):
        validate_sync_event(entity)
    elif isinstance(entity, UserUnitMapping):
        validate_user_unit_mapping(entity)
    else:
        raise DomainValidationError(f"unsupported entity type: {type(entity)!r}")
