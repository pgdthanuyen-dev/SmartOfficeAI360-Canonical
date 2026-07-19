import sys
import os
import json
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure stdout is utf-8 on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from tools.qlvb_downloader.config import QLVBConfig
from tools.qlvb_downloader.sync_client import sync_upload

# Đường dẫn mock đúng — Phase 1 import requests trực tiếp trong module
_MOCK_POST = "tools.qlvb_downloader.sync_client.requests.post"
_MOCK_GET = "tools.qlvb_downloader.sync_client.requests.get"
_MOCK_SLEEP = "tools.qlvb_downloader.sync_client.time.sleep"

def run_tests():
    data_root = Path("Data_sync_test")
    if data_root.exists():
        shutil.rmtree(data_root)
    data_root.mkdir(parents=True, exist_ok=True)
    
    try:
        # 1. Setup config
        cfg = QLVBConfig(
            save_root=str(data_root),
            planner_api_url="http://mock-api.local",
            planner_ingest_token="mock_token_123"
        )
        
        # 2. Setup mock files in queue
        direction = "incoming"
        doc_id = "test_doc_id"
        queue_dir = data_root / "queue" / direction / doc_id
        queue_dir.mkdir(parents=True, exist_ok=True)
        
        manifest_payload = {
            "schema_version": "2.0.0",
            "source": "QLVB",
            "direction": direction,
            "doc_id": doc_id,
            "external_doc_id": doc_id,
            "document_number": "111/QD",
            "issued_date": "2026-06-23",
            "issuing_agency": "Agency",
            "summary": "Summary",
            "main_document": {
                "filename": "doc.pdf",
                "size_bytes": 10,
                "sha256": "hash1",
                "relative_path": "doc.pdf"
            },
            "attachments": [
                {
                    "filename": "attach1.xlsx",
                    "size_bytes": 12,
                    "sha256": "hash2",
                    "relative_path": "attach1.xlsx"
                }
            ],
            "sync": {
                "planner_kpi_status": "PENDING",
                "planner_kpi_document_id": None,
                "last_sync_at": None,
                "last_error": None
            }
        }
        
        manifest_path = queue_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest_payload, indent=2), encoding="utf-8")
        
        (queue_dir / "doc.pdf").write_text("dummy main doc", encoding="utf-8")
        (queue_dir / "attach1.xlsx").write_text("dummy attachment", encoding="utf-8")
        
        # 3. Test Success Sync (HTTP 200)
        # Tắt polling (enable_polling=False) để test đơn giản không cần mock GET
        poll_ok = MagicMock(ok=True, status_code=200)
        poll_ok.json.return_value = {"status": "PROCESSED"}
        with patch(_MOCK_POST) as mock_post, patch(_MOCK_GET, return_value=poll_ok):
            mock_resp = MagicMock()
            mock_resp.ok = True
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"success": True, "document_id": "server-doc-12345"}
            mock_post.return_value = mock_resp
            
            ok = sync_upload(cfg, direction, doc_id, enable_polling=True,
                             poll_timeout=2.0, poll_interval=0.1)
            
            assert ok is True
            # Verify mock post was called
            mock_post.assert_called_once()
            
            # Read manifest.json to check status
            updated_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            assert updated_manifest["sync"]["planner_kpi_status"] == "SYNCED"
            assert updated_manifest["sync"]["planner_kpi_document_id"] == "server-doc-12345"
            assert updated_manifest["sync"]["last_error"] is None
            assert updated_manifest["sync"]["last_sync_at"] is not None
            
        # 4. Test Failed Sync (HTTP 500)
        # Reset mock
        manifest_payload["sync"]["planner_kpi_status"] = "PENDING"
        manifest_path.write_text(json.dumps(manifest_payload, indent=2), encoding="utf-8")
        
        # Dùng max_retries=1 để test nhanh, Phase 1 có retry nên gọi nhiều lần với max_retries=3
        with patch(_MOCK_POST) as mock_post, patch(_MOCK_SLEEP):
            mock_resp = MagicMock()
            mock_resp.ok = False
            mock_resp.status_code = 500
            mock_resp.text = "Internal Server Error"
            mock_resp.json.return_value = {"message": "Internal Server Error"}
            mock_post.return_value = mock_resp
            
            # max_retries=1 để test nhanh: 1 lần thử rồi RETRYABLE_FAILED
            ok = sync_upload(cfg, direction, doc_id, max_retries=1,
                             enable_polling=False)
            
            assert ok is False
            assert mock_post.call_count == 1, f"max_retries=1 phải gọi 1 lần, gọi {mock_post.call_count}"
            
            # Read manifest.json to check status
            updated_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            # Phase 1: HTTP 500 + hết retry → RETRYABLE_FAILED
            assert updated_manifest["sync"]["planner_kpi_status"] == "RETRYABLE_FAILED"
            assert "HTTP 500" in updated_manifest["sync"]["last_error"]
            assert updated_manifest["sync"]["last_sync_at"] is not None
            
        print("ALL SYNC CLIENT UNIT TESTS COMPLETED SUCCESSFULLY!")
    finally:
        if data_root.exists():
            shutil.rmtree(data_root)

if __name__ == "__main__":
    run_tests()
