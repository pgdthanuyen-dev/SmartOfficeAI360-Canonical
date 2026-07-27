from __future__ import annotations

import sqlite3
import socket
from dataclasses import fields
from types import SimpleNamespace

import pytest

from tools.qlvb_downloader.assignment_recommendation_models import AssignmentRecommendation
from tools.qlvb_downloader.assignment_recommendation_repository import (
    AssignmentRecommendationProjectionError, AssignmentRecommendationRepository,
)
from tools.qlvb_downloader.assignment_draft_models import AssignmentDraftCandidate
from tools.qlvb_downloader.assignment_draft_repository import (
    AssignmentDraftProjectionError, AssignmentDraftRepository, init_assignment_draft_schema,
)
from tools.qlvb_downloader.domain_repository import init_domain_schema
from tools.qlvb_downloader.planner_draft_handoff_v1_models import (
    ASSIGNMENT_PROVENANCE_INCOMPLETE, CONTRACT_VERSION, PRIMARY_ASSIGNEE_UNRESOLVED,
    SAFE_ATTACHMENT_URL_UNAVAILABLE, SOURCE_SYSTEM,
)
from tools.qlvb_downloader.planner_draft_handoff_v1_projection import (
    PlannerDraftHandoffProjectionError, build_planner_draft_handoff_projection_v1,
)


def draft(**overrides):
    values = dict(id="draft-1", tenant_id="tenant-a", source_document_id="document-a", draft_version=2,
                  supersedes_draft_id=None, document_number="number", subject="subject", issuing_agency="agency",
                  issued_date="2026-01-01", summary="summary", lead_unit_source_key="unit-a",
                  participating_unit_source_keys=("unit-b", "unit-a", "unit-b"), proposed_due_date=None,
                  priority="NORMAL", source_attachments=(), builder_version="builder")
    values.update(overrides)
    return SimpleNamespace(**values)


def recommendation(**overrides):
    values = dict(tenant_id="tenant-a", source_document_id="document-a", lead_unit="unit-a",
                  primary_assignee="person-a", coordinating_units=("unit-b", "unit-a", "unit-b"),
                  assignment_reason="reason", confidence=80, source_rules=("rule-b", "rule-a"),
                  manual_review_required=False, review_reasons=(), action_items=(), provenance={},
                  source_proposal_ids=("proposal-b", "proposal-a"))
    values.update(overrides)
    return AssignmentRecommendation(**values)


def proposal(identifier="proposal-a"):
    return dict(tenant_id="tenant-a", document_id="document-a", external_proposal_id=identifier,
                proposal_item_id=identifier + "-item", action_id=identifier + "-action", action_title="title",
                citations=({"id": identifier + "-citation", "attachment_id": "att", "page_start": 1, "page_end": 1, "excerpt_sha256": "hash"},))


def test_valid_projection_is_frozen_deterministic_and_scoped():
    first = build_planner_draft_handoff_projection_v1(draft=draft(), recommendation=recommendation(), proposals=(proposal("proposal-b"), proposal("proposal-a")), source_draft_version=2)
    second = build_planner_draft_handoff_projection_v1(draft=draft(), recommendation=recommendation(), proposals=(proposal("proposal-a"), proposal("proposal-b")), source_draft_version=2)
    assert first == second
    assert first.contract_version == CONTRACT_VERSION and first.source_system == SOURCE_SYSTEM
    assert first.coordinating_unit_source_keys == ("unit-b",)
    assert first.source_proposal_ids == ("proposal-a", "proposal-b")
    with pytest.raises((AttributeError, TypeError)):
        first.source_document_id = "other"
    with pytest.raises(TypeError):
        first.action_items[0]["action_id"] = "other"


def test_missing_optional_values_escalate_without_fabricating_data():
    value = build_planner_draft_handoff_projection_v1(
        draft=draft(document_number=None, subject=None, source_attachments=(object(),)), recommendation=None
    )
    assert value.attachments == ()
    assert value.required_action is None and value.received_date is None
    assert value.manual_review_required
    assert PRIMARY_ASSIGNEE_UNRESOLVED in value.warning_codes
    assert SAFE_ATTACHMENT_URL_UNAVAILABLE in value.warning_codes


@pytest.mark.parametrize("field,value,code", [
    ("tenant_id", "tenant-b", "TENANT_BOUNDARY_MISMATCH"),
    ("source_document_id", "document-b", "SOURCE_DOCUMENT_BOUNDARY_MISMATCH"),
])
def test_recommendation_boundary_mismatch_is_fatal(field, value, code):
    with pytest.raises(PlannerDraftHandoffProjectionError, match=code):
        build_planner_draft_handoff_projection_v1(draft=draft(), recommendation=recommendation(**{field: value}))


def test_proposal_boundary_and_version_mismatch_are_fatal():
    with pytest.raises(PlannerDraftHandoffProjectionError, match="TENANT_BOUNDARY_MISMATCH"):
        build_planner_draft_handoff_projection_v1(draft=draft(), recommendation=recommendation(), proposals=(proposal() | {"tenant_id": "tenant-b"},))
    with pytest.raises(PlannerDraftHandoffProjectionError, match="SOURCE_DRAFT_VERSION_MISMATCH"):
        build_planner_draft_handoff_projection_v1(draft=draft(), recommendation=recommendation(), source_draft_version=1)


def _stored_candidate(revision: str) -> AssignmentDraftCandidate:
    return AssignmentDraftCandidate(
        tenant_id="tenant-a", source_system="SMARTOFFICE_AI360", source_document_id="document-a",
        source_revision=revision, source_identity_key="source:document-a", initial_status="PENDING_OFFICE_REVIEW",
        task_title="task", task_description="description", lead_unit_source_key="unit-a",
        participating_unit_source_keys=(), required_roles=(), proposed_personnel=(), proposed_start_date=None,
        proposed_due_date=None, priority="NORMAL", deliverables=(), checklist_items=(), milestones=(), warnings=(),
        unresolved_items=(), overall_confidence=0, source_engine_versions=(), source_fingerprints=(),
        source_input_fingerprint=("a" if revision == "1" else "b") * 64,
        draft_content_fingerprint=("c" if revision == "1" else "d") * 64,
    )


def _draft_repository():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY)")
    init_domain_schema(conn)
    init_assignment_draft_schema(conn)
    return conn, AssignmentDraftRepository(conn)


def test_r3_09_exact_active_draft_version_is_projection_readable_after_supersession():
    """Scenario 9: the current active version is valid even when it supersedes history."""
    _conn, repo = _draft_repository()
    repo.save_draft_candidate(_stored_candidate("1"))
    current = repo.save_draft_candidate(_stored_candidate("2"))
    assert repo.get_draft_for_projection("tenant-a", "document-a", current.draft_version).id == current.id


def test_r3_10_11_12_exact_draft_query_rejects_other_or_inactive_versions():
    """Scenarios 10-12: no latest fallback; old inactive history is not projectable."""
    _conn, repo = _draft_repository()
    repo.save_draft_candidate(_stored_candidate("1"))
    current = repo.save_draft_candidate(_stored_candidate("2"))
    assert repo.get_draft_for_projection("tenant-a", "document-a", current.draft_version + 1) is None
    assert repo.get_draft_for_projection("tenant-a", "document-a", 1) is None


def test_r3_13_14_recommendation_query_is_tenant_document_scoped():
    repo = AssignmentRecommendationRepository(sqlite3.connect(":memory:"))
    repo.create_or_get(recommendation())
    assert repo.get_for_projection("tenant-a", "document-a").tenant_id == "tenant-a"
    assert repo.get_for_projection("tenant-b", "document-a") is None
    assert repo.get_for_projection("tenant-a", "document-b") is None


def test_r3_23_review_reasons_are_deduplicated_and_sorted():
    value = build_planner_draft_handoff_projection_v1(
        draft=draft(), recommendation=recommendation(manual_review_required=True, review_reasons=("z", "a", "z"))
    )
    assert value.review_reasons == ("a", "z") and value.manual_review_required


def test_r3_27_projection_has_no_transport_or_secret_fields():
    value = build_planner_draft_handoff_projection_v1(draft=draft(), recommendation=recommendation())
    forbidden = {"endpoint", "issuer", "secret", "headers", "correlation_id", "retry_state"}
    assert not (forbidden & set(value.__dataclass_fields__))


def test_r3_30_malformed_recommendation_json_is_rejected_safely():
    repo = AssignmentRecommendationRepository(sqlite3.connect(":memory:"))
    repo.conn.execute(
        "INSERT INTO assignment_recommendations VALUES (?,?,?,?,?,?,?)",
        ("id", "tenant-a", "document-a", "1.0.0", "{not-json", "hash", "now"),
    )
    with pytest.raises(AssignmentRecommendationProjectionError, match="MALFORMED_PERSISTED_DATA"):
        repo.get_for_projection("tenant-a", "document-a")


def test_r3_32_conflicting_recommendations_are_rejected_safely():
    repo = AssignmentRecommendationRepository(sqlite3.connect(":memory:"))
    repo.create_or_get(recommendation())
    repo.conn.execute(
        "INSERT INTO assignment_recommendations VALUES (?,?,?,?,?,?,?)",
        ("id-2", "tenant-a", "document-a", "2.0.0", repo._payload(recommendation())[0], "hash-2", "later"),
    )
    with pytest.raises(AssignmentRecommendationProjectionError, match="IRRECONCILABLE_SOURCE_CONFLICT"):
        repo.get_for_projection("tenant-a", "document-a")


def test_r3b_16_citation_order_is_deterministic_by_attachment_page_and_hash():
    """Scenario 16: transport-neutral projection must not retain input order."""
    first_citations = (
        {"id": "c2", "attachment_id": "b", "page_start": 2, "page_end": 2, "excerpt_sha256": "z"},
        {"id": "c1", "attachment_id": "a", "page_start": 1, "page_end": 1, "excerpt_sha256": "a"},
    )
    second_citations = tuple(reversed(first_citations))
    first = build_planner_draft_handoff_projection_v1(
        draft=draft(), recommendation=recommendation(), proposals=(proposal() | {"citations": first_citations},)
    )
    second = build_planner_draft_handoff_projection_v1(
        draft=draft(), recommendation=recommendation(), proposals=(proposal() | {"citations": second_citations},)
    )
    assert first == second


def test_r3b2_22_incomplete_assignment_provenance_requires_manual_review():
    """Scenario 22: absent persisted reason/rules must remain absent and be escalated."""
    value = build_planner_draft_handoff_projection_v1(
        draft=draft(),
        recommendation=recommendation(assignment_reason="", source_rules=(), manual_review_required=False),
    )
    assert value.assignment_reason == "" and value.source_rules == ()
    assert value.manual_review_required
    assert ASSIGNMENT_PROVENANCE_INCOMPLETE in value.warning_codes


@pytest.mark.parametrize("reason,rules,expected_reason,expected_rules,incomplete", [
    ("", (), "", (), True),
    ("   ", (), "", (), True),
    ("reason", (), "reason", (), True),
    ("", ("rule",), "", ("rule",), True),
    ("reason", (" rule-b ", "", "rule-a", "rule-b"), "reason", ("rule-a", "rule-b"), False),
])
def test_r3b2a_assignment_provenance_normalization(reason, rules, expected_reason, expected_rules, incomplete):
    value = build_planner_draft_handoff_projection_v1(
        draft=draft(), recommendation=recommendation(assignment_reason=reason, source_rules=rules, manual_review_required=False)
    )
    assert value.assignment_reason == expected_reason and value.source_rules == expected_rules
    assert value.manual_review_required is incomplete
    assert (ASSIGNMENT_PROVENANCE_INCOMPLETE in value.warning_codes) is incomplete


def test_r3b2a_persisted_manual_review_and_warning_deduplication_are_preserved():
    value = build_planner_draft_handoff_projection_v1(
        draft=draft(), recommendation=recommendation(assignment_reason="", source_rules=(), manual_review_required=True, review_reasons=("z", "a", "z"))
    )
    assert value.manual_review_required and value.review_reasons == ("a", "z")
    assert value.warning_codes.count(ASSIGNMENT_PROVENANCE_INCOMPLETE) == 1


def test_r3b2b1_05_real_g04_query_is_tenant_and_document_scoped():
    """Scenario 5: use the persisted G04 read model, not a pre-filtered list."""
    import test_g04_ai_proposal_boundary as g04

    _conn, _domain, _extraction, repository = g04._seed()
    g04._ingest(repository, g04._envelope(g04._proposal(external_proposal_id="in-scope")), "scope-key")
    in_scope = repository.list_validated_proposals_for_document("tenant-a", "doc-1")
    wrong_tenant = repository.list_validated_proposals_for_document("tenant-b", "doc-1")
    wrong_document = repository.list_validated_proposals_for_document("tenant-a", "missing-document")
    assert [item["external_proposal_id"] for item in in_scope] == ["in-scope"]
    assert in_scope[0]["action_id"] and in_scope[0]["citations"]
    assert wrong_tenant == [] and wrong_document == []
    projection = build_planner_draft_handoff_projection_v1(
        draft=draft(source_document_id="doc-1"),
        recommendation=recommendation(source_document_id="doc-1", source_proposal_ids=()), proposals=in_scope
    )
    assert projection.source_proposal_ids == ("in-scope",)


def _g04_query_and_projection_in_order(order):
    import test_g04_ai_proposal_boundary as g04

    _conn, _domain, _extraction, repository = g04._seed()
    g04._ingest(repository, g04._envelope(*(
        g04._proposal(external_proposal_id=value, title="title-" + value, description="description-" + value)
        for value in order
    )), "ordered-" + "-".join(order))
    values = repository.list_validated_proposals_for_document("tenant-a", "doc-1")
    projection = build_planner_draft_handoff_projection_v1(
        draft=draft(source_document_id="doc-1"),
        recommendation=recommendation(source_document_id="doc-1", source_proposal_ids=("proposal-z", "proposal-a", "proposal-z")),
        proposals=values,
    )
    return values, projection


def test_r3b2b1_06_15_17_g04_query_action_and_proposal_order_are_canonical():
    """Scenarios 6, 15, 17: real persisted records ignore fixture insertion order."""
    first_rows, first = _g04_query_and_projection_in_order(("proposal-b", "proposal-a"))
    second_rows, second = _g04_query_and_projection_in_order(("proposal-a", "proposal-b"))
    assert [row["external_proposal_id"] for row in first_rows] == ["proposal-a", "proposal-b"]
    assert [row["external_proposal_id"] for row in second_rows] == ["proposal-a", "proposal-b"]
    assert [row["external_proposal_id"] for row in first_rows] == [row["external_proposal_id"] for row in second_rows]
    assert [item["action_title"] for item in first.action_items] == [item["action_title"] for item in second.action_items]
    assert [item["proposal_item_id"] for item in first.action_items] == [row["proposal_item_id"] for row in first_rows]
    assert first.source_proposal_ids == ("proposal-a", "proposal-b", "proposal-z")


def test_r3b2b2_20_23_manual_review_and_reason_order_are_preserved():
    first = build_planner_draft_handoff_projection_v1(
        draft=draft(), recommendation=recommendation(manual_review_required=True, review_reasons=("z", "a", "z"))
    )
    second = build_planner_draft_handoff_projection_v1(
        draft=draft(), recommendation=recommendation(manual_review_required=True, review_reasons=("a", "z", "a"))
    )
    assert first.manual_review_required and second.manual_review_required
    assert first.review_reasons == second.review_reasons == ("a", "z")
    control = build_planner_draft_handoff_projection_v1(draft=draft(), recommendation=recommendation())
    assert not control.manual_review_required


def test_r3b2b2_26_builder_has_no_network_path(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("network path called")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    value = build_planner_draft_handoff_projection_v1(
        draft=draft(source_attachments=(object(),)), recommendation=recommendation()
    )
    assert value.attachments == () and SAFE_ATTACHMENT_URL_UNAVAILABLE in value.warning_codes


def test_r3b2b2_27_projection_has_no_transport_or_secret_fields():
    value = build_planner_draft_handoff_projection_v1(draft=draft(), recommendation=recommendation())
    prohibited = {"endpoint", "planner_url", "issuer", "secret", "headers", "authorization", "api_key", "correlation_id", "retry_state", "attempt_count", "next_retry_at", "cookie", "token", "session_url", "database_url", "http_status"}
    assert not (prohibited & {field.name.casefold() for field in fields(value)})
    for action in value.action_items:
        assert not (prohibited & {str(key).casefold() for key in action})
    assert value.source_document_id == "document-a" and value.source_system == SOURCE_SYSTEM


def test_r3b2b2_34_legacy_handoff_model_remains_separate():
    from tools.qlvb_downloader.assignment_draft_planner_handoff import PlannerDraftHandoff
    from tools.qlvb_downloader.planner_draft_handoff_v1_models import PlannerDraftHandoffProjectionV1
    assert PlannerDraftHandoff is not PlannerDraftHandoffProjectionV1
    assert "contract_version" not in PlannerDraftHandoff.__dataclass_fields__
