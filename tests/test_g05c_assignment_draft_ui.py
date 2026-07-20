from __future__ import annotations

from types import SimpleNamespace

import pytest

from tools.qlvb_downloader.assignment_draft_ui_state import (
    AssignmentDraftUiValidationError,
    changed_draft_edits,
    draft_form_values,
    normalized_personnel_rows,
)


def _draft():
    return SimpleNamespace(
        task_title="Original", task_description="Content", lead_unit_source_key="UNIT-A",
        proposed_start_date="2026-07-20", proposed_due_date="2026-07-25", priority="NORMAL",
        deliverables=("Output",), checklist_items=("Check",), milestones=("Milestone",),
        personnel=(SimpleNamespace(role_type="LEAD_EXECUTOR", personnel_source_key="P-1", is_substitute=False, proposal_source="G05B", confidence=80, item_order=0),),
    )


def test_cancel_edit_uses_a_copy_without_mutating_the_stored_draft():
    draft = _draft()
    values = draft_form_values(draft)
    values["task_title"] = "Changed"
    values["personnel"][0]["personnel_source_key"] = "P-2"
    assert draft.task_title == "Original" and draft.personnel[0].personnel_source_key == "P-1"


def test_unchanged_form_does_not_create_edits():
    original = draft_form_values(_draft())
    assert changed_draft_edits(original, draft_form_values(_draft())) == {}


def test_changed_form_only_returns_changed_fields_and_preserves_personnel_metadata():
    original = draft_form_values(_draft())
    edited = draft_form_values(_draft())
    edited["task_title"] = "Revised"
    edited["personnel"][0]["personnel_source_key"] = "P-2"
    changes = changed_draft_edits(original, edited)
    assert set(changes) == {"task_title", "personnel"}
    assert changes["personnel"] == [{"role_type": "LEAD_EXECUTOR", "personnel_source_key": "P-2", "is_substitute": False, "proposal_source": "G05B", "confidence": 80.0, "item_order": 0}]


def test_personnel_rows_are_ordered_and_reject_duplicate_identity():
    rows = normalized_personnel_rows([
        {"role_type": "MONITOR", "personnel_source_key": "P-2", "is_substitute": False},
        {"role_type": "LEAD_EXECUTOR", "personnel_source_key": "P-1", "is_substitute": True},
    ])
    assert [item["item_order"] for item in rows] == [0, 1]
    with pytest.raises(AssignmentDraftUiValidationError, match="lap"):
        normalized_personnel_rows([rows[0], rows[0]])


@pytest.mark.parametrize("row", [
    {"role_type": "OTHER", "personnel_source_key": "P-1"},
    {"role_type": "LEADER", "personnel_source_key": ""},
])
def test_personnel_rows_require_supported_role_and_key(row):
    with pytest.raises(AssignmentDraftUiValidationError):
        normalized_personnel_rows([row])
