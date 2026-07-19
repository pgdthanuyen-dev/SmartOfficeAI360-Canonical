"""
sync_client.py — Phase 1 Upgrade
=================================
Đồng bộ gói hàng đợi từ QLVB Downloader sang Planner KPI backend.

Cải tiến Phase 1:
  - Retry với exponential backoff, phân biệt lỗi 4xx (không retry) vs 5xx/timeout (retry)
  - Header X-Idempotency-Key chống tạo trùng nhiệm vụ khi retry
  - Polling xác nhận qua GET /api/document-ingest/status/{id} (graceful nếu 404)
  - Hàm sync_batch() hỗ trợ đồng bộ nhiều văn bản với callback progress
  - Chống trạng thái SYNCING bị kẹt: luôn ghi trạng thái cuối dù retry thất bại
  - Timeout tách biệt: connect timeout vs read timeout
  - Backward-compatible: chữ ký sync_upload() giữ nguyên, chỉ thêm tham số có default
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import requests
from requests.exceptions import ConnectionError, Timeout

from .config import QLVBConfig

# ---------------------------------------------------------------------------
# Logger — dùng tên riêng, KHÔNG log token/password
# ---------------------------------------------------------------------------
logger = logging.getLogger("qlvb.sync_client")

# ---------------------------------------------------------------------------
# Hằng số mặc định
# ---------------------------------------------------------------------------
_DEFAULT_CONNECT_TIMEOUT: float = 10.0   # giây — thiết lập kết nối
_DEFAULT_READ_TIMEOUT: float = 120.0     # giây — chờ nhận dữ liệu (file lớn)
_DEFAULT_MAX_RETRIES: int = 3
_DEFAULT_RETRY_BACKOFF_BASE: float = 2.0  # giây cho lần 1; lần 2: 4s, lần 3: 8s
_DEFAULT_POLL_INTERVAL: float = 5.0      # giây giữa 2 lần poll
_DEFAULT_POLL_TIMEOUT: float = 60.0      # tổng thời gian tối đa polling

# Trạng thái sync được lưu vào manifest["sync"]["planner_kpi_status"]
_STATUS_PENDING = "PENDING"
_STATUS_SYNCING = "SYNCING"
_STATUS_SYNCED = "SYNCED"
_STATUS_FAILED = "FAILED"
_STATUS_RETRYABLE_FAILED = "RETRYABLE_FAILED"

# HTTP status codes được phép retry
_RETRYABLE_HTTP_CODES = frozenset({429, 500, 502, 503, 504})


# ---------------------------------------------------------------------------
# Helper: đọc / ghi manifest an toàn
# ---------------------------------------------------------------------------
def _read_manifest(manifest_path: Path) -> dict[str, Any]:
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        logger.error("Không đọc được manifest %s: %s", manifest_path, exc)
        raise


def _write_manifest(manifest_path: Path, manifest: dict[str, Any]) -> None:
    try:
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:
        logger.error("Không ghi được manifest %s: %s", manifest_path, exc)


def _ensure_sync_block(manifest: dict[str, Any]) -> None:
    """Đảm bảo khối sync tồn tại với đầy đủ các trường."""
    if "sync" not in manifest or not isinstance(manifest["sync"], dict):
        manifest["sync"] = {}
    sync = manifest["sync"]
    sync.setdefault("planner_kpi_status", _STATUS_PENDING)
    sync.setdefault("planner_kpi_document_id", None)
    sync.setdefault("last_sync_at", None)
    sync.setdefault("last_error", None)
    sync.setdefault("retry_count", 0)


def _stamp_sync(manifest: dict[str, Any], status: str, **extra: Any) -> None:
    """Ghi trạng thái và timestamp vào khối sync trong manifest."""
    _ensure_sync_block(manifest)
    manifest["sync"]["planner_kpi_status"] = status
    manifest["sync"]["last_sync_at"] = datetime.now().isoformat()
    for k, v in extra.items():
        manifest["sync"][k] = v


# ---------------------------------------------------------------------------
# Helper: polling xác nhận ingest
# ---------------------------------------------------------------------------
def _poll_ingest_status(
    cfg: QLVBConfig,
    ingest_id: str,
    doc_id: str,
    poll_interval: float = _DEFAULT_POLL_INTERVAL,
    poll_timeout: float = _DEFAULT_POLL_TIMEOUT,
    connect_timeout: float = _DEFAULT_CONNECT_TIMEOUT,
    read_timeout: float = _DEFAULT_READ_TIMEOUT,
) -> tuple[bool, str]:
    """
    Polling endpoint GET /api/document-ingest/status/{ingest_id}.

    Trả về (confirmed: bool, message: str).
    Nếu endpoint không tồn tại (404) hoặc lỗi khác, trả về (True, 'SKIPPED_POLL')
    để không phá vỡ luồng cũ.
    """
    status_url = (
        cfg.planner_api_url.rstrip("/")
        + f"/api/document-ingest/status/{ingest_id}"
    )
    headers = {"Authorization": f"Bearer {cfg.planner_ingest_token}"}
    deadline = time.monotonic() + poll_timeout

    logger.info(
        "[sync_client] Bắt đầu polling xác nhận ingest | doc_id=%s ingest_id=%s",
        doc_id,
        ingest_id,
    )

    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        try:
            resp = requests.get(
                status_url,
                headers=headers,
                timeout=(connect_timeout, read_timeout),
            )
        except Exception as exc:
            logger.warning(
                "[sync_client] Lỗi kết nối khi poll lần %d | doc_id=%s | %s",
                attempt,
                doc_id,
                exc,
            )
            time.sleep(poll_interval)
            continue

        if resp.status_code == 404:
            logger.warning(
                "[sync_client] Endpoint polling chưa có (404), bỏ qua polling | doc_id=%s",
                doc_id,
            )
            return True, "SKIPPED_POLL_ENDPOINT_NOT_FOUND"

        if not resp.ok:
            logger.warning(
                "[sync_client] Poll lần %d trả HTTP %d | doc_id=%s",
                attempt,
                resp.status_code,
                doc_id,
            )
            time.sleep(poll_interval)
            continue

        try:
            data = resp.json()
        except Exception:
            data = {}

        ingest_status = (
            data.get("status") or data.get("ingest_status") or ""
        ).upper()

        if ingest_status in ("PROCESSED", "COMPLETED", "DONE", "SUCCESS", "SYNCED"):
            logger.info(
                "[sync_client] Polling xác nhận xong | doc_id=%s status=%s",
                doc_id,
                ingest_status,
            )
            return True, ingest_status

        if ingest_status in ("FAILED", "ERROR", "REJECTED"):
            reason = data.get("message") or data.get("error") or ingest_status
            logger.error(
                "[sync_client] Planner KPI báo lỗi xử lý | doc_id=%s reason=%s",
                doc_id,
                reason,
            )
            return False, f"PLANNER_REJECTED: {reason}"

        logger.debug(
            "[sync_client] Poll lần %d | doc_id=%s status=%s — chờ tiếp",
            attempt,
            doc_id,
            ingest_status or "UNKNOWN",
        )
        time.sleep(poll_interval)

    logger.warning(
        "[sync_client] Polling hết thời gian %ds | doc_id=%s — coi như thành công",
        int(poll_timeout),
        doc_id,
    )
    return True, "POLL_TIMEOUT_ASSUMED_OK"


# ---------------------------------------------------------------------------
# Hàm chính: sync_upload() — backward-compatible
# ---------------------------------------------------------------------------
def sync_upload(
    cfg: QLVBConfig,
    direction: str,
    doc_id: str,
    *,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    connect_timeout: float = _DEFAULT_CONNECT_TIMEOUT,
    read_timeout: float = _DEFAULT_READ_TIMEOUT,
    retry_backoff_base: float = _DEFAULT_RETRY_BACKOFF_BASE,
    enable_polling: bool = True,
    poll_interval: float = _DEFAULT_POLL_INTERVAL,
    poll_timeout: float = _DEFAULT_POLL_TIMEOUT,
) -> bool:
    """
    Đồng bộ một gói hàng đợi lên Planner KPI backend.

    Tham số (đều có giá trị mặc định — backward-compatible):
      max_retries          : số lần retry tối đa (HTTP 5xx / timeout)
      connect_timeout      : timeout kết nối (giây)
      read_timeout         : timeout đọc phản hồi (giây) — dùng cho file lớn
      retry_backoff_base   : cơ số backoff; lần n chờ backoff_base * 2^(n-1) giây
      enable_polling       : có polling xác nhận Planner xử lý xong không
      poll_interval        : khoảng cách giữa 2 lần poll (giây)
      poll_timeout         : tổng thời gian tối đa polling (giây)

    Trả về: True nếu upload (và optional poll) thành công, False nếu thất bại.
    """
    queue_dir = cfg.root_path / "queue" / direction / doc_id
    manifest_path = queue_dir / "manifest.json"

    if not manifest_path.exists():
        logger.error(
            "[sync_client] Không tìm thấy manifest | doc_id=%s path=%s",
            doc_id,
            manifest_path,
        )
        return False

    # Đọc manifest
    try:
        manifest = _read_manifest(manifest_path)
    except Exception:
        return False

    _ensure_sync_block(manifest)

    # Idempotency key = doc_id hoặc external_doc_id từ manifest
    idempotency_key = (
        manifest.get("external_doc_id")
        or manifest.get("doc_id")
        or doc_id
    )

    # URL upload
    upload_url = cfg.planner_api_url.rstrip("/") + "/api/document-ingest/upload"
    headers = {
        "Authorization": f"Bearer {cfg.planner_ingest_token}",
        "X-Idempotency-Key": idempotency_key,
    }

    # -----------------------------------------------------------------------
    # Retry loop
    # -----------------------------------------------------------------------
    last_error: Optional[str] = None
    attempt = 0

    for attempt in range(1, max_retries + 1):
        # Ghi trạng thái SYNCING ngay khi bắt đầu mỗi lần thử
        _stamp_sync(manifest, _STATUS_SYNCING, retry_count=attempt - 1)
        _write_manifest(manifest_path, manifest)

        logger.info(
            "[sync_client] Upload lần %d/%d | doc_id=%s url=%s",
            attempt,
            max_retries,
            doc_id,
            upload_url,
        )

        opened_files: list[Any] = []
        try:
            files_list = _build_files_list(queue_dir, manifest, opened_files)
        except FileNotFoundError as exc:
            # Thiếu file vật lý — không retry, lỗi cứng
            last_error = f"Thiếu file đính kèm: {exc}"
            logger.error(
                "[sync_client] Thiếu file, không retry | doc_id=%s | %s",
                doc_id,
                exc,
            )
            break
        except Exception as exc:
            last_error = f"Lỗi chuẩn bị file upload: {exc}"
            logger.error(
                "[sync_client] Lỗi chuẩn bị file | doc_id=%s | %s", doc_id, exc
            )
            break

        try:
            response = requests.post(
                upload_url,
                files=files_list,
                headers=headers,
                timeout=(connect_timeout, read_timeout),
            )
            http_status = response.status_code
            logger.info(
                "[sync_client] Phản hồi HTTP %d | doc_id=%s attempt=%d",
                http_status,
                doc_id,
                attempt,
            )

            if response.ok:
                # ---- Thành công ----
                try:
                    resp_data = response.json()
                except Exception:
                    resp_data = {}

                ingest_id = (
                    resp_data.get("ingest_id")
                    or resp_data.get("document_id")
                    or resp_data.get("id")
                )

                _stamp_sync(
                    manifest,
                    _STATUS_SYNCED,
                    planner_kpi_document_id=ingest_id,
                    last_error=None,
                    retry_count=attempt - 1,
                )
                _write_manifest(manifest_path, manifest)
                logger.info(
                    "[sync_client] Upload thành công | doc_id=%s ingest_id=%s",
                    doc_id,
                    ingest_id,
                )

                # Polling xác nhận (nếu backend trả ingest_id và enable_polling=True)
                if enable_polling and ingest_id:
                    poll_ok, poll_msg = _poll_ingest_status(
                        cfg,
                        ingest_id,
                        doc_id,
                        poll_interval=poll_interval,
                        poll_timeout=poll_timeout,
                        connect_timeout=connect_timeout,
                        read_timeout=read_timeout,
                    )
                    if not poll_ok:
                        # Planner từ chối xử lý — ghi lại nhưng không SYNCED
                        _stamp_sync(
                            manifest,
                            _STATUS_FAILED,
                            last_error=poll_msg,
                            retry_count=attempt - 1,
                        )
                        _write_manifest(manifest_path, manifest)
                        logger.error(
                            "[sync_client] Planner báo lỗi qua polling | doc_id=%s | %s",
                            doc_id,
                            poll_msg,
                        )
                        return False
                    # poll_ok: cập nhật thêm thông tin poll vào manifest
                    manifest["sync"]["poll_result"] = poll_msg
                    _write_manifest(manifest_path, manifest)

                return True  # ← đường thành công

            else:
                # ---- HTTP Error ----
                try:
                    err_body = response.json()
                    err_detail = err_body.get("message") or err_body.get("error") or response.text[:400]
                except Exception:
                    err_detail = response.text[:400]

                if http_status in (401, 403):
                    last_error = f"AUTH_FAILED HTTP {http_status}: {err_detail}"
                else:
                    last_error = f"HTTP {http_status}: {err_detail}"

                if http_status in _RETRYABLE_HTTP_CODES:
                    logger.warning(
                        "[sync_client] HTTP %d retryable | doc_id=%s attempt=%d/%d | %s",
                        http_status,
                        doc_id,
                        attempt,
                        max_retries,
                        err_detail[:120],
                    )
                    # Sẽ retry ở vòng lặp tiếp theo nếu còn lần
                else:
                    # HTTP 4xx (trừ 429) — lỗi logic, không retry
                    logger.error(
                        "[sync_client] HTTP %d không retry (lỗi client) | doc_id=%s | %s",
                        http_status,
                        doc_id,
                        err_detail[:120],
                    )
                    break  # thoát vòng retry ngay

        except (Timeout, ConnectionError) as exc:
            last_error = f"Lỗi kết nối/timeout lần {attempt}: {exc}"
            logger.warning(
                "[sync_client] Kết nối/timeout lần %d/%d | doc_id=%s | %s",
                attempt,
                max_retries,
                doc_id,
                type(exc).__name__,
            )
            # Sẽ retry ở vòng lặp tiếp theo nếu còn lần

        except Exception as exc:
            last_error = f"Lỗi không xác định lần {attempt}: {exc}"
            logger.error(
                "[sync_client] Lỗi không xác định | doc_id=%s | %s", doc_id, exc
            )
            break  # Lỗi không retry được

        finally:
            _close_files(opened_files)

        # Chờ backoff trước khi retry (chỉ nếu còn lần thử)
        if attempt < max_retries:
            wait_secs = retry_backoff_base * (2 ** (attempt - 1))
            logger.info(
                "[sync_client] Chờ %.1fs trước retry lần %d | doc_id=%s",
                wait_secs,
                attempt + 1,
                doc_id,
            )
            time.sleep(wait_secs)

    # -----------------------------------------------------------------------
    # Đã hết retry hoặc bị break — ghi trạng thái thất bại cuối cùng
    # Đảm bảo KHÔNG để manifest nằm vĩnh viễn ở SYNCING
    # -----------------------------------------------------------------------
    current_status = manifest.get("sync", {}).get("planner_kpi_status", "")
    if current_status == _STATUS_SYNCING:
        # Dùng RETRYABLE_FAILED nếu đã hết tất cả retry (không phải break sớm do 4xx)
        final_status = _STATUS_RETRYABLE_FAILED if attempt == max_retries else _STATUS_FAILED
        _stamp_sync(
            manifest,
            final_status,
            last_error=last_error or "Không rõ lỗi",
            retry_count=attempt,
        )
        _write_manifest(manifest_path, manifest)

    logger.error(
        "[sync_client] Đồng bộ thất bại sau %d lần thử | doc_id=%s | %s",
        attempt,
        doc_id,
        last_error,
    )
    return False


# ---------------------------------------------------------------------------
# Hàm batch: sync_batch()
# ---------------------------------------------------------------------------
def sync_batch(
    cfg: QLVBConfig,
    direction: str,
    doc_ids: list[str],
    *,
    on_progress: Optional[Callable[[int, int, str, dict[str, Any]], None]] = None,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    connect_timeout: float = _DEFAULT_CONNECT_TIMEOUT,
    read_timeout: float = _DEFAULT_READ_TIMEOUT,
    retry_backoff_base: float = _DEFAULT_RETRY_BACKOFF_BASE,
    enable_polling: bool = True,
    poll_interval: float = _DEFAULT_POLL_INTERVAL,
    poll_timeout: float = _DEFAULT_POLL_TIMEOUT,
) -> dict[str, Any]:
    """
    Đồng bộ hàng loạt nhiều văn bản.

    Tham số:
      doc_ids     : danh sách doc_id cần đồng bộ
      on_progress : callback(done: int, total: int, current_doc_id: str, result: dict)
                    Gọi sau mỗi tài liệu (dù thành công hay thất bại).
      Các tham số retry/timeout/polling: như sync_upload()

    Trả về summary dict:
      {
        "total": int,
        "success": int,
        "failed": int,
        "skipped": int,
        "results": [{"doc_id": str, "ok": bool, "error": str|None}, ...]
      }
    """
    total = len(doc_ids)
    summary: dict[str, Any] = {
        "total": total,
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "results": [],
    }

    logger.info(
        "[sync_client] Bắt đầu sync_batch | direction=%s total=%d", direction, total
    )

    for idx, doc_id in enumerate(doc_ids, start=1):
        # Kiểm tra manifest tồn tại trước khi gọi upload
        manifest_path = cfg.root_path / "queue" / direction / doc_id / "manifest.json"
        if not manifest_path.exists():
            logger.warning(
                "[sync_client] Bỏ qua doc_id=%s (không có manifest)", doc_id
            )
            result = {"doc_id": doc_id, "ok": False, "error": "Không tìm thấy manifest.json", "skipped": True}
            summary["skipped"] += 1
        else:
            try:
                ok = sync_upload(
                    cfg,
                    direction,
                    doc_id,
                    max_retries=max_retries,
                    connect_timeout=connect_timeout,
                    read_timeout=read_timeout,
                    retry_backoff_base=retry_backoff_base,
                    enable_polling=enable_polling,
                    poll_interval=poll_interval,
                    poll_timeout=poll_timeout,
                )
                if ok:
                    summary["success"] += 1
                    result = {"doc_id": doc_id, "ok": True, "error": None, "skipped": False}
                    logger.info(
                        "[sync_client] batch[%d/%d] THÀNH CÔNG | doc_id=%s",
                        idx,
                        total,
                        doc_id,
                    )
                else:
                    # Lấy thông tin lỗi từ manifest để báo cáo
                    last_err = _read_last_error(manifest_path) or ""
                    
                    if "AUTH_FAILED" in last_err or "HTTP 401" in last_err or "HTTP 403" in last_err:
                        summary["failed"] += 1
                        result = {"doc_id": doc_id, "ok": False, "error": last_err, "skipped": False}
                        summary["results"].append(result)
                        logger.error("[sync_client] Phát hiện AUTH_FAILED (HTTP %s). Dừng batch sync khẩn cấp.", last_err[:50])
                        
                        summary["auth_failed"] = True
                        summary["message"] = "Token hết hạn hoặc không đủ quyền. Vui lòng đăng nhập/cấu hình lại."
                        
                        if on_progress:
                            try:
                                on_progress(idx, total, doc_id, result)
                            except Exception as cb_exc:
                                logger.warning("[sync_client] Lỗi trong on_progress callback: %s", cb_exc)
                                
                        # Skip các văn bản còn lại
                        for skip_id in doc_ids[idx:]:
                            summary["skipped"] += 1
                            skip_result = {"doc_id": skip_id, "ok": False, "error": "SKIPPED_AUTH_FAILED", "skipped": True}
                            summary["results"].append(skip_result)
                            if on_progress:
                                try:
                                    on_progress(idx + summary["skipped"], total, skip_id, skip_result)
                                except Exception:
                                    pass
                        break

                    summary["failed"] += 1
                    result = {"doc_id": doc_id, "ok": False, "error": last_err, "skipped": False}
                    logger.warning(
                        "[sync_client] batch[%d/%d] THẤT BẠI | doc_id=%s | %s",
                        idx,
                        total,
                        doc_id,
                        last_err,
                    )
            except Exception as exc:
                # Không cho một tài liệu lỗi làm dừng toàn bộ batch
                summary["failed"] += 1
                result = {"doc_id": doc_id, "ok": False, "error": str(exc), "skipped": False}
                logger.error(
                    "[sync_client] batch[%d/%d] EXCEPTION | doc_id=%s | %s",
                    idx,
                    total,
                    doc_id,
                    exc,
                )

        summary["results"].append(result)

        # Gọi callback progress nếu có
        if on_progress:
            try:
                on_progress(idx, total, doc_id, result)
            except Exception as cb_exc:
                logger.warning(
                    "[sync_client] Lỗi trong on_progress callback: %s", cb_exc
                )

    logger.info(
        "[sync_client] Kết thúc sync_batch | total=%d success=%d failed=%d skipped=%d",
        summary["total"],
        summary["success"],
        summary["failed"],
        summary["skipped"],
    )
    return summary


# ---------------------------------------------------------------------------
# Helpers nội bộ
# ---------------------------------------------------------------------------
def _build_files_list(
    queue_dir: Path,
    manifest: dict[str, Any],
    opened_files: list[Any],
) -> list[tuple[str, tuple[str, Any, str]]]:
    """
    Xây dựng danh sách file cho multipart/form-data upload.
    Mở file và đẩy vào opened_files để caller có thể close sau.
    """
    files_list: list[tuple[str, tuple[str, Any, str]]] = []

    # manifest.json
    manifest_path = queue_dir / "manifest.json"
    mf = open(manifest_path, "rb")
    opened_files.append(mf)
    files_list.append(("manifest", ("manifest.json", mf, "application/json")))

    # main_document
    main_doc_meta = manifest.get("main_document")
    if main_doc_meta:
        filename = main_doc_meta.get("filename")
        if not filename:
            raise FileNotFoundError("main_document.filename không có trong manifest")
        filepath = queue_dir / filename
        if not filepath.exists():
            raise FileNotFoundError(f"File văn bản chính không tìm thấy: {filename}")
        f = open(filepath, "rb")
        opened_files.append(f)
        files_list.append(("main_document", (filename, f, "application/octet-stream")))

    # attachments
    for att in manifest.get("attachments", []):
        filename = att.get("filename")
        if not filename:
            continue
        filepath = queue_dir / filename
        if not filepath.exists():
            raise FileNotFoundError(f"File đính kèm không tìm thấy: {filename}")
        f = open(filepath, "rb")
        opened_files.append(f)
        files_list.append(("attachments", (filename, f, "application/octet-stream")))

    return files_list


def _close_files(opened_files: list[Any]) -> None:
    """Đóng tất cả file handle đã mở (an toàn, không raise)."""
    for f in opened_files:
        try:
            f.close()
        except Exception:
            pass


def _read_last_error(manifest_path: Path) -> Optional[str]:
    """Đọc last_error từ manifest, trả None nếu không đọc được."""
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        return data.get("sync", {}).get("last_error")
    except Exception:
        return None
