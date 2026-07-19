"""
extractor.py — Phase 2: Full-text extraction từ PDF/DOCX/TXT
=============================================================
Trích xuất nội dung văn bản từ file đính kèm để làm giàu manifest
trước khi đồng bộ sang Planner KPI.

Thiết kế:
  - Graceful degradation: không crash nếu thiếu thư viện (pdfminer.six, python-docx)
  - Không sửa file gốc
  - Chỉ lưu excerpt (3.000–5.000 ký tự), không đưa toàn bộ text vào manifest
  - Bảo toàn tiếng Việt (Unicode NFD → NFC normalization)
  - Xử lý PDF scan ảnh (text trống) → OCR_REQUIRED
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("qlvb.extractor")

# ---------------------------------------------------------------------------
# Kiểm tra thư viện tùy chọn
# ---------------------------------------------------------------------------
try:
    import pdfminer.high_level as _pdfminer_hl
    import pdfminer.layout as _pdfminer_layout
    _HAS_PDFMINER = True
except ImportError:
    _HAS_PDFMINER = False
    logger.debug("[extractor] pdfminer.six chưa cài — PDF extraction không khả dụng. Cài bằng: pip install pdfminer.six")

try:
    import docx as _docx_lib
    _HAS_DOCX = True
except ImportError:
    _HAS_DOCX = False
    logger.debug("[extractor] python-docx chưa cài — DOCX extraction không khả dụng. Cài bằng: pip install python-docx")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_MAX_CHARS = 5000
EXCERPT_MAX_CHARS = 4000   # Tối đa lưu vào manifest
MIN_TEXT_FOR_VALID = 20    # Số ký tự tối thiểu để coi là có nội dung

# Các trạng thái full_text_status
STATUS_OK = "OK"
STATUS_EMPTY = "EMPTY_TEXT"
STATUS_OCR_REQUIRED = "OCR_REQUIRED"
STATUS_UNSUPPORTED = "UNSUPPORTED_FORMAT"
STATUS_LIB_MISSING = "LIBRARY_NOT_INSTALLED"
STATUS_FILE_NOT_FOUND = "FILE_NOT_FOUND"
STATUS_ERROR = "EXTRACTION_ERROR"


# ---------------------------------------------------------------------------
# Data class kết quả
# ---------------------------------------------------------------------------
@dataclass
class ExtractResult:
    success: bool
    text: str = ""
    excerpt: str = ""
    word_count: int = 0
    page_count: int | None = None
    file_type: str = ""
    status: str = STATUS_OK
    warning: str | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------
def _normalize_text(text: str) -> str:
    """Chuẩn hóa Unicode NFC và làm sạch whitespace thừa, giữ nguyên tiếng Việt."""
    if not text:
        return ""
    # NFC để gộp tổ hợp dấu → ký tự đơn (giữ tiếng Việt đầy đủ)
    text = unicodedata.normalize("NFC", text)
    # Xóa ký tự điều khiển trừ \n và \t
    text = re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]", "", text)
    # Thu gọn nhiều dòng trống liên tiếp thành tối đa 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Thu gọn khoảng trắng trên cùng dòng (nhưng giữ nguyên dòng mới)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _make_excerpt(text: str, max_chars: int = EXCERPT_MAX_CHARS) -> str:
    """Cắt text thành excerpt, ưu tiên cắt tại ranh giới câu/dòng."""
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    # Cắt tại dấu câu gần nhất trước max_chars
    cut = text[:max_chars]
    last_break = max(cut.rfind("\n"), cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if last_break > max_chars * 0.7:
        cut = cut[:last_break + 1]
    return cut.rstrip() + "\n…[truncated]"


def _count_words(text: str) -> int:
    """Đếm số từ (split by whitespace), xử lý tiếng Việt không có khoảng trắng giữa âm tiết."""
    return len(text.split()) if text else 0


# ---------------------------------------------------------------------------
# Extractors per format
# ---------------------------------------------------------------------------
def _extract_txt(path: Path, max_chars: int) -> ExtractResult:
    """Đọc plain text, thử nhiều encoding."""
    for encoding in ("utf-8-sig", "utf-8", "utf-16", "cp1258", "latin-1"):
        try:
            raw = path.read_text(encoding=encoding, errors="replace")
            text = _normalize_text(raw[:max_chars * 3])  # đọc nhiều hơn rồi cắt
            excerpt = _make_excerpt(text, max_chars)
            return ExtractResult(
                success=True,
                text=text[:max_chars],
                excerpt=excerpt,
                word_count=_count_words(text),
                file_type="TXT",
                status=STATUS_OK if len(text) >= MIN_TEXT_FOR_VALID else STATUS_EMPTY,
            )
        except Exception:
            continue
    return ExtractResult(
        success=False,
        file_type="TXT",
        status=STATUS_ERROR,
        error="Không đọc được file TXT với bất kỳ encoding nào",
    )


def _extract_pdf(path: Path, max_chars: int) -> ExtractResult:
    """Trích xuất text từ PDF bằng pdfminer.six."""
    if not _HAS_PDFMINER:
        return ExtractResult(
            success=False,
            file_type="PDF",
            status=STATUS_LIB_MISSING,
            warning="pdfminer.six chưa cài. Chạy: pip install pdfminer.six",
        )
    try:
        import io
        output = io.StringIO()
        laparams = _pdfminer_layout.LAParams(
            line_margin=0.5,
            word_margin=0.1,
            char_margin=2.0,
        )
        page_count = 0
        raw_parts: list[str] = []
        chars_collected = 0

        with open(path, "rb") as f:
            # Đếm số trang và extract
            from pdfminer.high_level import extract_pages
            from pdfminer.layout import LTTextContainer
            for page_layout in extract_pages(f, laparams=laparams):
                page_count += 1
                if chars_collected >= max_chars * 3:
                    break
                for element in page_layout:
                    if isinstance(element, LTTextContainer):
                        chunk = element.get_text()
                        raw_parts.append(chunk)
                        chars_collected += len(chunk)

        raw_text = "".join(raw_parts)
        text = _normalize_text(raw_text)

        if len(text) < MIN_TEXT_FOR_VALID:
            return ExtractResult(
                success=True,
                text="",
                excerpt="",
                word_count=0,
                page_count=page_count,
                file_type="PDF",
                status=STATUS_OCR_REQUIRED,
                warning=f"PDF có {page_count} trang nhưng không trích được text (có thể là scan ảnh). Cần OCR.",
            )

        excerpt = _make_excerpt(text, max_chars)
        return ExtractResult(
            success=True,
            text=text[:max_chars],
            excerpt=excerpt,
            word_count=_count_words(text),
            page_count=page_count,
            file_type="PDF",
            status=STATUS_OK,
        )

    except Exception as exc:
        logger.warning("[extractor] Lỗi đọc PDF %s: %s", path.name, exc)
        return ExtractResult(
            success=False,
            file_type="PDF",
            status=STATUS_ERROR,
            error=f"Lỗi đọc PDF: {exc}",
        )


def _extract_docx(path: Path, max_chars: int) -> ExtractResult:
    """Trích xuất text từ DOCX bằng python-docx."""
    if not _HAS_DOCX:
        return ExtractResult(
            success=False,
            file_type="DOCX",
            status=STATUS_LIB_MISSING,
            warning="python-docx chưa cài. Chạy: pip install python-docx",
        )
    try:
        doc = _docx_lib.Document(str(path))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        raw_text = "\n".join(paragraphs)
        text = _normalize_text(raw_text)

        # Đếm số trang ước tính từ section / page break (python-docx không có API chính xác)
        page_count = None
        core_props = doc.core_properties
        # Không thể lấy page_count trực tiếp từ python-docx

        excerpt = _make_excerpt(text, max_chars)
        return ExtractResult(
            success=True,
            text=text[:max_chars],
            excerpt=excerpt,
            word_count=_count_words(text),
            page_count=page_count,
            file_type="DOCX",
            status=STATUS_OK if len(text) >= MIN_TEXT_FOR_VALID else STATUS_EMPTY,
        )
    except Exception as exc:
        logger.warning("[extractor] Lỗi đọc DOCX %s: %s", path.name, exc)
        return ExtractResult(
            success=False,
            file_type="DOCX",
            status=STATUS_ERROR,
            error=f"Lỗi đọc DOCX: {exc}",
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def extract_text_from_file(path: str | Path, max_chars: int = DEFAULT_MAX_CHARS) -> ExtractResult:
    """
    Trích xuất text từ file PDF/DOCX/TXT.

    Parameters:
        path      : đường dẫn file (str hoặc Path)
        max_chars : số ký tự tối đa trích xuất

    Returns:
        ExtractResult — không raise exception dù gặp lỗi nào
    """
    file_path = Path(path)

    # Kiểm tra file tồn tại
    if not file_path.exists():
        return ExtractResult(
            success=False,
            file_type=file_path.suffix.upper().lstrip(".") or "UNKNOWN",
            status=STATUS_FILE_NOT_FOUND,
            error=f"File không tồn tại: {file_path}",
        )

    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        return _extract_pdf(file_path, max_chars)
    elif suffix in (".docx",):
        return _extract_docx(file_path, max_chars)
    elif suffix in (".doc",):
        # .doc (binary Word) — không hỗ trợ, cần antiword/LibreOffice
        return ExtractResult(
            success=False,
            file_type="DOC",
            status=STATUS_UNSUPPORTED,
            warning="File .doc (Word 97-2003) chưa được hỗ trợ trực tiếp. Chuyển sang .docx hoặc dùng LibreOffice.",
        )
    elif suffix in (".txt", ".csv", ".log", ".xml", ".json"):
        return _extract_txt(file_path, max_chars)
    else:
        return ExtractResult(
            success=False,
            file_type=suffix.upper().lstrip(".") or "UNKNOWN",
            status=STATUS_UNSUPPORTED,
            warning=f"Định dạng '{suffix}' chưa được hỗ trợ. Hỗ trợ: PDF, DOCX, TXT.",
        )


def extract_text_for_manifest(
    manifest: dict[str, Any],
    base_dir: str | Path,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> dict[str, Any]:
    """
    Trích xuất text từ main_document trong manifest và bổ sung các trường:
      - full_text_excerpt    : str
      - full_text_word_count : int
      - full_text_status     : str
      - full_text_warning    : str | None
      - extracted_at         : ISO datetime string

    Tham số:
        manifest : dict manifest hiện tại (schema 2.0.0)
        base_dir : thư mục chứa các file (thường là queue item dir)
        max_chars: số ký tự tối đa

    Trả về manifest đã được bổ sung (không sửa bản gốc, trả về bản copy).
    Không raise exception.
    """
    result = dict(manifest)  # shallow copy — tránh sửa manifest gốc
    base_path = Path(base_dir)

    # Đặt mặc định cho các trường mới
    result.setdefault("full_text_excerpt", None)
    result.setdefault("full_text_word_count", 0)
    result.setdefault("full_text_status", STATUS_UNSUPPORTED)
    result.setdefault("full_text_warning", None)
    result.setdefault("extracted_at", None)

    # Lấy file chính từ main_document
    main_doc_meta = manifest.get("main_document")
    if not main_doc_meta or not isinstance(main_doc_meta, dict):
        result["full_text_status"] = STATUS_UNSUPPORTED
        result["full_text_warning"] = "Không có main_document trong manifest"
        logger.debug("[extractor] Bỏ qua extract: không có main_document")
        return result

    filename = main_doc_meta.get("filename")
    if not filename:
        result["full_text_status"] = STATUS_UNSUPPORTED
        result["full_text_warning"] = "main_document.filename trống"
        return result

    file_path = base_path / filename

    logger.info("[extractor] Đang extract | file=%s", filename)
    try:
        extract = extract_text_from_file(file_path, max_chars=max_chars)
    except Exception as exc:
        # Phòng thủ tuyệt đối — không bao giờ crash pipeline
        logger.error("[extractor] Exception không mong muốn khi extract %s: %s", filename, exc)
        result["full_text_status"] = STATUS_ERROR
        result["full_text_warning"] = str(exc)
        result["extracted_at"] = datetime.now().isoformat()
        return result

    result["full_text_excerpt"] = extract.excerpt or None
    result["full_text_word_count"] = extract.word_count
    result["full_text_status"] = extract.status
    result["full_text_warning"] = extract.warning or extract.error or None
    result["extracted_at"] = datetime.now().isoformat()

    if extract.page_count is not None:
        result["full_text_page_count"] = extract.page_count

    logger.info(
        "[extractor] Kết quả | file=%s status=%s words=%d",
        filename,
        extract.status,
        extract.word_count,
    )
    return result
