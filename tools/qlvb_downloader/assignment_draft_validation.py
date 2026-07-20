"""Hard validation and bounded normalization for G05C draft construction."""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Iterable

from .assignment_draft_models import AssignmentDraftBuildRequest


MAX_TENANT_LENGTH = 200
MAX_SOURCE_SYSTEM_LENGTH = 200
MAX_SOURCE_DOCUMENT_ID_LENGTH = 500
MAX_SOURCE_REVISION_LENGTH = 200
MAX_DOCUMENT_NUMBER_LENGTH = 500
MAX_SUBJECT_LENGTH = 1000
MAX_SUMMARY_LENGTH = 10_000
MAX_TASK_TITLE_LENGTH = 300
MAX_TASK_DESCRIPTION_LENGTH = 10_000
MAX_UNIT_KEY_LENGTH = 500
MAX_LIST_ITEM_LENGTH = 1_000
MAX_DELIVERABLES = 20
MAX_CHECKLIST_ITEMS = 50
MAX_MILESTONES = 20
MAX_WARNINGS = 16
MAX_WARNING_MESSAGE_LENGTH = 80
MAX_WARNING_ACTION_LENGTH = 200
VALID_PRIORITIES = frozenset({"LOW", "NORMAL", "HIGH", "URGENT"})
VALID_ROLE_TYPES = frozenset({"LEADER", "MONITOR", "LEAD_EXECUTOR", "CO_EXECUTOR"})
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SOURCE_SYSTEM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SENSITIVE_VALUE_RE = re.compile(
    r"(?is)(authorization\s*:|bearer\s+\S+|api[_-]?key\s*[=:]|"
    r"(?:access[_-]?)?token\s*[=:]|cookie\s*[=:]|password\s*[=:]|"
    r"(?:[A-Za-z]:\\\\|\\\\\\\\)|data:[^,]{0,120};base64,|"
    r"https?://[^\s]*sharepoint[^\s]*)"
)


class AssignmentDraftValidationError(ValueError):
    def __init__(self, code: str, field: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.field = field


def normalize_text(value: str, field: str, maximum: int, *, required: bool = False) -> str:
    if not isinstance(value, str):
        raise AssignmentDraftValidationError("INVALID_TEXT", field, f"{field} must be text.")
    normalized = " ".join(value.split())
    if required and not normalized:
        raise AssignmentDraftValidationError("MISSING_REQUIRED_FIELD", field, f"{field} is required.")
    if len(normalized) > maximum:
        raise AssignmentDraftValidationError("TEXT_LIMIT_EXCEEDED", field, f"{field} exceeds its approved limit.")
    if SENSITIVE_VALUE_RE.search(normalized):
        raise AssignmentDraftValidationError("SENSITIVE_DATA_NOT_ALLOWED", field, f"{field} contains prohibited data.")
    return normalized


def normalize_optional_text(value: str | None, field: str, maximum: int) -> str | None:
    if value is None:
        return None
    normalized = normalize_text(value, field, maximum)
    return normalized or None


def normalize_date(value: str | None, field: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise AssignmentDraftValidationError("INVALID_DATE", field, f"{field} must be an ISO date.")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise AssignmentDraftValidationError("INVALID_DATE", field, f"{field} must be an ISO date.") from exc


def normalize_priority(value: str | None) -> str:
    if value is None or not str(value).strip():
        return "NORMAL"
    priority = str(value).strip().upper()
    if priority not in VALID_PRIORITIES:
        raise AssignmentDraftValidationError("INVALID_PRIORITY", "proposed_priority", "Priority is not supported.")
    return priority


def normalize_text_list(value: Iterable[str], field: str, maximum_items: int) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise AssignmentDraftValidationError("INVALID_LIST", field, f"{field} must be a list.")
    try:
        values = list(value)
    except TypeError as exc:
        raise AssignmentDraftValidationError("INVALID_LIST", field, f"{field} must be a list.") from exc
    if len(values) > maximum_items:
        raise AssignmentDraftValidationError("LIST_LIMIT_EXCEEDED", field, f"{field} exceeds its approved limit.")
    return tuple(normalize_text(item, field, MAX_LIST_ITEM_LENGTH, required=True) for item in values)


def normalize_set_list(value: Iterable[str], field: str, maximum_items: int) -> tuple[str, ...]:
    normalized = normalize_text_list(value, field, maximum_items)
    return tuple(sorted(set(normalized)))


def validate_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise AssignmentDraftValidationError("INVALID_FINGERPRINT", field, f"{field} must be a lowercase SHA-256 value.")
    return value


def proposal_recommendation(proposal: Any) -> Any:
    """Accept G05A's evaluation wrapper or its documented recommendation."""

    return getattr(proposal, "recommendation", proposal)


def proposal_tenant(proposal: Any) -> str | None:
    if hasattr(proposal, "tenant_id"):
        return getattr(proposal, "tenant_id")
    signals = getattr(proposal, "signals", None)
    return getattr(signals, "tenant_id", None)


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _validate_bounded_warning_values(values: Any, field: str) -> None:
    try:
        items = list(values)
    except TypeError as exc:
        raise AssignmentDraftValidationError("INVALID_LIST", field, f"{field} must be a list.") from exc
    if len(items) > MAX_WARNINGS:
        raise AssignmentDraftValidationError("LIST_LIMIT_EXCEEDED", field, f"{field} exceeds its approved limit.")
    for item in items:
        normalize_text(_enum_value(item), field, MAX_WARNING_MESSAGE_LENGTH, required=True)


def _validate_roles(values: Any, field: str) -> None:
    try:
        roles = list(values)
    except TypeError as exc:
        raise AssignmentDraftValidationError("INVALID_LIST", field, f"{field} must be a list.") from exc
    if len(roles) > len(VALID_ROLE_TYPES):
        raise AssignmentDraftValidationError("LIST_LIMIT_EXCEEDED", field, f"{field} exceeds its approved limit.")
    for role in roles:
        if _enum_value(role) not in VALID_ROLE_TYPES:
            raise AssignmentDraftValidationError("INVALID_ROLE", field, "Proposal role is not supported.")


def validate_build_request(request: AssignmentDraftBuildRequest) -> None:
    if not isinstance(request, AssignmentDraftBuildRequest):
        raise AssignmentDraftValidationError("INVALID_REQUEST", "request", "A build request is required.")
    tenant_id = normalize_text(request.tenant_id, "tenant_id", MAX_TENANT_LENGTH, required=True)
    source_system = normalize_text(request.source_system, "source_system", MAX_SOURCE_SYSTEM_LENGTH, required=True)
    if not SOURCE_SYSTEM_RE.fullmatch(source_system):
        raise AssignmentDraftValidationError("INVALID_SOURCE_IDENTITY", "source_system", "source_system has an invalid format.")
    normalize_text(request.source_document_id, "source_document_id", MAX_SOURCE_DOCUMENT_ID_LENGTH, required=True)
    normalize_text(request.source_revision, "source_revision", MAX_SOURCE_REVISION_LENGTH, required=True)
    normalize_optional_text(request.document_number, "document_number", MAX_DOCUMENT_NUMBER_LENGTH)
    normalize_text(request.subject, "subject", MAX_SUBJECT_LENGTH)
    normalize_text(request.normalized_summary, "normalized_summary", MAX_SUMMARY_LENGTH)
    normalize_text(request.proposed_task_title, "proposed_task_title", MAX_TASK_TITLE_LENGTH, required=True)
    normalize_text(request.proposed_task_description, "proposed_task_description", MAX_TASK_DESCRIPTION_LENGTH)
    normalize_date(request.received_date, "received_date")
    normalize_date(request.issued_date, "issued_date")
    normalize_date(request.proposed_start_date, "proposed_start_date")
    normalize_date(request.proposed_due_date, "proposed_due_date")
    normalize_priority(request.proposed_priority)
    normalize_text_list(request.proposed_deliverables, "proposed_deliverables", MAX_DELIVERABLES)
    normalize_text_list(request.proposed_checklist_items, "proposed_checklist_items", MAX_CHECKLIST_ITEMS)
    normalize_text_list(request.proposed_milestones, "proposed_milestones", MAX_MILESTONES)
    normalize_optional_text(request.file_reference_placeholder, "file_reference_placeholder", MAX_LIST_ITEM_LENGTH)
    if request.g05a_proposal is None or request.g05b_proposal is None:
        raise AssignmentDraftValidationError("MISSING_PROPOSAL", "proposal", "Both G05A and G05B proposals are required.")
    g05a = proposal_recommendation(request.g05a_proposal)
    g05b = proposal_recommendation(request.g05b_proposal)
    for name, proposal in (("g05a_proposal", g05a), ("g05b_proposal", g05b)):
        proposal_tenant_id = proposal_tenant(request.g05a_proposal if name == "g05a_proposal" else request.g05b_proposal)
        if proposal_tenant_id is not None and proposal_tenant_id != tenant_id:
            raise AssignmentDraftValidationError("CROSS_TENANT_PROPOSAL", name, "Proposal tenant does not match the request.")
        if getattr(proposal, "document_id", None) != request.source_document_id:
            raise AssignmentDraftValidationError("SOURCE_IDENTITY_MISMATCH", name, "Proposal document does not match the request.")
        if getattr(proposal, "document_revision", None) != request.source_revision:
            raise AssignmentDraftValidationError("SOURCE_REVISION_MISMATCH", name, "Proposal revision does not match the request.")
        validate_sha256(getattr(proposal, "input_fingerprint", None), f"{name}.input_fingerprint")
        engine_version = getattr(proposal, "engine_version", None)
        normalize_text(engine_version, f"{name}.engine_version", 100, required=True)
    for field, value in (("g05a_proposal.confidence", getattr(g05a, "confidence", None)), ("g05b_proposal.overall_confidence", getattr(g05b, "overall_confidence", None))):
        if not isinstance(value, (int, float)) or not 0 <= float(value) <= 100:
            raise AssignmentDraftValidationError("INVALID_CONFIDENCE", field, "Proposal confidence must be between 0 and 100.")
    for recommendation in getattr(g05b, "role_recommendations", []):
        value = getattr(recommendation, "confidence", None)
        if not isinstance(value, (int, float)) or not 0 <= float(value) <= 100:
            raise AssignmentDraftValidationError("INVALID_CONFIDENCE", "g05b_proposal.role_recommendations", "Personnel confidence must be between 0 and 100.")
        if _enum_value(getattr(recommendation, "role_type", "")) not in VALID_ROLE_TYPES:
            raise AssignmentDraftValidationError("INVALID_ROLE", "g05b_proposal.role_recommendations", "Personnel role is not supported.")
    _validate_roles(getattr(g05a, "required_roles", []), "g05a_proposal.required_roles")
    _validate_roles(getattr(g05b, "unresolved_roles", []), "g05b_proposal.unresolved_roles")
    _validate_roles(getattr(g05b, "conflicting_roles", []), "g05b_proposal.conflicting_roles")
    _validate_bounded_warning_values(getattr(g05a, "warnings", []), "g05a_proposal.warnings")
    _validate_bounded_warning_values(getattr(g05b, "warnings", []), "g05b_proposal.warnings")
