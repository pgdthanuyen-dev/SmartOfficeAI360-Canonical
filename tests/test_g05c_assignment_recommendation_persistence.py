import json
import sqlite3

import pytest

from tools.qlvb_downloader.assignment_draft_models import AssignmentDraftCandidate
from tools.qlvb_downloader.assignment_draft_repository import AssignmentDraftRepository, init_assignment_draft_schema
from tools.qlvb_downloader.domain_repository import init_domain_schema
from tools.qlvb_downloader.assignment_recommendation_models import AssignmentRecommendation, AssignmentRecommendationValidationError
from tools.qlvb_downloader.assignment_recommendation_repository import AssignmentRecommendationConflict, AssignmentRecommendationRepository, MIGRATION_VERSION, init_assignment_recommendation_schema


def repo():
    return AssignmentRecommendationRepository(sqlite3.connect(":memory:"))


def recommendation(**changes):
    data = dict(tenant_id="tenant-a", source_document_id="doc-a", source_proposal_ids=("p1", "p1"), lead_unit="unit-a", primary_assignee=None, coordinating_units=("unit-a", "unit-b", "unit-b"), assignment_reason="rule", confidence=80, source_rules=("r1",), manual_review_required=False, review_reasons=(), action_items=("a1",), provenance={"source": "canonical"})
    data.update(changes)
    return AssignmentRecommendation(**data)


def candidate(revision="1"):
    return AssignmentDraftCandidate(tenant_id="tenant-a", source_system="canonical", source_document_id="doc-a", source_revision=revision, source_identity_key="canonical:doc-a", initial_status="PENDING_OFFICE_REVIEW", task_title="Task", task_description="Description", lead_unit_source_key=None, participating_unit_source_keys=(), required_roles=(), proposed_personnel=(), proposed_start_date=None, proposed_due_date=None, priority="NORMAL", deliverables=(), checklist_items=(), milestones=(), warnings=(), unresolved_items=(), overall_confidence=0, source_engine_versions=(), source_fingerprints=(), source_input_fingerprint="a"*64, draft_content_fingerprint=("b" if revision == "1" else "c")*64)

def draft_repo():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY)")
    init_domain_schema(conn); init_assignment_draft_schema(conn)
    return conn, AssignmentDraftRepository(conn)


def test_case_01_full_contract_roundtrip():
    r = repo(); row = r.create_or_get(recommendation()); payload = json.loads(row["payload_json"])
    assert payload["action_items"] == ["a1"] and payload["provenance"] == {"source": "canonical"}


def test_case_02_create_or_get_idempotent():
    r = repo(); assert r.create_or_get(recommendation())["id"] == r.create_or_get(recommendation())["id"]


def test_case_03_payload_conflict_does_not_overwrite():
    r = repo(); before = r.create_or_get(recommendation())
    with pytest.raises(AssignmentRecommendationConflict): r.create_or_get(recommendation(assignment_reason="different"))
    assert r.get_active_for_document("tenant-a", "doc-a")["payload_sha256"] == before["payload_sha256"]


def test_case_04_tenant_isolation():
    r = repo(); first = r.create_or_get(recommendation()); second = r.create_or_get(recommendation(tenant_id="tenant-b")); assert first["id"] != second["id"]


def test_case_05_document_isolation():
    r = repo(); assert r.create_or_get(recommendation())["id"] != r.create_or_get(recommendation(source_document_id="doc-b"))["id"]


def test_case_06_coordinating_units_dedup():
    assert recommendation().coordinating_units == ("unit-b",)


def test_case_07_lead_unit_excluded():
    assert "unit-a" not in recommendation().coordinating_units


def test_case_08_nullable_assignee_roundtrip():
    r = repo(); assert json.loads(r.create_or_get(recommendation())["payload_json"])["primary_assignee"] is None


def test_case_09_manual_review_roundtrip():
    r = repo(); row = r.create_or_get(recommendation(lead_unit=None, manual_review_required=True, review_reasons=("NO_MATCH",))); payload=json.loads(row["payload_json"]); assert payload["manual_review_required"] and payload["review_reasons"] == ["NO_MATCH"]


def test_case_10_one_active_draft_constraint():
    conn,d=draft_repo(); first=d.save_draft_candidate(candidate("1")); second=d.save_draft_candidate(candidate("2")); assert conn.execute("SELECT count(*) FROM assignment_drafts WHERE is_active=1").fetchone()[0] == 1 and second.supersedes_draft_id == first.id


def test_case_11_supersession_preserves_history():
    conn,d=draft_repo(); d.save_draft_candidate(candidate("1")); d.save_draft_candidate(candidate("2")); assert conn.execute("SELECT count(*) FROM assignment_drafts").fetchone()[0] == 2


def test_case_12_migration_rerun_preserves_data():
    r=repo(); row=r.create_or_get(recommendation()); init_assignment_recommendation_schema(r.conn); assert r.get_active_for_document("tenant-a","doc-a")["id"] == row["id"] and r.conn.execute("SELECT count(*) FROM schema_migrations WHERE version=?",(MIGRATION_VERSION,)).fetchone()[0] == 1


def test_case_13_injected_failure_rolls_back():
    r=repo(); r.conn.execute("BEGIN"); r.create_or_get(recommendation())
    r.conn.rollback(); assert r.get_active_for_document("tenant-a", "doc-a") is None


def test_case_14_sensitive_error_redaction():
    with pytest.raises(AssignmentRecommendationValidationError) as exc:
        recommendation(provenance={"token": "hidden-value"})
    assert "hidden-value" not in str(exc.value) and "token" not in str(exc.value).lower()
