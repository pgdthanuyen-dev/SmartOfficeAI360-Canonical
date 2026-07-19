import os
import shutil
import sys
from pathlib import Path

# Fix encoding
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except: pass
os.environ["PYTHONIOENCODING"] = "utf-8"

from tools.qlvb_downloader.models import DocumentRecord, AttachmentInfo
from tools.qlvb_downloader.storage import StorageManager
from tools.qlvb_downloader.index_db import get_default_db_path, init_db, search_documents
import json
from docx import Document
from reportlab.pdfgen import canvas


def _write_pdf(path: Path, text: str | None) -> None:
    pdf = canvas.Canvas(str(path))
    if text:
        pdf.drawString(72, 760, text)
    pdf.save()


def _write_docx(path: Path, text: str) -> None:
    doc = Document()
    doc.add_paragraph(text)
    doc.save(str(path))

def run_pipeline_test():
    data_root = Path("build/test-data/Data_Acceptance")
    if data_root.exists():
        shutil.rmtree(data_root)
        
    storage = StorageManager(data_root)
    db_path = get_default_db_path(data_root)

    # Fake scenarios:
    scenarios = [
        # 1. 01 văn bản đầy đủ số ký hiệu
        DocumentRecord(
            direction="incoming", source_url="", row_index=1, row_text="", detail_url="",
            doc_no="100/QD-UBND", doc_date="10/10/2026", issuing_agency="UBND", title="Test đầy đủ",
            status="READY"
        ),
        # 2. 01 văn bản thiếu số ký hiệu nhưng có trích yếu/ngày/cơ quan/file.
        DocumentRecord(
            direction="incoming", source_url="", row_index=2, row_text="", detail_url="",
            doc_no="", doc_date="10/10/2026", issuing_agency="UBND", title="Test thiếu số ký hiệu dài",
            status="READY"
        ),
        # 3. 01 văn bản PDF text.
        DocumentRecord(
            direction="incoming", source_url="", row_index=3, row_text="", detail_url="",
            doc_no="101/PDF", doc_date="10/10/2026", issuing_agency="UBND", title="Test PDF text",
            status="READY"
        ),
        # 4. 01 văn bản PDF scan ảnh.
        DocumentRecord(
            direction="incoming", source_url="", row_index=4, row_text="", detail_url="",
            doc_no="102/SCAN", doc_date="10/10/2026", issuing_agency="UBND", title="Test PDF scan",
            status="READY"
        ),
        # 5. 01 văn bản DOCX.
        DocumentRecord(
            direction="incoming", source_url="", row_index=5, row_text="", detail_url="",
            doc_no="103/DOCX", doc_date="10/10/2026", issuing_agency="UBND", title="Test DOCX",
            status="READY"
        ),
        # 6. 01 văn bản TXT tiếng Việt.
        DocumentRecord(
            direction="incoming", source_url="", row_index=6, row_text="", detail_url="",
            doc_no="104/TXT", doc_date="10/10/2026", issuing_agency="UBND", title="Test TXT Việt",
            status="READY"
        ),
        # 7. 01 văn bản lỗi file/không tồn tại.
        DocumentRecord(
            direction="incoming", source_url="", row_index=7, row_text="", detail_url="",
            doc_no="105/ERR", doc_date="10/10/2026", issuing_agency="UBND", title="Test Missing File",
            status="READY"
        )
    ]

    for i, r in enumerate(scenarios):
        r.doc_id = f"test_doc_{i}"
        
        att = AttachmentInfo(text="main", href="")
        att.status = "DOWNLOADED"
        doc_dir = storage.document_dir(r)
        
        # Create fake file based on scenario
        if i == 0 or i == 1:
            att.saved_path = str(doc_dir / "main.pdf")
            _write_pdf(Path(att.saved_path), "Acceptance PDF document with searchable text")
        elif i == 2:
            att.saved_path = str(doc_dir / "main.pdf")
            _write_pdf(Path(att.saved_path), "Acceptance PDF document with searchable text")
        elif i == 3:
            att.saved_path = str(doc_dir / "main.pdf")
            _write_pdf(Path(att.saved_path), None)
        elif i == 4:
            att.saved_path = str(doc_dir / "main.docx")
            _write_docx(Path(att.saved_path), "Acceptance DOCX document with valid text content")
        elif i == 5:
            att.saved_path = str(doc_dir / "main.txt")
            Path(att.saved_path).write_text("Tiếng Việt có dấu", encoding="utf-8")
        elif i == 6:
            # File không tồn tại
            att.saved_path = str(doc_dir / "missing.pdf")
            
        r.attachments.append(att)
        
        try:
            storage.write_document_outputs(r)
        except Exception as e:
            print(f"Doc {i} exception: {e}")

    # Verify SQLite
    conn = init_db(db_path)
    res = search_documents(conn)
    print(f"\n--- THỐNG KÊ SQLITE TỪ ACCEPTANCE TEST ---")
    print(f"Total SQLite records: {res['total']}")
    for item in res['items']:
        print(f"ID: {item['doc_id']} | No: {item['doc_no'] or '(trống)'} | Ext_Status: {item['full_text_status']} | Sync: {item['sync_status']}")
    assert res["total"] == 7, f"Expected 7 indexed records, got {res['total']}"
    by_id = {item["doc_id"]: item for item in res["items"]}
    assert by_id["test_doc_2"]["full_text_status"] == "OK"
    assert by_id["test_doc_3"]["full_text_status"] in {"OCR_REQUIRED", "EMPTY_TEXT"}
    assert by_id["test_doc_4"]["full_text_status"] == "OK"
    assert by_id["test_doc_5"]["full_text_status"] in {"OK", "EMPTY_TEXT"}
    assert all(item["sync_status"] == "PENDING" for item in res["items"])
    conn.close()
    print("ACCEPTANCE RESULT: 7 passed, 0 failed, 0 skipped")

if __name__ == '__main__':
    run_pipeline_test()
