from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from tools.qlvb_downloader.config import load_config
from tools.qlvb_downloader.index_db import upsert_document
from tools.qlvb_downloader.models import now_iso
from tools.qlvb_downloader.parser import build_header_map, map_row_to_canonical_record, validate_record_data


REPAIR_FIELDS = {
    "document_number": "doc_no",
    "issued_date": "doc_date",
    "issuing_agency": "issuing_agency",
    "summary": "title",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def find_metadata(root: Path, direction: str, doc_id: str) -> tuple[Path | None, dict[str, Any] | None]:
    files_dir = root / "files" / direction
    if not files_dir.exists():
        return None, None
    for item in files_dir.iterdir():
        if item.is_dir() and item.name.startswith(doc_id):
            metadata_path = item / "metadata.json"
            if metadata_path.exists():
                try:
                    return metadata_path, read_json(metadata_path)
                except Exception:
                    return metadata_path, None
    return None, None


def raw_columns_from_metadata(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    if not metadata:
        return None
    raw = metadata.get("metadata", {}).get("raw_columns")
    return raw if isinstance(raw, dict) and raw else None


def classify(status: str, before: dict[str, Any], proposed: dict[str, Any], raw_columns: dict[str, Any] | None) -> tuple[str, str]:
    if not raw_columns:
        return "INSUFFICIENT_SOURCE_DATA", "low"
    if status == "INVALID":
        return "QUARANTINE", "low"
    changed = any(str(before.get(k, "") or "") != str(proposed.get(v, "") or "") for k, v in REPAIR_FIELDS.items())
    if changed:
        return "REPAIR", "high" if status == "VALID" else "medium"
    return "UNCHANGED", "high" if status == "VALID" else "medium"


def build_proposal(manifest: dict[str, Any], direction: str, raw_columns: dict[str, Any] | None) -> tuple[dict[str, Any], str, str]:
    if not raw_columns:
        return {}, "INVALID", "Missing raw_columns"

    headers = list(raw_columns.keys())
    cells = list(raw_columns.values())
    header_map = build_header_map(headers)
    if not header_map and len(cells) > 2:
        header_map = {
            "stt": 0,
            "doc_no": 1,
            "doc_date_incoming": 2,
            "doc_date_outgoing": 2,
            "agency_incoming": 3,
            "agency_outgoing": 3,
            "title": 4,
        }

    proposed = map_row_to_canonical_record(cells, header_map, direction)
    status, reason = validate_record_data(
        proposed.get("doc_no", ""),
        proposed.get("title", ""),
        proposed.get("doc_date", ""),
        proposed.get("issuing_agency", ""),
        proposed.get("mapping_warnings", ""),
        main_doc_meta=manifest.get("main_document"),
        attachments_meta=manifest.get("attachments"),
    )
    return proposed, status, reason


def manifest_before(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "document_number": manifest.get("document_number", ""),
        "issued_date": manifest.get("issued_date", ""),
        "issuing_agency": manifest.get("issuing_agency", ""),
        "summary": manifest.get("summary", ""),
        "validation_status": manifest.get("validation_status", ""),
        "mapping_warnings": manifest.get("mapping_warnings", ""),
    }


def proposed_after(proposed: dict[str, Any], status: str) -> dict[str, Any]:
    return {
        "document_number": proposed.get("doc_no", ""),
        "issued_date": proposed.get("doc_date", ""),
        "issuing_agency": proposed.get("issuing_agency", ""),
        "summary": proposed.get("title", ""),
        "validation_status": status,
        "mapping_warnings": proposed.get("mapping_warnings", ""),
    }


def apply_repair(manifest_path: Path, manifest: dict[str, Any], proposed: dict[str, Any], status: str, root: Path, direction: str) -> None:
    manifest["document_number"] = proposed.get("doc_no", "")
    manifest["summary"] = proposed.get("title", "")
    manifest["issued_date"] = proposed.get("doc_date", "")
    manifest["issuing_agency"] = proposed.get("issuing_agency", "")
    manifest["validation_status"] = status
    manifest["audit_label"] = "UNAUDITED"
    manifest["parser_version"] = "v2"
    manifest["mapping_warnings"] = proposed.get("mapping_warnings", "")
    manifest["canonicalized_at"] = now_iso()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    from tools.qlvb_downloader.index_db import get_default_db_path, init_db

    db_path = get_default_db_path(root)
    with sqlite3.connect(db_path) as conn:
        init_db(conn)
        doc_dict = manifest.copy()
        doc_dict["doc_no"] = manifest["document_number"]
        doc_dict["doc_date"] = manifest["issued_date"]
        doc_dict["title"] = manifest["summary"]
        doc_dict["direction"] = direction
        doc_dict["parser_version"] = "v2"
        doc_dict["mapping_warnings"] = manifest["mapping_warnings"]
        doc_dict["canonicalized_at"] = manifest["canonicalized_at"]
        doc_dict["sync"] = manifest.get("sync", {})
        upsert_document(conn, doc_dict)


def write_reports(root: Path, mode: str, stats: dict[str, Any], records: list[dict[str, Any]]) -> tuple[Path, Path]:
    report_dir = root / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = now_iso().replace(":", "").replace("-", "").replace("T", "_")
    json_path = report_dir / f"repair_queue_mapping_{mode}_{stamp}.json"
    md_path = report_dir / f"repair_queue_mapping_{mode}_{stamp}.md"
    payload = {"mode": mode, "generated_at": now_iso(), "stats": stats, "records": records}
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# repair_queue_mapping {mode}",
        "",
        "## Statistics",
        "",
    ]
    for key in ["total", "repairable", "repaired", "unchanged", "quarantine_required", "quarantined", "insufficient_source_data", "duplicates_prevented", "errors"]:
        lines.append(f"- {key}: {stats.get(key, 0)}")
    lines.extend(["", "## Records", ""])
    for record in records:
        lines.append(f"- {record['proposed_action']}: {record['manifest_path']} | confidence={record['repair_confidence']} | status={record.get('validation_status', '')}")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair and canonicalize metadata of downloaded queue")
    parser.add_argument("--dry-run", action="store_true", help="Preview report only; do not write manifests or DB")
    parser.add_argument("--apply", action="store_true", help="Write manifest.json and update SQLite")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        print("Please provide either --dry-run or --apply")
        return 2
    if args.dry_run and args.apply:
        print("Use only one of --dry-run or --apply")
        return 2

    cfg = load_config()
    root = cfg.root_path
    queue_dir = root / "queue"
    mode = "dry_run" if args.dry_run else "apply"
    records: list[dict[str, Any]] = []
    errors = 0
    doc_id_counts: Counter[str] = Counter()

    for direction in ["incoming", "outgoing"]:
        d_path = queue_dir / direction
        if not d_path.exists():
            continue
        for folder in sorted(d_path.iterdir()):
            if not folder.is_dir() or folder.name.endswith("_ERROR"):
                continue
            manifest_path = folder / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                manifest = read_json(manifest_path)
                doc_id = manifest.get("doc_id") or folder.name
                doc_id_counts[str(doc_id)] += 1
                metadata_path, metadata = find_metadata(root, direction, str(doc_id))
                raw_columns = raw_columns_from_metadata(metadata)
                before = manifest_before(manifest)
                proposed, validation_status, reason = build_proposal(manifest, direction, raw_columns)
                action, confidence = classify(validation_status, before, proposed, raw_columns)
                after = proposed_after(proposed, validation_status) if proposed else {}
                record = {
                    "manifest_path": str(manifest_path),
                    "metadata_path": str(metadata_path) if metadata_path else "",
                    "doc_id": doc_id,
                    "direction": direction,
                    "before": before,
                    "proposed_after": after,
                    "mapping_warnings": after.get("mapping_warnings", ""),
                    "validation_status": validation_status,
                    "validation_reason": reason,
                    "repair_confidence": confidence,
                    "proposed_action": action,
                }
                records.append(record)
                if args.apply and action == "REPAIR":
                    apply_repair(manifest_path, manifest, proposed, validation_status, root, direction)
            except Exception as exc:
                errors += 1
                records.append({
                    "manifest_path": str(manifest_path),
                    "before": {},
                    "proposed_after": {},
                    "mapping_warnings": "",
                    "repair_confidence": "low",
                    "proposed_action": "ERROR",
                    "error": str(exc),
                })

    action_counts = Counter(record["proposed_action"] for record in records)
    duplicates = sum(count - 1 for count in doc_id_counts.values() if count > 1)
    stats = {
        "total": len(records),
        "repairable": action_counts.get("REPAIR", 0),
        "repaired": action_counts.get("REPAIR", 0) if args.apply else 0,
        "unchanged": action_counts.get("UNCHANGED", 0),
        "quarantine_required": action_counts.get("QUARANTINE", 0),
        "quarantined": action_counts.get("QUARANTINE", 0) if args.apply else 0,
        "insufficient_source_data": action_counts.get("INSUFFICIENT_SOURCE_DATA", 0),
        "duplicates_prevented": duplicates,
        "errors": errors + action_counts.get("ERROR", 0),
    }
    json_path, md_path = write_reports(root, mode, stats, records)

    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
