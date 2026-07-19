from tools.qlvb_downloader.downloader import QLVBDownloader


def test_normal_detail_url():
    url = QLVBDownloader._url_from_action(
        "https://qlvb.example/qlvbdh/main?list=1", "?6yXl=VAN_BAN_DEN_CHI_TIET&id=42"
    )
    assert url == "https://qlvb.example/qlvbdh/main?6yXl=VAN_BAN_DEN_CHI_TIET&id=42"


def test_javascript_wrapped_detail_url():
    url = QLVBDownloader._url_from_action(
        "https://qlvb.example/qlvbdh/main", "javascript:void(0)",
        "openWindow('/qlvbdh/main?6yXl=VAN_BAN_DEN_CHI_TIET&id=42')",
    )
    assert url == "https://qlvb.example/qlvbdh/main?6yXl=VAN_BAN_DEN_CHI_TIET&id=42"


def test_unusable_javascript_has_no_url():
    assert QLVBDownloader._url_from_action("https://qlvb.example/main", "javascript:view(42)") is None
