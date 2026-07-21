from __future__ import annotations

from types import SimpleNamespace

import pytest

from tools.qlvb_downloader.assignment_draft_service import AssignmentDraftService, AssignmentDraftServiceError
from tools.qlvb_downloader.planner_draft_handoff_client import PlannerHandoffOutcome, PlannerHandoffResult


class _Client:
    def __init__(self):
        self.handoff = None

    def send(self, handoff):
        self.handoff = handoff
        return PlannerHandoffResult(PlannerHandoffOutcome.CREATED, "correlation", "planner-1", "PENDING_OFFICE_REVIEW")


def test_service_reads_the_scoped_snapshot_and_never_accepts_ui_task_payload(monkeypatch, tmp_path):
    draft = SimpleNamespace(
        tenant_id="tenant-a", source_system="qlvb", source_document_id="DOC-1", source_revision="REV-1",
        id="draft-1", draft_version=1, current_status="PENDING_OFFICE_REVIEW", task_title="Demo", task_description="Description", lead_unit_source_key=None,
        proposed_start_date=None, proposed_due_date=None, priority="NORMAL", personnel=(), deliverables=(), checklist_items=(),
        milestones=(), warnings=(), overall_confidence=80, source_input_fingerprint="a" * 64, draft_content_fingerprint="b" * 64,
    )
    client = _Client()
    service = AssignmentDraftService(str(tmp_path), handoff_client=client)
    monkeypatch.setattr(service, "_with_repository", lambda tenant, callback: callback(SimpleNamespace(get_draft_by_id=lambda scoped_tenant, draft_id: draft if (scoped_tenant, draft_id) == ("tenant-a", "draft-1") else None)))
    result = service.send_draft_to_planner("tenant-a", "draft-1")
    assert result.outcome is PlannerHandoffOutcome.CREATED
    assert client.handoff.draft_id == "draft-1" and client.handoff.task_title == "Demo"


def test_ui_has_no_secret_or_direct_planner_http_client():
    import inspect
    from tools.qlvb_downloader.assignment_draft_ui import AssignmentDraftDetailDialog

    source = inspect.getsource(AssignmentDraftDetailDialog).lower()
    assert "planner_token" not in source and "planner_url" not in source
    assert "requests" not in source and "urlopen" not in source


def test_service_rejects_a_non_pending_snapshot_before_handoff(monkeypatch, tmp_path):
    client = _Client()
    service = AssignmentDraftService(str(tmp_path), handoff_client=client)
    draft = SimpleNamespace(current_status="SUPERSEDED")
    monkeypatch.setattr(service, "_with_repository", lambda tenant, callback: callback(SimpleNamespace(get_draft_by_id=lambda *_: draft)))
    with pytest.raises(AssignmentDraftServiceError, match="khong con"):
        service.send_draft_to_planner("tenant-a", "draft-1")
    assert client.handoff is None
