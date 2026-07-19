from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .domain_models import sha256_text
from .extraction_models import (
    EXTRACTOR_NAME,
    EXTRACTOR_VERSION,
    DetectedFileType,
    ExtractionMethod,
    ExtractionResult,
    ExtractionStatus,
    ExtractedPage,
    combined_text_hash,
    normalize_extracted_text,
    truncate_document_pages,
    validate_extracted_page,
)
from .extraction_repository import ExtractionRepository
from .models import ATTACHMENT_VALIDATED
from .ocr_adapter import OcrAdapter, OptionalTesseractOcrAdapter


MIN_DIRECT_TEXT_CHARS = 20


@dataclass
class DirectPageText:
    page_number: int
    text: str
    width: int | None = None
    height: int | None = None


class ExtractionService:
    def __init__(self, repository: ExtractionRepository):
        self.repository = repository

    def extract_attachment(
        self,
        document_id: str,
        attachment_id: str,
        file_path: str | Path,
        force: bool = False,
        ocr_adapter: OcrAdapter | None = None,
        force_ocr: bool = False,
    ) -> ExtractionResult:
        started_result: ExtractionResult | None = None
        file_path = Path(file_path)
        adapter = ocr_adapter or OptionalTesseractOcrAdapter()
        ocr_version = adapter.version()
        source_hash = _sha256_file(file_path) if file_path.exists() else _empty_sha()
        try:
            attachment = self.repository.get_attachment(attachment_id)
            if attachment is None:
                return self._failed(document_id, attachment_id, source_hash, ocr_version, "ATTACHMENT_NOT_FOUND", "Attachment not found")
            if attachment.get("document_id") != document_id:
                return self._failed(document_id, attachment_id, source_hash, ocr_version, "DOCUMENT_ATTACHMENT_MISMATCH", "Attachment does not belong to document")
            if attachment.get("validation_status") != ATTACHMENT_VALIDATED:
                return self._failed(document_id, attachment_id, source_hash, ocr_version, "ATTACHMENT_NOT_VALIDATED", "Attachment must be VALIDATED before extraction")
            expected_hash = attachment.get("sha256")
            if not file_path.exists():
                return self._failed(document_id, attachment_id, source_hash, ocr_version, "FILE_NOT_FOUND", f"File not found: {file_path}")
            if expected_hash and expected_hash.lower() != source_hash.lower():
                return self._failed(document_id, attachment_id, source_hash, ocr_version, "HASH_MISMATCH", "Attachment SHA-256 does not match file")

            if not force:
                cached = self.repository.find_cached_success(
                    attachment_id=attachment_id,
                    source_file_sha256=source_hash,
                    extractor_name=EXTRACTOR_NAME,
                    extractor_version=EXTRACTOR_VERSION,
                    ocr_version=ocr_version,
                )
                if cached:
                    return ExtractionResult.from_dict(cached)

            detected = detect_file_type(file_path)
            if detected == DetectedFileType.HTML:
                return self._unsupported(document_id, attachment_id, source_hash, ocr_version, "HTML_DISGUISED_FILE", "HTML content is not a supported attachment payload")
            if detected == DetectedFileType.ZIP:
                return self._unsupported(document_id, attachment_id, source_hash, ocr_version, "ZIP_CONTAINER_NOT_EXTRACTED", "ZIP is detected but not extracted directly in G03")
            if detected == DetectedFileType.UNSUPPORTED:
                return self._unsupported(document_id, attachment_id, source_hash, ocr_version, "UNSUPPORTED_FORMAT", "Attachment format is not supported")

            pages, method, warnings = self._extract_pages(file_path, detected, adapter, force_ocr=force_ocr)
            pages, limit_warnings = truncate_document_pages(pages)
            warnings.extend(limit_warnings)
            non_empty_pages = [page for page in pages if page.text]
            status = ExtractionStatus.SUCCEEDED
            if not non_empty_pages:
                status = ExtractionStatus.NO_TEXT
            elif warnings:
                status = ExtractionStatus.SUCCEEDED_WITH_WARNINGS
            normalized_hash = combined_text_hash(pages) if pages else sha256_text("")
            started_result = ExtractionResult(
                document_id=document_id,
                attachment_id=attachment_id,
                extractor_name=EXTRACTOR_NAME,
                extractor_version=EXTRACTOR_VERSION,
                extraction_method=method,
                status=status,
                source_file_sha256=source_hash,
                normalized_text_sha256=normalized_hash,
                language="vi",
                page_count=len(pages),
                warnings=";".join(warnings) if warnings else None,
                ocr_version=ocr_version,
            )
            for page in pages:
                page.extraction_result_id = started_result.id
                validate_extracted_page(page)
            self.repository.save_result_with_pages(started_result, pages)
            return started_result
        except Exception as exc:
            failed = started_result or ExtractionResult(
                document_id=document_id,
                attachment_id=attachment_id,
                extractor_name=EXTRACTOR_NAME,
                extractor_version=EXTRACTOR_VERSION,
                extraction_method=ExtractionMethod.UNSUPPORTED,
                status=ExtractionStatus.FAILED,
                source_file_sha256=source_hash,
                ocr_version=ocr_version,
            )
            failed.status = ExtractionStatus.FAILED
            failed.error_code = "EXTRACTION_FAILED"
            failed.error_message = str(exc)
            failed.page_count = 0
            try:
                self.repository.save_failed_result(failed)
            except Exception:
                pass
            return failed

    def _extract_pages(
        self,
        file_path: Path,
        detected: DetectedFileType,
        adapter: OcrAdapter,
        *,
        force_ocr: bool,
    ) -> tuple[list[ExtractedPage], ExtractionMethod, list[str]]:
        if detected == DetectedFileType.PDF:
            return _extract_pdf_pages(file_path, adapter, force_ocr=force_ocr)
        if detected == DetectedFileType.DOCX:
            return _extract_docx_pages(file_path)
        if detected == DetectedFileType.TXT:
            return _extract_txt_pages(file_path)
        if detected in {DetectedFileType.PNG, DetectedFileType.JPEG}:
            return _extract_image_page(file_path, adapter)
        raise ValueError(f"unsupported detected type: {detected}")

    def _failed(
        self,
        document_id: str,
        attachment_id: str,
        source_hash: str,
        ocr_version: str,
        error_code: str,
        error_message: str,
    ) -> ExtractionResult:
        result = ExtractionResult(
            document_id=document_id,
            attachment_id=attachment_id,
            extractor_name=EXTRACTOR_NAME,
            extractor_version=EXTRACTOR_VERSION,
            extraction_method=ExtractionMethod.UNSUPPORTED,
            status=ExtractionStatus.FAILED,
            source_file_sha256=source_hash,
            page_count=0,
            error_code=error_code,
            error_message=error_message,
            ocr_version=ocr_version,
        )
        try:
            self.repository.save_failed_result(result)
        except Exception:
            pass
        return result

    def _unsupported(
        self,
        document_id: str,
        attachment_id: str,
        source_hash: str,
        ocr_version: str,
        error_code: str,
        error_message: str,
    ) -> ExtractionResult:
        result = ExtractionResult(
            document_id=document_id,
            attachment_id=attachment_id,
            extractor_name=EXTRACTOR_NAME,
            extractor_version=EXTRACTOR_VERSION,
            extraction_method=ExtractionMethod.UNSUPPORTED,
            status=ExtractionStatus.UNSUPPORTED,
            source_file_sha256=source_hash,
            page_count=0,
            error_code=error_code,
            error_message=error_message,
            ocr_version=ocr_version,
        )
        self.repository.save_result_with_pages(result, [])
        return result


def detect_file_type(path: str | Path) -> DetectedFileType:
    path = Path(path)
    head = path.read_bytes()[:4096]
    stripped = head.lstrip().lower()
    if stripped.startswith(b"<!doctype html") or stripped.startswith(b"<html"):
        return DetectedFileType.HTML
    if head.startswith(b"%PDF-"):
        return DetectedFileType.PDF
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return DetectedFileType.PNG
    if head.startswith(b"\xff\xd8\xff"):
        return DetectedFileType.JPEG
    if head.startswith(b"PK\x03\x04") or head.startswith(b"PK\x05\x06") or head.startswith(b"PK\x07\x08"):
        if _is_docx(path):
            return DetectedFileType.DOCX
        return DetectedFileType.ZIP
    if _looks_like_utf8_text(head):
        return DetectedFileType.TXT
    return DetectedFileType.UNSUPPORTED


def _is_docx(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            return "[Content_Types].xml" in names and "word/document.xml" in names
    except Exception:
        return False


def _looks_like_utf8_text(sample: bytes) -> bool:
    if not sample:
        return True
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _extract_txt_pages(path: Path) -> tuple[list[ExtractedPage], ExtractionMethod, list[str]]:
    text = path.read_text(encoding="utf-8-sig")
    normalized = normalize_extracted_text(text)
    return [_page("", 1, normalized, ExtractionMethod.DIRECT_TEXT)], ExtractionMethod.DIRECT_TEXT, []


def _extract_docx_pages(path: Path) -> tuple[list[ExtractedPage], ExtractionMethod, list[str]]:
    try:
        import docx
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except Exception as exc:
        raise RuntimeError("python-docx is required for DOCX extraction") from exc
    document = docx.Document(str(path))
    parts: list[str] = []
    for child in document.element.body.iterchildren():
        if child.tag.endswith("}p"):
            paragraph = Paragraph(child, document)
            if paragraph.text:
                parts.append(paragraph.text)
        elif child.tag.endswith("}tbl"):
            table = Table(child, document)
            for row in table.rows:
                cells = [normalize_extracted_text(cell.text) for cell in row.cells]
                if any(cells):
                    parts.append("\t".join(cells))
    text = normalize_extracted_text("\n".join(parts))
    return [_page("", 1, text, ExtractionMethod.DIRECT_TEXT)], ExtractionMethod.DIRECT_TEXT, []


def _extract_pdf_pages(
    path: Path,
    adapter: OcrAdapter,
    *,
    force_ocr: bool,
) -> tuple[list[ExtractedPage], ExtractionMethod, list[str]]:
    try:
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LTPage, LTTextContainer
    except Exception as exc:
        raise RuntimeError("pdfminer.six is required for PDF extraction") from exc
    pages: list[ExtractedPage] = []
    warnings: list[str] = []
    used_direct = False
    used_ocr = False
    for index, layout in enumerate(extract_pages(str(path)), start=1):
        direct_text = ""
        width = None
        height = None
        if isinstance(layout, LTPage):
            width = int(layout.width)
            height = int(layout.height)
        for element in layout:
            if isinstance(element, LTTextContainer):
                direct_text += element.get_text()
        normalized = normalize_extracted_text(direct_text)
        if force_ocr or len(normalized) < MIN_DIRECT_TEXT_CHARS:
            if adapter.is_available():
                try:
                    ocr = adapter.extract_pdf_page(path, index)
                    ocr_text = normalize_extracted_text(ocr.text)
                    if ocr_text:
                        used_ocr = True
                        pages.append(
                            _page(
                                "",
                                index,
                                ocr_text,
                                ExtractionMethod.OCR,
                                confidence=ocr.confidence,
                                width=ocr.width or width,
                                height=ocr.height or height,
                            )
                        )
                        warnings.extend(ocr.warnings)
                        continue
                except Exception as exc:
                    warnings.append(f"OCR_PDF_PAGE_FAILED:{index}:{exc}")
            else:
                warnings.append(f"OCR_UNAVAILABLE_FOR_PAGE:{index}")
        if normalized:
            used_direct = True
        pages.append(_page("", index, normalized, ExtractionMethod.DIRECT_TEXT, width=width, height=height))
    method = ExtractionMethod.MIXED if used_direct and used_ocr else ExtractionMethod.OCR if used_ocr else ExtractionMethod.DIRECT_TEXT
    return pages, method, warnings


def _extract_image_page(path: Path, adapter: OcrAdapter) -> tuple[list[ExtractedPage], ExtractionMethod, list[str]]:
    if not adapter.is_available():
        return [], ExtractionMethod.OCR, ["OCR_UNAVAILABLE_FOR_IMAGE"]
    ocr = adapter.extract_image(path)
    page = _page(
        "",
        1,
        normalize_extracted_text(ocr.text),
        ExtractionMethod.OCR,
        confidence=ocr.confidence,
        width=ocr.width,
        height=ocr.height,
    )
    return [page], ExtractionMethod.OCR, ocr.warnings


def _page(
    result_id: str,
    page_number: int,
    text: str,
    method: ExtractionMethod,
    *,
    confidence: float | None = None,
    width: int | None = None,
    height: int | None = None,
) -> ExtractedPage:
    normalized = normalize_extracted_text(text)
    return ExtractedPage(
        extraction_result_id=result_id,
        page_number=page_number,
        text=normalized,
        text_sha256=sha256_text(normalized),
        character_count=len(normalized),
        extraction_method=method,
        confidence=confidence,
        width=width,
        height=height,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _empty_sha() -> str:
    return hashlib.sha256(b"").hexdigest()
