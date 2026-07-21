from __future__ import annotations

from dataclasses import asdict
from types import SimpleNamespace

from tools.qlvb_downloader.assignment_draft_planner_handoff import (
    build_planner_handoff,
    planner_display_status,
    planner_handoff_configured,
)


def _draft(title="Demo draft"):
    return SimpleNamespace(
        tenant_id="tenant-a", source_system="demo", source_document_id="DOC-1", source_revision="REV-1",
        id="draft-1", draft_version=1, task_title=title, task_description="Demo description",
        lead_unit_source_key="UNIT-A", proposed_start_date="2026-07-20", proposed_due_date="2026-07-25",
        priority="NORMAL", personnel=(SimpleNamespace(role_type="LEAD_EXECUTOR", personnel_source_key="PERSON-1", is_substitute=False, confidence=80.0, item_order=0),),
        deliverables=("Output",), checklist_items=("Check",), milestones=("Milestone",),
        warnings=({"code": "DEMO_WARNING", "severity": "WARNING", "field_or_role": None, "message": "Do not export this text"},),
        overall_confidence=85.0, source_input_fingerprint="a" * 64, draft_content_fingerprint="b" * 64,
        document_number="12/VP", subject="Official source subject", issuing_agency="Official issuing agency",
    )


def test_handoff_contains_required_draft_fields_without_credentials_or_warning_message():
    payload = asdict(build_planner_handoff(_draft()))
    assert payload["tenant_id"] == "tenant-a" and payload["draft_version"] == 1
    assert payload["proposed_personnel"][0]["role_type"] == "LEAD_EXECUTOR"
    rendered = str(payload).lower()
    assert "token" not in rendered and "cookie" not in rendered and "do not export" not in rendered


def test_handoff_idempotency_key_is_stable_for_the_same_draft_content():
    assert build_planner_handoff(_draft()).idempotency_key == build_planner_handoff(_draft()).idempotency_key
    assert build_planner_handoff(_draft("Changed")).idempotency_key == build_planner_handoff(_draft()).idempotency_key


def test_handoff_maps_exact_source_metadata_without_using_task_or_unit_values():
    payload = build_planner_handoff(_draft("Different task title")).to_planner_receiver_payload()
    assert payload["documentNumber"] == "12/VP"
    assert payload["subject"] == "Official source subject"
    assert payload["issuingAgency"] == "Official issuing agency"
    assert payload["subject"] != payload["taskTitle"]
    assert payload["issuingAgency"] != payload["leadUnitSourceKey"]
    changed = _draft()
    changed.document_number, changed.subject, changed.issuing_agency = "99/VP", "Changed subject", "Changed agency"
    assert build_planner_handoff(changed).idempotency_key == build_planner_handoff(_draft()).idempotency_key


def test_legacy_snapshot_without_source_metadata_remains_valid_for_nullable_receiver_fields():
    legacy = _draft()
    legacy.document_number = legacy.subject = legacy.issuing_agency = None
    payload = build_planner_handoff(legacy).to_planner_receiver_payload()
    assert payload["documentNumber"] is None and payload["subject"] is None and payload["issuingAgency"] is None


def test_handoff_adapts_only_normalized_g05_fields_to_the_planner_receiver_contract():
    payload = build_planner_handoff(_draft()).to_planner_receiver_payload()
    assert payload["sourceSystem"] == "SmartOfficeAI360"
    assert payload["smartOfficeDraftId"] == "draft-1"
    assert payload["personnel"] == [{
        "roleType": "LEAD_EXECUTOR", "personnelSourceKey": "PERSON-1", "confidence": 0.8,
        "isSubstitute": False, "itemOrder": 0,
    }]
    assert payload["overallConfidence"] == 0.85
    assert "message" not in str(payload).lower() and "token" not in str(payload).lower()


def test_display_status_and_configuration_guard_are_local_only():
    assert planner_display_status("PENDING_OFFICE_REVIEW") == "Du thao AI - Chua gui Planner"
    assert not planner_handoff_configured("", "token")
    assert not planner_handoff_configured("https://planner.invalid", "")
    assert planner_handoff_configured("https://planner.invalid", "local-token")


def test_smartoffice_detail_dialog_has_no_office_edit_or_decision_entry_points():
    import inspect
    from tools.qlvb_downloader.assignment_draft_ui import AssignmentDraftDetailDialog

    source = inspect.getsource(AssignmentDraftDetailDialog)
    for forbidden in ("enter_edit", "save_revision", "approve(", "reject(", "add_personnel_row"):
        assert forbidden not in source
