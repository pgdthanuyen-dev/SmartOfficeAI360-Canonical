import hashlib
import json
import queue
import sqlite3
import socket
import threading

import pytest

from tools.qlvb_downloader.planner_draft_handoff_v1_repository import (
    CONFLICT_ERROR_CODE,
    DATABASE_BUSY_ERROR_CODE,
    FINGERPRINT_MISMATCH_ERROR_CODE,
    IDENTITY_MISMATCH_ERROR_CODE,
    MALFORMED_PAYLOAD_ERROR_CODE,
    STORAGE_ERROR_CODE,
    TRANSACTION_STATE_ERROR_CODE,
    UNSUPPORTED_CONTRACT_ERROR_CODE,
    UNSUPPORTED_SOURCE_SYSTEM_ERROR_CODE,
    HandoffEnvelopeIntegrityError,
    PlannerDraftHandoffEnvelopeRepository,
)
from test_g06d0_planner_handoff_v1_envelope import projection


def connect(path):
    connection = sqlite3.connect(path, timeout=0.05)
    connection.execute("PRAGMA busy_timeout=200")
    return connection


def count_rows(connection):
    return connection.execute("SELECT count(*) FROM planner_draft_handoff_envelopes_v1").fetchone()[0]


class ConnectionWrapper:
    def __init__(self, connection, fail_at=None, hide_first_lookup=False):
        self.connection = connection
        self.fail_at = fail_at
        self.hide_first_lookup = hide_first_lookup
        self.hidden = False
        self.rollback_count = 0

    @property
    def in_transaction(self):
        return self.connection.in_transaction

    def execute(self, sql, parameters=()):
        statement = sql.strip().upper()
        if self.hide_first_lookup and not self.hidden and statement.startswith("SELECT * FROM PLANNER_DRAFT_HANDOFF_ENVELOPES_V1"):
            self.hidden = True
            return _EmptyCursor()
        if self.fail_at == "before_lookup" and statement.startswith("SELECT * FROM PLANNER_DRAFT_HANDOFF_ENVELOPES_V1"):
            raise RuntimeError("before lookup")
        if self.fail_at == "before_insert" and statement.startswith("INSERT INTO PLANNER_DRAFT_HANDOFF_ENVELOPES_V1"):
            raise RuntimeError("before insert")
        if self.fail_at == "integrity" and statement.startswith("INSERT INTO PLANNER_DRAFT_HANDOFF_ENVELOPES_V1"):
            raise sqlite3.IntegrityError("synthetic unique violation")
        result = self.connection.execute(sql, parameters)
        if self.fail_at == "after_insert" and statement.startswith("INSERT INTO PLANNER_DRAFT_HANDOFF_ENVELOPES_V1"):
            raise RuntimeError("after insert")
        return result

    def commit(self):
        if self.fail_at == "commit":
            raise sqlite3.OperationalError("synthetic commit failure")
        return self.connection.commit()

    def rollback(self):
        self.rollback_count += 1
        return self.connection.rollback()


class _EmptyCursor:
    def fetchone(self):
        return None


def wrapped_repo(path, **kwargs):
    connection = connect(path)
    repository = PlannerDraftHandoffEnvelopeRepository(connection)
    wrapper = ConnectionWrapper(connection, **kwargs)
    repository.conn = wrapper
    return repository, connection, wrapper


def test_create_or_get_uses_begin_immediate_and_creates_one_row(tmp_path):
    connection = connect(tmp_path / "transaction.sqlite")
    trace = []
    connection.set_trace_callback(trace.append)
    repository = PlannerDraftHandoffEnvelopeRepository(connection)
    envelope, created = repository.create_or_get_from_projection(projection())
    assert created and count_rows(connection) == 1 and any(item == "BEGIN IMMEDIATE" for item in trace)
    assert envelope.envelope_id


def test_same_key_same_fingerprint_and_conflict_preserve_immutable_row(tmp_path):
    path = tmp_path / "same-key.sqlite"
    first_connection = connect(path); first = PlannerDraftHandoffEnvelopeRepository(first_connection)
    original, created = first.create_or_get_from_projection(projection())
    second = PlannerDraftHandoffEnvelopeRepository(connect(path))
    replay, repeated = second.create_or_get_from_projection(projection())
    assert created and not repeated and (replay.envelope_id, replay.created_at) == (original.envelope_id, original.created_at)
    with pytest.raises(HandoffEnvelopeIntegrityError, match=CONFLICT_ERROR_CODE):
        second.create_or_get_from_projection(projection(subject="changed"))
    assert count_rows(first_connection) == 1
    stored = first.get_by_logical_key("tenant-a", "document-a", 2)
    assert (stored.envelope_id, stored.canonical_payload_json) == (original.envelope_id, original.canonical_payload_json)


@pytest.mark.parametrize("failure", ["before_lookup", "before_insert", "after_insert"])
def test_precommit_failures_rollback_and_connection_is_reusable(tmp_path, failure):
    repository, connection, wrapper = wrapped_repo(tmp_path / f"{failure}.sqlite", fail_at=failure)
    with pytest.raises(RuntimeError):
        repository.create_or_get_from_projection(projection())
    assert wrapper.rollback_count == 1 and count_rows(connection) == 0 and not connection.in_transaction
    repository.conn = connection
    assert repository.create_or_get_from_projection(projection())[1]


def test_commit_failure_rolls_back_and_maps_storage_error(tmp_path):
    repository, connection, wrapper = wrapped_repo(tmp_path / "commit.sqlite", fail_at="commit")
    with pytest.raises(HandoffEnvelopeIntegrityError, match=STORAGE_ERROR_CODE):
        repository.create_or_get_from_projection(projection())
    assert wrapper.rollback_count == 1 and count_rows(connection) == 0 and not connection.in_transaction
    repository.conn = connection
    assert repository.create_or_get_from_projection(projection())[1]


@pytest.mark.parametrize("conflict", [False, True])
def test_unexpected_unique_error_is_reclassified_by_exact_row_reread(tmp_path, conflict):
    path = tmp_path / f"unique-{conflict}.sqlite"
    winner_connection = connect(path); winner = PlannerDraftHandoffEnvelopeRepository(winner_connection)
    winner_envelope, _ = winner.create_or_get_from_projection(projection(subject="winner" if conflict else "subject"))
    repository, _, _ = wrapped_repo(path, fail_at="integrity", hide_first_lookup=True)
    if conflict:
        with pytest.raises(HandoffEnvelopeIntegrityError, match=CONFLICT_ERROR_CODE):
            repository.create_or_get_from_projection(projection())
    else:
        result, created = repository.create_or_get_from_projection(projection())
        assert not created and result.envelope_id == winner_envelope.envelope_id
    assert count_rows(winner_connection) == 1


def test_busy_database_is_classified_without_raw_operational_error(tmp_path):
    path = tmp_path / "locked.sqlite"
    setup = connect(path); PlannerDraftHandoffEnvelopeRepository(setup)
    repository = PlannerDraftHandoffEnvelopeRepository(connect(path))
    locker = connect(path); locker.execute("BEGIN EXCLUSIVE")
    try:
        with pytest.raises(HandoffEnvelopeIntegrityError, match=DATABASE_BUSY_ERROR_CODE):
            repository.create_or_get_from_projection(projection())
    finally:
        locker.rollback()
    assert count_rows(setup) == 0


def test_caller_transaction_is_rejected_without_interference(tmp_path):
    connection = connect(tmp_path / "caller.sqlite")
    repository = PlannerDraftHandoffEnvelopeRepository(connection)
    connection.execute("BEGIN")
    with pytest.raises(HandoffEnvelopeIntegrityError, match=TRANSACTION_STATE_ERROR_CODE):
        repository.create_or_get_from_projection(projection())
    assert connection.in_transaction and count_rows(connection) == 0
    connection.rollback()


def test_local_repository_never_calls_network(monkeypatch, tmp_path):
    monkeypatch.setattr(socket, "create_connection", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("network")))
    repository = PlannerDraftHandoffEnvelopeRepository(connect(tmp_path / "network.sqlite"))
    assert repository.create_or_get_from_projection(projection())[1]


def concurrent_connection(path):
    connection = sqlite3.connect(path, timeout=2)
    connection.execute("PRAGMA busy_timeout=2000")
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


def assert_no_duplicate_logical_keys(connection):
    duplicates = connection.execute(
        """SELECT tenant_id, source_document_id, source_draft_version
           FROM planner_draft_handoff_envelopes_v1
           GROUP BY tenant_id, source_document_id, source_draft_version HAVING COUNT(*) > 1"""
    ).fetchall()
    indexes = connection.execute("PRAGMA index_list(planner_draft_handoff_envelopes_v1)").fetchall()
    assert not duplicates and indexes


def run_workers(path, candidates):
    setup = concurrent_connection(path)
    PlannerDraftHandoffEnvelopeRepository(setup)
    setup.close()
    barrier = threading.Barrier(len(candidates))
    results, errors = queue.Queue(), queue.Queue()

    def worker(candidate):
        connection = concurrent_connection(path)
        repository = PlannerDraftHandoffEnvelopeRepository(connection)
        try:
            barrier.wait()
            envelope, created = repository.create_or_get_from_projection(candidate)
            results.put({"kind": "success", "created": created, "envelope_id": envelope.envelope_id,
                         "created_at": envelope.created_at, "payload_sha256": envelope.payload_sha256})
        except HandoffEnvelopeIntegrityError as exc:
            results.put({"kind": "domain_error", "code": str(exc)})
        except Exception as exc:
            errors.put(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(candidate,)) for candidate in candidates]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert not any(thread.is_alive() for thread in threads)
    assert errors.empty(), list(errors.queue)
    return list(results.queue)


def test_two_worker_same_payload_race_has_one_stable_winner(tmp_path):
    path = tmp_path / "two-worker.sqlite"
    results = run_workers(path, [projection(), projection()])
    assert len(results) == 2 and all(item["kind"] == "success" for item in results)
    assert sorted(item["created"] for item in results) == [False, True]
    assert len({item["envelope_id"] for item in results}) == len({item["created_at"] for item in results}) == 1
    assert len({item["payload_sha256"] for item in results}) == 1
    check = concurrent_connection(path)
    assert count_rows(check) == 1
    assert_no_duplicate_logical_keys(check)


def test_ten_worker_same_payload_race_has_nine_replays(tmp_path):
    path = tmp_path / "ten-worker.sqlite"
    results = run_workers(path, [projection() for _ in range(10)])
    assert len(results) == 10 and all(item["kind"] == "success" for item in results)
    assert sum(item["created"] for item in results) == 1 and sum(not item["created"] for item in results) == 9
    assert len({item["envelope_id"] for item in results}) == len({item["created_at"] for item in results}) == 1
    assert len({item["payload_sha256"] for item in results}) == 1
    check = concurrent_connection(path)
    assert count_rows(check) == 1
    assert_no_duplicate_logical_keys(check)


def test_conflicting_payload_race_persists_exactly_one_candidate(tmp_path):
    path = tmp_path / "conflict-race.sqlite"
    candidates = [projection(subject="candidate-a"), projection(subject="candidate-b")]
    expected_hashes = {build_hash(candidate) for candidate in candidates}
    results = run_workers(path, candidates)
    assert sum(item["kind"] == "success" and item["created"] for item in results) == 1
    assert [item["code"] for item in results if item["kind"] == "domain_error"] == [CONFLICT_ERROR_CODE]
    check = concurrent_connection(path)
    stored = PlannerDraftHandoffEnvelopeRepository(check).get_by_logical_key("tenant-a", "document-a", 2)
    assert count_rows(check) == 1 and stored.payload_sha256 in expected_hashes
    assert_no_duplicate_logical_keys(check)


def test_mixed_same_and_conflicting_workers_classify_all_results(tmp_path):
    path = tmp_path / "mixed-race.sqlite"
    a, b = projection(subject="payload-a"), projection(subject="payload-b")
    hashes = {"a": build_hash(a), "b": build_hash(b)}
    results = run_workers(path, [a, a, a, b, b, b])
    check = concurrent_connection(path)
    stored = PlannerDraftHandoffEnvelopeRepository(check).get_by_logical_key("tenant-a", "document-a", 2)
    winner = stored.payload_sha256
    assert count_rows(check) == 1 and winner in hashes.values()
    for item in results:
        if item["kind"] == "success":
            assert item["payload_sha256"] == winner
        else:
            assert item["code"] == CONFLICT_ERROR_CODE
    successes = [item for item in results if item["kind"] == "success"]
    assert len({item["envelope_id"] for item in successes}) == len({item["created_at"] for item in successes}) == 1
    assert_no_duplicate_logical_keys(check)


def build_hash(candidate):
    from tools.qlvb_downloader.planner_draft_handoff_v1_envelope import build_planner_draft_handoff_envelope_v1
    return build_planner_draft_handoff_envelope_v1(candidate).payload_sha256


def test_concurrent_multiple_versions_are_numeric_and_repeatable(tmp_path):
    path = tmp_path / "versions.sqlite"
    results = run_workers(path, [projection(version=value) for value in (1, 2, 3, 10)])
    assert all(item["kind"] == "success" and item["created"] for item in results)
    check = concurrent_connection(path); repository = PlannerDraftHandoffEnvelopeRepository(check)
    assert [item.source_draft_version for item in repository.list_versions_for_document("tenant-a", "document-a")] == [1, 2, 3, 10]
    assert [item.source_draft_version for item in repository.list_versions_for_document("tenant-a", "document-a")] == [1, 2, 3, 10]
    assert count_rows(check) == 4


def test_cross_tenant_and_cross_document_concurrent_writes_are_isolated(tmp_path):
    path = tmp_path / "scope.sqlite"
    tenant_candidates = [
        projection_for(tenant_id=f"tenant-{index}", source_document_id="document-a") for index in range(3)
    ]
    document_candidates = [
        projection_for(tenant_id="tenant-z", source_document_id=f"document-{index}") for index in range(3)
    ]
    results = run_workers(path, tenant_candidates + document_candidates)
    assert all(item["kind"] == "success" and item["created"] for item in results)
    check = concurrent_connection(path); repository = PlannerDraftHandoffEnvelopeRepository(check)
    assert count_rows(check) == 6
    for index in range(3):
        assert repository.get_by_logical_key(f"tenant-{index}", "document-a", 2) is not None
        assert repository.get_by_logical_key(f"tenant-{index}", "document-0", 2) is None
        assert repository.get_by_logical_key("tenant-z", f"document-{index}", 2) is not None
    assert_no_duplicate_logical_keys(check)


def projection_for(*, tenant_id, source_document_id, version=2, subject="subject"):
    from tools.qlvb_downloader.planner_draft_handoff_v1_projection import build_planner_draft_handoff_projection_v1
    from test_g06d0_planner_handoff_v1_projection import draft, recommendation
    return build_planner_draft_handoff_projection_v1(
        draft=draft(tenant_id=tenant_id, source_document_id=source_document_id, draft_version=version, subject=subject),
        recommendation=recommendation(tenant_id=tenant_id, source_document_id=source_document_id),
    )


def test_race_winner_is_stable_after_all_worker_connections_close(tmp_path):
    path = tmp_path / "winner-restart.sqlite"
    results = run_workers(path, [projection() for _ in range(2)])
    successful = [item for item in results if item["kind"] == "success"]
    repository = PlannerDraftHandoffEnvelopeRepository(concurrent_connection(path))
    stored = repository.get_by_logical_key("tenant-a", "document-a", 2)
    assert {(item["envelope_id"], item["created_at"], item["payload_sha256"]) for item in successful} == {
        (stored.envelope_id, stored.created_at, stored.payload_sha256)
    }


def test_restart_same_payload_conflict_and_history_are_deterministic(tmp_path):
    path = tmp_path / "restart.sqlite"
    first_connection = concurrent_connection(path); first = PlannerDraftHandoffEnvelopeRepository(first_connection)
    original, _ = first.create_or_get_from_projection(projection(version=1)); first_connection.close()
    second_connection = concurrent_connection(path); second = PlannerDraftHandoffEnvelopeRepository(second_connection)
    replay, created = second.create_or_get_from_projection(projection(version=1))
    with pytest.raises(HandoffEnvelopeIntegrityError, match=CONFLICT_ERROR_CODE):
        second.create_or_get_from_projection(projection(version=1, subject="changed"))
    second.create_or_get_from_projection(projection(version=2)); second_connection.close()
    third = PlannerDraftHandoffEnvelopeRepository(concurrent_connection(path))
    assert not created and (replay.envelope_id, replay.created_at, replay.canonical_payload_json, replay.payload_sha256) == (
        original.envelope_id, original.created_at, original.canonical_payload_json, original.payload_sha256
    )
    assert [item.source_draft_version for item in third.list_versions_for_document("tenant-a", "document-a")] == [1, 2]


def test_restart_tamper_and_malformed_payload_are_detected_without_rewrite(tmp_path):
    path = tmp_path / "tamper.sqlite"
    connection = concurrent_connection(path); repository = PlannerDraftHandoffEnvelopeRepository(connection)
    envelope, _ = repository.create_or_get_from_projection(projection()); connection.close()
    direct = concurrent_connection(path)
    direct.execute("UPDATE planner_draft_handoff_envelopes_v1 SET payload_sha256=? WHERE envelope_id=?", ("0" * 64, envelope.envelope_id)); direct.commit(); direct.close()
    reopened = PlannerDraftHandoffEnvelopeRepository(concurrent_connection(path))
    with pytest.raises(HandoffEnvelopeIntegrityError, match=FINGERPRINT_MISMATCH_ERROR_CODE):
        reopened.get_by_logical_key("tenant-a", "document-a", 2)
    direct = concurrent_connection(path)
    direct.execute("UPDATE planner_draft_handoff_envelopes_v1 SET canonical_payload_json=? WHERE envelope_id=?", ("{", envelope.envelope_id)); direct.commit(); direct.close()
    reopened = PlannerDraftHandoffEnvelopeRepository(concurrent_connection(path))
    with pytest.raises(HandoffEnvelopeIntegrityError, match=MALFORMED_PAYLOAD_ERROR_CODE):
        reopened.get_by_logical_key("tenant-a", "document-a", 2)
    assert reopened.create_or_get_from_projection(projection(version=3))[1]


@pytest.mark.parametrize(("field", "value", "error"), [
    ("tenant_id", "other", IDENTITY_MISMATCH_ERROR_CODE),
    ("source_document_id", "other", IDENTITY_MISMATCH_ERROR_CODE),
    ("source_draft_version", 99, IDENTITY_MISMATCH_ERROR_CODE),
    ("contract_version", "v2", UNSUPPORTED_CONTRACT_ERROR_CODE),
    ("source_system", "OTHER", UNSUPPORTED_SOURCE_SYSTEM_ERROR_CODE),
])
def test_restart_identity_contract_and_source_validation(field, value, error, tmp_path):
    path = tmp_path / f"restart-{field}.sqlite"
    connection = concurrent_connection(path); envelope, _ = PlannerDraftHandoffEnvelopeRepository(connection).create_or_get_from_projection(projection()); connection.close()
    direct = concurrent_connection(path)
    payload = json.loads(direct.execute("SELECT canonical_payload_json FROM planner_draft_handoff_envelopes_v1").fetchone()[0])
    payload[field] = value
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    direct.execute("UPDATE planner_draft_handoff_envelopes_v1 SET canonical_payload_json=?, payload_sha256=? WHERE envelope_id=?", (encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest(), envelope.envelope_id)); direct.commit(); direct.close()
    reopened = PlannerDraftHandoffEnvelopeRepository(concurrent_connection(path))
    with pytest.raises(HandoffEnvelopeIntegrityError, match=error):
        reopened.get_by_logical_key("tenant-a", "document-a", 2)


def test_locked_database_recovers_after_lock_release_and_reinitializes_schema(tmp_path):
    path = tmp_path / "lock-reuse.sqlite"
    setup = concurrent_connection(path); PlannerDraftHandoffEnvelopeRepository(setup)
    repository = PlannerDraftHandoffEnvelopeRepository(concurrent_connection(path))
    locker = concurrent_connection(path); locker.execute("BEGIN EXCLUSIVE")
    try:
        with pytest.raises(HandoffEnvelopeIntegrityError, match=DATABASE_BUSY_ERROR_CODE):
            repository.create_or_get_from_projection(projection())
    finally:
        locker.rollback(); locker.close()
    reopened_connection = concurrent_connection(path); reopened = PlannerDraftHandoffEnvelopeRepository(reopened_connection)
    assert reopened.create_or_get_from_projection(projection())[1]
    assert reopened.create_or_get_from_projection(projection())[1] is False
    assert reopened_connection.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='planner_draft_handoff_envelopes_v1'").fetchone()[0] == 1
    assert reopened_connection.execute("SELECT count(*) FROM schema_migrations WHERE version='g06_d0b2a_handoff_envelope_v1'").fetchone()[0] == 1


def test_concurrency_restart_and_listing_never_call_network(monkeypatch, tmp_path):
    monkeypatch.setattr(socket, "create_connection", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("network")))
    monkeypatch.setattr(socket.socket, "connect", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("network")))
    path = tmp_path / "no-network.sqlite"
    assert all(item["kind"] == "success" for item in run_workers(path, [projection(), projection()]))
    repository = PlannerDraftHandoffEnvelopeRepository(concurrent_connection(path))
    assert repository.get_by_logical_key("tenant-a", "document-a", 2) is not None
    assert [item.source_draft_version for item in repository.list_versions_for_document("tenant-a", "document-a")] == [2]


def test_regression_compatibility_preserves_legacy_boundary_and_immutable_api(tmp_path):
    from tools.qlvb_downloader.assignment_draft_planner_handoff import PlannerDraftHandoff
    from tools.qlvb_downloader.planner_draft_handoff_v1_models import PlannerDraftHandoffEnvelopeV1
    repository = PlannerDraftHandoffEnvelopeRepository(concurrent_connection(tmp_path / "compatibility.sqlite"))
    assert PlannerDraftHandoff is not PlannerDraftHandoffEnvelopeV1
    assert not ({"update", "delete", "overwrite"} & set(dir(repository)))
