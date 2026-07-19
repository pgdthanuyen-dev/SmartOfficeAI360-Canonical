from __future__ import annotations

import sqlite3

import pytest

from tools.qlvb_downloader.assignment_rule_engine import (
    ASSIGNMENT_RULE_ENGINE_VERSION,
    TOP_RULE_CONFLICT_DELTA,
    AssignmentRuleEngine,
    DocumentAssignmentSignals,
    evaluate_assignment_rules,
    normalize_assignment_signal,
)
from tools.qlvb_downloader.assignment_rule_models import (
    AssignmentRule,
    AssignmentRuleCondition,
    AssignmentRuleExclusion,
    AssignmentRuleRole,
    AssignmentRuleUnit,
    ConditionType,
    ExclusionType,
    MatchDecision,
    MatchMode,
    MatchWarningCode,
    RuleRoleType,
    RuleStatus,
    RuleUnitType,
)
from tools.qlvb_downloader.assignment_rule_repository import AssignmentRuleRepository
from tools.qlvb_downloader.assignment_rule_validation import AssignmentRuleValidationError
from tools.qlvb_downloader.domain_models import Document
from tools.qlvb_downloader.domain_repository import DomainRepository


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY, title TEXT)")
    return conn


def _seed():
    conn = _connect()
    DomainRepository(conn).save_document(
        Document(id="doc-1", tenant_id="tenant-a", source_system="QLVB", source_document_id="qlvb-1")
    )
    return conn, AssignmentRuleRepository(conn)


def _signals(**overrides):
    payload = {
        "tenant_id": "tenant-a",
        "document_id": "doc-1",
        "document_revision": "1",
        "document_type": "INCOMING",
        "issuer_name": "So Thong tin",
        "issuer_group": "so thong tin",
        "domain_codes": ["chuyen doi so"],
        "subdomain_codes": ["bao cao"],
        "required_actions": ["bao cao"],
        "keywords": ["chuyen doi so", "phu luc"],
        "target_entities": ["ubnd tinh"],
        "expected_outputs": ["bao cao"],
        "title": "Bao cao chuyen doi so",
        "summary": "Tom tat ngan gon ve bao cao chuyen doi so va phu luc.",
        "reference_date": "2026-07-19",
    }
    payload.update(overrides)
    return DocumentAssignmentSignals(**payload)


def _rule(rule_id="rule-1", code="R-001", priority=10, status=RuleStatus.ACTIVE, minimum_confidence=0, **overrides):
    payload = {
        "id": rule_id,
        "tenant_id": "tenant-a",
        "rule_code": code,
        "version": "1",
        "rule_name": code,
        "domain_code": "chuyen doi so",
        "priority": priority,
        "minimum_confidence": minimum_confidence,
        "effective_from": "2026-01-01",
        "effective_to": "2026-12-31",
        "status": status,
    }
    payload.update(overrides)
    return AssignmentRule(**payload)


def _condition(rule_id="rule-1", cid=None, ctype=ConditionType.REQUIRED_KEYWORD, value="bao cao", weight=100, required=False, mode=MatchMode.CONTAINS):
    return AssignmentRuleCondition(
        id=cid or "",
        rule_id=rule_id,
        condition_type=ctype,
        value=value,
        weight=weight,
        is_required=required,
        match_mode=mode,
    )


def _exclusion(rule_id="rule-1", eid="excl-1", value="du toan", hard=True, penalty=10, etype=ExclusionType.EXCLUDED_KEYWORD):
    return AssignmentRuleExclusion(
        id=eid,
        rule_id=rule_id,
        exclusion_type=etype,
        value=value,
        penalty=penalty,
        is_hard_exclusion=hard,
    )


def _unit(rule_id="rule-1", uid=None, key="VP", unit_type=RuleUnitType.LEAD_UNIT, priority=1, effective_from=None, effective_to=None):
    return AssignmentRuleUnit(
        id=uid or "",
        rule_id=rule_id,
        unit_type=unit_type,
        source_unit_key=key,
        unit_name=key,
        priority=priority,
        effective_from=effective_from,
        effective_to=effective_to,
    )


def _role(rule_id="rule-1", rid=None, role_type=RuleRoleType.LEADER, required=True, effective_from=None, effective_to=None):
    return AssignmentRuleRole(
        id=rid or "",
        rule_id=rule_id,
        role_type=role_type,
        role_code=role_type.value,
        unit_source_key="VP",
        is_required=required,
        priority=1,
        effective_from=effective_from,
        effective_to=effective_to,
    )


def _create_rule(repo, rule=None, conditions=None, exclusions=None, units=None, roles=None):
    rule = rule or _rule()
    repo.create_rule(
        rule,
        conditions=conditions if conditions is not None else [_condition(rule.id, ctype=ConditionType.DOMAIN, value="chuyen doi so", weight=100)],
        exclusions=exclusions or [],
        units=units if units is not None else [_unit(rule.id)],
        roles=roles if roles is not None else [_role(rule.id)],
    )
    return rule


def test_normalization_vietnamese_is_deterministic():
    first = normalize_assignment_signal("  Báo   cáo\r\nChuyển đổi số\u0000 ")
    second = normalize_assignment_signal("Báo cáo Chuyển đổi số")
    assert first == second == "báo cáo chuyển đổi số"


def test_exact_match():
    conn, repo = _seed()
    try:
        _create_rule(repo, conditions=[_condition(ctype=ConditionType.DOCUMENT_TYPE, value="incoming", mode=MatchMode.EXACT)])
        result = AssignmentRuleEngine(repo).evaluate(_signals())
        assert result.recommendation.primary_rule.decision == MatchDecision.MATCHED
    finally:
        conn.close()


def test_contains_match():
    conn, repo = _seed()
    try:
        _create_rule(repo, conditions=[_condition(value="chuyen doi", mode=MatchMode.CONTAINS)])
        assert AssignmentRuleEngine(repo).evaluate(_signals()).recommendation.primary_rule.score == 100
    finally:
        conn.close()


def test_token_match_does_not_match_partial_word():
    conn, repo = _seed()
    try:
        _create_rule(repo, conditions=[_condition(ctype=ConditionType.TARGET_ENTITY, value="bao", mode=MatchMode.TOKEN)])
        result = AssignmentRuleEngine(repo).evaluate(_signals(keywords=["baocao"]))
        assert result.recommendation.primary_rule is None
        assert result.recommendation.decision == MatchDecision.NO_MATCH
    finally:
        conn.close()


def test_prefix_match():
    conn, repo = _seed()
    try:
        _create_rule(repo, conditions=[_condition(ctype=ConditionType.ISSUER_GROUP, value="so", mode=MatchMode.PREFIX)])
        assert AssignmentRuleEngine(repo).evaluate(_signals()).recommendation.primary_rule.score == 100
    finally:
        conn.close()


def test_regex_safe_match():
    conn, repo = _seed()
    try:
        _create_rule(repo, conditions=[_condition(value=r"bao\s+cao", mode=MatchMode.REGEX_SAFE)])
        assert AssignmentRuleEngine(repo).evaluate(_signals()).recommendation.primary_rule.score == 100
    finally:
        conn.close()


def test_invalid_regex_is_rejected():
    conn, repo = _seed()
    try:
        with pytest.raises(AssignmentRuleValidationError):
            _create_rule(repo, conditions=[_condition(value="[", mode=MatchMode.REGEX_SAFE)])
    finally:
        conn.close()


def test_draft_rule_not_used():
    conn, repo = _seed()
    try:
        _create_rule(repo, _rule(status=RuleStatus.DRAFT))
        assert AssignmentRuleEngine(repo).evaluate(_signals()).recommendation.evaluated_rule_count == 0
    finally:
        conn.close()


def test_inactive_rule_not_used():
    conn, repo = _seed()
    try:
        _create_rule(repo, _rule(status=RuleStatus.INACTIVE))
        assert AssignmentRuleEngine(repo).evaluate(_signals()).recommendation.evaluated_rule_count == 0
    finally:
        conn.close()


def test_future_rule_not_used():
    conn, repo = _seed()
    try:
        _create_rule(repo, _rule(effective_from="2027-01-01", effective_to="2027-12-31"))
        assert AssignmentRuleEngine(repo).evaluate(_signals()).recommendation.evaluated_rule_count == 0
    finally:
        conn.close()


def test_expired_rule_not_used():
    conn, repo = _seed()
    try:
        _create_rule(repo, _rule(effective_to="2026-01-01"))
        assert AssignmentRuleEngine(repo).evaluate(_signals()).recommendation.evaluated_rule_count == 0
    finally:
        conn.close()


def test_tenant_isolation():
    conn, repo = _seed()
    try:
        _create_rule(repo, _rule(tenant_id="tenant-b"))
        assert AssignmentRuleEngine(repo).evaluate(_signals()).recommendation.evaluated_rule_count == 0
    finally:
        conn.close()


def test_required_keyword_matched():
    conn, repo = _seed()
    try:
        _create_rule(repo, conditions=[_condition(required=True, value="bao cao")])
        assert AssignmentRuleEngine(repo).evaluate(_signals()).recommendation.primary_rule.decision == MatchDecision.MATCHED
    finally:
        conn.close()


def test_required_keyword_missing():
    conn, repo = _seed()
    try:
        _create_rule(repo, conditions=[_condition(required=True, value="khong co", weight=100)])
        evaluation = AssignmentRuleEngine(repo).evaluate(_signals())
        candidate = evaluation.candidates[0]
        assert candidate.decision == MatchDecision.NO_MATCH
        assert evaluation.recommendation.primary_rule is None
        assert MatchWarningCode.MISSING_REQUIRED_SIGNAL in candidate.warnings
    finally:
        conn.close()


def test_preferred_keyword_increases_score():
    conn, repo = _seed()
    try:
        conditions = [
            _condition(cid="c1", value="bao cao", weight=50),
            _condition(cid="c2", ctype=ConditionType.PREFERRED_KEYWORD, value="phu luc", weight=50),
        ]
        _create_rule(repo, conditions=conditions)
        assert AssignmentRuleEngine(repo).evaluate(_signals()).recommendation.primary_rule.score == 100
    finally:
        conn.close()


def test_hard_exclusion_excludes_rule():
    conn, repo = _seed()
    try:
        _create_rule(repo, exclusions=[_exclusion(value="du toan", hard=True)])
        candidate = AssignmentRuleEngine(repo).evaluate(_signals(keywords=["du toan"])).candidates[0]
        assert candidate.decision == MatchDecision.EXCLUDED
        assert candidate.score == 0
    finally:
        conn.close()


def test_soft_exclusion_subtracts_score():
    conn, repo = _seed()
    try:
        _create_rule(repo, exclusions=[_exclusion(value="phu luc", hard=False, penalty=20)])
        candidate = AssignmentRuleEngine(repo).evaluate(_signals()).recommendation.primary_rule
        assert candidate.score == 80
        assert candidate.soft_penalty_total == 20
    finally:
        conn.close()


def test_score_clamped_to_zero():
    conn, repo = _seed()
    try:
        _create_rule(repo, exclusions=[_exclusion(value="phu luc", hard=False, penalty=200)])
        evaluation = AssignmentRuleEngine(repo).evaluate(_signals())
        assert evaluation.candidates[0].score == 0
        assert evaluation.recommendation.primary_rule is None
    finally:
        conn.close()


def test_minimum_confidence_applied():
    conn, repo = _seed()
    try:
        conditions = [_condition(cid="c1", value="bao cao", weight=80), _condition(cid="c2", value="missing", weight=20)]
        _create_rule(repo, _rule(minimum_confidence=90), conditions=conditions)
        candidate = AssignmentRuleEngine(repo).evaluate(_signals()).recommendation.primary_rule
        assert candidate.decision == MatchDecision.NEEDS_CLASSIFICATION
        assert MatchWarningCode.LOW_CONFIDENCE in candidate.warnings
    finally:
        conn.close()


def test_score_90_creates_matched():
    conn, repo = _seed()
    try:
        _create_rule(repo)
        assert AssignmentRuleEngine(repo).evaluate(_signals()).recommendation.primary_rule.decision == MatchDecision.MATCHED
    finally:
        conn.close()


def test_score_75_to_89_creates_matched_with_warning():
    conn, repo = _seed()
    try:
        conditions = [_condition(cid="c1", value="bao cao", weight=80), _condition(cid="c2", value="missing", weight=20)]
        _create_rule(repo, conditions=conditions)
        assert AssignmentRuleEngine(repo).evaluate(_signals()).recommendation.primary_rule.decision == MatchDecision.MATCHED_WITH_WARNING
    finally:
        conn.close()


def test_score_below_75_creates_no_match():
    conn, repo = _seed()
    try:
        conditions = [_condition(cid="c1", value="bao cao", weight=50), _condition(cid="c2", value="missing", weight=50)]
        _create_rule(repo, conditions=conditions)
        evaluation = AssignmentRuleEngine(repo).evaluate(_signals())
        assert evaluation.candidates[0].decision == MatchDecision.NO_MATCH
        assert evaluation.recommendation.primary_rule is None
        assert evaluation.recommendation.decision == MatchDecision.NO_MATCH
    finally:
        conn.close()


def test_missing_required_high_score_needs_classification():
    conn, repo = _seed()
    try:
        conditions = [
            _condition(cid="c1", value="missing", weight=10, required=True),
            _condition(cid="c2", value="bao cao", weight=90),
        ]
        _create_rule(repo, conditions=conditions)
        assert AssignmentRuleEngine(repo).evaluate(_signals()).recommendation.primary_rule.decision == MatchDecision.NEEDS_CLASSIFICATION
    finally:
        conn.close()


def test_top_rule_conflict_with_different_unit():
    conn, repo = _seed()
    try:
        _create_rule(repo, _rule("rule-1", "R-001"), units=[_unit("rule-1", key="VP")])
        _create_rule(repo, _rule("rule-2", "R-002"), conditions=[_condition("rule-2", value="bao cao", weight=97)], units=[_unit("rule-2", "unit-2", key="CNTT")])
        rec = AssignmentRuleEngine(repo).evaluate(_signals()).recommendation
        assert TOP_RULE_CONFLICT_DELTA == 3.0
        assert rec.decision == MatchDecision.NEEDS_CLASSIFICATION
        assert MatchWarningCode.CONFLICTING_RULES in rec.warnings
        assert rec.lead_unit_key is None
    finally:
        conn.close()


def test_priority_breaks_tie_when_no_conflict():
    conn, repo = _seed()
    try:
        _create_rule(repo, _rule("rule-low", "R-LOW", priority=1), units=[_unit("rule-low", key="VP")])
        _create_rule(repo, _rule("rule-high", "R-HIGH", priority=9), units=[_unit("rule-high", "unit-high", key="VP")])
        assert AssignmentRuleEngine(repo).evaluate(_signals()).recommendation.primary_rule.rule_code == "R-HIGH"
    finally:
        conn.close()


def test_single_lead_unit_returned():
    conn, repo = _seed()
    try:
        _create_rule(repo, units=[_unit(key="VP")])
        assert AssignmentRuleEngine(repo).evaluate(_signals()).recommendation.lead_unit_key == "VP"
    finally:
        conn.close()


def test_multiple_equal_lead_units_unresolved():
    conn, repo = _seed()
    try:
        _create_rule(repo, units=[_unit(key="VP")])
        repo.add_unit(_unit(uid="unit-2", key="CNTT"))
        rec = AssignmentRuleEngine(repo).evaluate(_signals()).recommendation
        assert MatchWarningCode.UNIT_UNRESOLVED in rec.warnings
        assert rec.lead_unit_key is None
    finally:
        conn.close()


def test_roles_returned():
    conn, repo = _seed()
    try:
        roles = [
            _role(role_type=RuleRoleType.LEADER),
            _role(rid="role-monitor", role_type=RuleRoleType.MONITOR),
            _role(rid="role-executor", role_type=RuleRoleType.LEAD_EXECUTOR),
        ]
        _create_rule(repo, roles=roles)
        roles_out = AssignmentRuleEngine(repo).evaluate(_signals()).recommendation.required_roles
        assert roles_out == ["LEADER", "MONITOR", "LEAD_EXECUTOR"]
    finally:
        conn.close()


def test_missing_required_role_unresolved():
    conn, repo = _seed()
    try:
        _create_rule(repo, roles=[_role(effective_from="2027-01-01")])
        rec = AssignmentRuleEngine(repo).evaluate(_signals()).recommendation
        assert MatchWarningCode.ROLE_UNRESOLVED in rec.warnings
        assert rec.decision == MatchDecision.NEEDS_CLASSIFICATION
    finally:
        conn.close()


def test_hard_exclusion_has_explanation():
    conn, repo = _seed()
    try:
        _create_rule(repo, exclusions=[_exclusion(value="du toan", hard=True)])
        candidate = AssignmentRuleEngine(repo).evaluate(_signals(keywords=["du toan"])).candidates[0]
        assert "hard exclusion" in candidate.explanation
    finally:
        conn.close()


def test_only_hard_excluded_rule_has_no_primary_assignment():
    conn, repo = _seed()
    try:
        _create_rule(repo, exclusions=[_exclusion(value="du toan", hard=True)])
        rec = AssignmentRuleEngine(repo).evaluate(_signals(keywords=["du toan"])).recommendation
        assert rec.primary_rule is None
        assert rec.decision == MatchDecision.EXCLUDED
        assert rec.confidence == 0
        assert rec.lead_unit_key is None
        assert rec.coordinating_unit_keys == []
        assert rec.required_roles == []
    finally:
        conn.close()


def test_excluded_high_priority_rule_cannot_beat_lower_valid_rule():
    conn, repo = _seed()
    try:
        _create_rule(
            repo,
            _rule("excluded-rule", "EXCLUDED-HIGH", priority=100),
            exclusions=[_exclusion("excluded-rule", value="du toan", hard=True)],
            units=[_unit("excluded-rule", key="TC")],
            roles=[_role("excluded-rule")],
        )
        _create_rule(
            repo,
            _rule("valid-rule", "VALID-LOW", priority=1),
            conditions=[
                _condition("valid-rule", cid="valid-c1", value="bao cao", weight=80),
                _condition("valid-rule", cid="valid-c2", value="missing", weight=20),
            ],
            units=[_unit("valid-rule", key="VP")],
            roles=[_role("valid-rule")],
        )
        rec = AssignmentRuleEngine(repo).evaluate(_signals(keywords=["du toan"])).recommendation
        assert rec.primary_rule.rule_code == "VALID-LOW"
        assert rec.lead_unit_key == "VP"
    finally:
        conn.close()


def test_all_no_match_rules_have_no_primary_assignment():
    conn, repo = _seed()
    try:
        _create_rule(repo, conditions=[_condition(value="khong khop", weight=100)])
        rec = AssignmentRuleEngine(repo).evaluate(_signals()).recommendation
        assert rec.primary_rule is None
        assert rec.decision == MatchDecision.NO_MATCH
        assert rec.lead_unit_key is None
        assert rec.coordinating_unit_keys == []
        assert rec.required_roles == []
    finally:
        conn.close()


def test_mixed_excluded_and_no_match_rules_have_no_primary_assignment():
    conn, repo = _seed()
    try:
        _create_rule(
            repo,
            _rule("excluded-rule", "EXCLUDED"),
            exclusions=[_exclusion("excluded-rule", value="du toan", hard=True)],
            units=[_unit("excluded-rule", key="TC")],
            roles=[_role("excluded-rule")],
        )
        _create_rule(
            repo,
            _rule("no-match-rule", "NO-MATCH"),
            conditions=[_condition("no-match-rule", value="khong khop", weight=100)],
            units=[_unit("no-match-rule", key="VP")],
            roles=[_role("no-match-rule")],
        )
        rec = AssignmentRuleEngine(repo).evaluate(_signals(keywords=["du toan"])).recommendation
        assert rec.primary_rule is None
        assert rec.decision == MatchDecision.NO_MATCH
        assert rec.lead_unit_key is None
        assert rec.required_roles == []
    finally:
        conn.close()


def test_excluded_rule_does_not_participate_in_top_rule_conflict():
    conn, repo = _seed()
    try:
        _create_rule(repo, _rule("valid-rule", "VALID"), units=[_unit("valid-rule", key="VP")])
        _create_rule(
            repo,
            _rule("excluded-rule", "EXCLUDED", priority=100),
            exclusions=[_exclusion("excluded-rule", value="du toan", hard=True)],
            units=[_unit("excluded-rule", key="TC")],
            roles=[_role("excluded-rule")],
        )
        rec = AssignmentRuleEngine(repo).evaluate(_signals(keywords=["du toan"])).recommendation
        assert rec.primary_rule.rule_code == "VALID"
        assert rec.conflicting_rules == []
        assert rec.decision == MatchDecision.MATCHED
        assert rec.lead_unit_key == "VP"
    finally:
        conn.close()


def test_excluded_candidate_is_retained_in_match_history():
    conn, repo = _seed()
    try:
        _create_rule(repo, exclusions=[_exclusion(value="du toan", hard=True)])
        AssignmentRuleEngine(repo).evaluate(_signals(keywords=["du toan"]), persist_matches=True)
        matches = repo.list_matches_for_document("doc-1")
        assert len(matches) == 1
        assert matches[0]["decision"] == MatchDecision.EXCLUDED.value
    finally:
        conn.close()


def test_excluded_fallback_result_is_deterministic():
    conn, repo = _seed()
    try:
        _create_rule(repo, exclusions=[_exclusion(value="du toan", hard=True)])
        engine = AssignmentRuleEngine(repo)
        first = engine.evaluate(_signals(keywords=["du toan"])).recommendation
        second = engine.evaluate(_signals(keywords=["du toan"])).recommendation
        assert first.input_fingerprint == second.input_fingerprint
        assert first.primary_rule is second.primary_rule is None
        assert first.decision == second.decision
        assert first.explanation == second.explanation
    finally:
        conn.close()


def test_explanation_does_not_contain_full_summary():
    conn, repo = _seed()
    try:
        _create_rule(repo)
        summary = "noi dung rat dai " * 50
        explanation = AssignmentRuleEngine(repo).evaluate(_signals(summary=summary)).recommendation.explanation
        assert summary not in explanation
    finally:
        conn.close()


def test_fingerprint_stable():
    assert _signals().input_fingerprint() == _signals().input_fingerprint()


def test_different_input_changes_fingerprint():
    assert _signals().input_fingerprint() != _signals(keywords=["khac"]).input_fingerprint()


def test_repeated_result_is_deterministic():
    conn, repo = _seed()
    try:
        _create_rule(repo)
        first = AssignmentRuleEngine(repo).evaluate(_signals()).recommendation
        second = AssignmentRuleEngine(repo).evaluate(_signals()).recommendation
        assert first.input_fingerprint == second.input_fingerprint
        assert first.primary_rule.rule_id == second.primary_rule.rule_id
        assert first.decision == second.decision
    finally:
        conn.close()


def test_persist_matches_append_only():
    conn, repo = _seed()
    try:
        _create_rule(repo)
        engine = AssignmentRuleEngine(repo)
        engine.evaluate(_signals(), persist_matches=True)
        engine.evaluate(_signals(), persist_matches=True)
        assert len(repo.list_matches_for_document("doc-1")) == 2
    finally:
        conn.close()


def test_match_history_does_not_store_full_text():
    conn, repo = _seed()
    try:
        _create_rule(repo)
        summary = "full document text " * 100
        AssignmentRuleEngine(repo).evaluate(_signals(summary=summary), persist_matches=True)
        row = repo.list_matches_for_document("doc-1")[0]
        assert summary not in (row["explanation"] or "")
    finally:
        conn.close()


def test_bad_rule_does_not_break_other_rules():
    conn, repo = _seed()
    try:
        _create_rule(repo, _rule("bad-rule", "BAD"), conditions=[_condition("bad-rule", value="khong khop", mode=MatchMode.REGEX_SAFE)])
        conn.execute("UPDATE assignment_rule_conditions SET normalized_value = '[' WHERE rule_id = 'bad-rule'")
        _create_rule(repo, _rule("good-rule", "GOOD"), units=[_unit("good-rule", key="VP")])
        rec = AssignmentRuleEngine(repo).evaluate(_signals()).recommendation
        assert rec.primary_rule.rule_code == "GOOD"
    finally:
        conn.close()


def test_no_specific_people_created():
    conn, repo = _seed()
    try:
        _create_rule(repo)
        rec = AssignmentRuleEngine(repo).evaluate(_signals()).recommendation
        assert not hasattr(rec, "person_id")
        assert not hasattr(rec, "planner_user_id")
    finally:
        conn.close()


def test_no_action_item_created():
    conn, repo = _seed()
    try:
        _create_rule(repo)
        AssignmentRuleEngine(repo).evaluate(_signals(), persist_matches=True)
        count = conn.execute("SELECT COUNT(*) AS n FROM action_items").fetchone()["n"]
        assert count == 0
    finally:
        conn.close()


def test_no_external_calls_are_needed():
    conn, repo = _seed()
    try:
        _create_rule(repo)
        evaluation = evaluate_assignment_rules(repo, _signals())
        assert evaluation.recommendation.engine_version == ASSIGNMENT_RULE_ENGINE_VERSION
    finally:
        conn.close()
