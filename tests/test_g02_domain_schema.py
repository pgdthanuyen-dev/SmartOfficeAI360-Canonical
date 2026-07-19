from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tools.qlvb_downloader.domain_models import (
    ActionItem,
    ActionItemStatus,
    Attachment,
    AttachmentValidationStatus,
    Document,
    DocumentType,
    MappingStatus,
    ReviewDecision,
    ReviewDecisionType,
    SourceCitation,
    SyncEvent,
    SyncEventStatus,
    UserUnitMapping,
    compute_stable_hash,
    utc_now_iso,
)
from tools.qlvb_downloader.domain_repository import DomainRepository, init_domain_schema
from tools.qlvb_downloader.domain_validation import (
    DomainValidationError,
    is_action_item_sync_eligible,
    validate_action_item,
    validate_action_item_transition,
    validate_user_unit_mapping,
)
from tools.qlvb_downloader.index_db import init_db
from tools.qlvb_downloader.models import ATTACHMENT_VALIDATED, AttachmentInfo, DocumentRecord
from tools.qlvb_downloader.storage import StorageManager


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    init_db(":memory:").close()
    init_domain_schema(conn) if _has_documents_table(conn) else None
    return conn


def _repo() -> tuple[sqlite3.Connection, DomainRepository]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY)")
    repo = DomainRepository(conn)
    return conn, repo


def _has_documents_table(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='documents'").fetchone() is not None


def _document() -> Document:
    return Document(
        id="doc-1",
        tenant_id="tenant-a",
        source_system="QLVB",
        source_document_id="qlvb-123",
        source_revision="1",
        document_type=DocumentType.INCOMING,
        document_number=None,
        issued_date="2026-07-19",
        received_date="2026-07-19",
        issuer="UBND",
        signer="Nguyen Van A",
        subject="Chi dao xu ly cong viec",
        summary="Tom tat van ban",
        urgency="NORMAL",
        source_url="https://qlvb.example/detail/123",
        content_sha256="a" * 64,
    )


def _action(document_id: str = "doc-1", *, status: ActionItemStatus = ActionItemStatus.PROPOSED, title: str = "Xu ly van ban") -> ActionItem:
    return ActionItem(
        id="action-1",
        document_id=document_id,
        ordinal=1,
        title=title,
        description="Mo ta nhiem vu",
        proposed_due_date="2026-08-01",
        ai_confidence=0.75,
        status=status,
    )


def test_document_serialize_deserialize_and_datetime_roundtrip():
    doc = _document()
    payload = doc.to_dict()
    loaded = Document.from_dict(payload)

    assert loaded.to_dict() == payload
    assert loaded.created_at.endswith("+00:00")
    assert loaded.updated_at.endswith("+00:00")
    assert loaded.document_number is None


def test_attachment_statuses_are_g01_compatible():
    attachment = Attachment(
        id="att-1",
        document_id="doc-1",
        file_name="main.pdf",
        validation_status=AttachmentValidationStatus.VALIDATED,
        sha256="b" * 64,
    )

    assert attachment.validation_status.value == ATTACHMENT_VALIDATED
    attachment.validate()


def test_document_can_have_many_action_items():
    conn, repo = _repo()
    try:
        repo.save_document(_document())
        repo.save_action_item(_action())
        repo.save_action_item(ActionItem(id="action-2", document_id="doc-1", ordinal=2, title="Bao cao ket qua"))

        items = repo.list_action_items("doc-1")
        assert [item["id"] for item in items] == ["action-1", "action-2"]
    finally:
        conn.close()


def test_action_item_can_have_many_citations():
    conn, repo = _repo()
    try:
        repo.save_document(_document())
        repo.save_action_item(_action())
        repo.save_attachment(Attachment(id="att-1", document_id="doc-1", file_name="main.pdf"))
        repo.save_citation(SourceCitation(id="cit-1", action_item_id="action-1", document_id="doc-1", attachment_id="att-1", page_start=1, page_end=1, excerpt="Can xu ly"))
        repo.save_citation(SourceCitation(id="cit-2", action_item_id="action-1", document_id="doc-1", attachment_id="att-1", char_start=10, char_end=20, excerpt="Trong han"))

        count = conn.execute("SELECT COUNT(*) FROM source_citations WHERE action_item_id = ?", ("action-1",)).fetchone()[0]
        assert count == 2
    finally:
        conn.close()


def test_citation_wrong_document_is_rejected():
    conn, repo = _repo()
    try:
        repo.save_document(_document())
        repo.save_document(Document(id="doc-2", tenant_id="tenant-a", source_system="QLVB", source_document_id="qlvb-456"))
        repo.save_action_item(_action(document_id="doc-1"))

        with pytest.raises(DomainValidationError):
            repo.save_citation(SourceCitation(id="cit-bad", action_item_id="action-1", document_id="doc-2", excerpt="Sai document"))
    finally:
        conn.close()


def test_confidence_out_of_range_is_rejected():
    action = _action()
    action.ai_confidence = 1.5

    with pytest.raises(DomainValidationError):
        validate_action_item(action)


def test_approved_action_item_requires_title():
    action = _action(status=ActionItemStatus.APPROVED, title="")

    with pytest.raises(DomainValidationError):
        validate_action_item(action)


def test_rejected_action_item_is_not_syncable():
    assert is_action_item_sync_eligible(ActionItemStatus.REJECTED) is False

    conn, repo = _repo()
    try:
        repo.save_document(_document())
        repo.save_action_item(_action(status=ActionItemStatus.REJECTED))
        with pytest.raises(DomainValidationError):
            repo.append_sync_event(
                SyncEvent(
                    id="sync-rejected",
                    action_item_id="action-1",
                    target_system="PlannerKPI",
                    idempotency_key="tenant/doc/action/rejected",
                    attempt_number=1,
                    status=SyncEventStatus.PENDING,
                )
            )
    finally:
        conn.close()


def test_sync_pending_requires_prior_approved_transition():
    with pytest.raises(DomainValidationError):
        validate_action_item_transition(ActionItemStatus.PROPOSED, ActionItemStatus.SYNC_PENDING)

    validate_action_item_transition(ActionItemStatus.APPROVED, ActionItemStatus.SYNC_PENDING)


def test_review_history_is_append_only():
    conn, repo = _repo()
    try:
        repo.save_document(_document())
        repo.save_action_item(_action())
        before = json.dumps({"status": "PENDING_REVIEW"})
        after = json.dumps({"status": "APPROVED"})
        repo.append_review_decision(
            ReviewDecision(
                id="review-1",
                action_item_id="action-1",
                decision=ReviewDecisionType.APPROVE,
                reviewer_id="user-1",
                before_json=before,
                after_json=after,
            )
        )
        repo.append_review_decision(
            ReviewDecision(
                id="review-2",
                action_item_id="action-1",
                decision=ReviewDecisionType.REQUEST_CHANGES,
                reviewer_display_name="System",
            )
        )

        count = conn.execute("SELECT COUNT(*) FROM review_decisions WHERE action_item_id = ?", ("action-1",)).fetchone()[0]
        assert count == 2
    finally:
        conn.close()


def test_sync_event_idempotency_key_is_unique():
    conn, repo = _repo()
    try:
        repo.save_document(_document())
        repo.save_action_item(_action(status=ActionItemStatus.APPROVED))
        event = SyncEvent(id="sync-1", action_item_id="action-1", target_system="PlannerKPI", idempotency_key="idem-1", attempt_number=1, status=SyncEventStatus.PENDING)
        repo.append_sync_event(event)

        with pytest.raises(sqlite3.IntegrityError):
            repo.append_sync_event(SyncEvent(id="sync-2", action_item_id="action-1", target_system="PlannerKPI", idempotency_key="idem-1", attempt_number=2, status=SyncEventStatus.PENDING))
    finally:
        conn.close()


def test_user_unit_mapping_ambiguous_defaults_to_needs_review():
    mapping = UserUnitMapping(
        tenant_id="tenant-a",
        source_system="QLVB",
        source_key="van-thu",
        source_display_name="Van thu",
    )

    assert mapping.status == MappingStatus.NEEDS_REVIEW
    validate_user_unit_mapping(mapping)


def test_ambiguous_active_user_unit_mapping_is_rejected():
    mapping = UserUnitMapping(
        tenant_id="tenant-a",
        source_system="QLVB",
        source_key="van-thu",
        source_display_name="Van thu",
        status=MappingStatus.ACTIVE,
    )

    with pytest.raises(DomainValidationError):
        validate_user_unit_mapping(mapping)


def test_domain_migration_runs_first_time():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY, title TEXT)")
    try:
        init_domain_schema(conn)
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"attachments", "action_items", "source_citations", "review_decisions", "sync_events", "user_unit_mappings", "schema_migrations"} <= tables
    finally:
        conn.close()


def test_domain_migration_is_idempotent():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY, title TEXT)")
    try:
        init_domain_schema(conn)
        init_domain_schema(conn)
        count = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
        assert count == 1
    finally:
        conn.close()


def test_old_database_opens_without_losing_legacy_data():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY, title TEXT)")
    conn.execute("INSERT INTO documents(doc_id, title) VALUES (?, ?)", ("legacy-doc", "Legacy title"))
    try:
        init_domain_schema(conn)
        row = conn.execute("SELECT doc_id, title FROM documents WHERE doc_id = ?", ("legacy-doc",)).fetchone()
        assert dict(row) == {"doc_id": "legacy-doc", "title": "Legacy title"}
    finally:
        conn.close()


def test_foreign_key_rejects_attachment_without_document():
    conn, repo = _repo()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            repo.save_attachment(Attachment(id="att-missing", document_id="missing-doc", file_name="missing.pdf"))
    finally:
        conn.close()


def test_cascade_delete_removes_action_items():
    conn, repo = _repo()
    try:
        repo.save_document(_document())
        repo.save_action_item(_action())
        conn.execute("DELETE FROM documents WHERE doc_id = ?", ("doc-1",))
        conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM action_items WHERE document_id = ?", ("doc-1",)).fetchone()[0]
        assert count == 0
    finally:
        conn.close()


def test_stable_hash_is_repeatable_for_same_data():
    payload = {"b": 2, "a": 1, "nested": {"x": None}}

    assert compute_stable_hash(payload) == compute_stable_hash({"nested": {"x": None}, "a": 1, "b": 2})


def test_stable_hash_changes_when_business_content_changes():
    doc = _document()
    original = doc.compute_stable_hash()
    doc.subject = "Noi dung thay doi"

    assert doc.compute_stable_hash() != original


def test_manifest_2_0_0_legacy_shape_remains_readable(tmp_path):
    queue_dir = tmp_path / "queue" / "incoming" / "doc-legacy"
    queue_dir.mkdir(parents=True)
    (queue_dir / ".ready").write_text("READY", encoding="utf-8")
    manifest = {
        "schema_version": "2.0.0",
        "source": "QLVB",
        "direction": "incoming",
        "doc_id": "doc-legacy",
        "external_doc_id": "doc-legacy",
        "main_document": None,
        "attachments": [],
        "sync": {"planner_kpi_status": "PENDING"},
    }
    (queue_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    storage = StorageManager(tmp_path)
    item = storage.get_queue_item_files("incoming", "doc-legacy")
    assert item is not None
    assert item["manifest"]["schema_version"] == "2.0.0"


def test_g01_queue_still_creates_ready_manifest(tmp_path):
    src = tmp_path / "valid.pdf"
    src.write_bytes(b"%PDF-1.4\n%%EOF")
    rec = DocumentRecord(
        direction="incoming",
        source_url="https://qlvb.example/incoming",
        row_index=1,
        row_text="row",
        doc_id="incoming_valid_g02",
        title="Valid attachment",
    )
    rec.attachments = [
        AttachmentInfo(
            text="main",
            href="https://qlvb.example/valid.pdf",
            saved_path=str(src),
            status=ATTACHMENT_VALIDATED,
        )
    ]
    rec.status = "READY"

    storage = StorageManager(tmp_path / "data")
    paths = storage.write_document_outputs(rec)
    queue_dir = Path(paths["queue_ready_dir"])

    assert (queue_dir / ".ready").exists()
    assert (queue_dir / "manifest.json").exists()
    manifest = json.loads((queue_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "2.0.0"
