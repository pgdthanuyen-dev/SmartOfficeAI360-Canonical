from __future__ import annotations

import inspect
import socket
import sqlite3

import pytest

from tools.qlvb_downloader.assignment_draft_builder import build_assignment_draft
from tools.qlvb_downloader.assignment_draft_models import AssignmentDraftBuildRequest
from tools.qlvb_downloader.assignment_draft_repository import AssignmentDraftRepository
from tools.qlvb_downloader.assignment_rule_engine import AssignmentRecommendation
from tools.qlvb_downloader.assignment_rule_models import MatchDecision, RuleRoleType
from tools.qlvb_downloader.personnel_directory_models import PersonnelSelectionDecision
from tools.qlvb_downloader.personnel_selection_engine import PersonnelRoleRecommendation, PersonnelSelectionRecommendation


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY, title TEXT)")
    from tools.qlvb_downloader.assignment_draft_repository import init_assignment_draft_schema

    init_assignment_draft_schema(connection)
    return connection


def _g05a(document_id: str, revision: str, fingerprint: str = "a" * 64) -> AssignmentRecommendation:
    return AssignmentRecommendation(
        document_id=document_id, document_revision=revision, input_fingerprint=fingerprint,
        evaluated_rule_count=1, eligible_rule_count=1, excluded_rule_count=0, primary_rule=None,
        alternative_rules=[], conflicting_rules=[], decision=MatchDecision.MATCHED, confidence=90,
        lead_unit_key="UNIT-A", coordinating_unit_keys=["UNIT-B"],
        required_roles=[RuleRoleType.LEADER, RuleRoleType.MONITOR, RuleRoleType.LEAD_EXECUTOR],
        unresolved_fields=[], warnings=[], explanation="rule proposal", engine_version="g05a.engine.1", evaluated_at="",
    )


def _role(role: RuleRoleType, key: str, confidence: float = 85) -> PersonnelRoleRecommendation:
    return PersonnelRoleRecommendation(
        role_type=role, decision=PersonnelSelectionDecision.SELECTED_WITH_WARNING,
        selected_personnel_id=f"id-{key}", selected_source_person_key=key, selected_personnel_ids=[f"id-{key}"],
        alternative_candidates=[], confidence=confidence, warnings=[], explanation="personnel proposal",
    )


def _g05b(document_id: str, revision: str, fingerprint: str = "b" * 64) -> PersonnelSelectionRecommendation:
    return PersonnelSelectionRecommendation(
        document_id=document_id, document_revision=revision, assignment_rule_match_id=None,
        unit_id="unit-id", unit_source_key="UNIT-A", role_recommendations=[
            _role(RuleRoleType.LEADER, "P-LEADER"), _role(RuleRoleType.MONITOR, "P-MONITOR"),
            _role(RuleRoleType.LEAD_EXECUTOR, "P-EXECUTOR"),
        ], unresolved_roles=[], conflicting_roles=[], overall_confidence=85, warnings=[],
        explanation="personnel proposal", input_fingerprint=fingerprint, engine_version="g05b.selection.1", evaluated_at="",
    )


def _candidate(*, tenant: str = "tenant-a", document_id: str = "DOC-1", revision: str = "REV-1",
               g05a_fingerprint: str = "a" * 64, g05b_fingerprint: str = "b" * 64):
    return build_assignment_draft(AssignmentDraftBuildRequest(
        tenant_id=tenant, source_system="qlvb", source_document_id=document_id, source_revision=revision,
        document_number="12/VP", subject="Handle document", issuing_agency="Demo Issuing Agency",
        normalized_summary="Normalized summary.",
        received_date="2026-07-20", issued_date="2026-07-19", proposed_task_title="Prepare response",
        proposed_task_description="Prepare one response draft.", proposed_start_date="2026-07-20",
        proposed_due_date="2026-07-25", proposed_priority="NORMAL", proposed_deliverables=["Response"],
        proposed_checklist_items=["Review"], proposed_milestones=["First review"],
        g05a_proposal=_g05a(document_id, revision, g05a_fingerprint),
        g05b_proposal=_g05b(document_id, revision, g05b_fingerprint),
        file_reference_placeholder="source-file-placeholder",
    ))


def _count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


def test_save_complete_draft_and_read_back_parent():
    connection = _connection()
    saved = AssignmentDraftRepository(connection).save_draft_candidate(_candidate())
    loaded = AssignmentDraftRepository(connection).get_draft_by_id("tenant-a", saved.id)
    assert loaded is not None and loaded.id == saved.id and loaded.task_title == "Prepare response"
    assert loaded.source_document_id == "DOC-1" and loaded.source_revision == "REV-1"


def test_source_document_metadata_persists_and_round_trips():
    candidate = _candidate()
    from dataclasses import replace

    saved = AssignmentDraftRepository(_connection()).save_draft_candidate(replace(
        candidate, document_number="Số 12/VP", subject="Trích yếu văn bản", issuing_agency="Cơ quan ban hành",
    ))
    assert (saved.document_number, saved.subject, saved.issuing_agency) == (
        "Số 12/VP", "Trích yếu văn bản", "Cơ quan ban hành",
    )


def test_read_back_returns_stable_personnel_order():
    saved = AssignmentDraftRepository(_connection()).save_draft_candidate(_candidate())
    assert [person.personnel_source_key for person in saved.personnel] == ["P-LEADER", "P-MONITOR", "P-EXECUTOR"]
    assert [person.item_order for person in saved.personnel] == [0, 1, 2]


def test_initial_status_is_pending_office_review():
    saved = AssignmentDraftRepository(_connection()).save_draft_candidate(_candidate())
    assert saved.initial_status == "PENDING_OFFICE_REVIEW"


def test_same_input_returns_existing_draft_without_duplicate_parent():
    connection = _connection()
    repository = AssignmentDraftRepository(connection)
    first = repository.save_draft_candidate(_candidate())
    second = repository.save_draft_candidate(_candidate())
    assert first.id == second.id and _count(connection, "assignment_drafts") == 1


def test_same_input_does_not_duplicate_personnel_rows():
    connection = _connection()
    repository = AssignmentDraftRepository(connection)
    repository.save_draft_candidate(_candidate())
    repository.save_draft_candidate(_candidate())
    assert _count(connection, "assignment_draft_personnel") == 3


def test_new_source_revision_creates_version_two():
    connection = _connection()
    repository = AssignmentDraftRepository(connection)
    repository.save_draft_candidate(_candidate())
    saved = repository.save_draft_candidate(_candidate(revision="REV-2"))
    assert saved.draft_version == 2 and _count(connection, "assignment_drafts") == 2


def test_new_source_input_fingerprint_creates_new_version():
    connection = _connection()
    repository = AssignmentDraftRepository(connection)
    repository.save_draft_candidate(_candidate())
    changed = _candidate(g05a_fingerprint="c" * 64)
    saved = repository.save_draft_candidate(changed)
    assert saved.draft_version == 2 and _count(connection, "assignment_drafts") == 2


def test_new_version_links_to_previous_draft():
    connection = _connection()
    repository = AssignmentDraftRepository(connection)
    first = repository.save_draft_candidate(_candidate())
    second = repository.save_draft_candidate(_candidate(revision="REV-2"))
    assert second.supersedes_draft_id == first.id


def test_old_version_remains_unchanged_after_new_version():
    connection = _connection()
    repository = AssignmentDraftRepository(connection)
    first = repository.save_draft_candidate(_candidate())
    repository.save_draft_candidate(_candidate(revision="REV-2"))
    old = repository.get_draft_by_id("tenant-a", first.id)
    assert old is not None and old.draft_version == 1 and old.supersedes_draft_id is None


def test_other_tenant_cannot_read_a_draft():
    connection = _connection()
    saved = AssignmentDraftRepository(connection).save_draft_candidate(_candidate())
    assert AssignmentDraftRepository(connection).get_draft_by_id("tenant-b", saved.id) is None


def test_pending_list_is_tenant_scoped():
    connection = _connection()
    repository = AssignmentDraftRepository(connection)
    repository.save_draft_candidate(_candidate(tenant="tenant-a", document_id="DOC-A"))
    repository.save_draft_candidate(_candidate(tenant="tenant-b", document_id="DOC-B"))
    listed = repository.list_pending_drafts("tenant-a")
    assert len(listed) == 1 and listed[0].tenant_id == "tenant-a"


def test_pending_list_returns_only_pending_status():
    connection = _connection()
    repository = AssignmentDraftRepository(connection)
    repository.save_draft_candidate(_candidate())
    assert all(item.initial_status == "PENDING_OFFICE_REVIEW" for item in repository.list_pending_drafts("tenant-a"))


def test_database_foreign_key_rejects_orphan_personnel_row():
    connection = _connection()
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """INSERT INTO assignment_draft_personnel
               (id, draft_id, tenant_id, personnel_source_key, role_type, proposal_source, is_substitute, confidence, item_order, created_at)
               VALUES ('orphan', 'missing', 'tenant-a', 'P', 'LEADER', 'G05B', 0, 80, 0, '2026-07-20T00:00:00Z')"""
        )


def test_child_insert_failure_rolls_back_parent_and_all_children(monkeypatch):
    connection = _connection()
    repository = AssignmentDraftRepository(connection)
    original = repository._insert_personnel
    calls = {"count": 0}

    def fail_second(draft_id, tenant_id, personnel):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("injected child failure")
        original(draft_id, tenant_id, personnel)

    monkeypatch.setattr(repository, "_insert_personnel", fail_second)
    with pytest.raises(RuntimeError, match="injected"):
        repository.save_draft_candidate(_candidate())
    assert _count(connection, "assignment_drafts") == 0
    assert _count(connection, "assignment_draft_personnel") == 0


def test_no_partial_commit_after_child_failure(monkeypatch):
    connection = _connection()
    repository = AssignmentDraftRepository(connection)
    monkeypatch.setattr(repository, "_insert_personnel", lambda *args: (_ for _ in ()).throw(RuntimeError("failure")))
    with pytest.raises(RuntimeError):
        repository.save_draft_candidate(_candidate())
    assert not connection.execute("SELECT id FROM assignment_drafts").fetchall()


def test_list_pending_applies_requested_limit():
    connection = _connection()
    repository = AssignmentDraftRepository(connection)
    for document_id in ("DOC-1", "DOC-2", "DOC-3"):
        repository.save_draft_candidate(_candidate(document_id=document_id))
    assert len(repository.list_pending_drafts("tenant-a", limit=2)) == 2


def test_pending_list_orders_newest_draft_first():
    connection = _connection()
    repository = AssignmentDraftRepository(connection)
    first = repository.save_draft_candidate(_candidate(document_id="DOC-1"))
    second = repository.save_draft_candidate(_candidate(document_id="DOC-2"))
    assert [item.id for item in repository.list_pending_drafts("tenant-a")] == [second.id, first.id]


def test_list_pending_has_a_safe_maximum_limit():
    connection = _connection()
    repository = AssignmentDraftRepository(connection)
    repository.save_draft_candidate(_candidate())
    assert len(repository.list_pending_drafts("tenant-a", limit=10_000)) <= 100
    with pytest.raises(TypeError):
        repository.list_pending_drafts("tenant-a", limit="50")


def test_convenience_functions_preserve_tenant_scoping():
    connection = _connection()
    from tools.qlvb_downloader.assignment_draft_repository import get_draft_by_id, list_pending_drafts, save_draft_candidate

    saved = save_draft_candidate(connection, _candidate())
    assert get_draft_by_id(connection, "tenant-a", saved.id) is not None
    assert get_draft_by_id(connection, "tenant-b", saved.id) is None
    assert [item.id for item in list_pending_drafts(connection, "tenant-a")] == [saved.id]


def test_repository_has_no_update_or_delete_operation():
    source = inspect.getsource(AssignmentDraftRepository).lower()
    assert "def update" not in source and "def delete" not in source


def test_save_path_has_no_network_dependency(monkeypatch):
    connection = _connection()
    monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: pytest.fail("network called"))
    saved = AssignmentDraftRepository(connection).save_draft_candidate(_candidate())
    assert saved.id
