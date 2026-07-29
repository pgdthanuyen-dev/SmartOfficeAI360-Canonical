"""Immutable, transport-neutral G06-D0 projection contracts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Mapping

CONTRACT_VERSION = "v1"
SOURCE_SYSTEM = "SMARTOFFICE_AI360"
ACTION_ITEM_PROVENANCE_INCOMPLETE = "ACTION_ITEM_PROVENANCE_INCOMPLETE"
ASSIGNMENT_PROVENANCE_INCOMPLETE = "ASSIGNMENT_PROVENANCE_INCOMPLETE"
PRIMARY_ASSIGNEE_UNRESOLVED = "PRIMARY_ASSIGNEE_UNRESOLVED"
COORDINATING_UNITS_UNAVAILABLE = "COORDINATING_UNITS_UNAVAILABLE"
SAFE_ATTACHMENT_URL_UNAVAILABLE = "SAFE_ATTACHMENT_URL_UNAVAILABLE"
SOURCE_DOCUMENT_METADATA_INCOMPLETE = "SOURCE_DOCUMENT_METADATA_INCOMPLETE"


@dataclass(frozen=True)
class PlannerDraftHandoffProjectionV1:
    contract_version: str
    tenant_id: str
    tenant_key: str
    source_system: str
    source_document_id: str
    source_draft_id: str
    source_draft_version: int
    document_number: str | None
    title: str | None
    issuing_agency: str | None
    issued_date: str | None
    received_date: str | None
    summary: str | None
    required_action: str | None
    action_items: tuple[Mapping[str, object], ...]
    lead_unit_source_key: str | None
    primary_assignee_source_key: str | None
    coordinating_unit_source_keys: tuple[str, ...]
    assignment_reason: str | None
    confidence: float | None
    source_rules: tuple[str, ...]
    manual_review_required: bool
    review_reasons: tuple[str, ...]
    due_date: str | None
    priority: str | None
    attachments: tuple[Mapping[str, object], ...]
    source_proposal_ids: tuple[str, ...]
    generator_version: str
    warning_codes: tuple[str, ...]
    is_complete_for_transport: bool


@dataclass(frozen=True)
class PlannerDraftHandoffEnvelopeV1:
    envelope_id: str
    contract_version: str
    source_system: str
    tenant_id: str
    tenant_key: str
    source_document_id: str
    source_draft_id: str
    source_draft_version: int
    canonical_payload_json: str
    payload_sha256: str
    created_at: str
    projection: PlannerDraftHandoffProjectionV1 | None = None
