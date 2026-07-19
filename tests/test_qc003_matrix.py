"""
tests/test_qc003_matrix.py - Unit tests for QC-003 strict workflow.
Run with: pytest tests/test_qc003_matrix.py
"""
import pytest
from unittest.mock import MagicMock, call
from tools.qlvb_downloader.downloader import QLVBDownloader
from tools.qlvb_downloader.config import QLVBConfig
from tools.qlvb_downloader.models import DocumentRecord

@pytest.fixture
def mock_downloader():
    config = QLVBConfig()
    return QLVBDownloader(config)

def test_extract_detail_action_index_finds_trich_yeu(mock_downloader):
    row = MagicMock()
    actions = MagicMock()
    row.locator.return_value = actions
    actions.count.return_value = 4
    
    def nth_effect(i):
        el = MagicMock()
        if i == 0:
            el.inner_text.return_value = "Báo cáo bình thường"
            el.get_attribute.side_effect = lambda k: "http://abc" if k == "href" else ""
        elif i == 1:
            el.inner_text.return_value = "Xử lý"
            el.get_attribute.side_effect = lambda k: "showdocdetail()" if k == "onclick" else ""
        elif i == 2:
            el.inner_text.return_value = "Trích yếu đặc biệt cần click"
            el.get_attribute.side_effect = lambda k: ""
        elif i == 3:
            el.inner_text.return_value = "Trích yếu đặc biệt cần click"
            el.get_attribute.side_effect = lambda k: "javascript:openDetail()" if k == "href" else ""
        return el
        
    actions.nth.side_effect = nth_effect
    index = mock_downloader._extract_detail_action_index(row)
    assert index == 1

def test_extract_attachments_finds_zip_button(mock_downloader):
    page = MagicMock()
    
    # Simulate get_by_text finding the ZIP button
    btn_mock = MagicMock()
    btn_mock.count.return_value = 1
    nth_mock = MagicMock()
    nth_mock.is_visible.return_value = True
    nth_mock.get_attribute.side_effect = lambda k: "javascript:downloadAll()" if k == "onclick" else None
    btn_mock.nth.return_value = nth_mock
    btn_mock.first = nth_mock
    
    def get_by_text_mock(text, exact=False):
        if text == "Nén và tải tất cả":
            return btn_mock
        return MagicMock()
        
    page.get_by_text.side_effect = get_by_text_mock
    
    # Mock locator just in case
    page.locator.return_value.filter.return_value = btn_mock
    
    attachments = mock_downloader._extract_attachments(page)
    
    assert len(attachments) == 1
    assert attachments[0].text == "Nén và tải tất cả"
    assert attachments[0].original_filename == "tat_ca_dinh_kem.zip"

def test_extract_attachments_finds_zip_button(mock_downloader):
    page = MagicMock()
    page.url = "https://qlvb.laichau.gov.vn/qlvbdh_lcu/main"

    container = MagicMock()
    container.inner_text.return_value = "Văn bản đính kèm  Nén và tải tất cả"

    btn_mock = MagicMock()
    btn_mock.count.return_value = 1
    nth_mock = MagicMock()
    nth_mock.is_visible.return_value = True
    nth_mock.inner_text.return_value = "Nén và tải tất cả"
    nth_mock.get_attribute.side_effect = lambda k: "javascript:downloadAll()" if k == "onclick" else None
    btn_mock.first = nth_mock
    container.locator.return_value = btn_mock

    rows = MagicMock()
    rows.count.return_value = 1
    rows.nth.return_value = container
    page.locator.return_value = rows

    attachments = mock_downloader._extract_attachments(page)

    assert len(attachments) == 1
    assert attachments[0].text == "Nén và tải tất cả"
    assert attachments[0].original_filename == "tat_ca_dinh_kem.zip"

def test_validate_fixed_qlvb_url_empty_invalid(mock_downloader):
    # Test empty
    res = mock_downloader.validate_fixed_qlvb_url("", "incoming")
    assert res["valid"] is False
    assert res["error"] == "FIXED_URL_EMPTY"

    # Test javascript
    res2 = mock_downloader.validate_fixed_qlvb_url("javascript:void(0)", "incoming")
    assert res2["valid"] is False
    assert res2["error"] == "FIXED_URL_INVALID_SCHEME"

    # Test non http
    res3 = mock_downloader.validate_fixed_qlvb_url("ftp://example.com", "incoming")
    assert res3["valid"] is False
    assert res3["error"] == "FIXED_URL_INVALID_SCHEME"

    # Test wrong host
    res4 = mock_downloader.validate_fixed_qlvb_url("http://google.com", "incoming", allowed_host="qlvb.laichau.gov.vn")
    assert res4["valid"] is False
    assert res4["error"] == "FIXED_URL_WRONG_HOST"

def test_validate_fixed_qlvb_url_valid_empty(mock_downloader, monkeypatch):
    # Mock playwright Context and Page
    mock_downloader.config.browser.headless = True
    
    class MockLocator:
        def __init__(self, text="", count=0):
            self._text = text
            self._count = count
        def count(self): return self._count
        def inner_text(self, timeout=0): return self._text
        @property
        def first(self): return self
        def nth(self, i): return self

    class MockPage:
        def set_default_timeout(self, ms): pass
        def goto(self, url, wait_until=""): pass
        def locator(self, selector):
            if ".breadcrumb" in selector:
                return MockLocator("Văn bản đến / Văn bản đến chờ xử lý")
            if "body" in selector:
                return MockLocator("không tìm thấy dữ liệu")
            if "table" in selector:
                return MockLocator("không tìm thấy dữ liệu", count=1)
            return MockLocator()

    mock_downloader._ensure_logged_in = MagicMock()
    mock_downloader._safe_wait_networkidle = MagicMock()
    mock_downloader._is_logged_in = MagicMock(return_value=True)
    mock_downloader._find_document_table = MagicMock(return_value=MockLocator("table", count=1))
    mock_downloader._extract_headers = MagicMock(return_value=["A", "B"])

    # Monkeypatch playwright
    class MockContext:
        pages = []
        def new_page(self): return MockPage()
        def close(self): pass

    class MockChromium:
        def launch_persistent_context(self, *args, **kwargs):
            return MockContext()

    class MockPlaywright:
        chromium = MockChromium()
        def __enter__(self): return self
        def __exit__(self, *args): pass
        
    import tools.qlvb_downloader.downloader
    monkeypatch.setattr(tools.qlvb_downloader.downloader, "sync_playwright", lambda: MockPlaywright())
    monkeypatch.setattr(tools.qlvb_downloader.downloader, "configure_bundled_playwright", lambda: None)

    res = mock_downloader.validate_fixed_qlvb_url("http://qlvb.laichau.gov.vn/incoming", "incoming")
    assert res["valid"] is True
    assert res["status"] == "VALID_EMPTY"
    assert res["record_count"] == 0
    assert res["source_category"] == "incoming"
    assert res["direction"] == "incoming"

def test_validate_fixed_qlvb_url_direction_mismatch(mock_downloader, monkeypatch):
    mock_downloader.config.browser.headless = True
    
    class MockLocator:
        def __init__(self, text="", count=0):
            self._text = text
            self._count = count
        def count(self): return self._count
        def inner_text(self, timeout=0): return self._text
        @property
        def first(self): return self
        def nth(self, i): return self

    class MockPage:
        def set_default_timeout(self, ms): pass
        def goto(self, url, wait_until=""): pass
        def locator(self, selector):
            # Mismatch: expects incoming but gets văn bản đi
            if ".breadcrumb" in selector:
                return MockLocator("Văn bản đi / Văn bản đi chờ xử lý")
            if "body" in selector:
                return MockLocator("không tìm thấy dữ liệu")
            return MockLocator()

    mock_downloader._ensure_logged_in = MagicMock()
    mock_downloader._safe_wait_networkidle = MagicMock()
    mock_downloader._is_logged_in = MagicMock(return_value=True)
    mock_downloader._find_document_table = MagicMock(return_value=MockLocator("table", count=1))
    mock_downloader._extract_headers = MagicMock(return_value=["A", "B"])

    class MockContext:
        pages = []
        def new_page(self): return MockPage()
        def close(self): pass

    class MockChromium:
        def launch_persistent_context(self, *args, **kwargs): return MockContext()

    class MockPlaywright:
        chromium = MockChromium()
        def __enter__(self): return self
        def __exit__(self, *args): pass
        
    import tools.qlvb_downloader.downloader
    monkeypatch.setattr(tools.qlvb_downloader.downloader, "sync_playwright", lambda: MockPlaywright())
    monkeypatch.setattr(tools.qlvb_downloader.downloader, "configure_bundled_playwright", lambda: None)

    res = mock_downloader.validate_fixed_qlvb_url("http://qlvb.laichau.gov.vn/incoming", "incoming")
    assert res["valid"] is False
    assert res["error"] == "FIXED_URL_DIRECTION_MISMATCH"
