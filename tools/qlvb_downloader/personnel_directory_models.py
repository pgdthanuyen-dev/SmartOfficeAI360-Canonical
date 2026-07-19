from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .assignment_rule_models import RuleRoleType
from .domain_models import DomainModel, StrEnum, new_id, utc_now_iso


PERSONNEL_DIRECTORY_SCHEMA_VERSION = "1.0.0"
MAX_DIRECTORY_TEXT_CHARS = 500
MAX_SOURCE_REFERENCE_CHARS = 1000
MAX_SELECTION_EXPLANATION_CHARS = 2000
MAX_SELECTION_WARNINGS_CHARS = 4000


class UnitStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    SUPERSEDED = "SUPERSEDED"


class UnitType(StrEnum):
    ADMINISTRATIVE = "ADMINISTRATIVE"
    PROFESSIONAL = "PROFESSIONAL"
    PUBLIC_SERVICE = "PUBLIC_SERVICE"
    SECURITY_DEFENSE = "SECURITY_DEFENSE"
    COMMUNITY = "COMMUNITY"
    EXTERNAL = "EXTERNAL"
    OTHER = "OTHER"


class PersonnelStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    TRANSFERRED = "TRANSFERRED"
    RETIRED = "RETIRED"
    SUSPENDED = "SUSPENDED"


class ResponsibilityLevel(StrEnum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    SUPPORT = "SUPPORT"


class AvailabilityStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    LEAVE = "LEAVE"
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class SubstitutionStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class PersonnelSelectionDecision(StrEnum):
    SELECTED = "SELECTED"
    SELECTED_WITH_WARNING = "SELECTED_WITH_WARNING"
    NEEDS_CLASSIFICATION = "NEEDS_CLASSIFICATION"
    NO_ELIGIBLE_PERSON = "NO_ELIGIBLE_PERSON"
    CONFLICT = "CONFLICT"


@dataclass
class OrganizationUnit(DomainModel):
    tenant_id: str
    source_unit_key: str
    record_version: int
    unit_code: str
    unit_name: str
    unit_type: UnitType
    id: str = ""
    normalized_name: str = ""
    parent_unit_id: str | None = None
    status: UnitStatus = UnitStatus.ACTIVE
    effective_from: str | None = None
    effective_to: str | None = None
    source_reference: str | None = None
    row_version: int = 1
    created_at: str = ""
    updated_at: str = ""
    schema_version: str = PERSONNEL_DIRECTORY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        self.id = self.id or new_id()
        self.normalized_name = self.normalized_name or normalize_directory_text(self.unit_name)
        now = utc_now_iso()
        self.created_at = self.created_at or now
        self.updated_at = self.updated_at or now


@dataclass
class PersonnelRecord(DomainModel):
    tenant_id: str
    source_person_key: str
    record_version: int
    full_name: str
    id: str = ""
    normalized_name: str = ""
    position_title: str | None = None
    primary_unit_id: str | None = None
    status: PersonnelStatus = PersonnelStatus.ACTIVE
    effective_from: str | None = None
    effective_to: str | None = None
    source_reference: str | None = None
    row_version: int = 1
    created_at: str = ""
    updated_at: str = ""
    schema_version: str = PERSONNEL_DIRECTORY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        self.id = self.id or new_id()
        self.normalized_name = self.normalized_name or normalize_directory_text(self.full_name)
        now = utc_now_iso()
        self.created_at = self.created_at or now
        self.updated_at = self.updated_at or now


@dataclass
class PersonnelDomainAssignment(DomainModel):
    tenant_id: str
    personnel_id: str
    domain_code: str
    responsibility_level: ResponsibilityLevel
    id: str = ""
    subdomain_code: str | None = None
    is_primary: bool = False
    priority: int = 0
    effective_from: str | None = None
    effective_to: str | None = None
    source_reference: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        self.id = self.id or new_id()
        now = utc_now_iso()
        self.created_at = self.created_at or now
        self.updated_at = self.updated_at or now


@dataclass
class PersonnelRoleAssignment(DomainModel):
    tenant_id: str
    personnel_id: str
    unit_id: str
    role_type: RuleRoleType
    role_code: str
    id: str = ""
    is_primary: bool = False
    priority: int = 0
    effective_from: str | None = None
    effective_to: str | None = None
    source_reference: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        self.id = self.id or new_id()
        now = utc_now_iso()
        self.created_at = self.created_at or now
        self.updated_at = self.updated_at or now


@dataclass
class PersonnelSubstitution(DomainModel):
    tenant_id: str
    primary_personnel_id: str
    substitute_personnel_id: str
    role_type: RuleRoleType
    id: str = ""
    unit_id: str | None = None
    reason: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    status: SubstitutionStatus = SubstitutionStatus.ACTIVE
    source_reference: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        self.id = self.id or new_id()
        now = utc_now_iso()
        self.created_at = self.created_at or now
        self.updated_at = self.updated_at or now


@dataclass
class PersonnelAvailability(DomainModel):
    tenant_id: str
    personnel_id: str
    availability_status: AvailabilityStatus
    unavailable_from: str
    id: str = ""
    unavailable_to: str | None = None
    reason: str | None = None
    source_reference: str | None = None
    recorded_at: str = ""
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        self.id = self.id or new_id()
        now = utc_now_iso()
        self.recorded_at = self.recorded_at or now
        self.created_at = self.created_at or now
        self.updated_at = self.updated_at or now


@dataclass
class PersonnelSelectionMatch(DomainModel):
    tenant_id: str
    document_id: str
    document_revision: str
    role_type: RuleRoleType
    score: float
    decision: PersonnelSelectionDecision
    input_fingerprint: str
    id: str = ""
    assignment_rule_match_id: str | None = None
    unit_id: str | None = None
    personnel_id: str | None = None
    explanation: str | None = None
    warnings_json: str = "[]"
    created_at: str = ""

    def __post_init__(self) -> None:
        self.id = self.id or new_id()
        self.created_at = self.created_at or utc_now_iso()


def normalize_directory_text(value: str | None) -> str:
    text = unicodedata.normalize("NFC", str(value or "")).casefold()
    return re.sub(r"\s+", " ", text).strip()
