from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import (
    ATTACHMENT_VALIDATED,
    DOCUMENT_NO_VALID_ATTACHMENT,
    DOCUMENT_QUEUEABLE_STATUSES,
    DocumentRecord,
    now_iso,
    safe_slug,
)
from .extractor import extract_text_for_manifest
from .index_db import upsert_document, get_default_db_path, init_db


def sha256_checksum(filepath: Path) -> str:
    h = hashlib.sha256()
    try:
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""



class StorageManager:
    def __init__(self, data_root: Path, copy_files_to_queue: bool = True, create_ready_marker: bool = True):
        self.data_root = data_root
        self.copy_files_to_queue = copy_files_to_queue
        self.create_ready_marker = create_ready_marker
        self.files_root = data_root / "files"
        self.queue_root = data_root / "queue"
        self.log_root = data_root / "logs"
        self.error_root = self.log_root / "errors"
        self._ensure()

    def _ensure(self) -> None:
        for rel in [
            "files/incoming", "files/outgoing", "queue/incoming", "queue/outgoing", "logs/errors", "runtime/playwright_profile"
        ]:
            (self.data_root / rel).mkdir(parents=True, exist_ok=True)

    def document_dir(self, record: DocumentRecord) -> Path:
        direction = "incoming" if record.direction == "incoming" else "outgoing"
        d = self.files_root / direction / record.folder_name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def find_existing_document_dir(self, record: DocumentRecord) -> Path | None:
        direction = "incoming" if record.direction == "incoming" else "outgoing"
        record.ensure_doc_id()
        root = self.files_root / direction
        if not root.exists():
            return None
        for item in root.iterdir():
            if item.is_dir() and item.name.startswith(record.doc_id):
                return item
        return None

    def existing_status(self, record: DocumentRecord) -> dict[str, Any] | None:
        existing = self.find_existing_document_dir(record)
        if not existing:
            return None
        status_path = existing / "status.json"
        if not status_path.exists():
            return None
        try:
            return json.loads(status_path.read_text(encoding="utf-8-sig"))
        except Exception:
            return None

    def queue_ready_dir(self, record: DocumentRecord) -> Path:
        direction = "incoming" if record.direction == "incoming" else "outgoing"
        record.ensure_doc_id()
        d = self.queue_root / direction / record.doc_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def get_queue_item_files(self, direction: str, doc_id: str) -> dict[str, Any] | None:
        """
        Locate the queue item files, returning the manifest/metadata and file paths.
        Supports both the new flat queue format and the old fallback READY/files format.
        """
        # New format path
        new_dir = self.queue_root / direction / doc_id
        if (new_dir / ".ready").exists() and (new_dir / "manifest.json").exists():
            try:
                manifest = json.loads((new_dir / "manifest.json").read_text(encoding="utf-8-sig"))
                return {
                    "format": "new",
                    "dir": new_dir,
                    "manifest": manifest,
                    "ready_file": new_dir / ".ready"
                }
            except Exception:
                pass

        # Old format fallback path
        old_dir = self.queue_root / direction / doc_id / "READY"
        if (old_dir / "READY.ok").exists():
            metadata_path = old_dir / "metadata.json"
            manifest_path = old_dir / "files_manifest.json"
            manifest = {}
            if metadata_path.exists():
                try:
                    manifest = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
                except Exception:
                    pass
            if manifest_path.exists():
                try:
                    files_info = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
                    manifest["files_manifest"] = files_info
                except Exception:
                    pass
            return {
                "format": "old_fallback",
                "dir": old_dir,
                "manifest": manifest,
                "ready_file": old_dir / "READY.ok"
            }
        return None

    @staticmethod
    def write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def write_document_outputs(self, record: DocumentRecord) -> dict[str, str]:
        doc_dir = self.document_dir(record)
        record.ensure_doc_id()
        validated_attachments = [
            a for a in record.attachments
            if a.status == ATTACHMENT_VALIDATED and a.saved_path
        ]
        queueable_status = record.status in DOCUMENT_QUEUEABLE_STATUSES
        if queueable_status and not validated_attachments:
            record.status = DOCUMENT_NO_VALID_ATTACHMENT
            record.error = record.error or "NO_VALID_ATTACHMENT"
            queueable_status = False
        is_ready = queueable_status
        ready_dir = self.queue_ready_dir(record) if is_ready else (self.queue_root / ("incoming" if record.direction == "incoming" else "outgoing") / f"{record.doc_id}_ERROR")

        metadata_path = doc_dir / "metadata.json"
        status_path = doc_dir / "status.json"
        metadata = record.to_dict()
        status = {
            "doc_id": record.doc_id,
            "direction": record.direction,
            "status": record.status,
            "error": record.error,
            "attachment_total": len(record.attachments),
            "attachment_downloaded": sum(1 for a in record.attachments if a.status == ATTACHMENT_VALIDATED),
            "updated_at": now_iso(),
            "document_dir": str(doc_dir),
            "ready_queue_dir": str(ready_dir),
        }
        self.write_json(metadata_path, metadata)
        self.write_json(status_path, status)
        
        if is_ready:
            ready_dir.mkdir(parents=True, exist_ok=True)
            
            # Find validated attachments. Raw downloads are not queueable.
            downloaded_attachments = validated_attachments
            
            main_doc = None
            other_atts = []
            classification_method = "fallback"
            
            if downloaded_attachments:
                # heuristic to find the main document file
                # 1. keywords: "chinh", "ky_so", "van_ban", "signed", "qd", "tt"
                keywords = ["chinh", "ky_so", "van_ban", "signed", "qd", "tt"]
                
                # Check for files containing keywords (case-insensitive)
                best_match = None
                for a in downloaded_attachments:
                    filename_lower = Path(a.saved_path).name.lower()
                    if any(k in filename_lower for k in keywords):
                        best_match = a
                        classification_method = "keyword"
                        break
                
                # 2. Check for PDF file if no keyword match
                if not best_match:
                    for a in downloaded_attachments:
                        if Path(a.saved_path).suffix.lower() == ".pdf":
                            best_match = a
                            classification_method = "extension"
                            break
                            
                # 3. Default to the first attachment
                if not best_match:
                    best_match = downloaded_attachments[0]
                    classification_method = "fallback"
                    
                main_doc = best_match
                other_atts = [a for a in downloaded_attachments if a != main_doc]
            
            # ATOMIC / SAFE WRITE:
            # Step 1: Copy files to ready_dir first
            copied_main = None
            copied_others = []
            
            if main_doc and main_doc.saved_path:
                src = Path(main_doc.saved_path)
                if src.exists():
                    dst = ready_dir / src.name
                    if src.resolve() != dst.resolve():
                        shutil.copy2(src, dst)
                    
                    # Verify file exists and has size > 0
                    if not dst.exists() or dst.stat().st_size == 0:
                        raise RuntimeError(f"Loi copy file chinh {src.name} sang queue: file rong hoac khong ton tai")
                        
                    copied_main = {
                        "filename": src.name,
                        "size_bytes": dst.stat().st_size,
                        "sha256": sha256_checksum(dst),
                        "relative_path": src.name
                    }
                    
            for a in other_atts:
                if a.saved_path:
                    src = Path(a.saved_path)
                    if src.exists():
                        dst = ready_dir / src.name
                        if src.resolve() != dst.resolve():
                            shutil.copy2(src, dst)
                        
                        # Verify file exists and has size > 0
                        if not dst.exists() or dst.stat().st_size == 0:
                            raise RuntimeError(f"Loi copy file dinh kem {src.name} sang queue: file rong hoac khong ton tai")
                            
                        copied_others.append({
                            "filename": src.name,
                            "size_bytes": dst.stat().st_size,
                            "sha256": sha256_checksum(dst),
                            "relative_path": src.name
                        })
            
            # Step 2: Write standardized manifest.json
            manifest_payload = {
                "schema_version": "2.0.0",
                "source": "QLVB",
                "direction": record.direction,
                "doc_id": record.doc_id,
                "external_doc_id": record.doc_id, # QLVB internal document ID
                "document_number": record.doc_no,
                "issued_date": record.doc_date,
                "issuing_agency": record.issuing_agency,
                "summary": record.summary or record.title,
                "downloaded_at": now_iso(),
                "classification_method": classification_method,
                "status": record.status,
                "main_document": copied_main,
                "attachments": copied_others,
                "sync": {
                    "planner_kpi_status": "PENDING",
                    "planner_kpi_document_id": None,
                    "last_sync_at": None,
                    "last_error": None
                }
            }
            
            # Step 2: Extract text to enrich manifest (Phase 2)
            try:
                manifest_payload = extract_text_for_manifest(manifest_payload, ready_dir)
            except Exception:
                pass  # Không crash pipeline nếu trích xuất lỗi

            # Step 3: Write standardized manifest.json
            self.write_json(ready_dir / "manifest.json", manifest_payload)
            
            # Step 4: Upsert to SQLite index (Phase 3)
            try:
                db_path = get_default_db_path(self.data_root)
                conn = init_db(db_path)
                try:
                    upsert_document(conn, manifest_payload)
                finally:
                    conn.close()
            except Exception:
                pass  # Không crash pipeline nếu DB bị lock hoặc lỗi

            # Step 5: Write .ready as the absolute final step
            (ready_dir / ".ready").write_text(f"READY {datetime.now().isoformat(timespec='seconds')}", encoding="utf-8")
            
            # Keep READY.ok for backward compatibility
            if self.create_ready_marker:
                (ready_dir / "READY.ok").write_text(f"READY {datetime.now().isoformat(timespec='seconds')}", encoding="utf-8")
        else:
            ready_dir.mkdir(parents=True, exist_ok=True)
            self.write_json(ready_dir / "status.json", status)
            if record.error:
                (ready_dir / "error.log").write_text(record.error, encoding="utf-8")

        return {"document_dir": str(doc_dir), "queue_ready_dir": str(ready_dir)}

    def next_download_path(self, record: DocumentRecord, suggested_filename: str | None, index: int) -> Path:
        doc_dir = self.document_dir(record)
        name = suggested_filename or f"tep_dinh_kem_{index}.bin"
        suffix = Path(name).suffix
        safe_name = safe_slug(name, 120)
        if suffix and not safe_name.lower().endswith(suffix.lower()):
            safe_name += suffix
        target = doc_dir / safe_name
        if not target.exists():
            return target
        stem = target.stem
        suffix = target.suffix
        counter = 2
        while True:
            candidate = doc_dir / f"{stem}_{counter}{suffix}"
            if not candidate.exists():
                return candidate
            counter += 1

    def write_error_artifact(self, name: str, html: str | None = None, screenshot_bytes: bytes | None = None, extra: dict[str, Any] | None = None) -> dict[str, str]:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = self.error_root / f"{stamp}_{safe_slug(name, 60)}"
        base.mkdir(parents=True, exist_ok=True)
        out: dict[str, str] = {"folder": str(base)}
        if html is not None:
            p = base / "page.html"
            p.write_text(html, encoding="utf-8", errors="ignore")
            out["html"] = str(p)
        if screenshot_bytes is not None:
            p = base / "screenshot.png"
            p.write_bytes(screenshot_bytes)
            out["screenshot"] = str(p)
        if extra is not None:
            p = base / "debug.json"
            self.write_json(p, extra)
            out["debug"] = str(p)
        return out
