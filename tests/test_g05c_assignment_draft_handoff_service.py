from __future__ import annotations

from dataclasses import asdict

import pytest

from tools.qlvb_downloader.assignment_draft_models import AssignmentDraftCandidate, AssignmentDraftPersonnelProposal
from tools.qlvb_downloader.assignment_draft_repository import AssignmentDraftRepository
from tools.qlvb_downloader.assignment_draft_service import AssignmentDraftService, AssignmentDraftServiceError
from tools.qlvb_downloader.index_db import open_db
from tools.qlvb_downloader.planner_draft_handoff_client import PlannerHandoffOutcome, PlannerHandoffResult


class _Client:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = 0
        self.last_handoff = None

    def send(self, handoff):
        self.calls += 1
        self.last_handoff = handoff
        return self.results.pop(0)

    def planner_draft_url(self, planner_draft_id):
        return f"https://planner.example/drafts/{planner_draft_id}" if planner_draft_id else None


def _candidate() -> AssignmentDraftCandidate:
    return AssignmentDraftCandidate(
        tenant_id="tenant-a", source_system="qlvb", source_document_id="DOC-1", source_revision="REV-1",
        source_identity_key="qlvb:DOC-1", initial_status="PENDING_OFFICE_REVIEW", task_title="Demo",
        task_description="Description", lead_unit_source_key="UNIT-A", participating_unit_source_keys=(),
        required_roles=("LEAD_EXECUTOR",), proposed_personnel=(
            AssignmentDraftPersonnelProposal("P-1", "LEAD_EXECUTOR", "G05B", False, 90, 0),
        ), proposed_start_date=None, proposed_due_date=None, priority="NORMAL", deliverables=(),
        checklist_items=(), milestones=(), warnings=(), unresolved_items=(), overall_confidence=90,
        source_engine_versions=(("g05", "1"),), source_fingerprints=(("g05", "a" * 64),),
        source_input_fingerprint="a" * 64, draft_content_fingerprint="b" * 64,
        document_number="12/VP", subject="Official subject", issuing_agency="Issuing agency",
    )


def _service_with_draft(tmp_path, client: _Client):
    service = AssignmentDraftService(str(tmp_path), handoff_client=client)
    connection = open_db(str(tmp_path))
    try:
        from tools.qlvb_downloader.assignment_draft_repository import init_assignment_draft_schema

        init_assignment_draft_schema(connection)
        draft = AssignmentDraftRepository(connection).save_draft_candidate(_candidate())
    finally:
        connection.close()
    return service, draft


def _result(outcome, planner_draft_id="planner-1", *, http_status=201, message=""):
    return PlannerHandoffResult(outcome, "correlation-1", planner_draft_id, "PENDING_OFFICE_REVIEW", message=message, http_status=http_status)


def test_created_is_persisted_with_one_append_only_attempt_and_survives_reload(tmp_path):
    service, draft = _service_with_draft(tmp_path, _Client(_result(PlannerHandoffOutcome.CREATED)))
    assert service.send_draft_to_planner("tenant-a", draft.id).outcome is PlannerHandoffOutcome.CREATED
    reloaded = AssignmentDraftService(str(tmp_path)).get_draft_detail("tenant-a", draft.id)
    assert reloaded.planner_handoff_status == "SENT" and reloaded.planner_draft_id == "planner-1"
    assert reloaded.planner_handoff_result == "CREATED" and reloaded.planner_handoff_correlation_id == "correlation-1"
    assert len(reloaded.planner_handoff_attempts) == 1
    assert reloaded.planner_handoff_attempts[0].result == "CREATED"


def test_handoff_uses_persisted_source_metadata_without_creating_a_second_draft(tmp_path):
    client = _Client(_result(PlannerHandoffOutcome.CREATED))
    service, draft = _service_with_draft(tmp_path, client)
    service.send_draft_to_planner("tenant-a", draft.id)
    payload = client.last_handoff.to_planner_receiver_payload()
    assert (payload["documentNumber"], payload["subject"], payload["issuingAgency"]) == (
        "12/VP", "Official subject", "Issuing agency",
    )
    reloaded = AssignmentDraftService(str(tmp_path)).get_draft_detail("tenant-a", draft.id)
    assert reloaded.planner_handoff_status == "SENT"
    assert (reloaded.document_number, reloaded.subject, reloaded.issuing_agency) == (
        "12/VP", "Official subject", "Issuing agency",
    )


def test_duplicate_appends_without_overwriting_created_attempt_or_duplicate_draft(tmp_path):
    client = _Client(_result(PlannerHandoffOutcome.CREATED), _result(PlannerHandoffOutcome.DUPLICATE, http_status=200))
    service, draft = _service_with_draft(tmp_path, client)
    service.send_draft_to_planner("tenant-a", draft.id)
    assert service.send_draft_to_planner("tenant-a", draft.id).outcome is PlannerHandoffOutcome.DUPLICATE
    reloaded = service.get_draft_detail("tenant-a", draft.id)
    assert [item.result for item in reloaded.planner_handoff_attempts] == ["CREATED", "DUPLICATE"]
    assert reloaded.planner_draft_id == "planner-1" and reloaded.planner_handoff_status == "SENT"
    connection = open_db(str(tmp_path))
    try:
        assert connection.execute("SELECT count(*) FROM assignment_drafts").fetchone()[0] == 1
    finally:
        connection.close()


@pytest.mark.parametrize(("outcome", "status"), [
    (PlannerHandoffOutcome.VALIDATION_ERROR, "FAILED"),
    (PlannerHandoffOutcome.AUTH_ERROR, "FAILED"),
    (PlannerHandoffOutcome.UNKNOWN_RESULT, "UNKNOWN"),
])
def test_errors_are_persisted_without_erasing_a_previous_planner_draft_id(tmp_path, outcome, status):
    client = _Client(_result(PlannerHandoffOutcome.CREATED), _result(outcome, None, http_status=None, message="safe failure"))
    service, draft = _service_with_draft(tmp_path, client)
    service.send_draft_to_planner("tenant-a", draft.id)
    assert service.send_draft_to_planner("tenant-a", draft.id).outcome is outcome
    reloaded = service.get_draft_detail("tenant-a", draft.id)
    assert reloaded.planner_handoff_status == status and reloaded.planner_draft_id == "planner-1"
    assert reloaded.planner_handoff_attempts[-1].result == outcome.value
    assert reloaded.planner_handoff_error == "safe failure"


def test_attempts_are_credential_free_and_keep_the_stable_idempotency_hash(tmp_path):
    service, draft = _service_with_draft(tmp_path, _Client(_result(PlannerHandoffOutcome.AUTH_ERROR, None, http_status=401, message="token=must-not-persist")))
    service.send_draft_to_planner("tenant-a", draft.id)
    stored = service.get_draft_detail("tenant-a", draft.id)
    rendered = str(asdict(stored.planner_handoff_attempts[0])).lower()
    assert len(stored.planner_handoff_attempts[0].idempotency_key_hash) == 64
    assert "secret" not in rendered and "token" not in rendered and "cookie" not in rendered
    assert stored.planner_handoff_error == "Planner handoff failed."


def test_persistence_failure_returns_local_error_without_a_second_planner_call(monkeypatch, tmp_path):
    client = _Client(_result(PlannerHandoffOutcome.CREATED))
    service, draft = _service_with_draft(tmp_path, client)
    monkeypatch.setattr(AssignmentDraftRepository, "record_planner_handoff_attempt", lambda *_: (_ for _ in ()).throw(RuntimeError("sqlite write failed")))
    result = service.send_draft_to_planner("tenant-a", draft.id)
    assert result.outcome is PlannerHandoffOutcome.LOCAL_PERSISTENCE_ERROR
    assert client.calls == 1


def test_conflicting_planner_draft_id_is_appended_but_never_overwrites_the_existing_link(tmp_path):
    client = _Client(_result(PlannerHandoffOutcome.CREATED, "planner-1"), _result(PlannerHandoffOutcome.DUPLICATE, "planner-2", http_status=200))
    service, draft = _service_with_draft(tmp_path, client)
    service.send_draft_to_planner("tenant-a", draft.id)
    result = service.send_draft_to_planner("tenant-a", draft.id)
    reloaded = service.get_draft_detail("tenant-a", draft.id)
    assert result.outcome is PlannerHandoffOutcome.LOCAL_PERSISTENCE_ERROR
    assert reloaded.planner_draft_id == "planner-1"
    assert len(reloaded.planner_handoff_attempts) == 2
    assert reloaded.planner_handoff_attempts[-1].planner_draft_id == "planner-2"
    assert reloaded.planner_handoff_attempts[-1].error_code == "PLANNER_DRAFT_ID_CONFLICT"


def test_schema_upgrade_adds_handoff_columns_to_a_pre_b8a_assignment_draft_database(tmp_path):
    import sqlite3
    from tools.qlvb_downloader.assignment_draft_repository import init_assignment_draft_schema

    connection = sqlite3.connect(tmp_path / "legacy.db")
    connection.execute("CREATE TABLE schema_migrations(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
    connection.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY)")
    connection.execute("""CREATE TABLE assignment_drafts (
        id TEXT PRIMARY KEY, tenant_id TEXT, source_system TEXT, source_document_id TEXT, source_revision TEXT,
        source_identity_key TEXT, draft_version INTEGER, initial_status TEXT, task_title TEXT, task_description TEXT,
        lead_unit_source_key TEXT, proposed_start_date TEXT, proposed_due_date TEXT, priority TEXT, overall_confidence REAL,
        source_input_fingerprint TEXT, draft_content_fingerprint TEXT, participating_units_json TEXT, deliverables_json TEXT,
        checklist_items_json TEXT, milestones_json TEXT, warnings_json TEXT, unresolved_items_json TEXT,
        source_engine_versions_json TEXT, source_fingerprints_json TEXT, supersedes_draft_id TEXT, created_at TEXT,
        created_by_system TEXT, schema_version TEXT, builder_version TEXT
    )""")
    try:
        init_assignment_draft_schema(connection)
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(assignment_drafts)").fetchall()}
        assert {"planner_handoff_status", "planner_draft_id", "planner_handoff_at", "planner_handoff_result"} <= columns
        assert {"document_number", "subject", "issuing_agency"} <= columns
        assert connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version='g05c_assignment_draft_source_metadata_1'"
        ).fetchone()
        assert connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='assignment_draft_planner_handoff_attempts'").fetchone()
    finally:
        connection.close()


def test_service_rejects_a_non_pending_snapshot_before_handoff(tmp_path):
    client = _Client(_result(PlannerHandoffOutcome.CREATED))
    service, draft = _service_with_draft(tmp_path, client)
    connection = open_db(str(tmp_path))
    try:
        connection.execute(
            """INSERT INTO assignment_draft_review_events
               (id, draft_id, tenant_id, event_type, reviewer_reference, reason, changes_json, created_at)
               VALUES ('superseded', ?, 'tenant-a', 'SUPERSEDED', 'reviewer', NULL, '{}', '2026-07-21T00:00:00Z')""",
            (draft.id,),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(AssignmentDraftServiceError, match="khong con"):
        service.send_draft_to_planner("tenant-a", draft.id)
    assert client.calls == 0


def test_ui_has_no_secret_or_direct_planner_http_client():
    import inspect
    from tools.qlvb_downloader.assignment_draft_ui import AssignmentDraftDetailDialog

    source = inspect.getsource(AssignmentDraftDetailDialog).lower()
    assert "planner_token" not in source and "planner_url" not in source
    assert "requests" not in source and "urlopen" not in source
