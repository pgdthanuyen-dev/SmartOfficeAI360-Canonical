from __future__ import annotations

import hashlib
import sqlite3
import unicodedata
import zipfile
from pathlib import Path

import pytest

from tools.qlvb_downloader.domain_models import Attachment, AttachmentValidationStatus, Document
from tools.qlvb_downloader.domain_repository import DomainRepository, init_domain_schema
from tools.qlvb_downloader.extraction_models import (
    EXTRACTION_SCHEMA_VERSION,
    EXTRACTOR_VERSION,
    ExtractionMethod,
    ExtractionStatus,
    ExtractedPage,
    normalize_extracted_text,
    validate_extracted_page,
)
from tools.qlvb_downloader.extraction_repository import ExtractionRepository, init_extraction_schema
from tools.qlvb_downloader.extraction_service import ExtractionService, detect_file_type
from tools.qlvb_downloader.ocr_adapter import OcrAdapter, OcrOutput


class FakeOcrAdapter(OcrAdapter):
    def __init__(self, text: str = "OCR tieng Viet", available: bool = True, confidence: float | None = 0.91):
        self.text = text
        self.available = available
        self.confidence = confidence
        self.image_calls = 0
        self.pdf_page_calls: list[int] = []

    def is_available(self) -> bool:
        return self.available

    def extract_image(self, image_path: str | Path) -> OcrOutput:
        self.image_calls += 1
        return OcrOutput(text=self.text, confidence=self.confidence, width=640, height=480)

    def extract_pdf_page(self, pdf_path: str | Path, page_number: int) -> OcrOutput:
        self.pdf_page_calls.append(page_number)
        return OcrOutput(text=f"{self.text} page {page_number}", confidence=self.confidence, width=800, height=1000)

    def version(self) -> str:
        return "fake-ocr:1"


class FailingPageRepository(ExtractionRepository):
    def _insert_page(self, page: ExtractedPage) -> None:
        if page.page_number == 2:
            raise sqlite3.IntegrityError("simulated page insert failure")
        super()._insert_page(page)


def _repo() -> tuple[sqlite3.Connection, DomainRepository, ExtractionRepository]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY, title TEXT)")
    domain_repo = DomainRepository(conn)
    extraction_repo = ExtractionRepository(conn)
    return conn, domain_repo, extraction_repo


def _seed_attachment(
    domain_repo: DomainRepository,
    file_path: Path,
    *,
    attachment_id: str = "att-1",
    status: AttachmentValidationStatus = AttachmentValidationStatus.VALIDATED,
    sha256: str | None = None,
) -> None:
    domain_repo.save_document(Document(id="doc-1", tenant_id="tenant-a", source_system="QLVB", source_document_id="qlvb-1"))
    domain_repo.save_attachment(
        Attachment(
            id=attachment_id,
            document_id="doc-1",
            file_name=file_path.name,
            file_extension=file_path.suffix.lower().lstrip("."),
            sha256=sha256 if sha256 is not None else _sha256_file(file_path),
            size_bytes=file_path.stat().st_size if file_path.exists() else 0,
            storage_path=str(file_path),
            validation_status=status,
        )
    )


def _extract(extraction_repo: ExtractionRepository, file_path: Path, adapter: OcrAdapter | None = None, **kwargs):
    return ExtractionService(extraction_repo).extract_attachment("doc-1", "att-1", file_path, ocr_adapter=adapter, **kwargs)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_pdf(path: Path, pages: list[str]) -> None:
    reportlab = pytest.importorskip("reportlab.pdfgen.canvas")
    canvas = reportlab.Canvas(str(path))
    for text in pages:
        if text:
            canvas.drawString(72, 720, text)
        canvas.showPage()
    canvas.save()


def _write_docx(path: Path, *, with_table: bool = False) -> None:
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_paragraph("Cong van ve viec kiem tra tien do")
    if with_table:
        table = document.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "Don vi"
        table.cell(0, 1).text = "San pham dau ra"
    document.save(str(path))


def test_pdf_direct_text_multi_page(tmp_path):
    pdf = tmp_path / "multi.pdf"
    _write_pdf(pdf, ["Trang 1 noi dung van ban", "Trang 2 noi dung ket luan"])
    conn, domain_repo, extraction_repo = _repo()
    try:
        _seed_attachment(domain_repo, pdf)
        result = _extract(extraction_repo, pdf, FakeOcrAdapter())
        pages = extraction_repo.list_pages(result.id)
        assert result.status == ExtractionStatus.SUCCEEDED
        assert result.extraction_method == ExtractionMethod.DIRECT_TEXT
        assert [p["page_number"] for p in pages] == [1, 2]
        assert "Trang 1" in pages[0]["text"]
        assert "Trang 2" in pages[1]["text"]
    finally:
        conn.close()


def test_blank_pdf_uses_fake_ocr(tmp_path):
    pdf = tmp_path / "scan.pdf"
    _write_pdf(pdf, [""])
    adapter = FakeOcrAdapter("Noi dung OCR")
    conn, domain_repo, extraction_repo = _repo()
    try:
        _seed_attachment(domain_repo, pdf)
        result = _extract(extraction_repo, pdf, adapter)
        pages = extraction_repo.list_pages(result.id)
        assert result.status in {ExtractionStatus.SUCCEEDED, ExtractionStatus.SUCCEEDED_WITH_WARNINGS}
        assert result.extraction_method == ExtractionMethod.OCR
        assert adapter.pdf_page_calls == [1]
        assert "Noi dung OCR page 1" in pages[0]["text"]
    finally:
        conn.close()


def test_png_uses_fake_ocr(tmp_path):
    image = tmp_path / "image.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    adapter = FakeOcrAdapter("Anh scan tieng Viet")
    conn, domain_repo, extraction_repo = _repo()
    try:
        _seed_attachment(domain_repo, image)
        result = _extract(extraction_repo, image, adapter)
        pages = extraction_repo.list_pages(result.id)
        assert result.extraction_method == ExtractionMethod.OCR
        assert adapter.image_calls == 1
        assert pages[0]["text"] == "Anh scan tieng Viet"
    finally:
        conn.close()


def test_jpeg_uses_fake_ocr(tmp_path):
    image = tmp_path / "image.jpg"
    image.write_bytes(b"\xff\xd8\xff\xe0fake")
    adapter = FakeOcrAdapter("JPEG OCR")
    conn, domain_repo, extraction_repo = _repo()
    try:
        _seed_attachment(domain_repo, image)
        result = _extract(extraction_repo, image, adapter)
        assert result.status == ExtractionStatus.SUCCEEDED
        assert extraction_repo.list_pages(result.id)[0]["text"] == "JPEG OCR"
    finally:
        conn.close()


def test_docx_paragraph_extraction(tmp_path):
    path = tmp_path / "doc.docx"
    _write_docx(path)
    conn, domain_repo, extraction_repo = _repo()
    try:
        _seed_attachment(domain_repo, path)
        result = _extract(extraction_repo, path, FakeOcrAdapter(available=False))
        assert result.status == ExtractionStatus.SUCCEEDED
        assert "Cong van" in extraction_repo.list_pages(result.id)[0]["text"]
    finally:
        conn.close()


def test_docx_table_extraction(tmp_path):
    path = tmp_path / "table.docx"
    _write_docx(path, with_table=True)
    conn, domain_repo, extraction_repo = _repo()
    try:
        _seed_attachment(domain_repo, path)
        result = _extract(extraction_repo, path)
        text = extraction_repo.list_pages(result.id)[0]["text"]
        assert "Don vi" in text
        assert "San pham dau ra" in text
    finally:
        conn.close()


def test_txt_utf8_vietnamese_extraction(tmp_path):
    path = tmp_path / "viet.txt"
    path.write_text("Quyết định về việc xử lý hồ sơ\r\nGiữ nguyên tiếng Việt", encoding="utf-8")
    conn, domain_repo, extraction_repo = _repo()
    try:
        _seed_attachment(domain_repo, path)
        result = _extract(extraction_repo, path)
        text = extraction_repo.list_pages(result.id)[0]["text"]
        assert result.status == ExtractionStatus.SUCCEEDED
        assert "Quyết định" in text
        assert "\r" not in text
    finally:
        conn.close()


def test_non_validated_file_is_rejected(tmp_path):
    path = tmp_path / "doc.txt"
    path.write_text("Noi dung", encoding="utf-8")
    conn, domain_repo, extraction_repo = _repo()
    try:
        _seed_attachment(domain_repo, path, status=AttachmentValidationStatus.DOWNLOAD_FAILED)
        result = _extract(extraction_repo, path)
        assert result.status == ExtractionStatus.FAILED
        assert result.error_code == "ATTACHMENT_NOT_VALIDATED"
        assert extraction_repo.list_pages(result.id) == []
    finally:
        conn.close()


def test_hash_mismatch_is_rejected(tmp_path):
    path = tmp_path / "doc.txt"
    path.write_text("Noi dung", encoding="utf-8")
    conn, domain_repo, extraction_repo = _repo()
    try:
        _seed_attachment(domain_repo, path, sha256="a" * 64)
        result = _extract(extraction_repo, path)
        assert result.status == ExtractionStatus.FAILED
        assert result.error_code == "HASH_MISMATCH"
    finally:
        conn.close()


def test_html_disguised_as_pdf_is_rejected(tmp_path):
    path = tmp_path / "fake.pdf"
    path.write_text("<html><body>login</body></html>", encoding="utf-8")
    conn, domain_repo, extraction_repo = _repo()
    try:
        _seed_attachment(domain_repo, path)
        result = _extract(extraction_repo, path)
        assert result.status == ExtractionStatus.UNSUPPORTED
        assert result.error_code == "HTML_DISGUISED_FILE"
    finally:
        conn.close()


def test_unsupported_binary_format(tmp_path):
    path = tmp_path / "data.bin"
    path.write_bytes(b"\x00\x01\x02\x03")
    conn, domain_repo, extraction_repo = _repo()
    try:
        _seed_attachment(domain_repo, path)
        result = _extract(extraction_repo, path)
        assert result.status == ExtractionStatus.UNSUPPORTED
        assert result.error_code == "UNSUPPORTED_FORMAT"
    finally:
        conn.close()


def test_zip_is_detected_but_not_extracted(tmp_path):
    path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("doc.txt", "Noi dung")
    conn, domain_repo, extraction_repo = _repo()
    try:
        _seed_attachment(domain_repo, path)
        assert detect_file_type(path).value == "ZIP"
        result = _extract(extraction_repo, path)
        assert result.status == ExtractionStatus.UNSUPPORTED
        assert result.error_code == "ZIP_CONTAINER_NOT_EXTRACTED"
    finally:
        conn.close()


def test_page_numbering_starts_at_one(tmp_path):
    pdf = tmp_path / "pages.pdf"
    _write_pdf(pdf, ["A" * 40, "B" * 40])
    conn, domain_repo, extraction_repo = _repo()
    try:
        _seed_attachment(domain_repo, pdf)
        result = _extract(extraction_repo, pdf)
        assert [p["page_number"] for p in extraction_repo.list_pages(result.id)] == [1, 2]
    finally:
        conn.close()


def test_unicode_nfc_normalization():
    decomposed = "Quye\u0302\u0301t đi\u0323nh\r\nDong hai"
    normalized = normalize_extracted_text(decomposed)
    assert unicodedata.is_normalized("NFC", normalized)
    assert "\r" not in normalized


def test_stable_text_hash():
    first = normalize_extracted_text("A\r\nB")
    second = normalize_extracted_text("A\nB")
    assert hashlib.sha256(first.encode("utf-8")).hexdigest() == hashlib.sha256(second.encode("utf-8")).hexdigest()


def test_confidence_validation():
    with pytest.raises(Exception):
        validate_extracted_page(
            ExtractedPage(
                extraction_result_id="result-1",
                page_number=1,
                text="text",
                extraction_method=ExtractionMethod.OCR,
                confidence=1.2,
            )
        )


def test_ocr_unavailable_does_not_crash_direct_pdf(tmp_path):
    pdf = tmp_path / "direct.pdf"
    _write_pdf(pdf, ["Direct text long enough to avoid OCR fallback"])
    adapter = FakeOcrAdapter(available=False)
    conn, domain_repo, extraction_repo = _repo()
    try:
        _seed_attachment(domain_repo, pdf)
        result = _extract(extraction_repo, pdf, adapter)
        assert result.status == ExtractionStatus.SUCCEEDED
        assert adapter.pdf_page_calls == []
    finally:
        conn.close()


def test_ocr_fallback_only_runs_when_needed(tmp_path):
    pdf = tmp_path / "direct.pdf"
    _write_pdf(pdf, ["Direct text long enough to avoid OCR fallback"])
    adapter = FakeOcrAdapter()
    conn, domain_repo, extraction_repo = _repo()
    try:
        _seed_attachment(domain_repo, pdf)
        _extract(extraction_repo, pdf, adapter)
        assert adapter.pdf_page_calls == []
    finally:
        conn.close()


def test_cache_hit_does_not_extract_again(tmp_path):
    image = tmp_path / "image.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    first_adapter = FakeOcrAdapter("First OCR")
    second_adapter = FakeOcrAdapter("Second OCR")
    conn, domain_repo, extraction_repo = _repo()
    try:
        _seed_attachment(domain_repo, image)
        first = _extract(extraction_repo, image, first_adapter)
        second = _extract(extraction_repo, image, second_adapter)
        assert first.id == second.id
        assert second_adapter.image_calls == 0
    finally:
        conn.close()


def test_force_extraction_bypasses_cache(tmp_path):
    image = tmp_path / "image.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    first_adapter = FakeOcrAdapter("First OCR")
    second_adapter = FakeOcrAdapter("Second OCR")
    conn, domain_repo, extraction_repo = _repo()
    try:
        _seed_attachment(domain_repo, image)
        first = _extract(extraction_repo, image, first_adapter)
        second = _extract(extraction_repo, image, second_adapter, force=True)
        assert first.id != second.id
        assert second_adapter.image_calls == 1
        assert extraction_repo.list_pages(second.id)[0]["text"] == "Second OCR"
    finally:
        conn.close()


def test_extraction_migration_first_time():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY, title TEXT)")
    try:
        init_domain_schema(conn)
        init_extraction_schema(conn)
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"extraction_results", "extracted_pages", "schema_migrations"} <= tables
    finally:
        conn.close()


def test_extraction_migration_idempotent():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY, title TEXT)")
    try:
        init_domain_schema(conn)
        init_extraction_schema(conn)
        init_extraction_schema(conn)
        count = conn.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = 'g03_extraction_schema_1'"
        ).fetchone()[0]
        assert count == 1
    finally:
        conn.close()


def test_legacy_g02_database_keeps_data(tmp_path):
    txt = tmp_path / "doc.txt"
    txt.write_text("Noi dung hop le", encoding="utf-8")
    conn, domain_repo, extraction_repo = _repo()
    try:
        _seed_attachment(domain_repo, txt)
        before = domain_repo.get_document("doc-1")
        init_extraction_schema(conn)
        after = domain_repo.get_document("doc-1")
        assert before["doc_id"] == after["doc_id"]
        assert extraction_repo.get_attachment("att-1")["id"] == "att-1"
    finally:
        conn.close()


def test_transaction_rollback_when_page_insert_fails(tmp_path):
    pdf = tmp_path / "two.pdf"
    _write_pdf(pdf, ["A" * 40, "B" * 40])
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY, title TEXT)")
    domain_repo = DomainRepository(conn)
    failing_repo = FailingPageRepository(conn)
    try:
        _seed_attachment(domain_repo, pdf)
        result = _extract(failing_repo, pdf)
        assert result.status == ExtractionStatus.FAILED
        assert failing_repo.list_pages(result.id) == []
    finally:
        conn.close()


def test_failed_result_does_not_store_partial_pages(tmp_path):
    image = tmp_path / "image.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    conn, domain_repo, extraction_repo = _repo()
    try:
        _seed_attachment(domain_repo, image)
        result = _extract(extraction_repo, image, FakeOcrAdapter(available=False))
        assert result.status == ExtractionStatus.NO_TEXT
        assert extraction_repo.list_pages(result.id) == []
    finally:
        conn.close()


def test_extraction_schema_version_constant():
    assert EXTRACTION_SCHEMA_VERSION == "1.0.0"
    assert EXTRACTOR_VERSION == "g03.1"
