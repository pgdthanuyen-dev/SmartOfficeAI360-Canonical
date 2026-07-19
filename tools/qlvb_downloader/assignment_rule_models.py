from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from .domain_models import DomainModel, StrEnum, new_id, utc_now_iso


ASSIGNMENT_RULE_SCHEMA_VERSION = "1.0.0"
MAX_RULE_TEXT_CHARS = 500
MAX_RULE_VALUE_CHARS = 1000
MAX_MATCH_EXPLANATION_CHARS = 2000
MAX_MATCH_WARNINGS_JSON_CHARS = 4000
MAX_SOURCE_REFERENCE_CHARS = 1000


class RuleStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    SUPERSEDED = "SUPERSEDED"


class ConditionType(StrEnum):
    DOMAIN = "DOMAIN"
    SUBDOMAIN = "SUBDOMAIN"
    DOCUMENT_TYPE = "DOCUMENT_TYPE"
    ISSUER_GROUP = "ISSUER_GROUP"
    REQUIRED_ACTION = "REQUIRED_ACTION"
    REQUIRED_KEYWORD = "REQUIRED_KEYWORD"
    PREFERRED_KEYWORD = "PREFERRED_KEYWORD"
    TARGET_ENTITY = "TARGET_ENTITY"
    EXPECTED_OUTPUT = "EXPECTED_OUTPUT"


class ExclusionType(StrEnum):
    EXCLUDED_KEYWORD = "EXCLUDED_KEYWORD"
    EXCLUDED_ACTION = "EXCLUDED_ACTION"
    EXCLUDED_ISSUER = "EXCLUDED_ISSUER"
    EXCLUDED_DOCUMENT_TYPE = "EXCLUDED_DOCUMENT_TYPE"


class RuleUnitType(StrEnum):
    LEAD_UNIT = "LEAD_UNIT"
    COORDINATING_UNIT = "COORDINATING_UNIT"


class RuleRoleType(StrEnum):
    LEADER = "LEADER"
    MONITOR = "MONITOR"
    LEAD_EXECUTOR = "LEAD_EXECUTOR"
    CO_EXECUTOR = "CO_EXECUTOR"


class MatchDecision(StrEnum):
    MATCHED = "MATCHED"
    MATCHED_WITH_WARNING = "MATCHED_WITH_WARNING"
    NEEDS_CLASSIFICATION = "NEEDS_CLASSIFICATION"
    EXCLUDED = "EXCLUDED"
    NO_MATCH = "NO_MATCH"


class MatchWarningCode(StrEnum):
    MULTIPLE_TOP_RULES = "MULTIPLE_TOP_RULES"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    MISSING_REQUIRED_SIGNAL = "MISSING_REQUIRED_SIGNAL"
    UNIT_UNRESOLVED = "UNIT_UNRESOLVED"
    ROLE_UNRESOLVED = "ROLE_UNRESOLVED"
    RULE_NEAR_EXPIRY = "RULE_NEAR_EXPIRY"
    CONFLICTING_RULES = "CONFLICTING_RULES"


class MatchMode(StrEnum):
    EXACT = "EXACT"
    CONTAINS = "CONTAINS"
    TOKEN = "TOKEN"
    PREFIX = "PREFIX"
    REGEX_SAFE = "REGEX_SAFE"


@dataclass
class AssignmentRule(DomainModel):
    tenant_id: str
    rule_code: str
    version: str
    rule_name: str
    domain_code: str
    subdomain_code: str | None = None
    task_type: str | None = None
    id: str = ""
    description: str | None = None
    priority: int = 0
    minimum_confidence: int = 0
    default_due_days: int | None = None
    signature_buffer_days: int | None = None
    draft_required: bool = False
    draft_type: str | None = None
    source_reference: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    status: RuleStatus = RuleStatus.DRAFT
    created_at: str = ""
    updated_at: str = ""
    schema_version: str = ASSIGNMENT_RULE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.id:
            self.id = new_id()
        now = utc_now_iso()
        self.created_at = self.created_at or now
        self.updated_at = self.updated_at or now


@dataclass
class AssignmentRuleCondition(DomainModel):
    rule_id: str
    condition_type: ConditionType
    value: str
    id: str = ""
    normalized_value: str = ""
    weight: int = 0
    is_required: bool = False
    match_mode: MatchMode = MatchMode.CONTAINS
    sort_order: int = 0
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = new_id()
        self.normalized_value = self.normalized_value or normalize_rule_text(self.value)
        self.created_at = self.created_at or utc_now_iso()


@dataclass
class AssignmentRuleExclusion(DomainModel):
    rule_id: str
    exclusion_type: ExclusionType
    value: str
    id: str = ""
    normalized_value: str = ""
    penalty: int = 0
    is_hard_exclusion: bool = True
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = new_id()
        self.normalized_value = self.normalized_value or normalize_rule_text(self.value)
        self.created_at = self.created_at or utc_now_iso()


@dataclass
class AssignmentRuleUnit(DomainModel):
    rule_id: str
    unit_type: RuleUnitType
    source_unit_key: str
    unit_name: str
    id: str = ""
    priority: int = 0
    is_required: bool = False
    effective_from: str | None = None
    effective_to: str | None = None
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = new_id()
        self.created_at = self.created_at or utc_now_iso()


@dataclass
class AssignmentRuleRole(DomainModel):
    rule_id: str
    role_type: RuleRoleType
    role_code: str
    unit_source_key: str
    id: str = ""
    is_required: bool = False
    priority: int = 0
    effective_from: str | None = None
    effective_to: str | None = None
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = new_id()
        self.created_at = self.created_at or utc_now_iso()


@dataclass
class AssignmentRuleMatch(DomainModel):
    tenant_id: str
    document_id: str
    document_revision: str
    rule_id: str
    rule_code: str
    rule_version: str
    score: int
    decision: MatchDecision
    matched_condition_count: int
    required_condition_count: int
    exclusion_count: int
    input_fingerprint: str
    id: str = ""
    explanation: str | None = None
    warnings_json: str = "[]"
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = new_id()
        self.created_at = self.created_at or utc_now_iso()


@dataclass
class AssignmentRuleBundle(DomainModel):
    rule: AssignmentRule
    conditions: list[AssignmentRuleCondition] = field(default_factory=list)
    exclusions: list[AssignmentRuleExclusion] = field(default_factory=list)
    units: list[AssignmentRuleUnit] = field(default_factory=list)
    roles: list[AssignmentRuleRole] = field(default_factory=list)


def normalize_rule_text(value: Any) -> str:
    text = unicodedata.normalize("NFC", str(value or "")).casefold()
    text = re.sub(r"\s+", " ", text).strip()
    return text
