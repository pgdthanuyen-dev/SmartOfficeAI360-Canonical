"""Pure form-state helpers for the local G05C Office review screen."""

from __future__ import annotations

from typing import Any, Iterable


EDITABLE_DRAFT_FIELDS = (
    "task_title", "task_description", "lead_unit_source_key", "proposed_start_date",
    "proposed_due_date", "priority", "deliverables", "checklist_items", "milestones", "personnel",
)
ALLOWED_PERSONNEL_ROLES = frozenset({"LEADER", "MONITOR", "LEAD_EXECUTOR", "CO_EXECUTOR"})


class AssignmentDraftUiValidationError(ValueError):
    pass


def draft_form_values(draft: Any) -> dict[str, Any]:
    """Copy a stored draft into mutable values used only by the edit form."""

    return {
        "task_title": draft.task_title,
        "task_description": draft.task_description,
        "lead_unit_source_key": draft.lead_unit_source_key or "",
        "proposed_start_date": draft.proposed_start_date or "",
        "proposed_due_date": draft.proposed_due_date or "",
        "priority": draft.priority,
        "deliverables": list(draft.deliverables),
        "checklist_items": list(draft.checklist_items),
        "milestones": list(draft.milestones),
        "personnel": [
            {
                "role_type": item.role_type,
                "personnel_source_key": item.personnel_source_key,
                "is_substitute": item.is_substitute,
                "proposal_source": item.proposal_source,
                "confidence": item.confidence,
                "item_order": item.item_order,
            }
            for item in draft.personnel
        ],
    }


def normalized_personnel_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate visible personnel columns and return deterministic repository edits."""

    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, bool]] = set()
    for position, row in enumerate(rows):
        role_type = str(row.get("role_type", "")).strip().upper()
        person_key = str(row.get("personnel_source_key", "")).strip()
        if role_type not in ALLOWED_PERSONNEL_ROLES:
            raise AssignmentDraftUiValidationError("Vai tro nhan su khong hop le.")
        if not person_key:
            raise AssignmentDraftUiValidationError("Ma nhan su la bat buoc.")
        identity = (role_type, person_key, bool(row.get("is_substitute", False)))
        if identity in seen:
            raise AssignmentDraftUiValidationError("Khong duoc lap dong nhan su giong nhau.")
        seen.add(identity)
        result.append(
            {
                "role_type": role_type,
                "personnel_source_key": person_key,
                "is_substitute": identity[2],
                "proposal_source": str(row.get("proposal_source") or "OFFICE_REVIEW"),
                "confidence": float(row.get("confidence", 100)),
                "item_order": position,
            }
        )
    return result


def changed_draft_edits(original: dict[str, Any], form_values: dict[str, Any]) -> dict[str, Any]:
    """Return only changed, editable fields without mutating either input."""

    edits: dict[str, Any] = {}
    for field in EDITABLE_DRAFT_FIELDS:
        original_value = original[field]
        value = form_values[field]
        if field in {"lead_unit_source_key", "proposed_start_date", "proposed_due_date"}:
            value = value or None
            original_value = original_value or None
        if field in {"deliverables", "checklist_items", "milestones"}:
            value = list(value)
            original_value = list(original_value)
        if field == "personnel":
            value = normalized_personnel_rows(value)
            original_value = normalized_personnel_rows(original_value)
        if value != original_value:
            edits[field] = value
    return edits
