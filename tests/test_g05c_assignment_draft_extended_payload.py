from __future__ import annotations

import sqlite3
from dataclasses import replace
from types import SimpleNamespace

from tools.qlvb_downloader.assignment_draft_builder import build_assignment_draft_from_canonical_source
from tools.qlvb_downloader.assignment_draft_models import AssignmentDraftBuildRequest, AssignmentDraftSourceAttachment
from tools.qlvb_downloader.assignment_draft_planner_handoff import build_planner_handoff
from tools.qlvb_downloader.assignment_draft_repository import AssignmentDraftRepository, init_assignment_draft_schema
from tools.qlvb_downloader.assignment_draft_review import AssignmentDraftReviewService
from tools.qlvb_downloader.assignment_draft_service import AssignmentDraftService
from tools.qlvb_downloader.domain_models import Attachment, AttachmentValidationStatus, Document
from tools.qlvb_downloader.domain_repository import DomainRepository
from tools.qlvb_downloader.index_db import open_db
from tools.qlvb_downloader.planner_draft_handoff_client import PlannerHandoffOutcome, PlannerHandoffResult


def _proposal(document_id: str, revision: str, fingerprint: str, **values):
    return SimpleNamespace(
        document_id=document_id, document_revision=revision, input_fingerprint=fingerprint,
        engine_version=values.pop("engine_version", "test.engine.1"), confidence=values.pop("confidence", 90),
        overall_confidence=values.pop("overall_confidence", 90), lead_unit_key="UNIT-A",
        coordinating_unit_keys=[], required_roles=[], role_recommendations=[], unresolved_roles=[],
        conflicting_roles=[], warnings=[], **values,
    )


def _request() -> AssignmentDraftBuildRequest:
    return AssignmentDraftBuildRequest(
        tenant_id="tenant-a", source_system="CanonicalQLVB", source_document_id="DOC-1", source_revision="REV-1",
        document_number="12/VP", subject="Source subject", issuing_agency="Source agency",
        normalized_summary="T\u00f3m t\u1eaft v\u0103n b\u1ea3n ngu\u1ed3n", received_date="2026-07-20", issued_date="2026-07-19",
        proposed_task_title="Task title", proposed_task_description="Task description", proposed_start_date=None,
        proposed_due_date="2026-07-25", proposed_priority="NORMAL", g05a_proposal=_proposal("DOC-1", "REV-1", "a" * 64),
        g05b_proposal=_proposal("DOC-1", "REV-1", "b" * 64), file_reference_placeholder="canonical-source",
    )


def _canonical_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY, title TEXT)")
    domain = DomainRepository(connection)
    document = Document(
        id="domain-doc-1", tenant_id="tenant-a", source_system="CanonicalQLVB", source_document_id="DOC-1",
        source_revision="REV-1", issued_date="2026-07-19", subject="Source subject",
    )
    domain.save_document(document)
    domain.save_attachment(Attachment(
        id="attachment-1", document_id=document.id, source_attachment_id="source-attachment-1",
        file_name="T\u1ec7p ngu\u1ed3n.pdf", mime_type="application/pdf", size_bytes=1024, sha256="c" * 64,
        storage_path="C:\\private\\source.pdf", download_source="https://source.example.test/file?token=excluded",
        validation_status=AttachmentValidationStatus.VALIDATED,
    ))
    init_assignment_draft_schema(connection)
    return connection


def test_canonical_source_metadata_persists_reloads_and_maps_to_the_planner_payload():
    connection = _canonical_connection()
    saved = AssignmentDraftRepository(connection).save_draft_candidate(build_assignment_draft_from_canonical_source(_request(), connection))
    reloaded = AssignmentDraftRepository(connection).get_draft_by_id("tenant-a", saved.id)
    assert reloaded is not None
    assert (reloaded.source_system, reloaded.issued_date, reloaded.summary) == (
        "CanonicalQLVB", "2026-07-19", "T\u00f3m t\u1eaft v\u0103n b\u1ea3n ngu\u1ed3n",
    )
    assert reloaded.source_attachments == (
        AssignmentDraftSourceAttachment("source-attachment-1", "T\u1ec7p ngu\u1ed3n.pdf", "application/pdf", 1024, "c" * 64),
    )
    payload = build_planner_handoff(reloaded).to_planner_receiver_payload()
    assert payload["sourceSystem"] == "CanonicalQLVB"
    assert payload["issuedDate"] == "2026-07-19"
    assert payload["summary"] == "T\u00f3m t\u1eaft v\u0103n b\u1ea3n ngu\u1ed3n"
    assert payload["summary"] not in {payload["taskTitle"], payload["taskDescription"], payload["subject"]}
    assert payload["sourceAttachments"] == [{
        "sourceAttachmentId": "source-attachment-1", "fileName": "T\u1ec7p ngu\u1ed3n.pdf",
        "mimeType": "application/pdf", "sizeBytes": 1024, "checksum": "c" * 64,
    }]
    rendered = str(payload).lower()
    for prohibited in ("storage_path", "download_source", "private\\source", "token="):
        assert prohibited not in rendered


def test_legacy_snapshot_and_office_revision_preserve_extended_source_metadata():
    connection = _canonical_connection()
    repository = AssignmentDraftRepository(connection)
    saved = repository.save_draft_candidate(build_assignment_draft_from_canonical_source(_request(), connection))
    revised = AssignmentDraftReviewService(connection).create_office_revision(
        "tenant-a", saved.id, "office", "title update", {"task_title": "Revised task"},
    )
    assert revised.supersedes_draft_id == saved.id
    assert (revised.issued_date, revised.summary, revised.source_attachments) == (
        saved.issued_date, saved.summary, saved.source_attachments,
    )
    legacy = repository.save_draft_candidate(replace(
        build_assignment_draft_from_canonical_source(_request(), connection), source_document_id="DOC-2",
        source_identity_key="CanonicalQLVB:DOC-2", source_revision="REV-2", issued_date=None, summary=None,
        source_attachments=(), source_input_fingerprint="d" * 64, draft_content_fingerprint="e" * 64,
    ))
    legacy_payload = build_planner_handoff(legacy).to_planner_receiver_payload()
    assert legacy_payload["issuedDate"] is None and legacy_payload["summary"] is None
    assert legacy_payload["sourceAttachments"] == []


class _Client:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = 0
        self.last_handoff = None

    def send(self, handoff):
        self.calls += 1
        self.last_handoff = handoff
        return self.results.pop(0)

    def planner_draft_url(self, _planner_draft_id):
        return None


def _result(outcome: PlannerHandoffOutcome, planner_draft_id: str = "planner-1"):
    return PlannerHandoffResult(outcome, "correlation", planner_draft_id, "PENDING_OFFICE_REVIEW", http_status=201)


def test_created_and_duplicate_handoff_keep_extended_metadata_without_duplicate_attachments(tmp_path):
    connection = open_db(str(tmp_path))
    try:
        domain = DomainRepository(connection)
        document = Document(id="domain-doc-1", tenant_id="tenant-a", source_system="CanonicalQLVB", source_document_id="DOC-1", source_revision="REV-1")
        domain.save_document(document)
        domain.save_attachment(Attachment(id="attachment-1", document_id=document.id, file_name="source.pdf", validation_status=AttachmentValidationStatus.VALIDATED))
        init_assignment_draft_schema(connection)
        draft = AssignmentDraftRepository(connection).save_draft_candidate(build_assignment_draft_from_canonical_source(_request(), connection))
    finally:
        connection.close()
    client = _Client(_result(PlannerHandoffOutcome.CREATED), _result(PlannerHandoffOutcome.DUPLICATE))
    service = AssignmentDraftService(str(tmp_path), handoff_client=client)
    assert service.send_draft_to_planner("tenant-a", draft.id).outcome is PlannerHandoffOutcome.CREATED
    assert service.send_draft_to_planner("tenant-a", draft.id).outcome is PlannerHandoffOutcome.DUPLICATE
    reloaded = service.get_draft_detail("tenant-a", draft.id)
    assert client.calls == 2 and len(reloaded.source_attachments) == 1
    assert client.last_handoff.to_planner_receiver_payload()["sourceAttachments"][0]["fileName"] == "source.pdf"
    assert len(reloaded.planner_handoff_attempts) == 2


def test_invalid_source_metadata_records_validation_error_before_http(tmp_path):
    connection = open_db(str(tmp_path))
    try:
        init_assignment_draft_schema(connection)
        candidate = build_assignment_draft_from_canonical_source(_request(), connection)
        draft = AssignmentDraftRepository(connection).save_draft_candidate(replace(
            candidate, source_attachments=(AssignmentDraftSourceAttachment("bad", "C:\\private\\source.pdf"),),
        ))
    finally:
        connection.close()
    client = _Client()
    result = AssignmentDraftService(str(tmp_path), handoff_client=client).send_draft_to_planner("tenant-a", draft.id)
    reloaded = AssignmentDraftService(str(tmp_path)).get_draft_detail("tenant-a", draft.id)
    assert result.outcome is PlannerHandoffOutcome.VALIDATION_ERROR and client.calls == 0
    assert reloaded.planner_draft_id is None and reloaded.planner_handoff_attempts[-1].result == "VALIDATION_ERROR"
