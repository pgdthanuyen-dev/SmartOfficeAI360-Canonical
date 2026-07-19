from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from .parser import validate_record_data, clean_text
from .paths import project_root
from .storage import sha256_checksum


def scan_queue_item(item_dir: Path, direction: str) -> dict[str, Any]:
    """
    Scans a queue item directory and returns its audit report.
    Returns:
        {
            "type": "queue",
            "direction": direction,
            "path": str(item_dir),
            "name": item_dir.name,
            "status": "VALID" | "SUSPICIOUS" | "INVALID",
            "reason": str,
            "quarantine_candidate": bool,
            "metadata": dict
        }
    """
    manifest_path = item_dir / "manifest.json"
    
    # Check if directory name itself looks like a username
    # E.g. incoming_90bd402fb262 is normal, but if name is raw username
    # or matches name formats
    # First, let's look for manifest
    if not manifest_path.exists():
        # Check if fallback folder exists (READY/READY.ok)
        old_dir = item_dir / "READY"
        if old_dir.exists() and (old_dir / "READY.ok").exists():
            metadata_path = old_dir / "metadata.json"
            files_manifest_path = old_dir / "files_manifest.json"
            metadata = {}
            if metadata_path.exists():
                try:
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
                except Exception:
                    pass
            
            doc_no = metadata.get("doc_no") or metadata.get("document_number") or ""
            title = metadata.get("title") or metadata.get("summary") or ""
            doc_date = metadata.get("doc_date") or metadata.get("issued_date") or ""
            agency = metadata.get("issuing_agency") or metadata.get("agency") or ""
            
            status, reason = validate_record_data(doc_no, title, doc_date, agency, main_doc_meta=None)
            
            # Check main file in fallback
            files_info = {}
            if files_manifest_path.exists():
                try:
                    files_info = json.loads(files_manifest_path.read_text(encoding="utf-8-sig"))
                except Exception:
                    pass
            
            # Look for downloaded files in READY
            main_file_found = False
            files_list = files_info.get("files", [])
            if files_list:
                for f in files_list:
                    filename = f.get("filename")
                    if filename and (old_dir / filename).exists():
                        main_file_found = True
                        break
            else:
                # Check any file in READY that's not metadata/manifest/READY.ok
                for f_path in old_dir.iterdir():
                    if f_path.is_file() and f_path.name not in ["metadata.json", "files_manifest.json", "READY.ok"]:
                        main_file_found = True
                        break
            
            if status == "VALID" and not main_file_found:
                status = "SUSPICIOUS"
                reason = "Thiếu file văn bản chính trong hàng đợi cũ"
                
            return {
                "type": "queue",
                "direction": direction,
                "path": str(item_dir),
                "name": item_dir.name,
                "status": status,
                "reason": reason,
                "quarantine_candidate": status in ["INVALID", "SUSPICIOUS"] or not main_file_found,
                "metadata": {
                    "doc_no": doc_no,
                    "title": title,
                    "doc_date": doc_date,
                    "agency": agency,
                    "format": "old_fallback"
                }
            }
        
        # Completely empty or non-compliant directory
        # Check files inside
        files = [f.name for f in item_dir.iterdir() if f.is_file()]
        if not files:
            return {
                "type": "queue",
                "direction": direction,
                "path": str(item_dir),
                "name": item_dir.name,
                "status": "INVALID",
                "reason": "Thư mục hàng đợi trống và không có manifest.json",
                "quarantine_candidate": True,
                "metadata": {}
            }
        else:
            return {
                "type": "queue",
                "direction": direction,
                "path": str(item_dir),
                "name": item_dir.name,
                "status": "INVALID",
                "reason": "Thư mục hàng đợi không có manifest.json hợp lệ",
                "quarantine_candidate": True,
                "metadata": {}
            }
            
    # Try parsing manifest
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except Exception as e:
        return {
            "type": "queue",
            "direction": direction,
            "path": str(item_dir),
            "name": item_dir.name,
            "status": "INVALID",
            "reason": f"Không thể đọc manifest.json (lỗi JSON: {e})",
            "quarantine_candidate": True,
            "metadata": {}
        }
        
    # Standardize schema check
    required_fields = [
        "schema_version", "source", "direction", "doc_id", "external_doc_id",
        "document_number", "issued_date", "issuing_agency", "summary",
        "downloaded_at", "main_document", "sync"
    ]
    missing_fields = [field for field in required_fields if field not in manifest]
    if missing_fields:
        return {
            "type": "queue",
            "direction": direction,
            "path": str(item_dir),
            "name": item_dir.name,
            "status": "INVALID",
            "reason": f"Lỗi schema manifest: thiếu các trường {', '.join(missing_fields)}",
            "quarantine_candidate": True,
            "metadata": manifest
        }
        
    # Check schema_version
    if manifest.get("schema_version") != "2.0.0":
        return {
            "type": "queue",
            "direction": direction,
            "path": str(item_dir),
            "name": item_dir.name,
            "status": "SUSPICIOUS",
            "reason": f"Phiên bản schema manifest không khớp (yêu cầu '2.0.0', có '{manifest.get('schema_version')}')",
            "quarantine_candidate": True,
            "metadata": manifest
        }
        
    # Check sync object details
    sync_obj = manifest.get("sync") or {}
    required_sync_fields = ["planner_kpi_status", "planner_kpi_document_id", "last_sync_at", "last_error"]
    missing_sync = [f for f in required_sync_fields if f not in sync_obj]
    if missing_sync:
        return {
            "type": "queue",
            "direction": direction,
            "path": str(item_dir),
            "name": item_dir.name,
            "status": "SUSPICIOUS",
            "reason": f"Lỗi schema manifest: thiếu các trường sync {', '.join(missing_sync)}",
            "quarantine_candidate": True,
            "metadata": manifest
        }
        
    # Run content validation first to catch user/account lists immediately
    doc_no = manifest.get("document_number") or ""
    title = manifest.get("summary") or ""
    doc_date = manifest.get("issued_date") or ""
    agency = manifest.get("issuing_agency") or ""
    
    status, reason = validate_record_data(doc_no, title, doc_date, agency, main_doc_meta=None)
    if status == "INVALID":
        return {
            "type": "queue",
            "direction": direction,
            "path": str(item_dir),
            "name": item_dir.name,
            "status": "INVALID",
            "reason": reason,
            "quarantine_candidate": True,
            "metadata": manifest
        }
        
    # Verify main_document fields
    main_doc = manifest.get("main_document")
    if main_doc is None:
        return {
            "type": "queue",
            "direction": direction,
            "path": str(item_dir),
            "name": item_dir.name,
            "status": "SUSPICIOUS",
            "reason": "Thiếu file văn bản chính (main_document is null)",
            "quarantine_candidate": True,
            "metadata": manifest
        }
    if not main_doc.get("filename") or "size_bytes" not in main_doc or "sha256" not in main_doc:
        return {
            "type": "queue",
            "direction": direction,
            "path": str(item_dir),
            "name": item_dir.name,
            "status": "INVALID",
            "reason": "Lỗi schema manifest: main_document thiếu filename, size_bytes hoặc sha256",
            "quarantine_candidate": True,
            "metadata": manifest
        }
        
    # Run content validation
    status, reason = validate_record_data(doc_no, title, doc_date, agency, main_doc_meta=main_doc)
    
    # If content validates, verify files existence & size & sha256
    if status == "VALID":
        # Check main document file
        main_filename = main_doc.get("filename")
        main_filepath = item_dir / main_filename
        if not main_filepath.exists():
            status = "SUSPICIOUS"
            reason = f"Thiếu file văn bản chính: {main_filename}"
        else:
            # Check size
            expected_size = main_doc.get("size_bytes")
            actual_size = main_filepath.stat().st_size
            if actual_size != expected_size:
                status = "SUSPICIOUS"
                reason = f"Sai lệch dung lượng file chính {main_filename} (kỳ vọng {expected_size}, thực tế {actual_size})"
            else:
                # Check sha256
                expected_sha = main_doc.get("sha256")
                actual_sha = sha256_checksum(main_filepath)
                if actual_sha != expected_sha:
                    status = "SUSPICIOUS"
                    reason = f"Sai lệch checksum SHA256 file chính {main_filename}"
                    
        # Check attachments
        attachments = manifest.get("attachments") or []
        for att in attachments:
            att_filename = att.get("filename")
            if not att_filename:
                continue
            att_filepath = item_dir / att_filename
            if not att_filepath.exists():
                status = "SUSPICIOUS"
                reason = f"Thiếu file đính kèm: {att_filename}"
                break
            # Check size
            expected_size = att.get("size_bytes")
            actual_size = att_filepath.stat().st_size
            if expected_size is not None and actual_size != expected_size:
                status = "SUSPICIOUS"
                reason = f"Sai lệch dung lượng file đính kèm {att_filename} (kỳ vọng {expected_size}, thực tế {actual_size})"
                break
            # Check sha256
            expected_sha = att.get("sha256")
            if expected_sha:
                actual_sha = sha256_checksum(att_filepath)
                if actual_sha != expected_sha:
                    status = "SUSPICIOUS"
                    reason = f"Sai lệch checksum SHA256 file đính kèm {att_filename}"
                    break

    # We determine if quarantine candidate
    # Quarantine if INVALID, or if SUSPICIOUS due to missing main file / manifest error
    quarantine = (status == "INVALID") or (status == "SUSPICIOUS" and ("Thiếu file" in reason or "manifest" in reason.lower()))

    return {
        "type": "queue",
        "direction": direction,
        "path": str(item_dir),
        "name": item_dir.name,
        "status": status,
        "reason": reason,
        "quarantine_candidate": quarantine,
        "metadata": manifest
    }


def scan_files_item(item_dir: Path, direction: str, invalid_doc_ids: set[str], suspicious_doc_ids: set[str]) -> dict[str, Any]:
    """
    Scans a download source directory in Data/files and returns its audit report.
    """
    metadata_path = item_dir / "metadata.json"
    status_path = item_dir / "status.json"
    
    # 1. Parse metadata if exists
    metadata = {}
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
        except Exception:
            pass
            
    doc_no = metadata.get("doc_no") or metadata.get("document_number") or ""
    title = metadata.get("title") or metadata.get("summary") or ""
    doc_date = metadata.get("doc_date") or metadata.get("issued_date") or ""
    agency = metadata.get("issuing_agency") or metadata.get("agency") or ""
    doc_id = metadata.get("doc_id") or ""
    
    # Check if doc_id was matched from parent directory name if not in metadata
    if not doc_id:
        # Folder pattern: <doc_id>_<slug>
        # e.g., incoming_90bd402fb262_Ve_viec_...
        # or it could be just a username list folder
        # Try to find incoming_<hash> or outgoing_<hash> prefix
        match = re.match(r"^((?:incoming|outgoing)_[a-f0-9]+)", item_dir.name)
        if match:
            doc_id = match.group(1)

    status = "VALID"
    reason = "Hợp lệ"
    
    # Check against known queue items
    if doc_id in invalid_doc_ids:
        status = "INVALID"
        reason = f"Thuộc về hàng đợi không hợp lệ: {doc_id}"
    elif doc_id in suspicious_doc_ids:
        status = "SUSPICIOUS"
        reason = f"Thuộc về hàng đợi nghi ngờ: {doc_id}"
    else:
        # Independent validation
        if metadata:
            status, reason = validate_record_data(doc_no, title, doc_date, agency)
        else:
            # Check folder name for user list patterns
            username_pattern = re.compile(r"^[a-z0-9_.-]+$")
            dot_pattern = re.compile(r"^[a-z]{2,8}\.[a-z]{2,20}(?:\.[a-z]{2,20})*$")
            # If folder name matches dot pattern or has a vertical bar, or is named after a user
            name_only = item_dir.name
            if "_" in name_only:
                parts = name_only.split("_")
                # check if first parts look like username
                if any(dot_pattern.match(p.lower()) for p in parts):
                    status = "INVALID"
                    reason = f"Tên thư mục gốc chứa định dạng tài khoản: {item_dir.name}"
            elif dot_pattern.match(name_only.lower()) or "|" in name_only:
                status = "INVALID"
                reason = f"Tên thư mục gốc giống tài khoản người dùng: {name_only}"

    # Also check if it's completely empty
    files = [f for f in item_dir.iterdir() if f.is_file()]
    if not files and status == "VALID":
        status = "SUSPICIOUS"
        reason = "Thư mục trống không có tệp tin"
        
    quarantine = (status == "INVALID") or (status == "SUSPICIOUS" and ("Thiếu file" in reason or "trống" in reason or "hàng đợi" in reason))

    return {
        "type": "file",
        "direction": direction,
        "path": str(item_dir),
        "name": item_dir.name,
        "status": status,
        "reason": reason,
        "quarantine_candidate": quarantine,
        "metadata": {
            "doc_id": doc_id,
            "doc_no": doc_no,
            "title": title,
            "doc_date": doc_date,
            "agency": agency
        }
    }


def format_report_txt(reports: list[dict[str, Any]], stats: dict[str, int]) -> str:
    lines = []
    lines.append("=" * 100)
    lines.append(" BÁO CÁO KIỂM TRA & ĐÁNH GIÁ CHẤT LƯỢNG DỮ LIỆU HÀNG ĐỢI QLVB DOWNLOADER")
    lines.append(f" Thời gian thực hiện: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    lines.append("=" * 100)
    lines.append("")
    lines.append("THỐNG KÊ CHUNG:")
    lines.append(f" - Tổng số hàng đợi (Queue) quét:  {stats['total_queue']}")
    lines.append(f"   + Hợp lệ (VALID):             {stats['queue_valid']}")
    lines.append(f"   + Nghi ngờ (SUSPICIOUS):      {stats['queue_suspicious']}")
    lines.append(f"   + Không hợp lệ (INVALID):      {stats['queue_invalid']}")
    lines.append("")
    lines.append(f" - Tổng số thư mục nguồn (Files) quét: {stats['total_files']}")
    lines.append(f"   + Hợp lệ (VALID):             {stats['files_valid']}")
    lines.append(f"   + Nghi ngờ (SUSPICIOUS):      {stats['files_suspicious']}")
    lines.append(f"   + Không hợp lệ (INVALID):      {stats['files_invalid']}")
    lines.append("")
    lines.append(f" - Số lượng đề xuất CÁCH LY (Quarantine): {stats['total_quarantine_candidates']}")
    if stats.get('quarantined_count', 0) > 0:
        lines.append(f" - TRẠNG THÁI THỰC THI: Đã di chuyển cách ly {stats['quarantined_count']} thư mục.")
    else:
        lines.append(" - TRẠNG THÁI THỰC THI: Chế độ DRY-RUN (Chỉ báo cáo, không di chuyển dữ liệu).")
    lines.append("")
    
    # Detailed Table
    lines.append("-" * 120)
    lines.append(f"{'LOẠI':<8} | {'HƯỚNG':<8} | {'TRẠNG THÁI':<10} | {'TÊN THƯ MỤC / DOC_ID':<35} | {'LÝ DO ĐÁNH GIÁ'}")
    lines.append("-" * 120)
    
    for r in reports:
        if r["status"] == "VALID" and r["type"] == "file":
            # Avoid cluttering the report with files that are VALID
            continue
        status_disp = r["status"]
        if status_disp == "INVALID":
            status_disp = "INVALID ❌"
        elif status_disp == "SUSPICIOUS":
            status_disp = "WARNING ⚠️"
        else:
            status_disp = "VALID  ✅"
            
        type_disp = "Queue" if r["type"] == "queue" else "Files"
        
        name_disp = r["name"]
        if len(name_disp) > 33:
            name_disp = name_disp[:30] + "..."
            
        lines.append(f"{type_disp:<8} | {r['direction']:<8} | {status_disp:<10} | {name_disp:<35} | {r['reason']}")
        
    lines.append("-" * 120)
    return "\n".join(lines)


def run_audit(apply: bool = False, data_path: Path | None = None) -> dict[str, Any]:
    if not data_path:
        data_path = project_root() / "Data"
        
    queue_root = data_path / "queue"
    files_root = data_path / "files"
    reports_root = data_path / "reports"
    reports_root.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    quarantine_root = data_path / "quarantine" / timestamp
    
    scanned_results = []
    
    # Keep track of IDs to cross-reference with file paths
    invalid_queue_ids = set()
    suspicious_queue_ids = set()
    
    stats = {
        "total_queue": 0,
        "queue_valid": 0,
        "queue_suspicious": 0,
        "queue_invalid": 0,
        "total_files": 0,
        "files_valid": 0,
        "files_suspicious": 0,
        "files_invalid": 0,
        "total_quarantine_candidates": 0,
        "quarantined_count": 0
    }
    
    # 1. Scan Queue directories
    for direction in ["incoming", "outgoing"]:
        dir_path = queue_root / direction
        if not dir_path.exists():
            continue
        for item in dir_path.iterdir():
            if item.is_dir() and item.name not in ["__pycache__", "browser_profile"]:
                stats["total_queue"] += 1
                res = scan_queue_item(item, direction)
                scanned_results.append(res)
                
                # Classify
                if res["status"] == "VALID":
                    stats["queue_valid"] += 1
                elif res["status"] == "SUSPICIOUS":
                    stats["queue_suspicious"] += 1
                    suspicious_queue_ids.add(res["name"])
                else:
                    stats["queue_invalid"] += 1
                    invalid_queue_ids.add(res["name"])
                    
                if res["quarantine_candidate"]:
                    stats["total_quarantine_candidates"] += 1

    # 2. Scan Files directories (source folders)
    for direction in ["incoming", "outgoing"]:
        dir_path = files_root / direction
        if not dir_path.exists():
            continue
        for item in dir_path.iterdir():
            if item.is_dir() and item.name not in ["__pycache__"]:
                stats["total_files"] += 1
                res = scan_files_item(item, direction, invalid_queue_ids, suspicious_queue_ids)
                scanned_results.append(res)
                
                # Classify
                if res["status"] == "VALID":
                    stats["files_valid"] += 1
                elif res["status"] == "SUSPICIOUS":
                    stats["files_suspicious"] += 1
                else:
                    stats["files_invalid"] += 1
                    
                if res["quarantine_candidate"]:
                    stats["total_quarantine_candidates"] += 1

    # 3. Apply quarantine migration if requested
    if apply and stats["total_quarantine_candidates"] > 0:
        quarantine_root.mkdir(parents=True, exist_ok=True)
        for r in scanned_results:
            if r["quarantine_candidate"]:
                src_path = Path(r["path"])
                if not src_path.exists():
                    continue
                    
                # Determine target quarantine path
                # e.g., Data/quarantine/<timestamp>/queue/incoming/<doc_id>/
                # or Data/quarantine/<timestamp>/files/incoming/<folder_name>/
                rel_part = src_path.relative_to(data_path)
                dest_path = quarantine_root / rel_part
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                
                try:
                    # Move folder
                    shutil.move(str(src_path), str(dest_path))
                    stats["quarantined_count"] += 1
                    r["quarantined"] = True
                    r["quarantined_at"] = dest_path.name
                except Exception as e:
                    r["quarantine_error"] = str(e)
                    r["quarantined"] = False

    # 4. Generate Reports
    json_report_path = reports_root / f"queue_audit_{timestamp}.json"
    txt_report_path = reports_root / f"queue_audit_{timestamp}.txt"
    
    # Save JSON report
    report_payload = {
        "timestamp": timestamp,
        "stats": stats,
        "dry_run": not apply,
        "results": scanned_results
    }
    with json_report_path.open("w", encoding="utf-8") as f:
        json.dump(report_payload, f, ensure_ascii=False, indent=2)
        
    # Save TXT report
    txt_content = format_report_txt(scanned_results, stats)
    txt_report_path.write_text(txt_content, encoding="utf-8")
    
    # Also save a symlink or constant name report 'latest_audit.json' / 'latest_audit.txt'
    # so that GUI can read it easily without parsing timestamps
    try:
        latest_json = reports_root / "latest_audit.json"
        latest_txt = reports_root / "latest_audit.txt"
        with latest_json.open("w", encoding="utf-8") as f:
            json.dump(report_payload, f, ensure_ascii=False, indent=2)
        latest_txt.write_text(txt_content, encoding="utf-8")
    except Exception:
        pass
        
    return report_payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Audit QLVB queue and files, and optionally quarantine bad/invalid data.")
    parser.add_argument("--apply", action="store_true", help="Execute the quarantine migration (moves files from active directories to Data/quarantine/).")
    args = parser.parse_args()
    
    print("Bắt đầu chạy đánh giá dữ liệu hàng đợi...")
    report = run_audit(apply=args.apply)
    
    # Print summary to console
    st = report["stats"]
    print("\n--- THỐNG KÊ ĐÁNH GIÁ ---")
    print(f"Tổng số Hàng đợi (Queue): {st['total_queue']} (VALID: {st['queue_valid']}, SUSPICIOUS: {st['queue_suspicious']}, INVALID: {st['queue_invalid']})")
    print(f"Tổng số Thư mục gốc (Files): {st['total_files']} (VALID: {st['files_valid']}, SUSPICIOUS: {st['files_suspicious']}, INVALID: {st['files_invalid']})")
    print(f"Số lượng đề xuất cách ly: {st['total_quarantine_candidates']}")
    
    if args.apply:
        print(f"-> ĐÃ THỰC HIỆN CÁCH LY: Di chuyển thành công {st['quarantined_count']} thư mục lỗi vào Data/quarantine/.")
    else:
        print("-> ĐANG CHẠY CHẾ ĐỘ DRY-RUN: Không có dữ liệu nào bị di chuyển. Để di chuyển thực tế, chạy với tham số --apply.")
        
    # Print location of report
    print(f"Báo cáo chi tiết đã lưu tại: Data/reports/latest_audit.txt và latest_audit.json\n")
