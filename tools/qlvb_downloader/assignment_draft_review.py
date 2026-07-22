"""Minimal, append-only Office review operations for G05C drafts."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass, replace
from typing import Any

from .assignment_draft_models import AssignmentDraftCandidate, AssignmentDraftPersonnelProposal, AssignmentDraftWarning
from .assignment_draft_repository import AssignmentDraftRepository, StoredAssignmentDraft, _json
from .assignment_draft_validation import normalize_date, normalize_optional_text, normalize_priority, normalize_text, normalize_text_list
from .domain_models import new_id, utc_now_iso


PENDING_OFFICE_REVIEW = "PENDING_OFFICE_REVIEW"
APPROVED_FOR_PLANNER = "APPROVED_FOR_PLANNER"
REJECTED = "REJECTED"
SUPERSEDED = "SUPERSEDED"
_EDITABLE_FIELDS = frozenset({
    "task_title", "task_description", "lead_unit_source_key", "proposed_start_date", "proposed_due_date",
    "priority", "personnel", "deliverables", "checklist_items", "milestones",
})


class AssignmentDraftReviewError(ValueError):
    pass


@dataclass(frozen=True)
class AssignmentDraftReviewState:
    status: str
    reason: str | None


class AssignmentDraftReviewService:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.repository = AssignmentDraftRepository(connection)
        self.connection = connection

    def create_office_revision(self, tenant_id: str, draft_id: str, reviewer_reference: str, reason: str | None,
                               edits: dict[str, Any]) -> StoredAssignmentDraft:
        reviewer = normalize_text(reviewer_reference, "reviewer_reference", 200, required=True)
        review_reason = normalize_optional_text(reason, "reason", 1000)
        if not isinstance(edits, dict) or not edits:
            raise AssignmentDraftReviewError("edits must contain at least one permitted field")
        unknown = set(edits) - _EDITABLE_FIELDS
        if unknown:
            raise AssignmentDraftReviewError("unsupported office edit")
        current = self._require_pending(tenant_id, draft_id)
        candidate, changes = self._edited_candidate(current, edits)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            latest = self.repository._latest_for_source(candidate)
            if latest is None:
                raise AssignmentDraftReviewError("draft source is unavailable")
            new_id_value = new_id()
            self.repository._insert_draft(candidate, new_id_value, latest.draft_version + 1, current.id)
            for person in candidate.proposed_personnel:
                self.repository._insert_personnel(new_id_value, tenant_id, person)
            self._insert_event(current.id, tenant_id, SUPERSEDED, reviewer, review_reason, changes)
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        created = self.repository.get_draft_by_id(tenant_id, new_id_value)
        if created is None:
            raise RuntimeError("office revision could not be read back")
        return created

    def approve_draft(self, tenant_id: str, draft_id: str, reviewer_reference: str, reason: str | None = None) -> None:
        self._decision(tenant_id, draft_id, reviewer_reference, reason, APPROVED_FOR_PLANNER, required_reason=False)

    def reject_draft(self, tenant_id: str, draft_id: str, reviewer_reference: str, reason: str) -> None:
        if not reason or not reason.strip():
            raise AssignmentDraftReviewError("reason is required for rejection")
        self._decision(tenant_id, draft_id, reviewer_reference, reason, REJECTED, required_reason=True)

    def get_current_review_status(self, tenant_id: str, draft_id: str) -> str | None:
        state = self.get_current_review_state(tenant_id, draft_id)
        return state.status if state else None

    def get_current_review_state(self, tenant_id: str, draft_id: str) -> AssignmentDraftReviewState | None:
        draft = self.repository.get_draft_by_id(tenant_id, draft_id)
        if draft is None:
            return None
        row = self.connection.execute(
            """SELECT event_type, reason FROM assignment_draft_review_events
               WHERE tenant_id=? AND draft_id=? ORDER BY created_at DESC, id DESC LIMIT 1""",
            (tenant_id, draft_id),
        ).fetchone()
        return AssignmentDraftReviewState(row["event_type"], row["reason"]) if row else AssignmentDraftReviewState(draft.current_status, None)

    def _decision(self, tenant_id: str, draft_id: str, reviewer_reference: str, reason: str | None,
                  event_type: str, required_reason: bool) -> None:
        reviewer = normalize_text(reviewer_reference, "reviewer_reference", 200, required=True)
        review_reason = normalize_optional_text(reason, "reason", 1000)
        if required_reason and not review_reason:
            raise AssignmentDraftReviewError("reason is required")
        self._require_pending(tenant_id, draft_id)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self._insert_event(draft_id, tenant_id, event_type, reviewer, review_reason, {})
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def _require_pending(self, tenant_id: str, draft_id: str) -> StoredAssignmentDraft:
        draft = self.repository.get_draft_by_id(tenant_id, draft_id)
        if draft is None:
            raise AssignmentDraftReviewError("draft is unavailable")
        if self.get_current_review_status(tenant_id, draft_id) != PENDING_OFFICE_REVIEW:
            raise AssignmentDraftReviewError("draft is no longer pending Office review")
        return draft

    def _edited_candidate(self, draft: StoredAssignmentDraft, edits: dict[str, Any]) -> tuple[AssignmentDraftCandidate, dict[str, Any]]:
        values = {
            "task_title": draft.task_title, "task_description": draft.task_description,
            "lead_unit_source_key": draft.lead_unit_source_key, "proposed_start_date": draft.proposed_start_date,
            "proposed_due_date": draft.proposed_due_date, "priority": draft.priority,
            "personnel": tuple(AssignmentDraftPersonnelProposal(p.personnel_source_key, p.role_type, p.proposal_source, p.is_substitute, p.confidence, p.item_order) for p in draft.personnel),
            "deliverables": draft.deliverables, "checklist_items": draft.checklist_items, "milestones": draft.milestones,
        }
        for field, value in edits.items():
            values[field] = self._normalize_edit(field, value)
        changes = {field: values[field] for field in edits if values[field] != getattr(draft, field, None)}
        if "personnel" in edits:
            changes["personnel"] = [asdict(item) for item in values["personnel"]]
        warnings = tuple(AssignmentDraftWarning(**item) for item in draft.warnings)
        candidate = AssignmentDraftCandidate(
            tenant_id=draft.tenant_id, source_system=draft.source_system, source_document_id=draft.source_document_id,
            source_revision=draft.source_revision, source_identity_key=draft.source_identity_key,
            initial_status=PENDING_OFFICE_REVIEW, task_title=values["task_title"], task_description=values["task_description"],
            lead_unit_source_key=values["lead_unit_source_key"], participating_unit_source_keys=draft.participating_unit_source_keys,
            required_roles=tuple(), proposed_personnel=tuple(values["personnel"]), proposed_start_date=values["proposed_start_date"],
            proposed_due_date=values["proposed_due_date"], priority=values["priority"], deliverables=tuple(values["deliverables"]),
            checklist_items=tuple(values["checklist_items"]), milestones=tuple(values["milestones"]), warnings=warnings,
            unresolved_items=draft.unresolved_items, overall_confidence=draft.overall_confidence,
            source_engine_versions=tuple(sorted(draft.source_engine_versions.items())), source_fingerprints=tuple(sorted(draft.source_fingerprints.items())),
            source_input_fingerprint=draft.source_input_fingerprint, draft_content_fingerprint="", builder_version=draft.builder_version,
            document_number=draft.document_number, subject=draft.subject, issuing_agency=draft.issuing_agency,
            issued_date=draft.issued_date, summary=draft.summary, source_attachments=draft.source_attachments,
        )
        content = asdict(candidate)
        content.pop("draft_content_fingerprint")
        for field in ("document_number", "subject", "issuing_agency", "issued_date", "summary", "source_attachments"):
            content.pop(field)
        fingerprint = hashlib.sha256(json.dumps(content, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return replace(candidate, draft_content_fingerprint=fingerprint), changes

    def _normalize_edit(self, field: str, value: Any) -> Any:
        if field == "task_title":
            return normalize_text(value, field, 300, required=True)
        if field == "task_description":
            return normalize_text(value, field, 10_000)
        if field == "lead_unit_source_key":
            return normalize_optional_text(value, field, 500)
        if field in {"proposed_start_date", "proposed_due_date"}:
            return normalize_date(value, field)
        if field == "priority":
            return normalize_priority(value)
        if field == "personnel":
            if not isinstance(value, list):
                raise AssignmentDraftReviewError("personnel must be a list")
            return tuple(AssignmentDraftPersonnelProposal(**item) if isinstance(item, dict) else item for item in value)
        limits = {"deliverables": 20, "checklist_items": 50, "milestones": 20}
        return normalize_text_list(value, field, limits[field])

    def _insert_event(self, draft_id: str, tenant_id: str, event_type: str, reviewer: str, reason: str | None,
                      changes: dict[str, Any]) -> None:
        self.connection.execute(
            """INSERT INTO assignment_draft_review_events
               (id, draft_id, tenant_id, event_type, reviewer_reference, reason, changes_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (new_id(), draft_id, tenant_id, event_type, reviewer, reason, _json(changes), utc_now_iso()),
        )
