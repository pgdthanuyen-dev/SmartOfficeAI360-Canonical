from __future__ import annotations

from dataclasses import replace

import pytest

from tools.qlvb_downloader.assignment_draft_builder import AssignmentDraftBuilder, build_assignment_draft
from tools.qlvb_downloader.assignment_draft_models import AssignmentDraftBuildRequest
from tools.qlvb_downloader.assignment_draft_validation import AssignmentDraftValidationError
from tools.qlvb_downloader.assignment_rule_engine import AssignmentRecommendation, AssignmentRuleEvaluation, DocumentAssignmentSignals
from tools.qlvb_downloader.assignment_rule_models import MatchDecision, MatchWarningCode, RuleRoleType
from tools.qlvb_downloader.personnel_directory_models import PersonnelSelectionDecision
from tools.qlvb_downloader.personnel_selection_engine import PersonnelRoleRecommendation, PersonnelSelectionRecommendation


def _g05a(*, lead_unit: str | None = "UNIT-A", units: list[str] | None = None, confidence: float = 91, warnings=None, conflicts=None):
    return AssignmentRecommendation(
        document_id="DOC-1", document_revision="REV-1", input_fingerprint="a" * 64,
        evaluated_rule_count=1, eligible_rule_count=1, excluded_rule_count=0, primary_rule=None,
        alternative_rules=[], conflicting_rules=conflicts or [], decision=MatchDecision.MATCHED, confidence=confidence,
        lead_unit_key=lead_unit, coordinating_unit_keys=units or ["UNIT-B", "UNIT-C"],
        required_roles=[RuleRoleType.LEADER, RuleRoleType.MONITOR, RuleRoleType.LEAD_EXECUTOR],
        unresolved_fields=[], warnings=warnings or [], explanation="rule proposal", engine_version="g05a.engine.1", evaluated_at="",
    )


def _role(role, key, confidence=84, warnings=None, *, alternatives=None):
    return PersonnelRoleRecommendation(
        role_type=role, decision=PersonnelSelectionDecision.SELECTED_WITH_WARNING,
        selected_personnel_id=f"id-{key}" if key else None, selected_source_person_key=key,
        selected_personnel_ids=[f"id-{key}"] if key else [], alternative_candidates=alternatives or [],
        confidence=confidence, warnings=warnings or [], explanation="personnel proposal",
    )


def _g05b(*, roles=None, confidence=84, unresolved=None, conflicts=None, warnings=None):
    return PersonnelSelectionRecommendation(
        document_id="DOC-1", document_revision="REV-1", assignment_rule_match_id=None,
        unit_id="unit-id", unit_source_key="UNIT-A", role_recommendations=roles or [
            _role(RuleRoleType.LEADER, "P-LEADER"), _role(RuleRoleType.MONITOR, "P-MONITOR"),
            _role(RuleRoleType.LEAD_EXECUTOR, "P-EXECUTOR"),
        ], unresolved_roles=unresolved or [], conflicting_roles=conflicts or [], overall_confidence=confidence,
        warnings=warnings or [], explanation="personnel proposal", input_fingerprint="b" * 64,
        engine_version="g05b.selection.1", evaluated_at="",
    )


def _request(**changes):
    values = dict(
        tenant_id="tenant-a", source_system="qlvb", source_document_id="DOC-1", source_revision="REV-1",
        document_number="12/VP", subject="Handle the document", normalized_summary="A normalized summary.",
        received_date="2026-07-20", issued_date="2026-07-19", proposed_task_title="Prepare the response",
        proposed_task_description="Prepare one response draft.", proposed_start_date="2026-07-20",
        proposed_due_date="2026-07-25", proposed_priority="HIGH", proposed_deliverables=["Response draft"],
        proposed_checklist_items=["Review source"], proposed_milestones=["First review"],
        g05a_proposal=_g05a(), g05b_proposal=_g05b(), file_reference_placeholder="source-file-placeholder",
    )
    values.update(changes)
    return AssignmentDraftBuildRequest(**values)


def _codes(candidate):
    return [warning.code for warning in candidate.warnings]


def test_full_input_builds_one_pending_office_review_candidate():
    candidate = build_assignment_draft(_request())
    assert candidate.initial_status == "PENDING_OFFICE_REVIEW"
    assert candidate.task_title == "Prepare the response"
    assert candidate.builder_version == "g05c.builder.1"


def test_maps_g05a_units_and_g05b_selected_personnel_only():
    candidate = build_assignment_draft(_request(g05a_proposal=_g05a(units=["UNIT-C", "UNIT-B", "UNIT-B"])))
    assert candidate.lead_unit_source_key == "UNIT-A"
    assert candidate.participating_unit_source_keys == ("UNIT-B", "UNIT-C")
    assert [person.personnel_source_key for person in candidate.proposed_personnel] == ["P-LEADER", "P-MONITOR", "P-EXECUTOR"]


def test_missing_people_due_date_and_deliverables_are_non_blocking_warnings():
    candidate = build_assignment_draft(_request(
        g05b_proposal=_g05b(roles=[_role(RuleRoleType.LEADER, "P-LEADER")]), proposed_due_date=None,
        proposed_deliverables=[],
    ))
    assert {"MONITOR_REVIEW_REQUIRED", "LEAD_EXECUTOR_REVIEW_REQUIRED", "DUE_DATE_REVIEW_REQUIRED", "DELIVERABLE_REVIEW_REQUIRED"}.issubset(_codes(candidate))


def test_unit_and_personnel_conflicts_are_non_blocking():
    candidate = build_assignment_draft(_request(
        g05a_proposal=_g05a(lead_unit=None, warnings=[MatchWarningCode.UNIT_UNRESOLVED]),
        g05b_proposal=_g05b(conflicts=[RuleRoleType.LEAD_EXECUTOR]),
    ))
    assert "UNIT_REVIEW_REQUIRED" in _codes(candidate)
    assert "PERSONNEL_CONFLICT_REVIEW_REQUIRED" in _codes(candidate)


def test_substitute_only_is_a_suggestion_not_a_block():
    candidate = build_assignment_draft(_request(g05b_proposal=_g05b(roles=[
        _role(RuleRoleType.LEADER, "P-SUB", warnings=["SUBSTITUTE_USED"]),
        _role(RuleRoleType.MONITOR, "P-MONITOR"), _role(RuleRoleType.LEAD_EXECUTOR, "P-EXECUTOR"),
    ])))
    assert candidate.proposed_personnel[0].is_substitute is True
    assert "SUBSTITUTE_SUGGESTION" in _codes(candidate)


def test_alternatives_never_become_assigned_personnel():
    candidate = build_assignment_draft(_request(g05b_proposal=_g05b(roles=[
        _role(RuleRoleType.LEADER, "P-LEADER", alternatives=[object()]),
        _role(RuleRoleType.MONITOR, "P-MONITOR"), _role(RuleRoleType.LEAD_EXECUTOR, "P-EXECUTOR"),
    ])))
    assert len(candidate.proposed_personnel) == 3
    assert "P-LEADER" in [person.personnel_source_key for person in candidate.proposed_personnel]


def test_overall_confidence_is_minimum_component_value():
    candidate = build_assignment_draft(_request(g05a_proposal=_g05a(confidence=92), g05b_proposal=_g05b(confidence=61)))
    assert candidate.overall_confidence == 61
    assert "LOW_CONFIDENCE_REVIEW_REQUIRED" in _codes(candidate)


def test_priority_defaults_to_normal_and_invalid_due_date_is_soft_warning():
    candidate = build_assignment_draft(_request(proposed_priority=None, proposed_due_date="2026-07-18"))
    assert candidate.priority == "NORMAL"
    assert "INVALID_PROPOSED_DUE_DATE" in _codes(candidate)


@pytest.mark.parametrize("changes, code", [
    ({"source_revision": ""}, "MISSING_REQUIRED_FIELD"),
    ({"g05a_proposal": replace(_g05a(), input_fingerprint="not-a-hash")}, "INVALID_FINGERPRINT"),
    ({"proposed_task_description": "Authorization: Bearer secret"}, "SENSITIVE_DATA_NOT_ALLOWED"),
    ({"proposed_priority": "AUTO_APPROVED"}, "INVALID_PRIORITY"),
    ({"proposed_due_date": "20-07-2026"}, "INVALID_DATE"),
])
def test_hard_validation_rejects_invalid_input(changes, code):
    with pytest.raises(AssignmentDraftValidationError) as raised:
        build_assignment_draft(_request(**changes))
    assert raised.value.code == code


def test_cross_tenant_g05a_evaluation_is_rejected():
    recommendation = _g05a()
    evaluation = AssignmentRuleEvaluation(
        signals=DocumentAssignmentSignals("tenant-b", "DOC-1", "REV-1"), candidates=[], recommendation=recommendation,
    )
    with pytest.raises(AssignmentDraftValidationError, match="tenant"):
        build_assignment_draft(_request(g05a_proposal=evaluation))


def test_same_input_and_set_order_changes_have_stable_fingerprints():
    first = build_assignment_draft(_request())
    second = build_assignment_draft(_request(
        g05a_proposal=_g05a(units=["UNIT-C", "UNIT-B"]),
        g05b_proposal=_g05b(roles=[_role(RuleRoleType.LEAD_EXECUTOR, "P-EXECUTOR"), _role(RuleRoleType.MONITOR, "P-MONITOR"), _role(RuleRoleType.LEADER, "P-LEADER")]),
    ))
    assert first.source_input_fingerprint == second.source_input_fingerprint
    assert first.draft_content_fingerprint == second.draft_content_fingerprint


def test_task_title_and_revision_change_the_correct_fingerprints():
    original = build_assignment_draft(_request())
    changed_title = build_assignment_draft(_request(proposed_task_title="Prepare a different response"))
    changed_revision = build_assignment_draft(_request(
        source_revision="REV-2", g05a_proposal=replace(_g05a(), document_revision="REV-2"),
        g05b_proposal=replace(_g05b(), document_revision="REV-2"),
    ))
    assert original.draft_content_fingerprint != changed_title.draft_content_fingerprint
    assert original.source_input_fingerprint != changed_revision.source_input_fingerprint


def test_warnings_are_deduplicated_and_deterministically_ordered():
    candidate = build_assignment_draft(_request(g05a_proposal=_g05a(lead_unit=None, warnings=[MatchWarningCode.UNIT_UNRESOLVED])))
    keys = [(warning.code, warning.severity, warning.field_or_role, warning.message, warning.suggested_action) for warning in candidate.warnings]
    assert len(keys) == len(set(keys))
    assert keys == sorted(keys)


def test_no_external_identifiers_and_builder_has_no_database_or_network_dependencies(monkeypatch):
    import sqlite3
    import socket

    monkeypatch.setattr(sqlite3, "connect", lambda *args, **kwargs: pytest.fail("database called"))
    monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: pytest.fail("network called"))
    candidate = AssignmentDraftBuilder().build(_request())
    serialized = str(candidate).lower()
    assert "planner" not in serialized and "sharepoint" not in serialized


def test_multiple_deliverables_remain_one_candidate_without_auto_task_split():
    candidate = build_assignment_draft(_request(proposed_deliverables=["One", "Two", "Three"]))
    assert candidate.deliverables == ("One", "Two", "Three")
    assert candidate.source_document_id == "DOC-1"


def test_source_identity_mismatch_is_rejected():
    with pytest.raises(AssignmentDraftValidationError) as raised:
        build_assignment_draft(_request(g05a_proposal=replace(_g05a(), document_id="DOC-OTHER")))
    assert raised.value.code == "SOURCE_IDENTITY_MISMATCH"


def test_cross_tenant_g05b_context_is_rejected_when_present():
    proposal = _g05b()
    proposal.tenant_id = "tenant-b"
    with pytest.raises(AssignmentDraftValidationError) as raised:
        build_assignment_draft(_request(g05b_proposal=proposal))
    assert raised.value.code == "CROSS_TENANT_PROPOSAL"


def test_overlong_proposal_warning_list_is_rejected():
    with pytest.raises(AssignmentDraftValidationError) as raised:
        build_assignment_draft(_request(g05a_proposal=_g05a(warnings=["W"] * 17)))
    assert raised.value.code == "LIST_LIMIT_EXCEEDED"


def test_over_limit_business_list_is_rejected_without_truncation():
    with pytest.raises(AssignmentDraftValidationError) as raised:
        build_assignment_draft(_request(proposed_deliverables=["item"] * 21))
    assert raised.value.code == "LIST_LIMIT_EXCEEDED"


def test_missing_file_reference_is_a_non_blocking_warning():
    candidate = build_assignment_draft(_request(file_reference_placeholder=None))
    assert "FILE_REFERENCE_REVIEW_REQUIRED" in _codes(candidate)


def test_business_order_lists_are_preserved_in_the_candidate():
    candidate = build_assignment_draft(_request(
        proposed_deliverables=["Third", "First"], proposed_checklist_items=["B", "A"], proposed_milestones=["M2", "M1"],
    ))
    assert candidate.deliverables == ("Third", "First")
    assert candidate.checklist_items == ("B", "A")
    assert candidate.milestones == ("M2", "M1")


def test_co_executor_source_keys_map_deterministically_when_provided_by_g05b():
    co_executor = _role(RuleRoleType.CO_EXECUTOR, None)
    co_executor.selected_source_person_keys = ["P-CO-2", "P-CO-1"]
    candidate = build_assignment_draft(_request(g05a_proposal=replace(_g05a(), required_roles=[RuleRoleType.CO_EXECUTOR]), g05b_proposal=_g05b(roles=[co_executor])))
    assert [person.personnel_source_key for person in candidate.proposed_personnel] == ["P-CO-1", "P-CO-2"]


def test_invalid_source_system_format_is_rejected():
    with pytest.raises(AssignmentDraftValidationError) as raised:
        build_assignment_draft(_request(source_system="qlvb source"))
    assert raised.value.code == "INVALID_SOURCE_IDENTITY"


def test_unresolved_roles_are_exposed_without_auto_selection():
    candidate = build_assignment_draft(_request(g05b_proposal=_g05b(
        roles=[_role(RuleRoleType.LEADER, "P-LEADER")], unresolved=[RuleRoleType.MONITOR, RuleRoleType.LEAD_EXECUTOR],
    )))
    assert candidate.unresolved_items == ("MONITOR", "LEAD_EXECUTOR")
    assert {"P-MONITOR", "P-EXECUTOR"}.isdisjoint({person.personnel_source_key for person in candidate.proposed_personnel})


def test_warning_order_handles_empty_and_role_scopes_for_the_same_code():
    candidate = build_assignment_draft(_request(
        g05a_proposal=replace(_g05a(), required_roles=[RuleRoleType.CO_EXECUTOR]),
        g05b_proposal=_g05b(roles=[_role(RuleRoleType.CO_EXECUTOR, None)], conflicts=[RuleRoleType.CO_EXECUTOR]),
    ))
    warnings = [warning for warning in candidate.warnings if warning.code == "PERSONNEL_CONFLICT_REVIEW_REQUIRED"]
    assert [warning.field_or_role for warning in warnings] == [None, "CO_EXECUTOR"]
