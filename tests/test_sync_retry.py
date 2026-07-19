"""
tests/test_sync_retry.py — Phase 1 Test Suite
===============================================
Kiểm tra các tình huống retry, idempotency, batch sync và polling
của sync_client.py đã được nâng cấp trong Phase 1.

Chạy: python -m tests.test_sync_retry
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any
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
# Đường dẫn mock đúng — module import requests trực tiếp
# ---------------------------------------------------------------------------
_MOCK_POST = "tools.qlvb_downloader.sync_client.requests.post"
_MOCK_GET = "tools.qlvb_downloader.sync_client.requests.get"
_MOCK_SLEEP = "tools.qlvb_downloader.sync_client.time.sleep"

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------
_TEST_ROOT = Path("Data_sync_retry_test")


def _make_cfg(data_root: Path) -> QLVBConfig:
    return QLVBConfig(
        save_root=str(data_root),
        planner_api_url="http://mock-planner.local",
        planner_ingest_token="mock_secret_token",
    )


def _make_queue(
    data_root: Path,
    direction: str = "incoming",
    doc_id: str = "test_doc_retry",
    extra_attachments: bool = False,
) -> tuple[Path, Path]:
    """Tạo thư mục queue giả lập với manifest.json và file giả."""
    queue_dir = data_root / "queue" / direction / doc_id
    queue_dir.mkdir(parents=True, exist_ok=True)

    (queue_dir / "doc.pdf").write_bytes(b"fake_pdf_content")

    attachments_meta: list[dict[str, Any]] = []
    if extra_attachments:
        (queue_dir / "attach.xlsx").write_bytes(b"fake_excel_content")
        attachments_meta.append(
            {
                "filename": "attach.xlsx",
                "size_bytes": 18,
                "sha256": "fakehash2",
                "relative_path": "attach.xlsx",
            }
        )

    manifest = {
        "schema_version": "2.0.0",
        "source": "QLVB",
        "direction": direction,
        "doc_id": doc_id,
        "external_doc_id": doc_id,
        "document_number": "100/QD/TEST",
        "issued_date": "2026-07-10",
        "issuing_agency": "Don vi Test",
        "summary": "Van ban kiem tra retry",
        "downloaded_at": "2026-07-10T07:00:00",
        "main_document": {
            "filename": "doc.pdf",
            "size_bytes": 16,
            "sha256": "fakehash1",
            "relative_path": "doc.pdf",
        },
        "attachments": attachments_meta,
        "sync": {
            "planner_kpi_status": "PENDING",
            "planner_kpi_document_id": None,
            "last_sync_at": None,
            "last_error": None,
        },
    }
    manifest_path = queue_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return queue_dir, manifest_path


def _read_sync(manifest_path: Path) -> dict:
    return json.loads(manifest_path.read_text(encoding="utf-8")).get("sync", {})


def _ok_post_response(doc_id: str = "server-12345") -> MagicMock:
    """Mock HTTP 200 OK từ endpoint upload."""
    r = MagicMock()
    r.ok = True
    r.status_code = 200
    r.json.return_value = {"success": True, "document_id": doc_id}
    return r


def _ok_poll_response(status: str = "PROCESSED") -> MagicMock:
    """Mock HTTP 200 OK từ endpoint polling với trạng thái xử lý xong."""
    r = MagicMock()
    r.ok = True
    r.status_code = 200
    r.json.return_value = {"status": status, "ingest_status": status}
    return r


def _fail_response(status_code: int, message: str = "Error") -> MagicMock:
    r = MagicMock()
    r.ok = False
    r.status_code = status_code
    r.text = message
    r.json.return_value = {"message": message}
    return r


def _no_poll():
    """Context manager mock GET trả 404 để bỏ qua polling trong test không cần poll."""
    r = MagicMock()
    r.ok = False
    r.status_code = 404
    return r


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_success_on_first_attempt():
    """Trường hợp thành công ngay lần đầu."""
    print("\n[TEST 1] Upload thành công lần 1...")
    data_root = _TEST_ROOT / "t1"
    _, manifest_path = _make_queue(data_root)
    cfg = _make_cfg(data_root)

    # Mock cả POST (upload) và GET (poll) để tránh kết nối thực
    with patch(_MOCK_POST, return_value=_ok_post_response("srv-001")) as mock_post, \
         patch(_MOCK_GET, return_value=_ok_poll_response()):
        ok = sync_upload(cfg, "incoming", "test_doc_retry", max_retries=3,
                         enable_polling=True, poll_timeout=2.0, poll_interval=0.1)

    assert ok is True, "Phải trả True khi HTTP 200"
    assert mock_post.call_count == 1, f"Phải gọi POST 1 lần, gọi {mock_post.call_count}"
    sync_info = _read_sync(manifest_path)
    assert sync_info["planner_kpi_status"] == "SYNCED"
    assert sync_info["planner_kpi_document_id"] == "srv-001"
    assert sync_info["last_error"] is None
    print("  -> PASSED")


def test_retry_on_timeout_then_success():
    """Timeout lần 1, thành công lần 2."""
    print("\n[TEST 2] Timeout lần 1, thành công lần 2...")
    data_root = _TEST_ROOT / "t2"
    _, manifest_path = _make_queue(data_root)
    cfg = _make_cfg(data_root)

    from requests.exceptions import Timeout

    call_count = 0

    def post_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Timeout("Connection timed out")
        return _ok_post_response("srv-002")

    with patch(_MOCK_POST, side_effect=post_side_effect), \
         patch(_MOCK_GET, return_value=_ok_poll_response()), \
         patch(_MOCK_SLEEP):  # Bỏ qua thời gian chờ backoff
        ok = sync_upload(cfg, "incoming", "test_doc_retry", max_retries=3,
                         retry_backoff_base=0.01, enable_polling=True,
                         poll_timeout=2.0, poll_interval=0.1)

    assert ok is True, "Phải thành công sau khi retry"
    assert call_count == 2, f"Phải gọi POST 2 lần, gọi {call_count}"
    sync_info = _read_sync(manifest_path)
    assert sync_info["planner_kpi_status"] == "SYNCED"
    print("  -> PASSED")


def test_http_500_retries_exhausted():
    """HTTP 500 retry hết lần — ghi RETRYABLE_FAILED."""
    print("\n[TEST 3] HTTP 500 retry đến cạn, ghi RETRYABLE_FAILED...")
    data_root = _TEST_ROOT / "t3"
    _, manifest_path = _make_queue(data_root)
    cfg = _make_cfg(data_root)

    with patch(_MOCK_POST, return_value=_fail_response(500, "Internal Server Error")), \
         patch(_MOCK_SLEEP):
        ok = sync_upload(cfg, "incoming", "test_doc_retry", max_retries=3,
                         retry_backoff_base=0.01, enable_polling=False)

    assert ok is False
    sync_info = _read_sync(manifest_path)
    assert sync_info["planner_kpi_status"] == "RETRYABLE_FAILED", \
        f"Expected RETRYABLE_FAILED, got {sync_info['planner_kpi_status']}"
    assert "HTTP 500" in (sync_info.get("last_error") or "")
    print("  -> PASSED")


def test_http_400_no_retry():
    """HTTP 400 không retry — ghi FAILED ngay lần đầu."""
    print("\n[TEST 4] HTTP 400 không retry...")
    data_root = _TEST_ROOT / "t4"
    _, manifest_path = _make_queue(data_root)
    cfg = _make_cfg(data_root)

    call_count = 0

    def post_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return _fail_response(400, "Bad Request: missing field")

    with patch(_MOCK_POST, side_effect=post_side_effect):
        ok = sync_upload(cfg, "incoming", "test_doc_retry", max_retries=3,
                         enable_polling=False)

    assert ok is False
    assert call_count == 1, \
        f"HTTP 4xx không được retry — phải gọi 1 lần, gọi {call_count}"
    sync_info = _read_sync(manifest_path)
    assert sync_info["planner_kpi_status"] == "FAILED", \
        f"Expected FAILED, got {sync_info['planner_kpi_status']}"
    assert "HTTP 400" in (sync_info.get("last_error") or "")
    print("  -> PASSED")


def test_idempotency_key_in_header():
    """X-Idempotency-Key phải được gửi trong header với giá trị đúng."""
    print("\n[TEST 5] X-Idempotency-Key trong header...")
    data_root = _TEST_ROOT / "t5"
    doc_id = "test_doc_retry"
    _, manifest_path = _make_queue(data_root, doc_id=doc_id)
    cfg = _make_cfg(data_root)

    captured_headers: dict = {}

    def post_side_effect(*args, **kwargs):
        captured_headers.update(kwargs.get("headers", {}))
        return _ok_post_response()

    with patch(_MOCK_POST, side_effect=post_side_effect), \
         patch(_MOCK_GET, return_value=_ok_poll_response()), \
         patch(_MOCK_SLEEP):
        sync_upload(cfg, "incoming", doc_id, max_retries=1,
                    enable_polling=True, poll_timeout=2.0, poll_interval=0.1)

    assert "X-Idempotency-Key" in captured_headers, \
        "Header X-Idempotency-Key phải được gửi"
    assert captured_headers["X-Idempotency-Key"] == doc_id, \
        f"Idempotency key phải là doc_id='{doc_id}', nhận: {captured_headers['X-Idempotency-Key']}"
    print("  -> PASSED")


def test_no_manifest_returns_false():
    """Không có manifest.json thì trả False ngay, không crash."""
    print("\n[TEST 6] Không có manifest.json trả False...")
    data_root = _TEST_ROOT / "t6"
    data_root.mkdir(parents=True, exist_ok=True)
    cfg = _make_cfg(data_root)

    with patch(_MOCK_POST) as mock_post:
        ok = sync_upload(cfg, "incoming", "nonexistent_doc", max_retries=3)

    assert ok is False
    mock_post.assert_not_called()
    print("  -> PASSED")


def test_syncing_not_stuck_after_failure():
    """SYNCING phải được xóa sau thất bại — manifest không bị kẹt."""
    print("\n[TEST 7] Không kẹt trạng thái SYNCING sau thất bại...")
    data_root = _TEST_ROOT / "t7"
    _, manifest_path = _make_queue(data_root)
    cfg = _make_cfg(data_root)

    from requests.exceptions import ConnectionError as ReqConnError

    with patch(_MOCK_POST, side_effect=ReqConnError("Network unreachable")), \
         patch(_MOCK_SLEEP):
        ok = sync_upload(cfg, "incoming", "test_doc_retry", max_retries=2,
                         retry_backoff_base=0.01, enable_polling=False)

    assert ok is False
    sync_info = _read_sync(manifest_path)
    assert sync_info["planner_kpi_status"] != "SYNCING", \
        f"Manifest không được ở SYNCING sau thất bại, nhận: {sync_info['planner_kpi_status']}"
    print("  -> PASSED")


def test_sync_batch_continues_on_one_failure():
    """sync_batch không dừng khi 1 tài liệu lỗi — tiếp tục các tài liệu còn lại."""
    print("\n[TEST 8] sync_batch tiếp tục khi 1 tài liệu lỗi...")
    data_root = _TEST_ROOT / "t8"
    cfg = _make_cfg(data_root)

    doc_ids = []
    for i in range(3):
        did = f"doc_{i}"
        _make_queue(data_root, doc_id=did)
        doc_ids.append(did)

    call_count = 0

    def post_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            # Tài liệu thứ 2 lỗi HTTP 400 — không retry
            return _fail_response(400, "Bad field")
        return _ok_post_response(f"srv-{call_count}")

    progress_calls: list[tuple] = []

    def on_progress(done, total, doc_id, result):
        progress_calls.append((done, total, doc_id, result["ok"]))

    with patch(_MOCK_POST, side_effect=post_side_effect), \
         patch(_MOCK_GET, return_value=_ok_poll_response()), \
         patch(_MOCK_SLEEP):
        summary = sync_batch(
            cfg, "incoming", doc_ids, on_progress=on_progress,
            enable_polling=True, poll_timeout=2.0, poll_interval=0.1
        )

    assert summary["total"] == 3
    assert summary["success"] == 2, f"Phải có 2 thành công, nhận {summary['success']}"
    assert summary["failed"] == 1, f"Phải có 1 thất bại, nhận {summary['failed']}"
    assert summary["skipped"] == 0
    assert len(summary["results"]) == 3

    # Callback phải được gọi đúng 3 lần
    assert len(progress_calls) == 3, \
        f"on_progress phải được gọi 3 lần, gọi {len(progress_calls)}"
    # Lần 2 phải là False (lỗi 400)
    assert progress_calls[1][3] is False, "Tài liệu thứ 2 phải báo failed"
    print("  -> PASSED")


def test_sync_batch_skip_missing_manifest():
    """sync_batch ghi nhận skipped nếu không có manifest.json."""
    print("\n[TEST 9] sync_batch bỏ qua tài liệu không có manifest...")
    data_root = _TEST_ROOT / "t9"
    cfg = _make_cfg(data_root)

    # Tạo 2 tài liệu hợp lệ + 1 không có manifest
    _make_queue(data_root, doc_id="doc_ok1")
    _make_queue(data_root, doc_id="doc_ok2")
    # doc_missing: không tạo gì cả

    with patch(_MOCK_POST, return_value=_ok_post_response()), \
         patch(_MOCK_GET, return_value=_ok_poll_response()), \
         patch(_MOCK_SLEEP):
        summary = sync_batch(
            cfg, "incoming", ["doc_ok1", "doc_missing", "doc_ok2"],
            enable_polling=True, poll_timeout=2.0, poll_interval=0.1
        )

    assert summary["success"] == 2, f"Phải 2 success, nhận {summary['success']}"
    assert summary["skipped"] == 1, f"Phải 1 skipped, nhận {summary['skipped']}"
    assert summary["failed"] == 0, f"Phải 0 failed, nhận {summary['failed']}"
    print("  -> PASSED")


def test_polling_404_does_not_fail_sync():
    """Endpoint polling trả 404 → upload vẫn được ghi là SYNCED (graceful)."""
    print("\n[TEST 10] Polling 404 không làm hỏng luồng upload...")
    data_root = _TEST_ROOT / "t10"
    _, manifest_path = _make_queue(data_root)
    cfg = _make_cfg(data_root)

    poll_404 = MagicMock()
    poll_404.ok = False
    poll_404.status_code = 404

    with patch(_MOCK_POST, return_value=_ok_post_response("srv-poll")), \
         patch(_MOCK_GET, return_value=poll_404):
        ok = sync_upload(
            cfg, "incoming", "test_doc_retry",
            max_retries=1,
            enable_polling=True,
            poll_timeout=5.0,
            poll_interval=0.1,
        )

    assert ok is True
    sync_info = _read_sync(manifest_path)
    assert sync_info["planner_kpi_status"] == "SYNCED", \
        f"Phải SYNCED dù polling 404, nhận {sync_info['planner_kpi_status']}"
    print("  -> PASSED")


def test_token_not_logged():
    """Token không xuất hiện trong log output (bảo mật)."""
    print("\n[TEST 11] Token không bị log ra...")
    import io
    import logging

    log_stream = io.StringIO()
    handler = logging.StreamHandler(log_stream)
    handler.setLevel(logging.DEBUG)
    target_logger = logging.getLogger("qlvb.sync_client")
    target_logger.addHandler(handler)
    target_logger.setLevel(logging.DEBUG)

    data_root = _TEST_ROOT / "t11"
    _, manifest_path = _make_queue(data_root)
    cfg = _make_cfg(data_root)

    try:
        with patch(_MOCK_POST, return_value=_ok_post_response()), \
             patch(_MOCK_GET, return_value=_ok_poll_response()), \
             patch(_MOCK_SLEEP):
            sync_upload(cfg, "incoming", "test_doc_retry", max_retries=1,
                        enable_polling=True, poll_timeout=2.0, poll_interval=0.1)

        log_output = log_stream.getvalue()
        secret_token = cfg.planner_ingest_token  # "mock_secret_token"
        assert secret_token not in log_output, \
            f"Token '{secret_token}' không được xuất hiện trong log!"
    finally:
        target_logger.removeHandler(handler)

    print("  -> PASSED")


def test_connection_error_retry():
    """ConnectionError retry rồi thành công lần 3."""
    print("\n[TEST 12] ConnectionError retry nhiều lần rồi thành công...")
    data_root = _TEST_ROOT / "t12"
    _, manifest_path = _make_queue(data_root)
    cfg = _make_cfg(data_root)

    from requests.exceptions import ConnectionError as ReqConnError

    call_count = 0

    def post_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ReqConnError(f"Connection refused (attempt {call_count})")
        return _ok_post_response("srv-003")

    with patch(_MOCK_POST, side_effect=post_side_effect), \
         patch(_MOCK_GET, return_value=_ok_poll_response()), \
         patch(_MOCK_SLEEP):
        ok = sync_upload(cfg, "incoming", "test_doc_retry", max_retries=3,
                         retry_backoff_base=0.01, enable_polling=True,
                         poll_timeout=2.0, poll_interval=0.1)

    assert ok is True, f"Phải thành công ở lần 3, call_count={call_count}"
    assert call_count == 3
    sync_info = _read_sync(manifest_path)
    assert sync_info["planner_kpi_status"] == "SYNCED"
    print("  -> PASSED")


# ---------------------------------------------------------------------------
# Cleanup và runner
# ---------------------------------------------------------------------------
def _cleanup():
    if _TEST_ROOT.exists():
        shutil.rmtree(_TEST_ROOT)


def run_tests():
    print("=" * 65)
    print(" Phase 1 — test_sync_retry.py")
    print("=" * 65)

    _cleanup()

    tests = [
        test_success_on_first_attempt,
        test_retry_on_timeout_then_success,
        test_http_500_retries_exhausted,
        test_http_400_no_retry,
        test_idempotency_key_in_header,
        test_no_manifest_returns_false,
        test_syncing_not_stuck_after_failure,
        test_sync_batch_continues_on_one_failure,
        test_sync_batch_skip_missing_manifest,
        test_polling_404_does_not_fail_sync,
        test_token_not_logged,
        test_connection_error_retry,
    ]

    passed = 0
    failed_names: list[str] = []

    for test_fn in tests:
        _cleanup()
        _TEST_ROOT.mkdir(parents=True, exist_ok=True)
        try:
            test_fn()
            passed += 1
        except Exception as exc:
            name = test_fn.__name__
            import traceback
            print(f"  -> FAILED: {name}")
            print(f"     Lỗi: {exc}")
            traceback.print_exc()
            failed_names.append(name)

    _cleanup()

    print("\n" + "=" * 65)
    print(f" Kết quả: {passed}/{len(tests)} PASSED")
    if failed_names:
        print(f" FAILED: {', '.join(failed_names)}")
    else:
        print(" ALL TESTS PASSED!")
    print("=" * 65)

    if failed_names:
        sys.exit(1)


if __name__ == "__main__":
    run_tests()
