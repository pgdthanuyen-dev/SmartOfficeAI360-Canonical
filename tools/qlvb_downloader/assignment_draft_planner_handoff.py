"""Local G05C-to-Planner handoff contract; this module performs no network I/O."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


PENDING_OFFICE_REVIEW = "PENDING_OFFICE_REVIEW"


def planner_display_status(current_status: str) -> str:
    return {
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
        proposed_personnel=tuple({"role_type": person.role_type, "personnel_source_key": person.personnel_source_key, "is_substitute": person.is_substitute} for person in draft.personnel),
        deliverables=tuple(draft.deliverables), checklist_items=tuple(draft.checklist_items), milestones=tuple(draft.milestones),
        warnings=tuple({"code": warning.get("code"), "severity": warning.get("severity"), "field_or_role": warning.get("field_or_role")} for warning in draft.warnings),
        overall_confidence=draft.overall_confidence, source_input_fingerprint=draft.source_input_fingerprint,
        draft_content_fingerprint=draft.draft_content_fingerprint, idempotency_key=idempotency_key,
    )
