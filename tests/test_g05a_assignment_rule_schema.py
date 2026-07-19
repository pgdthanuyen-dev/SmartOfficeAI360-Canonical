from __future__ import annotations

import sqlite3

import pytest

from tools.qlvb_downloader.ai_proposal_repository import AiProposalRepository
from tools.qlvb_downloader.assignment_rule_models import (
    ASSIGNMENT_RULE_SCHEMA_VERSION,
    AssignmentRule,
    AssignmentRuleCondition,
    AssignmentRuleExclusion,
    AssignmentRuleMatch,
    AssignmentRuleRole,
    AssignmentRuleUnit,
    ConditionType,
    ExclusionType,
    MatchDecision,
    MatchMode,
    RuleRoleType,
    RuleStatus,
    RuleUnitType,
)
from tools.qlvb_downloader.assignment_rule_repository import (
    ASSIGNMENT_RULE_MIGRATION_VERSION,
    MIGRATION_RUNTIME_ENTRYPOINT,
    AssignmentRuleRepository,
    init_assignment_rule_schema,
)
from tools.qlvb_downloader.assignment_rule_validation import AssignmentRuleValidationError
from tools.qlvb_downloader.domain_models import Document, compute_stable_hash
from tools.qlvb_downloader.domain_repository import DomainRepository


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY, title TEXT)")
    return conn


def _seed():
    conn = _connect()
    domain_repo = DomainRepository(conn)
    domain_repo.save_document(
        Document(id="doc-1", tenant_id="tenant-a", source_system="QLVB", source_document_id="qlvb-1")
    )
    repo = AssignmentRuleRepository(conn)
    return conn, repo


def _rule(**overrides):
    payload = {
        "id": "rule-1",
        "tenant_id": "tenant-a",
        "rule_code": "R-001",
        "version": "1",
        "rule_name": "Bao cao tong hop",
        "domain_code": "VAN_PHONG",
        "subdomain_code": "BAO_CAO",
        "task_type": "REPORT",
        "description": "Xu ly bao cao",
        "priority": 10,
        "minimum_confidence": 70,
        "default_due_days": 5,
        "signature_buffer_days": 1,
        "draft_required": True,
        "draft_type": "REPORT_DRAFT",
        "source_reference": "QD-001",
        "effective_from": "2026-01-01",
        "effective_to": "2026-12-31",
        "status": RuleStatus.ACTIVE,
    }
    payload.update(overrides)
    return AssignmentRule(**payload)


def _condition(rule_id="rule-1", **overrides):
    payload = {
        "id": "cond-1",
        "rule_id": rule_id,
        "condition_type": ConditionType.REQUIRED_KEYWORD,
        "value": "bao cao",
        "weight": 40,
        "is_required": True,
        "match_mode": MatchMode.CONTAINS,
        "sort_order": 1,
    }
    payload.update(overrides)
    return AssignmentRuleCondition(**payload)


def _exclusion(rule_id="rule-1", **overrides):
    payload = {
        "id": "excl-1",
        "rule_id": rule_id,
        "exclusion_type": ExclusionType.EXCLUDED_KEYWORD,
        "value": "khong thuc hien",
        "penalty": 100,
        "is_hard_exclusion": True,
    }
    payload.update(overrides)
    return AssignmentRuleExclusion(**payload)


def _unit(rule_id="rule-1", **overrides):
    payload = {
        "id": "unit-1",
        "rule_id": rule_id,
        "unit_type": RuleUnitType.LEAD_UNIT,
        "source_unit_key": "VP",
        "unit_name": "Van phong",
        "priority": 1,
        "is_required": True,
    }
    payload.update(overrides)
    return AssignmentRuleUnit(**payload)


def _role(rule_id="rule-1", role_type=RuleRoleType.LEADER, **overrides):
    payload = {
        "id": f"role-{role_type.value.lower()}",
        "rule_id": rule_id,
        "role_type": role_type,
        "role_code": role_type.value,
        "unit_source_key": "VP",
        "is_required": role_type == RuleRoleType.LEADER,
        "priority": 1,
    }
    payload.update(overrides)
    return AssignmentRuleRole(**payload)


def _match(rule_id="rule-1", **overrides):
    payload = {
        "id": "match-1",
        "tenant_id": "tenant-a",
        "document_id": "doc-1",
        "document_revision": "1",
        "rule_id": rule_id,
        "rule_code": "R-001",
        "rule_version": "1",
        "score": 90,
        "decision": MatchDecision.MATCHED,
        "matched_condition_count": 1,
        "required_condition_count": 1,
        "exclusion_count": 0,
        "explanation": "Matched required signal.",
        "warnings_json": "[]",
        "input_fingerprint": compute_stable_hash({"doc": "doc-1", "rule": rule_id}),
    }
    payload.update(overrides)
    return AssignmentRuleMatch(**payload)


def test_create_valid_rule():
    conn, repo = _seed()
    try:
        rule_id = repo.create_rule(_rule())
        row = repo.get_rule(rule_id)
        assert row["rule_code"] == "R-001"
        assert row["schema_version"] == ASSIGNMENT_RULE_SCHEMA_VERSION
    finally:
        conn.close()


def test_rule_code_version_unique_by_tenant():
    conn, repo = _seed()
    try:
        repo.create_rule(_rule())
        with pytest.raises(sqlite3.IntegrityError):
            repo.create_rule(_rule(id="rule-duplicate"))
    finally:
        conn.close()


def test_same_rule_code_version_allowed_for_different_tenant():
    conn, repo = _seed()
    try:
        repo.create_rule(_rule())
        repo.create_rule(_rule(id="rule-2", tenant_id="tenant-b"))
        assert len(repo.list_rules()) == 2
    finally:
        conn.close()


def test_effective_date_valid():
    rule = _rule(effective_from="2026-01-01", effective_to="2026-01-02")
    conn, repo = _seed()
    try:
        repo.create_rule(rule)
        assert repo.get_rule(rule.id)["effective_to"] == "2026-01-02"
    finally:
        conn.close()


def test_effective_to_before_from_rejected():
    conn, repo = _seed()
    try:
        with pytest.raises(AssignmentRuleValidationError):
            repo.create_rule(_rule(effective_from="2026-02-01", effective_to="2026-01-01"))
    finally:
        conn.close()


def test_confidence_out_of_range_rejected():
    conn, repo = _seed()
    try:
        with pytest.raises(AssignmentRuleValidationError):
            repo.create_rule(_rule(minimum_confidence=101))
    finally:
        conn.close()


def test_required_condition_saved():
    conn, repo = _seed()
    try:
        repo.create_rule(_rule(), conditions=[_condition()])
        bundle = repo.get_rule_bundle("rule-1")
        assert bundle.conditions[0].is_required
        assert bundle.conditions[0].normalized_value == "bao cao"
    finally:
        conn.close()


def test_exclusion_saved():
    conn, repo = _seed()
    try:
        repo.create_rule(_rule(), exclusions=[_exclusion()])
        bundle = repo.get_rule_bundle("rule-1")
        assert bundle.exclusions[0].is_hard_exclusion
        assert bundle.exclusions[0].penalty == 100
    finally:
        conn.close()


def test_lead_unit_saved():
    conn, repo = _seed()
    try:
        repo.create_rule(_rule(), units=[_unit()])
        bundle = repo.get_rule_bundle("rule-1")
        assert bundle.units[0].unit_type == RuleUnitType.LEAD_UNIT
        assert bundle.units[0].source_unit_key == "VP"
    finally:
        conn.close()


def test_roles_saved():
    conn, repo = _seed()
    try:
        roles = [
            _role(role_type=RuleRoleType.LEADER),
            _role(role_type=RuleRoleType.MONITOR),
            _role(role_type=RuleRoleType.LEAD_EXECUTOR),
        ]
        repo.create_rule(_rule(), roles=roles)
        bundle = repo.get_rule_bundle("rule-1")
        assert {role.role_type for role in bundle.roles} == {
            RuleRoleType.LEADER,
            RuleRoleType.MONITOR,
            RuleRoleType.LEAD_EXECUTOR,
        }
    finally:
        conn.close()


def test_rule_bundle_reads_all_children():
    conn, repo = _seed()
    try:
        repo.create_rule(_rule(), conditions=[_condition()], exclusions=[_exclusion()], units=[_unit()], roles=[_role()])
        bundle = repo.get_rule_bundle("rule-1")
        assert bundle.rule.rule_code == "R-001"
        assert len(bundle.conditions) == 1
        assert len(bundle.exclusions) == 1
        assert len(bundle.units) == 1
        assert len(bundle.roles) == 1
    finally:
        conn.close()


def test_list_active_rules_excludes_draft_and_inactive():
    conn, repo = _seed()
    try:
        repo.create_rule(_rule())
        repo.create_rule(_rule(id="rule-draft", rule_code="R-002", status=RuleStatus.DRAFT))
        repo.create_rule(_rule(id="rule-inactive", rule_code="R-003", status=RuleStatus.INACTIVE))
        rows = repo.list_active_rules(as_of_date="2026-07-19", tenant_id="tenant-a")
        assert [row["rule_code"] for row in rows] == ["R-001"]
    finally:
        conn.close()


def test_list_active_rules_excludes_expired_rule():
    conn, repo = _seed()
    try:
        repo.create_rule(_rule(effective_to="2026-01-31"))
        assert repo.list_active_rules(as_of_date="2026-07-19", tenant_id="tenant-a") == []
    finally:
        conn.close()


def test_supersede_rule_preserves_match_history():
    conn, repo = _seed()
    try:
        repo.create_rule(_rule())
        repo.append_match(_match())
        repo.supersede_rule("rule-1")
        assert repo.get_rule("rule-1")["status"] == "SUPERSEDED"
        assert len(repo.list_matches_for_document("doc-1")) == 1
    finally:
        conn.close()


def test_match_history_append_only():
    conn, repo = _seed()
    try:
        repo.create_rule(_rule())
        repo.append_match(_match(id="match-1"))
        repo.append_match(_match(id="match-2", input_fingerprint=compute_stable_hash({"n": 2})))
        rows = repo.list_matches_for_document("doc-1")
        assert [row["id"] for row in rows] == ["match-1", "match-2"]
    finally:
        conn.close()


def test_match_score_validation():
    conn, repo = _seed()
    try:
        repo.create_rule(_rule())
        with pytest.raises(AssignmentRuleValidationError):
            repo.append_match(_match(score=101))
    finally:
        conn.close()


def test_fingerprint_validation():
    conn, repo = _seed()
    try:
        repo.create_rule(_rule())
        with pytest.raises(AssignmentRuleValidationError):
            repo.append_match(_match(input_fingerprint="not-sha"))
    finally:
        conn.close()


def test_migration_first_run_records_version():
    conn = _connect()
    try:
        init_assignment_rule_schema(conn)
        row = conn.execute(
            "SELECT version FROM schema_migrations WHERE version = ?",
            (ASSIGNMENT_RULE_MIGRATION_VERSION,),
        ).fetchone()
        assert row["version"] == ASSIGNMENT_RULE_MIGRATION_VERSION
        assert MIGRATION_RUNTIME_ENTRYPOINT == "LIBRARY_ONLY"
    finally:
        conn.close()


def test_migration_second_run_is_idempotent():
    conn = _connect()
    try:
        init_assignment_rule_schema(conn)
        init_assignment_rule_schema(conn)
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM schema_migrations WHERE version = ?",
            (ASSIGNMENT_RULE_MIGRATION_VERSION,),
        ).fetchone()["n"]
        assert count == 1
    finally:
        conn.close()


def test_legacy_g04_database_keeps_ai_proposal_rows():
    conn = _connect()
    try:
        domain_repo = DomainRepository(conn)
        domain_repo.save_document(
            Document(id="doc-1", tenant_id="tenant-a", source_system="QLVB", source_document_id="qlvb-1")
        )
        ai_repo = AiProposalRepository(conn)
        batch_id = ai_repo.create_batch(
            document_id="doc-1",
            idempotency_key="g04-key",
            schema_version="1.0.0",
            model_name="fake",
            model_version="v1",
            prompt_version="p1",
            generated_at="2026-07-19T00:00:00+00:00",
            raw_response_sha256="a" * 64,
            received_count=0,
        )
        init_assignment_rule_schema(conn)
        row = conn.execute("SELECT id FROM ai_proposal_batches WHERE id = ?", (batch_id,)).fetchone()
        assert row["id"] == batch_id
    finally:
        conn.close()


def test_foreign_key_rejects_match_without_rule():
    conn, repo = _seed()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            repo.append_match(_match(rule_id="missing-rule"))
    finally:
        conn.close()


def test_transaction_rolls_back_when_child_insert_fails():
    conn, repo = _seed()
    try:
        first = _condition(id="same-id", value="bao cao")
        second = _condition(id="same-id", value="van ban")
        with pytest.raises(sqlite3.IntegrityError):
            repo.create_rule(_rule(), conditions=[first, second])
        assert repo.get_rule("rule-1") is None
        count = conn.execute("SELECT COUNT(*) AS n FROM assignment_rule_conditions").fetchone()["n"]
        assert count == 0
    finally:
        conn.close()


def test_roles_do_not_store_specific_people():
    conn, repo = _seed()
    try:
        repo.create_rule(_rule(), roles=[_role()])
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(assignment_rule_roles)").fetchall()}
        assert "user_id" not in columns
        assert "planner_user_id" not in columns
        assert "target_user_id" not in columns
    finally:
        conn.close()


def test_no_planner_or_sharepoint_binary_fields():
    conn, _ = _seed()
    try:
        forbidden = {"planner_payload", "planner_user_id", "sharepoint_url", "binary_payload", "token", "cookie"}
        columns = {
            row["name"]
            for table in (
                "assignment_rules",
                "assignment_rule_conditions",
                "assignment_rule_exclusions",
                "assignment_rule_units",
                "assignment_rule_roles",
                "assignment_rule_matches",
            )
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        assert columns.isdisjoint(forbidden)
    finally:
        conn.close()
