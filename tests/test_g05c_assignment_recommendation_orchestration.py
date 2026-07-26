import json
import sqlite3
import threading

import pytest
from dataclasses import dataclass

from tools.qlvb_downloader.assignment_draft_models import AssignmentDraftCandidate
from tools.qlvb_downloader.assignment_draft_repository import AssignmentDraftRepository, init_assignment_draft_schema
from tools.qlvb_downloader.assignment_recommendation_service import (
    AssignmentOrchestrationRequest,
    AssignmentRecommendationService,
    AssignmentOrchestrationError,
)
from tools.qlvb_downloader.assignment_recommendation_repository import AssignmentRecommendationConflict
from tools.qlvb_downloader.assignment_rule_engine import DocumentAssignmentSignals
from tools.qlvb_downloader.domain_repository import init_domain_schema


@dataclass
class Rule:
    lead_unit_key: str | None = "unit-a"
    coordinating_unit_keys: list[str] = None
    confidence: float = 90
    conflicting_rules: list[object] = None
    primary_rule: object | None = None
    required_roles: list[str] = None
    explanation: str = "validated rule"

    def __post_init__(self):
        self.coordinating_unit_keys = self.coordinating_unit_keys or ["unit-a", "unit-b", "unit-b"]
        self.conflicting_rules = self.conflicting_rules or []
        self.required_roles = self.required_roles or []


@dataclass
class Personnel:
    overall_confidence: float = 90
    role_recommendations: tuple = ()
    conflicting_roles: tuple = ()
    unresolved_roles: tuple = ()


class Proposals:
    def __init__(self, values): self.values = values; self.calls = []
    def list_accepted_proposals_for_tenant_document(self, *, tenant_id, document_id):
        self.calls.append((tenant_id, document_id)); return list(self.values.get((tenant_id, document_id), []))


class RuleEngine:
    def __init__(self, rule): self.rule = rule
    def evaluate(self, signals, *, persist_matches=False): return type("Evaluation", (), {"recommendation": self.rule})()


class PersonnelEngine:
    def __init__(self, personnel): self.personnel = personnel
    def evaluate(self, request, *, persist_matches=False): return self.personnel


class Builder:
    def build(self, request):
        return AssignmentDraftCandidate(
            tenant_id=request.tenant_id, source_system=request.source_system,
            source_document_id=request.source_document_id, source_revision=request.source_revision,
            source_identity_key=f"{request.source_system}:{request.source_document_id}",
            initial_status="PENDING_OFFICE_REVIEW", task_title="Task", task_description="Description",
            lead_unit_source_key=getattr(request.g05a_proposal, "lead_unit_key", None),
            participating_unit_source_keys=("unit-b",), required_roles=(), proposed_personnel=(),
            proposed_start_date=None, proposed_due_date=None, priority="NORMAL", deliverables=(),
            checklist_items=(), milestones=(), warnings=(), unresolved_items=(), overall_confidence=90,
            source_engine_versions=(), source_fingerprints=(), source_input_fingerprint="a" * 64,
            draft_content_fingerprint="b" * 64,
        )


def make_service(proposals=None, rule=None, personnel=None, builder=None, draft_repository=None):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY)")
    init_domain_schema(conn); init_assignment_draft_schema(conn)
    return AssignmentRecommendationService(
        conn, proposal_repository=Proposals(proposals or {}), rule_engine=RuleEngine(rule or Rule()),
        personnel_engine=PersonnelEngine(personnel or Personnel()), draft_builder=builder or Builder(),
        draft_repository=draft_repository or AssignmentDraftRepository(conn),
    )


def request(tenant="tenant-a", document="doc-a", with_personnel=False):
    from tools.qlvb_downloader.assignment_draft_models import AssignmentDraftBuildRequest
    return AssignmentOrchestrationRequest(
        tenant_id=tenant, source_document_id=document, contract_version="1.0.0",
        signals=DocumentAssignmentSignals(tenant_id=tenant, document_id=document, document_revision="1"),
        draft_request=AssignmentDraftBuildRequest(tenant_id=tenant, source_system="canonical", source_document_id=document,
            source_revision="1", document_number=None, subject="Task", normalized_summary="Summary", received_date=None,
            issued_date=None, proposed_task_title="Task", proposed_task_description="Description", proposed_start_date=None,
            proposed_due_date=None, proposed_priority="NORMAL"),
        personnel_request_factory=(lambda rule: object()) if with_personnel else None,
    )


def rows():
    return [{"proposal_item_id": "p1", "action_item_id": "a1", "citation_count": 2, "citation_ids": "c1,c2"}, {"proposal_item_id": "p2", "action_item_id": "a2", "citation_count": 1, "citation_ids": "c3"}]


def payload(result): return json.loads(result.recommendation["payload_json"])


def test_multiple_g04_proposals_create_one_recommendation_and_draft():
    service = make_service({("tenant-a", "doc-a"): rows()}); result = service.orchestrate(request())
    assert result.created and len(payload(result)["source_proposal_ids"]) == 2
    assert service.connection.execute("SELECT count(*) FROM assignment_drafts").fetchone()[0] == 1


def test_action_items_and_citation_provenance_are_retained():
    result = make_service({("tenant-a", "doc-a"): rows()}).orchestrate(request()); value = payload(result)
    assert value["action_items"] == ["a1", "a2"] and value["provenance"]["citation_counts"] == {"p1": 2, "p2": 1} and value["provenance"]["citation_ids"]["p1"] == ["c1", "c2"]


def test_coordinating_units_are_deduplicated_and_exclude_lead():
    result = make_service({("tenant-a", "doc-a"): rows()}).orchestrate(request()); assert payload(result)["coordinating_units"] == ["unit-b"]


def test_primary_assignee_may_be_null():
    result = make_service({("tenant-a", "doc-a"): rows()}).orchestrate(request()); assert payload(result)["primary_assignee"] is None


def test_incomplete_provenance_requires_manual_review():
    result = make_service({("tenant-a", "doc-a"): [{"proposal_item_id": "p1", "action_item_id": "a1", "citation_count": 0}]}).orchestrate(request())
    assert "PROVENANCE_INCOMPLETE" in payload(result)["review_reasons"]


def test_no_match_requires_manual_review_without_invented_lead():
    result = make_service({}, rule=Rule(lead_unit_key=None)).orchestrate(request()); value = payload(result)
    assert value["manual_review_required"] and value["lead_unit"] is None


def test_low_confidence_and_tie_require_manual_review():
    result = make_service({("tenant-a", "doc-a"): rows()}, personnel=Personnel(overall_confidence=60, conflicting_roles=("LEADER",))).orchestrate(request(with_personnel=True))
    assert {"LOW_CONFIDENCE", "PERSONNEL_TIE"}.issubset(payload(result)["review_reasons"]) and payload(result)["primary_assignee"] is None


def test_rerun_returns_existing_recommendation_and_active_draft():
    service = make_service({("tenant-a", "doc-a"): rows()}); first = service.orchestrate(request()); second = service.orchestrate(request())
    assert not second.created and second.recommendation["id"] == first.recommendation["id"] and second.draft.id == first.draft.id


def test_tenant_and_document_are_isolated():
    service = make_service({("tenant-a", "doc-a"): rows(), ("tenant-b", "doc-a"): rows()})
    first = service.orchestrate(request()); second = service.orchestrate(request("tenant-b", "doc-a"))
    assert first.recommendation["id"] != second.recommendation["id"]


class FailingBuilder:
    def build(self, request): raise RuntimeError("untrusted upstream detail")


def test_recommendation_to_draft_failure_rolls_back_everything():
    service = make_service({("tenant-a", "doc-a"): rows()}, builder=FailingBuilder())
    with pytest.raises(AssignmentOrchestrationError, match="PERSISTENCE_FAILED"):
        service.orchestrate(request())
    assert service.connection.execute("SELECT count(*) FROM assignment_recommendations").fetchone()[0] == 0
    assert service.connection.execute("SELECT count(*) FROM assignment_drafts WHERE is_active=1").fetchone()[0] == 0


def test_rerun_after_rollback_creates_one_recommendation_and_draft():
    service = make_service({("tenant-a", "doc-a"): rows()}, builder=FailingBuilder())
    with pytest.raises(AssignmentOrchestrationError): service.orchestrate(request())
    service.draft_builder = Builder(); result = service.orchestrate(request())
    assert result.created and service.connection.execute("SELECT count(*) FROM assignment_recommendations").fetchone()[0] == 1


def test_draft_persistence_failure_rolls_back_recommendation_and_active_draft():
    class FailAfterDraftWrite(AssignmentDraftRepository):
        def save_draft_candidate(self, candidate, *, manage_transaction=True):
            super().save_draft_candidate(candidate, manage_transaction=manage_transaction)
            raise RuntimeError("persistence failure after write")
    service = make_service({("tenant-a", "doc-a"): rows()})
    service.draft_repository = FailAfterDraftWrite(service.connection)
    with pytest.raises(AssignmentOrchestrationError, match="PERSISTENCE_FAILED"):
        service.orchestrate(request())
    assert service.connection.execute("SELECT count(*) FROM assignment_recommendations").fetchone()[0] == 0
    assert service.connection.execute("SELECT count(*) FROM assignment_drafts WHERE is_active=1").fetchone()[0] == 0


def test_cross_tenant_or_document_row_is_rejected_before_persistence():
    wrong = [{"proposal_item_id": "p", "action_item_id": "a", "tenant_id": "tenant-b", "document_id": "doc-a", "citation_count": 1}]
    service = make_service({("tenant-a", "doc-a"): wrong})
    with pytest.raises(AssignmentOrchestrationError, match="G04_TENANT_DOCUMENT_MISMATCH"):
        service.orchestrate(request())
    assert service.connection.execute("SELECT count(*) FROM assignment_recommendations").fetchone()[0] == 0


def test_g05a_failure_leaves_no_partial_state_and_redacts_error():
    class BrokenRuleEngine:
        def evaluate(self, *args, **kwargs): raise RuntimeError("untrusted upstream detail")
    service = make_service({("tenant-a", "doc-a"): rows()}); service.rule_engine = BrokenRuleEngine()
    with pytest.raises(AssignmentOrchestrationError) as error: service.orchestrate(request())
    assert str(error.value) == "G05A_RULE_EVALUATION_FAILED" and "detail" not in str(error.value)
    assert service.connection.execute("SELECT count(*) FROM assignment_recommendations").fetchone()[0] == 0


def test_g05b_failure_leaves_no_partial_state_and_redacts_error():
    class BrokenPersonnelEngine:
        def evaluate(self, *args, **kwargs): raise RuntimeError("untrusted upstream detail")
    service = make_service({("tenant-a", "doc-a"): rows()}); service.personnel_engine = BrokenPersonnelEngine()
    with pytest.raises(AssignmentOrchestrationError) as error: service.orchestrate(request(with_personnel=True))
    assert str(error.value) == "G05B_PERSONNEL_SELECTION_FAILED" and "detail" not in str(error.value)
    assert service.connection.execute("SELECT count(*) FROM assignment_recommendations").fetchone()[0] == 0


def test_conflicting_payload_same_idempotency_key_is_not_overwritten():
    service = make_service({("tenant-a", "doc-a"): rows()}); first = service.orchestrate(request())
    service.rule_engine.rule.explanation = "different payload"
    with pytest.raises(AssignmentRecommendationConflict): service.orchestrate(request())
    assert service.recommendation_repository.get_by_idempotency_key("tenant-a", "doc-a", "1.0.0")["id"] == first.recommendation["id"]


def test_concurrent_same_key_uses_one_recommendation_and_one_active_draft(tmp_path):
    database = tmp_path / "orchestration.sqlite"; setup = sqlite3.connect(database)
    setup.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY)"); init_domain_schema(setup); init_assignment_draft_schema(setup); setup.close()
    barrier = threading.Barrier(2); results = []; errors = []
    def worker():
        conn = sqlite3.connect(database, timeout=2)
        try:
            service = AssignmentRecommendationService(conn, proposal_repository=Proposals({("tenant-a", "doc-a"): rows()}), rule_engine=RuleEngine(Rule()), personnel_engine=PersonnelEngine(Personnel()), draft_builder=Builder(), draft_repository=AssignmentDraftRepository(conn))
            barrier.wait(); results.append(service.orchestrate(request()))
        except Exception as exc: errors.append(exc)
        finally: conn.close()
    threads = [threading.Thread(target=worker) for _ in range(2)]
    [thread.start() for thread in threads]; [thread.join() for thread in threads]
    check = sqlite3.connect(database)
    assert not errors and len(results) == 2
    assert check.execute("SELECT count(*) FROM assignment_recommendations").fetchone()[0] == 1
    assert check.execute("SELECT count(*) FROM assignment_drafts WHERE is_active=1").fetchone()[0] == 1


def test_concurrent_conflicting_payload_reports_conflict_without_overwrite(tmp_path):
    database = tmp_path / "conflict.sqlite"; setup = sqlite3.connect(database)
    setup.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY)"); init_domain_schema(setup); init_assignment_draft_schema(setup); setup.close()
    barrier = threading.Barrier(2); outcomes = []
    def worker(explanation):
        conn = sqlite3.connect(database, timeout=2)
        try:
            service = AssignmentRecommendationService(conn, proposal_repository=Proposals({("tenant-a", "doc-a"): rows()}), rule_engine=RuleEngine(Rule(explanation=explanation)), personnel_engine=PersonnelEngine(Personnel()), draft_builder=Builder(), draft_repository=AssignmentDraftRepository(conn))
            barrier.wait()
            try: service.orchestrate(request()); outcomes.append("SUCCESS")
            except AssignmentRecommendationConflict: outcomes.append("CONFLICT")
        finally: conn.close()
    threads = [threading.Thread(target=worker, args=(value,)) for value in ("first", "second")]
    [thread.start() for thread in threads]; [thread.join() for thread in threads]
    check = sqlite3.connect(database)
    assert sorted(outcomes) == ["CONFLICT", "SUCCESS"]
    assert check.execute("SELECT count(*) FROM assignment_recommendations").fetchone()[0] == 1
    assert check.execute("SELECT count(*) FROM assignment_drafts WHERE is_active=1").fetchone()[0] == 1
