from __future__ import annotations

import sqlite3

import pytest

from tools.qlvb_downloader.assignment_rule_models import RuleRoleType
from tools.qlvb_downloader.domain_models import Document
from tools.qlvb_downloader.domain_repository import DomainRepository
from tools.qlvb_downloader.personnel_directory_models import (
    AvailabilityStatus,
    OrganizationUnit,
    PersonnelAvailability,
    PersonnelDomainAssignment,
    PersonnelRecord,
    PersonnelRoleAssignment,
    PersonnelSelectionDecision,
    PersonnelSelectionMatch,
    PersonnelStatus,
    PersonnelSubstitution,
    ResponsibilityLevel,
    UnitStatus,
    UnitType,
)
from tools.qlvb_downloader.personnel_directory_repository import (
    PERSONNEL_DIRECTORY_MIGRATION_VERSION,
    PersonnelDirectoryRepository,
    init_personnel_directory_schema,
)
from tools.qlvb_downloader.personnel_directory_validation import (
    PersonnelDirectoryConflictError,
    PersonnelDirectoryValidationError,
)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY, title TEXT)")
    return conn


def _repo() -> tuple[sqlite3.Connection, PersonnelDirectoryRepository]:
    conn = _connect()
    return conn, PersonnelDirectoryRepository(conn)


def _unit(tenant: str = "tenant-a", key: str = "DV_VHXH", version: int = 1, **kwargs) -> OrganizationUnit:
    return OrganizationUnit(tenant_id=tenant, source_unit_key=key, record_version=version, unit_code=key, unit_name="Phong Van hoa Xa hoi", unit_type=UnitType.PROFESSIONAL, **kwargs)


def _person(unit_id: str | None, tenant: str = "tenant-a", key: str = "VX08", version: int = 1, **kwargs) -> PersonnelRecord:
    full_name = kwargs.pop("full_name", "Nguyen Van A")
    return PersonnelRecord(tenant_id=tenant, source_person_key=key, record_version=version, full_name=full_name, primary_unit_id=unit_id, **kwargs)


def test_migration_creates_seven_tables_and_is_idempotent_without_harming_g05a():
    conn = _connect()
    try:
        init_personnel_directory_schema(conn)
        init_personnel_directory_schema(conn)
        names = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"organization_units", "personnel_records", "personnel_domain_assignments", "personnel_role_assignments", "personnel_substitutions", "personnel_availability", "personnel_selection_matches"} <= names
        assert "assignment_rules" in names
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations WHERE version=?", (PERSONNEL_DIRECTORY_MIGRATION_VERSION,)).fetchone()[0] == 1
    finally:
        conn.close()


def test_units_are_tenant_scoped_versioned_effective_and_not_name_unique():
    conn, repo = _repo()
    try:
        first = _unit(effective_from="2026-01-01", effective_to="2026-06-30")
        repo.create_unit(first)
        repo.create_unit(_unit(tenant="tenant-b"))
        with pytest.raises(PersonnelDirectoryConflictError):
            repo.create_unit(_unit())
        with pytest.raises(PersonnelDirectoryConflictError):
            repo.create_unit(_unit(version=2, effective_from="2026-06-01"))
        next_unit = _unit(version=2, effective_from="2026-07-01")
        repo.create_unit(next_unit)
        assert [u["record_version"] for u in repo.list_active_units("tenant-a", "2026-07-01")] == [2]
    finally:
        conn.close()


def test_unit_parent_requires_same_tenant_and_no_cycles_or_self_parent():
    conn, repo = _repo()
    try:
        parent = _unit(key="PARENT")
        repo.create_unit(parent)
        child = _unit(key="CHILD", parent_unit_id=parent.id)
        repo.create_unit(child)
        child.parent_unit_id = child.id
        with pytest.raises(PersonnelDirectoryValidationError): repo.update_unit(child, 1)
        parent.parent_unit_id = child.id
        with pytest.raises(PersonnelDirectoryValidationError): repo.update_unit(parent, 1)
        with pytest.raises(PersonnelDirectoryValidationError): repo.create_unit(_unit(tenant="tenant-b", key="CROSS", parent_unit_id=parent.id))
    finally:
        conn.close()


def test_personnel_versions_tenant_status_and_effective_dates():
    conn, repo = _repo()
    try:
        unit = _unit(); repo.create_unit(unit)
        active = _person(unit.id, effective_from="2026-01-01", effective_to="2026-06-30")
        repo.create_personnel(active)
        repo.create_personnel(_person(unit.id, version=2, effective_from="2026-07-01"))
        repo.create_personnel(_person(unit.id, key="OLD", status=PersonnelStatus.TRANSFERRED))
        assert [p["record_version"] for p in repo.list_active_personnel("tenant-a", "2026-07-01")] == [2]
        with pytest.raises(PersonnelDirectoryValidationError): repo.create_personnel(_person(unit.id, tenant="tenant-b"))
        with pytest.raises(PersonnelDirectoryValidationError): repo.create_personnel(_person(unit.id, key="PLACEHOLDER", full_name="[Can cap nhat nhan su]"))
    finally:
        conn.close()


def test_domain_and_role_assignments_validate_dates_duplicates_and_all_g05a_roles():
    conn, repo = _repo()
    try:
        unit = _unit(); repo.create_unit(unit)
        person = _person(unit.id); repo.create_personnel(person)
        domain = PersonnelDomainAssignment(tenant_id="tenant-a", personnel_id=person.id, domain_code="LV019", responsibility_level=ResponsibilityLevel.PRIMARY, priority=10)
        repo.add_domain_assignment(domain)
        with pytest.raises(PersonnelDirectoryConflictError): repo.add_domain_assignment(domain)
        assert repo.list_personnel_by_domain("tenant-a", "LV019", "2026-07-19")[0]["id"] == person.id
        for role_type in RuleRoleType:
            repo.add_role_assignment(PersonnelRoleAssignment(tenant_id="tenant-a", personnel_id=person.id, unit_id=unit.id, role_type=role_type, role_code=f"R-{role_type.value}"))
        assert len(repo.list_role_assignments(personnel_id=person.id)) == 4
        duplicate = PersonnelRoleAssignment(tenant_id="tenant-a", personnel_id=person.id, unit_id=unit.id, role_type=RuleRoleType.LEADER, role_code="R-LEADER")
        with pytest.raises(PersonnelDirectoryConflictError): repo.add_role_assignment(duplicate)
    finally:
        conn.close()


def test_substitution_cycle_and_availability_intervals_are_rejected():
    conn, repo = _repo()
    try:
        unit = _unit(); repo.create_unit(unit)
        first, second = _person(unit.id), _person(unit.id, key="VX09")
        repo.create_personnel(first); repo.create_personnel(second)
        repo.add_substitution(PersonnelSubstitution(tenant_id="tenant-a", primary_personnel_id=first.id, substitute_personnel_id=second.id, role_type=RuleRoleType.LEAD_EXECUTOR))
        with pytest.raises(PersonnelDirectoryValidationError): repo.add_substitution(PersonnelSubstitution(tenant_id="tenant-a", primary_personnel_id=second.id, substitute_personnel_id=first.id, role_type=RuleRoleType.LEAD_EXECUTOR))
        leave = PersonnelAvailability(tenant_id="tenant-a", personnel_id=first.id, availability_status=AvailabilityStatus.LEAVE, unavailable_from="2026-07-01", unavailable_to="2026-07-10", reason="Leave")
        repo.add_availability(leave)
        assert repo.get_effective_availability(first.id, "2026-07-05")["availability_status"] == "LEAVE"
        with pytest.raises(PersonnelDirectoryConflictError): repo.add_availability(PersonnelAvailability(tenant_id="tenant-a", personnel_id=first.id, availability_status=AvailabilityStatus.UNAVAILABLE, unavailable_from="2026-07-05"))
        assert repo.get_effective_availability(second.id, "2026-07-05")["availability_status"] == "AVAILABLE"
    finally:
        conn.close()


def test_bundle_transaction_rolls_back_and_stale_updates_conflict():
    conn, repo = _repo()
    try:
        unit = _unit(); repo.create_unit(unit)
        person = _person(unit.id)
        broken = PersonnelDomainAssignment(tenant_id="tenant-a", personnel_id="missing", domain_code="LV019", responsibility_level=ResponsibilityLevel.PRIMARY)
        with pytest.raises(PersonnelDirectoryValidationError): repo.create_personnel(person, domains=[broken])
        assert repo.get_personnel(person.id) is None
        repo.create_personnel(person)
        assert repo.update_personnel(person, 1) == 2
        with pytest.raises(PersonnelDirectoryConflictError): repo.update_personnel(person, 1)
    finally:
        conn.close()


def test_selection_history_is_append_only_bounded_and_tenant_safe():
    conn, repo = _repo()
    try:
        unit = _unit(); repo.create_unit(unit)
        person = _person(unit.id); repo.create_personnel(person)
        document = Document(tenant_id="tenant-a", source_system="fake", source_document_id="doc-1")
        DomainRepository(conn).save_document(document)
        match = PersonnelSelectionMatch(tenant_id="tenant-a", document_id=document.id, document_revision="1", role_type=RuleRoleType.LEAD_EXECUTOR, unit_id=unit.id, personnel_id=person.id, score=80, decision=PersonnelSelectionDecision.SELECTED, input_fingerprint="a" * 64)
        repo.append_selection_match(match)
        assert len(repo.list_selection_matches_for_document(document.id, "1")) == 1
        with pytest.raises(PersonnelDirectoryValidationError): repo.append_selection_match(PersonnelSelectionMatch(tenant_id="tenant-a", document_id=document.id, document_revision="1", role_type=RuleRoleType.LEAD_EXECUTOR, score=101, decision=PersonnelSelectionDecision.SELECTED, input_fingerprint="bad"))
        assert not any("planner" in column[1].lower() or "sharepoint" in column[1].lower() for table in ("personnel_records", "personnel_role_assignments") for column in conn.execute(f"PRAGMA table_info({table})"))
    finally:
        conn.close()
