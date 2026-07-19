from __future__ import annotations
import pytest
from tools.qlvb_downloader.downloader import QLVBDownloader
from tools.qlvb_downloader.config import QLVBConfig
from tools.qlvb_downloader.parser import build_header_map, is_document_table_headers

def test_path_validator_accepts_runtime_path():
    cfg = QLVBConfig()
    downloader = QLVBDownloader(cfg)
    captured = "https://qlvb.laichau.gov.vn/qlvbdh_lcu/smartoffice/jbm/download_all.jsp?token=123"
    detail_url = "https://qlvb.laichau.gov.vn/qlvbdh_lcu/main"
    res = downloader._validate_captured_download_url(captured, detail_url)
    assert res == captured

def test_path_validator_rejects_almost_similar_path():
    cfg = QLVBConfig()
    downloader = QLVBDownloader(cfg)
    captured = "https://qlvb.laichau.gov.vn/qlvbdh_lcu/smartoffice/jbm/download_some.jsp"
    detail_url = "https://qlvb.laichau.gov.vn/qlvbdh_lcu/main"
    with pytest.raises(RuntimeError, match="UNEXPECTED_DOWNLOAD_PATH"):
        downloader._validate_captured_download_url(captured, detail_url)

def test_path_validator_rejects_smartca_host():
    cfg = QLVBConfig()
    downloader = QLVBDownloader(cfg)
    captured = "https://smartca.laichau.gov.vn/smartoffice/jbm/download_all.jsp"
    detail_url = "https://qlvb.laichau.gov.vn/qlvbdh_lcu/main"
    with pytest.raises(RuntimeError, match="UNEXPECTED_DOWNLOAD_HOST"):
        downloader._validate_captured_download_url(captured, detail_url)

def test_path_validator_resolves_relative_url():
    cfg = QLVBConfig()
    downloader = QLVBDownloader(cfg)
    captured = "smartoffice/jbm/download_all.jsp?docid=1"
    detail_url = "https://qlvb.laichau.gov.vn/qlvbdh_lcu/main"
    res = downloader._validate_captured_download_url(captured, detail_url)
    assert res == "https://qlvb.laichau.gov.vn/qlvbdh_lcu/smartoffice/jbm/download_all.jsp?docid=1"

def test_header_map_excludes_data_row():
    headers = ["1", "9447", "1180/UBND-VP", "tên trích yếu", "tên cơ quan", "22/10/2026"]
    is_valid = is_document_table_headers(headers)
    assert not is_valid

    headers_valid = ["STT", "Số eOffice", "Số/Ký hiệu", "Ngày văn bản", "Trích yếu", "Thao tác"]
    is_valid_yes = is_document_table_headers(headers_valid)
    assert is_valid_yes
    h_map = build_header_map(headers_valid)
    assert "doc_no" in h_map
    assert h_map["doc_no"] == 2