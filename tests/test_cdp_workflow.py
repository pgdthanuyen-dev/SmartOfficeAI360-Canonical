from __future__ import annotations

import inspect
import zipfile
from pathlib import Path

import pytest

from tools.qlvb_downloader import cdp_workflow


class _Response:
    def __init__(self, status: int, body: bytes, content_type: str = "application/octet-stream", url: str = "https://qlvb.example/download.jsp"):
        self.status = status
        self._body = body
        self.headers = {"content-type": content_type}
        self.url = url

    def body(self) -> bytes:
        return self._body


class _Request:
    def __init__(self, response: _Response):
        self.response = response

    def get(self, _url: str, timeout: int):
        assert timeout == 30000
        return self.response


class _Page:
    url = "https://qlvb.example/qlvbdh_lcu/main"

    def __init__(self, response: _Response):
        self.context = type("Context", (), {"request": _Request(response)})()


def _attachment() -> dict[str, str]:
    return {"name": "safe-file.bin", "hdd_file": "opaque-file-id", "type": "vb"}


def _part_files(directory: Path) -> list[Path]:
    return list(directory.glob("*.part-*"))


def test_unicode_escape_labels_decode_and_mojibake_is_rejected() -> None:
    assert cdp_workflow.normalize_text(cdp_workflow.MENU_GROUP) == "quan ly van ban den"
    assert cdp_workflow.normalize_text(cdp_workflow.CATEGORY_INCOMING_REGISTRY) == "van ban vao so"
    assert cdp_workflow.normalize_text(cdp_workflow.CATEGORY_FORWARDED_PROCESSED) == "da chuyen xu ly"
    assert cdp_workflow.normalize_text(cdp_workflow.CATEGORY_PROCESSED) == "da xu ly"
    cdp_workflow.validate_category_labels()
    with pytest.raises(RuntimeError, match="CATEGORY_LABEL_MOJIBAKE_DETECTED"):
        cdp_workflow.validate_category_labels(["VÄƒn báº£n vÃ o sá»•"])


def test_cdp_path_uses_connect_over_cdp_and_no_legacy_browser_creation() -> None:
    source = inspect.getsource(cdp_workflow)
    assert "connect_over_cdp(endpoint)" in source
    assert ".launch(" not in source
    assert "launch_persistent_context" not in source


def test_browser_context_page_close_calls_are_not_present() -> None:
    source = inspect.getsource(cdp_workflow)
    assert "browser.close(" not in source
    assert "context.close(" not in source
    assert "page.close(" not in source


def test_menu_flow_has_utf8_safe_expansion_guard_and_delayed_rescan() -> None:
    script = cdp_workflow.MENU_NAV_SCRIPT
    assert "stripCount(groupLabel)" in script
    assert "stripCount(label)" in script
    assert "expandedBefore = submenuCandidates().length > 0" in script
    assert "header.click()" in script
    assert "setTimeout(resolve, 900)" in script
    assert "submenu_candidate_count" in script


def test_table_validator_uses_structural_div_data_list_scoring() -> None:
    script = cdp_workflow.TABLE_VALIDATOR_SCRIPT
    assert "document.querySelectorAll('table')" in script
    assert "table.closest('#div_data_list')" in script
    assert "headers.includes('so ky hieu')" in script
    assert "headers.includes('trich yeu')" in script
    assert "headers.includes('files')" in script
    assert "window.__qlvb_cdp_selected_table" in script


def test_post_click_stabilization_precedes_document_discovery() -> None:
    source = inspect.getsource(cdp_workflow.run_cdp_three_category_smoke)
    post_click_index = source.index("poll_category_target_state")
    discovery_index = source.index("discover_attachment")
    assert post_click_index < discovery_index
    assert "CATEGORY_{category.index}_POST_CLICK_TARGET_STATE_TIMEOUT" in source


def test_neoremoting_legacy_call_contract_is_preserved() -> None:
    script = cdp_workflow.NEOREMOTING_SCRIPT
    assert "qlvb.van_ban_den.getFileAttachLst" in script
    assert "neo.getRSet.call(neo, operation" in script
    assert "parse_attachment_response" in inspect.getsource(cdp_workflow.discover_attachment)


def test_authenticated_direct_download_and_integrity_contracts_are_integrated() -> None:
    source = inspect.getsource(cdp_workflow.download_one)
    assert "build_legacy_download_url" in source
    assert "page.context.request.get" in source
    assert "detect_login_html" in source
    assert "validate_integrity" in source
    assert "os.replace" in source
    assert "NamedTemporaryFile" in source


def test_integrity_validation_accepts_pdf_and_zip(tmp_path) -> None:
    pdf_body = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
    pdf_path = tmp_path / "file.pdf"
    pdf_path.write_bytes(pdf_body)
    assert cdp_workflow.body_signature(pdf_body) == "PDF"
    assert cdp_workflow.validate_integrity(pdf_path, pdf_body, "PDF") == "PASS"

    zip_path = tmp_path / "file.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("a.txt", "ok")
    zip_body = zip_path.read_bytes()
    assert cdp_workflow.body_signature(zip_body) == "ZIP"
    assert cdp_workflow.validate_integrity(zip_path, zip_body, "ZIP") == "PASS"


def test_atomic_download_persists_valid_pdf_and_removes_temp_file(tmp_path) -> None:
    body = b"%PDF-1.7\n%%EOF\n"
    result = cdp_workflow.download_one(_Page(_Response(200, body)), tmp_path, _attachment())
    assert result.persisted is True
    assert result.signature == "PDF"
    assert result.integrity == "PASS"
    assert result.final_path and result.final_path.read_bytes() == body
    assert _part_files(tmp_path) == []


def test_atomic_download_persists_valid_zip_and_ole(tmp_path) -> None:
    zip_source = tmp_path / "source.zip"
    with zipfile.ZipFile(zip_source, "w") as archive:
        archive.writestr("document.xml", "ok")
    zip_result = cdp_workflow.download_one(_Page(_Response(200, zip_source.read_bytes())), tmp_path, _attachment())
    assert zip_result.persisted is True and zip_result.signature == "ZIP"

    ole_body = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 32
    ole_result = cdp_workflow.download_one(_Page(_Response(200, ole_body)), tmp_path, _attachment())
    assert ole_result.persisted is True and ole_result.signature == "OLE"
    assert _part_files(tmp_path) == []


@pytest.mark.parametrize(
    ("response", "failure_code"),
    [
        (_Response(200, b"<html><input type='password'></html>", "text/html"), "LOGIN_HTML_DETECTED"),
        (_Response(401, b"denied"), "SESSION_EXPIRED"),
        (_Response(403, b"denied"), "SESSION_EXPIRED"),
        (_Response(500, b"server-error"), "HTTP_DOWNLOAD_FAILED"),
        (_Response(200, b"not-a-supported-file"), "UNSUPPORTED_OR_UNKNOWN_FILE_SIGNATURE"),
        (_Response(200, b""), "EMPTY_RESPONSE_BODY"),
    ],
)
def test_invalid_response_is_not_persisted(tmp_path, response, failure_code) -> None:
    result = cdp_workflow.download_one(_Page(response), tmp_path, _attachment())
    assert result.persisted is False
    assert result.failure_code == failure_code
    assert list(tmp_path.iterdir()) == []


def test_existing_final_file_is_not_overwritten(tmp_path) -> None:
    existing = tmp_path / "safe-file.bin"
    existing.write_bytes(b"existing")
    body = b"%PDF-1.7\n%%EOF\n"
    result = cdp_workflow.download_one(_Page(_Response(200, body)), tmp_path, _attachment())
    assert result.persisted is True
    assert existing.read_bytes() == b"existing"
    assert result.final_path and result.final_path.name == "safe-file-1.bin"


def test_integrity_failure_size_mismatch_and_rename_failure_leave_no_final_or_temp(tmp_path, monkeypatch) -> None:
    body = b"%PDF-1.7\n%%EOF\n"
    assert cdp_workflow.validate_integrity(tmp_path / "missing.pdf", body, "PDF") == "FAIL"

    monkeypatch.setattr(cdp_workflow, "validate_integrity", lambda *_args: "FAIL")
    failed = cdp_workflow.download_one(_Page(_Response(200, body)), tmp_path, _attachment())
    assert failed.failure_code == "INTEGRITY_CHECK_FAILED"
    assert failed.persisted is False
    assert list(tmp_path.iterdir()) == []

    monkeypatch.setattr(cdp_workflow, "validate_integrity", lambda *_args: "PASS")
    monkeypatch.setattr(cdp_workflow.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("rename failed")))
    rename_failed = cdp_workflow.download_one(_Page(_Response(200, body)), tmp_path, _attachment())
    assert rename_failed.failure_code == "ATOMIC_PERSISTENCE_FAILED"
    assert rename_failed.persisted is False
    assert list(tmp_path.iterdir()) == []


def test_runner_exposes_explicit_source_level_smoke_flag() -> None:
    import tools.qlvb_downloader.runner as runner

    source = inspect.getsource(runner)
    assert "--cdp-three-category-smoke" in source
    assert "run_cdp_three_category_smoke" in source
    assert "LIVE_ACCEPTANCE" in source
