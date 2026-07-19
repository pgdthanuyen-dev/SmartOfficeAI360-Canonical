import shutil
import json
from pathlib import Path
from tools.qlvb_downloader.models import DocumentRecord
from tools.qlvb_downloader.storage import StorageManager

def run_tests():
    data_root = Path("Data_dup_test")
    if data_root.exists():
        shutil.rmtree(data_root)
    data_root.mkdir(parents=True, exist_ok=True)
    
    try:
        storage = StorageManager(data_root)
        
        # Build doc record
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
            summary="Về việc kiểm tra hệ thống QLVB"
        )
        doc_id = rec.ensure_doc_id()
        
        # Test 1: Check duplicate when nothing exists
        # Verify get_queue_item_files is None
        assert storage.get_queue_item_files("incoming", doc_id) is None
        
        # Test 2: Check duplicate in new format
        # Write .ready and manifest.json
        queue_dir = storage.queue_root / "incoming" / doc_id
        queue_dir.mkdir(parents=True, exist_ok=True)
        (queue_dir / ".ready").write_text("ready", encoding="utf-8")
        (queue_dir / "manifest.json").write_text(json.dumps({"doc_id": doc_id, "schema_version": "2.0.0"}), encoding="utf-8")
        
        # It should detect it
        queue_info = storage.get_queue_item_files("incoming", doc_id)
        assert queue_info is not None
        assert queue_info["format"] == "new"
        
        # Clean up new format
        shutil.rmtree(queue_dir)
        assert storage.get_queue_item_files("incoming", doc_id) is None
        
        # Test 3: Check duplicate in old format fallback
        old_queue_dir = storage.queue_root / "incoming" / doc_id / "READY"
        old_queue_dir.mkdir(parents=True, exist_ok=True)
        (old_queue_dir / "READY.ok").write_text("ready", encoding="utf-8")
        (old_queue_dir / "metadata.json").write_text(json.dumps({"doc_id": doc_id}), encoding="utf-8")
        (old_queue_dir / "files_manifest.json").write_text(json.dumps({"files": []}), encoding="utf-8")
        
        # It should detect it
        queue_info_old = storage.get_queue_item_files("incoming", doc_id)
        assert queue_info_old is not None
        assert queue_info_old["format"] == "old_fallback"
        
        print("ALL DEDUPLICATION TESTS COMPLETED SUCCESSFULLY!")
        
    finally:
        if data_root.exists():
            shutil.rmtree(data_root)

if __name__ == "__main__":
    run_tests()
