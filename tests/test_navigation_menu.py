from types import SimpleNamespace

import pytest
from playwright.sync_api import sync_playwright

from tools.qlvb_downloader.config import DEFAULT_SELECTORS
from tools.qlvb_downloader.downloader import QLVBDownloader


TABLE = "<table><thead><tr><th>Số ký hiệu</th><th>Trích yếu</th></tr></thead><tbody><tr><td>1/QĐ</td><td>Test</td></tr></tbody></table>"


def _downloader():
    obj = QLVBDownloader.__new__(QLVBDownloader)
    obj.config = SimpleNamespace(
        qlvb_base_url="",
        browser=SimpleNamespace(timeout_ms=5000),
        selectors=DEFAULT_SELECTORS,
        download=SimpleNamespace(save_source_html_on_error=False, save_screenshot_on_error=False),
    )
    obj.logger = SimpleNamespace(
        info=lambda *a, **k: None, warning=lambda *a, **k: None,
        error=lambda *a, **k: None, debug=lambda *a, **k: None,
    )
    obj.storage = SimpleNamespace(write_error_artifact=lambda *a, **k: {})
    return obj


@pytest.fixture
def browser_page():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        yield page
        browser.close()


def test_javascript_href_is_never_sent_to_goto():
    class NeverGoto:
        def goto(self, *args, **kwargs):
            raise AssertionError("page.goto must not be called")
    with pytest.raises(RuntimeError, match="UNSAFE_NAVIGATION_TARGET"):
        _downloader()._goto(NeverGoto(), 'javascript:link("m3806")', "menu")


def test_incoming_clicks_van_ban_den(browser_page):
    browser_page.set_content(f"<a onclick=\"document.getElementById('x').innerHTML='{TABLE}'\">Văn bản đến</a><div id=x></div>")
    assert _downloader().open_document_direction(browser_page, "incoming") is browser_page


def test_outgoing_clicks_van_ban_di(browser_page):
    browser_page.set_content(f"<a onclick=\"document.getElementById('x').innerHTML='{TABLE}'\">Văn bản đi</a><div id=x></div>")
    assert _downloader().open_document_direction(browser_page, "outgoing") is browser_page


def test_menu_inside_iframe_is_clicked(browser_page):
    src = f"<a onclick=&quot;document.getElementById('x').innerHTML='{TABLE}'&quot;>Văn bản đến</a><div id=x></div>"
    browser_page.set_content(f"<main>Văn bản đến</main><iframe srcdoc=\"{src}\"></iframe>")
    browser_page.wait_for_timeout(200)
    assert _downloader().open_document_direction(browser_page, "incoming") is browser_page


def test_dynamic_session_menu_action_is_clicked(browser_page):
    browser_page.set_content(f"<a href='javascript:void(0)' onclick=\"window.sessionMenu='m9999';document.getElementById('x').innerHTML='{TABLE}'\">Văn bản đến</a><div id=x></div>")
    _downloader().open_document_direction(browser_page, "incoming")
    assert browser_page.evaluate("window.sessionMenu") == "m9999"


def test_menu_click_same_tab(browser_page):
    browser_page.set_content(f"<button onclick=\"document.body.innerHTML='{TABLE}'\">Văn bản đến</button>")
    assert _downloader().open_document_direction(browser_page, "incoming") is browser_page


def test_menu_click_ajax_content(browser_page):
    browser_page.set_content(f"<button onclick=\"setTimeout(()=>document.getElementById('x').innerHTML='{TABLE}',50)\">Văn bản đến</button><div id=x></div>")
    assert _downloader().open_document_direction(browser_page, "incoming") is browser_page


def test_menu_click_opens_new_tab(browser_page):
    script = f"var w=window.open('about:blank');w.document.write(`{TABLE}`);w.document.close()"
    browser_page.set_content(f"<button onclick=\"{script}\">Văn bản đến</button>")
    result = _downloader().open_document_direction(browser_page, "incoming")
    assert result is not browser_page
    result.close()


def test_find_document_table_after_navigation(browser_page):
    browser_page.set_content(TABLE)
    assert _downloader()._find_document_table(browser_page) is not None


def test_outgoing_fallback_matches_javascript_attribute(browser_page):
    browser_page.set_content(f"<main>Văn bản đi</main><a href='javascript:link(\"vanban_di_da_banhanh\")' onclick=\"document.getElementById('x').innerHTML='{TABLE}'\">Mở danh sách</a><div id=x></div>")
    assert _downloader().open_document_direction(browser_page, "outgoing") is browser_page


def test_parent_menu_expands_then_dynamic_child_is_clicked(browser_page):
    browser_page.set_content(
        f"<a onclick=\"document.getElementById('child').style.display='block'\">Văn bản đến</a>"
        f"<a id=child style='display:none' href='javascript:void(0)' "
        f"onclick=\"document.getElementById('x').innerHTML='{TABLE}'\">Văn bản đến chờ xử lý</a><div id=x></div>"
    )
    assert _downloader().open_document_direction(browser_page, "incoming") is browser_page


def test_repeated_header_row_is_not_parsed_as_document(browser_page):
    browser_page.set_content(
        "<table><thead><tr><th>STT</th><th>Số ký hiệu</th><th>Trích yếu</th></tr></thead>"
        "<tbody><tr><td>STT</td><td>Số ký hiệu</td><td>Trích yếu</td></tr>"
        "<tr><td>1</td><td>123/QĐ</td><td>Về việc kiểm thử tải văn bản</td></tr></tbody></table>"
    )
    downloader = _downloader()
    headers = downloader._extract_headers(browser_page)
    records = downloader._extract_records_from_current_page(browser_page, "incoming", "https://host/list", headers)
    assert len(records) == 1 and records[0].doc_no == "123/QĐ"


def test_after_parent_click_keyword_child_wins_over_wrong_text_sibling(browser_page):
    browser_page.set_content(
        f"<a onclick=\"document.getElementById('children').style.display='block'\">Văn bản đến</a>"
        f"<div id=children style='display:none'>"
        f"<a href='javascript:link(\"VAN_BAN_DA_XU_LY\")'>Văn bản đến trả lại</a>"
        f"<a href='javascript:void(0)' data-url='VAN_BAN_DEN_CA_NHAN' "
        f"onclick=\"document.getElementById('x').innerHTML='{TABLE}'\">Văn bản đến chờ xử lý</a></div><div id=x></div>"
    )
    assert _downloader().open_document_direction(browser_page, "incoming") is browser_page
