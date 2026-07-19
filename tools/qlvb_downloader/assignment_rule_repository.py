from __future__ import annotations

import sqlite3
from typing import Any

from .assignment_rule_models import (
    ASSIGNMENT_RULE_SCHEMA_VERSION,
    AssignmentRule,
    AssignmentRuleBundle,
    AssignmentRuleCondition,
    AssignmentRuleExclusion,
    AssignmentRuleMatch,
    AssignmentRuleRole,
    AssignmentRuleUnit,
    RuleStatus,
)
from .assignment_rule_validation import (
    AssignmentRuleValidationError,
    validate_condition,
    validate_exclusion,
    validate_match,
    validate_role,
    validate_rule,
    validate_rule_bundle,
    validate_unit,
)
from .domain_models import utc_now_iso
from .domain_repository import init_domain_schema


ASSIGNMENT_RULE_MIGRATION_VERSION = "g05a_assignment_rule_schema_1"
MIGRATION_RUNTIME_ENTRYPOINT = "LIBRARY_ONLY"


_CREATE_TABLES_SQL = [
    """
    CREATE TABLE IF NOT EXISTS assignment_rules (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        rule_code TEXT NOT NULL,
        version TEXT NOT NULL,
        rule_name TEXT NOT NULL,
        domain_code TEXT NOT NULL,
        subdomain_code TEXT,
        task_type TEXT,
        description TEXT,
        priority INTEGER NOT NULL,
        minimum_confidence INTEGER NOT NULL,
        default_due_days INTEGER,
        signature_buffer_days INTEGER,
        draft_required INTEGER NOT NULL,
        draft_type TEXT,
        source_reference TEXT,
        effective_from TEXT,
        effective_to TEXT,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        schema_version TEXT NOT NULL,
        UNIQUE(tenant_id, rule_code, version)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS assignment_rule_conditions (
        id TEXT PRIMARY KEY,
        rule_id TEXT NOT NULL,
        condition_type TEXT NOT NULL,
        value TEXT NOT NULL,
        normalized_value TEXT NOT NULL,
        weight INTEGER NOT NULL,
        is_required INTEGER NOT NULL,
        match_mode TEXT NOT NULL,
        sort_order INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(rule_id) REFERENCES assignment_rules(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS assignment_rule_exclusions (
        id TEXT PRIMARY KEY,
        rule_id TEXT NOT NULL,
        exclusion_type TEXT NOT NULL,
        value TEXT NOT NULL,
        normalized_value TEXT NOT NULL,
        penalty INTEGER NOT NULL,
        is_hard_exclusion INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(rule_id) REFERENCES assignment_rules(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS assignment_rule_units (
        id TEXT PRIMARY KEY,
        rule_id TEXT NOT NULL,
        unit_type TEXT NOT NULL,
        source_unit_key TEXT NOT NULL,
        unit_name TEXT NOT NULL,
        priority INTEGER NOT NULL,
        is_required INTEGER NOT NULL,
        effective_from TEXT,
        effective_to TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(rule_id) REFERENCES assignment_rules(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS assignment_rule_roles (
        id TEXT PRIMARY KEY,
        rule_id TEXT NOT NULL,
        role_type TEXT NOT NULL,
        role_code TEXT NOT NULL,
        unit_source_key TEXT NOT NULL,
        is_required INTEGER NOT NULL,
        priority INTEGER NOT NULL,
        effective_from TEXT,
        effective_to TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(rule_id) REFERENCES assignment_rules(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS assignment_rule_matches (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        document_id TEXT NOT NULL,
        document_revision TEXT NOT NULL,
        rule_id TEXT NOT NULL,
        rule_code TEXT NOT NULL,
        rule_version TEXT NOT NULL,
        score INTEGER NOT NULL,
        decision TEXT NOT NULL,
        matched_condition_count INTEGER NOT NULL,
        required_condition_count INTEGER NOT NULL,
        exclusion_count INTEGER NOT NULL,
        explanation TEXT,
        warnings_json TEXT NOT NULL,
        input_fingerprint TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(document_id) REFERENCES documents(doc_id) ON DELETE CASCADE,
        FOREIGN KEY(rule_id) REFERENCES assignment_rules(id) ON DELETE RESTRICT
    );
    """,
]

_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_assignment_rules_status_dates ON assignment_rules(tenant_id, status, effective_from, effective_to);",
    "CREATE INDEX IF NOT EXISTS idx_assignment_rule_conditions_rule_type ON assignment_rule_conditions(rule_id, condition_type);",
    "CREATE INDEX IF NOT EXISTS idx_assignment_rule_exclusions_rule_type ON assignment_rule_exclusions(rule_id, exclusion_type);",
    "CREATE INDEX IF NOT EXISTS idx_assignment_rule_units_rule_type ON assignment_rule_units(rule_id, unit_type);",
    "CREATE INDEX IF NOT EXISTS idx_assignment_rule_roles_rule_type ON assignment_rule_roles(rule_id, role_type);",
    "CREATE INDEX IF NOT EXISTS idx_assignment_rule_matches_document_revision ON assignment_rule_matches(document_id, document_revision);",
    "CREATE INDEX IF NOT EXISTS idx_assignment_rule_matches_rule_id ON assignment_rule_matches(rule_id);",
    "CREATE INDEX IF NOT EXISTS idx_assignment_rule_matches_fingerprint ON assignment_rule_matches(input_fingerprint);",
]


def init_assignment_rule_schema(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    init_domain_schema(conn)
    for sql in _CREATE_TABLES_SQL:
        conn.execute(sql)
    for sql in _INDEXES_SQL:
        conn.execute(sql)
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
        (ASSIGNMENT_RULE_MIGRATION_VERSION, utc_now_iso()),
    )
    conn.commit()


class AssignmentRuleRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON;")
        init_assignment_rule_schema(conn)

    def create_rule(
        self,
        rule: AssignmentRule,
        *,
        conditions: list[AssignmentRuleCondition] | None = None,
        exclusions: list[AssignmentRuleExclusion] | None = None,
        units: list[AssignmentRuleUnit] | None = None,
        roles: list[AssignmentRuleRole] | None = None,
    ) -> str:
        conditions = conditions or []
        exclusions = exclusions or []
        units = units or []
        roles = roles or []
        validate_rule_bundle(rule, conditions, exclusions, units, roles)
        with self.conn:
            self._insert_rule(rule)
            for condition in conditions:
                self._insert_condition(condition)
            for exclusion in exclusions:
                self._insert_exclusion(exclusion)
            for unit in units:
                self._insert_unit(unit)
            for role in roles:
                self._insert_role(role)
        return rule.id

    def get_rule(self, rule_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM assignment_rules WHERE id = ?", (rule_id,)).fetchone()
        return dict(row) if row is not None else None

    def list_rules(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        if tenant_id is None:
            rows = self.conn.execute("SELECT * FROM assignment_rules ORDER BY tenant_id, rule_code, version").fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM assignment_rules WHERE tenant_id = ? ORDER BY rule_code, version",
                (tenant_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_rule(self, rule: AssignmentRule, *, expected_updated_at: str) -> None:
        validate_rule(rule)
        rule.updated_at = utc_now_iso()
        with self.conn:
            cur = self.conn.execute(
                """
                UPDATE assignment_rules
                SET rule_name = ?, domain_code = ?, subdomain_code = ?, task_type = ?,
                    description = ?, priority = ?, minimum_confidence = ?,
                    default_due_days = ?, signature_buffer_days = ?, draft_required = ?,
                    draft_type = ?, source_reference = ?, effective_from = ?, effective_to = ?,
                    status = ?, updated_at = ?, schema_version = ?
                WHERE id = ? AND updated_at = ?
                """,
                (
                    rule.rule_name,
                    rule.domain_code,
                    rule.subdomain_code,
                    rule.task_type,
                    rule.description,
                    rule.priority,
                    rule.minimum_confidence,
                    rule.default_due_days,
                    rule.signature_buffer_days,
                    1 if rule.draft_required else 0,
                    rule.draft_type,
                    rule.source_reference,
                    rule.effective_from,
                    rule.effective_to,
                    rule.status.value,
                    rule.updated_at,
                    rule.schema_version,
                    rule.id,
                    expected_updated_at,
                ),
            )
            if cur.rowcount != 1:
                raise AssignmentRuleValidationError("rule update conflict")

    def supersede_rule(self, rule_id: str) -> None:
        now = utc_now_iso()
        with self.conn:
            cur = self.conn.execute(
                "UPDATE assignment_rules SET status = ?, updated_at = ? WHERE id = ?",
                (RuleStatus.SUPERSEDED.value, now, rule_id),
            )
            if cur.rowcount != 1:
                raise AssignmentRuleValidationError("rule not found")

    def add_condition(self, condition: AssignmentRuleCondition) -> str:
        validate_condition(condition)
        with self.conn:
            self._insert_condition(condition)
        return condition.id

    def add_exclusion(self, exclusion: AssignmentRuleExclusion) -> str:
        validate_exclusion(exclusion)
        with self.conn:
            self._insert_exclusion(exclusion)
        return exclusion.id

    def add_unit(self, unit: AssignmentRuleUnit) -> str:
        validate_unit(unit)
        with self.conn:
            self._insert_unit(unit)
        return unit.id

    def add_role(self, role: AssignmentRuleRole) -> str:
        validate_role(role)
        with self.conn:
            self._insert_role(role)
        return role.id

    def get_rule_bundle(self, rule_id: str) -> AssignmentRuleBundle | None:
        rule_row = self.get_rule(rule_id)
        if rule_row is None:
            return None
        return AssignmentRuleBundle(
            rule=_rule_from_row(rule_row),
            conditions=[_condition_from_row(row) for row in self._list_children("assignment_rule_conditions", rule_id)],
            exclusions=[_exclusion_from_row(row) for row in self._list_children("assignment_rule_exclusions", rule_id)],
            units=[_unit_from_row(row) for row in self._list_children("assignment_rule_units", rule_id)],
            roles=[_role_from_row(row) for row in self._list_children("assignment_rule_roles", rule_id)],
        )

    def list_active_rules(self, *, as_of_date: str, tenant_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM assignment_rules
            WHERE tenant_id = ?
              AND status = ?
              AND (effective_from IS NULL OR effective_from <= ?)
              AND (effective_to IS NULL OR effective_to >= ?)
            ORDER BY priority DESC, rule_code, version
            """,
            (tenant_id, RuleStatus.ACTIVE.value, as_of_date, as_of_date),
        ).fetchall()
        return [dict(row) for row in rows]

    def append_match(self, match: AssignmentRuleMatch) -> str:
        validate_match(match)
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO assignment_rule_matches (
                    id, tenant_id, document_id, document_revision, rule_id, rule_code,
                    rule_version, score, decision, matched_condition_count,
                    required_condition_count, exclusion_count, explanation, warnings_json,
                    input_fingerprint, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    match.id,
                    match.tenant_id,
                    match.document_id,
                    match.document_revision,
                    match.rule_id,
                    match.rule_code,
                    match.rule_version,
                    match.score,
                    match.decision.value,
                    match.matched_condition_count,
                    match.required_condition_count,
                    match.exclusion_count,
                    match.explanation,
                    match.warnings_json,
                    match.input_fingerprint,
                    match.created_at,
                ),
            )
        return match.id

    def list_matches_for_document(self, document_id: str, document_revision: str | None = None) -> list[dict[str, Any]]:
        if document_revision is None:
            rows = self.conn.execute(
                "SELECT * FROM assignment_rule_matches WHERE document_id = ? ORDER BY created_at, id",
                (document_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT * FROM assignment_rule_matches
                WHERE document_id = ? AND document_revision = ?
                ORDER BY created_at, id
                """,
                (document_id, document_revision),
            ).fetchall()
        return [dict(row) for row in rows]

    def _list_children(self, table_name: str, rule_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            f"SELECT * FROM {table_name} WHERE rule_id = ? ORDER BY created_at, id",
            (rule_id,),
        ).fetchall()

    def _insert_rule(self, rule: AssignmentRule) -> None:
        self.conn.execute(
            """
            INSERT INTO assignment_rules (
                id, tenant_id, rule_code, version, rule_name, domain_code, subdomain_code,
                task_type, description, priority, minimum_confidence, default_due_days,
                signature_buffer_days, draft_required, draft_type, source_reference,
                effective_from, effective_to, status, created_at, updated_at, schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rule.id,
                rule.tenant_id,
                rule.rule_code,
                rule.version,
                rule.rule_name,
                rule.domain_code,
                rule.subdomain_code,
                rule.task_type,
                rule.description,
                rule.priority,
                rule.minimum_confidence,
                rule.default_due_days,
                rule.signature_buffer_days,
                1 if rule.draft_required else 0,
                rule.draft_type,
                rule.source_reference,
                rule.effective_from,
                rule.effective_to,
                rule.status.value,
                rule.created_at,
                rule.updated_at,
                rule.schema_version or ASSIGNMENT_RULE_SCHEMA_VERSION,
            ),
        )

    def _insert_condition(self, condition: AssignmentRuleCondition) -> None:
        self.conn.execute(
            """
            INSERT INTO assignment_rule_conditions (
                id, rule_id, condition_type, value, normalized_value, weight,
                is_required, match_mode, sort_order, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                condition.id,
                condition.rule_id,
                condition.condition_type.value,
                condition.value,
                condition.normalized_value,
                condition.weight,
                1 if condition.is_required else 0,
                condition.match_mode.value,
                condition.sort_order,
                condition.created_at,
            ),
        )

    def _insert_exclusion(self, exclusion: AssignmentRuleExclusion) -> None:
        self.conn.execute(
            """
            INSERT INTO assignment_rule_exclusions (
                id, rule_id, exclusion_type, value, normalized_value, penalty,
                is_hard_exclusion, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                exclusion.id,
                exclusion.rule_id,
                exclusion.exclusion_type.value,
                exclusion.value,
                exclusion.normalized_value,
                exclusion.penalty,
                1 if exclusion.is_hard_exclusion else 0,
                exclusion.created_at,
            ),
        )

    def _insert_unit(self, unit: AssignmentRuleUnit) -> None:
        self.conn.execute(
            """
            INSERT INTO assignment_rule_units (
                id, rule_id, unit_type, source_unit_key, unit_name, priority,
                is_required, effective_from, effective_to, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                unit.id,
                unit.rule_id,
                unit.unit_type.value,
                unit.source_unit_key,
                unit.unit_name,
                unit.priority,
                1 if unit.is_required else 0,
                unit.effective_from,
                unit.effective_to,
                unit.created_at,
            ),
        )

    def _insert_role(self, role: AssignmentRuleRole) -> None:
        self.conn.execute(
            """
            INSERT INTO assignment_rule_roles (
                id, rule_id, role_type, role_code, unit_source_key, is_required,
                priority, effective_from, effective_to, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                role.id,
                role.rule_id,
                role.role_type.value,
                role.role_code,
                role.unit_source_key,
                1 if role.is_required else 0,
                role.priority,
                role.effective_from,
                role.effective_to,
                role.created_at,
            ),
        )


def _rule_from_row(row: dict[str, Any]) -> AssignmentRule:
    return AssignmentRule(
        id=row["id"],
        tenant_id=row["tenant_id"],
        rule_code=row["rule_code"],
        version=row["version"],
        rule_name=row["rule_name"],
        domain_code=row["domain_code"],
        subdomain_code=row["subdomain_code"],
        task_type=row["task_type"],
        description=row["description"],
        priority=row["priority"],
        minimum_confidence=row["minimum_confidence"],
        default_due_days=row["default_due_days"],
        signature_buffer_days=row["signature_buffer_days"],
        draft_required=bool(row["draft_required"]),
        draft_type=row["draft_type"],
        source_reference=row["source_reference"],
        effective_from=row["effective_from"],
        effective_to=row["effective_to"],
        status=RuleStatus(row["status"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        schema_version=row["schema_version"],
    )


def _condition_from_row(row: sqlite3.Row) -> AssignmentRuleCondition:
    return AssignmentRuleCondition.from_dict(dict(row))


def _exclusion_from_row(row: sqlite3.Row) -> AssignmentRuleExclusion:
    return AssignmentRuleExclusion.from_dict(dict(row))


def _unit_from_row(row: sqlite3.Row) -> AssignmentRuleUnit:
    return AssignmentRuleUnit.from_dict(dict(row))


def _role_from_row(row: sqlite3.Row) -> AssignmentRuleRole:
    return AssignmentRuleRole.from_dict(dict(row))
