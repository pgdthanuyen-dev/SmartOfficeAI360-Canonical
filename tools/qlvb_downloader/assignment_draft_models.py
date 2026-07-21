"""Immutable, library-only contracts for the G05C assignment draft builder."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


ASSIGNMENT_DRAFT_BUILDER_VERSION = "g05c.builder.1"
PENDING_OFFICE_REVIEW = "PENDING_OFFICE_REVIEW"


@dataclass(frozen=True)
class AssignmentDraftBuildRequest:
    tenant_id: str
    source_system: str
    source_document_id: str
    source_revision: str
    document_number: str | None
    subject: str
    normalized_summary: str
    received_date: str | None
    issued_date: str | None
    proposed_task_title: str
    proposed_task_description: str
    proposed_start_date: str | None
    proposed_due_date: str | None
    proposed_priority: str | None
    issuing_agency: str | None = None
    proposed_deliverables: list[str] = field(default_factory=list)
    proposed_checklist_items: list[str] = field(default_factory=list)
    proposed_milestones: list[str] = field(default_factory=list)
    g05a_proposal: Any = None
    g05b_proposal: Any = None
    file_reference_placeholder: str | None = None


@dataclass(frozen=True)
class AssignmentDraftPersonnelProposal:
    personnel_source_key: str
    role_type: str
    proposal_source: str
    is_substitute: bool
    confidence: float
    item_order: int


@dataclass(frozen=True)
class AssignmentDraftWarning:
    code: str
    severity: str
    field_or_role: str | None
    message: str
    suggested_action: str


@dataclass(frozen=True)
class AssignmentDraftCandidate:
    tenant_id: str
    source_system: str
    source_document_id: str
    source_revision: str
    source_identity_key: str
    initial_status: str
    task_title: str
    task_description: str
    lead_unit_source_key: str | None
    participating_unit_source_keys: tuple[str, ...]
    required_roles: tuple[str, ...]
    proposed_personnel: tuple[AssignmentDraftPersonnelProposal, ...]
    proposed_start_date: str | None
    proposed_due_date: str | None
    priority: str
    deliverables: tuple[str, ...]
    checklist_items: tuple[str, ...]
    milestones: tuple[str, ...]
    warnings: tuple[AssignmentDraftWarning, ...]
    unresolved_items: tuple[str, ...]
    overall_confidence: float
    source_engine_versions: tuple[tuple[str, str], ...]
    source_fingerprints: tuple[tuple[str, str], ...]
    source_input_fingerprint: str
    draft_content_fingerprint: str
    builder_version: str = ASSIGNMENT_DRAFT_BUILDER_VERSION
    document_number: str | None = None
    subject: str | None = None
    issuing_agency: str | None = None
