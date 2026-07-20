from __future__ import annotations

import sqlite3

import pytest

from tools.qlvb_downloader.assignment_draft_repository import (
    ASSIGNMENT_DRAFT_MVP_MIGRATION_VERSION,
    _CREATE_TABLES_SQL,
    init_assignment_draft_schema,
)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY, title TEXT)")
    return conn


def _draft_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "id": "draft-1",
        "tenant_id": "tenant-a",
        "source_system": "canonical",
        "source_document_id": "source-1",
        "source_revision": "1",
        "source_identity_key": "tenant-a|canonical|source-1",
        "draft_version": 1,
        "initial_status": "PENDING_OFFICE_REVIEW",
        "task_title": "Prepare report",
        "task_description": "Prepare the requested report.",
        "lead_unit_source_key": "UNIT-1",
        "proposed_start_date": None,
        "proposed_due_date": None,
        "priority": "NORMAL",
        "overall_confidence": 80.0,
        "source_input_fingerprint": "a" * 64,
        "draft_content_fingerprint": "b" * 64,
        "supersedes_draft_id": None,
        "created_at": "2026-07-20T00:00:00+00:00",
        "created_by_system": "g05c-test",
        "schema_version": "1.0.0",
        "builder_version": "not-built",
    }
    values.update(overrides)
    return values


def _insert_draft(conn: sqlite3.Connection, **overrides: object) -> None:
    values = _draft_values(**overrides)
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    conn.execute(
        f"INSERT INTO assignment_drafts ({columns}) VALUES ({placeholders})",
        tuple(values.values()),
    )


def _insert_personnel(conn: sqlite3.Connection, **overrides: object) -> None:
    values: dict[str, object] = {
        "id": "personnel-1",
        "draft_id": "draft-1",
        "tenant_id": "tenant-a",
        "personnel_source_key": "PERSON-1",
        "role_type": "LEAD_EXECUTOR",
        "proposal_source": "G05B",
        "is_substitute": 0,
        "confidence": 75.0,
        "item_order": 0,
        "created_at": "2026-07-20T00:00:00+00:00",
    }
    values.update(overrides)
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    conn.execute(
        f"INSERT INTO assignment_draft_personnel ({columns}) VALUES ({placeholders})",
        tuple(values.values()),
    )


def test_migration_is_additive_and_idempotent() -> None:
    conn = _connect()
    try:
        init_assignment_draft_schema(conn)
        init_assignment_draft_schema(conn)
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM schema_migrations WHERE version = ?",
            (ASSIGNMENT_DRAFT_MVP_MIGRATION_VERSION,),
        ).fetchone()
        assert row["count"] == 1
        assert conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='assignment_rules'").fetchone()
        assert conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='personnel_records'").fetchone()
    finally:
        conn.close()


def test_core_tables_columns_and_foreign_keys_exist() -> None:
    conn = _connect()
    try:
        init_assignment_draft_schema(conn)
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        parent_columns = {row["name"] for row in conn.execute("PRAGMA table_info(assignment_drafts)")}
        assert {
            "source_revision",
            "source_input_fingerprint",
            "draft_content_fingerprint",
            "participating_units_json",
            "source_engine_versions_json",
        } <= parent_columns
        child_columns = {row["name"] for row in conn.execute("PRAGMA table_info(assignment_draft_personnel)")}
        assert {
            "draft_id",
            "tenant_id",
            "personnel_source_key",
            "role_type",
            "proposal_source",
            "is_substitute",
            "confidence",
            "item_order",
        } <= child_columns
        assert conn.execute("PRAGMA foreign_key_list(assignment_draft_personnel)").fetchone()["table"] == "assignment_drafts"
    finally:
        conn.close()


def test_personnel_requires_existing_draft() -> None:
    conn = _connect()
    try:
        init_assignment_draft_schema(conn)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_personnel(conn)
    finally:
        conn.close()


def test_source_version_unique_but_tenants_are_isolated() -> None:
    conn = _connect()
    try:
        init_assignment_draft_schema(conn)
        _insert_draft(conn)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_draft(conn, id="draft-duplicate")
        _insert_draft(
            conn,
            id="draft-tenant-b",
            tenant_id="tenant-b",
            source_identity_key="tenant-b|canonical|source-1",
        )
        assert conn.execute("SELECT COUNT(*) FROM assignment_drafts").fetchone()[0] == 2
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("draft_version", 0),
        ("initial_status", "APPROVED_FOR_PLANNER"),
        ("priority", "INVALID"),
        ("overall_confidence", 100.01),
        ("source_input_fingerprint", "not-a-sha"),
        ("draft_content_fingerprint", "A" * 64),
        ("source_revision", ""),
    ],
)
def test_parent_constraints_are_enforced(field: str, value: object) -> None:
    conn = _connect()
    try:
        init_assignment_draft_schema(conn)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_draft(conn, **{field: value})
    finally:
        conn.close()


def test_canonical_bounded_json_is_checked() -> None:
    conn = _connect()
    try:
        init_assignment_draft_schema(conn)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_draft(conn, participating_units_json="{")
        with pytest.raises(sqlite3.IntegrityError):
            _insert_draft(conn, warnings_json="x" * 16001)
    finally:
        conn.close()


def test_personnel_constraints_are_enforced() -> None:
    conn = _connect()
    try:
        init_assignment_draft_schema(conn)
        _insert_draft(conn)
        for field, value in (("item_order", -1), ("role_type", "INVALID"), ("confidence", -0.01)):
            with pytest.raises(sqlite3.IntegrityError):
                _insert_personnel(conn, **{field: value})
    finally:
        conn.close()


def test_supersedes_cannot_self_reference() -> None:
    conn = _connect()
    try:
        init_assignment_draft_schema(conn)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_draft(conn, supersedes_draft_id="draft-1")
    finally:
        conn.close()


def test_no_external_identity_or_binary_columns() -> None:
    conn = _connect()
    try:
        init_assignment_draft_schema(conn)
        columns = {
            row["name"].lower()
            for table in ("assignment_drafts", "assignment_draft_personnel")
            for row in conn.execute(f"PRAGMA table_info({table})")
        }
        forbidden = ("planner", "sharepoint", "microsoft", "token", "binary", "base64", "blob", "email")
        assert not any(term in column for term in forbidden for column in columns)
    finally:
        conn.close()


def test_migration_sql_is_non_destructive() -> None:
    sql = "\n".join(_CREATE_TABLES_SQL).upper()
    assert "DROP " not in sql
    assert "DELETE FROM " not in sql
