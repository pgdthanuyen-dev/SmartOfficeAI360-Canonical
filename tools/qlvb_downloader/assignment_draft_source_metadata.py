"""Canonical, credential-free source attachment metadata for G05C drafts."""

from __future__ import annotations

import sqlite3
import re
from typing import Iterable

from .assignment_draft_models import AssignmentDraftSourceAttachment
from .assignment_draft_validation import AssignmentDraftValidationError, normalize_optional_text, normalize_text
from .domain_models import AttachmentValidationStatus


MAX_SOURCE_ATTACHMENTS = 32
MAX_ATTACHMENT_FILE_NAME_LENGTH = 512
MAX_ATTACHMENT_MIME_TYPE_LENGTH = 255
MAX_ATTACHMENT_ID_LENGTH = 512
MAX_ATTACHMENT_CHECKSUM_LENGTH = 128
MAX_ATTACHMENT_SIZE_BYTES = 10 * 1024 * 1024 * 1024
LOCAL_PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\|file://|/home/|/Users/|/tmp/)", re.IGNORECASE)
LONG_BASE64_RE = re.compile(r"^(?:[A-Za-z0-9+/]{1024,}={0,2})$")


def _safe_text(value: str | None, field: str, maximum: int, *, required: bool = False) -> str | None:
    normalized = normalize_text(value, field, maximum, required=required) if required else normalize_optional_text(value, field, maximum)
    if normalized and (LOCAL_PATH_RE.search(normalized) or LONG_BASE64_RE.fullmatch(normalized)):
        raise AssignmentDraftValidationError("SENSITIVE_DATA_NOT_ALLOWED", field, f"{field} contains prohibited data.")
    return normalized


def normalize_source_attachments(value: Iterable[AssignmentDraftSourceAttachment]) -> tuple[AssignmentDraftSourceAttachment, ...]:
    """Keep only bounded fields accepted by the Planner receiver contract."""

    if isinstance(value, (str, bytes)):
        raise AssignmentDraftValidationError("INVALID_LIST", "source_attachments", "source_attachments must be a list.")
    try:
        attachments = list(value)
    except TypeError as exc:
        raise AssignmentDraftValidationError("INVALID_LIST", "source_attachments", "source_attachments must be a list.") from exc
    if len(attachments) > MAX_SOURCE_ATTACHMENTS:
        raise AssignmentDraftValidationError("LIST_LIMIT_EXCEEDED", "source_attachments", "source_attachments exceed the approved limit.")

    normalized: list[AssignmentDraftSourceAttachment] = []
    for index, attachment in enumerate(attachments):
        if not isinstance(attachment, AssignmentDraftSourceAttachment):
            raise AssignmentDraftValidationError("INVALID_ATTACHMENT", f"source_attachments[{index}]", "attachment metadata is invalid.")
        if attachment.size_bytes is not None and (
            not isinstance(attachment.size_bytes, int)
            or attachment.size_bytes < 0
            or attachment.size_bytes > MAX_ATTACHMENT_SIZE_BYTES
        ):
            raise AssignmentDraftValidationError("INVALID_ATTACHMENT", f"source_attachments[{index}].size_bytes", "attachment size is invalid.")
        normalized.append(AssignmentDraftSourceAttachment(
            source_attachment_id=_safe_text(attachment.source_attachment_id, f"source_attachments[{index}].source_attachment_id", MAX_ATTACHMENT_ID_LENGTH),
            file_name=_safe_text(attachment.file_name, f"source_attachments[{index}].file_name", MAX_ATTACHMENT_FILE_NAME_LENGTH, required=True) or "",
            mime_type=_safe_text(attachment.mime_type, f"source_attachments[{index}].mime_type", MAX_ATTACHMENT_MIME_TYPE_LENGTH),
            size_bytes=attachment.size_bytes,
            checksum=_safe_text(attachment.checksum, f"source_attachments[{index}].checksum", MAX_ATTACHMENT_CHECKSUM_LENGTH),
        ))
    return tuple(sorted(normalized, key=lambda item: (item.source_attachment_id or "", item.file_name, item.checksum or "")))


def load_canonical_source_attachments(
    connection: sqlite3.Connection,
    *,
    tenant_id: str,
    source_system: str,
    source_document_id: str,
    source_revision: str,
) -> tuple[AssignmentDraftSourceAttachment, ...]:
    """Read only validated G02 attachment metadata; never read or expose files."""

    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT a.id, a.source_attachment_id, a.file_name, a.mime_type, a.size_bytes, a.sha256
            FROM attachments AS a
            JOIN documents AS d ON d.doc_id = a.document_id
            WHERE d.tenant_id=? AND d.source_system=? AND d.source_document_id=? AND d.source_revision=?
              AND a.validation_status=?
            ORDER BY a.id ASC
            """,
            (tenant_id, source_system, source_document_id, source_revision, AttachmentValidationStatus.VALIDATED.value),
        ).fetchall()
    except sqlite3.OperationalError:
        # Legacy local databases may not have initialized the G02 attachment tables yet.
        return ()
    return normalize_source_attachments(
        AssignmentDraftSourceAttachment(
            source_attachment_id=row["source_attachment_id"] or row["id"],
            file_name=row["file_name"],
            mime_type=row["mime_type"],
            size_bytes=row["size_bytes"],
            checksum=row["sha256"],
        )
        for row in rows
    )
