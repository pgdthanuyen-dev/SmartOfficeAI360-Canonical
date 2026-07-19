from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .paths import project_root, resolve_path

VERSION = "V22.2.3-QC_MAINTENANCE1_DATA_INTEGRITY"

DEFAULT_SELECTORS = {
    "login": {
        "username": [
            "input[name='username']", "input[name='UserName']", "input[name='USER_NAME']",
            "input[id*='user' i]", "input[name*='user' i]", "input[id*='tai' i]",
            "input[name*='tai' i]", "input[placeholder*='tên đăng nhập' i]",
            "input[placeholder*='tai khoan' i]", "input[placeholder*='tài khoản' i]",
            "input[placeholder*='username' i]", "input[autocomplete='username']",
            "input[type='text']"
        ],
        "password": [
            "input[name='password']", "input[name='Password']", "input[name='PASSWORD']",
            "input[id*='pass' i]", "input[name*='pass' i]", "input[placeholder*='mật khẩu' i]",
            "input[placeholder*='mat khau' i]", "input[autocomplete='current-password']", "input[type='password']"
        ],
        "submit": [
            "button[type='submit']", "input[type='submit']", "button:has-text('Đăng nhập')",
            "button:has-text('Dang nhap')", "button:has-text('Login')", "a:has-text('Đăng nhập')",
            "a:has-text('Dang nhap')", ".btn-login", "#btnLogin", "button.btn-primary"
        ],
        "captcha": [
            "input[name*='captcha' i]", "input[id*='captcha' i]", "img[src*='captcha' i]",
            "iframe[src*='captcha' i]", "div[class*='captcha' i]",
            "div[class*='captra' i]", "input[id*='txtMaXacNhan' i]", "input[name*='XacNhan' i]"
        ],
        "logged_in_markers": [
            "a:has-text('Đăng xuất')", "a:has-text('Thoát')", "button:has-text('Đăng xuất')",
            "text=Văn bản đến", "text=Văn bản đi", "text=Quản lý văn bản"
        ]
    },
    "list": {
        "table": ["table", ".k-grid table", ".dx-datagrid table", ".ant-table table", ".el-table table", ".v-data-table table", ".grid table", "#grid table", ".table", "[role='grid'] table"],
        "rows": ["table tbody tr", ".k-grid-content tr", ".dx-datagrid-rowsview tr", ".ant-table-tbody tr", ".el-table__body tr", ".v-data-table tbody tr", ".grid-content tr", "[role='row']", "tr"],
        "next_page": [
            "a:has-text('Sau')", "a:has-text('Tiếp')", "button:has-text('Sau')", "button:has-text('Tiếp')",
            ".k-pager-nav.k-link[title*='next' i]", ".k-pager-nav.k-link[title*='sau' i]",
            ".pagination .next a", ".paginate_button.next", "a[aria-label*='Next' i]", "button[aria-label*='Next' i]"
        ],
        "detail_link": ["a[href]"],
        "empty_markers": ["Không có dữ liệu", "Khong co du lieu", "No data", "Không tìm thấy", "Khong tim thay"]
    },
    "detail": {
        "attachment_links": [
            "a[href*='download' i]", "a[href*='attachment' i]", "a[href*='file' i]",
            "a[href*='GetFile' i]", "a[href*='Download' i]", "a[href*='GetAttachment' i]",
            "a[href$='.pdf' i]", "a[href$='.doc' i]", "a[href$='.docx' i]", "a[href$='.xls' i]",
            "a[href$='.xlsx' i]", "a[href$='.zip' i]", "a:has-text('.pdf')", "a:has-text('.doc')",
            "a:has-text('.xls')", "a:has-text('Tải')", "a:has-text('Tai')", "a:has-text('Đính kèm')",
            "a:has-text('Dinh kem')", "a:has-text('File')", "a:has-text('Tệp')", "a:has-text('Tep')"
        ],
        "metadata_blocks": ["table", ".form-horizontal", ".detail", ".content", "body"]
    }
}


@dataclass
class BrowserConfig:
    headless: bool = False
    slow_mo_ms: int = 80
    timeout_ms: int = 45000
    persistent_profile: str = "Data/runtime/playwright_profile"
    chromium_channel: str | None = None
    allow_manual_login: bool = True
    manual_login_wait_seconds: int = 120


@dataclass
class DownloadConfig:
    max_items_per_run: int = 50
    max_pages_per_direction: int = 1
    skip_existing: bool = True
    save_source_html_on_error: bool = True
    save_screenshot_on_error: bool = True
    copy_files_to_queue: bool = True
    create_ready_marker: bool = True
    min_file_size_bytes: int = 1
    retry_download_times: int = 2
    retry_detail_times: int = 2
    dry_run: bool = False
    export_html_report: bool = True
    export_csv_report: bool = True
    detect_duplicate_by: str = "doc_id"


@dataclass
class QLVBConfig:
    version: str = VERSION
    qlvb_base_url: str = ""
    login_url: str = ""
    username: str = ""
    password: str = ""
    remember_password: bool = False
    incoming_pending_url: str = ""
    incoming_processed_url: str = ""
    outgoing_issued_url: str = ""
    use_fixed_urls: bool = True
    enable_dom_navigation_fallback: bool = False
    save_root: str = "Data"
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    download: DownloadConfig = field(default_factory=DownloadConfig)
    selectors: dict[str, Any] = field(default_factory=lambda: json.loads(json.dumps(DEFAULT_SELECTORS, ensure_ascii=False)))
    password_source: str = "MANUAL"
    planner_api_url: str = ""
    planner_ingest_token: str = ""

    @property
    def root_path(self) -> Path:
        return resolve_path(self.save_root, "Data")

    @property
    def browser_profile_path(self) -> Path:
        return resolve_path(self.browser.persistent_profile, "Data/runtime/playwright_profile")


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        elif key == "ghi_chu":
            continue
        else:
            result[key] = value
    return result


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def _candidate_config_paths(root: Path) -> list[Path]:
    return [
        root / "Data/config/qlvb_downloader_config.json",
        root / "Data/config/qlvb_config.json",
        root / "config/qlvb_downloader_config.json",
        root / "qlvb_downloader_config.json",
    ]


def find_config_file() -> Path | None:
    env_path = os.environ.get("SMARTOFFICE_QLVB_CONFIG")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p
    root = project_root()
    for p in _candidate_config_paths(root):
        if p.exists():
            return p
    return None


def normalize_legacy_config(raw: dict[str, Any]) -> dict[str, Any]:
    """Accept field names from older UX builds and normalize them for V22.1.4."""
    aliases = {
        "qlvb_base_url": ["qlvb_base_url", "base_url", "url_qlvb", "qlvb_url", "dia_chi_qlvb", "address"],
        "login_url": ["login_url", "url_dang_nhap", "login"],
        "username": ["username", "user", "ten_dang_nhap", "tai_khoan", "account"],
        "password": ["password", "pass", "mat_khau"],
        "incoming_pending_url": ["incoming_pending_url", "incoming_url", "link_van_ban_den", "link_den", "url_incoming", "van_ban_den_url", "van_ban_den_cho_xu_ly"],
        "incoming_processed_url": ["incoming_processed_url", "link_van_ban_den_da_xu_ly"],
        "outgoing_issued_url": ["outgoing_issued_url", "outgoing_url", "link_van_ban_di", "link_di", "url_outgoing", "van_ban_di_url"],
        "save_root": ["save_root", "noi_luu_file", "save_dir", "download_dir", "data_root"],
    }
    normalized: dict[str, Any] = {}
    for target, keys in aliases.items():
        for key in keys:
            if key in raw and raw[key] not in [None, ""]:
                normalized[target] = raw[key]
                break

    for key in ["remember_password", "browser", "download", "selectors", "version"]:
        if key in raw:
            normalized[key] = raw[key]

    # Some older config screens save links under nested keys.
    for nested_key in ["qlvb", "downloader", "config"]:
        nested = raw.get(nested_key) if isinstance(raw.get(nested_key), dict) else {}
        for target, keys in aliases.items():
            if target not in normalized:
                for key in keys:
                    if key in nested and nested[key] not in [None, ""]:
                        normalized[target] = nested[key]
                        break
    return normalized


def _filter_dataclass_kwargs(raw: dict[str, Any], cls: type) -> dict[str, Any]:
    return {k: v for k, v in raw.items() if k in cls.__annotations__}


def load_config(path: Path | None = None) -> QLVBConfig:
    root = project_root()
    path = path or find_config_file()
    if path is None:
        raise FileNotFoundError(
            "Chưa thấy file cấu hình QLVB. Hãy tạo Data/config/qlvb_downloader_config.json "
            "theo mẫu Data/config/qlvb_downloader_config.example.json."
        )

    raw = normalize_legacy_config(_read_json(path))
    browser_raw = raw.get("browser") or {}
    download_raw = raw.get("download") or {}
    selectors = _deep_merge(DEFAULT_SELECTORS, raw.get("selectors") or {})
    # User configs from older releases replaced selector lists wholesale.
    # Keep custom selectors, but never lose newer safety-critical defaults.
    for group, values in DEFAULT_SELECTORS.items():
        if not isinstance(values, dict):
            continue
        selectors.setdefault(group, {})
        for key, defaults in values.items():
            if not isinstance(defaults, list):
                continue
            current = selectors[group].setdefault(key, [])
            selectors[group][key] = list(dict.fromkeys([*current, *defaults]))

    config_password = raw.get("password", "")
    env_password = os.environ.get("QLVB_PASSWORD") or os.environ.get("SMARTOFFICE_QLVB_PASSWORD")
    
    password = ""
    password_source = "MANUAL"
    
    if config_password:
        password = config_password
        password_source = "CONFIG"
    elif env_password:
        password = env_password
        password_source = "ENV"

    env_token = os.environ.get("PLANNER_INGEST_TOKEN") or os.environ.get("SMARTOFFICE_PLANNER_TOKEN")
    planner_ingest_token = raw.get("planner_ingest_token", "")
    if not planner_ingest_token and env_token:
        planner_ingest_token = env_token

    cfg = QLVBConfig(
        version=VERSION,
        qlvb_base_url=raw.get("qlvb_base_url", ""),
        login_url=raw.get("login_url", "") or raw.get("qlvb_base_url", ""),
        username=raw.get("username", ""),
        password=password,
        remember_password=bool(raw.get("remember_password", False)),
        incoming_pending_url=raw.get("incoming_pending_url", ""),
        incoming_processed_url=raw.get("incoming_processed_url", ""),
        outgoing_issued_url=raw.get("outgoing_issued_url", ""),
        use_fixed_urls=bool(raw.get("use_fixed_urls", True)),
        enable_dom_navigation_fallback=bool(raw.get("enable_dom_navigation_fallback", False)),
        save_root=raw.get("save_root", "Data"),
        browser=BrowserConfig(**_filter_dataclass_kwargs(browser_raw, BrowserConfig)),
        download=DownloadConfig(**_filter_dataclass_kwargs(download_raw, DownloadConfig)),
        selectors=selectors,
        password_source=password_source,
        planner_api_url=raw.get("planner_api_url", ""),
        planner_ingest_token=planner_ingest_token,
    )

    cfg.root_path.mkdir(parents=True, exist_ok=True)
    cfg.browser_profile_path.mkdir(parents=True, exist_ok=True)
    return cfg


def save_config(cfg: QLVBConfig, path: Path | None = None) -> Path:
    root = project_root()
    path = path or root / "Data/config/qlvb_downloader_config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": VERSION,
        "qlvb_base_url": cfg.qlvb_base_url,
        "login_url": cfg.login_url,
        "username": cfg.username,
        "password": cfg.password if cfg.remember_password else "",
        "remember_password": cfg.remember_password,
        "incoming_pending_url": cfg.incoming_pending_url,
        "incoming_processed_url": cfg.incoming_processed_url,
        "outgoing_issued_url": cfg.outgoing_issued_url,
        "use_fixed_urls": cfg.use_fixed_urls,
        "enable_dom_navigation_fallback": cfg.enable_dom_navigation_fallback,
        "save_root": cfg.save_root,
        "browser": cfg.browser.__dict__,
        "download": cfg.download.__dict__,
        "selectors": cfg.selectors,
        "planner_api_url": cfg.planner_api_url,
        "planner_ingest_token": cfg.planner_ingest_token,
    }
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path
