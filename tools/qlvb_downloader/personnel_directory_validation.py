from __future__ import annotations

import json
import math
import re
from datetime import date
from typing import Iterable

from .assignment_rule_models import RuleRoleType
from .domain_models import parse_utc_datetime
from .personnel_directory_models import (
    MAX_DIRECTORY_TEXT_CHARS,
    MAX_SELECTION_EXPLANATION_CHARS,
    MAX_SELECTION_WARNINGS_CHARS,
    MAX_SOURCE_REFERENCE_CHARS,
    OrganizationUnit,
    PersonnelAvailability,
    PersonnelDomainAssignment,
    PersonnelRecord,
    PersonnelRoleAssignment,
    PersonnelSelectionMatch,
    PersonnelSubstitution,
)
from .personnel_directory_models import MAX_SELECTION_WARNING_COUNT, MAX_SELECTION_WARNING_LENGTH


_SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")
_WARNING_CODES = {'UNIT_NOT_FOUND','UNIT_VERSION_CONFLICT','NO_ELIGIBLE_PERSON','PERSONNEL_STATUS_INELIGIBLE','PERSONNEL_OUTSIDE_EFFECTIVE_DATE','ROLE_NOT_MATCHED','DOMAIN_NOT_MATCHED','AVAILABILITY_BLOCKED','AVAILABILITY_CONFLICT','SUBSTITUTE_USED','SUBSTITUTION_CHAIN_UNSUPPORTED','SUBSTITUTION_CYCLE_DETECTED','MULTIPLE_TOP_PERSONNEL','REQUIRED_ROLE_UNRESOLVED','PERSONNEL_DIRECTORY_INCOMPLETE','PERSONNEL_CONFLICT','CO_EXECUTOR_COUNT_SHORTFALL'}
_SENSITIVE = re.compile(r'(?i)(authorization\s*:|bearer\s+|access_token|cookie=|https?://|[a-z]:\\\\|\\\\\\\\|planner_user_id|select\s+\*|traceback)')


class PersonnelDirectoryValidationError(ValueError):
    pass


class PersonnelDirectoryConflictError(PersonnelDirectoryValidationError):
    pass


def validate_unit(unit: OrganizationUnit) -> None:
    _required(unit.tenant_id, "unit.tenant_id")
    _required(unit.source_unit_key, "unit.source_unit_key")
    _required(unit.unit_code, "unit.unit_code")
    _text(unit.unit_name, "unit.unit_name")
    _positive(unit.record_version, "unit.record_version")
    _positive(unit.row_version, "unit.row_version")
    _date_pair(unit.effective_from, unit.effective_to, "unit")
    _optional_text(unit.source_reference, "unit.source_reference", MAX_SOURCE_REFERENCE_CHARS)
    _datetime(unit.created_at, "unit.created_at")
    _datetime(unit.updated_at, "unit.updated_at")


def validate_personnel(personnel: PersonnelRecord) -> None:
    _required(personnel.tenant_id, "personnel.tenant_id")
    _required(personnel.source_person_key, "personnel.source_person_key")
    _text(personnel.full_name, "personnel.full_name")
    if "cần cập nhật" in personnel.full_name.casefold() or "can cap nhat" in personnel.full_name.casefold():
        raise PersonnelDirectoryValidationError("personnel.full_name cannot be an import placeholder")
    _positive(personnel.record_version, "personnel.record_version")
    _positive(personnel.row_version, "personnel.row_version")
    _date_pair(personnel.effective_from, personnel.effective_to, "personnel")
    _optional_text(personnel.position_title, "personnel.position_title", MAX_DIRECTORY_TEXT_CHARS)
    _optional_text(personnel.source_reference, "personnel.source_reference", MAX_SOURCE_REFERENCE_CHARS)
    _datetime(personnel.created_at, "personnel.created_at")
    _datetime(personnel.updated_at, "personnel.updated_at")


def validate_domain_assignment(assignment: PersonnelDomainAssignment) -> None:
    _required(assignment.tenant_id, "domain.tenant_id")
    _required(assignment.personnel_id, "domain.personnel_id")
    _required(assignment.domain_code, "domain.domain_code")
    _non_negative(assignment.priority, "domain.priority")
    _date_pair(assignment.effective_from, assignment.effective_to, "domain")
    _optional_text(assignment.source_reference, "domain.source_reference", MAX_SOURCE_REFERENCE_CHARS)


def validate_role_assignment(assignment: PersonnelRoleAssignment) -> None:
    _required(assignment.tenant_id, "role.tenant_id")
    _required(assignment.personnel_id, "role.personnel_id")
    _required(assignment.unit_id, "role.unit_id")
    _required(assignment.role_code, "role.role_code")
    if assignment.role_type not in set(RuleRoleType):
        raise PersonnelDirectoryValidationError("role.role_type is invalid")
    _non_negative(assignment.priority, "role.priority")
    _date_pair(assignment.effective_from, assignment.effective_to, "role")


def validate_substitution(substitution: PersonnelSubstitution) -> None:
    _required(substitution.tenant_id, "substitution.tenant_id")
    _required(substitution.primary_personnel_id, "substitution.primary_personnel_id")
    _required(substitution.substitute_personnel_id, "substitution.substitute_personnel_id")
    if substitution.primary_personnel_id == substitution.substitute_personnel_id:
        raise PersonnelDirectoryValidationError("substitution cannot reference itself")
    _date_pair(substitution.effective_from, substitution.effective_to, "substitution")
    _optional_text(substitution.reason, "substitution.reason", MAX_DIRECTORY_TEXT_CHARS)


def validate_availability(availability: PersonnelAvailability) -> None:
    _required(availability.tenant_id, "availability.tenant_id")
    _required(availability.personnel_id, "availability.personnel_id")
    _required(availability.unavailable_from, "availability.unavailable_from")
    _date_pair(availability.unavailable_from, availability.unavailable_to, "availability")
    _optional_text(availability.reason, "availability.reason", MAX_DIRECTORY_TEXT_CHARS)
    _datetime(availability.recorded_at, "availability.recorded_at")


def validate_selection_match(match: PersonnelSelectionMatch) -> None:
    _required(match.tenant_id, "selection.tenant_id")
    _required(match.document_id, "selection.document_id")
    _required(match.document_revision, "selection.document_revision")
    if not isinstance(match.score, (int, float)) or not math.isfinite(match.score) or not 0 <= match.score <= 100:
        raise PersonnelDirectoryValidationError("selection.score must be between 0 and 100")
    if match.role_type not in set(RuleRoleType) or match.decision not in set(__import__('tools.qlvb_downloader.personnel_directory_models', fromlist=['PersonnelSelectionDecision']).PersonnelSelectionDecision):
        raise PersonnelDirectoryValidationError("selection role or decision is invalid")
    if not _SHA256_RE.fullmatch(match.input_fingerprint or ""):
        raise PersonnelDirectoryValidationError("selection.input_fingerprint must be SHA-256")
    _optional_text(match.explanation, "selection.explanation", MAX_SELECTION_EXPLANATION_CHARS)
    if match.explanation and _SENSITIVE.search(match.explanation): raise PersonnelDirectoryValidationError("selection.explanation contains disallowed content")
    if len(match.warnings_json) > MAX_SELECTION_WARNINGS_CHARS:
        raise PersonnelDirectoryValidationError("selection.warnings_json is too long")
    try:
        warnings = json.loads(match.warnings_json)
    except json.JSONDecodeError as exc:
        raise PersonnelDirectoryValidationError("selection.warnings_json must be JSON") from exc
    if not isinstance(warnings, list):
        raise PersonnelDirectoryValidationError("selection.warnings_json must be a JSON array")
    if len(warnings) > MAX_SELECTION_WARNING_COUNT or any(not isinstance(w,str) or len(w)>MAX_SELECTION_WARNING_LENGTH or w not in _WARNING_CODES for w in warnings):
        raise PersonnelDirectoryValidationError("selection warnings are invalid")


def date_ranges_overlap(
    left_from: str | None, left_to: str | None, right_from: str | None, right_to: str | None
) -> bool:
    return (left_to is None or right_from is None or left_to >= right_from) and (
        right_to is None or left_from is None or right_to >= left_from
    )


def assert_no_directed_cycle(edges: Iterable[tuple[str, str]], start: str, target: str, message: str) -> None:
    graph: dict[str, set[str]] = {}
    for source, destination in edges:
        graph.setdefault(source, set()).add(destination)
    graph.setdefault(start, set()).add(target)
    pending = [target]
    visited: set[str] = set()
    while pending:
        current = pending.pop()
        if current == start:
            raise PersonnelDirectoryValidationError(message)
        if current not in visited:
            visited.add(current)
            pending.extend(graph.get(current, ()))


def _required(value: object, field_name: str) -> None:
    if value is None or not str(value).strip():
        raise PersonnelDirectoryValidationError(f"{field_name} is required")


def _text(value: str, field_name: str) -> None:
    _required(value, field_name)
    if len(value) > MAX_DIRECTORY_TEXT_CHARS:
        raise PersonnelDirectoryValidationError(f"{field_name} is too long")


def _optional_text(value: str | None, field_name: str, limit: int) -> None:
    if value is not None and len(value) > limit:
        raise PersonnelDirectoryValidationError(f"{field_name} is too long")


def _positive(value: int, field_name: str) -> None:
    if not isinstance(value, int) or value < 1:
        raise PersonnelDirectoryValidationError(f"{field_name} must be a positive integer")


def _non_negative(value: int, field_name: str) -> None:
    if not isinstance(value, int) or value < 0:
        raise PersonnelDirectoryValidationError(f"{field_name} must be non-negative")


def _date_pair(start: str | None, end: str | None, field_name: str) -> None:
    for value in (start, end):
        if value is not None:
            try:
                date.fromisoformat(value)
            except ValueError as exc:
                raise PersonnelDirectoryValidationError(f"{field_name} dates must be ISO dates") from exc
    if start and end and end < start:
        raise PersonnelDirectoryValidationError(f"{field_name} end cannot be before start")


def _datetime(value: str, field_name: str) -> None:
    try:
        parse_utc_datetime(value)
    except Exception as exc:
        raise PersonnelDirectoryValidationError(f"{field_name} must be UTC ISO-8601") from exc
