"""
tests/test_sync_auth_failed.py — QC-001 Hotfix Test Suite
=========================================================
Kiểm tra kịch bản Short-circuit của sync_batch khi nhận được mã lỗi HTTP 401/403
(AUTH_FAILED).

Chạy: python -m tests.test_sync_auth_failed
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Đảm bảo stdout UTF-8 trên Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from tools.qlvb_downloader.config import QLVBConfig
from tools.qlvb_downloader.sync_client import sync_batch, sync_upload

# ---------------------------------------------------------------------------
# Mock paths
# ---------------------------------------------------------------------------
_MOCK_POST = "tools.qlvb_downloader.sync_client.requests.post"
_MOCK_GET = "tools.qlvb_downloader.sync_client.requests.get"
_MOCK_SLEEP = "tools.qlvb_downloader.sync_client.time.sleep"

_TEST_ROOT = Path("Data_auth_test")

def _make_cfg(data_root: Path) -> QLVBConfig:
    return QLVBConfig(
        save_root=str(data_root),
        planner_api_url="http://mock-planner.local",
        planner_ingest_token="expired_token",
    )

def _make_queue(data_root: Path, doc_id: str) -> tuple[Path, Path]:
    queue_dir = data_root / "queue" / "incoming" / doc_id
    queue_dir.mkdir(parents=True, exist_ok=True)
    (queue_dir / "doc.pdf").write_bytes(b"fake_pdf_content")
    manifest = {
        "schema_version": "2.0.0",
        "direction": "incoming",
        "doc_id": doc_id,
        "main_document": {"filename": "doc.pdf"},
        "sync": {"planner_kpi_status": "PENDING"}
    }
    manifest_path = queue_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return queue_dir, manifest_path

def _read_sync(manifest_path: Path) -> dict:
    return json.loads(manifest_path.read_text(encoding="utf-8")).get("sync", {})

def _auth_fail_response(status_code: int = 401) -> MagicMock:
    r = MagicMock()
    r.ok = False
    r.status_code = status_code
    r.text = "Unauthorized"
    r.json.return_value = {"message": "Invalid token"}
    return r

def _ok_post_response(doc_id: str = "srv-ok") -> MagicMock:
    r = MagicMock()
    r.ok = True
    r.status_code = 200
    r.json.return_value = {"success": True, "document_id": doc_id}
    return r

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_sync_upload_auth_failed():
    print("\n[TEST 1] sync_upload nhận HTTP 401 trả False và ghi AUTH_FAILED...")
    data_root = _TEST_ROOT / "t1"
    _, manifest_path = _make_queue(data_root, "doc_auth_1")
    cfg = _make_cfg(data_root)

    with patch(_MOCK_POST, return_value=_auth_fail_response(401)), \
         patch(_MOCK_SLEEP):
        ok = sync_upload(cfg, "incoming", "doc_auth_1", max_retries=3, enable_polling=False)

    assert ok is False
    sync_info = _read_sync(manifest_path)
    assert sync_info["planner_kpi_status"] == "FAILED"
    assert "AUTH_FAILED HTTP 401" in sync_info["last_error"], f"Lỗi phải chứa AUTH_FAILED, nhận {sync_info['last_error']}"
    print("  -> PASSED")

def test_sync_batch_short_circuit_on_401():
    print("\n[TEST 2] sync_batch gặp HTTP 401 ở file đầu tiên, skip toàn bộ file sau...")
    data_root = _TEST_ROOT / "t2"
    cfg = _make_cfg(data_root)
    
    doc_ids = ["doc_1", "doc_2", "doc_3"]
    for did in doc_ids:
        _make_queue(data_root, did)

    call_count = 0
    def post_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return _auth_fail_response(401)  # Luôn trả 401

    progress_calls = []
    def on_progress(done, total, doc_id, result):
        progress_calls.append(result)

    with patch(_MOCK_POST, side_effect=post_side_effect), \
         patch(_MOCK_SLEEP):
        summary = sync_batch(cfg, "incoming", doc_ids, on_progress=on_progress, enable_polling=False)

    assert summary["total"] == 3
    assert summary["success"] == 0
    assert summary["failed"] == 1, "Chỉ 1 file bị failed (file gọi API bị 401)"
    assert summary["skipped"] == 2, "2 file còn lại phải bị skipped"
    assert summary["auth_failed"] is True, "Cờ auth_failed phải là True"
    assert "Token hết hạn" in summary["message"]
    
    assert call_count == 1, f"Chỉ được gọi API 1 lần duy nhất, gọi {call_count}"
    
    assert len(progress_calls) == 3
    assert progress_calls[0]["ok"] is False and "AUTH_FAILED" in progress_calls[0]["error"]
    assert progress_calls[1]["skipped"] is True and progress_calls[1]["error"] == "SKIPPED_AUTH_FAILED"
    assert progress_calls[2]["skipped"] is True and progress_calls[2]["error"] == "SKIPPED_AUTH_FAILED"
    print("  -> PASSED")

def test_sync_batch_short_circuit_in_middle():
    print("\n[TEST 3] sync_batch gặp HTTP 403 ở giữa danh sách, chỉ skip từ đó trở đi...")
    data_root = _TEST_ROOT / "t3"
    cfg = _make_cfg(data_root)
    
    doc_ids = ["doc_1", "doc_2", "doc_3", "doc_4"]
    for did in doc_ids:
        _make_queue(data_root, did)

    call_count = 0
    def post_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _ok_post_response() # File 1 OK
        else:
            return _auth_fail_response(403) # File 2 bị 403

    progress_calls = []
    def on_progress(done, total, doc_id, result):
        progress_calls.append(result)

    with patch(_MOCK_POST, side_effect=post_side_effect), \
         patch(_MOCK_GET, return_value=MagicMock(ok=True, status_code=200, json=lambda: {"status": "PROCESSED"})), \
         patch(_MOCK_SLEEP):
        summary = sync_batch(cfg, "incoming", doc_ids, on_progress=on_progress, enable_polling=True)

    assert call_count == 2, "Chỉ gọi API cho file 1 và file 2"
    assert summary["success"] == 1
    assert summary["failed"] == 1
    assert summary["skipped"] == 2
    assert summary["auth_failed"] is True
    
    assert len(progress_calls) == 4
    assert progress_calls[0]["ok"] is True
    assert progress_calls[1]["ok"] is False and "AUTH_FAILED HTTP 403" in progress_calls[1]["error"]
    assert progress_calls[2]["skipped"] is True
    assert progress_calls[3]["skipped"] is True
    print("  -> PASSED")

def run_tests():
    print("=" * 65)
    print(" QC-001 HOTFIX TEST SUITE (AUTH_FAILED Short-circuit)")
    print("=" * 65)
    if _TEST_ROOT.exists():
        shutil.rmtree(_TEST_ROOT)

    tests = [
        test_sync_upload_auth_failed,
        test_sync_batch_short_circuit_on_401,
        test_sync_batch_short_circuit_in_middle,
    ]

    passed = 0
    failed_names = []

    for test_fn in tests:
        if _TEST_ROOT.exists():
            shutil.rmtree(_TEST_ROOT)
        _TEST_ROOT.mkdir(parents=True, exist_ok=True)
        try:
            test_fn()
            passed += 1
        except Exception as exc:
            name = test_fn.__name__
            import traceback
            print(f"  -> FAILED: {name}")
            traceback.print_exc()
            failed_names.append(name)

    if _TEST_ROOT.exists():
        shutil.rmtree(_TEST_ROOT)

    print("\n" + "=" * 65)
    print(f" Kết quả: {passed}/{len(tests)} PASSED")
    if failed_names:
        print(f" FAILED: {', '.join(failed_names)}")
        sys.exit(1)
    else:
        print(" ALL HOTFIX TESTS PASSED SUCCESSFULLY!")
    print("=" * 65)

if __name__ == "__main__":
    run_tests()
