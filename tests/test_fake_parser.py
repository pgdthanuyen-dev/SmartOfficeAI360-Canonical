import sys
import os

# Fix encoding cho Windows terminal cp1252
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
# Fallback: dùng PYTHONIOENCODING
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from tools.qlvb_downloader.parser import build_record_from_row

cells = ["1", "123/UBND-VHXH", "27/04/2026", "UBND tinh", "Ve viec kiem tra he thong QLVB"]
rec = build_record_from_row("incoming", "https://example.local/list", 1, " ".join(cells), cells, "https://example.local/detail/1")
assert rec.doc_no, "doc_no phai co gia tri"
assert rec.doc_date, "doc_date phai co gia tri"
assert rec.title, "title phai co gia tri"

# Dung bytes de tranh loi encode console
msg = "OK parser fake row: doc_no={}, doc_date={}, title={}".format(
    rec.doc_no, rec.doc_date, rec.title[:30]
)
sys.stdout.buffer.write((msg + "\n").encode("utf-8"))
