from __future__ import annotations

import sqlite3

import pytest

from tools.qlvb_downloader.assignment_draft_models import AssignmentDraftCandidate, AssignmentDraftPersonnelProposal
from tools.qlvb_downloader.assignment_draft_repository import AssignmentDraftRepository, init_assignment_draft_schema
from tools.qlvb_downloader.assignment_draft_review import AssignmentDraftReviewError, AssignmentDraftReviewService


def _connection():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY, title TEXT)")
    init_assignment_draft_schema(connection)
    return connection


def _candidate(tenant="tenant-a"):
    people = (
        AssignmentDraftPersonnelProposal("P-LEADER", "LEADER", "G05B", False, 90, 0),
        AssignmentDraftPersonnelProposal("P-EXECUTOR", "LEAD_EXECUTOR", "G05B", False, 85, 1),
    )
    return AssignmentDraftCandidate(
        tenant, "qlvb", "DOC-1", "REV-1", "qlvb:DOC-1", "PENDING_OFFICE_REVIEW", "Original title",
        "Original content", "UNIT-A", ("UNIT-B",), ("LEADER", "LEAD_EXECUTOR"), people, "2026-07-20", "2026-07-25",
        "NORMAL", ("Output",), ("Review",), ("Milestone",), (), (), 85, (("g05a", "g05a.engine.1"),),
        (("g05a", "a" * 64),), "b" * 64, "c" * 64,
        document_number="12/VP", subject="Official subject", issuing_agency="Issuing agency",
    )


def _saved_service():
    connection = _connection()
    draft = AssignmentDraftRepository(connection).save_draft_candidate(_candidate())
    return connection, draft, AssignmentDraftReviewService(connection)


@pytest.mark.parametrize("edits, field", [
    ({"task_title": "Revised title"}, "task_title"),
    ({"task_description": "Revised content"}, "task_description"),
    ({"lead_unit_source_key": "UNIT-C"}, "lead_unit_source_key"),
    ({"proposed_due_date": "2026-07-30"}, "proposed_due_date"),
    ({"personnel": [{"personnel_source_key": "P-NEW", "role_type": "LEAD_EXECUTOR", "proposal_source": "OFFICE", "is_substitute": False, "confidence": 80, "item_order": 0}]}, "personnel"),
])
def test_office_edits_create_pending_revision(edits, field):
    connection, old, service = _saved_service()
    revised = service.create_office_revision("tenant-a", old.id, "OFFICE-1", "review", edits)
    assert revised.draft_version == 2 and revised.initial_status == "PENDING_OFFICE_REVIEW"
    assert revised.supersedes_draft_id == old.id
    event = connection.execute("SELECT event_type, changes_json FROM assignment_draft_review_events WHERE draft_id=?", (old.id,)).fetchone()
    assert event["event_type"] == "SUPERSEDED" and field in event["changes_json"]


def test_revision_keeps_old_snapshot_unchanged_and_changes_json_is_minimal():
    connection, old, service = _saved_service()
    service.create_office_revision("tenant-a", old.id, "OFFICE-1", None, {"task_title": "Revised title"})
    loaded = AssignmentDraftRepository(connection).get_draft_by_id("tenant-a", old.id)
    changes = connection.execute("SELECT changes_json FROM assignment_draft_review_events WHERE draft_id=?", (old.id,)).fetchone()[0]
    assert loaded.task_title == "Original title" and changes == '{"task_title":"Revised title"}'


def test_office_revision_preserves_source_metadata_and_rejects_metadata_edits():
    _, old, service = _saved_service()
    revised = service.create_office_revision("tenant-a", old.id, "OFFICE-1", None, {"task_title": "Revised"})
    assert (revised.document_number, revised.subject, revised.issuing_agency) == (
        "12/VP", "Official subject", "Issuing agency",
    )
    with pytest.raises(AssignmentDraftReviewError, match="unsupported office edit"):
        service.create_office_revision("tenant-a", revised.id, "OFFICE-1", None, {"subject": "Not allowed"})


def test_approve_and_reject_are_events_without_snapshot_update():
    connection, draft, service = _saved_service()
    service.approve_draft("tenant-a", draft.id, "OFFICE-1")
    assert service.get_current_review_status("tenant-a", draft.id) == "APPROVED_FOR_PLANNER"
    assert AssignmentDraftRepository(connection).get_draft_by_id("tenant-a", draft.id).initial_status == "PENDING_OFFICE_REVIEW"
    connection, draft, service = _saved_service()
    service.reject_draft("tenant-a", draft.id, "OFFICE-1", "Not applicable")
    assert service.get_current_review_status("tenant-a", draft.id) == "REJECTED"


def test_review_state_exposes_current_status_and_rejection_reason():
    _, draft, service = _saved_service()
    assert service.get_current_review_state("tenant-a", draft.id).status == "PENDING_OFFICE_REVIEW"
    service.reject_draft("tenant-a", draft.id, "OFFICE-1", "Needs Office clarification")
    state = service.get_current_review_state("tenant-a", draft.id)
    assert state.status == "REJECTED" and state.reason == "Needs Office clarification"


def test_revision_excludes_superseded_snapshot_from_pending_list_and_keeps_tenants_isolated():
    connection, old, service = _saved_service()
    other = AssignmentDraftRepository(connection).save_draft_candidate(_candidate(tenant="tenant-b"))
    revised = service.create_office_revision("tenant-a", old.id, "OFFICE-1", "revision", {"task_title": "Revised title"})
    repository = AssignmentDraftRepository(connection)
    assert [draft.id for draft in repository.list_pending_drafts("tenant-a")] == [revised.id]
    assert repository.get_draft_by_id("tenant-a", old.id).current_status == "SUPERSEDED"
    assert repository.get_draft_by_id("tenant-a", old.id).task_title == "Original title"
    assert repository.get_draft_by_id("tenant-a", revised.id).current_status == "PENDING_OFFICE_REVIEW"
    assert [draft.id for draft in repository.list_pending_drafts("tenant-b")] == [other.id]


def test_rejection_reason_and_second_decision_are_rejected():
    _, draft, service = _saved_service()
    with pytest.raises(AssignmentDraftReviewError):
        service.reject_draft("tenant-a", draft.id, "OFFICE-1", "")
    service.approve_draft("tenant-a", draft.id, "OFFICE-1")
    with pytest.raises(AssignmentDraftReviewError):
        service.approve_draft("tenant-a", draft.id, "OFFICE-1")


def test_tenant_isolation_and_pending_default_status():
    _, draft, service = _saved_service()
    assert service.get_current_review_status("tenant-a", draft.id) == "PENDING_OFFICE_REVIEW"
    with pytest.raises(AssignmentDraftReviewError):
        service.approve_draft("tenant-b", draft.id, "OFFICE-1")
    with pytest.raises(AssignmentDraftReviewError):
        service.create_office_revision("tenant-b", draft.id, "OFFICE-1", None, {"task_title": "No"})


def test_personnel_failure_rolls_back_new_version(monkeypatch):
    connection, old, service = _saved_service()
    monkeypatch.setattr(service.repository, "_insert_personnel", lambda *args: (_ for _ in ()).throw(RuntimeError("failure")))
    with pytest.raises(RuntimeError):
        service.create_office_revision("tenant-a", old.id, "OFFICE-1", None, {"task_title": "Revised"})
    assert connection.execute("SELECT count(*) FROM assignment_drafts").fetchone()[0] == 1
    assert not connection.execute("SELECT * FROM assignment_draft_review_events").fetchall()
