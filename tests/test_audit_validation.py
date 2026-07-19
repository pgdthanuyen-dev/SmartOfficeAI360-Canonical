from __future__ import annotations

import os
import sys
import shutil
import json
import hashlib
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.qlvb_downloader.parser import validate_record_data, validate_document_record
from tools.qlvb_downloader.models import DocumentRecord, AttachmentInfo
from tools.qlvb_downloader.audit_queue import run_audit


def sha256_checksum(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def test_validation_filters():
    print("Running validation filters unit tests...")
    
    # 1. Accounts/users rows must be INVALID
    status, reason = validate_record_data("mnmt.phanthimai", "mnmt.phanthimai | Phan Thị Mai", "20/06/2026", "UBND tỉnh")
    assert status == "INVALID", f"Expected INVALID for username doc_no, got {status} ({reason})"
    assert "tài khoản" in reason.lower()
    
    status, reason = validate_record_data("mnhn.dangthithuy", "Đặng Thị Thủy", "20/06/2026", "UBND tỉnh")
    assert status == "INVALID", f"Expected INVALID for username, got {status} ({reason})"
    
    # Format "username | Họ tên"
    status, reason = validate_record_data("123", "mt.ngothihoai | Ngô Thị Hoài", "20/06/2026", "UBND tỉnh")
    assert status == "INVALID", f"Expected INVALID for username | name format, got {status} ({reason})"
    assert "tài khoản" in reason.lower()
    
    # doc_no like a personal name
    status, reason = validate_record_data("Nguyễn Văn A", "Văn bản hành chính", "20/06/2026", "UBND tỉnh")
    assert status == "INVALID", f"Expected INVALID for name doc_no, got {status} ({reason})"
    assert "tên người" in reason.lower()
    
    # 2. Valid document numbers
    status, reason = validate_record_data("419/QĐ/ĐU", "Quyết định thành lập ban", "20/06/2026", "UBND tỉnh")
    assert status == "VALID", f"Expected VALID for standard admin doc_no, got {status} ({reason})"
    
    status, reason = validate_record_data("1091/CV-VP", "Công văn chỉ đạo", "20/06/2026", "Sở Nội Vụ")
    assert status == "VALID", f"Expected VALID for standard admin doc_no, got {status} ({reason})"

    # 3. Missing fields (Phase 2: Confidence Scoring)
    # Thiếu doc_no (0), có title "Trích yếu" (10 vì <10 chars), date (20), agency (15) -> 45 điểm -> SUSPICIOUS
    status, reason = validate_record_data("", "Trích yếu", "20/06/2026", "UBND tỉnh")
    assert status == "SUSPICIOUS", f"Expected SUSPICIOUS for missing doc_no, got {status} ({reason})"
    
    # Thiếu title (0), có doc_no (25), date (20), agency (15) -> 60 điểm -> VALID (nhưng có warning thiếu title)
    status, reason = validate_record_data("123/CV", "", "20/06/2026", "UBND tỉnh")
    assert status == "VALID", f"Expected VALID (score=60) for missing title, got {status} ({reason})"
    assert "Thiếu trích yếu" in reason
    
    # Thiếu ngày (0), có doc_no (25), title ngắn (10), agency (15) -> 50 điểm -> SUSPICIOUS
    status, reason = validate_record_data("123/CV", "Trích yếu", "", "UBND tỉnh")
    assert status == "SUSPICIOUS", f"Expected SUSPICIOUS for missing date with short title, got {status} ({reason})"
    
    # Thiếu gần như toàn bộ -> INVALID (<30 điểm)
    status, reason = validate_record_data("", "", "", "")
    assert status == "INVALID", f"Expected INVALID for completely empty data, got {status} ({reason})"
    
    print("Validation filters unit tests PASSED!")


def test_audit_quarantine_flow():
    print("\nRunning audit and quarantine integration flow tests...")
    
    # Set up temp workspace
    data_root = Path("Data_test_audit")
    if data_root.exists():
        shutil.rmtree(data_root)
    data_root.mkdir(parents=True, exist_ok=True)
    
    try:
        # Create directories
        queue_incoming = data_root / "queue" / "incoming"
        queue_incoming.mkdir(parents=True, exist_ok=True)
        
        files_incoming = data_root / "files" / "incoming"
        files_incoming.mkdir(parents=True, exist_ok=True)
        
        # Scenario A: Valid document in queue (has main doc)
        doc_a_id = "incoming_valid_doc_a"
        doc_a_dir = queue_incoming / doc_a_id
        doc_a_dir.mkdir(parents=True, exist_ok=True)
        
        main_doc_file = doc_a_dir / "chinh.pdf"
        main_doc_file.write_text("Hello PDF Content", encoding="utf-8")
        main_checksum = sha256_checksum(main_doc_file)
        
        manifest_a = {
            "schema_version": "2.0.0",
            "source": "QLVB",
            "direction": "incoming",
            "doc_id": doc_a_id,
            "external_doc_id": doc_a_id,
            "document_number": "1091/CV-VP",
            "issued_date": "20/06/2026",
            "issuing_agency": "Sở Nội Vụ",
            "summary": "Công văn chỉ đạo nâng cấp hệ thống",
            "downloaded_at": "2026-06-23T23:00:00",
            "main_document": {
                "filename": "chinh.pdf",
                "size_bytes": main_doc_file.stat().st_size,
                "sha256": main_checksum,
                "relative_path": "chinh.pdf"
            },
            "attachments": [],
            "sync": {
                "planner_kpi_status": "PENDING",
                "planner_kpi_document_id": None,
                "last_sync_at": None,
                "last_error": None
            }
        }
        with (doc_a_dir / "manifest.json").open("w", encoding="utf-8") as f:
            json.dump(manifest_a, f)
            
        # Correlating files dir
        files_a_dir = files_incoming / f"{doc_a_id}_Cong_van_chi_dao_nang_cap"
        files_a_dir.mkdir(parents=True, exist_ok=True)
        (files_a_dir / "metadata.json").write_text(json.dumps({
            "doc_id": doc_a_id,
            "doc_no": "1091/CV-VP",
            "title": "Công văn chỉ đạo",
            "doc_date": "20/06/2026",
            "issuing_agency": "Sở Nội Vụ"
        }), encoding="utf-8")
        
        # Scenario B: User account scrape (INVALID)
        doc_b_id = "incoming_user_b"
        doc_b_dir = queue_incoming / doc_b_id
        doc_b_dir.mkdir(parents=True, exist_ok=True)
        manifest_b = {
            "schema_version": "2.0.0",
            "source": "QLVB",
            "direction": "incoming",
            "doc_id": doc_b_id,
            "external_doc_id": doc_b_id,
            "document_number": "mnmt.phanthimai",
            "issued_date": "",
            "issuing_agency": "",
            "summary": "mnmt.phanthimai | Phan Thị Mai",
            "downloaded_at": "2026-06-23T23:00:00",
            "main_document": None,
            "attachments": [],
            "sync": {
                "planner_kpi_status": "PENDING",
                "planner_kpi_document_id": None,
                "last_sync_at": None,
                "last_error": None
            }
        }
        with (doc_b_dir / "manifest.json").open("w", encoding="utf-8") as f:
            json.dump(manifest_b, f)
            
        # Correlating files dir
        files_b_dir = files_incoming / f"{doc_b_id}_mnmt_phanthimai"
        files_b_dir.mkdir(parents=True, exist_ok=True)
        (files_b_dir / "metadata.json").write_text(json.dumps({"doc_id": doc_b_id, "doc_no": "mnmt.phanthimai", "title": "Phan Thị Mai"}), encoding="utf-8")
        
        # Scenario C: Valid document but missing main document file (SUSPICIOUS)
        doc_c_id = "incoming_suspicious_c"
        doc_c_dir = queue_incoming / doc_c_id
        doc_c_dir.mkdir(parents=True, exist_ok=True)
        manifest_c = {
            "schema_version": "2.0.0",
            "source": "QLVB",
            "direction": "incoming",
            "doc_id": doc_c_id,
            "external_doc_id": doc_c_id,
            "document_number": "419/QĐ/ĐU",
            "issued_date": "20/06/2026",
            "issuing_agency": "Đảng Ủy",
            "summary": "Quyết định khen thưởng",
            "downloaded_at": "2026-06-23T23:00:00",
            "main_document": {
                "filename": "missing.pdf",
                "size_bytes": 100,
                "sha256": "abcdef",
                "relative_path": "missing.pdf"
            },
            "attachments": [],
            "sync": {
                "planner_kpi_status": "PENDING",
                "planner_kpi_document_id": None,
                "last_sync_at": None,
                "last_error": None
            }
        }
        with (doc_c_dir / "manifest.json").open("w", encoding="utf-8") as f:
            json.dump(manifest_c, f)
            
        # 1. Run Audit in DRY-RUN mode
        print("Running dry-run audit...")
        report = run_audit(apply=False, data_path=data_root)
        
        st = report["stats"]
        assert st["total_queue"] == 3, f"Expected 3 queue items, got {st['total_queue']}"
        assert st["queue_valid"] == 1, f"Expected 1 valid queue, got {st['queue_valid']}"
        assert st["queue_suspicious"] == 1, f"Expected 1 suspicious queue, got {st['queue_suspicious']}"
        assert st["queue_invalid"] == 1, f"Expected 1 invalid queue, got {st['queue_invalid']}"
        
        # Verify no files were moved in dry-run
        assert doc_b_dir.exists(), "Dry-run moved files when it shouldn't!"
        assert doc_c_dir.exists(), "Dry-run moved files when it shouldn't!"
        
        # 2. Run Audit with --apply
        print("Running audit with quarantine apply...")
        report_apply = run_audit(apply=True, data_path=data_root)
        
        # Valid doc must still exist
        assert doc_a_dir.exists(), "Valid document was removed!"
        assert files_a_dir.exists(), "Valid source folder was removed!"
        
        # Invalid and Suspicious should be moved (quarantined)
        assert not doc_b_dir.exists(), "Invalid document was not quarantined!"
        assert not files_b_dir.exists(), "Invalid source folder was not quarantined!"
        assert not doc_c_dir.exists(), "Suspicious document (missing main file) was not quarantined!"
        
        # Check that quarantine folder contains the items
        q_timestamp_dir = data_root / "quarantine" / report_apply["timestamp"]
        assert q_timestamp_dir.exists(), "Quarantine directory not created"
        assert (q_timestamp_dir / "queue" / "incoming" / doc_b_id).exists(), "Quarantined queue folder missing"
        assert (q_timestamp_dir / "files" / "incoming" / files_b_dir.name).exists(), "Quarantined source folder missing"
        assert (q_timestamp_dir / "queue" / "incoming" / doc_c_id).exists(), "Quarantined suspicious queue folder missing"
        
        print("Audit and quarantine flow integration tests PASSED!")
        
    finally:
        # Clean up temp test directory
        if data_root.exists():
            shutil.rmtree(data_root)


def main():
    test_validation_filters()
    test_audit_quarantine_flow()
    print("\nALL VALIDATION AND AUDIT TESTS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    main()
