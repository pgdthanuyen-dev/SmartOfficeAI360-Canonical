from __future__ import annotations

import zipfile
import io
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tools.qlvb_downloader.config import QLVBConfig
from tools.qlvb_downloader.downloader import QLVBDownloader
from tools.qlvb_downloader.models import (
    ATTACHMENT_INVALID_FILE,
    ATTACHMENT_VALIDATED,
    DOCUMENT_NO_VALID_ATTACHMENT,
    DOCUMENT_READY,
    AttachmentInfo,
    DocumentRecord,
)


class FakeResponse:
    def __init__(self, url: str, headers: dict[str, str], body: bytes, status: int = 200):
        self.url = url
        self.headers = headers
        self.status = status
        self._body = body

    def body(self) -> bytes:
        return self._body

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class FakeRequest:
    def __init__(self, response: FakeResponse | None = None):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.response is None:
            raise AssertionError("unexpected request")
        return self.response


class FakeEventOwner:
    def __init__(self):
        self.listeners: dict[str, list] = {}

    def on(self, event_name: str, handler) -> None:
        self.listeners.setdefault(event_name, []).append(handler)

    def remove_listener(self, event_name: str, handler) -> None:
        if event_name in self.listeners and handler in self.listeners[event_name]:
            self.listeners[event_name].remove(handler)

    def emit(self, event_name: str, payload) -> None:
        for handler in list(self.listeners.get(event_name, [])):
            handler(payload)


class FakeContext(FakeEventOwner):
    def __init__(self):
        super().__init__()
        self.pages = []
        self.request = FakeRequest()


class FakeExpectDownload:
    def __enter__(self):
        self.value = None
        return self

    def __exit__(self, exc_type, exc, tb):
        raise TimeoutError("no download event")


class FakePage(FakeEventOwner):
    def __init__(self):
        super().__init__()
        self.context = FakeContext()
        self.context.pages = [self]
        self.url = "https://qlvb.laichau.gov.vn/qlvbdh_lcu/main"
        self.captured_url = None
        self.original_open_installed = False
        self.evaluate = MagicMock(side_effect=self._evaluate)
        self.goto = MagicMock()

    def expect_download(self, timeout=0):
        return FakeExpectDownload()

    def wait_for_timeout(self, timeout=0):
        return None

    def is_closed(self):
        return False

    def _evaluate(self, script):
        if "__smartofficeOriginalOpen = window.open" in script:
            self.original_open_installed = True
            self.captured_url = None
            return None
        if "() => window.__smartofficeCapturedDownloadUrl" == script:
            return self.captured_url
        if "delete window.__smartofficeCapturedDownloadUrl" in script:
            self.original_open_installed = False
            self.captured_url = None
            return None
        return None


class FakeLocator:
    def __init__(self, page: FakePage, response: FakeResponse | None = None, captured_url: str | None = None):
        self.page = page
        self.response = response
        self.captured_url = captured_url
        self.click = MagicMock(side_effect=self._click)
        self.evaluate = MagicMock()

    def _click(self, timeout=0):
        if self.captured_url:
            self.page.captured_url = self.captured_url
        if self.response:
            self.page.emit("response", self.response)
            self.page.context.emit("response", self.response)


def make_downloader(tmp_path: Path) -> QLVBDownloader:
    cfg = QLVBConfig()
    cfg.save_root = str(tmp_path)
    return QLVBDownloader(cfg)


def make_record() -> DocumentRecord:
    return DocumentRecord(direction="incoming", source_url="https://qlvb.laichau.gov.vn/qlvbdh_lcu/main", row_index=1, row_text="row", doc_id="incoming_test")


def zip_bytes(name: str = "doc.txt", content: bytes = b"ok") -> bytes:
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as zf:
        zf.writestr(name, content)
    return bio.getvalue()


def docx_bytes() -> bytes:
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types></Types>")
        zf.writestr("word/document.xml", "<w:document></w:document>")
    return bio.getvalue()


def test_all_file_download_response_zip_without_download_event(tmp_path):
    downloader = make_downloader(tmp_path)
    page = FakePage()
    response = FakeResponse(
        "https://qlvb.laichau.gov.vn/smartoffice/jbm/download_all.jsp?dynamic_name=2561570",
        {"content-type": "application/zip", "content-disposition": 'attachment; filename="all.zip"'},
        zip_bytes(),
    )
    page.context.request.response = response
    locator = FakeLocator(page, captured_url="/smartoffice/jbm/download_all.jsp?dynamic_name=2561570")

    saved = downloader.trigger_qlvb_attachment_download(page, locator, make_record(), "javascript:allFileDownload(1)", 1, timeout_seconds=13)

    assert saved.exists()
    assert saved.suffix == ".zip"
    assert page.context.request.calls[0][0].endswith("?dynamic_name=2561570")
    assert page.context.request.calls[0][1]["headers"]["Referer"] == page.url
    assert page.original_open_installed is False
    page.goto.assert_not_called()
    assert all(call.args[0] != "allFileDownload(1)" for call in page.evaluate.call_args_list)


def test_filedownload_response_pdf_without_download_event(tmp_path):
    downloader = make_downloader(tmp_path)
    page = FakePage()
    response = FakeResponse(
        "https://qlvb.laichau.gov.vn/file.pdf",
        {"content-type": "application/pdf", "content-disposition": 'attachment; filename="file.pdf"'},
        b"%PDF-1.4\n%%EOF",
    )
    page.context.request.response = response
    with pytest.raises(RuntimeError, match="UNEXPECTED_DOWNLOAD_PATH"):
        downloader.trigger_qlvb_attachment_download(
            page, FakeLocator(page, captured_url="/file.pdf"), make_record(), "javascript:filedownload('x')", 1, timeout_seconds=13
        )


def test_external_smartca_response_is_rejected(tmp_path):
    downloader = make_downloader(tmp_path)
    page = FakePage()
    response = FakeResponse(
        "https://smartca.vnpt.vn/download",
        {"content-type": "application/zip", "content-disposition": 'attachment; filename="smartca.zip"'},
        zip_bytes(),
    )
    with pytest.raises(RuntimeError, match="UNEXPECTED_DOWNLOAD_HOST"):
        downloader.trigger_qlvb_attachment_download(
            page, FakeLocator(page, captured_url="https://smartca.vnpt.vn/download"), make_record(), "javascript:allFileDownload(1)", 1, timeout_seconds=13
        )


def test_dynamic_query_parameter_names_are_not_hard_coded(tmp_path):
    downloader = make_downloader(tmp_path)
    page = FakePage()
    response = FakeResponse(
        "https://qlvb.laichau.gov.vn/smartoffice/jbm/download_all.jsp?alpha=1&omega=2",
        {"content-type": "application/zip", "content-disposition": 'attachment; filename="dynamic.zip"'},
        zip_bytes(),
    )
    page.context.request.response = response
    locator = FakeLocator(page, captured_url=response.url)
    saved = downloader.trigger_qlvb_attachment_download(page, locator, make_record(), "javascript:zipfileDownload_('1',2561570)", 1)
    assert saved.name == "dynamic.zip"
    assert page.context.request.calls[0][0] == response.url


def test_legacy_query_parameter_names_are_not_in_adapter_source():
    source = Path("tools/qlvb_downloader/downloader.py").read_text(encoding="utf-8")
    assert "5E1XCBS" not in source
    assert "5E9Z6BO" not in source


@pytest.mark.parametrize("url,error", [
    ("javascript:alert(1)", "CAPTURED_DOWNLOAD_URL_INVALID"),
    ("about:blank", "CAPTURED_DOWNLOAD_URL_INVALID"),
    ("http://qlvb.laichau.gov.vn/smartoffice/jbm/download_all.jsp", "CAPTURED_DOWNLOAD_URL_INVALID"),
    ("https://qlvb.laichau.gov.vn/support/document", "UNEXPECTED_DOWNLOAD_PATH"),
])
def test_invalid_captured_urls_are_rejected(tmp_path, url, error):
    downloader = make_downloader(tmp_path)
    with pytest.raises(RuntimeError, match=error):
        downloader._validate_captured_download_url(url, "https://qlvb.laichau.gov.vn/detail")


def test_capture_restores_window_open_when_click_fails(tmp_path):
    downloader = make_downloader(tmp_path)
    page = FakePage()
    locator = FakeLocator(page)
    locator.click.side_effect = RuntimeError("click failed")
    locator.evaluate.side_effect = RuntimeError("evaluate failed")
    with pytest.raises(RuntimeError, match="evaluate failed"):
        downloader._capture_runtime_download_url(page, locator, "javascript:zipfileDownload_('1',1)")
    assert page.original_open_installed is False


def test_zip_validation_requires_at_least_one_entry(tmp_path):
    downloader = make_downloader(tmp_path)
    path = tmp_path / "empty.zip"
    with zipfile.ZipFile(path, "w"):
        pass
    with pytest.raises(RuntimeError, match="DOWNLOADED_ZIP_INVALID"):
        downloader._validate_downloaded_file(path, {})


def test_download_statistics_separate_archive_and_extracted_files(tmp_path):
    downloader = make_downloader(tmp_path)
    page = FakePage()
    rec = make_record()
    archive = tmp_path / "source.zip"
    archive.write_bytes(zip_bytes("van_ban.pdf", b"%PDF-1.4\n%%EOF"))
    rec.attachments = [AttachmentInfo(text="Nén và tải tất cả", href="javascript:zipfileDownload_('1',1)")]
    downloader._download_by_click_or_request = MagicMock(return_value=archive)

    downloader._download_attachments(page, rec)

    assert rec.metadata["download_stats"] == {
        "downloaded_files": 1,
        "downloaded_archives": 1,
        "extracted_files": 1,
        "materialized_files": 2,
        "invalid_files": 0,
        "failed_files": 0,
    }
    assert rec.attachments[0].status == ATTACHMENT_VALIDATED


def test_valid_zip_bundle_is_extracted(tmp_path):
    downloader = make_downloader(tmp_path)
    rec = make_record()
    zip_path = tmp_path / "bundle.zip"
    zip_path.write_bytes(zip_bytes("van_ban.pdf", b"%PDF-1.4\n%%EOF"))

    extracted = downloader._extract_zip_bundle(rec, zip_path)

    assert len(extracted) == 1
    assert extracted[0].name == "01_van_ban.pdf"
    assert extracted[0].read_bytes().startswith(b"%PDF")


def test_zip_slip_bundle_is_rejected(tmp_path):
    downloader = make_downloader(tmp_path)
    rec = make_record()
    zip_path = tmp_path / "bad.zip"
    import io

    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as zf:
        zf.writestr("../evil.pdf", b"%PDF-1.4\n%%EOF")
    zip_path.write_bytes(bio.getvalue())

    with pytest.raises(RuntimeError, match="ZIP_SLIP_DETECTED"):
        downloader._extract_zip_bundle(rec, zip_path)


def test_downloaded_html_login_page_is_rejected(tmp_path):
    downloader = make_downloader(tmp_path)
    path = tmp_path / "login.html"
    path.write_bytes(b"<!DOCTYPE html><html><form name=\"password\">captcha</form></html>")
    with pytest.raises(RuntimeError, match="DOWNLOADED_HTML_LOGIN_PAGE|SESSION_EXPIRED"):
        downloader._validate_downloaded_file(path, {})


def test_valid_pdf_is_accepted_and_hashed(tmp_path):
    downloader = make_downloader(tmp_path)
    path = tmp_path / "valid.pdf"
    path.write_bytes(b"%PDF-1.4\n%%EOF")
    result = downloader._validate_downloaded_file(path, {"content-type": "application/pdf"})
    assert result["size_bytes"] == path.stat().st_size
    assert len(result["sha256"]) == 64


def test_valid_docx_is_accepted(tmp_path):
    downloader = make_downloader(tmp_path)
    path = tmp_path / "valid.docx"
    path.write_bytes(docx_bytes())
    result = downloader._validate_downloaded_file(path, {})
    assert result["filename"] == "valid.docx"


def test_html_disguised_as_pdf_is_rejected(tmp_path):
    downloader = make_downloader(tmp_path)
    path = tmp_path / "fake.pdf"
    path.write_bytes(b"<html><body><form><input name='password'></form></body></html>")
    with pytest.raises(RuntimeError, match="DOWNLOADED_HTML_LOGIN_PAGE|SESSION_EXPIRED"):
        downloader._validate_downloaded_file(path, {"content-type": "application/pdf"})


def test_html_disguised_as_zip_is_rejected(tmp_path):
    downloader = make_downloader(tmp_path)
    path = tmp_path / "fake.zip"
    path.write_bytes(b"<!doctype html><html>login password</html>")
    with pytest.raises(RuntimeError, match="DOWNLOADED_HTML_LOGIN_PAGE|SESSION_EXPIRED"):
        downloader._validate_downloaded_file(path, {"content-type": "application/zip"})


def test_empty_download_is_rejected(tmp_path):
    downloader = make_downloader(tmp_path)
    path = tmp_path / "empty.pdf"
    path.write_bytes(b"")
    with pytest.raises(RuntimeError, match="DOWNLOADED_FILE_TOO_SMALL|DOWNLOADED_FILE_EMPTY"):
        downloader._validate_downloaded_file(path, {"content-type": "application/pdf"})


def test_corrupt_zip_is_rejected(tmp_path):
    downloader = make_downloader(tmp_path)
    path = tmp_path / "bad.zip"
    path.write_bytes(b"PK not a real zip")
    with pytest.raises(RuntimeError, match="DOWNLOADED_FILE_INVALID"):
        downloader._validate_downloaded_file(path, {"content-type": "application/zip"})


def test_docx_validation_requires_docx_structure(tmp_path):
    downloader = make_downloader(tmp_path)
    path = tmp_path / "bad.docx"
    path.write_bytes(zip_bytes("plain.txt"))
    with pytest.raises(RuntimeError, match="DOWNLOADED_FILE_INVALID"):
        downloader._validate_downloaded_file(path, {})


def test_about_blank_download_source_is_rejected(tmp_path):
    downloader = make_downloader(tmp_path)
    path = tmp_path / "valid.pdf"
    path.write_bytes(b"%PDF-1.4\n%%EOF")
    with pytest.raises(RuntimeError, match="DOWNLOAD_SOURCE_URL_INVALID"):
        downloader._validate_downloaded_file(path, {}, source_url="about:blank")


def test_response_with_right_type_but_wrong_href_context_is_ignored(tmp_path):
    downloader = make_downloader(tmp_path)
    page = FakePage()
    wrong_response = FakeResponse(
        "https://qlvb.laichau.gov.vn/other.zip",
        {"content-type": "application/zip", "content-disposition": 'attachment; filename="other.zip"'},
        zip_bytes(),
    )
    locator = FakeLocator(page, response=wrong_response)
    downloader._locator_for_href = MagicMock(return_value=locator)

    with pytest.raises(AssertionError, match="unexpected request"):
        downloader._download_by_click_or_request(page, make_record(), "https://qlvb.laichau.gov.vn/expected.zip", 1)

    assert not list((tmp_path / "files").rglob("other.zip"))


def test_downloaded_files_counts_validated_only(tmp_path):
    downloader = make_downloader(tmp_path)
    downloader.config.download.retry_download_times = 1
    page = FakePage()
    rec = make_record()
    valid = tmp_path / "valid.pdf"
    valid.write_bytes(b"%PDF-1.4\n%%EOF")
    invalid = tmp_path / "invalid.pdf"
    invalid.write_bytes(b"<html>login password</html>")
    rec.attachments = [
        AttachmentInfo(text="valid", href="valid"),
        AttachmentInfo(text="invalid", href="invalid"),
    ]
    downloader._download_by_click_or_request = MagicMock(side_effect=[valid, invalid])

    downloader._download_attachments(page, rec)

    assert rec.metadata["download_stats"]["downloaded_files"] == 1
    assert rec.metadata["download_stats"]["invalid_files"] == 1
    assert rec.attachments[0].status == ATTACHMENT_VALIDATED
    assert rec.attachments[1].status == ATTACHMENT_INVALID_FILE


def test_process_direction_processed_increments_once(tmp_path):
    downloader = make_downloader(tmp_path)
    page = FakePage()
    detail = FakePage()
    detail.set_default_timeout = MagicMock()
    page.context.new_page = MagicMock(return_value=detail)
    rec = make_record()
    rec.attachments = [AttachmentInfo(text="valid", href="valid", status=ATTACHMENT_VALIDATED)]
    downloader.open_document_direction = MagicMock(return_value=page)
    downloader._extract_records_from_current_page = MagicMock(return_value=[rec])
    downloader._extract_headers = MagicMock(return_value=[])
    downloader._process_record = MagicMock(side_effect=lambda _page, record, list_page=None: setattr(record, "status", DOCUMENT_READY))
    downloader._go_next_page = MagicMock(return_value=False)

    result = downloader._process_direction(page, "incoming", max_items=1)

    assert result["processed"] == 1
    assert result["downloaded_files"] == 1
    assert result["status"] == "DONE"


def test_direction_done_with_errors_when_no_valid_attachment(tmp_path):
    downloader = make_downloader(tmp_path)
    page = FakePage()
    detail = FakePage()
    detail.set_default_timeout = MagicMock()
    page.context.new_page = MagicMock(return_value=detail)
    rec = make_record()
    rec.attachments = [AttachmentInfo(text="bad", href="bad", status=ATTACHMENT_INVALID_FILE, error="bad")]
    downloader.open_document_direction = MagicMock(return_value=page)

    def mark_no_valid(_page, record, list_page=None):
        record.status = DOCUMENT_NO_VALID_ATTACHMENT
        record.error = "NO_VALID_ATTACHMENT"

    downloader._extract_records_from_current_page = MagicMock(return_value=[rec])
    downloader._extract_headers = MagicMock(return_value=[])
    downloader._process_record = MagicMock(side_effect=mark_no_valid)
    downloader._go_next_page = MagicMock(return_value=False)

    result = downloader._process_direction(page, "incoming", max_items=1)

    assert result["processed"] == 1
    assert result["downloaded_files"] == 0
    assert result["invalid_files"] == 1
    assert result["records_without_valid_attachment"] == 1
    assert result["status"] == "DONE_WITH_ERRORS"


def test_click_dom_before_javascript_evaluate(tmp_path):
    downloader = make_downloader(tmp_path)
    page = FakePage()
    locator = FakeLocator(page)
    downloader._click_attachment_element(page, locator, "javascript:filedownload('x')")
    assert locator.click.called
    page.evaluate.assert_not_called()
