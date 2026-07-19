from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urljoin, unquote

from .models import DocumentRecord, AttachmentInfo, short_hash

DATE_RE = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})\b")
DOC_NO_RE = re.compile(r"\b(\d{1,5}\s*/\s*[A-ZĐa-zđ0-9._/-]+(?:-[A-ZĐa-zđ0-9._/-]+)*)\b")
FILE_EXT_RE = re.compile(r"\.(pdf|doc|docx|xls|xlsx|ppt|pptx|zip|rar|7z|xml)(\?|$|#)", re.I)
NON_DOCUMENT_ATTACHMENT_RE = re.compile(
    r"(smartca\.vnpt\.vn/download|/(?:tailieu|tai_lieu|video)_huongdan/|(?:^|['\"/(])(?:tailieu|tai_lieu|video)_huongdan/)",
    re.I,
)

def clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = value.replace("\xa0", " ").replace("\ufeff", " ")
    value = re.sub(r"\s+", " ", value).strip()
    return value

def guess_doc_no(text: str) -> str:
    m = DOC_NO_RE.search(text or "")
    return clean_text(m.group(1)) if m else ""

def guess_date(text: str) -> str:
    m = DATE_RE.search(text or "")
    return clean_text(m.group(1)) if m else ""

def is_probable_attachment(text: str, href: str) -> bool:
    text_l = clean_text(text).lower()
    href_l = unquote(href or "").lower()
    if NON_DOCUMENT_ATTACHMENT_RE.search(href_l):
        return False
    if FILE_EXT_RE.search(href_l) or FILE_EXT_RE.search(text_l):
        return True
    keywords = [
        "download", "attachment", "getfile", "getattachment", "file", "tailieu", "tai-lieu",
        "tệp", "tep", "đính kèm", "dinh kem", "tải", "tai", "xem file", "xem tệp",
    ]
    return any(k in href_l or k in text_l for k in keywords)

def make_absolute(base_url: str, href: str | None) -> str:
    href = href or ""
    if not href:
        return ""
    if href.lower().startswith("javascript:"):
        return href
    return urljoin(base_url, href)

def attachment_from_anchor(base_url: str, text: str, href: str) -> AttachmentInfo | None:
    full = make_absolute(base_url, href)
    if not full:
        return None
    if not is_probable_attachment(text, full):
        return None
    return AttachmentInfo(text=clean_text(text) or full, href=full)

def normalize_header_name(header: str) -> str:
    """Chuẩn hóa tên cột để dễ mapping"""
    h = clean_text(header).lower().rstrip(":")
    return h

def build_header_map(headers: list[str]) -> dict[str, int]:
    """Tạo map từ tên cột chuẩn hóa sang vị trí index"""
    header_map = {}
    for idx, h in enumerate(headers):
        norm = normalize_header_name(h)
        if norm:
            if any(k in norm for k in ["số ký hiệu", "số/ký hiệu", "số văn bản", "số đến", "số đi", "ký hiệu"]):
                header_map["doc_no"] = idx
            elif any(k in norm for k in ["ngày văn bản", "ngày đến", "ngày ký"]):
                header_map["doc_date_incoming"] = idx
            elif any(k in norm for k in ["ngày ban hành"]):
                header_map["doc_date_outgoing"] = idx
            elif any(k in norm for k in ["cơ quan ban hành", "đơn vị ban hành", "nơi gửi", "cơ quan gửi"]):
                header_map["agency_incoming"] = idx
            elif any(k in norm for k in ["đơn vị soạn thảo"]):
                header_map["agency_outgoing"] = idx
            elif any(k in norm for k in ["trích yếu", "nội dung", "tiêu đề", "tên văn bản", "về việc"]):
                header_map["title"] = idx
            elif any(k in norm for k in ["số", "stt"]):
                header_map["stt"] = idx
    return header_map

def is_document_table_headers(headers: list[str]) -> bool:
    """Check if the given headers look like a document list table."""
    norm = [normalize_header_name(h) for h in headers]
    has_title = any("trích yếu" in h or "nội dung" in h for h in norm)
    has_doc_no = any("số ký hiệu" in h or "số đến" in h or "ký hiệu" in h for h in norm)
    return has_title and has_doc_no

def is_header_row(cells: list[str], header_map: dict[str, int] | None = None) -> bool:
    """Phát hiện nếu dòng hiện tại thực chất là dòng tiêu đề bị lặp lại."""
    if not cells:
        return False
    norm_cells = [normalize_header_name(c) for c in cells]
    has_title = any("trích yếu" in c or "nội dung" in c for c in norm_cells)
    has_doc_no = any("số ký hiệu" in c or "số đến" in c for c in norm_cells)
    return has_title and has_doc_no

def is_technical_row(cells: list[str]) -> bool:
    """Phát hiện dòng rác kỹ thuật không chứa dữ liệu hồ sơ"""
    if not cells: return True
    text = " ".join(cells)
    if re.match(r'^[\d\s]+$', text): return True
    if "Chi tiết Phòng ban nhận hoặc người nhận" in text:
        meaningful_cells = [c for c in cells if clean_text(c)]
        if len(meaningful_cells) <= 3: return True
    if "Không tìm thấy dữ liệu" in text: return True
    return False

def map_row_to_canonical_record(cells: list[str], header_map: dict[str, int], direction: str) -> dict:
    """Trích xuất dữ liệu dựa vào header map động"""
    cells = [clean_text(c) for c in cells]
    meta = {"raw_columns": {str(i): c for i, c in enumerate(cells)}}
    warnings = []

    def get_val(key: str) -> str:
        idx = header_map.get(key, -1)
        if 0 <= idx < len(cells):
            return cells[idx]
        return ""

    doc_no = get_val("doc_no")
    if doc_no == "1" or (doc_no.isdigit() and len(doc_no) > 6):
        warnings.append("POSSIBLE_TECHNICAL_DOC_NO")

    if direction == "incoming":
        doc_date = get_val("doc_date_incoming") or get_val("doc_date_outgoing")
        agency = get_val("agency_incoming") or get_val("agency_outgoing")
    else:
        doc_date = get_val("doc_date_outgoing") or get_val("doc_date_incoming")
        agency = get_val("agency_outgoing") or get_val("agency_incoming")

    title = get_val("title")

    # Fallback rules
    if not doc_no:
        doc_no = guess_doc_no(" | ".join(cells))
    if not doc_date:
        doc_date = guess_date(" | ".join(cells))

    # Structural checks
    if doc_date and doc_date.isdigit() and len(doc_date) > 2:
        warnings.append("INVALID_DOC_DATE")
        doc_date = ""

    if doc_no and agency and doc_no == agency:
        warnings.append("INVALID_ISSUING_AGENCY")

    if title and len(title) < 20 and title == doc_no:
        warnings.append("TECHNICAL_TITLE")
        title = ""

    meta["doc_no"] = doc_no
    meta["doc_date"] = doc_date
    meta["issuing_agency"] = agency
    meta["title"] = title
    meta["mapping_warnings"] = ";".join(warnings)
    return meta

def build_record_from_row(
    direction: str,
    source_url: str,
    row_index: int,
    row_text: str,
    cells: list[str],
    detail_url: str | None,
    headers: list[str] | None = None,
) -> DocumentRecord:
    headers = [clean_text(h) for h in (headers or [])]
    header_map = build_header_map(headers) if headers else {}

    if not header_map and len(cells) > 2:
        header_map = {"stt": 0, "doc_no": 1, "doc_date_incoming": 2, "doc_date_outgoing": 2, "agency_incoming": 3, "agency_outgoing": 3, "title": 4}

    meta = map_row_to_canonical_record(cells, header_map, direction)
    rec = DocumentRecord(
        direction=direction,
        source_url=source_url,
        row_index=row_index,
        row_text=clean_text(row_text),
        detail_url=detail_url,
        doc_no=clean_text(str(meta.get("doc_no", ""))),
        doc_date=clean_text(str(meta.get("doc_date", ""))),
        issuing_agency=clean_text(str(meta.get("issuing_agency", ""))),
        title=clean_text(str(meta.get("title", ""))),
        summary=clean_text(str(meta.get("title", ""))),
        metadata=meta,
        parser_version="v2",
        mapping_warnings=meta.get("mapping_warnings", "")
    )
    rec.doc_id = f"{direction}_{short_hash(detail_url or row_text or str(row_index))}"

    # Identify header/technical rows inside build step
    if is_header_row(cells, header_map):
        rec.mapping_warnings += ";HEADER_ROW_DETECTED"
    elif is_technical_row(cells):
        rec.mapping_warnings += ";TECHNICAL_ROW_DETECTED"

    return rec

_THRESHOLD_VALID = 60
_THRESHOLD_SUSPICIOUS = 30
_PLACEHOLDER_VALUES = {"N/A", "CHƯA CÓ", "CHUA CO", "UNKNOWN", ""}

def _is_account_data(doc_no: str, title: str) -> tuple[bool, str]:
    if re.match(r"^[a-z]{2,8}\.[a-z]{2,20}(?:\.[a-z]{2,20})*$", doc_no.lower()):
        return True, "Dữ liệu tài khoản"
    if "|" in title and re.match(r"^[a-z]{2,8}\.[a-z]{2,20}(?:\.[a-z]{2,20})*$", title.split("|")[0].strip().lower()):
        return True, "Dữ liệu tài khoản (trong trích yếu)"
    if doc_no and not re.search(r"[\d/\-]", doc_no) and len(doc_no.split()) >= 2 and len(doc_no) < 30:
        return True, "Số ký hiệu giống tên người (không chứa số hoặc ký tự phân cách)"
    return False, ""

def score_record_data(
    doc_no: str,
    title: str,
    doc_date: str,
    agency: str,
    mapping_warnings: str = "",
) -> tuple[str, int, list[str]]:

    score = 0
    warnings = []

    if "INVALID_MAPPING" in mapping_warnings or "STRUCTURAL_MAPPING_ERROR" in mapping_warnings:
        return "INVALID_MAPPING", 0, ["Lỗi ánh xạ dữ liệu nghiêm trọng"]
    if "TECHNICAL_ROW_DETECTED" in mapping_warnings:
        return "INVALID", 0, ["Dòng kỹ thuật bị loại"]
    if "HEADER_ROW_DETECTED" in mapping_warnings:
        return "INVALID", 0, ["Dòng tiêu đề bị lặp bị loại"]

    if "INVALID_DOC_DATE" in mapping_warnings:
        warnings.append("Ngày văn bản sai cấu trúc kỹ thuật")
    if "POSSIBLE_TECHNICAL_DOC_NO" in mapping_warnings:
        warnings.append("Số ký hiệu nghi ngờ là mã kỹ thuật")

    is_account, account_reason = _is_account_data(doc_no, title)
    if is_account:
        return "INVALID", 0, [account_reason]

    if doc_no and doc_no.upper() not in _PLACEHOLDER_VALUES:
        if "/" in doc_no: score += 25
        elif doc_no.isdigit(): score += 20
        else: score += 15
    else:
        warnings.append("Thiếu số/ký hiệu văn bản")

    if title and title.upper() not in _PLACEHOLDER_VALUES and len(title) >= 10:
        score += 25
    elif title and len(title) >= 3:
        score += 10
        warnings.append("Trích yếu văn bản quá ngắn")
    else:
        warnings.append("Thiếu trích yếu/tiêu đề văn bản")

    if doc_date and re.search(r"\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}|\d{4}[/\-]\d{1,2}[/\-]\d{1,2}", doc_date):
        score += 20
    else:
        warnings.append("Thiếu ngày ban hành hợp lệ")

    if agency and len(agency) >= 3:
        score += 15
    else:
        warnings.append("Thiếu cơ quan ban hành/gửi")

    if score >= _THRESHOLD_VALID:
        status = "VALID"
        if not doc_no or doc_no.upper() in _PLACEHOLDER_VALUES:
            status = "SUSPICIOUS"
    elif score >= _THRESHOLD_SUSPICIOUS:
        status = "SUSPICIOUS"
    else:
        status = "INVALID"

    if "POSSIBLE_TECHNICAL_DOC_NO" in mapping_warnings or "INVALID_DOC_DATE" in mapping_warnings or "INVALID_ISSUING_AGENCY" in mapping_warnings:
        if status == "VALID": status = "SUSPICIOUS"

    return status, score, warnings

def validate_record_data(
    doc_no: str,
    title: str,
    doc_date: str,
    agency: str,
    mapping_warnings: str = "",
    main_doc_meta: dict | None = None,
    attachments_meta: list[dict] | None = None,
) -> tuple[str, str]:
    has_file = False
    if main_doc_meta and isinstance(main_doc_meta, dict) and main_doc_meta.get("filename"):
        has_file = True
    if not has_file and attachments_meta:
        has_file = any(isinstance(a, dict) and a.get("filename") for a in attachments_meta)

    status, score, warnings = score_record_data(doc_no, title, doc_date, agency, mapping_warnings)

    if has_file and status != "INVALID":
        score += 15
        if score >= _THRESHOLD_VALID and status != "INVALID_MAPPING":
            status = "VALID"
            if not doc_no or doc_no.upper() in _PLACEHOLDER_VALUES:
                status = "SUSPICIOUS"
            if "POSSIBLE_TECHNICAL_DOC_NO" in mapping_warnings or "INVALID_DOC_DATE" in mapping_warnings or "INVALID_ISSUING_AGENCY" in mapping_warnings:
                status = "SUSPICIOUS"
    if status == "VALID":
        if warnings:
            return "VALID", "Hợp lệ (nhưng " + ", ".join(warnings) + ")"
        return "VALID", "Hợp lệ"
    elif status == "SUSPICIOUS":
        return "SUSPICIOUS", f"Điểm {score}/100 - " + ", ".join(warnings)
    else:
        return "INVALID", ", ".join(warnings) if warnings else f"Chưa đạt (score={score})"

def validate_document_record(record: DocumentRecord) -> tuple[str, str]:
    return validate_record_data(
        record.doc_no, record.title, record.doc_date, record.issuing_agency, getattr(record, "mapping_warnings", "")
    )
