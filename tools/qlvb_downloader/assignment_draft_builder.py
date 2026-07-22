"""Deterministic, side-effect-free G05C assignment draft builder."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from typing import Any

from .assignment_draft_models import (
    ASSIGNMENT_DRAFT_BUILDER_VERSION,
    PENDING_OFFICE_REVIEW,
    AssignmentDraftBuildRequest,
    AssignmentDraftCandidate,
    AssignmentDraftPersonnelProposal,
    AssignmentDraftSourceAttachment,
    AssignmentDraftWarning,
)
from .assignment_draft_validation import (
    MAX_CHECKLIST_ITEMS,
    MAX_DELIVERABLES,
    MAX_DOCUMENT_NUMBER_LENGTH,
    MAX_ISSUING_AGENCY_LENGTH,
    MAX_MILESTONES,
    MAX_SUMMARY_LENGTH,
    MAX_SUBJECT_LENGTH,
    MAX_UNIT_KEY_LENGTH,
    MAX_WARNING_ACTION_LENGTH,
    MAX_WARNING_MESSAGE_LENGTH,
    MAX_WARNINGS,
    normalize_date,
    normalize_optional_text,
    normalize_priority,
    normalize_set_list,
    normalize_text,
    normalize_text_list,
    proposal_recommendation,
    validate_build_request,
    AssignmentDraftValidationError,
)
from .assignment_draft_source_metadata import normalize_source_attachments


_ROLE_ORDER = {"LEADER": 0, "MONITOR": 1, "LEAD_EXECUTOR": 2, "CO_EXECUTOR": 3}


def _value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _warning(code: str, field_or_role: str | None, message: str, action: str) -> AssignmentDraftWarning:
    return AssignmentDraftWarning(
        code=code,
        severity="REVIEW_REQUIRED",
        field_or_role=field_or_role,
        message=normalize_text(message, "warning.message", MAX_WARNING_MESSAGE_LENGTH, required=True),
        suggested_action=normalize_text(action, "warning.suggested_action", MAX_WARNING_ACTION_LENGTH, required=True),
    )


class AssignmentDraftBuilder:
    """Merge G05A and G05B proposals without persistence or external calls."""

    def build(self, request: AssignmentDraftBuildRequest, *, source_attachments: tuple[AssignmentDraftSourceAttachment, ...] = ()) -> AssignmentDraftCandidate:
        validate_build_request(request)
        g05a = proposal_recommendation(request.g05a_proposal)
        g05b = proposal_recommendation(request.g05b_proposal)
        source_system = normalize_text(request.source_system, "source_system", 200, required=True)
        document_id = normalize_text(request.source_document_id, "source_document_id", 500, required=True)
        revision = normalize_text(request.source_revision, "source_revision", 200, required=True)
        document_number = normalize_optional_text(request.document_number, "document_number", MAX_DOCUMENT_NUMBER_LENGTH)
        subject = normalize_text(request.subject, "subject", MAX_SUBJECT_LENGTH)
        issuing_agency = normalize_optional_text(request.issuing_agency, "issuing_agency", MAX_ISSUING_AGENCY_LENGTH)
        title = normalize_text(request.proposed_task_title, "proposed_task_title", 300, required=True)
        description = normalize_text(request.proposed_task_description, "proposed_task_description", 10_000)
        received_date = normalize_date(request.received_date, "received_date")
        issued_date = normalize_date(request.issued_date, "issued_date")
        summary = normalize_optional_text(request.normalized_summary, "normalized_summary", MAX_SUMMARY_LENGTH)
        attachments = normalize_source_attachments(source_attachments)
        start_date = normalize_date(request.proposed_start_date, "proposed_start_date")
        due_date = normalize_date(request.proposed_due_date, "proposed_due_date")
        priority = normalize_priority(request.proposed_priority)
        lead_unit = normalize_optional_text(getattr(g05a, "lead_unit_key", None), "g05a_proposal.lead_unit_key", MAX_UNIT_KEY_LENGTH)
        units = normalize_set_list(getattr(g05a, "coordinating_unit_keys", []), "g05a_proposal.coordinating_unit_keys", 20)
        units = tuple(unit for unit in units if unit != lead_unit)
        required_roles = tuple(sorted({_value(role) for role in getattr(g05a, "required_roles", [])}, key=lambda role: (_ROLE_ORDER.get(role, 99), role)))
        personnel, unresolved_roles, personnel_warnings = self._personnel(g05b, required_roles)
        warnings = self._warnings(request, g05a, g05b, lead_unit, personnel, unresolved_roles, personnel_warnings, received_date, start_date, due_date)
        unresolved_items = tuple(unresolved_roles)
        confidence_values = [float(getattr(g05a, "confidence", 0)), float(getattr(g05b, "overall_confidence", 0)), 100.0]
        overall_confidence = min(confidence_values)
        if overall_confidence < 75:
            warnings.append(_warning("LOW_CONFIDENCE_REVIEW_REQUIRED", None, "Overall confidence is low.", "Review the proposal evidence."))
        warnings = self._canonical_warnings(warnings)
        source_versions = (("g05a", str(getattr(g05a, "engine_version"))), ("g05b", str(getattr(g05b, "engine_version"))))
        source_fingerprints = (("g05a", str(getattr(g05a, "input_fingerprint"))), ("g05b", str(getattr(g05b, "input_fingerprint"))))
        deliverables = normalize_text_list(request.proposed_deliverables, "proposed_deliverables", MAX_DELIVERABLES)
        checklist = normalize_text_list(request.proposed_checklist_items, "proposed_checklist_items", MAX_CHECKLIST_ITEMS)
        milestones = normalize_text_list(request.proposed_milestones, "proposed_milestones", MAX_MILESTONES)
        source_identity_key = f"{source_system}:{document_id}"
        source_input_fingerprint = _sha256({
            "tenant_id": request.tenant_id.strip(), "source_identity_key": source_identity_key, "source_revision": revision,
            "g05a": dict(source_fingerprints)["g05a"], "g05a_version": dict(source_versions)["g05a"],
            "g05b": dict(source_fingerprints)["g05b"], "g05b_version": dict(source_versions)["g05b"],
            "task_title": title, "task_description": description, "priority": priority, "start_date": start_date, "due_date": due_date,
            "deliverables": deliverables, "checklist_items": checklist, "milestones": milestones,
        })
        candidate = AssignmentDraftCandidate(
            tenant_id=request.tenant_id.strip(), source_system=source_system, source_document_id=document_id,
            source_revision=revision, source_identity_key=source_identity_key, initial_status=PENDING_OFFICE_REVIEW,
            task_title=title, task_description=description, lead_unit_source_key=lead_unit,
            participating_unit_source_keys=units, required_roles=required_roles, proposed_personnel=personnel,
            proposed_start_date=start_date, proposed_due_date=due_date, priority=priority, deliverables=deliverables,
            checklist_items=checklist, milestones=milestones, warnings=tuple(warnings), unresolved_items=unresolved_items,
            overall_confidence=overall_confidence, source_engine_versions=source_versions,
            source_fingerprints=source_fingerprints, source_input_fingerprint=source_input_fingerprint,
            draft_content_fingerprint="", builder_version=ASSIGNMENT_DRAFT_BUILDER_VERSION,
            document_number=document_number, subject=subject, issuing_agency=issuing_agency,
            issued_date=issued_date, summary=summary, source_attachments=attachments,
        )
        content = asdict(candidate)
        content.pop("draft_content_fingerprint")
        # Source display metadata is not part of the existing B7 idempotency material.
        for field in ("document_number", "subject", "issuing_agency", "issued_date", "summary", "source_attachments"):
            content.pop(field)
        return replace(candidate, draft_content_fingerprint=_sha256(content))

    def _personnel(self, g05b: Any, required_roles: tuple[str, ...]) -> tuple[tuple[AssignmentDraftPersonnelProposal, ...], list[str], list[str]]:
        proposals: list[AssignmentDraftPersonnelProposal] = []
        unresolved = {_value(role) for role in getattr(g05b, "unresolved_roles", [])}
        conflicts = {_value(role) for role in getattr(g05b, "conflicting_roles", [])}
        warnings: list[str] = []
        for recommendation in getattr(g05b, "role_recommendations", []):
            role = _value(getattr(recommendation, "role_type"))
            selected_keys = []
            selected_key = getattr(recommendation, "selected_source_person_key", None)
            if selected_key:
                selected_keys.append(selected_key)
            selected_keys.extend(getattr(recommendation, "selected_source_person_keys", []))
            selected_keys = sorted(set(selected_keys))
            role_warnings = {_value(item) for item in getattr(recommendation, "warnings", [])}
            if role in conflicts or "PERSONNEL_CONFLICT" in role_warnings:
                warnings.append("PERSONNEL_CONFLICT")
            if "SUBSTITUTE_USED" in role_warnings:
                warnings.append("SUBSTITUTE_USED")
            if not selected_keys:
                unresolved.add(role)
                continue
            for key in selected_keys:
                proposals.append(AssignmentDraftPersonnelProposal(
                    personnel_source_key=normalize_text(key, "g05b_proposal.personnel_source_key", 500, required=True),
                    role_type=role, proposal_source="G05B", is_substitute="SUBSTITUTE_USED" in role_warnings,
                    confidence=float(getattr(recommendation, "confidence", 0)), item_order=0,
                ))
        unresolved.update(role for role in required_roles if role not in {proposal.role_type for proposal in proposals})
        canonical = sorted(proposals, key=lambda proposal: (_ROLE_ORDER.get(proposal.role_type, 99), proposal.personnel_source_key))
        canonical = tuple(replace(proposal, item_order=index) for index, proposal in enumerate(canonical))
        return canonical, sorted(unresolved, key=lambda role: (_ROLE_ORDER.get(role, 99), role)), sorted(set(warnings))

    def _warnings(self, request: AssignmentDraftBuildRequest, g05a: Any, g05b: Any, lead_unit: str | None,
                  personnel: tuple[AssignmentDraftPersonnelProposal, ...], unresolved_roles: list[str], personnel_warnings: list[str],
                  received_date: str | None, start_date: str | None, due_date: str | None) -> list[AssignmentDraftWarning]:
        warnings: list[AssignmentDraftWarning] = []
        if not lead_unit:
            warnings.append(_warning("UNIT_REVIEW_REQUIRED", "lead_unit", "No lead unit was proposed.", "Select a lead unit."))
        if getattr(g05a, "conflicting_rules", []) or any("CONFLICT" in _value(item) for item in getattr(g05a, "warnings", [])):
            warnings.append(_warning("UNIT_REVIEW_REQUIRED", "lead_unit", "Unit proposal needs review.", "Confirm the lead unit."))
        for role in unresolved_roles:
            code = {"LEADER": "LEADER_REVIEW_REQUIRED", "MONITOR": "MONITOR_REVIEW_REQUIRED", "LEAD_EXECUTOR": "LEAD_EXECUTOR_REVIEW_REQUIRED"}.get(role, "PERSONNEL_CONFLICT_REVIEW_REQUIRED")
            warnings.append(_warning(code, role, f"{role} needs Office review.", "Assign or confirm the role."))
        if "PERSONNEL_CONFLICT" in personnel_warnings or getattr(g05b, "conflicting_roles", []):
            warnings.append(_warning("PERSONNEL_CONFLICT_REVIEW_REQUIRED", None, "Personnel proposal has a conflict.", "Resolve the personnel conflict."))
        if "SUBSTITUTE_USED" in personnel_warnings:
            warnings.append(_warning("SUBSTITUTE_SUGGESTION", None, "Only a substitute is proposed for a role.", "Confirm the substitute."))
        if due_date is None:
            warnings.append(_warning("DUE_DATE_REVIEW_REQUIRED", "proposed_due_date", "No due date was proposed.", "Enter or confirm a due date."))
        elif (received_date and due_date < received_date) or (start_date and due_date < start_date):
            warnings.append(_warning("INVALID_PROPOSED_DUE_DATE", "proposed_due_date", "The due date precedes a source date.", "Confirm or correct the due date."))
        if not request.proposed_deliverables:
            warnings.append(_warning("DELIVERABLE_REVIEW_REQUIRED", "deliverables", "No deliverable was proposed.", "Add expected deliverables."))
        if request.file_reference_placeholder is None:
            warnings.append(_warning("FILE_REFERENCE_REVIEW_REQUIRED", "file_reference", "No file reference placeholder was provided.", "Attach or confirm the reference later."))
        return warnings

    @staticmethod
    def _canonical_warnings(warnings: list[AssignmentDraftWarning]) -> list[AssignmentDraftWarning]:
        deduplicated = {(item.code, item.severity, item.field_or_role, item.message, item.suggested_action): item for item in warnings}
        canonical = sorted(
            deduplicated.values(),
            key=lambda item: (item.code, item.severity, item.field_or_role or "", item.message, item.suggested_action),
        )
        if len(canonical) > MAX_WARNINGS:
            raise AssignmentDraftValidationError("LIST_LIMIT_EXCEEDED", "warnings", "warnings exceed the approved limit.")
        return canonical


def build_assignment_draft(request: AssignmentDraftBuildRequest) -> AssignmentDraftCandidate:
    return AssignmentDraftBuilder().build(request)


def build_assignment_draft_from_canonical_source(request: AssignmentDraftBuildRequest, connection: Any) -> AssignmentDraftCandidate:
    """Build from backend-owned G02 source metadata, never from frontend input."""

    from .assignment_draft_source_metadata import load_canonical_source_attachments

    attachments = load_canonical_source_attachments(
        connection,
        tenant_id=request.tenant_id,
        source_system=request.source_system,
        source_document_id=request.source_document_id,
        source_revision=request.source_revision,
    )
    return AssignmentDraftBuilder().build(request, source_attachments=attachments)
