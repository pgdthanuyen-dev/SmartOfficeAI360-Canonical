from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from .assignment_rule_models import (
    MAX_MATCH_EXPLANATION_CHARS,
    MAX_MATCH_WARNINGS_JSON_CHARS,
    MAX_RULE_TEXT_CHARS,
    MAX_RULE_VALUE_CHARS,
    AssignmentRule,
    AssignmentRuleCondition,
    AssignmentRuleExclusion,
    AssignmentRuleMatch,
    AssignmentRuleRole,
    AssignmentRuleUnit,
    MatchMode,
    RuleRoleType,
    RuleUnitType,
)
from .domain_models import parse_utc_datetime


SAFE_REGEX_MAX_CHARS = 200
_SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")


class AssignmentRuleValidationError(ValueError):
    pass


def validate_rule(rule: AssignmentRule) -> None:
    _require_non_empty(rule.id, "rule.id")
    _require_non_empty(rule.tenant_id, "rule.tenant_id")
    _require_non_empty(rule.rule_code, "rule.rule_code")
    _require_non_empty(rule.version, "rule.version")
    _require_non_empty(rule.rule_name, "rule.rule_name")
    _require_non_empty(rule.domain_code, "rule.domain_code")
    _require(isinstance(rule.priority, int), "rule.priority must be an integer")
    _require(0 <= rule.minimum_confidence <= 100, "rule.minimum_confidence must be between 0 and 100")
    _validate_non_negative_days(rule.default_due_days, "rule.default_due_days")
    _validate_non_negative_days(rule.signature_buffer_days, "rule.signature_buffer_days")
    _validate_iso_date(rule.effective_from, "rule.effective_from")
    _validate_iso_date(rule.effective_to, "rule.effective_to")
    if rule.effective_from and rule.effective_to:
        _require(rule.effective_to >= rule.effective_from, "rule.effective_to cannot be before effective_from")
    _validate_text(rule.rule_code, "rule.rule_code", MAX_RULE_TEXT_CHARS)
    _validate_text(rule.version, "rule.version", MAX_RULE_TEXT_CHARS)
    _validate_text(rule.rule_name, "rule.rule_name", MAX_RULE_TEXT_CHARS)
    _validate_optional_text(rule.source_reference, "rule.source_reference", MAX_RULE_VALUE_CHARS)
    _validate_datetime(rule.created_at, "rule.created_at")
    _validate_datetime(rule.updated_at, "rule.updated_at")


def validate_condition(condition: AssignmentRuleCondition) -> None:
    _require_non_empty(condition.id, "condition.id")
    _require_non_empty(condition.rule_id, "condition.rule_id")
    _validate_text(condition.value, "condition.value", MAX_RULE_VALUE_CHARS)
    _validate_text(condition.normalized_value, "condition.normalized_value", MAX_RULE_VALUE_CHARS)
    _require(isinstance(condition.weight, int), "condition.weight must be an integer")
    _require(isinstance(condition.sort_order, int), "condition.sort_order must be an integer")
    if condition.match_mode == MatchMode.REGEX_SAFE:
        _validate_safe_regex(condition.value)
    _validate_datetime(condition.created_at, "condition.created_at")


def validate_exclusion(exclusion: AssignmentRuleExclusion) -> None:
    _require_non_empty(exclusion.id, "exclusion.id")
    _require_non_empty(exclusion.rule_id, "exclusion.rule_id")
    _validate_text(exclusion.value, "exclusion.value", MAX_RULE_VALUE_CHARS)
    _validate_text(exclusion.normalized_value, "exclusion.normalized_value", MAX_RULE_VALUE_CHARS)
    _require(exclusion.penalty >= 0, "exclusion.penalty cannot be negative")
    _validate_datetime(exclusion.created_at, "exclusion.created_at")


def validate_unit(unit: AssignmentRuleUnit) -> None:
    _require_non_empty(unit.id, "unit.id")
    _require_non_empty(unit.rule_id, "unit.rule_id")
    _require_non_empty(unit.source_unit_key, "unit.source_unit_key")
    _require_non_empty(unit.unit_name, "unit.unit_name")
    _require(isinstance(unit.priority, int), "unit.priority must be an integer")
    _validate_effective_pair(unit.effective_from, unit.effective_to, "unit")
    _validate_datetime(unit.created_at, "unit.created_at")


def validate_role(role: AssignmentRuleRole) -> None:
    _require_non_empty(role.id, "role.id")
    _require_non_empty(role.rule_id, "role.rule_id")
    _require_non_empty(role.role_code, "role.role_code")
    _require_non_empty(role.unit_source_key, "role.unit_source_key")
    _require(isinstance(role.priority, int), "role.priority must be an integer")
    _validate_effective_pair(role.effective_from, role.effective_to, "role")
    _validate_datetime(role.created_at, "role.created_at")


def validate_match(match: AssignmentRuleMatch) -> None:
    _require_non_empty(match.id, "match.id")
    _require_non_empty(match.tenant_id, "match.tenant_id")
    _require_non_empty(match.document_id, "match.document_id")
    _require_non_empty(match.document_revision, "match.document_revision")
    _require_non_empty(match.rule_id, "match.rule_id")
    _require_non_empty(match.rule_code, "match.rule_code")
    _require_non_empty(match.rule_version, "match.rule_version")
    _require(0 <= match.score <= 100, "match.score must be between 0 and 100")
    _require(match.matched_condition_count >= 0, "match.matched_condition_count cannot be negative")
    _require(match.required_condition_count >= 0, "match.required_condition_count cannot be negative")
    _require(match.exclusion_count >= 0, "match.exclusion_count cannot be negative")
    _validate_sha(match.input_fingerprint, "match.input_fingerprint")
    _validate_optional_text(match.explanation, "match.explanation", MAX_MATCH_EXPLANATION_CHARS)
    _require(len(match.warnings_json) <= MAX_MATCH_WARNINGS_JSON_CHARS, "match.warnings_json is too long")
    try:
        decoded = json.loads(match.warnings_json)
    except json.JSONDecodeError as exc:
        raise AssignmentRuleValidationError("match.warnings_json must be JSON") from exc
    _require(isinstance(decoded, list), "match.warnings_json must be a JSON array")
    _validate_datetime(match.created_at, "match.created_at")


def validate_rule_bundle(
    rule: AssignmentRule,
    conditions: list[AssignmentRuleCondition],
    exclusions: list[AssignmentRuleExclusion],
    units: list[AssignmentRuleUnit],
    roles: list[AssignmentRuleRole],
) -> None:
    validate_rule(rule)
    seen_conditions: set[tuple[str, str, str]] = set()
    for condition in conditions:
        _require(condition.rule_id == rule.id, "condition.rule_id must match rule.id")
        validate_condition(condition)
        key = (condition.condition_type.value, condition.normalized_value, condition.match_mode.value)
        _require(key not in seen_conditions, "duplicate condition in rule")
        seen_conditions.add(key)
    for exclusion in exclusions:
        _require(exclusion.rule_id == rule.id, "exclusion.rule_id must match rule.id")
        validate_exclusion(exclusion)
    lead_units = [unit for unit in units if unit.unit_type == RuleUnitType.LEAD_UNIT]
    _require(len(lead_units) <= 1, "rule cannot contain duplicate lead units")
    for unit in units:
        _require(unit.rule_id == rule.id, "unit.rule_id must match rule.id")
        validate_unit(unit)
    required_role_types: set[RuleRoleType] = set()
    for role in roles:
        _require(role.rule_id == rule.id, "role.rule_id must match rule.id")
        validate_role(role)
        if role.is_required:
            _require(role.role_type not in required_role_types, "duplicate required role type in rule")
            required_role_types.add(role.role_type)


def _validate_safe_regex(value: str) -> None:
    _require(len(value) <= SAFE_REGEX_MAX_CHARS, "REGEX_SAFE pattern is too long")
    try:
        re.compile(value)
    except re.error as exc:
        raise AssignmentRuleValidationError("REGEX_SAFE pattern is invalid") from exc


def _validate_effective_pair(effective_from: str | None, effective_to: str | None, context: str) -> None:
    _validate_iso_date(effective_from, f"{context}.effective_from")
    _validate_iso_date(effective_to, f"{context}.effective_to")
    if effective_from and effective_to:
        _require(effective_to >= effective_from, f"{context}.effective_to cannot be before effective_from")


def _validate_non_negative_days(value: int | None, field_name: str) -> None:
    if value is None:
        return
    _require(isinstance(value, int) and value >= 0, f"{field_name} must be a non-negative integer")


def _validate_iso_date(value: str | None, field_name: str) -> None:
    if value in (None, ""):
        return
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise AssignmentRuleValidationError(f"{field_name} must be ISO date") from exc


def _validate_datetime(value: str | None, field_name: str) -> None:
    if value in (None, ""):
        return
    try:
        parse_utc_datetime(value)
    except Exception as exc:
        raise AssignmentRuleValidationError(f"{field_name} must be timezone-aware ISO datetime") from exc


def _validate_sha(value: str | None, field_name: str) -> None:
    _require(bool(value and _SHA256_RE.match(value)), f"{field_name} must be a SHA-256 hex digest")


def _validate_text(value: str, field_name: str, max_chars: int) -> None:
    _require(isinstance(value, str) and bool(value.strip()), f"{field_name} must be a non-empty string")
    _require(len(value) <= max_chars, f"{field_name} is too long")


def _validate_optional_text(value: str | None, field_name: str, max_chars: int) -> None:
    if value is None:
        return
    _require(isinstance(value, str), f"{field_name} must be a string")
    _require(len(value) <= max_chars, f"{field_name} is too long")


def _require_non_empty(value: str | None, field_name: str) -> None:
    _require(isinstance(value, str) and bool(value.strip()), f"{field_name} is required")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssignmentRuleValidationError(message)
