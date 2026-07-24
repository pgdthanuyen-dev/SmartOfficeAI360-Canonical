from __future__ import annotations

from pathlib import Path
import inspect
from urllib.parse import parse_qsl, urlparse
from unittest.mock import MagicMock

import pytest
from playwright.sync_api import sync_playwright

from tools.qlvb_downloader.config import QLVBConfig, normalize_legacy_config
from tools.qlvb_downloader.downloader import (
    CATEGORY_ORDER,
    CATEGORY_ROUTE_MARKERS,
    QLVBDownloader,
    classify_download_body_prefix,
)
from tools.qlvb_downloader.models import ATTACHMENT_VALIDATED, DOCUMENT_FAILED, AttachmentInfo, DocumentRecord
from tools.qlvb_downloader.neoremoting import (
    MAX_ATTACHMENTS,
    MAX_RESPONSE_BYTES,
    NeoRemotingAttachmentDiscoveryAdapter,
    NeoRemotingDiscoveryError,
    build_legacy_download_url,
    classify_hdd_file,
    extract_document_id,
    parse_attachment_response,
    validate_neoremoting_download_url,
)


class FakePage:
    def __init__(self, result):
        self.result = result
        self.url = "https://qlvb.laichau.gov.vn/qlvbdh_lcu/main"
        self.evaluate_calls = []

    def evaluate(self, script, args=None):
        self.evaluate_calls.append((script, args))
        return self.result


def make_downloader(tmp_path: Path) -> QLVBDownloader:
    config = QLVBConfig(qlvb_base_url="https://qlvb.laichau.gov.vn/qlvbdh_lcu/main")
    config.save_root = str(tmp_path)
    return QLVBDownloader(config)


def make_record() -> DocumentRecord:
    return DocumentRecord(
        direction="incoming",
        source_url="https://qlvb.laichau.gov.vn/qlvbdh_lcu/main",
        row_index=1,
        row_text="fixture row",
        doc_id="incoming_fixture",
        source_category="incoming_pending",
        metadata={"source_document_id": "123456"},
    )


def valid_payload(name: str = "tệp đính kèm.pdf") -> str:
    return '[{"name": "' + name + '", "hdd_file": "upload/2026/demo.pdf", "type": "vb", "is_phieu_trinh": "0"}]'


def test_document_id_prefers_canonical_attribute():
    extracted = extract_document_id(attributes={"data-document-id": "123456"}, row_id="vb_999999")
    assert extracted and extracted.document_id == "123456"
    assert extracted.source_method == "canonical_data_attribute"


def test_config_maps_incoming_registry_without_reusing_legacy_pending_url():
    normalized = normalize_legacy_config({
        "incoming_registry_url": "https://qlvb.laichau.gov.vn/registry",
        "incoming_pending_url": "https://qlvb.laichau.gov.vn/pending",
    })

    assert normalized["incoming_registry_url"].endswith("/registry")
    assert normalized["incoming_pending_url"].endswith("/pending")


def test_document_id_supports_legacy_row_id():
    extracted = extract_document_id(row_id="vb_123456")
    assert extracted and extracted.document_id == "123456"
    assert extracted.source_method == "legacy_row_id"


def test_document_id_supports_allowlisted_onclick_only():
    extracted = extract_document_id(onclick="showDocDetail('123456')")
    assert extracted and extracted.source_method == "legacy_onclick_show_detail"
    assert extract_document_id(onclick="renderTitle('20260722')") is None


def test_document_id_supports_allowlisted_href_query_only():
    extracted = extract_document_id(href="/detail?id=123456&date=20260722")
    assert extracted and extracted.document_id == "123456"
    assert extract_document_id(href="/detail?date=20260722") is None


@pytest.mark.parametrize("value", ["", "12", "123x", "2026-07-22"])
def test_document_id_rejects_malformed_values(value):
    assert extract_document_id(attributes={"data-document-id": value}) is None


def test_unicode_does_not_change_explicit_document_id():
    extracted = extract_document_id(onclick="getFileAttachLst('987654', 0)")
    assert extracted and extracted.document_id == "987654"


def test_document_id_accepts_all_file_download_only_as_a_row_scoped_identifier():
    extracted = extract_document_id(onclick="javascript:allFileDownload(2573137)")
    assert extracted and extracted.document_id == "2573137"
    assert extracted.source_method == "legacy_onclick_all_file_download"


def test_parser_accepts_json_and_unicode_filename():
    parsed = parse_attachment_response(valid_payload())
    assert parsed[0]["name"] == "tệp đính kèm.pdf"


def test_parser_accepts_bounded_json_like_literal():
    parsed = parse_attachment_response("[{name: 'a.pdf', hdd_file: 'upload/a.pdf', type: 'vb', is_phieu_trinh: '0'}]")
    assert parsed[0]["hdd_file"] == "upload/a.pdf"


def test_parser_accepts_verified_runtime_metadata_but_does_not_return_it():
    raw = '[{"name":"a.pdf","hdd_file":"upload/a.pdf","file_id":"7","created_date":"x","user_name":"u","ky_so_info":"","vanban_chinh_phu":"0"}]'
    assert parse_attachment_response(raw) == [
        {"name": "a.pdf", "hdd_file": "upload/a.pdf", "type": "vb"}
    ]


def test_parser_accepts_verified_runtime_metadata_in_json_like_literal():
    raw = "[{name:'a.pdf',hdd_file:'upload/a.pdf',file_id:'7',created_date:'x',user_name:'u',ky_so_info:'',vanban_chinh_phu:'0'}]"
    assert parse_attachment_response(raw)[0]["name"] == "a.pdf"


def test_parser_ignores_bounded_scalar_metadata_not_used_for_download():
    raw = "[{name:'a.pdf',hdd_file:'upload/a.pdf',server_revision:7,optional_note:null,active:true}]"
    assert parse_attachment_response(raw) == [
        {"name": "a.pdf", "hdd_file": "upload/a.pdf", "type": "vb"}
    ]


def test_parser_rejects_nested_or_dangerous_extra_metadata():
    for raw in (
        '[{"name":"a.pdf","hdd_file":"upload/a.pdf","extra":{"nested":1}}]',
        "[{name:'a.pdf',hdd_file:'upload/a.pdf',__proto__:'x'}]",
    ):
        with pytest.raises(NeoRemotingDiscoveryError, match="NEOREMOTING_INVALID_RESPONSE"):
            parse_attachment_response(raw)


@pytest.mark.parametrize("payload", ["<html>login</html>", "[function(){return 1}]", "[{name: 'a', hdd_file: 'x'}];"])
def test_parser_rejects_html_and_script_forms(payload):
    with pytest.raises(NeoRemotingDiscoveryError, match="NEOREMOTING_INVALID_RESPONSE"):
        parse_attachment_response(payload)


def test_parser_rejects_oversize_too_many_and_deep_values():
    with pytest.raises(NeoRemotingDiscoveryError):
        parse_attachment_response("[" + " " * MAX_RESPONSE_BYTES + "]")
    too_many = [{"name": "a.pdf", "hdd_file": "upload/a.pdf", "type": "vb"}] * (MAX_ATTACHMENTS + 1)
    with pytest.raises(NeoRemotingDiscoveryError):
        parse_attachment_response(__import__("json").dumps(too_many))
    with pytest.raises(NeoRemotingDiscoveryError):
        parse_attachment_response("[[[[[[[]]]]]]]")


def test_parser_reports_no_attachments_when_only_presentation_files():
    with pytest.raises(NeoRemotingDiscoveryError, match="NO_ATTACHMENTS"):
        parse_attachment_response('[{"name":"x.pdf","hdd_file":"upload/x.pdf","type":"vb","is_phieu_trinh":"1"}]')


def test_legacy_download_url_has_only_verified_keys_and_path():
    url = build_legacy_download_url(
        "https://qlvb.laichau.gov.vn/qlvbdh_lcu/main",
        "văn bản.pdf",
        "upload/2026/a.pdf",
        "vb",
    )
    assert url.startswith("https://qlvb.laichau.gov.vn/qlvbdh_lcu/smartoffice/jbm/download.jsp?")
    assert all(key in url for key in ("5E1XCBS.", "5FpXTEW.", "TFbm5O."))
    assert "văn bản" not in url


def test_upload_relative_path_uses_exact_legacy_parameter_contract():
    value = "upload/2026/a.pdf"
    url = build_legacy_download_url(
        "https://qlvb.laichau.gov.vn/qlvbdh_lcu/main", "a.pdf", value, "vb"
    )
    assert "5FpXTEW.=upload/2026/a.pdf" in url
    shape = classify_hdd_file(value)
    assert shape["is_relative_path"] is True
    assert shape["is_absolute_http_url"] is False
    assert shape["is_server_file_id"] is False
    assert shape["length"] == len(value)


def test_hdd_file_token_is_encoded_for_legacy_endpoint_not_treated_as_url():
    shape = classify_hdd_file("opaqueFileId")
    url = build_legacy_download_url(
        "https://qlvb.laichau.gov.vn/qlvbdh_lcu/main", "a.pdf", "opaqueFileId", "vb"
    )
    assert shape["is_server_file_id"] is True
    assert shape["is_relative_path"] is False
    assert "opaqueFileId" not in url


@pytest.mark.parametrize(("data", "expected"), [
    (b"%PDF-1.7\nfixture", "PDF"),
    (b"PK\x03\x04fixture", "DOCX_XLSX_PPTX_ZIP"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1fixture", "OLE_OFFICE"),
    (b"<!doctype html><form>login</form>", "HTML"),
    (b'{"error":"fixture"}', "JSON"),
    (b"", "EMPTY"),
])
def test_download_body_prefix_classification_is_value_free(data, expected):
    assert classify_download_body_prefix(data) == expected


@pytest.mark.parametrize(("suffix", "data"), [
    (".bin", b"%PDF-1.7\n" + b"x" * 128),
    (".doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"x" * 128),
])
def test_octet_stream_valid_signature_is_accepted(tmp_path, suffix, data):
    downloader = make_downloader(tmp_path)
    path = tmp_path / ("fixture" + suffix)
    path.write_bytes(data)
    result = downloader._validate_downloaded_file(path, {"content-type": "application/octet-stream"})
    assert result["size_bytes"] == len(data)


def test_live_r13_ms_pdf_mime_is_accepted_by_pdf_signature(tmp_path):
    downloader = make_downloader(tmp_path)
    path = tmp_path / "fixture.bin"
    data = b"%PDF-1.7\n" + b"x" * 128
    path.write_bytes(data)

    result = downloader._validate_downloaded_file(
        path, {"content-type": "application/vnd.ms-pdf"}
    )

    assert result["body_prefix_class"] == "PDF"


def test_direct_transport_records_only_safe_authenticated_response_shape():
    record = make_record()
    response = MagicMock()
    response.url = "https://qlvb.laichau.gov.vn/qlvbdh_lcu/smartoffice/jbm/download.jsp?secret=redacted"
    response.status = 200
    response.headers = {"content-type": "application/octet-stream", "content-length": "140"}
    QLVBDownloader._record_direct_download_transport(
        record,
        "https://qlvb.laichau.gov.vn/qlvbdh_lcu/smartoffice/jbm/download.jsp?token=redacted",
        response,
        b"%PDF-1.7\n" + b"x" * 128,
    )
    diagnostic = record.metadata["last_download_transport"]
    assert diagnostic["authenticated_context_used"] is True
    assert diagnostic["request_method"] == "GET"
    assert diagnostic["referer_present"] is False
    assert diagnostic["body_prefix_class"] == "PDF"
    assert "token" not in str(diagnostic)
    assert "secret" not in str(diagnostic)


@pytest.mark.parametrize("url", [
    "javascript:alert(1)",
    "data:text/plain,x",
    "file:///tmp/a.pdf",
    "https://example.invalid/qlvbdh_lcu/smartoffice/jbm/download.jsp?5E1XCBS.=a&5FpXTEW.=b&TFbm5O.=c",
    "https://qlvb.laichau.gov.vn/qlvbdh_lcu/smartoffice/jbm/../download.jsp?5E1XCBS.=a&5FpXTEW.=b&TFbm5O.=c",
])
def test_download_url_rejects_untrusted_scheme_host_or_path(url):
    with pytest.raises(NeoRemotingDiscoveryError):
        validate_neoremoting_download_url(url, allowed_hosts={"qlvb.laichau.gov.vn"})


def test_adapter_uses_verified_neoremoting_contract_without_eval():
    page = FakePage({"state": "SUCCESS", "raw": valid_payload()})
    adapter = NeoRemotingAttachmentDiscoveryAdapter("https://qlvb.laichau.gov.vn/qlvbdh_lcu/main")
    candidates = adapter.discover(page, document_id="123456", category="incoming_pending", correlation_id="test")
    assert len(candidates) == 1
    assert candidates[0].source_method == "NEOREMOTING"
    assert candidates[0].attachment_id == "upload/2026/demo.pdf"
    assert candidates[0].href.startswith("https://qlvb.laichau.gov.vn/")
    assert "neo.getRSet.call(neo, operation" in page.evaluate_calls[0][0]
    assert "JSON.stringify(data)" in page.evaluate_calls[0][0]
    assert "eval(" not in page.evaluate_calls[0][0]
    assert "function(data)" in page.evaluate_calls[0][0]
    assert "callbackArgCount" in page.evaluate_calls[0][0]


def test_adapter_selects_child_frame_when_top_frame_has_no_runtime():
    top = FakePage({"neoType": "undefined", "getRSetType": "undefined"})
    child = FakePage({"neoType": "object", "getRSetType": "function"})
    success = {"state": "SUCCESS", "raw": valid_payload(), "shape": {"resultType": "string"}}
    child_results = iter([child.result, success])
    child.evaluate = lambda script, args=None: next(child_results)
    page = MagicMock()
    page.frames = [top, child]

    adapter = NeoRemotingAttachmentDiscoveryAdapter("https://qlvb.laichau.gov.vn/qlvbdh_lcu/main")
    assert len(adapter.discover(page, document_id="123456", category="incoming_processed", correlation_id="test")) == 1
    assert adapter.last_probe["frames"][-1]["getrset_type"] == "function"
    assert adapter.last_probe["shape"]["resultType"] == "string"


@pytest.mark.parametrize("neo_type", ["object", "function"])
def test_runtime_scope_accepts_object_or_function_when_getrset_is_function(neo_type):
    frame = FakePage({"neoType": neo_type, "getRSetType": "function"})
    page = MagicMock()
    page.frames = [frame]

    selected, inspected = NeoRemotingAttachmentDiscoveryAdapter._select_runtime_scope(page)

    assert selected is frame
    assert inspected[0] == {"frame_index": 0, "neo_type": neo_type, "getrset_type": "function"}


def test_function_object_without_getrset_is_classified_exactly():
    frame = FakePage({"neoType": "function", "getRSetType": "undefined"})
    page = MagicMock()
    page.frames = [frame]

    with pytest.raises(NeoRemotingDiscoveryError, match="NEOREMOTING_GETRSET_NOT_FUNCTION"):
        NeoRemotingAttachmentDiscoveryAdapter._select_runtime_scope(page)


def test_undefined_neoremoting_is_classified_exactly():
    frame = FakePage({"neoType": "undefined", "getRSetType": "undefined"})
    page = MagicMock()
    page.frames = [frame]

    with pytest.raises(NeoRemotingDiscoveryError, match="NEOREMOTING_OBJECT_NOT_AVAILABLE"):
        NeoRemotingAttachmentDiscoveryAdapter._select_runtime_scope(page)


def test_about_blank_is_skipped_and_qlvb_function_object_frame_is_selected():
    blank = FakePage({"neoType": "function", "getRSetType": "function"})
    blank.url = "about:blank"
    qlvb = FakePage({"neoType": "function", "getRSetType": "function"})
    page = MagicMock()
    page.frames = [blank, qlvb]

    selected, inspected = NeoRemotingAttachmentDiscoveryAdapter._select_runtime_scope(page)

    assert selected is qlvb
    assert inspected[0]["neo_type"] == "skipped_about_blank"
    assert blank.evaluate_calls == []


def test_callback_promise_waits_uses_callback_data_and_preserves_this_binding():
    page = FakePage({"state": "SUCCESS", "raw": valid_payload(), "shape": {"resultType": "string"}})
    NeoRemotingAttachmentDiscoveryAdapter("https://qlvb.laichau.gov.vn/qlvbdh_lcu/main").discover(
        page, document_id="123456", category="incoming_processed", correlation_id="test"
    )
    script = page.evaluate_calls[0][0]
    assert "new Promise" in script
    assert "neo.getRSet.call(neo, operation" in script
    assert "NEOREMOTING_CALLBACK_TIMEOUT" in script
    assert "NEOREMOTING_SYNCHRONOUS_EXCEPTION" in script
    assert "resolve({state: 'SUCCESS', raw, shape})" in script
    assert "eval(" not in script


def test_callback_array_is_captured_and_safely_normalized():
    page = FakePage({
        "state": "SUCCESS",
        "raw": valid_payload(),
        "shape": {"resultType": "object", "isArray": True, "arrayLength": 1},
    })
    adapter = NeoRemotingAttachmentDiscoveryAdapter("https://qlvb.laichau.gov.vn/qlvbdh_lcu/main")

    assert len(adapter.discover(page, document_id="123456", category="incoming_processed", correlation_id="test")) == 1
    assert adapter.last_probe["shape"]["isArray"] is True


@pytest.mark.parametrize("state", [
    "NEOREMOTING_OBJECT_NOT_AVAILABLE",
    "NEOREMOTING_GETRSET_NOT_FUNCTION",
    "NEOREMOTING_CALLBACK_TIMEOUT",
    "NEOREMOTING_SYNCHRONOUS_EXCEPTION",
])
def test_adapter_classifies_expected_primary_failures(state):
    adapter = NeoRemotingAttachmentDiscoveryAdapter("https://qlvb.laichau.gov.vn/qlvbdh_lcu/main")
    with pytest.raises(NeoRemotingDiscoveryError, match=state):
        adapter.discover(FakePage({"state": state}), document_id="123456", category="incoming_pending", correlation_id="test")


def test_neoremoting_success_skips_detail_page_and_uses_existing_downloader(tmp_path):
    downloader = make_downloader(tmp_path)
    rec = make_record()
    page = MagicMock()
    page.url = "https://qlvb.laichau.gov.vn/qlvbdh_lcu/main"
    downloader._is_logged_in = MagicMock(return_value=True)
    downloader._goto_detail_with_retry = MagicMock(side_effect=AssertionError("detail must not open"))
    downloader._write_outputs_and_report = MagicMock()
    downloader._download_attachments = MagicMock(side_effect=lambda _page, record: setattr(record.attachments[0], "status", ATTACHMENT_VALIDATED))

    from tools.qlvb_downloader import downloader as downloader_module
    original = downloader_module.NeoRemotingAttachmentDiscoveryAdapter
    downloader_module.NeoRemotingAttachmentDiscoveryAdapter = MagicMock(return_value=MagicMock(discover=MagicMock(return_value=[AttachmentInfo(text="a.pdf", href="https://qlvb.laichau.gov.vn/qlvbdh_lcu/smartoffice/jbm/download.jsp?5E1XCBS.=a&5FpXTEW.=b&TFbm5O.=c", source_method="NEOREMOTING")])))
    try:
        downloader._process_record(page, rec, list_page=page)
    finally:
        downloader_module.NeoRemotingAttachmentDiscoveryAdapter = original

    assert rec.metadata["attachment_discovery_method"] == "NEOREMOTING"
    assert rec.attachments[0].status == ATTACHMENT_VALIDATED
    downloader._goto_detail_with_retry.assert_not_called()


def test_access_denied_does_not_fallback_to_detail_page(tmp_path):
    downloader = make_downloader(tmp_path)
    rec = make_record()
    page = MagicMock()
    page.url = "https://qlvb.laichau.gov.vn/qlvbdh_lcu/main"
    downloader._is_logged_in = MagicMock(return_value=False)
    downloader._goto_detail_with_retry = MagicMock(side_effect=AssertionError("must not fallback"))
    downloader._write_outputs_and_report = MagicMock()

    downloader._process_record(page, rec, list_page=page)

    assert rec.status == DOCUMENT_FAILED
    assert rec.error == "NEOREMOTING_ACCESS_DENIED"
    downloader._goto_detail_with_retry.assert_not_called()


def test_unavailable_neoremoting_uses_detail_dom_fallback_outside_strict_incoming_flow(tmp_path):
    downloader = make_downloader(tmp_path)
    rec = make_record()
    rec.source_category = "incoming"
    rec.detail_url = "https://qlvb.laichau.gov.vn/detail/123"
    page = MagicMock()
    page.url = "https://qlvb.laichau.gov.vn/qlvbdh_lcu/main"
    downloader._is_logged_in = MagicMock(return_value=True)
    downloader._goto_detail_with_retry = MagicMock()
    downloader._ensure_usable_detail_page = MagicMock()
    downloader._merge_detail_metadata = MagicMock()
    downloader._extract_attachments = MagicMock(return_value=[AttachmentInfo(text="fallback.pdf", href="https://qlvb.laichau.gov.vn/fallback.pdf")])
    downloader._download_attachments = MagicMock(side_effect=lambda _page, record: setattr(record.attachments[0], "status", ATTACHMENT_VALIDATED))
    downloader._write_outputs_and_report = MagicMock()

    from tools.qlvb_downloader import downloader as downloader_module
    original = downloader_module.NeoRemotingAttachmentDiscoveryAdapter
    downloader_module.NeoRemotingAttachmentDiscoveryAdapter = MagicMock(return_value=MagicMock(discover=MagicMock(side_effect=NeoRemotingDiscoveryError("NEOREMOTING_NOT_AVAILABLE"))))
    try:
        downloader._process_record(page, rec, list_page=page)
    finally:
        downloader_module.NeoRemotingAttachmentDiscoveryAdapter = original

    assert rec.metadata["attachment_discovery_method"] == "DETAIL_DOM"
    downloader._goto_detail_with_retry.assert_called_once()


def test_strict_incoming_flow_never_falls_back_to_page_wide_detail_download(tmp_path):
    downloader = make_downloader(tmp_path)
    rec = make_record()
    page = MagicMock()
    page.url = "https://qlvb.laichau.gov.vn/qlvbdh_lcu/main"
    downloader._is_logged_in = MagicMock(return_value=True)
    downloader._goto_detail_with_retry = MagicMock(side_effect=AssertionError("strict flow must not open detail"))
    downloader._extract_attachments = MagicMock(side_effect=AssertionError("strict flow must not scan detail"))
    downloader._write_outputs_and_report = MagicMock()

    from tools.qlvb_downloader import downloader as downloader_module
    original = downloader_module.NeoRemotingAttachmentDiscoveryAdapter
    downloader_module.NeoRemotingAttachmentDiscoveryAdapter = MagicMock(
        return_value=MagicMock(discover=MagicMock(side_effect=NeoRemotingDiscoveryError("NEOREMOTING_NOT_AVAILABLE")))
    )
    try:
        downloader._process_record(page, rec, list_page=page)
    finally:
        downloader_module.NeoRemotingAttachmentDiscoveryAdapter = original

    assert rec.status == DOCUMENT_FAILED
    assert rec.error == "NEOREMOTING_NOT_AVAILABLE"
    downloader._goto_detail_with_retry.assert_not_called()
    downloader._extract_attachments.assert_not_called()


def test_direct_transport_diagnostics_exclude_query_material():
    rec = make_record()
    response = type("Response", (), {
        "url": "https://qlvb.laichau.gov.vn/qlvbdh_lcu/smartoffice/jbm/download.jsp?secret=not-recorded",
        "status": 200,
        "headers": {"content-type": "application/pdf; charset=binary", "content-disposition": "attachment"},
    })()
    QLVBDownloader._record_direct_download_transport(rec, response.url, response)
    transport = rec.metadata["last_download_transport"]
    assert transport["method"] == "AUTHENTICATED_DIRECT_REQUEST"
    assert transport["http_status"] == 200
    assert transport["content_disposition_present"] is True
    assert "?" not in transport["url"] and "secret" not in str(transport)


@pytest.fixture
def browser_page():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        context.route(
            "https://qlvb.laichau.gov.vn/**",
            lambda route: route.fulfill(status=200, content_type="text/html", body="<main></main>"),
        )
        page = context.new_page()
        page.goto("https://qlvb.laichau.gov.vn/qlvbdh_lcu/main?6yXl=DEN_CAN_VAO_SO")
        yield page
        context.close()
        browser.close()


def _incoming_category_shell(category_label: str, table_html: str) -> str:
    return f"""
        <nav class='breadcrumb'>Quản lý văn bản đến / {category_label}</nav>
        <aside><a href='/help/user-guide.pdf'>User guide PDF</a></aside>
        <button onclick=\"allFileDownload('999999')\">All files from another document</button>
        <button onclick=\"inTaiPhieuTrinh('999999')\">Print another document</button>
        <a class='active' aria-current='page'>{category_label}</a>
        <h1>{category_label}</h1>
        <main>{table_html}</main>
    """


def _document_table(rows: str) -> str:
    return f"""
        <table id='validated-document-table'>
          <thead><tr>
            <th>S\u1ed1 \u0111\u1ebfn</th><th>S\u1ed1 k\u00fd hi\u1ec7u</th><th>Ng\u00e0y \u0111\u1ebfn</th>
            <th>C\u01a1 quan g\u1eedi</th><th>Tr\u00edch y\u1ebfu</th><th>Files</th><th>Thao t\u00e1c</th>
          </tr></thead>
          <tbody>{rows}</tbody>
        </table>
    """


def test_route_validation_accepts_qlvb_html_title_when_no_h1_is_rendered(browser_page, tmp_path):
    downloader = make_downloader(tmp_path)
    label = "V\u0103n b\u1ea3n \u0111\u1ebfn ch\u1edd x\u1eed l\u00fd"
    browser_page.set_content(
        f"<title>Ch\u1edd x\u1eed l\u00fd</title><ol class='breadcrumb'>Qu\u1ea3n l\u00fd v\u0103n b\u1ea3n \u0111\u1ebfn / Ch\u1edd x\u1eed l\u00fd</ol>"
        f"<ul><li class='active'>{label}</li></ul>"
    )

    route = downloader._validate_incoming_category_route(browser_page, "incoming_pending")

    assert route["host"] is True
    assert route["route_marker"] is True
    assert route["breadcrumb"] is True
    assert route["active_menu"] is True
    assert route["title"] is True
    assert route["valid"] is True


def test_registry_route_validation_uses_breadcrumb_and_active_menu(browser_page, tmp_path):
    downloader = make_downloader(tmp_path)
    label = "V\u0103n b\u1ea3n v\u00e0o s\u1ed5"
    browser_page.set_content(
        f"<ol class='breadcrumb'>Qu\u1ea3n l\u00fd v\u0103n b\u1ea3n \u0111\u1ebfn / {label}</ol>"
        f"<ul id='full_menu'><li class='active'><a>{label} (18)</a></li></ul>"
    )

    route = downloader._validate_incoming_category_route(browser_page, "incoming_registry")

    assert route["breadcrumb"] is True
    assert route["active_menu"] is True
    assert route["host"] is True
    assert route["route_marker"] is True
    assert route["valid"] is True


def test_registry_route_marker_is_required_before_any_table_scan(browser_page, tmp_path):
    downloader = make_downloader(tmp_path)
    label = "V\u0103n b\u1ea3n v\u00e0o s\u1ed5"
    browser_page.goto("https://qlvb.laichau.gov.vn/qlvbdh_lcu/main")
    browser_page.set_content(_incoming_category_shell(label, _document_table(_registry_rows(["123456"]))))
    downloader._goto = MagicMock()
    downloader._find_document_table = MagicMock()

    result = downloader._process_direction(
        browser_page, "incoming", 1,
        fixed_url="https://qlvb.laichau.gov.vn/registry",
        category="incoming_registry",
    )

    assert result["status"] == "FAILED"
    assert result["error"] == "INCOMING_REGISTRY_ROUTE_MARKER_MISSING"
    downloader._find_document_table.assert_not_called()


def test_registry_breadcrumb_and_active_menu_must_match_before_any_table_scan(browser_page, tmp_path):
    downloader = make_downloader(tmp_path)
    label = "V\u0103n b\u1ea3n v\u00e0o s\u1ed5"
    browser_page.set_content(
        "<nav class='breadcrumb'>Other section</nav><a class='active'>" + label + "</a><main>" +
        _document_table(_registry_rows(["123456"])) + "</main>"
    )
    downloader._goto = MagicMock()
    downloader._find_document_table = MagicMock()

    result = downloader._process_direction(
        browser_page, "incoming", 1,
        fixed_url="https://qlvb.laichau.gov.vn/registry",
        category="incoming_registry",
    )

    assert result["status"] == "FAILED"
    assert result["error"] == "INCOMING_REGISTRY_BREADCRUMB_MISMATCH"
    downloader._find_document_table.assert_not_called()


def test_registry_table_must_be_in_main_content(browser_page, tmp_path):
    downloader = make_downloader(tmp_path)
    label = "V\u0103n b\u1ea3n v\u00e0o s\u1ed5"
    browser_page.set_content(
        "<nav class='breadcrumb'>Qu\u1ea3n l\u00fd v\u0103n b\u1ea3n \u0111\u1ebfn / " + label + "</nav>"
        "<a class='active'>" + label + "</a><aside>" + _document_table(_registry_rows(["123456"])) + "</aside>"
    )

    assert downloader._find_document_table(browser_page, allow_fallback=False) is None


def test_registry_route_fallback_preserves_in_memory_session_parameters_without_logging_them(tmp_path):
    downloader = make_downloader(tmp_path)
    page = MagicMock()
    page.url = "https://qlvb.laichau.gov.vn/qlvbdh_lcu/main?session=current&6yXl=WRONG"
    downloader._goto = MagicMock()

    downloader._fallback_to_incoming_registry_route(page)

    target = downloader._goto.call_args.args[1]
    assert "session=current" in target
    assert "6yXl=DEN_CAN_VAO_SO" in target
    assert "6yXl=WRONG" not in target


def test_registry_menu_navigation_expands_only_incoming_parent(browser_page, tmp_path):
    downloader = make_downloader(tmp_path)
    downloader.browser_context = browser_page.context
    browser_page.goto("https://qlvb.laichau.gov.vn/qlvbdh_lcu/main")
    browser_page.set_content("""
        <ol id='crumb' class='breadcrumb'>Home</ol>
        <ul id='full_menu'>
          <li id='incoming-parent'>
            <a onclick="this.parentElement.className='open'; document.getElementById('children').style.display='block'">Quản lý văn bản đến</a>
            <ul id='children' style='display:none'>
              <li><a onclick="this.parentElement.className='active'; document.getElementById('crumb').textContent='Quản lý văn bản đến / Văn bản vào sổ'">Văn bản vào sổ (27)</a></li>
              <li><a>Chờ xử lý</a></li>
            </ul>
          </li>
        </ul>
    """)

    assert downloader.open_incoming_category(browser_page, "incoming_registry") is browser_page
    assert downloader._validate_incoming_category_route(browser_page, "incoming_registry")["valid"] is True


def _workflow_login_page(downloader):
    page = MagicMock()
    page.url = "https://qlvb.laichau.gov.vn/qlvbdh_lcu/main?session=current&locale=vi"
    page.context = downloader.browser_context
    return page


def test_registry_workflow_stops_after_registry_download(tmp_path):
    downloader = make_downloader(tmp_path)
    downloader.browser_context = MagicMock()
    downloader.config.incoming_registry_url = "https://qlvb.laichau.gov.vn/registry"
    downloader.config.incoming_processed_url = "https://qlvb.laichau.gov.vn/processed"
    downloader._process_direction = MagicMock(return_value={"status": "DONE", "processed": 1, "document_count": 18, "downloaded_files": 1})

    processed = downloader._run_incoming_registry_workflow(_workflow_login_page(downloader), 1, use_fixed_urls=True)

    assert processed == 1
    assert downloader._process_direction.call_count == 1
    assert downloader._process_direction.call_args.kwargs["category"] == "incoming_registry"
    assert "incoming_pending" not in str(downloader._process_direction.call_args_list)


def test_controlled_workflow_downloads_at_most_one_document_from_each_of_three_categories(tmp_path):
    downloader = make_downloader(tmp_path)
    downloader.browser_context = MagicMock()
    downloader.open_category_resilient = MagicMock(side_effect=AssertionError("category click must not run"))
    downloader.resolve_active_qlvb_page = MagicMock(side_effect=AssertionError("resolver must not run"))
    downloader._process_direction = MagicMock(return_value={
        "status": "DONE", "processed": 1, "document_count": 10, "downloaded_files": 1
    })
    login_page = _workflow_login_page(downloader)

    processed = downloader._run_incoming_registry_workflow(login_page, 3, use_fixed_urls=True)

    assert processed == 3
    assert [call.kwargs["category"] for call in downloader._process_direction.call_args_list] == list(CATEGORY_ORDER)
    assert [call.args[2] for call in downloader._process_direction.call_args_list] == [1, 1, 1]
    assert all(call.args[0] is login_page for call in downloader._process_direction.call_args_list)
    downloader.browser_context.new_page.assert_not_called()
    downloader.open_category_resilient.assert_not_called()
    downloader.resolve_active_qlvb_page.assert_not_called()
    assert all(call.kwargs["fixed_url"] == "" for call in downloader._process_direction.call_args_list)


def test_controlled_workflow_stops_after_requested_two_documents(tmp_path):
    downloader = make_downloader(tmp_path)
    downloader.browser_context = MagicMock()
    downloader._process_direction = MagicMock(return_value={
        "status": "DONE", "processed": 1, "document_count": 10, "downloaded_files": 1
    })

    assert downloader._run_incoming_registry_workflow(_workflow_login_page(downloader), 2, use_fixed_urls=True) == 2
    assert downloader._process_direction.call_count == 2


def test_category_order_skips_pending_and_exhausts_all_three(tmp_path):
    downloader = make_downloader(tmp_path)
    downloader.browser_context = MagicMock()
    downloader.config.incoming_registry_url = "https://qlvb.laichau.gov.vn/registry"
    downloader.config.incoming_processed_url = "https://qlvb.laichau.gov.vn/processed"
    downloader._process_direction = MagicMock(
        return_value={"status": "EMPTY", "processed": 0, "document_count": 0, "downloaded_files": 0}
    )

    processed = downloader._run_incoming_registry_workflow(_workflow_login_page(downloader), 1, use_fixed_urls=True)

    assert processed == 0
    assert [call.kwargs["category"] for call in downloader._process_direction.call_args_list] == [
        "incoming_registry", "incoming_forwarded_processed", "incoming_processed"
    ]
    assert "incoming_pending" not in str(downloader._process_direction.call_args_list)


def test_invalid_neoremoting_response_uses_row_fallback_then_continues(tmp_path, monkeypatch):
    downloader = make_downloader(tmp_path)
    first = make_record()
    second = make_record()
    second.metadata["source_document_id"] = "123457"
    calls = []

    class Adapter:
        def __init__(self, *_args, **_kwargs): pass
        def discover(self, _page, *, document_id, **_kwargs):
            calls.append(document_id)
            if document_id == "123456":
                raise NeoRemotingDiscoveryError("NEOREMOTING_INVALID_RESPONSE")
            return [AttachmentInfo(text="a.pdf", href="https://qlvb.laichau.gov.vn/qlvbdh_lcu/smartoffice/jbm/download.jsp?5E1XCBS.=a&5FpXTEW.=b&TFbm5O.=c")]

    monkeypatch.setattr("tools.qlvb_downloader.downloader.NeoRemotingAttachmentDiscoveryAdapter", Adapter)
    downloader._row_scoped_attachment_fallback = MagicMock(return_value=[])
    result = {"invalid_response_count": 0}

    selected = downloader._select_first_incoming_row_with_attachments(MagicMock(), [first, second], result)

    assert selected is second
    assert calls == ["123456", "123457"]
    assert result["invalid_response_count"] == 1


def test_registry_empty_never_scans_page_actions_and_processed_row_stays_scoped(browser_page, tmp_path):
    downloader = make_downloader(tmp_path)
    registry_label = "V\u0103n b\u1ea3n v\u00e0o s\u1ed5"
    processed_label = "V\u0103n b\u1ea3n \u0111\u1ebfn \u0111\u00e3 x\u1eed l\u00fd"

    browser_page.set_content(_incoming_category_shell(registry_label, _document_table("")))
    assert downloader._validate_incoming_category_route(browser_page, "incoming_registry")["valid"] is True
    registry_headers = downloader._extract_headers(browser_page, allow_fallback=False)
    assert registry_headers
    assert downloader._extract_records_from_current_page(browser_page, "incoming", browser_page.url, registry_headers) == []

    downloader._goto = MagicMock()
    downloader._is_logged_in = MagicMock(return_value=True)
    registry = downloader._process_direction(
        browser_page,
        "incoming",
        1,
        fixed_url="https://qlvb.laichau.gov.vn/registry",
        category="incoming_registry",
    )
    assert registry["status"] == "EMPTY"
    assert registry["document_count"] == 0

    row = """
      <tr id='vb_123456'>
        <td>42</td><td>42/QD-TEST</td><td>22/07/2026</td><td>Test agency</td>
        <td>Processed document with attachment</td>
        <td><button onclick=\"getFileAttachLst('123456', 0)\">Files</button></td>
        <td><button onclick=\"inPhieuXl('123456')\">Print</button></td>
      </tr>
    """
    browser_page.set_content(_incoming_category_shell(processed_label, _document_table(row)))
    assert downloader._validate_incoming_category_route(browser_page, "incoming_processed")["valid"] is True
    headers = downloader._extract_headers(browser_page, allow_fallback=False)
    records = downloader._extract_records_from_current_page(browser_page, "incoming", browser_page.url, headers)

    assert len(records) == 1
    selected = records[0]
    assert selected.metadata["source_document_id"] == "123456"
    assert selected.metadata["row_has_attachment_indicator"] is True
    assert "user-guide" not in str(selected.metadata)
    assert "999999" not in str(selected.metadata)

    downloader._process_record = MagicMock(side_effect=lambda _detail, record, list_page: setattr(record, "status", "READY"))
    downloader._probe_incoming_row_attachments = MagicMock(return_value=True)
    processed = downloader._process_direction(
        browser_page,
        "incoming",
        1,
        fixed_url="https://qlvb.laichau.gov.vn/processed",
        category="incoming_processed",
    )
    assert processed["document_table_validated"] is True
    assert processed["document_count"] == 1
    assert downloader._process_record.call_count == 1
    assert downloader._process_record.call_args.args[1].metadata["source_document_id"] == "123456"


class _Tab:
    def __init__(self, url: str, name: str):
        self.url = url
        self.name = name
        self.closed = False
        self.brought_to_front = 0

    def is_closed(self):
        return self.closed

    def close(self):
        self.closed = True

    def title(self):
        return ""

    def wait_for_timeout(self, _milliseconds):
        return None

    def bring_to_front(self):
        self.brought_to_front += 1


class _TabContext:
    def __init__(self, pages):
        self.pages = pages


class _BlankMonitorContext:
    def __init__(self):
        self.pages = []
        self.handlers = {}

    def on(self, event, handler):
        self.handlers[event] = handler

    def emit_page(self, page):
        self.pages.append(page)
        if "page" in self.handlers:
            self.handlers["page"](page)


class _BlankMonitorPage(_Tab):
    def __init__(self, url, title=""):
        super().__init__(url, "monitor")
        self._title = title
        self.context = None
        self.handlers = {}
        self.waits = []

    def title(self):
        return self._title

    def wait_for_timeout(self, milliseconds):
        self.waits.append(milliseconds)

    def on(self, event, handler):
        self.handlers[event] = handler


class _MenuCollection:
    def __init__(self, items):
        self.items = items

    def count(self):
        return len(self.items)

    def nth(self, index):
        return self.items[index]


class _MenuItem:
    def __init__(self, text, attributes=None, children=None):
        self.text = text
        self.attributes = attributes or {}
        self.children = children or []
        self.parent_item = None

    def inner_text(self, timeout=0):
        return self.text

    def get_attribute(self, name):
        return self.attributes.get(name)

    def locator(self, selector):
        if selector == "xpath=ancestor::li[1]":
            return self.parent_item
        return _MenuCollection(self.children)


def test_category_route_map_reads_three_scoped_menu_routes_with_dynamic_count(tmp_path):
    downloader = make_downloader(tmp_path)
    routes = {
        "incoming_registry": "/qlvbdh_lcu/main?6yXl=DEN_CAN_VAO_SO&session=current",
        "incoming_forwarded_processed": "/qlvbdh_lcu/main?runtime=FORWARDED_CURRENT",
        "incoming_processed": "/qlvbdh_lcu/main?runtime=PROCESSED_CURRENT",
    }
    children = [
        _MenuItem("Văn bản vào sổ (27)", {"href": routes["incoming_registry"]}),
        _MenuItem("Đã chuyển xử lý", {"data-url": routes["incoming_forwarded_processed"]}),
        _MenuItem("Đã xử lý", {"onclick": "openPage('" + routes["incoming_processed"] + "')"}),
        _MenuItem("In văn bản", {"href": "/print"}),
    ]
    parent_item = _MenuItem("", children=children)
    parent_link = _MenuItem("Quản lý văn bản đến")
    parent_link.parent_item = parent_item
    page = MagicMock()
    page.url = "https://qlvb.laichau.gov.vn/qlvbdh_lcu/main?session=current"
    page.frames = []
    page.locator.return_value = _MenuCollection([parent_link, *children])

    discovered = downloader.discover_incoming_category_routes(page)

    assert set(discovered) == set(CATEGORY_ORDER)
    assert "DEN_CAN_VAO_SO" in discovered["incoming_registry"]
    assert downloader.run_summary["category_routes"] == {
        category: "VALIDATED" for category in CATEGORY_ORDER
    }


@pytest.mark.parametrize("route", [
    "javascript:openPage('/qlvbdh_lcu/main?x=1')",
    "about:blank",
    "blob:https://qlvb.laichau.gov.vn/value",
    "https://evil.example/qlvbdh_lcu/main?x=1",
])
def test_category_route_rejects_unsafe_or_cross_origin_values(tmp_path, route):
    downloader = make_downloader(tmp_path)
    item = _MenuItem("Đã xử lý", {"href": route})

    assert downloader._extract_category_route_from_menu_item(
        item, "https://qlvb.laichau.gov.vn/qlvbdh_lcu/main?session=current"
    ) == ""


def test_direct_category_navigation_does_not_log_session_query(tmp_path):
    downloader = make_downloader(tmp_path)
    downloader.logger = MagicMock()
    page = MagicMock()
    route = "https://qlvb.laichau.gov.vn/qlvbdh_lcu/main?session=SECRET&6yXl=DEN_CAN_VAO_SO"

    downloader._goto(page, route, "incoming_registry")

    logged = str(downloader.logger.info.call_args)
    assert "SECRET" not in logged
    assert "session=" not in logged
    assert "DEN_CAN_VAO_SO" not in logged
    assert "[REDACTED]" in logged
    page.goto.assert_called_once_with(route, wait_until="domcontentloaded", timeout=downloader.config.browser.timeout_ms)


def test_live_incoming_workflow_restores_r14_menu_path_without_experimental_navigation():
    source = inspect.getsource(QLVBDownloader._run_incoming_registry_workflow)

    assert "open_category_resilient" not in source
    assert "resolve_active_qlvb_page" not in source
    assert "build_category_url" not in source
    assert "CATEGORY_ROUTE_MARKERS" not in source
    assert "context.pages" not in source
    assert "new_page()" not in source
    assert "single_automation_page_used\"] = \"NO\"" in source
    assert "direct_category_navigation_used\"] = \"NO\"" in source
    assert "page_reacquisition_used\"] = \"NO\"" in source
    assert "blank_page_cleanup_used\"] = \"NO\"" in source


def test_legacy_category_route_markers_match_read_only_evidence():
    assert CATEGORY_ROUTE_MARKERS["incoming_registry"]["6yXl"] == "DEN_CAN_VAO_SO"
    assert CATEGORY_ROUTE_MARKERS["incoming_forwarded_processed"]["6yXl"] == "DEN_HE_THONG"
    assert CATEGORY_ROUTE_MARKERS["incoming_processed"]["6yXl"] == "DEN_DA_XU_LY"
    assert [CATEGORY_ROUTE_MARKERS[category]["CBAkTA9f5o.."] for category in CATEGORY_ORDER] == [
        "m2268", "m2270", "m2289"
    ]


def test_category_url_builder_preserves_session_and_only_overlays_route_markers():
    base = (
        "https://qlvb.laichau.gov.vn/qlvbdh_lcu/main?"
        "session=ephemeral&locale=vi&6yXl=OLD&CBAkTA9f5o..=old_menu"
    )

    built = QLVBDownloader.build_category_url(
        base, CATEGORY_ROUTE_MARKERS["incoming_forwarded_processed"]
    )
    query = dict(parse_qsl(urlparse(built).query, keep_blank_values=True))

    assert query["session"] == "ephemeral"
    assert query["locale"] == "vi"
    assert query["6yXl"] == "DEN_HE_THONG"
    assert query["CBAkTA9f5o.."] == "m2270"


def test_restored_r14_workflow_uses_authenticated_page_and_does_not_create_automation_page(tmp_path):
    downloader = make_downloader(tmp_path)
    context = MagicMock()
    downloader.browser_context = context
    login_page = _workflow_login_page(downloader)
    downloader.open_incoming_category = MagicMock(side_effect=lambda current_page, _category, **_kwargs: current_page)
    downloader._process_direction = MagicMock(return_value={
        "status": "DONE", "processed": 1, "document_count": 1, "downloaded_files": 1
    })

    assert downloader._run_incoming_registry_workflow(
        login_page, 3, use_fixed_urls=False
    ) == 3
    assert all(call.args[0] is login_page for call in downloader._process_direction.call_args_list)
    context.new_page.assert_not_called()
    assert downloader.run_summary["r14_known_good_workflow_restored"] == "YES"
    assert downloader.run_summary["r15_to_r21_experimental_flow_used"] == "NO"
    assert downloader.run_summary["blank_page_left_untouched"] == "YES"
    assert downloader.run_summary["single_automation_page_used"] == "NO"


def test_same_page_incoming_registry_smoke_reuses_authenticated_page(tmp_path):
    downloader = make_downloader(tmp_path)
    page = MagicMock()
    page.url = "https://qlvb.laichau.gov.vn/qlvbdh_lcu/main?session=current"
    page.is_closed.return_value = False
    downloader._is_logged_in = MagicMock(return_value=True)
    downloader._validate_incoming_category_route = MagicMock(return_value={
        "valid": True, "breadcrumb": True, "active_menu": True
    })
    downloader._wait_for_validated_document_table = MagicMock(return_value=object())

    result = downloader.run_same_page_incoming_registry_smoke(page)

    assert result["new_automation_page_used"] == "NO"
    assert result["authenticated_page_reused"] == "YES"
    page.goto.assert_called_once()
    assert page.goto.call_args.kwargs == {"wait_until": "domcontentloaded", "timeout": 30000}
    assert "DEN_CAN_VAO_SO" in page.goto.call_args.args[0]
    assert downloader._wait_for_validated_document_table.call_count == 1


def test_same_page_smoke_fails_before_goto_when_authenticated_page_closed(tmp_path):
    downloader = make_downloader(tmp_path)
    page = MagicMock()
    page.is_closed.return_value = True

    with pytest.raises(RuntimeError, match="AUTHENTICATED_PAGE_CLOSED_BEFORE_DIRECT_NAVIGATION"):
        downloader.run_same_page_incoming_registry_smoke(page)
    page.goto.assert_not_called()


def test_same_page_smoke_classifies_page_closed_during_goto(tmp_path):
    downloader = make_downloader(tmp_path)
    page = MagicMock()
    page.url = "https://qlvb.laichau.gov.vn/qlvbdh_lcu/main?session=current"
    page.is_closed.side_effect = [False, True]
    page.goto.side_effect = RuntimeError("target closed")

    with pytest.raises(RuntimeError, match="AUTHENTICATED_PAGE_CLOSED_DURING_DIRECT_NAVIGATION"):
        downloader.run_same_page_incoming_registry_smoke(page)


def _blank_monitor(tmp_path):
    downloader = make_downloader(tmp_path)
    context = _BlankMonitorContext()
    primary = _BlankMonitorPage("https://qlvb.laichau.gov.vn/qlvbdh_lcu/main", "QLVB")
    primary.context = context
    context.pages.append(primary)
    downloader._register_blank_page_monitor(primary)
    return downloader, context, primary


def test_blank_page_created_on_category_click_is_ignored_and_left_open(tmp_path):
    downloader, context, primary = _blank_monitor(tmp_path)
    blank = _BlankMonitorPage("about:blank")
    blank.context = context

    context.emit_page(blank)

    assert blank.closed is False
    assert blank.waits == []
    assert downloader.primary_qlvb_page is primary
    assert "page" not in context.handlers


def test_primary_page_temporarily_about_blank_is_protected_by_identity(tmp_path):
    downloader, context, primary = _blank_monitor(tmp_path)
    primary.url = "about:blank"

    assert downloader._cleanup_spurious_blank_pages(primary_qlvb_page=primary, grace_ms=1000) == 0
    assert primary.closed is False
    assert downloader.run_summary["blank_pages"]["protected_page_skip_count"] >= 1


def test_primary_and_secondary_blank_are_both_left_open(tmp_path):
    downloader, context, primary = _blank_monitor(tmp_path)
    primary.url = "about:blank"
    secondary = _BlankMonitorPage("about:blank")
    secondary.context = context
    context.pages.append(secondary)

    assert downloader._cleanup_spurious_blank_pages(primary_qlvb_page=primary, grace_ms=1000) == 0
    assert primary.closed is False
    assert secondary.closed is False


def test_blank_page_appearing_late_is_ignored_without_changing_primary(tmp_path):
    downloader, context, primary = _blank_monitor(tmp_path)
    blank = _BlankMonitorPage("about:blank")
    blank.context = context

    context.emit_page(blank)

    assert blank.closed is False
    assert downloader.run_summary.get("blank_pages", {}).get("primary_qlvb_page_preserved", "PASS") == "PASS"
    assert downloader.primary_qlvb_page is primary


def test_observation_sweep_does_not_close_last_blank_tab(tmp_path):
    downloader, context, primary = _blank_monitor(tmp_path)
    blank = _BlankMonitorPage("about:blank")
    blank.context = context
    context.pages.append(blank)

    assert downloader._cleanup_spurious_blank_pages(grace_ms=1000) == 0
    assert context.pages[-1] is blank
    assert primary.closed is False

    assert downloader._cleanup_spurious_blank_pages(primary_qlvb_page=primary, grace_ms=1000) == 0
    assert blank.closed is False


def test_download_does_not_close_ignored_blank_page(tmp_path):
    downloader, context, primary = _blank_monitor(tmp_path)
    blank = _BlankMonitorPage("about:blank")
    blank.context = context
    context.pages.append(blank)
    record = make_record()
    record.attachments = []

    downloader._download_attachments(primary, record)

    assert blank.closed is False
    assert downloader._download_in_progress is False


def test_closed_primary_fails_before_category_selector_lookup(tmp_path):
    downloader, context, primary = _blank_monitor(tmp_path)
    primary.closed = True
    primary.locator = MagicMock(side_effect=AssertionError("selector must not run"))

    with pytest.raises(RuntimeError, match="PRIMARY_QLVB_PAGE_CLOSED_BEFORE_CATEGORY_NAVIGATION"):
        downloader.open_incoming_category(primary, "incoming_forwarded_processed")
    primary.locator.assert_not_called()


def test_closed_primary_reacquires_one_uniquely_valid_qlvb_page(tmp_path):
    downloader, context, primary = _blank_monitor(tmp_path)
    primary.closed = True
    replacement = _BlankMonitorPage("https://qlvb.laichau.gov.vn/qlvbdh_lcu/main", "QLVB")
    replacement.context = context
    context.pages.append(replacement)
    downloader._is_primary_qlvb_page = MagicMock(side_effect=lambda page: page is replacement)

    selected, reacquired = downloader.ensure_primary_qlvb_page(context, primary)

    assert selected is replacement
    assert reacquired is True
    assert downloader.primary_qlvb_page is replacement
    assert replacement in downloader.protected_pages


def test_closed_primary_without_valid_replacement_is_not_recoverable(tmp_path):
    downloader, context, primary = _blank_monitor(tmp_path)
    primary.closed = True
    context.pages.append(_BlankMonitorPage("about:blank"))

    with pytest.raises(RuntimeError, match="PRIMARY_QLVB_PAGE_CLOSED_AND_NOT_RECOVERABLE"):
        downloader.ensure_primary_qlvb_page(context, primary)


def _configure_active_page_resolver(downloader):
    downloader._is_logged_in = MagicMock(side_effect=lambda page: not getattr(page, "login_page", False))
    downloader._has_qlvb_navigation = MagicMock(return_value=True)
    downloader._has_qlvb_account_context = MagicMock(return_value=True)
    downloader._validate_incoming_category_route = MagicMock(side_effect=lambda page, expected: {
        "host": True,
        "route_marker": True,
        "breadcrumb": getattr(page, "category", None) == expected,
        "active_menu": getattr(page, "category", None) == expected,
        "title": getattr(page, "category", None) == expected,
        "valid": getattr(page, "category", None) == expected,
    })
    downloader._find_document_table = MagicMock(
        side_effect=lambda page, allow_fallback=False: object() if getattr(page, "has_table", False) else None
    )
    downloader._has_empty_document_state = MagicMock(return_value=False)


def test_resilient_category_resolves_before_selector_when_current_page_closed(tmp_path):
    downloader, context, closed_page = _blank_monitor(tmp_path)
    closed_page.closed = True
    live_page = _BlankMonitorPage("https://qlvb.laichau.gov.vn/qlvbdh_lcu/main", "QLVB")
    target_page = _BlankMonitorPage("https://qlvb.laichau.gov.vn/qlvbdh_lcu/main", "Forwarded")
    downloader.resolve_active_qlvb_page = MagicMock(side_effect=[live_page, target_page])
    downloader.open_incoming_category = MagicMock(return_value=target_page)

    selected = downloader.open_category_resilient(
        context, closed_page, "incoming_forwarded_processed"
    )

    assert selected is target_page
    assert downloader.resolve_active_qlvb_page.call_args_list[0].kwargs == {
        "expected_category": None,
        "current_page": closed_page,
    }
    downloader.open_incoming_category.assert_called_once_with(
        live_page, "incoming_forwarded_processed", resolve_after_click=False
    )
    assert downloader.resolve_active_qlvb_page.call_args_list[1].kwargs == {
        "expected_category": "incoming_forwarded_processed",
        "current_page": None,
        "timeout_seconds": 15.0,
    }


def test_resilient_category_reacquires_new_page_after_old_page_closes(tmp_path):
    downloader, context, old_page = _blank_monitor(tmp_path)
    target_page = _BlankMonitorPage("https://qlvb.laichau.gov.vn/qlvbdh_lcu/main", "Forwarded")

    def click_and_close(page, category, *, resolve_after_click):
        assert page is old_page
        assert category == "incoming_forwarded_processed"
        assert resolve_after_click is False
        old_page.closed = True
        return old_page

    downloader.resolve_active_qlvb_page = MagicMock(side_effect=[old_page, target_page])
    downloader.open_incoming_category = MagicMock(side_effect=click_and_close)

    assert downloader.open_category_resilient(
        context, old_page, "incoming_forwarded_processed"
    ) is target_page
    assert old_page.closed is True


def test_resilient_category_registers_page_signal_before_click(tmp_path):
    downloader, context, source_page = _blank_monitor(tmp_path)
    target_page = _BlankMonitorPage("https://qlvb.laichau.gov.vn/qlvbdh_lcu/main", "Forwarded")
    target_page.context = context
    downloader.resolve_active_qlvb_page = MagicMock(side_effect=[source_page, target_page])

    def click_after_registration(page, category, *, resolve_after_click):
        assert "page" in context.handlers
        context.emit_page(target_page)
        return page

    downloader.open_incoming_category = MagicMock(side_effect=click_after_registration)

    assert downloader.open_category_resilient(
        context, source_page, "incoming_forwarded_processed"
    ) is target_page
    assert downloader.run_summary["active_page"]["page_event_signal_count"] == 1


@pytest.mark.parametrize("new_context", [False, True])
def test_browser_wide_resolver_waits_through_zero_pages_and_ignores_blank(
    tmp_path, monkeypatch, new_context
):
    downloader, old_context, old_page = _blank_monitor(tmp_path)
    old_page.closed = True
    clock = {"now": 0.0}
    blank = _BlankMonitorPage("about:blank")
    target = _BlankMonitorPage("https://qlvb.laichau.gov.vn/qlvbdh_lcu/main", "Forwarded")
    target.category = "incoming_forwarded_processed"
    target.has_table = True

    class DynamicContext(_BlankMonitorContext):
        def __init__(self, role):
            self.role = role
            self.handlers = {}

        @property
        def pages(self):
            if self.role == "old":
                result = [blank] if clock["now"] >= 0.8 else []
                if not new_context and clock["now"] >= 1.2:
                    result.append(target)
                return result
            return [target] if clock["now"] >= 1.2 else []

    dynamic_old = DynamicContext("old")
    dynamic_new = DynamicContext("new")
    blank.context = dynamic_old
    target.context = dynamic_new if new_context else dynamic_old

    class DynamicBrowser:
        @property
        def contexts(self):
            if new_context and clock["now"] >= 1.0:
                return [dynamic_old, dynamic_new]
            return [dynamic_old]

    downloader.browser = DynamicBrowser()
    _configure_active_page_resolver(downloader)
    monkeypatch.setattr("tools.qlvb_downloader.downloader.time.monotonic", lambda: clock["now"])
    monkeypatch.setattr(
        "tools.qlvb_downloader.downloader.time.sleep",
        lambda seconds: clock.__setitem__("now", clock["now"] + seconds),
    )

    selected = downloader.resolve_active_qlvb_page(
        dynamic_old, "incoming_forwarded_processed", timeout_seconds=15.0
    )

    assert selected is target
    assert blank.closed is False
    assert target.brought_to_front == 1
    assert downloader.run_summary["active_page"]["zero_page_observation_count"] >= 1
    assert downloader.run_summary["active_page"]["context_count_max"] == (2 if new_context else 1)


def test_browser_wide_resolver_waits_for_late_category_dom(tmp_path, monkeypatch):
    downloader, context, target = _blank_monitor(tmp_path)
    clock = {"now": 0.0}
    target.category = "incoming_forwarded_processed"
    target.has_table = True
    _configure_active_page_resolver(downloader)
    downloader._validate_incoming_category_route = MagicMock(side_effect=lambda page, expected: {
        "host": True,
        "route_marker": clock["now"] >= 0.6,
        "breadcrumb": clock["now"] >= 1.0,
        "active_menu": clock["now"] >= 1.0,
        "title": clock["now"] >= 0.6,
        "valid": clock["now"] >= 1.0,
    })
    monkeypatch.setattr("tools.qlvb_downloader.downloader.time.monotonic", lambda: clock["now"])
    monkeypatch.setattr(
        "tools.qlvb_downloader.downloader.time.sleep",
        lambda seconds: clock.__setitem__("now", clock["now"] + seconds),
    )

    assert downloader.resolve_active_qlvb_page(
        context, "incoming_forwarded_processed", timeout_seconds=15.0
    ) is target
    assert clock["now"] >= 1.0


def test_browser_wide_resolver_times_out_only_after_deadline(tmp_path, monkeypatch):
    downloader, context, _page = _blank_monitor(tmp_path)
    context.pages.clear()
    clock = {"now": 0.0}
    monkeypatch.setattr("tools.qlvb_downloader.downloader.time.monotonic", lambda: clock["now"])
    monkeypatch.setattr(
        "tools.qlvb_downloader.downloader.time.sleep",
        lambda seconds: clock.__setitem__("now", clock["now"] + seconds),
    )

    with pytest.raises(RuntimeError, match="TARGET_QLVB_PAGE_NOT_FOUND_AFTER_CATEGORY_CLICK_TIMEOUT"):
        downloader.resolve_active_qlvb_page(
            context, "incoming_forwarded_processed", timeout_seconds=15.0
        )
    assert clock["now"] >= 15.0
    assert downloader.run_summary["active_page"]["zero_page_observation_count"] > 0


def test_resilient_category_reports_before_click_when_no_live_qlvb_page(tmp_path):
    downloader, context, closed_page = _blank_monitor(tmp_path)
    closed_page.closed = True
    downloader.resolve_active_qlvb_page = MagicMock(
        side_effect=RuntimeError("SOURCE_QLVB_PAGE_NOT_FOUND_BEFORE_CATEGORY_CLICK_TIMEOUT")
    )
    downloader.open_incoming_category = MagicMock()

    with pytest.raises(RuntimeError, match="SOURCE_QLVB_PAGE_NOT_FOUND_BEFORE_CATEGORY_CLICK_TIMEOUT"):
        downloader.open_category_resilient(
            context, closed_page, "incoming_forwarded_processed"
        )
    downloader.open_incoming_category.assert_not_called()


@pytest.mark.parametrize("category", ["incoming_forwarded_processed", "incoming_processed"])
def test_active_page_resolver_selects_expected_category_and_brings_it_front(tmp_path, category):
    downloader, context, old = _blank_monitor(tmp_path)
    old.closed = True
    blank = _BlankMonitorPage("about:blank")
    blank.context = context
    target = _BlankMonitorPage("https://qlvb.laichau.gov.vn/qlvbdh_lcu/main", "QLVB")
    target.context = context
    target.category = category
    target.has_table = True
    context.pages.extend([target, blank])  # about:blank is deliberately the last tab.
    _configure_active_page_resolver(downloader)

    selected = downloader.resolve_active_qlvb_page(context, category)

    assert selected is target
    assert target.brought_to_front == 1
    assert blank.closed is False
    assert downloader.browser_context is context


def test_active_page_resolver_chooses_category_match_among_multiple_qlvb_pages(tmp_path):
    downloader, context, old = _blank_monitor(tmp_path)
    old.closed = True
    registry = _BlankMonitorPage("https://qlvb.laichau.gov.vn/qlvbdh_lcu/main", "Registry")
    forwarded = _BlankMonitorPage("https://qlvb.laichau.gov.vn/qlvbdh_lcu/main", "Forwarded")
    for page, category in ((registry, "incoming_registry"), (forwarded, "incoming_forwarded_processed")):
        page.context = context
        page.category = category
        page.has_table = True
    context.pages.extend([registry, forwarded])
    _configure_active_page_resolver(downloader)

    assert downloader.resolve_active_qlvb_page(context, "incoming_forwarded_processed") is forwarded


def test_active_page_resolver_excludes_login_blob_and_file_pages(tmp_path):
    downloader, context, old = _blank_monitor(tmp_path)
    old.closed = True
    login = _BlankMonitorPage("https://qlvb.laichau.gov.vn/qlvbdh_lcu/main", "Login")
    login.context = context
    login.login_page = True
    login.category = "incoming_forwarded_processed"
    login.has_table = True
    blob = _BlankMonitorPage("blob:https://qlvb.laichau.gov.vn/fixture")
    file_preview = _BlankMonitorPage("file:///C:/Temp/preview.pdf")
    target = _BlankMonitorPage("https://qlvb.laichau.gov.vn/qlvbdh_lcu/main", "QLVB")
    target.context = context
    target.category = "incoming_forwarded_processed"
    target.has_table = True
    context.pages.extend([login, blob, file_preview, target])
    _configure_active_page_resolver(downloader)

    assert downloader.resolve_active_qlvb_page(context, "incoming_forwarded_processed") is target


@pytest.mark.parametrize(("url", "title"), [
    ("https://qlvb.laichau.gov.vn/qlvbdh_lcu/main", "QLVB popup"),
    ("blob:https://qlvb.laichau.gov.vn/fixture", ""),
    ("file:///C:/Temp/preview.pdf", "Preview"),
    ("about:blank", "PDF preview"),
])
def test_valid_qlvb_blob_and_file_preview_popups_are_preserved(tmp_path, url, title):
    downloader, context, _primary = _blank_monitor(tmp_path)
    popup = _BlankMonitorPage(url, title)
    popup.context = context

    context.emit_page(popup)

    assert popup.closed is False


def test_primary_qlvb_page_is_selected_instead_of_a_trailing_blank_tab(tmp_path):
    downloader = make_downloader(tmp_path)
    primary = _Tab("https://qlvb.laichau.gov.vn/qlvbdh_lcu/main", "qlvb")
    blank = _Tab("about:blank", "blank")
    downloader._is_primary_qlvb_page = MagicMock(side_effect=lambda page: page is primary)

    selected, diagnostics = downloader.select_primary_qlvb_page(_TabContext([primary, blank]))

    assert selected is primary
    assert blank.closed is False
    assert diagnostics["blank_page_detected"] == "YES"
    assert diagnostics["blank_page_closed"] == "NO"
    assert diagnostics["primary_qlvb_page_selected"] == "PASS"


def test_primary_qlvb_page_requires_host_session_menu_and_account_context(tmp_path):
    downloader = make_downloader(tmp_path)
    page = MagicMock()
    page.url = "https://qlvb.laichau.gov.vn/qlvbdh_lcu/main"
    page.is_closed.return_value = False
    downloader._is_logged_in = MagicMock(return_value=True)
    downloader._has_qlvb_navigation = MagicMock(return_value=True)
    downloader._has_qlvb_account_context = MagicMock(return_value=True)

    assert downloader._is_primary_qlvb_page(page) is True

    downloader._has_qlvb_account_context.return_value = False
    assert downloader._is_primary_qlvb_page(page) is False


def test_hidden_login_form_is_never_treated_as_authenticated(browser_page, tmp_path):
    browser_page.set_content(
        "<title>Hệ thống quản lý văn bản và điều hành</title>"
        "<div>Quản lý văn bản đến</div>"
        "<input type='password' style='display:none'>"
    )

    assert make_downloader(tmp_path)._is_logged_in(browser_page) is False


def _registry_rows(document_ids: list[str]) -> str:
    return "".join(
        f"<tr id='vb_{document_id}'><td>{index}</td><td>{document_id}/TEST</td><td>22/07/2026</td>"
        f"<td>Fixture agency</td><td>Fixture {document_id}</td><td></td><td></td></tr>"
        for index, document_id in enumerate(document_ids, start=1)
    )


def test_registry_selects_third_neoremoting_attachment_without_files_icon(browser_page, tmp_path, monkeypatch):
    downloader = make_downloader(tmp_path)
    document_ids = [str(100000 + index) for index in range(1, 11)]
    label = "V\u0103n b\u1ea3n v\u00e0o s\u1ed5"
    browser_page.set_content(_incoming_category_shell(label, _document_table(_registry_rows(document_ids))))
    calls: list[str] = []

    class Adapter:
        def __init__(self, *_args, **_kwargs):
            pass

        def discover(self, _page, *, document_id, **_kwargs):
            calls.append(document_id)
            if document_id in document_ids[:2]:
                raise NeoRemotingDiscoveryError("NO_ATTACHMENTS")
            if document_id == document_ids[2]:
                return [AttachmentInfo(text="fixture.pdf", href="https://qlvb.laichau.gov.vn/file.pdf", source_method="NEOREMOTING")]
            raise AssertionError("must stop after first row with attachments")

    monkeypatch.setattr("tools.qlvb_downloader.downloader.NeoRemotingAttachmentDiscoveryAdapter", Adapter)
    downloader._goto = MagicMock()
    downloader._is_logged_in = MagicMock(return_value=True)
    downloader._process_record = MagicMock(side_effect=lambda _detail, record, list_page: setattr(record, "status", "READY"))

    result = downloader._process_direction(
        browser_page,
        "incoming",
        1,
        fixed_url="https://qlvb.laichau.gov.vn/registry",
        category="incoming_registry",
    )

    assert calls == document_ids[:3]
    assert result["rows_scanned"] == 3
    assert result["document_ids_validated"] == 3
    assert result["rows_with_attachments"] == 1
    assert result["selected_row_index"] == 3
    assert result["selected_document_id"] == document_ids[2]
    assert result["attachment_discovery_method"] == "NEOREMOTING"
    assert result["attachment_count"] == 1


def test_registry_neoremoting_access_denied_stops_without_trying_another_row(browser_page, tmp_path, monkeypatch):
    downloader = make_downloader(tmp_path)
    document_ids = ["100001", "100002"]
    label = "V\u0103n b\u1ea3n v\u00e0o s\u1ed5"
    browser_page.set_content(_incoming_category_shell(label, _document_table(_registry_rows(document_ids))))
    calls: list[str] = []

    class Adapter:
        def __init__(self, *_args, **_kwargs):
            pass

        def discover(self, _page, *, document_id, **_kwargs):
            calls.append(document_id)
            raise NeoRemotingDiscoveryError("NEOREMOTING_ACCESS_DENIED")

    monkeypatch.setattr("tools.qlvb_downloader.downloader.NeoRemotingAttachmentDiscoveryAdapter", Adapter)
    downloader._goto = MagicMock()
    downloader._is_logged_in = MagicMock(return_value=True)

    result = downloader._process_direction(
        browser_page,
        "incoming",
        1,
        fixed_url="https://qlvb.laichau.gov.vn/registry",
        category="incoming_registry",
    )

    assert calls == [document_ids[0]]
    assert result["status"] == "FAILED"
    assert result["error"] == "NEOREMOTING_ACCESS_DENIED"


def test_neoremoting_unavailable_uses_row_scoped_files_fallback(tmp_path, monkeypatch):
    downloader = make_downloader(tmp_path)
    record = make_record()
    record.source_category = "incoming_registry"
    fallback = [AttachmentInfo(text="fallback.pdf", href="https://qlvb.laichau.gov.vn/file.pdf")]

    class Adapter:
        def __init__(self, *_args, **_kwargs):
            pass

        def discover(self, *_args, **_kwargs):
            raise NeoRemotingDiscoveryError("NEOREMOTING_NOT_AVAILABLE")

    monkeypatch.setattr("tools.qlvb_downloader.downloader.NeoRemotingAttachmentDiscoveryAdapter", Adapter)
    downloader._row_scoped_attachment_fallback = MagicMock(return_value=fallback)

    assert downloader._probe_incoming_row_attachments(MagicMock(url="https://qlvb.laichau.gov.vn/qlvbdh_lcu/main"), record) is True
    assert record.attachments == fallback
    assert record.metadata["attachment_discovery_method"] == "ROW_SCOPED_FILES_FALLBACK"


def test_row_scoped_fallback_never_treats_all_file_download_javascript_as_a_url(browser_page, tmp_path):
    downloader = make_downloader(tmp_path)
    label = "V\u0103n b\u1ea3n v\u00e0o s\u1ed5"
    browser_page.set_content(_incoming_category_shell(label, _document_table(
        "<tr id='vb_123456'><td>1</td><td>123456/TEST</td><td>22/07/2026</td><td>Agency</td>"
        "<td>Fixture</td><td><a href=\"javascript:allFileDownload('123456')\">Files</a></td><td></td></tr>"
    )))
    headers = downloader._extract_headers(browser_page, allow_fallback=False)
    record = downloader._extract_records_from_current_page(browser_page, "incoming", browser_page.url, headers)[0]

    assert downloader._row_scoped_attachment_fallback(browser_page, record) == []


def test_registry_probe_stops_at_ten_rows(tmp_path, monkeypatch):
    downloader = make_downloader(tmp_path)
    calls: list[str] = []
    records = []
    for index in range(11):
        record = make_record()
        record.row_index = index + 1
        record.metadata["source_document_id"] = str(200000 + index)
        records.append(record)

    def probe(_page, record):
        calls.append(record.metadata["source_document_id"])
        return False

    monkeypatch.setattr(downloader, "_probe_incoming_row_attachments", probe)
    result = {}

    assert downloader._select_first_incoming_row_with_attachments(MagicMock(), records, result) is None
    assert result["rows_scanned"] == 10
    assert result["document_ids_validated"] == 10
    assert calls == [str(200000 + index) for index in range(10)]


def test_controlled_selected_document_keeps_only_first_safe_attachment(tmp_path, monkeypatch):
    downloader = make_downloader(tmp_path)
    record = make_record()
    record.source_category = "incoming_forwarded_processed"

    class Adapter:
        def __init__(self, *_args, **_kwargs): pass
        def discover(self, *_args, **_kwargs):
            return [
                AttachmentInfo(text="first.pdf", href="https://qlvb.laichau.gov.vn/first", source_method="NEOREMOTING"),
                AttachmentInfo(text="second.pdf", href="https://qlvb.laichau.gov.vn/second", source_method="NEOREMOTING"),
            ]

    monkeypatch.setattr("tools.qlvb_downloader.downloader.NeoRemotingAttachmentDiscoveryAdapter", Adapter)
    result = {"invalid_response_count": 0}

    selected = downloader._select_first_incoming_row_with_attachments(MagicMock(), [record], result)

    assert selected is record
    assert len(record.attachments) == 1
    assert record.attachments[0].text == "first.pdf"


def test_r22_first_zero_gate_reports_table_header_validation(tmp_path):
    downloader = make_downloader(tmp_path)
    diag = {
        "CATEGORY_HOST_VALID": "YES",
        "CATEGORY_PATH_VALID": "YES",
        "CATEGORY_ROUTE_MARKER_PRESENT": "YES",
        "CATEGORY_BREADCRUMB_VALID": "YES",
        "CATEGORY_ACTIVE_MENU_VALID": "YES",
        "TABLE_CANDIDATE_COUNT": 2,
        "VALIDATED_TABLE_SELECTOR": "",
        "EMPTY_STATE_FOUND": "NO",
    }

    assert downloader._first_zero_gate(diag) == "TABLE_HEADER_VALIDATION"


def test_r22_first_zero_gate_reports_confirmed_empty_only_with_empty_state(tmp_path):
    downloader = make_downloader(tmp_path)
    diag = {
        "CATEGORY_HOST_VALID": "YES",
        "CATEGORY_PATH_VALID": "YES",
        "CATEGORY_ROUTE_MARKER_PRESENT": "YES",
        "CATEGORY_BREADCRUMB_VALID": "YES",
        "CATEGORY_ACTIVE_MENU_VALID": "YES",
        "TABLE_CANDIDATE_COUNT": 0,
        "VALIDATED_TABLE_SELECTOR": "",
        "EMPTY_STATE_FOUND": "YES",
    }

    assert downloader._first_zero_gate(diag) == "CONFIRMED_EMPTY"


def test_r22_first_zero_gate_reports_table_missing_without_empty_state(tmp_path):
    downloader = make_downloader(tmp_path)
    diag = {
        "CATEGORY_HOST_VALID": "YES",
        "CATEGORY_PATH_VALID": "YES",
        "CATEGORY_ROUTE_MARKER_PRESENT": "YES",
        "CATEGORY_BREADCRUMB_VALID": "YES",
        "CATEGORY_ACTIVE_MENU_VALID": "YES",
        "TABLE_CANDIDATE_COUNT": 0,
        "VALIDATED_TABLE_SELECTOR": "",
        "EMPTY_STATE_FOUND": "NO",
    }

    assert downloader._first_zero_gate(diag) == "TABLE_NOT_FOUND_WITHOUT_EMPTY_STATE"


def test_r22_first_zero_gate_reports_row_filtering_when_all_rows_skip(tmp_path):
    downloader = make_downloader(tmp_path)
    diag = {
        "CATEGORY_HOST_VALID": "YES",
        "CATEGORY_PATH_VALID": "YES",
        "CATEGORY_ROUTE_MARKER_PRESENT": "YES",
        "CATEGORY_BREADCRUMB_VALID": "YES",
        "CATEGORY_ACTIVE_MENU_VALID": "YES",
        "TABLE_CANDIDATE_COUNT": 1,
        "VALIDATED_TABLE_SELECTOR": "MAIN_CONTENT_DOCUMENT_TABLE",
        "EMPTY_STATE_FOUND": "NO",
        "DATA_ROW_COUNT_BEFORE_FILTER": 10,
        "DATA_ROW_COUNT_AFTER_FILTER": 0,
    }

    assert downloader._first_zero_gate(diag) == "ROW_FILTERING"


def test_r22_first_zero_gate_reports_document_id_extraction(tmp_path):
    downloader = make_downloader(tmp_path)
    diag = {
        "CATEGORY_HOST_VALID": "YES",
        "CATEGORY_PATH_VALID": "YES",
        "CATEGORY_ROUTE_MARKER_PRESENT": "YES",
        "CATEGORY_BREADCRUMB_VALID": "YES",
        "CATEGORY_ACTIVE_MENU_VALID": "YES",
        "TABLE_CANDIDATE_COUNT": 1,
        "VALIDATED_TABLE_SELECTOR": "MAIN_CONTENT_DOCUMENT_TABLE",
        "EMPTY_STATE_FOUND": "NO",
        "DATA_ROW_COUNT_BEFORE_FILTER": 3,
        "DATA_ROW_COUNT_AFTER_FILTER": 3,
        "DOCUMENT_ID_VALID_COUNT": 0,
    }

    assert downloader._first_zero_gate(diag) == "DOCUMENT_ID_EXTRACTION"


def test_r22_diagnostic_mode_writes_sanitized_bundle_and_skips_attachment_layer(tmp_path):
    downloader = make_downloader(tmp_path)
    downloader._probe_incoming_row_attachments = MagicMock(side_effect=AssertionError("NeoRemoting must not run"))
    downloader._download_attachments = MagicMock(side_effect=AssertionError("download must not run"))
    page = MagicMock()
    categories = [
        {
            "CATEGORY_KEY": "INCOMING_REGISTRY",
            "CATEGORY_RESULT": "ZERO_AT_DOCUMENT_ID_EXTRACTION",
            "CATEGORY_FIRST_ZERO_GATE": "DOCUMENT_ID_EXTRACTION",
            "TABLE_SELECTOR_CANDIDATES": [{"class": "grid", "headers_normalized": ["stt"]}],
            "SAMPLE_ROW_SHAPE": {"tag": "tr", "cell_count": 5, "attribute_names": ["onclick"]},
        },
        {"CATEGORY_KEY": "FORWARDED_PROCESSED", "CATEGORY_RESULT": "CONFIRMED_EMPTY", "CATEGORY_FIRST_ZERO_GATE": "CONFIRMED_EMPTY"},
        {"CATEGORY_KEY": "PROCESSED", "CATEGORY_RESULT": "CONFIRMED_EMPTY", "CATEGORY_FIRST_ZERO_GATE": "CONFIRMED_EMPTY"},
    ]
    downloader._diagnose_incoming_category = MagicMock(side_effect=[(page, item) for item in categories])

    summary = downloader.run_zero_document_diagnostic(page, tmp_path / "diag")

    assert summary["PROCESS_DIRECTION_CALL_COUNT"] == 0
    assert summary["FIRST_ZERO_GATE"] == "DOCUMENT_ID_EXTRACTION"
    assert summary["ALL_CATEGORIES_CONFIRMED_EMPTY"] == "NO"
    assert (tmp_path / "diag" / "diagnostic-summary.txt").exists()
    assert (tmp_path / "diag" / "category-structure.json").exists()
    assert (tmp_path / "diag" / "sanitized-dom-snippets.txt").exists()
    downloader._probe_incoming_row_attachments.assert_not_called()
    downloader._download_attachments.assert_not_called()


def test_r22_all_categories_confirmed_empty_is_classified_exactly(tmp_path):
    downloader = make_downloader(tmp_path)
    page = MagicMock()
    categories = [
        {"CATEGORY_KEY": "INCOMING_REGISTRY", "CATEGORY_RESULT": "CONFIRMED_EMPTY", "CATEGORY_FIRST_ZERO_GATE": "CONFIRMED_EMPTY"},
        {"CATEGORY_KEY": "FORWARDED_PROCESSED", "CATEGORY_RESULT": "CONFIRMED_EMPTY", "CATEGORY_FIRST_ZERO_GATE": "CONFIRMED_EMPTY"},
        {"CATEGORY_KEY": "PROCESSED", "CATEGORY_RESULT": "CONFIRMED_EMPTY", "CATEGORY_FIRST_ZERO_GATE": "CONFIRMED_EMPTY"},
    ]
    downloader._diagnose_incoming_category = MagicMock(side_effect=[(page, item) for item in categories])

    summary = downloader.run_zero_document_diagnostic(page, tmp_path / "diag-empty")

    assert summary["ALL_CATEGORIES_CONFIRMED_EMPTY"] == "YES"
    assert summary["FIRST_ZERO_GATE"] == "ALL_CATEGORIES_CONFIRMED_EMPTY"


def test_r23_global_text_selector_removed_from_exact_menu_navigation():
    source = inspect.getsource(QLVBDownloader.open_incoming_category)
    script = QLVBDownloader._strict_menu_probe_script()

    assert "get_by_text" not in source
    assert "text=" not in source
    assert "has-text" not in source
    assert "contains(" not in source
    assert "#full_menu" in script
    assert "quan ly van ban den" in script
    assert "closest('main, #content, #main-content, .main-content, .modal" in script


def test_r23_exact_category_label_match_supports_count_suffix():
    script = QLVBDownloader._strict_menu_probe_script()

    assert r"\(\s*\d+\s*\)" in script
    assert "text !== expected" in script
    assert "startsWith" not in script


def _r23_page():
    page = MagicMock()
    page.url = "https://qlvb.laichau.gov.vn/qlvbdh_lcu/main?6yXl=DEN_CAN_VAO_SO"
    page.is_closed.return_value = False
    page.frames = []
    page.wait_for_load_state = MagicMock()
    return page


def test_r23_zero_candidate_fails_without_clicking(tmp_path):
    downloader = make_downloader(tmp_path)
    page = _r23_page()
    downloader._probe_exact_incoming_menu = MagicMock(return_value={
        "group_found": True,
        "candidate_count": 0,
        "candidate_text": "",
        "candidate_in_expected_group": False,
        "candidate_is_visible": False,
        "candidate_is_navigation_item": False,
    })

    with pytest.raises(RuntimeError, match="CATEGORY_MENU_ACTIONABLE_TARGET_NOT_FOUND"):
        downloader.open_incoming_category(page, "incoming_registry", resolve_after_click=False)

    downloader._probe_exact_incoming_menu.assert_called_once()


def test_r23_ambiguous_target_fails_without_clicking(tmp_path):
    downloader = make_downloader(tmp_path)
    page = _r23_page()
    downloader._probe_exact_incoming_menu = MagicMock(return_value={
        "group_found": True,
        "candidate_count": 2,
        "candidate_text": "van ban vao so|van ban vao so",
        "candidate_in_expected_group": False,
        "candidate_is_visible": False,
        "candidate_is_navigation_item": False,
        "raw_text_match_count": 2,
        "actionable_ancestor_count": 2,
        "deduped_actionable_count": 2,
        "visible_actionable_count": 2,
        "expected_group_actionable_count": 2,
    })

    with pytest.raises(RuntimeError, match="CATEGORY_MENU_ACTIONABLE_TARGET_AMBIGUOUS"):
        downloader.open_incoming_category(page, "incoming_registry", resolve_after_click=False)

    downloader._probe_exact_incoming_menu.assert_called_once()


def test_r23_wrong_information_action_click_is_rejected(tmp_path):
    downloader = make_downloader(tmp_path)
    page = _r23_page()
    downloader._probe_exact_incoming_menu = MagicMock(side_effect=[
        {
            "group_found": True,
            "candidate_count": 1,
                "candidate_text": "van ban vao so",
                "candidate_in_expected_group": True,
                "candidate_is_visible": True,
                "candidate_is_navigation_item": True,
                "raw_text_match_count": 1,
                "actionable_ancestor_count": 1,
                "deduped_actionable_count": 1,
                "visible_actionable_count": 1,
                "expected_group_actionable_count": 1,
            },
            {
                "group_found": True,
                "candidate_count": 1,
                "clicked": True,
                "candidate_text": "van ban vao so",
                "candidate_in_expected_group": True,
                "candidate_is_visible": True,
                "candidate_is_navigation_item": True,
                "raw_text_match_count": 1,
                "actionable_ancestor_count": 1,
                "deduped_actionable_count": 1,
                "visible_actionable_count": 1,
                "expected_group_actionable_count": 1,
            },
    ])
    downloader._diagnostic_route_texts = MagicMock(return_value={"active_menu": "thong tin xu ly van ban"})

    with pytest.raises(RuntimeError, match="WRONG_MENU_TARGET_CLICKED"):
        downloader.open_incoming_category(page, "incoming_registry", resolve_after_click=False)


def test_r23_modal_and_table_decoys_are_excluded_by_menu_probe_script():
    script = QLVBDownloader._strict_menu_probe_script()

    assert ".modal" in script
    assert "[role=\"dialog\"]" in script
    assert "table, tr, td, th" in script
    assert "inExcludedSurface(raw)" in script


def test_r24_actionable_ancestor_resolution_and_dedup_are_implemented():
    script = QLVBDownloader._strict_menu_probe_script()

    assert "actionableFrom" in script
    assert "depth <= 6" in script
    assert "new WeakSet()" in script
    assert "DEDUPED" not in script
    assert "raw_text_match_count" in script
    assert "actionable_ancestor_count" in script
    assert "deduped_actionable_count" in script


def test_r24_computed_visibility_and_hidden_clone_filters_are_implemented():
    script = QLVBDownloader._strict_menu_probe_script()

    assert "window.getComputedStyle" in script
    assert "style.display === 'none'" in script
    assert "style.visibility === 'hidden'" in script
    assert "Number(style.opacity) === 0" in script
    assert "getBoundingClientRect" in script
    assert "aria-hidden" in script
    assert "tag === 'template'" in script


def test_r24_collapsed_group_expand_and_rescan_are_implemented():
    script = QLVBDownloader._strict_menu_probe_script()

    assert "menu_group_expand_required" in script
    assert "menu_group_expand_clicked" in script
    assert "menu_rescan_performed" in script
    assert "setTimeout(resolve, 800)" in script
    assert "result = scan()" in script


def test_r24_actionable_click_requires_all_three_singleton_counts(tmp_path):
    downloader = make_downloader(tmp_path)
    page = _r23_page()
    downloader._probe_exact_incoming_menu = MagicMock(return_value={
        "group_found": True,
        "candidate_count": 1,
        "candidate_text": "van ban vao so",
        "candidate_in_expected_group": True,
        "candidate_is_visible": True,
        "candidate_is_navigation_item": True,
        "raw_text_match_count": 3,
        "actionable_ancestor_count": 3,
        "deduped_actionable_count": 2,
        "visible_actionable_count": 1,
        "expected_group_actionable_count": 1,
    })

    with pytest.raises(RuntimeError, match="CATEGORY_MENU_ACTIONABLE_TARGET_AMBIGUOUS"):
        downloader.open_incoming_category(page, "incoming_registry", resolve_after_click=False)


def test_r24_three_text_clones_can_dedup_to_one_actionable_node(tmp_path):
    downloader = make_downloader(tmp_path)
    page = _r23_page()
    downloader._probe_exact_incoming_menu = MagicMock(side_effect=[
        {
            "group_found": True,
            "candidate_count": 1,
            "candidate_text": "van ban vao so",
            "candidate_in_expected_group": True,
            "candidate_is_visible": True,
            "candidate_is_navigation_item": True,
            "raw_text_match_count": 3,
            "actionable_ancestor_count": 3,
            "deduped_actionable_count": 1,
            "visible_actionable_count": 1,
            "expected_group_actionable_count": 1,
        },
        {
            "group_found": True,
            "candidate_count": 1,
            "clicked": True,
            "candidate_text": "van ban vao so",
            "candidate_in_expected_group": True,
            "candidate_is_visible": True,
            "candidate_is_navigation_item": True,
            "raw_text_match_count": 3,
            "actionable_ancestor_count": 3,
            "deduped_actionable_count": 1,
            "visible_actionable_count": 1,
            "expected_group_actionable_count": 1,
        },
    ])
    downloader._diagnostic_route_texts = MagicMock(return_value={"active_menu": "van ban vao so"})

    assert downloader.open_incoming_category(page, "incoming_registry", resolve_after_click=False) is page
