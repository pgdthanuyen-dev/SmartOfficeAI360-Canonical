from __future__ import annotations

import json
from datetime import date
from typing import Any

from .ai_proposal_models import (
    AI_PROPOSAL_SCHEMA_VERSION,
    MAX_AI_PROPOSAL_CITATIONS,
    MAX_AI_PROPOSAL_DESCRIPTION_CHARS,
    MAX_AI_PROPOSAL_EXCERPT_CHARS,
    MAX_AI_PROPOSAL_JSON_BYTES,
    MAX_AI_PROPOSAL_REASONING_CHARS,
    MAX_AI_PROPOSAL_TITLE_CHARS,
    MAX_AI_PROPOSALS,
    MAX_WARNING_LENGTH,
    MAX_WARNINGS_PER_ENVELOPE,
    MAX_WARNINGS_PER_PROPOSAL,
    AiCitation,
    AiProposal,
    AiProposalEnvelope,
)
from .domain_models import Complexity, ExpectedOutputType, Priority, parse_utc_datetime


class AiProposalValidationError(ValueError):
    pass


ENVELOPE_FIELDS = {
    "schema_version",
    "document_id",
    "attachment_ids",
    "model_name",
    "model_version",
    "prompt_version",
    "generated_at",
    "proposals",
    "warnings",
}

PROPOSAL_FIELDS = {
    "external_proposal_id",
    "title",
    "description",
    "proposed_unit_id",
    "proposed_assignee_id",
    "proposed_supervisor_id",
    "proposed_due_date",
    "expected_output",
    "expected_output_type",
    "priority",
    "complexity",
    "confidence",
    "citations",
    "reasoning_summary",
    "warnings",
}

CITATION_FIELDS = {
    "attachment_id",
    "page_start",
    "page_end",
    "excerpt",
    "char_start",
    "char_end",
}

FORBIDDEN_STATUS_VALUES = {"APPROVED", "SYNC_PENDING", "SYNCED", "SYNCING"}


def parse_ai_proposal_json(payload: str | bytes | dict[str, Any], *, strict: bool = True) -> AiProposalEnvelope:
    obj = _load_json_object(payload)
    return validate_ai_proposal_envelope(obj, strict=strict)


def validate_ai_proposal_envelope(payload: dict[str, Any], *, strict: bool = True) -> AiProposalEnvelope:
    _require_object(payload, "envelope")
    _reject_unknown(payload, ENVELOPE_FIELDS, "envelope", strict=strict)
    _require_fields(payload, ENVELOPE_FIELDS, "envelope")
    _require(payload["schema_version"] == AI_PROPOSAL_SCHEMA_VERSION, "unsupported ai proposal schema_version")
    document_id = _require_string(payload["document_id"], "document_id")
    attachment_ids = _require_string_list(payload["attachment_ids"], "attachment_ids")
    model_name = _require_string(payload["model_name"], "model_name")
    model_version = _require_string(payload["model_version"], "model_version")
    prompt_version = _require_string(payload["prompt_version"], "prompt_version")
    generated_at = _require_string(payload["generated_at"], "generated_at")
    try:
        parse_utc_datetime(generated_at)
    except ValueError as exc:
        raise AiProposalValidationError("generated_at must be timezone-aware ISO datetime") from exc
    proposals_payload = payload["proposals"]
    _require(isinstance(proposals_payload, list), "proposals must be an array")
    _require(len(proposals_payload) <= MAX_AI_PROPOSALS, "too many proposals")
    proposals = [validate_ai_proposal(item, strict=strict) for item in proposals_payload]
    warnings = _require_string_list(
        payload["warnings"],
        "warnings",
        allow_empty=True,
        max_items=MAX_WARNINGS_PER_ENVELOPE,
        max_chars=MAX_WARNING_LENGTH,
    )
    return AiProposalEnvelope(
        schema_version=AI_PROPOSAL_SCHEMA_VERSION,
        document_id=document_id,
        attachment_ids=attachment_ids,
        model_name=model_name,
        model_version=model_version,
        prompt_version=prompt_version,
        generated_at=generated_at,
        proposals=proposals,
        warnings=warnings,
    )


def validate_ai_proposal(payload: dict[str, Any], *, strict: bool = True) -> AiProposal:
    _require_object(payload, "proposal")
    if "status" in payload and payload["status"] in FORBIDDEN_STATUS_VALUES:
        raise AiProposalValidationError("AI response cannot set approved or sync status")
    _reject_unknown(payload, PROPOSAL_FIELDS, "proposal", strict=strict)
    _require_fields(payload, PROPOSAL_FIELDS, "proposal")
    external_proposal_id = _require_string(payload["external_proposal_id"], "external_proposal_id")
    title = _require_string(payload["title"], "title", max_chars=MAX_AI_PROPOSAL_TITLE_CHARS)
    description = _optional_string(payload["description"], "description", max_chars=MAX_AI_PROPOSAL_DESCRIPTION_CHARS)
    due_date = _optional_string(payload["proposed_due_date"], "proposed_due_date")
    if due_date:
        try:
            date.fromisoformat(due_date)
        except ValueError as exc:
            raise AiProposalValidationError("proposed_due_date must be ISO date") from exc
    confidence = payload["confidence"]
    if confidence is not None:
        _require(isinstance(confidence, int | float), "confidence must be numeric")
        confidence = float(confidence)
        _require(0.0 <= confidence <= 1.0, "confidence must be between 0.0 and 1.0")
    citations_payload = payload["citations"]
    _require(isinstance(citations_payload, list), "citations must be an array")
    _require(len(citations_payload) <= MAX_AI_PROPOSAL_CITATIONS, "too many citations")
    citations = [validate_ai_citation(item, strict=strict) for item in citations_payload]
    expected_output_type = _optional_enum_value(
        payload["expected_output_type"],
        ExpectedOutputType,
        "expected_output_type",
    )
    priority = _optional_enum_value(payload["priority"], Priority, "priority")
    complexity = _optional_enum_value(payload["complexity"], Complexity, "complexity")
    return AiProposal(
        external_proposal_id=external_proposal_id,
        title=title,
        description=description,
        proposed_unit_id=_optional_string(payload["proposed_unit_id"], "proposed_unit_id"),
        proposed_assignee_id=_optional_string(payload["proposed_assignee_id"], "proposed_assignee_id"),
        proposed_supervisor_id=_optional_string(payload["proposed_supervisor_id"], "proposed_supervisor_id"),
        proposed_due_date=due_date,
        expected_output=_optional_string(payload["expected_output"], "expected_output"),
        expected_output_type=expected_output_type,
        priority=priority,
        complexity=complexity,
        confidence=confidence,
        citations=citations,
        reasoning_summary=_optional_string(
            payload["reasoning_summary"],
            "reasoning_summary",
            max_chars=MAX_AI_PROPOSAL_REASONING_CHARS,
        ),
        warnings=_require_string_list(
            payload["warnings"],
            "warnings",
            allow_empty=True,
            max_items=MAX_WARNINGS_PER_PROPOSAL,
            max_chars=MAX_WARNING_LENGTH,
        ),
    )


def validate_ai_citation(payload: dict[str, Any], *, strict: bool = True) -> AiCitation:
    _require_object(payload, "citation")
    _reject_unknown(payload, CITATION_FIELDS, "citation", strict=strict)
    _require_fields(payload, CITATION_FIELDS, "citation")
    page_start = _require_positive_int(payload["page_start"], "page_start")
    page_end = _require_positive_int(payload["page_end"], "page_end")
    _require(page_end >= page_start, "page_end cannot be less than page_start")
    char_start = _optional_non_negative_int(payload["char_start"], "char_start")
    char_end = _optional_non_negative_int(payload["char_end"], "char_end")
    if char_start is not None and char_end is not None:
        _require(char_end >= char_start, "char_end cannot be less than char_start")
    return AiCitation(
        attachment_id=_require_string(payload["attachment_id"], "attachment_id"),
        page_start=page_start,
        page_end=page_end,
        excerpt=_require_string(payload["excerpt"], "excerpt", max_chars=MAX_AI_PROPOSAL_EXCERPT_CHARS),
        char_start=char_start,
        char_end=char_end,
    )


def _load_json_object(payload: str | bytes | dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload, bytes):
        _require(len(payload) <= MAX_AI_PROPOSAL_JSON_BYTES, "AI JSON payload is too large")
        text = payload.decode("utf-8")
        obj = json.loads(text)
    elif isinstance(payload, str):
        _require(len(payload.encode("utf-8")) <= MAX_AI_PROPOSAL_JSON_BYTES, "AI JSON payload is too large")
        obj = json.loads(payload)
    elif isinstance(payload, dict):
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        _require(len(encoded) <= MAX_AI_PROPOSAL_JSON_BYTES, "AI JSON payload is too large")
        obj = payload
    else:
        raise AiProposalValidationError("AI response must be a JSON object")
    _require_object(obj, "AI response")
    return obj


def _reject_unknown(payload: dict[str, Any], allowed: set[str], context: str, *, strict: bool) -> None:
    if not strict:
        return
    unknown = set(payload) - allowed
    _require(not unknown, f"{context} contains unknown fields: {', '.join(sorted(unknown))}")


def _require_fields(payload: dict[str, Any], required: set[str], context: str) -> None:
    missing = required - set(payload)
    _require(not missing, f"{context} is missing required fields: {', '.join(sorted(missing))}")


def _require_object(value: Any, context: str) -> None:
    _require(isinstance(value, dict), f"{context} must be an object")


def _require_string(value: Any, field_name: str, *, max_chars: int | None = None) -> str:
    _require(isinstance(value, str) and bool(value.strip()), f"{field_name} must be a non-empty string")
    if max_chars is not None:
        _require(len(value) <= max_chars, f"{field_name} is too long")
    return value


def _optional_string(value: Any, field_name: str, *, max_chars: int | None = None) -> str | None:
    if value is None:
        return None
    return _require_string(value, field_name, max_chars=max_chars)


def _require_string_list(
    value: Any,
    field_name: str,
    *,
    allow_empty: bool = False,
    max_items: int | None = None,
    max_chars: int | None = None,
) -> list[str]:
    _require(isinstance(value, list), f"{field_name} must be an array")
    if max_items is not None:
        _require(len(value) <= max_items, f"{field_name} contains too many items")
    if not allow_empty:
        _require(all(isinstance(item, str) and item.strip() for item in value), f"{field_name} must contain strings")
    else:
        _require(all(isinstance(item, str) for item in value), f"{field_name} must contain strings")
    if max_chars is not None:
        _require(all(len(item) <= max_chars for item in value), f"{field_name} item is too long")
    return list(value)


def _require_positive_int(value: Any, field_name: str) -> int:
    _require(isinstance(value, int) and value > 0, f"{field_name} must be a positive integer")
    return value


def _optional_non_negative_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    _require(isinstance(value, int) and value >= 0, f"{field_name} must be a non-negative integer")
    return value


def _optional_enum_value(value: Any, enum_type: Any, field_name: str) -> str | None:
    if value is None:
        return None
    _require(isinstance(value, str), f"{field_name} must be a string")
    try:
        enum_type(value)
    except ValueError as exc:
        raise AiProposalValidationError(f"{field_name} is not supported") from exc
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AiProposalValidationError(message)
