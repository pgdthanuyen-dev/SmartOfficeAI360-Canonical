"""Local G05C-to-Planner handoff contract; this module performs no network I/O."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


PENDING_OFFICE_REVIEW = "PENDING_OFFICE_REVIEW"
PLANNER_RECEIVER_PATH = "/api/integrations/smartoffice/drafts"
SMARTOFFICE_SOURCE_SYSTEM = "SmartOfficeAI360"


def planner_display_status(current_status: str) -> str:
    return {
        "NOT_SENT": "Chua gui Planner",
        "SENT": "Da gui Planner",
        "UNKNOWN": "Chua xac dinh ket qua gui",
        "FAILED": "Gui Planner that bai",
        PENDING_OFFICE_REVIEW: "Du thao AI - Chua gui Planner",
        "PLANNER_SYNCING": "Dang gui Planner",
        "PLANNER_SYNCED": "Da gui Planner",
        "PLANNER_SYNC_FAILED": "Gui Planner that bai",
    }.get(current_status, current_status)


def planner_handoff_configured(planner_url: str, planner_token: str) -> bool:
    return bool(isinstance(planner_url, str) and planner_url.strip() and isinstance(planner_token, str) and planner_token.strip())


@dataclass(frozen=True)
class PlannerDraftHandoff:
    tenant_id: str
    source_system: str
    source_document_id: str
    source_revision: str
    draft_id: str
    draft_version: int
    task_title: str
    task_description: str
    lead_unit_source_key: str | None
    proposed_start_date: str | None
    proposed_due_date: str | None
    priority: str
    proposed_personnel: tuple[dict[str, Any], ...]
    deliverables: tuple[str, ...]
    checklist_items: tuple[str, ...]
    milestones: tuple[str, ...]
    warnings: tuple[dict[str, str | None], ...]
    overall_confidence: float
    source_input_fingerprint: str
    draft_content_fingerprint: str
    idempotency_key: str

    def to_planner_receiver_payload(self) -> dict[str, Any]:
        """Adapt the credential-free G05C snapshot to Planner's B6 receiver."""

        return {
            "tenantId": self.tenant_id,
            "sourceSystem": SMARTOFFICE_SOURCE_SYSTEM,
            "sourceDocumentId": self.source_document_id,
            "sourceRevision": self.source_revision,
            "smartOfficeDraftId": self.draft_id,
            "smartOfficeDraftVersion": self.draft_version,
            "taskTitle": self.task_title,
            "taskDescription": self.task_description,
            "leadUnitSourceKey": self.lead_unit_source_key,
            "proposedStartDate": self.proposed_start_date,
            "proposedDueDate": self.proposed_due_date,
            "priority": self.priority,
            "personnel": [
                {
                    "roleType": person["role_type"],
                    "personnelSourceKey": person["personnel_source_key"],
                    "confidence": person["confidence"] / 100.0,
                    "isSubstitute": person["is_substitute"],
                    "itemOrder": person["item_order"],
                }
                for person in self.proposed_personnel
            ],
            "deliverables": list(self.deliverables),
            "checklistItems": list(self.checklist_items),
            "milestones": list(self.milestones),
            "warnings": [
                {key: value for key, value in {
                    "code": warning["code"], "severity": warning["severity"], "fieldOrRole": warning["field_or_role"],
                }.items() if value is not None}
                for warning in self.warnings
            ],
            "overallConfidence": self.overall_confidence / 100.0,
            "sourceInputFingerprint": self.source_input_fingerprint,
            "draftContentFingerprint": self.draft_content_fingerprint,
            "idempotencyKey": self.idempotency_key,
        }


def build_planner_handoff(draft: Any) -> PlannerDraftHandoff:
    """Build the documented, credential-free Planner draft payload."""

    key_material = {
        "tenant_id": draft.tenant_id,
        "source_system": draft.source_system,
        "source_document_id": draft.source_document_id,
        "source_revision": draft.source_revision,
        "draft_content_fingerprint": draft.draft_content_fingerprint,
    }
    idempotency_key = hashlib.sha256(
        json.dumps(key_material, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    return PlannerDraftHandoff(
        tenant_id=draft.tenant_id, source_system=draft.source_system, source_document_id=draft.source_document_id,
        source_revision=draft.source_revision, draft_id=draft.id, draft_version=draft.draft_version,
        task_title=draft.task_title, task_description=draft.task_description,
        lead_unit_source_key=draft.lead_unit_source_key, proposed_start_date=draft.proposed_start_date,
        proposed_due_date=draft.proposed_due_date, priority=draft.priority,
        proposed_personnel=tuple({
            "role_type": person.role_type,
            "personnel_source_key": person.personnel_source_key,
            "is_substitute": person.is_substitute,
            "confidence": person.confidence,
            "item_order": person.item_order,
        } for person in draft.personnel),
        deliverables=tuple(draft.deliverables), checklist_items=tuple(draft.checklist_items), milestones=tuple(draft.milestones),
        warnings=tuple({"code": warning.get("code"), "severity": warning.get("severity"), "field_or_role": warning.get("field_or_role")} for warning in draft.warnings),
        overall_confidence=draft.overall_confidence, source_input_fingerprint=draft.source_input_fingerprint,
        draft_content_fingerprint=draft.draft_content_fingerprint, idempotency_key=idempotency_key,
    )
