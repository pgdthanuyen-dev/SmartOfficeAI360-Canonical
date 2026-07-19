import sys
import os

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from tools.qlvb_downloader.downloader import QLVBDownloader
from tools.qlvb_downloader.config import QLVBConfig

class MockLocator:
    def locator(self, sel):
        return self
    def count(self):
        return 0
    def get_attribute(self, attr):
        return ""

class MockLocatorWithTh:
    def locator(self, sel):
        if sel == "th": return type('L', (), {'count': lambda self: 1})()
        if sel == "td": return type('L', (), {'count': lambda self: 0})()
        return MockLocator()
    def get_attribute(self, attr):
        return ""

class MockLocatorWithHeaderClass:
    def locator(self, sel):
        return type('L', (), {'count': lambda self: 0})()
    def get_attribute(self, attr):
        if attr == "class": return "table-header-row"
        return ""

def test_header_filters():
    dl = QLVBDownloader(QLVBConfig())
    
    print("\n[TEST 1] tbody có dòng đầu là header 'Trích yếu' -> bỏ qua")
    row_text = "STT Trích yếu Số / Ký hiệu Ngày văn bản Cơ quan ban hành"
    cells = ["STT", "Trích yếu", "Số / Ký hiệu", "Ngày văn bản", "Cơ quan ban hành"]
    assert dl._is_header_row(MockLocator(), row_text, cells, ["STT", "Trích yếu"]), "Phải bỏ qua dòng chứa header labels"
    print("  -> PASSED")

    print("\n[TEST 2] tbody có th thay vì td -> bỏ qua")
    row_text = "Nội dung"
    cells = ["Nội dung"]
    assert dl._is_header_row(MockLocatorWithTh(), row_text, cells, None), "Phải bỏ qua dòng có <th>"
    print("  -> PASSED")
    
    print("\n[TEST 3] Dòng hồ sơ thật đầy đủ -> giữ")
    row_text = "1 123/UBND-VX Về việc abc 01/01/2026 UBND"
    cells = ["1", "123/UBND-VX", "Về việc abc", "01/01/2026", "UBND"]
    assert not dl._is_header_row(MockLocator(), row_text, cells, None), "Phải giữ lại hồ sơ thật"
    print("  -> PASSED")
    
    print("\n[TEST 4] Dòng hồ sơ thật thiếu số ký hiệu -> giữ (validation sẽ lo)")
    row_text = "2 Về việc thông báo abc 02/01/2026 Sở GDĐT"
    cells = ["2", "", "Về việc thông báo abc", "02/01/2026", "Sở GDĐT"]
    assert not dl._is_header_row(MockLocator(), row_text, cells, None), "Phải giữ lại hồ sơ thiếu số ký hiệu"
    print("  -> PASSED")
    
    print("\n[TEST 5] Header-row xen giữa danh sách (với stt) -> bỏ qua")
    row_text = "Số Trích yếu Ngày"
    cells = ["Số", "Trích yếu", "Ngày"]
    assert dl._is_header_row(MockLocator(), row_text, cells, ["Số", "Trích yếu"]), "Phải bỏ qua header xen giữa danh sách"
    print("  -> PASSED")
    
    print("\n[TEST 6] Class header -> bỏ qua")
    row_text = "Data"
    cells = ["Data"]
    assert dl._is_header_row(MockLocatorWithHeaderClass(), row_text, cells, None), "Phải bỏ qua dòng có class header"
    print("  -> PASSED")

    print("\nALL HEADER FILTER TESTS PASSED!")

if __name__ == '__main__':
    test_header_filters()
