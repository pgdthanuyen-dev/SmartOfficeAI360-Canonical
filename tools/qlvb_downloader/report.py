from __future__ import annotations

import csv
import html
from pathlib import Path
from typing import Any

from .models import now_iso


def append_csv_report(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "run_id", "time", "direction", "doc_id", "doc_no", "doc_date", "issuing_agency",
        "title", "status", "attachment_total", "attachment_downloaded", "document_dir", "queue_ready_dir", "error"
    ]
    exists = path.exists()
    with path.open("a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in fields})


def write_html_run_report(path: Path, summary: dict[str, Any], csv_rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    title = "Smart Office AI 360 - Bao cao tai QLVB V22.1.4"
    trs = []
    for r in csv_rows:
        status = str(r.get("status", ""))
        trs.append(
            "<tr>" + "".join([
                f"<td>{html.escape(str(r.get('direction','')))}</td>",
                f"<td>{html.escape(str(r.get('doc_no','')))}</td>",
                f"<td>{html.escape(str(r.get('doc_date','')))}</td>",
                f"<td>{html.escape(str(r.get('issuing_agency','')))}</td>",
                f"<td>{html.escape(str(r.get('title','')))[:500]}</td>",
                f"<td><b>{html.escape(status)}</b></td>",
                f"<td>{html.escape(str(r.get('attachment_downloaded','')))} / {html.escape(str(r.get('attachment_total','')))}</td>",
                f"<td>{html.escape(str(r.get('error','')))[:500]}</td>",
            ]) + "</tr>"
        )
    html_doc = f'''<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><title>{title}</title>
<style>
body{{font-family:Arial,Helvetica,sans-serif;margin:24px;background:#f5f7fb;color:#111827}}
.card{{background:#fff;border:1px solid #d9e2f1;border-radius:12px;padding:16px;margin-bottom:16px;box-shadow:0 2px 8px rgba(0,0,0,.04)}}
h1{{font-size:22px;margin:0 0 8px}} table{{border-collapse:collapse;width:100%;background:#fff}}
th,td{{border:1px solid #d8dee9;padding:8px;font-size:13px;vertical-align:top}} th{{background:#0f4c81;color:#fff;text-align:left}}
.small{{color:#4b5563;font-size:13px}}
</style></head><body>
<div class="card"><h1>{title}</h1><div class="small">Tao luc: {html.escape(now_iso())}</div>
<pre>{html.escape(str(summary))}</pre></div>
<div class="card"><h2>Danh sach ho so da xu ly</h2><table><thead><tr>
<th>Luong</th><th>So/Ky hieu</th><th>Ngay</th><th>Co quan/Noi gui</th><th>Trich yeu</th><th>Trang thai</th><th>File</th><th>Loi</th>
</tr></thead><tbody>{''.join(trs) or '<tr><td colspan="8">Chua co ho so.</td></tr>'}</tbody></table></div>
</body></html>'''
    path.write_text(html_doc, encoding="utf-8")
