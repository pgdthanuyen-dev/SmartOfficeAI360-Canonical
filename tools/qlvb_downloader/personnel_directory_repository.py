from __future__ import annotations

import sqlite3
from typing import Any

from .assignment_rule_repository import init_assignment_rule_schema
from .domain_models import utc_now_iso
from .personnel_directory_models import (
    AvailabilityStatus,
    OrganizationUnit,
    PersonnelAvailability,
    PersonnelDomainAssignment,
    PersonnelRecord,
    PersonnelRoleAssignment,
    PersonnelSelectionMatch,
    PersonnelStatus,
    PersonnelSubstitution,
    SubstitutionStatus,
    UnitStatus,
)
from .personnel_directory_validation import (
    PersonnelDirectoryConflictError,
    PersonnelDirectoryValidationError,
    assert_no_directed_cycle,
    date_ranges_overlap,
    validate_availability,
    validate_domain_assignment,
    validate_personnel,
    validate_role_assignment,
    validate_selection_match,
    validate_substitution,
    validate_unit,
)


PERSONNEL_DIRECTORY_MIGRATION_VERSION = "g05b_personnel_unit_directory_schema_1"
MIGRATION_RUNTIME_ENTRYPOINT = "LIBRARY_ONLY"

_TABLES_SQL = [
    """CREATE TABLE IF NOT EXISTS organization_units (
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, source_unit_key TEXT NOT NULL,
        record_version INTEGER NOT NULL, unit_code TEXT NOT NULL, unit_name TEXT NOT NULL,
        normalized_name TEXT NOT NULL, unit_type TEXT NOT NULL, parent_unit_id TEXT,
        status TEXT NOT NULL, effective_from TEXT, effective_to TEXT, source_reference TEXT,
        row_version INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        schema_version TEXT NOT NULL,
        UNIQUE(tenant_id, source_unit_key, record_version),
        FOREIGN KEY(parent_unit_id) REFERENCES organization_units(id) ON DELETE RESTRICT
    );""",
    """CREATE TABLE IF NOT EXISTS personnel_records (
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, source_person_key TEXT NOT NULL,
        record_version INTEGER NOT NULL, full_name TEXT NOT NULL, normalized_name TEXT NOT NULL,
        position_title TEXT, primary_unit_id TEXT, status TEXT NOT NULL,
        effective_from TEXT, effective_to TEXT, source_reference TEXT,
        row_version INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        schema_version TEXT NOT NULL,
        UNIQUE(tenant_id, source_person_key, record_version),
        FOREIGN KEY(primary_unit_id) REFERENCES organization_units(id) ON DELETE RESTRICT
    );""",
    """CREATE TABLE IF NOT EXISTS personnel_domain_assignments (
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, personnel_id TEXT NOT NULL,
        domain_code TEXT NOT NULL, subdomain_code TEXT, responsibility_level TEXT NOT NULL,
        is_primary INTEGER NOT NULL, priority INTEGER NOT NULL, effective_from TEXT,
        effective_to TEXT, source_reference TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        FOREIGN KEY(personnel_id) REFERENCES personnel_records(id) ON DELETE RESTRICT
    );""",
    """CREATE TABLE IF NOT EXISTS personnel_role_assignments (
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, personnel_id TEXT NOT NULL,
        unit_id TEXT NOT NULL, role_type TEXT NOT NULL, role_code TEXT NOT NULL,
        is_primary INTEGER NOT NULL, priority INTEGER NOT NULL, effective_from TEXT,
        effective_to TEXT, source_reference TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        FOREIGN KEY(personnel_id) REFERENCES personnel_records(id) ON DELETE RESTRICT,
        FOREIGN KEY(unit_id) REFERENCES organization_units(id) ON DELETE RESTRICT
    );""",
    """CREATE TABLE IF NOT EXISTS personnel_substitutions (
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, primary_personnel_id TEXT NOT NULL,
        substitute_personnel_id TEXT NOT NULL, role_type TEXT NOT NULL, unit_id TEXT,
        reason TEXT, effective_from TEXT, effective_to TEXT, status TEXT NOT NULL,
        source_reference TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        FOREIGN KEY(primary_personnel_id) REFERENCES personnel_records(id) ON DELETE RESTRICT,
        FOREIGN KEY(substitute_personnel_id) REFERENCES personnel_records(id) ON DELETE RESTRICT,
        FOREIGN KEY(unit_id) REFERENCES organization_units(id) ON DELETE RESTRICT
    );""",
    """CREATE TABLE IF NOT EXISTS personnel_availability (
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, personnel_id TEXT NOT NULL,
        availability_status TEXT NOT NULL, unavailable_from TEXT NOT NULL, unavailable_to TEXT,
        reason TEXT, source_reference TEXT, recorded_at TEXT NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        FOREIGN KEY(personnel_id) REFERENCES personnel_records(id) ON DELETE RESTRICT
    );""",
    """CREATE TABLE IF NOT EXISTS personnel_selection_matches (
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, document_id TEXT NOT NULL,
        document_revision TEXT NOT NULL, assignment_rule_match_id TEXT, role_type TEXT NOT NULL,
        unit_id TEXT, personnel_id TEXT, score REAL NOT NULL, decision TEXT NOT NULL,
        explanation TEXT, warnings_json TEXT NOT NULL, input_fingerprint TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(document_id) REFERENCES documents(doc_id) ON DELETE RESTRICT,
        FOREIGN KEY(assignment_rule_match_id) REFERENCES assignment_rule_matches(id) ON DELETE RESTRICT,
        FOREIGN KEY(unit_id) REFERENCES organization_units(id) ON DELETE RESTRICT,
        FOREIGN KEY(personnel_id) REFERENCES personnel_records(id) ON DELETE RESTRICT
    );""",
]

_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_org_units_tenant_status ON organization_units(tenant_id, status);",
    "CREATE INDEX IF NOT EXISTS idx_org_units_source_dates ON organization_units(tenant_id, source_unit_key, effective_from, effective_to);",
    "CREATE INDEX IF NOT EXISTS idx_org_units_parent ON organization_units(parent_unit_id);",
    "CREATE INDEX IF NOT EXISTS idx_personnel_tenant_status ON personnel_records(tenant_id, status);",
    "CREATE INDEX IF NOT EXISTS idx_personnel_source_dates ON personnel_records(tenant_id, source_person_key, effective_from, effective_to);",
    "CREATE INDEX IF NOT EXISTS idx_personnel_primary_unit ON personnel_records(primary_unit_id);",
    "CREATE INDEX IF NOT EXISTS idx_personnel_normalized_name ON personnel_records(normalized_name);",
    "CREATE INDEX IF NOT EXISTS idx_domain_personnel ON personnel_domain_assignments(personnel_id);",
    "CREATE INDEX IF NOT EXISTS idx_domain_lookup ON personnel_domain_assignments(domain_code, subdomain_code, effective_from, effective_to);",
    "CREATE INDEX IF NOT EXISTS idx_role_lookup ON personnel_role_assignments(unit_id, role_type, effective_from, effective_to);",
    "CREATE INDEX IF NOT EXISTS idx_role_personnel ON personnel_role_assignments(personnel_id);",
    "CREATE INDEX IF NOT EXISTS idx_substitution_primary ON personnel_substitutions(primary_personnel_id, status, effective_from, effective_to);",
    "CREATE INDEX IF NOT EXISTS idx_substitution_substitute ON personnel_substitutions(substitute_personnel_id);",
    "CREATE INDEX IF NOT EXISTS idx_availability_lookup ON personnel_availability(personnel_id, availability_status, unavailable_from, unavailable_to);",
    "CREATE INDEX IF NOT EXISTS idx_selection_document ON personnel_selection_matches(document_id, document_revision);",
    "CREATE INDEX IF NOT EXISTS idx_selection_rule_match ON personnel_selection_matches(assignment_rule_match_id);",
    "CREATE INDEX IF NOT EXISTS idx_selection_fingerprint ON personnel_selection_matches(input_fingerprint);",
]


def init_personnel_directory_schema(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    init_assignment_rule_schema(conn)
    for sql in _TABLES_SQL + _INDEXES_SQL:
        conn.execute(sql)
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
        (PERSONNEL_DIRECTORY_MIGRATION_VERSION, utc_now_iso()),
    )
    conn.commit()


class PersonnelDirectoryRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON;")
        init_personnel_directory_schema(conn)

    def create_unit(self, unit: OrganizationUnit) -> str:
        validate_unit(unit)
        self._validate_unit_relationship(unit)
        self._assert_unit_version_window(unit)
        try:
            with self.conn:
                self._insert_unit(unit)
        except sqlite3.IntegrityError as exc:
            raise PersonnelDirectoryConflictError("unit unique or foreign-key conflict") from exc
        return unit.id

    def get_unit(self, unit_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM organization_units WHERE id = ?", (unit_id,))

    def get_unit_by_source_key(self, tenant_id: str, source_unit_key: str, as_of_date: str | None = None) -> dict[str, Any] | None:
        rows = self.list_units(tenant_id=tenant_id, source_unit_key=source_unit_key, as_of_date=as_of_date)
        return rows[0] if rows else None

    def list_units(self, *, tenant_id: str | None = None, source_unit_key: str | None = None, as_of_date: str | None = None) -> list[dict[str, Any]]:
        sql, params = "SELECT * FROM organization_units WHERE 1=1", []
        if tenant_id: sql, params = sql + " AND tenant_id = ?", params + [tenant_id]
        if source_unit_key: sql, params = sql + " AND source_unit_key = ?", params + [source_unit_key]
        if as_of_date: sql, params = sql + " AND (effective_from IS NULL OR effective_from <= ?) AND (effective_to IS NULL OR effective_to >= ?)", params + [as_of_date, as_of_date]
        return self._many(sql + " ORDER BY record_version DESC, id", params)

    def list_active_units(self, tenant_id: str, as_of_date: str) -> list[dict[str, Any]]:
        return self._many("SELECT * FROM organization_units WHERE tenant_id = ? AND status = ? AND (effective_from IS NULL OR effective_from <= ?) AND (effective_to IS NULL OR effective_to >= ?) ORDER BY source_unit_key, record_version DESC", (tenant_id, UnitStatus.ACTIVE.value, as_of_date, as_of_date))

    def update_unit(self, unit: OrganizationUnit, expected_row_version: int) -> int:
        validate_unit(unit); self._validate_unit_relationship(unit); self._assert_unit_version_window(unit, exclude_id=unit.id)
        next_version = expected_row_version + 1
        with self.conn:
            cursor = self.conn.execute("UPDATE organization_units SET unit_code=?, unit_name=?, normalized_name=?, unit_type=?, parent_unit_id=?, status=?, effective_from=?, effective_to=?, source_reference=?, row_version=?, updated_at=? WHERE id=? AND row_version=?", (unit.unit_code, unit.unit_name, unit.normalized_name, unit.unit_type.value, unit.parent_unit_id, unit.status.value, unit.effective_from, unit.effective_to, unit.source_reference, next_version, utc_now_iso(), unit.id, expected_row_version))
            if cursor.rowcount != 1: raise PersonnelDirectoryConflictError("stale unit update")
        return next_version

    def supersede_unit(self, unit: OrganizationUnit, expected_row_version: int) -> int:
        unit.status = UnitStatus.SUPERSEDED
        return self.update_unit(unit, expected_row_version)

    def get_unit_tree(self, tenant_id: str) -> list[dict[str, Any]]:
        return self._many("SELECT * FROM organization_units WHERE tenant_id = ? ORDER BY parent_unit_id, source_unit_key, record_version", (tenant_id,))

    def create_personnel(self, personnel: PersonnelRecord, *, domains: list[PersonnelDomainAssignment] | None = None, roles: list[PersonnelRoleAssignment] | None = None) -> str:
        validate_personnel(personnel); self._assert_tenant_row("organization_units", personnel.primary_unit_id, personnel.tenant_id, "primary unit")
        self._assert_personnel_version_window(personnel)
        domains, roles = domains or [], roles or []
        try:
            with self.conn:
                self._insert_personnel(personnel)
                for assignment in domains: self.add_domain_assignment(assignment, commit=False)
                for assignment in roles: self.add_role_assignment(assignment, commit=False)
        except sqlite3.IntegrityError as exc:
            raise PersonnelDirectoryConflictError("personnel unique or foreign-key conflict") from exc
        return personnel.id

    def get_personnel(self, personnel_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM personnel_records WHERE id = ?", (personnel_id,))

    def get_personnel_by_source_key(self, tenant_id: str, source_person_key: str, as_of_date: str | None = None) -> dict[str, Any] | None:
        rows = self.list_personnel(tenant_id=tenant_id, source_person_key=source_person_key, as_of_date=as_of_date)
        return rows[0] if rows else None

    def list_personnel(self, *, tenant_id: str | None = None, source_person_key: str | None = None, as_of_date: str | None = None) -> list[dict[str, Any]]:
        sql, params = "SELECT * FROM personnel_records WHERE 1=1", []
        if tenant_id: sql, params = sql + " AND tenant_id = ?", params + [tenant_id]
        if source_person_key: sql, params = sql + " AND source_person_key = ?", params + [source_person_key]
        if as_of_date: sql, params = sql + " AND (effective_from IS NULL OR effective_from <= ?) AND (effective_to IS NULL OR effective_to >= ?)", params + [as_of_date, as_of_date]
        return self._many(sql + " ORDER BY record_version DESC, id", params)

    def list_active_personnel(self, tenant_id: str, as_of_date: str) -> list[dict[str, Any]]:
        return self._many("SELECT * FROM personnel_records WHERE tenant_id=? AND status=? AND (effective_from IS NULL OR effective_from<=?) AND (effective_to IS NULL OR effective_to>=?) ORDER BY source_person_key, record_version DESC", (tenant_id, PersonnelStatus.ACTIVE.value, as_of_date, as_of_date))

    def update_personnel(self, personnel: PersonnelRecord, expected_row_version: int) -> int:
        validate_personnel(personnel); self._assert_tenant_row("organization_units", personnel.primary_unit_id, personnel.tenant_id, "primary unit"); self._assert_personnel_version_window(personnel, exclude_id=personnel.id)
        next_version = expected_row_version + 1
        with self.conn:
            cursor = self.conn.execute("UPDATE personnel_records SET full_name=?, normalized_name=?, position_title=?, primary_unit_id=?, status=?, effective_from=?, effective_to=?, source_reference=?, row_version=?, updated_at=? WHERE id=? AND row_version=?", (personnel.full_name, personnel.normalized_name, personnel.position_title, personnel.primary_unit_id, personnel.status.value, personnel.effective_from, personnel.effective_to, personnel.source_reference, next_version, utc_now_iso(), personnel.id, expected_row_version))
            if cursor.rowcount != 1: raise PersonnelDirectoryConflictError("stale personnel update")
        return next_version

    def supersede_personnel(self, personnel: PersonnelRecord, expected_row_version: int) -> int:
        personnel.status = PersonnelStatus.TRANSFERRED
        return self.update_personnel(personnel, expected_row_version)

    def get_personnel_bundle(self, personnel_id: str) -> dict[str, Any] | None:
        person = self.get_personnel(personnel_id)
        if person is None: return None
        person["domains"] = self.list_domain_assignments(personnel_id=personnel_id)
        person["roles"] = self.list_role_assignments(personnel_id=personnel_id)
        person["availability"] = self.list_availability(personnel_id)
        return person

    def add_domain_assignment(self, assignment: PersonnelDomainAssignment, *, commit: bool = True) -> str:
        validate_domain_assignment(assignment); self._assert_tenant_row("personnel_records", assignment.personnel_id, assignment.tenant_id, "domain personnel")
        self._assert_no_overlap("personnel_domain_assignments", "personnel_id=? AND domain_code=? AND COALESCE(subdomain_code, '')=COALESCE(?, '') AND responsibility_level=?", (assignment.personnel_id, assignment.domain_code, assignment.subdomain_code, assignment.responsibility_level.value), assignment.effective_from, assignment.effective_to, "duplicate domain assignment")
        self.conn.execute("INSERT INTO personnel_domain_assignments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (assignment.id, assignment.tenant_id, assignment.personnel_id, assignment.domain_code, assignment.subdomain_code, assignment.responsibility_level.value, int(assignment.is_primary), assignment.priority, assignment.effective_from, assignment.effective_to, assignment.source_reference, assignment.created_at, assignment.updated_at))
        if commit: self.conn.commit()
        return assignment.id

    def list_domain_assignments(self, *, personnel_id: str | None = None, domain_code: str | None = None, as_of_date: str | None = None) -> list[dict[str, Any]]:
        return self._list_assignments("personnel_domain_assignments", personnel_id, domain_code, as_of_date, "domain_code")

    def list_personnel_by_domain(self, tenant_id: str, domain_code: str, as_of_date: str) -> list[dict[str, Any]]:
        return self._many("SELECT p.* FROM personnel_records p JOIN personnel_domain_assignments d ON d.personnel_id=p.id WHERE p.tenant_id=? AND d.domain_code=? AND (d.effective_from IS NULL OR d.effective_from<=?) AND (d.effective_to IS NULL OR d.effective_to>=?) ORDER BY d.is_primary DESC,d.priority DESC,p.source_person_key", (tenant_id, domain_code, as_of_date, as_of_date))

    def add_role_assignment(self, assignment: PersonnelRoleAssignment, *, commit: bool = True) -> str:
        validate_role_assignment(assignment); self._assert_tenant_row("personnel_records", assignment.personnel_id, assignment.tenant_id, "role personnel"); self._assert_tenant_row("organization_units", assignment.unit_id, assignment.tenant_id, "role unit")
        self._assert_no_overlap("personnel_role_assignments", "personnel_id=? AND unit_id=? AND role_type=? AND role_code=?", (assignment.personnel_id, assignment.unit_id, assignment.role_type.value, assignment.role_code), assignment.effective_from, assignment.effective_to, "duplicate role assignment")
        self.conn.execute("INSERT INTO personnel_role_assignments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (assignment.id, assignment.tenant_id, assignment.personnel_id, assignment.unit_id, assignment.role_type.value, assignment.role_code, int(assignment.is_primary), assignment.priority, assignment.effective_from, assignment.effective_to, assignment.source_reference, assignment.created_at, assignment.updated_at))
        if commit: self.conn.commit()
        return assignment.id

    def list_role_assignments(self, *, personnel_id: str | None = None, role_type: str | None = None, as_of_date: str | None = None) -> list[dict[str, Any]]:
        return self._list_assignments("personnel_role_assignments", personnel_id, role_type, as_of_date, "role_type")

    def list_personnel_by_role(self, tenant_id: str, unit_id: str, role_type: str, as_of_date: str) -> list[dict[str, Any]]:
        return self._many("SELECT p.* FROM personnel_records p JOIN personnel_role_assignments r ON r.personnel_id=p.id WHERE p.tenant_id=? AND r.unit_id=? AND r.role_type=? AND (r.effective_from IS NULL OR r.effective_from<=?) AND (r.effective_to IS NULL OR r.effective_to>=?) ORDER BY r.is_primary DESC,r.priority DESC,p.source_person_key", (tenant_id, unit_id, role_type, as_of_date, as_of_date))

    def add_substitution(self, substitution: PersonnelSubstitution) -> str:
        validate_substitution(substitution); self._assert_tenant_row("personnel_records", substitution.primary_personnel_id, substitution.tenant_id, "primary personnel"); self._assert_tenant_row("personnel_records", substitution.substitute_personnel_id, substitution.tenant_id, "substitute personnel"); self._assert_tenant_row("organization_units", substitution.unit_id, substitution.tenant_id, "substitution unit")
        edges = [(row["primary_personnel_id"], row["substitute_personnel_id"]) for row in self._many("SELECT primary_personnel_id, substitute_personnel_id FROM personnel_substitutions WHERE tenant_id=? AND status=?", (substitution.tenant_id, SubstitutionStatus.ACTIVE.value))]
        assert_no_directed_cycle(edges, substitution.primary_personnel_id, substitution.substitute_personnel_id, "substitution cycle")
        self.conn.execute("INSERT INTO personnel_substitutions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (substitution.id, substitution.tenant_id, substitution.primary_personnel_id, substitution.substitute_personnel_id, substitution.role_type.value, substitution.unit_id, substitution.reason, substitution.effective_from, substitution.effective_to, substitution.status.value, substitution.source_reference, substitution.created_at, substitution.updated_at)); self.conn.commit(); return substitution.id

    def list_active_substitutions(self, personnel_id: str, as_of_date: str) -> list[dict[str, Any]]:
        return self._many("SELECT * FROM personnel_substitutions WHERE primary_personnel_id=? AND status=? AND (effective_from IS NULL OR effective_from<=?) AND (effective_to IS NULL OR effective_to>=?) ORDER BY id", (personnel_id, SubstitutionStatus.ACTIVE.value, as_of_date, as_of_date))

    def add_availability(self, availability: PersonnelAvailability) -> str:
        validate_availability(availability); self._assert_tenant_row("personnel_records", availability.personnel_id, availability.tenant_id, "availability personnel")
        self._assert_no_overlap("personnel_availability", "personnel_id=?", (availability.personnel_id,), availability.unavailable_from, availability.unavailable_to, "conflicting availability interval")
        self.conn.execute("INSERT INTO personnel_availability VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (availability.id, availability.tenant_id, availability.personnel_id, availability.availability_status.value, availability.unavailable_from, availability.unavailable_to, availability.reason, availability.source_reference, availability.recorded_at, availability.created_at, availability.updated_at)); self.conn.commit(); return availability.id

    def list_availability(self, personnel_id: str) -> list[dict[str, Any]]:
        return self._many("SELECT * FROM personnel_availability WHERE personnel_id=? ORDER BY unavailable_from,id", (personnel_id,))

    def get_effective_availability(self, personnel_id: str, as_of_date: str) -> dict[str, Any]:
        row = self._one("SELECT * FROM personnel_availability WHERE personnel_id=? AND unavailable_from<=? AND (unavailable_to IS NULL OR unavailable_to>=?) ORDER BY unavailable_from DESC,id LIMIT 1", (personnel_id, as_of_date, as_of_date))
        return row or {"personnel_id": personnel_id, "availability_status": AvailabilityStatus.AVAILABLE.value}

    def append_selection_match(self, match: PersonnelSelectionMatch) -> str:
        validate_selection_match(match); self._assert_document_tenant(match.document_id, match.tenant_id); self._assert_tenant_row("organization_units", match.unit_id, match.tenant_id, "selection unit"); self._assert_tenant_row("personnel_records", match.personnel_id, match.tenant_id, "selection personnel")
        self.conn.execute("INSERT INTO personnel_selection_matches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (match.id, match.tenant_id, match.document_id, match.document_revision, match.assignment_rule_match_id, match.role_type.value, match.unit_id, match.personnel_id, match.score, match.decision.value, match.explanation, match.warnings_json, match.input_fingerprint, match.created_at)); self.conn.commit(); return match.id

    def list_selection_matches_for_document(self, document_id: str, document_revision: str) -> list[dict[str, Any]]:
        return self._many("SELECT * FROM personnel_selection_matches WHERE document_id=? AND document_revision=? ORDER BY created_at,id", (document_id, document_revision))

    def _insert_unit(self, unit: OrganizationUnit) -> None:
        self.conn.execute("INSERT INTO organization_units VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (unit.id, unit.tenant_id, unit.source_unit_key, unit.record_version, unit.unit_code, unit.unit_name, unit.normalized_name, unit.unit_type.value, unit.parent_unit_id, unit.status.value, unit.effective_from, unit.effective_to, unit.source_reference, unit.row_version, unit.created_at, unit.updated_at, unit.schema_version))

    def _insert_personnel(self, person: PersonnelRecord) -> None:
        self.conn.execute("INSERT INTO personnel_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (person.id, person.tenant_id, person.source_person_key, person.record_version, person.full_name, person.normalized_name, person.position_title, person.primary_unit_id, person.status.value, person.effective_from, person.effective_to, person.source_reference, person.row_version, person.created_at, person.updated_at, person.schema_version))

    def _validate_unit_relationship(self, unit: OrganizationUnit) -> None:
        if unit.parent_unit_id == unit.id: raise PersonnelDirectoryValidationError("unit cannot be its own parent")
        self._assert_tenant_row("organization_units", unit.parent_unit_id, unit.tenant_id, "unit parent")
        edges = [(row["id"], row["parent_unit_id"]) for row in self._many("SELECT id,parent_unit_id FROM organization_units WHERE tenant_id=? AND parent_unit_id IS NOT NULL", (unit.tenant_id,)) if row["id"] != unit.id]
        assert_no_directed_cycle(edges, unit.id, unit.parent_unit_id or "", "unit hierarchy cycle") if unit.parent_unit_id else None

    def _assert_unit_version_window(self, unit: OrganizationUnit, exclude_id: str | None = None) -> None:
        if unit.status != UnitStatus.ACTIVE: return
        self._assert_no_overlap("organization_units", "tenant_id=? AND source_unit_key=? AND status=?", (unit.tenant_id, unit.source_unit_key, UnitStatus.ACTIVE.value), unit.effective_from, unit.effective_to, "overlapping active unit versions", exclude_id)

    def _assert_personnel_version_window(self, person: PersonnelRecord, exclude_id: str | None = None) -> None:
        if person.status != PersonnelStatus.ACTIVE: return
        self._assert_no_overlap("personnel_records", "tenant_id=? AND source_person_key=? AND status=?", (person.tenant_id, person.source_person_key, PersonnelStatus.ACTIVE.value), person.effective_from, person.effective_to, "overlapping active personnel versions", exclude_id)

    def _assert_no_overlap(self, table: str, where: str, params: tuple[Any, ...], start: str | None, end: str | None, message: str, exclude_id: str | None = None) -> None:
        rows = self._many(f"SELECT id,effective_from,effective_to FROM {table} WHERE {where}" if table not in {"personnel_availability"} else f"SELECT id,unavailable_from AS effective_from,unavailable_to AS effective_to FROM {table} WHERE {where}", params)
        for row in rows:
            if row["id"] != exclude_id and date_ranges_overlap(start, end, row["effective_from"], row["effective_to"]): raise PersonnelDirectoryConflictError(message)

    def _assert_tenant_row(self, table: str, row_id: str | None, tenant_id: str, name: str) -> None:
        if row_id is None: return
        row = self._one(f"SELECT tenant_id FROM {table} WHERE id=?", (row_id,))
        if row is None or row["tenant_id"] != tenant_id: raise PersonnelDirectoryValidationError(f"{name} must belong to tenant")

    def _assert_document_tenant(self, document_id: str, tenant_id: str) -> None:
        row = self._one("SELECT tenant_id FROM documents WHERE doc_id=?", (document_id,))
        if row is None or row["tenant_id"] != tenant_id:
            raise PersonnelDirectoryValidationError("selection document must belong to tenant")

    def _list_assignments(self, table: str, personnel_id: str | None, value: str | None, as_of_date: str | None, value_column: str) -> list[dict[str, Any]]:
        sql, params = f"SELECT * FROM {table} WHERE 1=1", []
        if personnel_id: sql, params = sql + " AND personnel_id=?", params + [personnel_id]
        if value: sql, params = sql + f" AND {value_column}=?", params + [value]
        if as_of_date: sql, params = sql + " AND (effective_from IS NULL OR effective_from<=?) AND (effective_to IS NULL OR effective_to>=?)", params + [as_of_date, as_of_date]
        return self._many(sql + " ORDER BY priority DESC,id", params)

    def _one(self, sql: str, params: tuple[Any, ...] | list[Any]) -> dict[str, Any] | None:
        row = self.conn.execute(sql, params).fetchone(); return dict(row) if row else None

    def _many(self, sql: str, params: tuple[Any, ...] | list[Any]) -> list[dict[str, Any]]:
        return [dict(row) for row in self.conn.execute(sql, params).fetchall()]
