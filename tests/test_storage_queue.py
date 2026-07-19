import os
import shutil
import json
import hashlib
from pathlib import Path
from tools.qlvb_downloader.models import DocumentRecord, AttachmentInfo
from tools.qlvb_downloader.storage import StorageManager

def sha256_checksum(filepath):
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()

def run_tests():
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    data_root = Path("Data_test")
    if data_root.exists():
        shutil.rmtree(data_root)
    data_root.mkdir(parents=True, exist_ok=True)
    
    try:
        # 1. Create dummy files representing downloaded attachments
        files_dir = data_root / "temp_files"
        files_dir.mkdir(parents=True, exist_ok=True)
        
        main_src = files_dir / "van_ban_chinh_thuc.pdf"
        main_src.write_text("This is the main document content.", encoding="utf-8")
        
        attach_src = files_dir / "phu_luc_1.xlsx"
        attach_src.write_text("This is the attachment spreadsheet content.", encoding="utf-8")
        
        main_sha = sha256_checksum(main_src)
        attach_sha = sha256_checksum(attach_src)
        
        # 2. Setup mock DocumentRecord
        rec = DocumentRecord(
            direction="incoming",
            source_url="https://qlvb.laichau.gov.vn/incoming",
            row_index=1,
            row_text="1 123/UBND-VHXH 27/04/2026 UBND tinh Về việc kiểm tra hệ thống QLVB",
            detail_url="https://qlvb.laichau.gov.vn/detail/123",
            doc_no="123/UBND-VHXH",
            doc_date="27/04/2026",
            issuing_agency="UBND tỉnh",
            title="Về việc kiểm tra hệ thống QLVB",
            summary="Về việc kiểm tra hệ thống QLVB tóm tắt"
        )
        rec.ensure_doc_id()
        
        rec.attachments = [
            AttachmentInfo(text="Văn bản chính thức", href="http://example.com/chinh.pdf", saved_path=str(main_src), status="DOWNLOADED"),
            AttachmentInfo(text="Phụ lục 1", href="http://example.com/phuluc1.xlsx", saved_path=str(attach_src), status="DOWNLOADED")
        ]
        rec.status = "READY"
        
        # 3. Run StorageManager
        storage = StorageManager(data_root, copy_files_to_queue=True, create_ready_marker=True)
        paths = storage.write_document_outputs(rec)
        
        print("Outputs written to:")
        print(json.dumps(paths, indent=2))
        
        # 4. Verify flat queue folder structure and atomic writes
        queue_dir = Path(paths["queue_ready_dir"])
        assert queue_dir.exists(), "Queue directory not created"
        
        # Verify files are copied flatly
        copied_main = queue_dir / "van_ban_chinh_thuc.pdf"
        copied_attach = queue_dir / "phu_luc_1.xlsx"
        assert copied_main.exists(), "Main document file not copied flatly"
        assert copied_attach.exists(), "Attachment file not copied flatly"
        
        # Verify file size > 0
        assert copied_main.stat().st_size > 0, "Copied main document file size is 0"
        assert copied_attach.stat().st_size > 0, "Copied attachment file size is 0"
        
        # Verify .ready and READY.ok markers exist
        assert (queue_dir / ".ready").exists(), ".ready marker file missing"
        assert (queue_dir / "READY.ok").exists(), "READY.ok marker file missing"
        
        # 5. Verify manifest.json schema and data
        manifest_path = queue_dir / "manifest.json"
        assert manifest_path.exists(), "manifest.json missing"
        
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        print("\nGenerated manifest.json contents:")
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
        
        assert manifest["schema_version"] == "2.0.0"
        assert manifest["source"] == "QLVB"
        assert manifest["direction"] == "incoming"
        assert manifest["doc_id"] == rec.doc_id
        assert manifest["external_doc_id"] == rec.doc_id
        assert manifest["document_number"] == "123/UBND-VHXH"
        assert manifest["issued_date"] == "27/04/2026"
        assert manifest["issuing_agency"] == "UBND tỉnh"
        assert manifest["summary"] == "Về việc kiểm tra hệ thống QLVB tóm tắt"
        assert manifest["classification_method"] == "keyword" # because it contains "chinh"
        
        # Verify checksums and size_bytes in manifest
        assert manifest["main_document"]["filename"] == "van_ban_chinh_thuc.pdf"
        assert manifest["main_document"]["size_bytes"] == main_src.stat().st_size
        assert manifest["main_document"]["sha256"] == main_sha
        
        assert manifest["attachments"][0]["filename"] == "phu_luc_1.xlsx"
        assert manifest["attachments"][0]["size_bytes"] == attach_src.stat().st_size
        assert manifest["attachments"][0]["sha256"] == attach_sha
        
        assert manifest["sync"]["planner_kpi_status"] == "PENDING"
        assert manifest["sync"]["planner_kpi_document_id"] is None
        assert manifest["sync"]["last_sync_at"] is None
        assert manifest["sync"]["last_error"] is None
        
        # 6. Test get_queue_item_files reader on new format
        item_info = storage.get_queue_item_files("incoming", rec.doc_id)
        assert item_info is not None, "Failed to read new queue item format"
        assert item_info["format"] == "new"
        assert item_info["manifest"]["doc_id"] == rec.doc_id
        
        # 7. Test get_queue_item_files fallback reader on old format
        old_doc_id = "incoming_old_test_123"
        old_queue_dir = data_root / "queue" / "incoming" / old_doc_id / "READY"
        old_queue_dir.mkdir(parents=True, exist_ok=True)
        (old_queue_dir / "READY.ok").write_text("READY", encoding="utf-8")
        (old_queue_dir / "metadata.json").write_text(json.dumps({"doc_id": old_doc_id, "title": "Old doc"}), encoding="utf-8")
        (old_queue_dir / "files_manifest.json").write_text(json.dumps({"files": [{"filename": "old_file.pdf"}]}), encoding="utf-8")
        
        item_info_old = storage.get_queue_item_files("incoming", old_doc_id)
        assert item_info_old is not None, "Failed to read old queue item format fallback"
        assert item_info_old["format"] == "old_fallback"
        assert item_info_old["manifest"]["doc_id"] == old_doc_id
        assert item_info_old["manifest"]["files_manifest"]["files"][0]["filename"] == "old_file.pdf"
        
        print("\nALL STORAGE & QUEUE TESTS COMPLETED SUCCESSFULLY!")
        
    finally:
        # Clean up test directory
        if data_root.exists():
            shutil.rmtree(data_root)

if __name__ == "__main__":
    run_tests()
