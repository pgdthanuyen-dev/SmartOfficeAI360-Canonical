from __future__ import annotations

import re
import time
import traceback
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urljoin, urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import Locator, Page, sync_playwright

from .config import QLVBConfig, VERSION
from .logger import build_logger
from .models import AttachmentInfo, DocumentRecord, now_iso, safe_slug, mask_url_query, safe_slug, mask_url_query
from .parser import attachment_from_anchor, build_record_from_row, clean_text, guess_date, is_probable_attachment
from .storage import StorageManager
from .report import append_csv_report, write_html_run_report
from .paths import configure_bundled_playwright


QLVB_ALLOWED_HOSTS = {"qlvb.laichau.gov.vn"}
QLVB_DOWNLOAD_ALL_PATHS = ["/smartoffice/jbm/download_all.jsp"]

class QLVBDownloader:
    def __init__(self, config: QLVBConfig):
        self.config = config
        self.storage = StorageManager(
            config.root_path,
            copy_files_to_queue=config.download.copy_files_to_queue,
            create_ready_marker=config.download.create_ready_marker,
        )
        self.logger, self.log_file = build_logger(self.storage.log_root)
        self.report_rows = []
        self.run_id = now_iso().replace(":", "").replace("-", "").replace("T", "_")
        self.run_summary = {
            "version": VERSION,
            "started_at": now_iso(),
            "log_file": str(self.log_file),
            "run_id": self.run_id,
            "mode": "DRY_RUN" if self.config.download.dry_run else "REAL_DOWNLOAD",
            "directions": {},
            "errors": [],
        }

    def run(self, directions: Iterable[str] = ("incoming", "outgoing"), headless: bool | None = None, max_items: int | None = None, login_only: bool = False) -> dict:
        configure_bundled_playwright()
        headless_value = self.config.browser.headless if headless is None else headless
        if login_only:
            headless_value = False
        max_items_value = max_items or self.config.download.max_items_per_run
        global_processed = 0
        if login_only:
            self.logger.info("Bat dau QLVB Downloader V22.2.2-QC Hotfix 3 | version=%s | login_only=True", VERSION)
        else:
            self.logger.info("Bat dau QLVB Downloader V22.2.2-QC Hotfix 3 | version=%s | headless=%s | max_items=%s | dry_run=%s", VERSION, headless_value, max_items_value, self.config.download.dry_run)
        self._validate_config()

        with sync_playwright() as p:
            launch_kwargs = {
                "headless": headless_value,
                "slow_mo": self.config.browser.slow_mo_ms,
                "accept_downloads": True,
                "args": ["--disable-blink-features=AutomationControlled", "--disable-popup-blocking"]
            }
            if self.config.browser.chromium_channel:
                launch_kwargs["channel"] = self.config.browser.chromium_channel
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(self.config.browser_profile_path),
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                **launch_kwargs,
            )
            context.set_default_timeout(self.config.browser.timeout_ms)
            page = context.pages[0] if context.pages else context.new_page()
            try:
                self._ensure_logged_in(page, headless_value=headless_value)
                if login_only:
                    self.logger.info("Dang nhap thanh cong va da luu phien.")
                    self.run_summary["status"] = "DONE"
                    self.run_summary["login_status"] = "Đăng nhập thành công"
                else:
                    if self.config.use_fixed_urls:
                        sources = [
                            ("incoming", "incoming_pending", self.config.incoming_pending_url, True, True),
                            ("incoming", "incoming_processed", self.config.incoming_processed_url, False, True),
                            ("outgoing", "outgoing_issued", self.config.outgoing_issued_url, False, True),
                        ]
                        for direction, category, url, planner, knowledge in sources:
                            if not url or not self._is_http_url(url):
                                continue
                            self.run_summary["directions"][category] = self._process_direction(
                                page, direction, max_items_value, 
                                fixed_url=url, category=category, planner=planner, knowledge=knowledge
                            )
                        
                        if not any(s[2] for s in sources):
                            self.logger.warning("use_fixed_urls = True nhưng không có link cố định nào được cấu hình.")
                    else:
                        for direction in directions:
                            if direction not in ["incoming", "outgoing"]:
                                continue
                            remain = max(0, max_items_value - global_processed)
                            res = self._process_direction(page, direction, remain)
                            self.run_summary["directions"][direction] = res
                            global_processed += res.get("processed", 0)
            except Exception as exc:
                self.run_summary["status"] = "FAILED"
                self.run_summary["error"] = str(exc)
                self.logger.error("Loi trong qua trinh chay: %s", exc)
                raise exc
            finally:
                context.close()

        self.run_summary["finished_at"] = now_iso()
        summary_path = self.storage.log_root / "qlvb_downloader_last_run_summary.json"
        self.storage.write_json(summary_path, self.run_summary)
        if self.config.download.export_html_report:
            write_html_run_report(self.storage.log_root / "qlvb_downloader_last_run_report.html", self.run_summary, self.report_rows)
        self.logger.info("Hoan thanh. Summary: %s", summary_path)
        return self.run_summary

    def validate_fixed_qlvb_url(self, url: str, expected_direction: str, allowed_host: str = "qlvb.laichau.gov.vn") -> dict:
        if not url:
            return {"valid": False, "error": "FIXED_URL_EMPTY"}
        if url.lower().startswith("javascript:") or "onclick" in url.lower():
            return {"valid": False, "error": "FIXED_URL_INVALID_SCHEME"}
        parsed = urlparse(url)
        if parsed.scheme not in ["http", "https"]:
            return {"valid": False, "error": "FIXED_URL_INVALID_SCHEME"}
        if allowed_host and allowed_host not in parsed.netloc:
            return {"valid": False, "error": "FIXED_URL_WRONG_HOST"}
            
        configure_bundled_playwright()
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(self.config.browser_profile_path),
                headless=self.config.browser.headless,
                args=["--disable-blink-features=AutomationControlled"]
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.set_default_timeout(self.config.browser.timeout_ms)
                
                self._ensure_logged_in(page, headless_value=self.config.browser.headless)
                page.goto(url, wait_until="domcontentloaded")
                self._safe_wait_networkidle(page)
                
                if not self._is_logged_in(page):
                    return {"valid": False, "error": "FIXED_URL_REDIRECTED_TO_LOGIN"}
                    
                breadcrumb = ""
                try:
                    breadcrumb = clean_text(page.locator(".breadcrumb, .page-title, h1, h2, .nav-title").first.inner_text(timeout=1000))
                except Exception:
                    pass
                    
                is_empty_state = False
                empty_texts = ["không tìm thấy dữ liệu", "không có dữ liệu", "không có bản ghi", "no data available", "không có văn bản"]
                try:
                    page_text = page.locator("body").inner_text(timeout=1000).lower()
                    if any(et in page_text for et in empty_texts):
                        is_empty_state = True
                except Exception:
                    pass

                table = self._find_document_table(page)
                if not table and not is_empty_state:
                    return {"valid": False, "error": "FIXED_URL_DOCUMENT_TABLE_NOT_FOUND"}

                # Check direction mismatch
                is_incoming = "văn bản đến" in breadcrumb.lower() or "van_ban_den" in url.lower()
                is_outgoing = "văn bản đi" in breadcrumb.lower() or "vanban_di" in url.lower()
                if "incoming" in expected_direction and is_outgoing:
                    return {"valid": False, "error": "FIXED_URL_DIRECTION_MISMATCH"}
                if "outgoing" in expected_direction and is_incoming:
                    return {"valid": False, "error": "FIXED_URL_DIRECTION_MISMATCH"}
                    
                headers = []
                row_count = 0
                if table:
                    headers = self._extract_headers(page)
                    for sel in self.config.selectors["list"].get("rows", ["table tbody tr"]):
                        try:
                            loc = page.locator(sel)
                            rc = loc.count()
                            valid_rows = 0
                            for i in range(rc):
                                row_text = loc.nth(i).inner_text(timeout=100).lower()
                                if any(et in row_text for et in empty_texts):
                                    is_empty_state = True
                                else:
                                    valid_rows += 1
                            row_count = valid_rows
                            if valid_rows > 0:
                                break
                        except Exception:
                            pass

                direction = "incoming" if "incoming" in expected_direction else "outgoing"
                
                if row_count == 0 and is_empty_state:
                    return {
                        "valid": True,
                        "status": "VALID_EMPTY",
                        "source_category": expected_direction,
                        "direction": direction,
                        "record_count": 0,
                        "title": breadcrumb,
                        "message": "Link hợp lệ, hiện chưa có dữ liệu",
                        "columns": headers
                    }

                return {
                    "valid": True,
                    "status": "VALID_WITH_DATA",
                    "source_category": expected_direction,
                    "direction": direction,
                    "record_count": row_count,
                    "title": breadcrumb,
                    "columns": headers
                }
            except Exception as e:
                return {"valid": False, "error": f"Lỗi không xác định: {e}"}
            finally:
                context.close()

    def _validate_config(self) -> None:
        missing = []
        if not (self.config.qlvb_base_url or self.config.login_url or getattr(self.config, 'incoming_url', '') or getattr(self.config, 'outgoing_url', '') or self.config.incoming_pending_url):
            missing.append("địa chỉ/link QLVB")
        if not self.config.username:
            missing.append("tên đăng nhập")
        if not self.config.password and not self.config.browser.allow_manual_login:
            missing.append("mật khẩu")
        if missing:
            raise ValueError("Thiếu cấu hình: " + ", ".join(missing))

    def _goto(self, page: Page, url: str, label: str) -> None:
        if not self._is_http_url(url):
            raise RuntimeError(f"UNSAFE_NAVIGATION_TARGET: {label} khong phai URL HTTP/HTTPS")
        self.logger.info("Mo trang %s: %s", label, mask_url_query(url))
        page.goto(url, wait_until="domcontentloaded", timeout=self.config.browser.timeout_ms)
        self._safe_wait_networkidle(page)

    @staticmethod
    def _is_http_url(value: str | None) -> bool:
        try:
            return urlparse(str(value or "").strip()).scheme.lower() in {"http", "https"}
        except Exception:
            return False

    def _safe_home_url(self) -> str:
        for value in (self.config.qlvb_base_url, self.config.login_url, getattr(self.config, 'incoming_url', ''), getattr(self.config, 'outgoing_url', ''), self.config.incoming_pending_url):
            if self._is_http_url(value):
                return str(value)
        raise RuntimeError("NAVIGATION_HOME_URL_NOT_FOUND")

    def _safe_wait_networkidle(self, page: Page, timeout: int = 8000) -> None:
        try:
            page.wait_for_load_state("networkidle", timeout=timeout)
        except PlaywrightTimeoutError:
            pass

    def _count_visible(self, page: Page, selectors: list[str]) -> int:
        total = 0
        for sel in selectors:
            try:
                loc = page.locator(sel)
                count = min(loc.count(), 5)
                for i in range(count):
                    try:
                        if loc.nth(i).is_visible(timeout=300):
                            total += 1
                    except Exception:
                        continue
            except Exception:
                continue
        return total

    def _first_visible(self, page: Page, selectors: list[str], timeout: int = 1000) -> Locator | None:
        for sel in selectors:
            try:
                loc = page.locator(sel)
                count = loc.count()
                for i in range(min(count, 10)):
                    item = loc.nth(i)
                    try:
                        if item.is_visible(timeout=timeout):
                            return item
                    except Exception:
                        continue
            except Exception:
                continue
        return None

    def _update_dynamic_urls(self, page: Page):
        # Dynamic QLVB menu actions belong to the current authenticated DOM.
        # Never persist them as URLs or reuse them in a later browser session.
        self.logger.info("Da o man hinh chinh; menu dong se duoc click tren DOM hien tai.")

    def _ensure_logged_in(self, page: Page, headless_value: bool = False) -> None:
        # Sử dụng URL làm mồi (nếu là Lai Châu bị cấu hình thiếu /qlvbdh_lcu/main thì bù vào)
        probe_url = self._safe_home_url()
        if probe_url.strip("/") == "https://qlvb.laichau.gov.vn":
            probe_url = "https://qlvb.laichau.gov.vn/qlvbdh_lcu/main"

        self._goto(page, probe_url, "kiem tra phien dang nhap")
        if self._is_logged_in(page):
            self.logger.info("Da co phien dang nhap hop le, khong can dang nhap lai.")
            self._update_dynamic_urls(page)
            return

        login_url = self.config.login_url if self._is_http_url(self.config.login_url) else probe_url
        self._goto(page, login_url, "dang nhap")
        if self._is_logged_in(page):
            self.logger.info("Trang dang nhap da tu chuyen vao he thong, phien hop le.")
            self._update_dynamic_urls(page)
            return

        login_selectors = self.config.selectors["login"]
        username = self._first_visible(page, login_selectors["username"])
        password = self._first_visible(page, login_selectors["password"])
        submit = self._first_visible(page, login_selectors["submit"])

        if username and password and self.config.username and self.config.password:
            self.logger.info("Dang dien thong tin dang nhap...")
            username.fill(self.config.username)
            password.fill(self.config.password)

        if self._detect_captcha(page):
            self._save_page_error(page, "captcha_login")
            if self._wait_manual_login(page, probe_url, reason="Trang đăng nhập có CAPTCHA/OTP", headless_value=headless_value):
                return
            raise RuntimeError("Trang đăng nhập có CAPTCHA/OTP. Vui lòng chạy hiện trình duyệt, đăng nhập thủ công một lần rồi chạy lại để dùng phiên đã lưu.")

        if not username or not password:
            self._save_page_error(page, "login_fields_not_found")
            if self._wait_manual_login(page, probe_url, reason="Không tìm thấy ô tài khoản/mật khẩu", headless_value=headless_value):
                return
            raise RuntimeError("Không tìm thấy ô tên đăng nhập/mật khẩu. Cần cập nhật selector sau khi xem log/screenshot.")

        if self.config.username and self.config.password:
            self.logger.info("Khong phat hien CAPTCHA, tu dong submit...")
            if submit:
                submit.click()
            else:
                password.press("Enter")
            self._safe_wait_networkidle(page, timeout=12000)
        else:
            self.logger.warning("Chua co mat khau trong cau hinh, chuyen sang che do dang nhap thu cong.")

        self._goto(page, probe_url, "kiem tra sau dang nhap")
        if not self._is_logged_in(page):
            self._save_page_error(page, "login_failed")
            if self._wait_manual_login(page, probe_url, reason="Đăng nhập tự động chưa thành công", headless_value=headless_value):
                return
            raise RuntimeError("Đăng nhập chưa thành công. Kiểm tra tài khoản, mật khẩu, CAPTCHA/OTP hoặc selector.")
        self.logger.info("Dang nhap thanh cong, phien trinh duyet da duoc luu.")
        self._update_dynamic_urls(page)

    def _wait_manual_login(self, page: Page, probe_url: str, reason: str, headless_value: bool) -> bool:
        if headless_value or not self.config.browser.allow_manual_login:
            return False
        wait_seconds = max(10, int(self.config.browser.manual_login_wait_seconds or 120))
        self.logger.warning("%s. Cho phep dang nhap thu cong trong %s giay. Sếp đăng nhập xong, tool sẽ tự kiểm tra lại.", reason, wait_seconds)
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            try:
                if self._is_logged_in(page):
                    self.logger.info("Da phat hien dang nhap thu cong thanh cong.")
                    self._update_dynamic_urls(page)
                    return True
                # Định kỳ thử mở lại link đích; nếu phiên đã có cookie thì sẽ vào thẳng danh sách.
                # Never reload while the user is solving CAPTCHA: doing so
                # clears both the verification code and the filled fields.
                login_form_visible = self._count_visible(page, self.config.selectors["login"]["password"]) > 0
                if not login_form_visible and page.url != probe_url:
                    try:
                        page.goto(probe_url, wait_until="domcontentloaded", timeout=10000)
                        self._safe_wait_networkidle(page, timeout=3000)
                    except Exception:
                        pass
                    if self._is_logged_in(page):
                        self.logger.info("Dang nhap thu cong thanh cong va da luu phien.")
                        self._update_dynamic_urls(page)
                        return True
            except Exception:
                pass
            time.sleep(2)
        self.logger.error("Het thoi gian cho dang nhap thu cong.")
        return False

    def _is_logged_in(self, page: Page) -> bool:
        login_selectors = self.config.selectors["login"]
        if self._count_visible(page, login_selectors["password"]) > 0:
            return False
        if self._count_visible(page, login_selectors.get("logged_in_markers", [])) > 0:
            return True
        try:
            body = clean_text(page.locator("body").inner_text(timeout=5000)) if page.locator("body").count() else ""
        except Exception:
            body = ""
        login_words = ["đăng nhập", "dang nhap", "login", "mật khẩu", "mat khau", "password"]
        list_words = ["văn bản đến", "van ban den", "văn bản đi", "van ban di", "trích yếu", "so van ban", "số văn bản"]
        body_l = body.lower()
        if any(w in body_l for w in list_words):
            return True
        if len(body) < 120 and any(w in body_l for w in login_words):
            return False
        return bool(body)

    def _detect_captcha(self, page: Page) -> bool:
        return self._count_visible(page, self.config.selectors["login"].get("captcha", [])) > 0

    def open_document_direction(self, page: Page, direction: str) -> Page:
        if direction not in {"incoming", "outgoing"}:
            raise ValueError(f"Unsupported direction: {direction}")
        label = "Văn bản đến" if direction == "incoming" else "Văn bản đi"
        keywords = ["van_ban_den_ca_nhan", "van_ban_den", "vanban_den"] if direction == "incoming" else [
            "van_ban_di", "vanban_di", "vanban_di_da_banhanh", "vanban_di_cho_banhanh"
        ]
        home_url = getattr(self.config, "qlvb_base_url", "")
        if self._is_http_url(home_url) and not page.url.rstrip("/").lower() == str(home_url).rstrip("/").lower():
            self._goto(page, str(home_url), "man hinh chinh QLVB")
        if not self._is_logged_in(page):
            raise RuntimeError("QLVB_MAIN_SCREEN_NOT_FOUND")
        self.logger.info("Da o man hinh chinh QLVB.")
        self.logger.info("Dang tim menu %s.", label)

        text_selectors = [
            f"a:has-text('{label}')", f"button:has-text('{label}')",
            f"[role='menuitem']:has-text('{label}')", f"[onclick]:has-text('{label}')",
        ]
        keyword_selectors = [
            f"a[href*='{word}' i], [onclick*='{word}' i], [data-url*='{word}' i], [data-href*='{word}' i]"
            for word in keywords
        ]
        pages_before = set(page.context.pages)
        deadline = time.time() + 30
        target_page = page
        attempted: set[str] = set()
        found_any = False

        def next_candidate():
            scopes = [page, *page.frames]
            selectors = (text_selectors + keyword_selectors) if not attempted else (keyword_selectors + text_selectors)
            for selector in selectors:
                for scope in scopes:
                    try:
                        loc = scope.locator(selector)
                        for i in range(min(loc.count(), 30)):
                            candidate = loc.nth(i)
                            if not candidate.is_visible(timeout=200):
                                continue
                            signature = "|".join([
                                clean_text(candidate.inner_text(timeout=300)),
                                candidate.get_attribute("href") or "",
                                candidate.get_attribute("onclick") or "",
                                candidate.get_attribute("data-url") or "",
                                candidate.get_attribute("data-href") or "",
                            ])
                            if signature not in attempted:
                                return candidate, selector, signature
                    except Exception:
                        continue
            return None

        while time.time() < deadline:
            found = next_candidate()
            if found is None:
                if not found_any:
                    extra = self._navigation_debug(page)
                    self._save_page_error(page, f"navigation_menu_not_found_{direction}", extra=extra)
                    raise RuntimeError("NAVIGATION_MENU_NOT_FOUND")
                page.wait_for_timeout(250)
                continue
            matched, matched_selector, signature = found
            attempted.add(signature)
            found_any = True
            self.logger.info("Menu %s matched selector: %s", label, matched_selector)
            try:
                matched.click(timeout=5000)
            except Exception:
                matched.evaluate("element => element.click()")
            self.logger.info("Da click menu %s (lan %s).", label, len(attempted))

            attempt_deadline = min(deadline, time.time() + 4)
            while time.time() < attempt_deadline:
                new_pages = [item for item in page.context.pages if item not in pages_before]
                if new_pages:
                    target_page = new_pages[-1]
                    try:
                        target_page.wait_for_load_state("domcontentloaded", timeout=3000)
                    except Exception:
                        pass
                table = self._find_document_table(target_page, allow_fallback=False)
                if table is not None:
                    self.logger.info("Da tim thay bang danh sach sau khi click menu %s.", label)
                    return target_page
                target_page.wait_for_timeout(250)

        self._save_page_error(target_page, f"document_table_not_found_{direction}", extra=self._navigation_debug(target_page))
        raise RuntimeError("DOCUMENT_TABLE_NOT_FOUND")

    def _navigation_debug(self, page: Page) -> dict:
        frames = []
        elements = []
        for frame in page.frames:
            frames.append(frame.url)
            try:
                loc = frame.locator("a, button, [onclick], [href]")
                for i in range(min(loc.count(), 200)):
                    item = loc.nth(i)
                    text = clean_text(item.inner_text(timeout=200))[:120]
                    href = (item.get_attribute("href") or "").strip().lower()
                    onclick = bool(item.get_attribute("onclick"))
                    if "văn bản" not in text.lower() and "van ban" not in text.lower() and not onclick and not href:
                        continue
                    kind = "javascript" if href.startswith("javascript:") else "hash" if href.startswith("#") else "http" if self._is_http_url(href) else "relative" if href else "none"
                    elements.append({"text": text, "href_kind": kind, "onclick": onclick})
            except Exception:
                continue
        return {"frame_urls": frames, "navigation_elements": elements[:300]}

    def _process_direction(self, page: Page, direction: str, max_items: int,
                           fixed_url: str = "", category: str = "", planner: bool = False, knowledge: bool = False) -> dict:
        result = {"status": "RUNNING", "url": fixed_url or "DOM_MENU", "processed": 0, "skipped_existing": 0, "downloaded_files": 0, "errors": []}
        detail_page: Page | None = None
        try:
            if fixed_url:
                self._goto(page, fixed_url, f"Link cố định {category}")
                if not self._is_logged_in(page):
                    self.logger.warning("Trang yêu cầu đăng nhập lại (SESSION_EXPIRED).")
                    self._ensure_logged_in(page, headless_value=self.config.browser.headless)
                    self._goto(page, fixed_url, f"Retry link cố định {category} sau khi login")
                
                table = self._find_document_table(page)
                if not table:
                    is_empty_state = False
                    empty_texts = ["không tìm thấy dữ liệu", "không có dữ liệu", "không có bản ghi", "no data available", "không có văn bản"]
                    try:
                        page_text = page.locator("body").inner_text(timeout=1000).lower()
                        if any(et in page_text for et in empty_texts):
                            is_empty_state = True
                    except Exception:
                        pass
                        
                    if is_empty_state:
                        self.logger.info("Nguồn %s hiện chưa có dữ liệu (EMPTY).", category)
                        result["status"] = "EMPTY"
                        result["message"] = "Hiện chưa có văn bản đến chờ xử lý" if "pending" in category else "Hiện chưa có dữ liệu"
                        return result
                    else:
                        raise RuntimeError("FIXED_URL_DOCUMENT_TABLE_NOT_FOUND")
            else:
                page = self.open_document_direction(page, direction)
                
            source_url = page.url
            headers = self._extract_headers(page)
            seen_ids: set[str] = set()
            page_no = 1
            max_pages = max(1, int(getattr(self.config.download, "max_pages_per_direction", 1)))
            detail_page = page.context.new_page()
            detail_page.set_default_timeout(self.config.browser.timeout_ms)

            while page_no <= max_pages and result["processed"] < max_items:
                self.logger.info("Quet danh sach %s | trang %s/%s", direction, page_no, max_pages)
                records = self._extract_records_from_current_page(page, direction, source_url, headers)
                if not records:
                    if page_no == 1:
                        is_empty_state = False
                        empty_texts = ["không tìm thấy dữ liệu", "không có dữ liệu", "không có bản ghi", "no data available", "không có văn bản"]
                        try:
                            page_text = page.locator("body").inner_text(timeout=1000).lower()
                            if any(et in page_text for et in empty_texts):
                                is_empty_state = True
                        except Exception:
                            pass
                        
                        if is_empty_state:
                            self.logger.info("Nguồn %s hiện chưa có dữ liệu (EMPTY).", category)
                            result["status"] = "EMPTY"
                            result["message"] = "Hiện chưa có văn bản đến chờ xử lý" if "pending" in category else "Hiện chưa có dữ liệu"
                            break
                            
                    self.logger.warning("Khong doc duoc dong nao o danh sach %s trang %s.", direction, page_no)
                    self._save_page_error(page, f"no_rows_{direction}_page_{page_no}", extra={"headers": headers, "url": page.url})
                    break

                for rec in records:
                    if category:
                        rec.source_category = category
                    rec.planner_candidate = planner
                    rec.knowledge_candidate = knowledge
                    
                    if result["processed"] >= max_items:
                        break
                    rec.ensure_doc_id()
                    if rec.doc_id in seen_ids:
                        continue
                    seen_ids.add(rec.doc_id)

                    # Deduplication check
                    external_doc_id = rec.doc_id
                    already_in_queue = False
                    
                    # Check queue directory (both formats via get_queue_item_files)
                    queue_info = self.storage.get_queue_item_files(direction, external_doc_id)
                    if queue_info is not None:
                        already_in_queue = True
                        
                    # Check if files directory status is READY
                    existing = self.storage.existing_status(rec) if self.config.download.skip_existing else None
                    already_downloaded = existing and str(existing.get("status", "")).startswith("READY")
                    
                    if already_in_queue or already_downloaded:
                        self.logger.info("Bo qua ho so bi trung (external_doc_id: %s) | skipped_duplicate", external_doc_id)
                        result["skipped_existing"] += 1
                        continue

                    try:
                        self._process_record(detail_page, rec, list_page=page)
                        result["processed"] += 1
                        result["downloaded_files"] += sum(1 for a in rec.attachments if a.status == "DOWNLOADED")
                    except Exception as exc:
                        rec.status = "ERROR"
                        rec.error = str(exc)
                        self._write_outputs_and_report(rec)
                        err = {"doc_id": rec.doc_id, "error": str(exc)}
                        result["errors"].append(err)
                        self.run_summary["errors"].append(err)
                        self.logger.error("Loi xu ly ho so %s: %s", rec.doc_id, exc)
                        self.logger.debug(traceback.format_exc())
                    finally:
                        result["processed"] += 1

                if result["processed"] >= max_items:
                    break
                if not self._go_next_page(page):
                    break
                page_no += 1
                headers = self._extract_headers(page)

            result["status"] = "DONE" if not result["errors"] else "DONE_WITH_ERRORS"
            return result
        except Exception as exc:
            self._save_page_error(page, f"direction_error_{direction}")
            result["status"] = "ERROR"
            result["error"] = str(exc)
            self.run_summary["errors"].append({"direction": direction, "error": str(exc)})
            self.logger.error("Loi xu ly huong %s: %s", direction, exc)
            return result
        finally:
            try:
                if detail_page:
                    detail_page.close()
            except Exception:
                pass

    def _find_document_table(self, page: Page, allow_fallback: bool = True) -> Locator | None:
        try:
            scopes = [page]
            if hasattr(page, "frames"):
                scopes.extend(page.frames)
            for scope in scopes:
                tables = scope.locator("table").all()
                for t in tables:
                    try:
                        if t.is_visible():
                            headers = [clean_text(h) for h in t.locator("thead th, tr th").all_inner_texts()]
                            headers = [h for h in headers if h]
                            if headers:
                                from .parser import is_document_table_headers
                                if is_document_table_headers(headers):
                                    self.logger.info("Da tim thay bang danh sach van ban hop le voi cac cot: %s", ", ".join(headers))
                                    return t
                    except Exception:
                        continue
            
            if not allow_fallback:
                return None
            # Fallback if no table matches: first visible table matching config selectors
            selectors = self.config.selectors["list"].get("table", ["table"])
            for scope in scopes:
                fallback = self._first_visible(scope, selectors, timeout=500)
                if fallback:
                    self.logger.debug("Khong tim thay bang nao khop tieu chi, fallback ve bang visible dau tien.")
                    return fallback
            return None
        except Exception as e:
            self.logger.error("Loi khi tim bang danh sach van ban: %s", e)
            return None

    def _extract_headers(self, page: Page) -> list[str]:
        self._current_table_container = None
        table = self._find_document_table(page)
        if not table:
            return []
            
        # Resolve container
        container = table
        try:
            parent = table.locator("..")
            for _ in range(3):
                class_attr = parent.get_attribute("class") or ""
                if any(c in class_attr for c in ["k-grid", "dx-datagrid", "ant-table", "el-table", "v-data-table"]):
                    container = parent
                    break
                parent = parent.locator("..")
        except Exception:
            pass
        self._current_table_container = container

        try:
            headers = table.locator("thead th, tr th").all_inner_texts()
            return [clean_text(h) for h in headers if clean_text(h)]
        except Exception:
            return []

    def _extract_records_from_current_page(self, page: Page, direction: str, source_url: str, headers: list[str]) -> list[DocumentRecord]:
        records: list[DocumentRecord] = []
        row_selectors = self.config.selectors["list"].get("rows", ["table tbody tr"])
        
        # Determine search context: either resolved container or global page
        context = getattr(self, "_current_table_container", None) or page
        
        rows: Locator | None = None
        for sel in row_selectors:
            try:
                relative_sel = sel
                if context != page:
                    try:
                        tag_name = context.evaluate("el => el.tagName.toLowerCase()")
                    except Exception:
                        tag_name = ""
                    if tag_name == "table":
                        if relative_sel.startswith("table "):
                            relative_sel = relative_sel[6:]
                        elif relative_sel == "table":
                            relative_sel = "tr"
                
                loc = context.locator(relative_sel)
                if loc.count() > 0:
                    rows = loc
                    break
            except Exception:
                continue
        if rows is None:
            return records

        count = rows.count()
        for i in range(count):
            row = rows.nth(i)
            try:
                row_text = clean_text(row.inner_text(timeout=3000))
            except Exception:
                continue
            if not row_text or self._is_empty_row(row_text):
                continue
            try:
                cells = [clean_text(c) for c in row.locator("td, th").all_inner_texts()]
            except Exception:
                cells = [row_text]
            cells = [c for c in cells if c]

            if self._is_header_row(row, row_text, cells, headers):
                self.logger.debug("Bỏ qua dòng tiêu đề bảng, không phải hồ sơ: %s", row_text[:160])
                continue
            if len(cells) <= 1 and len(row_text) < 15:
                continue
            detail_url = self._extract_detail_url(row, page.url)
            
            # Construct record
            rec = build_record_from_row(direction, source_url, i + 1, row_text, cells, detail_url, headers if len(headers) == len(cells) else None)
            rec.metadata["row_locator_index"] = i
            rec.metadata["detail_action_index"] = self._extract_detail_action_index(row)
            
            # Validate document record immediately
            from .parser import validate_document_record
            status, reason = validate_document_record(rec)
            if status == "INVALID":
                self.logger.warning("skipped_invalid_non_document_record | Ly do: %s | doc_id: %s", reason, rec.doc_id)
                continue
                
            records.append(rec)
        return records

    def _is_empty_row(self, text: str) -> bool:
        lowered = text.lower()
        for marker in self.config.selectors["list"].get("empty_markers", []):
            if marker.lower() in lowered:
                return True
        return False

    def _is_header_row(self, row: Locator, row_text: str, cells: list[str], headers: list[str] | None) -> bool:
        lowered = row_text.lower()
        
        # 1. Chứa đồng thời nhiều nhãn
        labels = ["trích yếu", "số ký hiệu", "số / ký hiệu", "ngày văn bản", "cơ quan ban hành", "người ký", "loại văn bản"]
        hits = sum(1 for kw in labels if kw in lowered)
        if hits >= 3:
            return True
            
        # 2. Các cell bắt đầu bằng stt hoặc chứa phần lớn các header truyền vào
        if cells and cells[0].strip().lower() in ("stt", "số", "tt"):
            return True
            
        if headers and len(cells) >= 2:
            header_set = {clean_text(value).lower() for value in headers if clean_text(value)}
            header_hits = sum(1 for value in cells if value.lower() in header_set)
            if header_hits >= max(2, len(cells) // 2):
                return True
                
        # 3. Có th thay vì td
        try:
            th_count = row.locator("th").count()
            td_count = row.locator("td").count()
            if th_count > 0 and td_count == 0:
                return True
        except Exception:
            pass
            
        # 4. Có class dạng header
        try:
            cls = row.get_attribute("class") or ""
            cls_low = cls.lower()
            if any(hc in cls_low for hc in ["header", "table-header", "grid-header"]):
                return True
        except Exception:
            pass
            
        return False

    def _extract_detail_url(self, row: Locator, base_url: str) -> str | None:
        try:
            anchors = row.locator("a, button, [onclick], [data-url], [data-href]")
            count = anchors.count()
            first_any = None
            for i in range(min(count, 30)):
                a = anchors.nth(i)
                href = a.get_attribute("href") or a.get_attribute("data-url") or a.get_attribute("data-href") or ""
                text = clean_text(a.inner_text(timeout=1000))
                full = self._url_from_action(base_url, href, a.get_attribute("onclick") or "")
                if not full:
                    continue
                first_any = first_any or full
                if not is_probable_attachment(text, full):
                    return full
            return first_any
        except Exception:
            return None

    @staticmethod
    def _url_from_action(base_url: str, href: str, onclick: str = "") -> str | None:
        """Resolve normal, data-* and JavaScript-wrapped detail URLs."""
        href = (href or "").strip()
        if href and not href.lower().startswith("javascript:") and href not in ("#", ""):
            return urljoin(base_url, href)
        script = " ".join(x for x in (href, onclick) if x)
        for value in re.findall(r"['\"]([^'\"]+)['\"]", script):
            candidate = value.strip()
            low = candidate.lower()
            if (candidate.startswith(("/", "?", "http://", "https://")) or
                    "6yxl=" in low or "/main" in low or "detail" in low or "van_ban" in low):
                return urljoin(base_url, candidate)
        return None

    def _extract_detail_action_index(self, row: Locator) -> int | None:
        """Remember a clickable row action when the site exposes no real href."""
        try:
            actions = row.locator("a, button, [onclick], [role='button']")
            fallback = None
            for i in range(min(actions.count(), 40)):
                action = actions.nth(i)
                text = clean_text(action.inner_text(timeout=500)).lower()
                href = action.get_attribute("href") or ""
                onclick = action.get_attribute("onclick") or ""
                if is_probable_attachment(text, href):
                    continue
                if "showdocdetail" in onclick.lower():
                    return i
                if fallback is None and (onclick or href.lower().startswith("javascript:")):
                    fallback = i
                if any(word in text for word in ("chi tiết", "chi tiet", "trích yếu", "trich yeu", "xem")):
                    return i
            return fallback
        except Exception:
            return None

    def _process_record(self, page: Page, rec: DocumentRecord, list_page: Page | None = None) -> None:
        self.logger.info("Xu ly ho so: %s | %s", rec.doc_id, rec.title[:120])
        active_page = page
        restore_list = False
        opened_detail = bool(rec.detail_url)
        if rec.detail_url:
            self._goto_detail_with_retry(page, rec.detail_url, f"chi tiet {rec.doc_id}")
        elif list_page is not None:
            opened = self._open_detail_by_saved_action(list_page, rec)
            if opened is not None:
                active_page, restore_list = opened
                opened_detail = True
            else:
                self.logger.warning("Ho so %s khong co link/hanh dong chi tiet hop le.", rec.doc_id)
        else:
            self.logger.warning("Ho so %s khong co link chi tiet; chi ghi metadata dong danh sach.", rec.doc_id)

        if opened_detail:
            self._merge_detail_metadata(active_page, rec)
            rec.attachments = self._extract_attachments(active_page)

        if not rec.attachments:
            rec.status = "READY_NO_ATTACHMENT"
            self.logger.warning("Ho so %s chua tim thay file dinh kem.", rec.doc_id)
        elif self.config.download.dry_run:
            rec.status = "READY_DRY_RUN"
            self.logger.info("DRY RUN: chi ghi metadata, khong tai tep dinh kem.")
        else:
            self._download_attachments(active_page, rec)
            downloaded = sum(1 for a in rec.attachments if a.status == "DOWNLOADED")
            rec.status = "READY" if downloaded > 0 else "READY_ATTACHMENT_ERROR"

        self._write_outputs_and_report(rec)
        if active_page is not page and active_page is not list_page:
            try:
                active_page.close()
            except Exception:
                pass
        elif restore_list and list_page is not None:
            try:
                list_page.go_back(wait_until="domcontentloaded", timeout=self.config.browser.timeout_ms)
            except Exception:
                self._goto(list_page, rec.source_url, "khoi phuc danh sach")
        elif opened_detail and list_page is not None and active_page is list_page:
            self._close_detail_modal(list_page)

    def _close_detail_modal(self, page: Page) -> None:
        for selector in (
            "[role='dialog']:visible button[aria-label*='close' i]",
            ".modal:visible button.close", ".modal:visible .btn-close",
            ".ui-dialog:visible .ui-dialog-titlebar-close",
            "button:visible:has-text('Đóng')", "button:visible:has-text('Dong')",
        ):
            try:
                loc = page.locator(selector)
                if loc.count():
                    loc.first.click(force=True)
                    return
            except Exception:
                continue

    def _open_detail_by_saved_action(self, list_page: Page, rec: DocumentRecord) -> tuple[Page, bool] | None:
        action_index = rec.metadata.get("detail_action_index")
        row_index = rec.metadata.get("row_locator_index")
        if action_index is None or row_index is None:
            return None
        table = self._find_document_table(list_page)
        if table is None:
            return None
        rows = table.locator("tbody tr")
        if rows.count() <= int(row_index):
            rows = table.locator("tr")
        if rows.count() <= int(row_index):
            return None
        actions = rows.nth(int(row_index)).locator("a, button, [onclick], [role='button']")
        if actions.count() <= int(action_index):
            return None
        before_url = list_page.url
        before_pages = set(list_page.context.pages)
        try:
            actions.nth(int(action_index)).evaluate("el => { if(el.getAttribute('onclick')) { let fn = new Function(el.getAttribute('onclick')); fn.call(el); } else { el.click(); } }")
        except Exception:
            actions.nth(int(action_index)).click(force=True)
            
        list_page.wait_for_timeout(2000)
        self._safe_wait_networkidle(list_page, timeout=8000)
        new_pages = [p for p in list_page.context.pages if p not in before_pages]
        if new_pages:
            detail = new_pages[-1]
            detail.wait_for_load_state("domcontentloaded", timeout=self.config.browser.timeout_ms)
            return detail, False
        if list_page.url != before_url:
            return list_page, True
        # QLVB may render a modal/AJAX detail view on the list page.
        # If it didn't open a new page, just return list_page and search for attachments.
        # It's safer to just search the current page for attachments than to fail completely.
        return list_page, False

    def _goto_detail_with_retry(self, page: Page, url: str, label: str) -> None:
        attempts = max(1, int(getattr(self.config.download, "retry_detail_times", 2) or 1))
        last_exc = None
        for attempt in range(1, attempts + 1):
            try:
                self._goto(page, url, f"{label} | lan {attempt}")
                return
            except Exception as exc:
                last_exc = exc
                self.logger.warning("Mo chi tiet loi lan %s/%s: %s", attempt, attempts, exc)
                time.sleep(1 + attempt)
        raise RuntimeError(f"Khong mo duoc trang chi tiet sau {attempts} lan: {last_exc}")

    def _write_outputs_and_report(self, rec: DocumentRecord) -> None:
        paths = self.storage.write_document_outputs(rec)
        row = {
            "run_id": self.run_id,
            "time": now_iso(),
            "direction": rec.direction,
            "doc_id": rec.doc_id,
            "doc_no": rec.doc_no,
            "doc_date": rec.doc_date,
            "issuing_agency": rec.issuing_agency,
            "title": rec.title,
            "status": rec.status,
            "attachment_total": len(rec.attachments),
            "attachment_downloaded": sum(1 for a in rec.attachments if a.status == "DOWNLOADED"),
            "document_dir": paths.get("document_dir", ""),
            "queue_ready_dir": paths.get("queue_ready_dir", ""),
            "error": rec.error or "",
        }
        self.report_rows.append(row)
        if self.config.download.export_csv_report:
            append_csv_report(self.storage.log_root / "qlvb_downloader_run_report.csv", row)

    def _merge_detail_metadata(self, page: Page, rec: DocumentRecord) -> None:
        try:
            body_text = clean_text(page.locator("body").inner_text(timeout=8000))
        except Exception:
            body_text = ""
        rec.metadata["detail_body_excerpt"] = body_text[:4000]

        pairs = {}
        try:
            rows = page.locator("tr")
            for i in range(min(rows.count(), 120)):
                cells = [clean_text(c) for c in rows.nth(i).locator("td, th").all_inner_texts()]
                cells = [c for c in cells if c]
                if len(cells) >= 2:
                    key = cells[0].rstrip(":")
                    val = " | ".join(cells[1:])
                    if 1 <= len(key) <= 90 and val:
                        pairs[key] = val
        except Exception:
            pass
        try:
            dts = page.locator("dt")
            for i in range(min(dts.count(), 80)):
                key = clean_text(dts.nth(i).inner_text(timeout=500)).rstrip(":")
                dd = page.locator("dd").nth(i) if page.locator("dd").count() > i else None
                val = clean_text(dd.inner_text(timeout=500)) if dd else ""
                if key and val:
                    pairs[key] = val
        except Exception:
            pass
        rec.metadata["detail_pairs"] = pairs

        def first_pair_contains(words: list[str]) -> str:
            for k, v in pairs.items():
                kl = k.lower()
                if any(w in kl for w in words):
                    return v
            return ""

        rec.doc_no = rec.doc_no or first_pair_contains(["số", "ký hiệu"])
        rec.doc_date = rec.doc_date or first_pair_contains(["ngày"])
        rec.issuing_agency = rec.issuing_agency or first_pair_contains(["cơ quan", "nơi gửi", "đơn vị", "người gửi"])
        rec.title = rec.title or first_pair_contains(["trích yếu", "nội dung", "tiêu đề", "tên văn bản"])
        rec.summary = rec.summary or rec.title
        if not rec.doc_date:
            rec.doc_date = guess_date(body_text)

    def _extract_attachments(self, page: Page) -> list[AttachmentInfo]:
        attachments: list[AttachmentInfo] = []
        seen = set()
        
        # QC-003: Tim nut Nen va tai tat ca
        zip_loc = None
        zip_selectors = [
            page.locator("a, button").filter(has_text=re.compile(r"(nén và )?tải tất cả", re.I)),
            page.locator("[onclick*='downloadAll' i], [onclick*='taiTatCa' i], [href*='filedownload']"),
            page.locator("[title*='Nén'], [title*='tải tất cả' i], [aria-label*='Nén'], [aria-label*='tải tất cả' i]")
        ]
        for loc in zip_selectors:
            try:
                if loc.count() > 0 and loc.first.is_visible(timeout=500):
                    zip_loc = loc.first
                    break
            except Exception:
                pass

        if zip_loc:
            href = zip_loc.get_attribute("href") or ""
            onclick = zip_loc.get_attribute("onclick") or ""
            if onclick and not href:
                href = f"javascript:{onclick}"
            if not href.lower().startswith("javascript:") and not href.startswith("http"):
                href = urljoin(page.url, href)
            
            if href:
                info = AttachmentInfo(
                    text="Nén và tải tất cả",
                    original_filename="tat_ca_dinh_kem.zip",
                    href=href,
                    status="PENDING",
                    saved_path=""
                )
                attachments.append(info)
                self.logger.info("Da tim thay nut Nen va tai tat ca: %s", href)
                return attachments

        selectors = self.config.selectors["detail"].get("attachment_links", ["a[href]"])
        for sel in selectors:
            try:
                anchors = page.locator(sel)
                count = anchors.count()
                for i in range(min(count, 160)):
                    a = anchors.nth(i)
                    href = a.get_attribute("href") or ""
                    text = clean_text(a.inner_text(timeout=1000))
                    info = attachment_from_anchor(page.url, text, href)
                    if not info:
                        continue
                    key = info.href + "|" + text
                    if key in seen:
                        continue
                    seen.add(key)
                    attachments.append(info)
            except Exception:
                continue
        return attachments

    def _download_attachments(self, page: Page, rec: DocumentRecord) -> None:
        attempts = max(1, int(getattr(self.config.download, "retry_download_times", 2) or 1))
        downloaded_files = 0
        downloaded_archives = 0
        extracted_files = 0
        materialized_files = 0
        
        for idx, att in enumerate(rec.attachments, start=1):
            self.logger.info("Tai tep %s/%s: %s", idx, len(rec.attachments), att.href)
            last_exc = None
            for attempt in range(1, attempts + 1):
                try:
                    saved = self._download_by_click_or_request(page, rec, att.href, idx)
                    if saved.stat().st_size < self.config.download.min_file_size_bytes:
                        raise RuntimeError(f"File tai ve qua nho: {saved.stat().st_size} bytes")
                    att.saved_path = str(saved)
                    att.original_filename = saved.name
                    att.status = "DOWNLOADED"
                    
                    downloaded_files += 1
                    materialized_files += 1
                    
                    if saved.suffix.lower() == ".zip":
                        downloaded_archives += 1
                        extracted = self._extract_zip_bundle(rec, saved)
                        extracted_files += len(extracted)
                        materialized_files += len(extracted)
                        
                    break
                except Exception as exc:
                    last_exc = exc
                    att.status = "ERROR"
                    att.error = str(exc)
                    self.logger.warning("Tai tep loi lan %s/%s: %s | %s", attempt, attempts, att.href, exc)
                    import time
                    time.sleep(1 + attempt)
            if att.status != "DOWNLOADED":
                self.logger.error("Khong tai duoc tep sau %s lan: %s | %s", attempts, att.href, last_exc)
                
        rec.metadata["download_stats"] = {
            "downloaded_files": downloaded_files,
            "downloaded_archives": downloaded_archives,
            "extracted_files": extracted_files,
            "materialized_files": materialized_files,
        }

    def _locator_for_href(self, page: Page, href: str) -> Locator | None:
        try:
            anchors = page.locator("a[href]")
            for i in range(min(anchors.count(), 300)):
                a = anchors.nth(i)
                raw = a.get_attribute("href") or ""
                full = raw if raw.lower().startswith("javascript:") else urljoin(page.url, raw)
                if raw == href or full == href or unquote(full) == unquote(href):
                    return a
        except Exception:
            return None
        return None

    def _download_by_click_or_request(self, page: Page, rec: DocumentRecord, href: str, idx: int) -> Path:
        locator = self._locator_for_href(page, href)
        intercepted_path = None
        
        def handle_response(response):
            nonlocal intercepted_path
            if response.status == 200 and ("application/zip" in response.headers.get("content-type", "").lower() or "attachment" in response.headers.get("content-disposition", "").lower()):
                try:
                    filename = self._filename_from_response(response.url, response.headers, idx)
                    target = self.storage.next_download_path(rec, filename, idx)
                    target.write_bytes(response.body())
                    intercepted_path = target
                except Exception:
                    pass

        if href.lower().startswith("javascript:"):
            return self.trigger_qlvb_attachment_download(page, locator, rec, href, idx)

        if locator is not None:
            page.on("response", handle_response)
            try:
                with page.expect_download(timeout=12000) as download_info:
                    locator.evaluate("el => el.click()")
                download = download_info.value
                suggested = download.suggested_filename or f"tep_dinh_kem_{idx}.bin"
                target = self.storage.next_download_path(rec, suggested, idx)
                download.save_as(str(target))
                page.remove_listener("response", handle_response)
                return target
            except Exception as exc:
                self.logger.warning("Click khong bat duoc download (%s), chuyen sang tai truc tiep neu co the.", exc)
                page.remove_listener("response", handle_response)
                if intercepted_path and intercepted_path.exists():
                    self.logger.info("Da bat duoc file thong qua response interceptor: %s", intercepted_path)
                    return intercepted_path

        if href.lower().startswith("javascript:"):
            raise RuntimeError("Link tải là javascript và click không tạo download. Cần vá selector/luồng tải theo log.")

        response = page.context.request.get(href, timeout=self.config.browser.timeout_ms)
        if not response.ok:
            raise RuntimeError(f"HTTP {response.status} khi tải file")
        filename = self._filename_from_response(href, response.headers, idx)
        target = self.storage.next_download_path(rec, filename, idx)
        target.write_bytes(response.body())
        return target

    def _filename_from_response(self, href: str, headers: dict, idx: int) -> str:
        cd = headers.get("content-disposition") or headers.get("Content-Disposition") or ""
        m = re.search(r"filename\*=UTF-8''([^;]+)", cd, flags=re.I)
        if m:
            return unquote(m.group(1).strip().strip('"'))
        m = re.search(r"filename=(?:\")?([^\";]+)", cd, flags=re.I)
        if m:
            return unquote(m.group(1).strip().strip('"'))
        tail = href.split("/")[-1].split("?")[0].split("#")[0]
        return unquote(tail) or f"tep_dinh_kem_{idx}.bin"

    def _go_next_page(self, page: Page) -> bool:
        selectors = self.config.selectors["list"].get("next_page", [])
        for sel in selectors:
            try:
                loc = page.locator(sel)
                if loc.count() and loc.first.is_visible(timeout=700):
                    disabled = (loc.first.get_attribute("aria-disabled") or "").lower() == "true"
                    cls = loc.first.get_attribute("class") or ""
                    if disabled or "disabled" in cls.lower():
                        return False
                    loc.first.click()
                    self._safe_wait_networkidle(page, timeout=10000)
                    return True
            except Exception:
                continue
        return False

    def _abs_url(self, base: str, href: str) -> str:
        return urljoin(base, href)


    # --- JAVASCRIPT DOWNLOAD ADAPTER METHODS RESTORED ---

    def _capture_runtime_download_url(self, page: Page, element: Locator, click_url: str) -> str | None:
        page.evaluate('''() => {
            window.__smartofficeOriginalOpen = window.open;
            window.open = function(name, url) {
                window.__smartofficeCapturedDownloadUrl = url;
            };
        }''')
        try:
            self._click_attachment_element(page, element, click_url)
            captured = page.evaluate("() => window.__smartofficeCapturedDownloadUrl")
            return captured
        except Exception as e:
            raise RuntimeError(str(e))
        finally:
            page.evaluate('''() => {
                if (window.__smartofficeCapturedDownloadUrl !== undefined) {
                    delete window.__smartofficeCapturedDownloadUrl;
                }
                window.open = window.__smartofficeOriginalOpen;
            }''')

    def _validate_captured_download_url(self, captured: str, detail_url: str) -> str:
        if not captured or captured.startswith("javascript:") or captured.startswith("about:blank") or captured.startswith("http://"):
            raise RuntimeError("CAPTURED_DOWNLOAD_URL_INVALID")
            
        from urllib.parse import urlparse, urljoin
        absolute = urljoin(detail_url, captured)
        parsed = urlparse(absolute)
        
        if parsed.scheme != "https":
            raise RuntimeError("CAPTURED_DOWNLOAD_URL_INVALID")
            
        
        if parsed.hostname.lower() not in QLVB_ALLOWED_HOSTS:
            raise RuntimeError("UNEXPECTED_DOWNLOAD_HOST")
            
        # FIX for QC-004: use endswith instead of exact match
        valid_path = any(parsed.path.endswith(p) for p in QLVB_DOWNLOAD_ALL_PATHS)
        if not valid_path:
            raise RuntimeError("UNEXPECTED_DOWNLOAD_PATH")
            
        return absolute

    def _click_attachment_element(self, page: Page, element: Locator, href: str) -> None:
        try:
            element.click(timeout=self.config.browser.timeout_ms)
        except Exception:
            element.evaluate("el => el.click()")

    def _validate_downloaded_file(self, path: Path, response_headers: dict) -> None:
        data = path.read_bytes()
        if b"<!DOCTYPE html>" in data and b"password" in data:
            raise RuntimeError("DOWNLOADED_HTML_LOGIN_PAGE|SESSION_EXPIRED")
            
        import zipfile
        import io
        is_zip = path.suffix.lower() == ".zip" or response_headers.get("content-type") == "application/zip"
        is_docx = path.suffix.lower() == ".docx"
        
        if is_zip or is_docx:
            if not data.startswith(b"PK"):
                raise RuntimeError("DOWNLOADED_FILE_INVALID")
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    if len(zf.infolist()) == 0:
                        raise RuntimeError("DOWNLOADED_ZIP_INVALID" if is_zip else "DOWNLOADED_FILE_INVALID")
                    if is_docx:
                        names = zf.namelist()
                        if "[Content_Types].xml" not in names and "word/document.xml" not in names:
                            raise RuntimeError("DOWNLOADED_FILE_INVALID")
            except zipfile.BadZipFile:
                raise RuntimeError("DOWNLOADED_FILE_INVALID")

    def _extract_zip_bundle(self, record, zip_path: Path) -> list[Path]:
        import zipfile
        extracted = []
        with zipfile.ZipFile(zip_path, "r") as zf:
            for i, info in enumerate(zf.infolist()):
                if ".." in info.filename or info.filename.startswith("/"):
                    raise RuntimeError("ZIP_SLIP_DETECTED")
                content = zf.read(info)
                out_name = f"{i+1:02d}_{Path(info.filename).name}"
                out_path = zip_path.parent / out_name
                out_path.write_bytes(content)
                extracted.append(out_path)
        return extracted

    def trigger_qlvb_attachment_download(self, page: Page, element: Locator, record, click_url: str, att_idx: int, timeout_seconds: int = 15) -> Path:
        captured = self._capture_runtime_download_url(page, element, click_url)
        absolute = self._validate_captured_download_url(captured, page.url)
        
        response = page.context.request.get(absolute, headers={"Referer": page.url}, timeout=timeout_seconds * 1000)
        if not response.ok:
            raise RuntimeError(f"HTTP {response.status}")
            
        filename = self._filename_from_response(absolute, response.headers, att_idx)
        target = self.storage.next_download_path(record, filename, att_idx)
        target.write_bytes(response.body())
        
        self._validate_downloaded_file(target, response.headers)
        
        return target

    def _save_page_error(self, page: Page, name: str, extra: dict | None = None) -> None:
        html = None
        screenshot = None
        debug = {"url": getattr(page, "url", ""), "time": now_iso()}
        if extra:
            debug.update(extra)
        if self.config.download.save_source_html_on_error:
            try:
                html = page.content()
            except Exception:
                html = None
        if self.config.download.save_screenshot_on_error:
            try:
                screenshot = page.screenshot(full_page=True)
            except Exception:
                screenshot = None
        artifact = self.storage.write_error_artifact(name, html=html, screenshot_bytes=screenshot, extra=debug)
        self.logger.error("Da luu hien trang loi %s: %s", name, artifact)
