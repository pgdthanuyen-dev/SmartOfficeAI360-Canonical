"""
tests/test_index_db.py — Phase 3 SQLite Index Test Suite
==========================================================
Chạy: python -m tests.test_index_db
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from tools.qlvb_downloader.index_db import (
    delete_document,
    get_document,
    init_db,
    rebuild_index_from_queue,
    search_documents,
    upsert_document,
)

_TEST_ROOT = Path("Data_index_test")
_DB_PATH = _TEST_ROOT / "index" / "test_documents.db"


def _setup():
    _TEST_ROOT.mkdir(parents=True, exist_ok=True)


def _teardown():
    if _TEST_ROOT.exists():
        shutil.rmtree(_TEST_ROOT)


def _sample_doc(
    doc_id: str = "incoming_abc123",
    direction: str = "incoming",
    doc_no: str = "123/QD-UBND",
    title: str = "Quyet dinh ve viec khen thuong",
    sync_status: str = "PENDING",
    validation_status: str = "VALID",
    confidence_score: int = 85,
) -> dict:
    return {
        "doc_id": doc_id,
        "external_doc_id": doc_id,
        "direction": direction,
        "document_number": doc_no,
        "issued_date": "2026-07-01",
        "issuing_agency": "UBND tinh",
        "summary": title,
        "downloaded_at": "2026-07-01T10:00:00",
        "status": "READY",
        "validation_status": validation_status,
        "confidence_score": confidence_score,
        "manifest_path": str(_TEST_ROOT / direction / doc_id / "manifest.json"),
        "full_text_excerpt": "Quyet dinh khen thuong...",
        "full_text_status": "OK",
        "sync": {
            "planner_kpi_status": sync_status,
            "planner_kpi_document_id": None,
            "last_sync_at": None,
            "last_error": None,
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_init_db_creates_table():
    """init_db tao bang va index thanh cong."""
    print("\n[TEST 1] init_db tao bang...")
    _setup()
    conn = init_db(_DB_PATH)
    try:
        # Kiem tra bang ton tai
        result = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='documents'"
        ).fetchone()
        assert result is not None, "Bang documents phai duoc tao"

        # Kiem tra cac index
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
        index_names = {r[0] for r in indexes}
        assert "idx_documents_sync_status" in index_names, "Index sync_status phai ton tai"
        assert "idx_documents_direction" in index_names, "Index direction phai ton tai"
        assert "idx_documents_title" in index_names, "Index title phai ton tai"
    finally:
        conn.close()
    print("  -> PASSED")


def test_upsert_and_get_document():
    """upsert roi get_document thanh cong."""
    print("\n[TEST 2] upsert + get_document...")
    _setup()
    conn = init_db(_DB_PATH)
    try:
        doc = _sample_doc()
        ok = upsert_document(conn, doc)
        assert ok is True, "upsert phai tra True"

        fetched = get_document(conn, "incoming_abc123")
        assert fetched is not None, "get_document phai tim thay ban ghi"
        assert fetched["doc_id"] == "incoming_abc123"
        assert fetched["doc_no"] == "123/QD-UBND"
        assert fetched["sync_status"] == "PENDING"
        assert fetched["confidence_score"] == 85
    finally:
        conn.close()
    print("  -> PASSED")


def test_upsert_updates_existing():
    """upsert cap nhat ban ghi da ton tai (ON CONFLICT DO UPDATE)."""
    print("\n[TEST 3] upsert cap nhat ban ghi cu...")
    _setup()
    conn = init_db(_DB_PATH)
    try:
        doc = _sample_doc()
        upsert_document(conn, doc)

        # Cap nhat sync_status
        doc["sync"]["planner_kpi_status"] = "SYNCED"
        doc["sync"]["last_sync_at"] = "2026-07-02T08:00:00"
        ok = upsert_document(conn, doc)
        assert ok is True

        fetched = get_document(conn, "incoming_abc123")
        assert fetched["sync_status"] == "SYNCED", f"sync_status phai la SYNCED, got: {fetched['sync_status']}"
    finally:
        conn.close()
    print("  -> PASSED")


def test_search_by_title():
    """search_documents tim kiem theo title."""
    print("\n[TEST 4] search theo title...")
    _setup()
    conn = init_db(_DB_PATH)
    try:
        upsert_document(conn, _sample_doc("doc_001", title="Quyet dinh ve viec khen thuong"))
        upsert_document(conn, _sample_doc("doc_002", title="Thong bao cuoc hop"))
        upsert_document(conn, _sample_doc("doc_003", title="Ke hoach dao tao 2026"))

        result = search_documents(conn, query="khen thuong")
        assert result["total"] >= 1, f"Phai tim thay >= 1 ban ghi, got: {result['total']}"
        titles = [item["title"] for item in result["items"]]
        assert any("khen thuong" in t.lower() for t in titles), f"Title phai chua 'khen thuong', got: {titles}"
    finally:
        conn.close()
    print("  -> PASSED")


def test_search_by_doc_no():
    """search_documents tim kiem theo doc_no."""
    print("\n[TEST 5] search theo doc_no...")
    _setup()
    conn = init_db(_DB_PATH)
    try:
        upsert_document(conn, _sample_doc("doc_10", doc_no="456/QD-BTC"))
        upsert_document(conn, _sample_doc("doc_11", doc_no="789/TB-UBND"))

        result = search_documents(conn, query="456/QD")
        assert result["total"] >= 1, f"Phai tim thay >= 1, got: {result['total']}"
        found_doc_no = result["items"][0]["doc_no"]
        assert "456" in found_doc_no, f"doc_no phai chua '456', got: {found_doc_no}"
    finally:
        conn.close()
    print("  -> PASSED")


def test_filter_by_sync_status():
    """search_documents filter theo sync_status."""
    print("\n[TEST 6] filter theo sync_status...")
    _setup()
    conn = init_db(_DB_PATH)
    try:
        upsert_document(conn, _sample_doc("doc_p1", sync_status="PENDING"))
        upsert_document(conn, _sample_doc("doc_p2", sync_status="PENDING"))
        upsert_document(conn, _sample_doc("doc_s1", sync_status="SYNCED"))

        result = search_documents(conn, filters={"sync_status": "PENDING"})
        assert result["total"] == 2, f"Phai co 2 PENDING, got: {result['total']}"

        result_synced = search_documents(conn, filters={"sync_status": "SYNCED"})
        assert result_synced["total"] == 1, f"Phai co 1 SYNCED, got: {result_synced['total']}"
    finally:
        conn.close()
    print("  -> PASSED")


def test_pagination():
    """search_documents phan trang dung limit va offset."""
    print("\n[TEST 7] Phan trang (limit/offset)...")
    _setup()
    conn = init_db(_DB_PATH)
    try:
        for i in range(10):
            upsert_document(conn, _sample_doc(f"doc_{i:03d}", title=f"Van ban so {i}"))

        page1 = search_documents(conn, limit=3, offset=0)
        page2 = search_documents(conn, limit=3, offset=3)

        assert len(page1["items"]) == 3, f"Trang 1 phai co 3 items, got: {len(page1['items'])}"
        assert len(page2["items"]) == 3, f"Trang 2 phai co 3 items, got: {len(page2['items'])}"
        # 2 trang phai khac nhau
        ids_1 = {i["doc_id"] for i in page1["items"]}
        ids_2 = {i["doc_id"] for i in page2["items"]}
        assert not ids_1.intersection(ids_2), "Hai trang phai khac nhau"
    finally:
        conn.close()
    print("  -> PASSED")


def test_get_nonexistent_returns_none():
    """get_document voi doc_id khong ton tai tra None."""
    print("\n[TEST 8] get_document khong ton tai tra None...")
    _setup()
    conn = init_db(_DB_PATH)
    try:
        result = get_document(conn, "nonexistent_doc_id_xyz")
        assert result is None, f"Phai tra None, got: {result}"
    finally:
        conn.close()
    print("  -> PASSED")


def test_rebuild_index_from_queue():
    """rebuild_index_from_queue doc manifest file va index vao DB."""
    print("\n[TEST 9] rebuild_index_from_queue...")
    _setup()

    # Tao thu muc queue gia lap
    queue_dir = _TEST_ROOT / "queue" / "incoming" / "incoming_test001"
    queue_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "schema_version": "2.0.0",
        "source": "QLVB",
        "direction": "incoming",
        "doc_id": "incoming_test001",
        "external_doc_id": "incoming_test001",
        "document_number": "001/QD-TEST",
        "issued_date": "2026-07-01",
        "issuing_agency": "So thu nghiem",
        "summary": "Van ban thu nghiem rebuild index",
        "downloaded_at": "2026-07-01T10:00:00",
        "status": "READY",
        "main_document": {"filename": "doc.pdf", "size_bytes": 100, "sha256": "abc"},
        "attachments": [],
        "sync": {
            "planner_kpi_status": "PENDING",
            "planner_kpi_document_id": None,
            "last_sync_at": None,
            "last_error": None,
        },
    }
    (queue_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    stats = rebuild_index_from_queue(_TEST_ROOT, db_path=_DB_PATH)

    assert stats["total"] >= 1, f"Phai index >= 1 manifest, got: {stats}"
    assert stats["indexed"] >= 1, f"Phai indexed >= 1, got: {stats}"
    assert stats["errors"] == 0, f"Khong duoc co error, got: {stats}"

    # Kiem tra ban ghi trong DB
    conn = init_db(_DB_PATH)
    try:
        fetched = get_document(conn, "incoming_test001")
        assert fetched is not None, "Ban ghi phai co trong DB sau rebuild"
        assert fetched["doc_no"] == "001/QD-TEST"
    finally:
        conn.close()

    print("  -> PASSED")


def test_rebuild_tolerates_invalid_manifest():
    """rebuild_index_from_queue khong crash khi gap manifest loi."""
    print("\n[TEST 10] rebuild chiu duoc manifest loi...")
    _setup()

    # Tao 1 manifest hop le
    good_dir = _TEST_ROOT / "queue" / "incoming" / "incoming_good"
    good_dir.mkdir(parents=True, exist_ok=True)
    (good_dir / "manifest.json").write_text(
        json.dumps({"doc_id": "incoming_good", "direction": "incoming"}),
        encoding="utf-8",
    )

    # Tao 1 manifest bi hong (JSON sai)
    bad_dir = _TEST_ROOT / "queue" / "incoming" / "incoming_bad"
    bad_dir.mkdir(parents=True, exist_ok=True)
    (bad_dir / "manifest.json").write_text("{invalid json!!!", encoding="utf-8")

    stats = rebuild_index_from_queue(_TEST_ROOT, db_path=_DB_PATH)

    # Khong crash, bao cao dung
    assert stats["total"] == 2
    assert stats["indexed"] >= 1, "Phai index duoc it nhat 1 manifest hop le"
    assert stats["errors"] >= 1, "Phai dem duoc 1 error"
    print("  -> PASSED")


def test_delete_document():
    """delete_document xoa ban ghi thanh cong."""
    print("\n[TEST 11] delete_document...")
    _setup()
    conn = init_db(_DB_PATH)
    try:
        upsert_document(conn, _sample_doc("doc_to_delete"))
        assert get_document(conn, "doc_to_delete") is not None

        ok = delete_document(conn, "doc_to_delete")
        assert ok is True
        assert get_document(conn, "doc_to_delete") is None
    finally:
        conn.close()
    print("  -> PASSED")


def test_filter_by_direction():
    """search_documents filter theo direction."""
    print("\n[TEST 12] filter theo direction...")
    _setup()
    conn = init_db(_DB_PATH)
    try:
        upsert_document(conn, _sample_doc("in_001", direction="incoming"))
        upsert_document(conn, _sample_doc("in_002", direction="incoming"))
        upsert_document(conn, _sample_doc("out_001", direction="outgoing"))

        result = search_documents(conn, filters={"direction": "incoming"})
        assert result["total"] == 2, f"Phai co 2 incoming, got: {result['total']}"

        result_out = search_documents(conn, filters={"direction": "outgoing"})
        assert result_out["total"] == 1, f"Phai co 1 outgoing, got: {result_out['total']}"
    finally:
        conn.close()
    print("  -> PASSED")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def run_tests():
    print("=" * 65)
    print(" Phase 3 — test_index_db.py")
    print("=" * 65)

    tests = [
        test_init_db_creates_table,
        test_upsert_and_get_document,
        test_upsert_updates_existing,
        test_search_by_title,
        test_search_by_doc_no,
        test_filter_by_sync_status,
        test_pagination,
        test_get_nonexistent_returns_none,
        test_rebuild_index_from_queue,
        test_rebuild_tolerates_invalid_manifest,
        test_delete_document,
        test_filter_by_direction,
    ]

    passed = 0
    failed: list[str] = []

    for fn in tests:
        _setup()
        try:
            fn()
            passed += 1
        except Exception as exc:
            import traceback
            print(f"  -> FAILED: {fn.__name__}")
            print(f"     Error: {exc}")
            traceback.print_exc()
            failed.append(fn.__name__)
        finally:
            _teardown()

    print("\n" + "=" * 65)
    print(f" Ket qua: {passed}/{len(tests)} PASSED")
    if failed:
        print(f" FAILED: {', '.join(failed)}")
    else:
        print(" ALL TESTS PASSED!")
    print("=" * 65)

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    run_tests()
