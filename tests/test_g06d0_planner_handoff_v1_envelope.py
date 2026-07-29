import json
import sqlite3
import socket
import inspect
from dataclasses import replace

import pytest

from tools.qlvb_downloader.planner_draft_handoff_v1_envelope import build_planner_draft_handoff_envelope_v1
from tools.qlvb_downloader.planner_draft_handoff_v1_projection import build_planner_draft_handoff_projection_v1
from tools.qlvb_downloader.planner_draft_handoff_v1_repository import HandoffEnvelopeIntegrityError, PlannerDraftHandoffEnvelopeRepository
from test_g06d0_planner_handoff_v1_projection import draft, recommendation


def projection(version=2, subject="subject"):
    return build_planner_draft_handoff_projection_v1(draft=draft(draft_version=version, subject=subject), recommendation=recommendation())


def test_envelope_is_canonical_immutable_and_excludes_transport_fields():
    first = build_planner_draft_handoff_envelope_v1(projection())
    second = build_planner_draft_handoff_envelope_v1(projection())
    assert first.canonical_payload_json == second.canonical_payload_json and first.payload_sha256 == second.payload_sha256
    assert len(first.payload_sha256) == 64 and "endpoint" not in first.canonical_payload_json and "secret" not in first.canonical_payload_json
    with pytest.raises(Exception): first.tenant_id = "other"


def test_create_or_get_versions_and_conflict_are_immutable():
    repo = PlannerDraftHandoffEnvelopeRepository(sqlite3.connect(":memory:"))
    first, created = repo.create_or_get_from_projection(projection())
    same, repeated = repo.create_or_get_from_projection(projection())
    assert created and not repeated and same.envelope_id == first.envelope_id and same.created_at == first.created_at
    higher, higher_created = repo.create_or_get_from_projection(projection(3))
    assert higher_created and [item.source_draft_version for item in repo.list_versions_for_document("tenant-a", "document-a")] == [2, 3]
    with pytest.raises(HandoffEnvelopeIntegrityError, match="HANDOFF_ENVELOPE_VERSION_CONFLICT"):
        repo.create_or_get_from_projection(projection(2, "changed"))
    assert repo.get_by_logical_key("tenant-b", "document-a", 2) is None and higher.source_draft_version == 3


@pytest.mark.parametrize("mutation,error", [
    (lambda row: row.update(canonical_payload_json="{"), "HANDOFF_ENVELOPE_MALFORMED_PAYLOAD"),
    (lambda row: row.update(payload_sha256="0" * 64), "HANDOFF_ENVELOPE_FINGERPRINT_MISMATCH"),
    (lambda row: row["payload"].update(tenant_id="other"), "HANDOFF_ENVELOPE_IDENTITY_MISMATCH"),
    (lambda row: row["payload"].update(source_document_id="other"), "HANDOFF_ENVELOPE_IDENTITY_MISMATCH"),
    (lambda row: row["payload"].update(source_draft_version=99), "HANDOFF_ENVELOPE_IDENTITY_MISMATCH"),
    (lambda row: row["payload"].update(source_draft_id="other"), "HANDOFF_ENVELOPE_IDENTITY_MISMATCH"),
    (lambda row: row["payload"].update(contract_version="v2"), "HANDOFF_ENVELOPE_UNSUPPORTED_CONTRACT"),
    (lambda row: row["payload"].update(source_system="OTHER"), "HANDOFF_ENVELOPE_UNSUPPORTED_SOURCE_SYSTEM"),
])
def test_read_integrity_rejects_tampered_rows_without_rewrite(mutation, error):
    repo = PlannerDraftHandoffEnvelopeRepository(sqlite3.connect(":memory:"))
    envelope, _ = repo.create_or_get_from_projection(projection())
    row = dict(repo.conn.execute("SELECT * FROM planner_draft_handoff_envelopes_v1 WHERE envelope_id=?", (envelope.envelope_id,)).fetchone())
    row["payload"] = json.loads(row["canonical_payload_json"])
    mutation(row)
    if error == "HANDOFF_ENVELOPE_MALFORMED_PAYLOAD":
        row.pop("payload")
    elif "payload" in row:
        row["canonical_payload_json"] = json.dumps(row.pop("payload"), sort_keys=True, separators=(",", ":"))
        if error != "HANDOFF_ENVELOPE_FINGERPRINT_MISMATCH":
            row["payload_sha256"] = __import__("hashlib").sha256(row["canonical_payload_json"].encode()).hexdigest()
    repo.conn.execute("UPDATE planner_draft_handoff_envelopes_v1 SET canonical_payload_json=?, payload_sha256=? WHERE envelope_id=?", (row["canonical_payload_json"], row["payload_sha256"], envelope.envelope_id))
    repo.conn.commit()
    with pytest.raises(HandoffEnvelopeIntegrityError, match=error): repo.get_by_logical_key("tenant-a", "document-a", 2)


@pytest.mark.parametrize("field", ["contract_version", "source_system", "tenant_id", "tenant_key", "source_document_id", "source_draft_id", "source_draft_version"])
def test_missing_identity_fields_are_rejected(field):
    repo = PlannerDraftHandoffEnvelopeRepository(sqlite3.connect(":memory:")); envelope, _ = repo.create_or_get_from_projection(projection())
    payload = json.loads(envelope.canonical_payload_json); payload.pop(field)
    text = json.dumps(payload, sort_keys=True, separators=(",", ":")); digest = __import__("hashlib").sha256(text.encode()).hexdigest()
    repo.conn.execute("UPDATE planner_draft_handoff_envelopes_v1 SET canonical_payload_json=?, payload_sha256=? WHERE envelope_id=?", (text, digest, envelope.envelope_id)); repo.conn.commit()
    with pytest.raises(HandoffEnvelopeIntegrityError): repo.get_by_logical_key("tenant-a", "document-a", 2)


def test_cross_document_schema_immutability_and_network_boundaries(monkeypatch):
    conn = sqlite3.connect(":memory:"); repo = PlannerDraftHandoffEnvelopeRepository(conn); PlannerDraftHandoffEnvelopeRepository(conn)
    envelope, _ = repo.create_or_get_from_projection(projection())
    assert repo.get_by_logical_key("tenant-a", "other", 2) is None
    assert [item.source_draft_version for item in repo.list_versions_for_document("tenant-a", "document-a")] == [2]
    methods = {name for name, _ in inspect.getmembers(PlannerDraftHandoffEnvelopeRepository, inspect.isfunction)}
    assert not ({"update", "delete", "overwrite"} & methods)
    monkeypatch.setattr(socket, "create_connection", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("network")))
    assert repo.get_by_logical_key("tenant-a", "document-a", 2).envelope_id == envelope.envelope_id


def test_r2b1a_03_04_contract_and_source_system_persisted():
    repo = PlannerDraftHandoffEnvelopeRepository(sqlite3.connect(":memory:")); envelope, _ = repo.create_or_get_from_projection(projection())
    payload = json.loads(envelope.canonical_payload_json); row = repo.conn.execute("SELECT contract_version, source_system FROM planner_draft_handoff_envelopes_v1").fetchone()
    assert envelope.contract_version == payload["contract_version"] == row["contract_version"] == "v1"
    assert envelope.source_system == payload["source_system"] == row["source_system"] == "SMARTOFFICE_AI360"


def test_r2b1a_06_canonical_payload_is_mapping_order_independent():
    first = build_planner_draft_handoff_envelope_v1(projection())
    reordered = build_planner_draft_handoff_projection_v1(draft=draft(), recommendation=recommendation(source_rules=("rule-a", "rule-b")))
    second = build_planner_draft_handoff_envelope_v1(reordered)
    assert first.canonical_payload_json == second.canonical_payload_json
    assert first.payload_sha256 == second.payload_sha256 and json.loads(first.canonical_payload_json) == json.loads(second.canonical_payload_json)


@pytest.mark.parametrize("changed", ["summary", "priority"])
def test_r2b1a_08_business_field_change_changes_fingerprint(changed):
    base = build_planner_draft_handoff_envelope_v1(projection())
    values = {changed: "changed-value"}
    altered = build_planner_draft_handoff_envelope_v1(build_planner_draft_handoff_projection_v1(draft=draft(**values), recommendation=recommendation()))
    assert base.canonical_payload_json != altered.canonical_payload_json and base.payload_sha256 != altered.payload_sha256
    assert all(len(value) == 64 and value == value.lower() for value in (base.payload_sha256, altered.payload_sha256))


def _names(value):
    if isinstance(value, dict):
        yield from (str(key).casefold() for key in value)
        for item in value.values(): yield from _names(item)
    elif isinstance(value, list):
        for item in value: yield from _names(item)


def test_r2b1a_09_10_transport_and_persistence_metadata_are_outside_payload():
    first = build_planner_draft_handoff_envelope_v1(projection())
    second = replace(first, envelope_id="different-id", created_at="2099-01-01T00:00:00+00:00")
    payload = json.loads(first.canonical_payload_json); names = set(_names(payload))
    prohibited = {"endpoint", "planner_url", "issuer", "secret", "authorization", "headers", "api_key", "cookie", "token", "session_url", "correlation_id", "attempt_count", "retry_state", "next_retry_at", "http_status", "database_url"}
    assert not (prohibited & names) and {"tenant_id", "source_document_id", "source_draft_version"} <= names
    assert first.canonical_payload_json == second.canonical_payload_json and first.payload_sha256 == second.payload_sha256
    assert "envelope_id" not in names and "created_at" not in names


def test_r2b1b_17_21_versions_are_immutable_and_numeric():
    repo = PlannerDraftHandoffEnvelopeRepository(sqlite3.connect(":memory:"))
    saved = {}
    for version in (3, 1, 10, 2):
            envelope, _ = repo.create_or_get_from_projection(projection(version)); saved[version] = envelope
    before = saved[1]
    after = repo.get_by_logical_key("tenant-a", "document-a", 1)
    assert (before.envelope_id, before.created_at, before.canonical_payload_json, before.payload_sha256) == (after.envelope_id, after.created_at, after.canonical_payload_json, after.payload_sha256)
    assert [item.source_draft_version for item in repo.list_versions_for_document("tenant-a", "document-a")] == [1, 2, 3, 10]
    assert len(repo.list_versions_for_document("tenant-a", "document-a")) == 4
    foreign = build_planner_draft_handoff_projection_v1(draft=draft(tenant_id="tenant-b"), recommendation=recommendation(tenant_id="tenant-b"))
    other_document = build_planner_draft_handoff_projection_v1(draft=draft(source_document_id="document-b"), recommendation=recommendation(source_document_id="document-b"))
    repo.create_or_get_from_projection(foreign); repo.create_or_get_from_projection(other_document)
    assert [item.source_draft_version for item in repo.list_versions_for_document("tenant-a", "document-a")] == [1, 2, 3, 10]


def test_r2b1b_22_schema_is_idempotent_and_unique_constraint_remains():
    conn = sqlite3.connect(":memory:"); first = PlannerDraftHandoffEnvelopeRepository(conn); PlannerDraftHandoffEnvelopeRepository(conn)
    indexes = conn.execute("PRAGMA index_list(planner_draft_handoff_envelopes_v1)").fetchall()
    migrations = conn.execute("SELECT count(*) FROM schema_migrations WHERE version='g06_d0b2a_handoff_envelope_v1'").fetchone()[0]
    first.create_or_get_from_projection(projection())
    table_count = conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='planner_draft_handoff_envelopes_v1'").fetchone()[0]
    assert indexes and migrations == 1 and table_count == 1


def test_r2b1b_28_29_full_local_path_has_no_network_or_transport_data(monkeypatch):
    def blocked(*_a, **_k): raise AssertionError("network boundary called")
    monkeypatch.setattr(socket, "create_connection", blocked); monkeypatch.setattr(socket.socket, "connect", blocked)
    repo = PlannerDraftHandoffEnvelopeRepository(sqlite3.connect(":memory:")); envelope, _ = repo.create_or_get_from_projection(projection())
    stored = repo.get_by_logical_key("tenant-a", "document-a", 2); row = dict(repo.conn.execute("SELECT * FROM planner_draft_handoff_envelopes_v1").fetchone())
    forbidden = {"endpoint", "planner_url", "issuer", "secret", "authorization", "headers", "api_key", "cookie", "token", "session_url", "correlation_id", "attempt_count", "retry_state", "next_retry_at", "http_status", "database_url"}
    assert stored.envelope_id == envelope.envelope_id and not (forbidden & {key.casefold() for key in row})
    assert not any("http" in str(value).casefold() for value in row.values()) and {"tenant_id", "source_document_id", "source_draft_version"} <= set(row)


def test_r2b1b_30_legacy_model_is_separate_and_unmodified():
    from tools.qlvb_downloader.assignment_draft_planner_handoff import PlannerDraftHandoff
    from tools.qlvb_downloader.planner_draft_handoff_v1_models import PlannerDraftHandoffEnvelopeV1
    assert PlannerDraftHandoff is not PlannerDraftHandoffEnvelopeV1
    assert "canonical_payload_json" not in PlannerDraftHandoff.__dataclass_fields__
