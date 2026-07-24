from __future__ import annotations

import json
import re
import hashlib
import time
import traceback
import unicodedata
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlparse, urlunparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import Locator, Page, sync_playwright

from .config import QLVBConfig, VERSION
from .logger import build_logger
from .models import (
    ATTACHMENT_DOWNLOAD_FAILED,
    ATTACHMENT_DOWNLOAD_STARTED,
    ATTACHMENT_DOWNLOADED_RAW,
    ATTACHMENT_INVALID_FILE,
    ATTACHMENT_VALIDATED,
    DOCUMENT_FAILED,
    DOCUMENT_NO_VALID_ATTACHMENT,
    DOCUMENT_PROCESSING,
    DOCUMENT_QUEUEABLE_STATUSES,
    DOCUMENT_READY,
    DOCUMENT_READY_WITH_WARNINGS,
    DOCUMENT_SESSION_EXPIRED,
    AttachmentInfo,
    DocumentRecord,
    mask_url_query,
    now_iso,
)
from .parser import attachment_from_anchor, build_record_from_row, clean_text, guess_date, is_probable_attachment
from .neoremoting import (
    NeoRemotingAttachmentDiscoveryAdapter,
    NeoRemotingDiscoveryError,
    extract_document_id,
)
from .storage import StorageManager
from .report import append_csv_report, write_html_run_report
from .paths import configure_bundled_playwright


QLVB_ALLOWED_HOSTS = {"qlvb.laichau.gov.vn"}
QLVB_DOWNLOAD_ALL_PATHS = ["/smartoffice/jbm/download_all.jsp"]
MAX_INCOMING_REGISTRY_ROWS = 10
QLVB_INCOMING_REGISTRY_MARKER = "DEN_CAN_VAO_SO"
QLVB_INCOMING_REGISTRY_LABEL = "Văn bản vào sổ"
QLVB_INCOMING_PENDING_LABEL = "Văn bản đến chờ xử lý"
QLVB_INCOMING_PROCESSED_LABEL = "Văn bản đến đã xử lý"
CATEGORY_ORDER = ("incoming_registry", "incoming_forwarded_processed", "incoming_processed")
CATEGORY_ROUTE_MARKERS = {
    "incoming_registry": {
        "IyLlCc5f5w5fCES.": "DBny4Y9y4B1V4ctk3yPbCY9aDz5Y3yPbCY9fCcPbUo..",
        "CBAkTA9f5o..": "m2268",
        "4c9lTFLwDctm": "2",
        "6yXl": "DEN_CAN_VAO_SO",
        "TFbm5B5xCcLw6B9k": "0",
    },
    "incoming_forwarded_processed": {
        "IyLlCc5f5w5fCES.": "DBny4Y9y4B1V4ctk3yPbCY9aDz5Y3yPbCY9fCcPbUo..",
        "CBAkTA9f5o..": "m2270",
        "4c9lTFLwDctm": "2",
        "6yXl": "DEN_HE_THONG",
        "TFbm5B5xCcLw6B9k": "0",
    },
    "incoming_processed": {
        "IyLlCc5f5w5fCES.": "DBny4Y9y4B1V4ctk3yPbCY9aDz5Y3yPbCY9fCcPbUo..",
        "CBAkTA9f5o..": "m2289",
        "4c9lTFLwDctm": "2",
        "6yXl": "DEN_DA_XU_LY",
        "TFbm5B5xCcLw6B9k": "0",
    },
}


def classify_download_body_prefix(data: bytes) -> str:
    """Classify a response from a bounded prefix without exposing body content."""
    if not data:
        return "EMPTY"
    if data.startswith(b"%PDF-"):
        return "PDF"
    if data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "OLE_OFFICE"
    if data.startswith(b"PK"):
        return "DOCX_XLSX_PPTX_ZIP"
    if data.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"II*\x00", b"MM\x00*")):
        return "IMAGE"
    prefix = data[:4096].lstrip().lower()
    if prefix.startswith((b"<!doctype html", b"<html", b"<form")):
        return "HTML"
    if prefix.startswith((b"{", b"[")):
        return "JSON"
    try:
        text = data[:4096].decode("utf-8")
        printable = sum(char.isprintable() or char in "\r\n\t" for char in text)
        if text and printable / len(text) >= 0.95:
            return "TEXT"
    except UnicodeDecodeError:
        pass
    return "UNKNOWN_BINARY"
QLVB_INCOMING_LABEL = "V\u0103n b\u1ea3n \u0111\u1ebfn"
QLVB_OUTGOING_LABEL = "V\u0103n b\u1ea3n \u0111i"

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
        self._last_incoming_registry_menu_clicked = False
        self.primary_qlvb_page: Page | None = None
        self.browser_context = None
        self.browser = None
        self.protected_pages: set[Page] = set()
        self._blank_page_context_ids: set[int] = set()
        self._blank_page_detected_ids: set[int] = set()
        self._blank_page_closed_ids: set[int] = set()
        self._download_in_progress = False
        self._last_download_event_at = 0.0
        self._protected_page_skip_count = 0
        self._already_closed_page_skip_count = 0

    def _note_download_event(self, _download=None) -> None:
        self._last_download_event_at = time.monotonic()

    def _blank_cleanup_download_guarded(self) -> bool:
        return self._download_in_progress or time.monotonic() - self._last_download_event_at < 2.0

    def _inspect_and_close_spurious_blank(self, candidate: Page, *, grace_ms: int = 1000) -> bool:
        # R18: about:blank is observational only and is never closed.
        try:
            if candidate.is_closed():
                self._already_closed_page_skip_count += 1
            elif str(candidate.url or "") == "about:blank":
                self._blank_page_detected_ids.add(id(candidate))
        except Exception:
            pass
        return False

    def _cleanup_spurious_blank_pages(
        self,
        *,
        primary_qlvb_page: Page | None = None,
        grace_ms: int = 1000,
    ) -> int:
        primary = primary_qlvb_page or self.primary_qlvb_page
        if primary is None:
            return 0
        self.primary_qlvb_page = primary
        self.protected_pages.add(primary)
        primary_closed_before = True
        try:
            primary_closed_before = primary.is_closed()
        except Exception:
            pass
        closed = 0
        try:
            pages_snapshot = list(primary.context.pages)
        except Exception:
            return 0
        blank_candidates = 0
        for candidate in pages_snapshot:
            if candidate is primary or candidate in self.protected_pages:
                self._protected_page_skip_count += 1
                continue
            try:
                if not candidate.is_closed() and str(candidate.url or "") == "about:blank":
                    blank_candidates += 1
            except Exception:
                pass
            self._inspect_and_close_spurious_blank(candidate, grace_ms=0)
        try:
            primary_closed_after = primary.is_closed()
            page_count_after = len(primary.context.pages)
        except Exception:
            primary_closed_after = True
            page_count_after = "UNKNOWN"
        self.run_summary["blank_pages"] = {
            "detected_count": len(self._blank_page_detected_ids),
            "closed_count": len(self._blank_page_closed_ids),
            "primary_qlvb_page_preserved": "PASS" if not primary_closed_after else "FAIL",
            "primary_page_object_preserved": self.primary_qlvb_page is primary,
            "primary_page_closed_before_cleanup": primary_closed_before,
            "primary_page_closed_after_cleanup": primary_closed_after,
            "page_count_before_cleanup": len(pages_snapshot),
            "page_count_after_cleanup": page_count_after,
            "blank_page_candidate_count": blank_candidates,
            "protected_page_skip_count": self._protected_page_skip_count,
            "already_closed_page_skip_count": self._already_closed_page_skip_count,
        }
        return closed

    def _register_blank_page_monitor(self, primary: Page) -> None:
        """Record page/context ownership without registering a page-closing callback."""
        self.primary_qlvb_page = primary
        self.protected_pages.add(primary)
        try:
            context = primary.context
        except Exception:
            return
        self.browser_context = context

    def ensure_primary_qlvb_page(self, context, current_primary: Page | None) -> tuple[Page, bool]:
        """Keep the current primary, or reacquire one uniquely valid QLVB page."""
        if current_primary is not None:
            try:
                if not current_primary.is_closed():
                    self._register_blank_page_monitor(current_primary)
                    return current_primary, False
            except Exception:
                pass
        candidates: list[Page] = []
        try:
            pages_snapshot = list(context.pages)
        except Exception as exc:
            raise RuntimeError("PRIMARY_QLVB_PAGE_CLOSED_AND_NOT_RECOVERABLE") from exc
        for candidate in pages_snapshot:
            try:
                parsed = urlparse(candidate.url or "")
                if (
                    not candidate.is_closed()
                    and parsed.hostname == "qlvb.laichau.gov.vn"
                    and parsed.path == "/qlvbdh_lcu/main"
                    and self._is_primary_qlvb_page(candidate)
                ):
                    candidates.append(candidate)
            except Exception:
                continue
        if len(candidates) != 1:
            raise RuntimeError("PRIMARY_QLVB_PAGE_CLOSED_AND_NOT_RECOVERABLE")
        primary = candidates[0]
        self._register_blank_page_monitor(primary)
        self.run_summary["primary_page_reacquired"] = "YES"
        return primary, True

    def resolve_active_qlvb_page(
        self,
        browser_context,
        expected_category: str | None,
        current_page: Page | None = None,
        timeout_seconds: float | None = None,
    ) -> Page:
        """Poll every browser context for a verified QLVB page; never use tab order."""
        error_code = (
            "SOURCE_QLVB_PAGE_NOT_FOUND_BEFORE_CATEGORY_CLICK_TIMEOUT"
            if expected_category is None
            else "TARGET_QLVB_PAGE_NOT_FOUND_AFTER_CATEGORY_CLICK_TIMEOUT"
        )
        if browser_context is None:
            raise RuntimeError(error_code)
        browser = self.browser
        if browser is None:
            try:
                browser = browser_context.browser
            except Exception:
                browser = None
        if browser is not None:
            self.browser = browser
        wait_seconds = timeout_seconds if timeout_seconds is not None else (10.0 if expected_category is None else 15.0)
        started_at = time.monotonic()
        deadline = started_at + wait_seconds
        best_page: Page | None = None
        best_score = -1
        context_count_max = 0
        page_count_max = 0
        zero_page_observation_count = 0
        qlvb_candidate_count = 0
        while time.monotonic() < deadline:
            try:
                contexts_snapshot = list(browser.contexts) if browser is not None else [browser_context]
            except Exception as exc:
                raise RuntimeError(error_code) from exc
            context_count_max = max(context_count_max, len(contexts_snapshot))
            pages_snapshot = []
            for context in contexts_snapshot:
                try:
                    pages_snapshot.extend(list(context.pages))
                except Exception:
                    continue
            page_count_max = max(page_count_max, len(pages_snapshot))
            if not pages_snapshot:
                zero_page_observation_count += 1
                time.sleep(0.2)
                continue
            best_page = None
            best_score = -1
            for candidate in pages_snapshot:
                try:
                    if candidate.is_closed():
                        continue
                    parsed = urlparse(candidate.url or "")
                    if parsed.scheme in {"about", "blob", "file"}:
                        continue
                    if parsed.hostname != "qlvb.laichau.gov.vn" or parsed.path != "/qlvbdh_lcu/main":
                        continue
                    qlvb_candidate_count += 1
                    if not self._is_logged_in(candidate):
                        continue
                    if expected_category is None:
                        navigation = self._has_qlvb_navigation(candidate)
                        account = self._has_qlvb_account_context(candidate)
                        if not navigation or not account:
                            continue
                        score = 4 + (1 if candidate is current_page else 0)
                    else:
                        route = self._validate_incoming_category_route(candidate, expected_category)
                        category_signal = bool(route.get("breadcrumb") or route.get("active_menu"))
                        if not category_signal:
                            continue
                        table = self._find_document_table(candidate, allow_fallback=False)
                        content_signal = table is not None or self._has_empty_document_state(candidate)
                        if not content_signal:
                            continue
                        score = sum(bool(route.get(key)) for key in (
                            "host", "route_marker", "breadcrumb", "active_menu", "title", "valid"
                        )) + 2
                    if score > best_score:
                        best_page = candidate
                        best_score = score
                    elif score == best_score:
                        best_page = None
                except Exception:
                    continue
            if best_page is not None:
                old_primary = self.primary_qlvb_page
                self.primary_qlvb_page = best_page
                try:
                    self.browser_context = best_page.context
                except Exception:
                    self.browser_context = browser_context
                try:
                    best_page.bring_to_front()
                except Exception:
                    time.sleep(0.25)
                    if best_page.is_closed():
                        best_page = None
                        continue
                    best_page.bring_to_front()
                self.run_summary["active_page"] = {
                    "old_page_closed": bool(old_primary is not None and old_primary.is_closed()),
                    "active_qlvb_page_reacquired": "YES",
                    "active_qlvb_page_host_valid": "YES",
                    "active_qlvb_page_category_valid": "YES",
                    "about_blank_page_count": sum(
                        1 for page in pages_snapshot
                        if not page.is_closed() and str(page.url or "") == "about:blank"
                    ),
                    "about_blank_ignored": "YES",
                    "wait_duration_ms": int((time.monotonic() - started_at) * 1000),
                    "context_count_max": context_count_max,
                    "page_count_max": page_count_max,
                    "zero_page_observation_count": zero_page_observation_count,
                    "qlvb_candidate_count": qlvb_candidate_count,
                }
                return best_page
            time.sleep(0.2)
        self.run_summary["active_page"] = {
            "wait_duration_ms": int((time.monotonic() - started_at) * 1000),
            "context_count_max": context_count_max,
            "page_count_max": page_count_max,
            "zero_page_observation_count": zero_page_observation_count,
            "qlvb_candidate_count": qlvb_candidate_count,
            "about_blank_ignored": "YES",
        }
        raise RuntimeError(error_code)

    def _register_page_event_signals(self, browser_context) -> list[dict]:
        """Register non-owning wake signals; callbacks never select or close a page."""
        browser = self.browser
        if browser is None:
            try:
                browser = browser_context.browser
            except Exception:
                browser = None
        try:
            contexts_snapshot = list(browser.contexts) if browser is not None else [browser_context]
        except Exception:
            contexts_snapshot = [browser_context]
        signals: list[dict] = []
        for context in contexts_snapshot:
            signal = {"page_event_count": 0}
            try:
                context.on("page", lambda _page, state=signal: state.__setitem__(
                    "page_event_count", state["page_event_count"] + 1
                ))
                signals.append(signal)
            except Exception:
                continue
        return signals

    def open_category_resilient(
        self,
        browser_context,
        current_page: Page | None,
        target_category: str,
    ) -> Page:
        """Resolve a live QLVB page before and after the category click."""
        if self.browser is None:
            try:
                self.browser = browser_context.browser
            except Exception:
                self.browser = None
        live_page = self.resolve_active_qlvb_page(
            browser_context,
            expected_category=None,
            current_page=current_page,
        )
        if live_page.is_closed():
            raise RuntimeError("SOURCE_QLVB_PAGE_NOT_FOUND_BEFORE_CATEGORY_CLICK_TIMEOUT")
        page_event_signals = self._register_page_event_signals(browser_context)
        self.open_incoming_category(live_page, target_category, resolve_after_click=False)
        target_page = self.resolve_active_qlvb_page(
            browser_context,
            expected_category=target_category,
            current_page=None,
            timeout_seconds=15.0,
        )
        self.run_summary.setdefault("active_page", {})["page_event_signal_count"] = sum(
            int(signal.get("page_event_count", 0)) for signal in page_event_signals
        )
        return target_page

    @staticmethod
    def _is_safe_blank_page(page: Page) -> bool:
        try:
            url = (page.url or "").lower()
            return url == "about:blank" or url.startswith("chrome://newtab")
        except Exception:
            return False

    def _select_bootstrap_page(self, context) -> Page:
        """Avoid treating an incidental blank tab as the working QLVB page."""
        for candidate in context.pages:
            try:
                if not candidate.is_closed() and not self._is_safe_blank_page(candidate):
                    return candidate
            except Exception:
                continue
        return context.pages[0] if context.pages else context.new_page()

    def _has_qlvb_navigation(self, page: Page) -> bool:
        try:
            menu = page.locator("#full_menu")
            return menu.count() > 0 and "quan ly van ban den" in self._navigation_key(
                menu.inner_text(timeout=1500)
            )
        except Exception:
            return False

    def _has_qlvb_account_context(self, page: Page) -> bool:
        try:
            header = page.locator(
                "header, #header, .login-info, #login-info, .user-info, #user-info, "
                ".account-info, #account-info, .user-profile, .profile-user-info"
            )
            for index in range(min(header.count(), 20)):
                if header.nth(index).inner_text(timeout=1000).strip():
                    return True

            logout = page.locator(
                "a:has-text('Đăng xuất'), button:has-text('Đăng xuất'), "
                "a:has-text('Thoát'), button:has-text('Thoát'), "
                "[href*='logout' i], [onclick*='logout' i], "
                "[href*='dangxuat' i], [onclick*='dangxuat' i]"
            )
            for index in range(min(logout.count(), 20)):
                control = logout.nth(index)
                container = control.locator("xpath=ancestor::*[self::li or self::div][1]")
                if container.count() and len(clean_text(container.first.inner_text(timeout=1000))) > 5:
                    return True
            return False
        except Exception:
            return False

    def _is_primary_qlvb_page(self, page: Page) -> bool:
        try:
            parsed = urlparse(page.url or "")
            return bool(
                not page.is_closed()
                and not self._is_safe_blank_page(page)
                and parsed.hostname == "qlvb.laichau.gov.vn"
                and self._is_logged_in(page)
                and self._has_qlvb_navigation(page)
                and self._has_qlvb_account_context(page)
            )
        except Exception:
            return False

    def select_primary_qlvb_page(self, context) -> tuple[Page, dict[str, object]]:
        """Select the authenticated QLVB tab and close only confirmed blank tabs."""
        diagnostics: dict[str, object] = {
            "browser_page_count": len(context.pages),
            "blank_page_detected": "NO",
            "blank_page_closed": "NO",
            "primary_qlvb_page_selected": "FAIL",
            "primary_page_url_valid": "FAIL",
        }
        primary = None
        blank_pages: list[Page] = []
        deadline = time.monotonic() + 10
        while primary is None and time.monotonic() < deadline:
            blank_pages = []
            for candidate in list(context.pages):
                if self._is_safe_blank_page(candidate):
                    diagnostics["blank_page_detected"] = "YES"
                    blank_pages.append(candidate)
                    continue
                if primary is None and self._is_primary_qlvb_page(candidate):
                    primary = candidate
            if primary is None:
                time.sleep(0.25)

        if primary is None:
            for candidate in list(context.pages):
                if self._is_safe_blank_page(candidate):
                    continue
                parsed = urlparse(candidate.url or "")
                self.logger.warning(
                    "PRIMARY_PAGE_DIAGNOSTIC host_valid=%s logged_in=%s navigation=%s account_context=%s",
                    parsed.hostname == "qlvb.laichau.gov.vn",
                    self._is_logged_in(candidate),
                    self._has_qlvb_navigation(candidate),
                    self._has_qlvb_account_context(candidate),
                )
            raise RuntimeError("PRIMARY_QLVB_PAGE_NOT_FOUND")

        self._register_blank_page_monitor(primary)
        for blank_page in blank_pages:
            if self._inspect_and_close_spurious_blank(blank_page, grace_ms=1000):
                diagnostics["blank_page_closed"] = "YES"
        diagnostics["primary_qlvb_page_selected"] = "PASS"
        diagnostics["primary_page_url_valid"] = "PASS"
        diagnostics["spurious_blank_page_detected_count"] = len(self._blank_page_detected_ids)
        diagnostics["spurious_blank_page_closed_count"] = len(self._blank_page_closed_ids)
        diagnostics["browser_page_count"] = len(context.pages)
        return primary, diagnostics

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
            self.browser_context = context
            self.browser = context.browser
            context.set_default_timeout(self.config.browser.timeout_ms)
            page = self._select_bootstrap_page(context)
            try:
                self._ensure_logged_in(page, headless_value=headless_value)
                page, page_diagnostics = self.select_primary_qlvb_page(context)
                self.run_summary["browser_pages"] = page_diagnostics
                if login_only:
                    self.logger.info("Dang nhap thanh cong va da luu phien.")
                    self.run_summary["status"] = "DONE"
                    self.run_summary["login_status"] = "ÄÄƒng nháº­p thÃ nh cÃ´ng"
                else:
                    incoming_requested = "incoming" in set(directions)
                    if incoming_requested:
                        global_processed += self._run_incoming_registry_workflow(
                            page,
                            max_items_value,
                            use_fixed_urls=self.config.use_fixed_urls,
                        )
                    if not self.config.use_fixed_urls:
                        for direction in directions:
                            if direction != "outgoing":
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
                self._download_in_progress = False
                context.close()

        self.run_summary["finished_at"] = now_iso()
        summary_path = self.storage.log_root / "qlvb_downloader_last_run_summary.json"
        self.storage.write_json(summary_path, self.run_summary)
        if self.config.download.export_html_report:
            write_html_run_report(self.storage.log_root / "qlvb_downloader_last_run_report.html", self.run_summary, self.report_rows)
        self.logger.info("Hoan thanh. Summary: %s", summary_path)
        return self.run_summary

    def run_cdp_three_category_smoke(self, *, output_dir: Path | None = None) -> dict:
        """Run the externally authenticated CDP workflow without owning the browser."""
        from .cdp_workflow import run_cdp_three_category_smoke

        return run_cdp_three_category_smoke(self.config, output_dir=output_dir)

    def _run_incoming_registry_workflow(self, page: Page, max_items: int, use_fixed_urls: bool) -> int:
        self.logger.info("CATEGORY_ORDER: INCOMING_REGISTRY,FORWARDED_PROCESSED,PROCESSED")
        self.logger.info("PENDING_USED_IN_DEFAULT_WORKFLOW: NO")
        total_processed = 0
        controlled_limit = max(1, min(int(max_items or 1), 3))
        self.primary_qlvb_page = page
        self.run_summary["r14_known_good_workflow_restored"] = "YES"
        self.run_summary["r15_to_r21_experimental_flow_used"] = "NO"
        self.run_summary["blank_page_left_untouched"] = "YES"
        self.run_summary["single_automation_page_used"] = "NO"
        self.run_summary["direct_category_navigation_used"] = "NO"
        self.run_summary["category_route_dom_discovery_used"] = "NO"
        self.run_summary["category_menu_click_used"] = "YES"
        self.run_summary["page_reacquisition_used"] = "NO"
        self.run_summary["blank_page_cleanup_used"] = "NO"
        for category in CATEGORY_ORDER:
            if total_processed >= controlled_limit:
                break
            self.logger.info("REQUESTED_CATEGORY: %s", category.upper())
            result = self._process_direction(
                page,
                "incoming",
                min(1, controlled_limit - total_processed),
                fixed_url="",
                category=category,
                planner=False,
                knowledge=True,
            )
            self.run_summary["directions"][category] = result
            prefix = {
                "incoming_registry": "INCOMING_REGISTRY",
                "incoming_forwarded_processed": "FORWARDED_PROCESSED",
                "incoming_processed": "PROCESSED",
            }[category]
            self.logger.info("%s_DOCUMENT_COUNT: %s", prefix, result.get("document_count", 0))
            self.logger.info("%s_ROWS_SCANNED: %s", prefix, result.get("rows_scanned", 0))
            self.logger.info("%s_VALID_DOCUMENT_IDS: %s", prefix, result.get("document_ids_validated", 0))
            self.logger.info("%s_INVALID_RESPONSE_COUNT: %s", prefix, result.get("invalid_response_count", 0))
            self.logger.info("%s_ROWS_WITH_ATTACHMENTS: %s", prefix, result.get("rows_with_attachments", 0))
            if result.get("downloaded_files", 0) > 0:
                result["category_result"] = "DOWNLOADED"
                self.run_summary["selected_category"] = prefix
                self.logger.info("%s_RESULT: DOWNLOADED", prefix)
                total_processed += result.get("processed", 0)
                continue
            result["category_result"] = "EXHAUSTED_NO_DOWNLOADABLE_DOCUMENT"
            self.logger.info("%s_RESULT: EXHAUSTED_NO_DOWNLOADABLE_DOCUMENT", prefix)
            if result.get("status") in {DOCUMENT_SESSION_EXPIRED, "FAILED"}:
                error = str(result.get("error") or "")
                fatal_tokens = ("SESSION", "AUTH", "ACCESS_DENIED", "CAPTCHA", "WRONG_QLVB_HOST", "LOGIN_REDIRECT", "SECURITY")
                if any(token in error.upper() for token in fatal_tokens):
                    raise RuntimeError(error)
            total_processed += result.get("processed", 0)
        return total_processed

    @staticmethod
    def build_category_url(authenticated_base_url: str, markers: dict[str, str]) -> str:
        parsed = urlparse(authenticated_base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname != "qlvb.laichau.gov.vn"
            or parsed.path != "/qlvbdh_lcu/main"
        ):
            raise RuntimeError("AUTHENTICATED_BASE_URL_INVALID")
        query_items = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query_items.update(markers)
        return urlunparse(parsed._replace(query=urlencode(query_items)))

    def run_same_page_incoming_registry_smoke(self, authenticated_page: Page) -> dict:
        """Navigate the authenticated tab itself to Incoming Registry; no popup or download."""
        try:
            if authenticated_page is None or authenticated_page.is_closed():
                raise RuntimeError("AUTHENTICATED_PAGE_CLOSED_BEFORE_DIRECT_NAVIGATION")
            authenticated_base_url = str(authenticated_page.url or "")
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError("AUTHENTICATED_PAGE_CLOSED_BEFORE_DIRECT_NAVIGATION") from exc
        parsed = urlparse(authenticated_base_url)
        if parsed.hostname != "qlvb.laichau.gov.vn" or parsed.path != "/qlvbdh_lcu/main":
            raise RuntimeError("AUTHENTICATED_PAGE_INVALID_BEFORE_DIRECT_NAVIGATION")
        incoming_registry_url = self.build_category_url(
            authenticated_base_url,
            CATEGORY_ROUTE_MARKERS["incoming_registry"],
        )
        try:
            authenticated_page.goto(
                incoming_registry_url,
                wait_until="domcontentloaded",
                timeout=30000,
            )
        except Exception as exc:
            try:
                if authenticated_page.is_closed():
                    raise RuntimeError("AUTHENTICATED_PAGE_CLOSED_DURING_DIRECT_NAVIGATION") from exc
            except RuntimeError:
                raise
            raise
        if authenticated_page.is_closed():
            raise RuntimeError("AUTHENTICATED_PAGE_CLOSED_DURING_DIRECT_NAVIGATION")
        if not self._is_logged_in(authenticated_page):
            raise RuntimeError("AUTH_SESSION_NOT_PRESERVED_ON_AUTHENTICATED_PAGE")
        route = self._validate_incoming_category_route(authenticated_page, "incoming_registry")
        if not route.get("valid"):
            raise RuntimeError("INCOMING_REGISTRY_ROUTE_NOT_VALIDATED")
        table = self._wait_for_validated_document_table(authenticated_page, allow_fallback=False)
        empty_state = False if table is not None else self._has_empty_document_state(authenticated_page)
        if table is None and not empty_state:
            raise RuntimeError("INCOMING_REGISTRY_TABLE_OR_EMPTY_STATE_NOT_VALIDATED")
        return {
            "new_automation_page_used": "NO",
            "authenticated_page_reused": "YES",
            "authenticated_page_open_before_goto": "YES",
            "direct_goto_on_authenticated_page": "PASS",
            "auth_session_preserved": "PASS",
            "incoming_registry_route_validated": "PASS",
            "incoming_registry_breadcrumb_validated": "PASS" if route.get("breadcrumb") else "FAIL",
            "incoming_registry_table_or_empty_state_validated": "PASS",
        }

    def discover_incoming_category_routes(self, authenticated_page: Page) -> dict[str, str]:
        """Read only the three incoming-category routes from the authenticated menu DOM."""
        expected_labels = {
            "incoming_registry": QLVB_INCOMING_REGISTRY_LABEL,
            "incoming_forwarded_processed": "Đã chuyển xử lý",
            "incoming_processed": "Đã xử lý",
        }
        routes: dict[str, str] = {}
        base_url = str(authenticated_page.url or "")
        base = urlparse(base_url)
        if base.hostname != "qlvb.laichau.gov.vn" or base.path != "/qlvbdh_lcu/main":
            raise RuntimeError("CATEGORY_ROUTE_SOURCE_PAGE_INVALID")
        for scope in [authenticated_page, *getattr(authenticated_page, "frames", [])]:
            try:
                links = scope.locator("#full_menu a, #full_menu [role='menuitem']")
                incoming_parent = None
                for index in range(min(links.count(), 250)):
                    candidate = links.nth(index)
                    text = self._navigation_key(clean_text(candidate.inner_text(timeout=400)))
                    if text == "quan ly van ban den":
                        incoming_parent = candidate.locator("xpath=ancestor::li[1]")
                        break
                if incoming_parent is None:
                    continue
                items = incoming_parent.locator("a, [role='menuitem']")
                for index in range(min(items.count(), 100)):
                    item = items.nth(index)
                    text = self._navigation_key(clean_text(item.inner_text(timeout=400)))
                    for category, label in expected_labels.items():
                        expected = self._navigation_key(label)
                        if category in routes or not (
                            text == expected or text.startswith(expected + " ") or text.startswith(expected + "(")
                        ):
                            continue
                        route = self._extract_category_route_from_menu_item(item, base_url)
                        if route:
                            routes[category] = route
            except Exception:
                continue
        missing = [category for category in CATEGORY_ORDER if category not in routes]
        if missing:
            raise RuntimeError("CATEGORY_ROUTE_MAP_INCOMPLETE:" + ",".join(missing))
        if "DEN_CAN_VAO_SO" not in routes["incoming_registry"]:
            raise RuntimeError("INCOMING_REGISTRY_ROUTE_MARKER_MISSING")
        self.run_summary["category_routes"] = {category: "VALIDATED" for category in CATEGORY_ORDER}
        return routes

    def _extract_category_route_from_menu_item(self, item: Locator, base_url: str) -> str:
        values = []
        for attribute in ("href", "data-url", "data-href", "data-link", "onclick"):
            try:
                value = (item.get_attribute(attribute) or "").strip()
            except Exception:
                value = ""
            if value:
                values.append((attribute, value))
        base = urlparse(base_url)
        for attribute, raw_value in values:
            candidates = [raw_value]
            if attribute == "onclick":
                candidates = re.findall(
                    r"(?:https?://[^\s'\"]+|/qlvbdh_lcu/main\?[^'\"\s;)]+|qlvbdh_lcu/main\?[^'\"\s;)]+)",
                    raw_value,
                    flags=re.IGNORECASE,
                )
            for candidate in candidates:
                if candidate.casefold().startswith(("javascript:", "about:", "blob:")):
                    continue
                absolute = urljoin(base_url, candidate)
                parsed = urlparse(absolute)
                if (
                    parsed.scheme in {"http", "https"}
                    and parsed.scheme == base.scheme
                    and parsed.hostname == "qlvb.laichau.gov.vn"
                    and parsed.netloc == base.netloc
                    and parsed.path == "/qlvbdh_lcu/main"
                    and parsed.query
                ):
                    return absolute
        return ""

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
                page = self._select_bootstrap_page(context)
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
                empty_texts = [
                    "khÃ´ng tÃ¬m tháº¥y dá»¯ liá»‡u", "khÃ´ng cÃ³ dá»¯ liá»‡u",
                    "khÃ´ng cÃ³ báº£n ghi", "no data available", "khÃ´ng cÃ³ vÄƒn báº£n",
                    "kh\u00f4ng t\u00ecm th\u1ea5y d\u1eef li\u1ec7u", "kh\u00f4ng c\u00f3 d\u1eef li\u1ec7u",
                    "kh\u00f4ng c\u00f3 b\u1ea3n ghi", "kh\u00f4ng c\u00f3 v\u0103n b\u1ea3n",
                ]
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
                breadcrumb_l = breadcrumb.lower()
                is_incoming = (
                    "vÄƒn báº£n Ä‘áº¿n" in breadcrumb_l
                    or QLVB_INCOMING_LABEL.lower() in breadcrumb_l
                    or "van_ban_den" in url.lower()
                )
                is_outgoing = (
                    "vÄƒn báº£n Ä‘i" in breadcrumb_l
                    or QLVB_OUTGOING_LABEL.lower() in breadcrumb_l
                    or "vanban_di" in url.lower()
                )
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
                        "message": "Link há»£p lá»‡, hiá»‡n chÆ°a cÃ³ dá»¯ liá»‡u",
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
                return {"valid": False, "error": f"Lá»—i khÃ´ng xÃ¡c Ä‘á»‹nh: {e}"}
            finally:
                context.close()

    def _validate_config(self) -> None:
        missing = []
        if not (self.config.qlvb_base_url or self.config.login_url or getattr(self.config, 'incoming_url', '') or getattr(self.config, 'outgoing_url', '') or self.config.incoming_registry_url or self.config.incoming_pending_url):
            missing.append("Ä‘á»‹a chá»‰/link QLVB")
        if not self.config.username:
            missing.append("tÃªn Ä‘Äƒng nháº­p")
        if not self.config.password and not self.config.browser.allow_manual_login:
            missing.append("máº­t kháº©u")
        if missing:
            raise ValueError("Thiáº¿u cáº¥u hÃ¬nh: " + ", ".join(missing))

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
        for value in (self.config.qlvb_base_url, self.config.login_url, getattr(self.config, 'incoming_url', ''), getattr(self.config, 'outgoing_url', ''), self.config.incoming_registry_url, self.config.incoming_pending_url):
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
        # Sá»­ dá»¥ng URL lÃ m má»“i (náº¿u lÃ  Lai ChÃ¢u bá»‹ cáº¥u hÃ¬nh thiáº¿u /qlvbdh_lcu/main thÃ¬ bÃ¹ vÃ o)
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
            if self._wait_manual_login(page, probe_url, reason="Trang Ä‘Äƒng nháº­p cÃ³ CAPTCHA/OTP", headless_value=headless_value):
                return
            raise RuntimeError("Trang Ä‘Äƒng nháº­p cÃ³ CAPTCHA/OTP. Vui lÃ²ng cháº¡y hiá»‡n trÃ¬nh duyá»‡t, Ä‘Äƒng nháº­p thá»§ cÃ´ng má»™t láº§n rá»“i cháº¡y láº¡i Ä‘á»ƒ dÃ¹ng phiÃªn Ä‘Ã£ lÆ°u.")

        if not username or not password:
            self._save_page_error(page, "login_fields_not_found")
            if self._wait_manual_login(page, probe_url, reason="KhÃ´ng tÃ¬m tháº¥y Ã´ tÃ i khoáº£n/máº­t kháº©u", headless_value=headless_value):
                return
            raise RuntimeError("KhÃ´ng tÃ¬m tháº¥y Ã´ tÃªn Ä‘Äƒng nháº­p/máº­t kháº©u. Cáº§n cáº­p nháº­t selector sau khi xem log/screenshot.")

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
            if self._wait_manual_login(page, probe_url, reason="ÄÄƒng nháº­p tá»± Ä‘á»™ng chÆ°a thÃ nh cÃ´ng", headless_value=headless_value):
                return
            raise RuntimeError("ÄÄƒng nháº­p chÆ°a thÃ nh cÃ´ng. Kiá»ƒm tra tÃ i khoáº£n, máº­t kháº©u, CAPTCHA/OTP hoáº·c selector.")
        self.logger.info("Dang nhap thanh cong, phien trinh duyet da duoc luu.")
        self._update_dynamic_urls(page)

    def _wait_manual_login(self, page: Page, probe_url: str, reason: str, headless_value: bool) -> bool:
        if headless_value or not self.config.browser.allow_manual_login:
            return False
        wait_seconds = max(10, int(self.config.browser.manual_login_wait_seconds or 120))
        self.logger.warning("%s. Cho phep dang nhap thu cong trong %s giay. Sáº¿p Ä‘Äƒng nháº­p xong, tool sáº½ tá»± kiá»ƒm tra láº¡i.", reason, wait_seconds)
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            try:
                if self._is_logged_in(page):
                    self.logger.info("Da phat hien dang nhap thu cong thanh cong.")
                    self._update_dynamic_urls(page)
                    return True
                # Äá»‹nh ká»³ thá»­ má»Ÿ láº¡i link Ä‘Ã­ch; náº¿u phiÃªn Ä‘Ã£ cÃ³ cookie thÃ¬ sáº½ vÃ o tháº³ng danh sÃ¡ch.
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
        try:
            if page.is_closed():
                return False
        except Exception:
            return False
        login_selectors = self.config.selectors["login"]
        # During a CAPTCHA submit the login controls can briefly be hidden.
        # Presence in the DOM is therefore a stronger negative signal than
        # visibility; otherwise the login page title itself ("Quan ly van
        # ban...") can be mistaken for authenticated application content.
        for selector in login_selectors["password"]:
            try:
                if page.locator(selector).count() > 0:
                    return False
            except Exception:
                continue
        if self._count_visible(page, login_selectors["password"]) > 0:
            return False
        if self._count_visible(page, login_selectors.get("logged_in_markers", [])) > 0:
            return True
        try:
            body = clean_text(page.locator("body").inner_text(timeout=5000)) if page.locator("body").count() else ""
        except Exception:
            body = ""
        login_words = ["Ä‘Äƒng nháº­p", "dang nhap", "login", "máº­t kháº©u", "mat khau", "password"]
        list_words = [
            "vÄƒn báº£n Ä‘áº¿n", "van ban den", "vÄƒn báº£n Ä‘i", "van ban di",
            "trÃ­ch yáº¿u", "so van ban", "sá»‘ vÄƒn báº£n",
            QLVB_INCOMING_LABEL.lower(), QLVB_OUTGOING_LABEL.lower(),
            "tr\u00edch y\u1ebfu", "s\u1ed1 v\u0103n b\u1ea3n",
        ]
        body_l = body.lower()
        if any(w in body_l for w in login_words):
            return False
        if any(w in body_l for w in list_words):
            return True
        return False

    def _detect_captcha(self, page: Page) -> bool:
        return self._count_visible(page, self.config.selectors["login"].get("captcha", [])) > 0

    def open_document_direction(self, page: Page, direction: str) -> Page:
        if direction not in {"incoming", "outgoing"}:
            raise ValueError(f"Unsupported direction: {direction}")
        label = "VÄƒn báº£n Ä‘áº¿n" if direction == "incoming" else "VÄƒn báº£n Ä‘i"
        label_candidates = [label]
        unicode_label = QLVB_INCOMING_LABEL if direction == "incoming" else QLVB_OUTGOING_LABEL
        if unicode_label not in label_candidates:
            label_candidates.append(unicode_label)
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
            selector
            for candidate_label in label_candidates
            for selector in (
                f"a:has-text('{candidate_label}')",
                f"button:has-text('{candidate_label}')",
                f"[role='menuitem']:has-text('{candidate_label}')",
                f"[onclick]:has-text('{candidate_label}')",
            )
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
                # This is the generic incoming/outgoing navigator.  The stricter
                # main-content-only table gate belongs to the incoming-registry
                # workflow after its host/route/breadcrumb/menu checks pass.
                table = self._find_document_table(target_page, allow_fallback=True)
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
                    if "vÄƒn báº£n" not in text.lower() and "van ban" not in text.lower() and not onclick and not href:
                        continue
                    kind = "javascript" if href.startswith("javascript:") else "hash" if href.startswith("#") else "http" if self._is_http_url(href) else "relative" if href else "none"
                    elements.append({"text": text, "href_kind": kind, "onclick": onclick})
            except Exception:
                continue
        return {"frame_urls": frames, "navigation_elements": elements[:300]}

    def open_incoming_category(
        self,
        page: Page,
        category: str,
        *,
        resolve_after_click: bool = True,
    ) -> Page:
        """Open a stable incoming menu item when no verified fixed URL is configured."""
        if page is None:
            raise RuntimeError("PRIMARY_QLVB_PAGE_CLOSED_BEFORE_CATEGORY_NAVIGATION")
        try:
            if page.is_closed():
                raise RuntimeError("PRIMARY_QLVB_PAGE_CLOSED_BEFORE_CATEGORY_NAVIGATION")
            parsed_page = urlparse(page.url or "")
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError("PRIMARY_QLVB_PAGE_CLOSED_BEFORE_CATEGORY_NAVIGATION") from exc
        if parsed_page.hostname != "qlvb.laichau.gov.vn" or parsed_page.path != "/qlvbdh_lcu/main":
            raise RuntimeError("PRIMARY_QLVB_PAGE_INVALID_BEFORE_CATEGORY_NAVIGATION")
        labels = {
            "incoming_registry": QLVB_INCOMING_REGISTRY_LABEL,
            "incoming_forwarded_processed": "Đã chuyển xử lý",
            "incoming_processed": "Đã xử lý",
            "incoming_pending": "Chờ xử lý",
        }
        label = labels.get(category)
        if not label:
            raise ValueError(f"Unsupported incoming category: {category}")
        self._last_incoming_registry_menu_clicked = False
        for scope in [page, *getattr(page, "frames", [])]:
            try:
                group_probe = self._probe_exact_incoming_menu(scope, label, click=False)
                print("MENU_GROUP_FOUND: " + ("YES" if group_probe.get("group_found") else "NO"))
                print("MENU_CANDIDATE_COUNT: " + str(group_probe.get("candidate_count", 0)))
                print("MENU_CANDIDATE_TEXT: " + str(group_probe.get("candidate_text", "")))
                print("MENU_CANDIDATE_IN_EXPECTED_GROUP: " + ("YES" if group_probe.get("candidate_in_expected_group") else "NO"))
                print("MENU_CANDIDATE_IS_VISIBLE: " + ("YES" if group_probe.get("candidate_is_visible") else "NO"))
                print("MENU_CANDIDATE_IS_NAVIGATION_ITEM: " + ("YES" if group_probe.get("candidate_is_navigation_item") else "NO"))
                print("RAW_TEXT_MATCH_COUNT: " + str(group_probe.get("raw_text_match_count", 0)))
                print("ACTIONABLE_ANCESTOR_COUNT: " + str(group_probe.get("actionable_ancestor_count", 0)))
                print("DEDUPED_ACTIONABLE_COUNT: " + str(group_probe.get("deduped_actionable_count", 0)))
                print("VISIBLE_ACTIONABLE_COUNT: " + str(group_probe.get("visible_actionable_count", 0)))
                print("EXPECTED_GROUP_ACTIONABLE_COUNT: " + str(group_probe.get("expected_group_actionable_count", 0)))
                print("MENU_GROUP_EXPAND_REQUIRED: " + ("YES" if group_probe.get("menu_group_expand_required") else "NO"))
                print("MENU_GROUP_EXPAND_CLICKED: " + ("YES" if group_probe.get("menu_group_expand_clicked") else "NO"))
                print("MENU_RESCAN_PERFORMED: " + ("YES" if group_probe.get("menu_rescan_performed") else "NO"))
                print("MENU_ACTIONABLE_FINGERPRINTS: " + str(group_probe.get("candidate_fingerprints", "")))
                if not group_probe.get("group_found"):
                    continue
                if int(group_probe.get("expected_group_actionable_count", 0) or 0) == 0:
                    raise RuntimeError("CATEGORY_MENU_ACTIONABLE_TARGET_NOT_FOUND")
                if (
                    int(group_probe.get("deduped_actionable_count", 0) or 0) != 1
                    or int(group_probe.get("visible_actionable_count", 0) or 0) != 1
                    or int(group_probe.get("expected_group_actionable_count", 0) or 0) != 1
                ):
                    raise RuntimeError("CATEGORY_MENU_ACTIONABLE_TARGET_AMBIGUOUS")
                clicked = self._probe_exact_incoming_menu(scope, label, click=True)
                if not clicked.get("clicked"):
                    raise RuntimeError("CATEGORY_MENU_ACTIONABLE_TARGET_NOT_FOUND")
                if category == "incoming_registry":
                    self._last_incoming_registry_menu_clicked = True
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=5000)
                except Exception:
                    page.wait_for_timeout(500)
                active_text = self._diagnostic_route_texts(page).get("active_menu", "")
                if "thong tin xu ly van ban" in active_text:
                    raise RuntimeError("WRONG_MENU_TARGET_CLICKED")
                if not resolve_after_click:
                    return page
                route_after_click = self._validate_incoming_category_route(page, category)
                if route_after_click.get("breadcrumb") or route_after_click.get("active_menu") or route_after_click.get("title"):
                    return page
                browser_context = self.browser_context
                if browser_context is None:
                    raise RuntimeError("SOURCE_QLVB_PAGE_NOT_FOUND_BEFORE_CATEGORY_CLICK_TIMEOUT")
                time.sleep(0.5)
                return self.resolve_active_qlvb_page(
                    browser_context,
                    category,
                    current_page=page,
                )
            except RuntimeError:
                raise
            except Exception:
                if not resolve_after_click:
                    try:
                        if page.is_closed():
                            raise RuntimeError("PRIMARY_QLVB_PAGE_CLOSED_DURING_CATEGORY_NAVIGATION")
                    except RuntimeError:
                        raise
                    except Exception:
                        pass
                    continue
                try:
                    if page.is_closed():
                        return self.resolve_active_qlvb_page(self.browser_context, category)
                except RuntimeError:
                    raise
                except Exception:
                    pass
                continue
        raise RuntimeError("INCOMING_CATEGORY_MENU_NOT_FOUND")

    @staticmethod
    def _strict_menu_probe_script() -> str:
        return r"""async ({expectedLabel, click}) => {
            const normalize = (value) => String(value || '')
                .normalize('NFD')
                .replace(/[\u0300-\u036f]/g, '')
                .replace(/đ/g, 'd')
                .replace(/Đ/g, 'D')
                .toLowerCase()
                .replace(/\s+/g, ' ')
                .trim();
            const stripCount = (value) => normalize(value).replace(/\s*\(\s*\d+\s*\)\s*$/g, '').trim();
            const rectOk = (el) => {
                const rect = el && el.getBoundingClientRect ? el.getBoundingClientRect() : {width: 0, height: 0};
                return rect.width > 0 && rect.height > 0;
            };
            const hasHiddenAncestor = (el) => {
                for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
                    const tag = String(node.tagName || '').toLowerCase();
                    if (tag === 'template') return true;
                    if (node.getAttribute('aria-hidden') === 'true') return true;
                    const style = window.getComputedStyle(node);
                    if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) return true;
                }
                return false;
            };
            const isVisible = (el) => !!(el && el.isConnected && !hasHiddenAncestor(el) && rectOk(el));
            const inExcludedSurface = (el) => !!el.closest('main, #content, #main-content, .main-content, .modal, .popup, [role="dialog"], table, tr, td, th, template');
            const isNav = (el) => {
                const tag = String(el.tagName || '').toLowerCase();
                return tag === 'a' || tag === 'button' || el.getAttribute('role') === 'menuitem'
                    || !!el.getAttribute('href') || !!el.getAttribute('onclick') || !!el.getAttribute('data-url')
                    || !!el.getAttribute('data-href') || !!el.getAttribute('data-link');
            };
            const actionableFrom = (textNode, group) => {
                let node = textNode;
                for (let depth = 0; node && depth <= 6; depth += 1, node = node.parentElement) {
                    if (!node || node === group.parentElement || inExcludedSurface(node)) continue;
                    if (isNav(node)) return node;
                    const tag = String(node.tagName || '').toLowerCase();
                    if (tag === 'li') {
                        const direct = Array.from(node.children || []).find(child => isNav(child) && !inExcludedSurface(child));
                        if (direct) return direct;
                    }
                }
                return null;
            };
            const safeSig = (el) => {
                const tag = String(el.tagName || '').toLowerCase();
                const cls = String(el.getAttribute('class') || '').split(/\s+/).filter(Boolean).slice(0, 4).join('.');
                const id = el.getAttribute('id') ? '[ID]' : '';
                const role = el.getAttribute('role') || '';
                return [tag, id, cls, role, el.getAttribute('href') ? 'href' : '', el.getAttribute('onclick') ? 'onclick' : '', el.getAttribute('data-url') || el.getAttribute('data-href') || el.getAttribute('data-link') ? 'data' : ''].filter(Boolean).join('|');
            };
            const fingerprint = (raw, action, group) => ({
                raw_text_node_tag: String(raw.tagName || '').toLowerCase(),
                actionable_ancestor_tag: String(action.tagName || '').toLowerCase(),
                ancestor_id_class: (action.getAttribute('id') ? '[ID]' : '') + ' ' + String(action.getAttribute('class') || '').slice(0, 120),
                href_present: action.getAttribute('href') ? 'YES' : 'NO',
                onclick_present: action.getAttribute('onclick') ? 'YES' : 'NO',
                data_url_present: (action.getAttribute('data-url') || action.getAttribute('data-href') || action.getAttribute('data-link')) ? 'YES' : 'NO',
                role: action.getAttribute('role') || '',
                visible: isVisible(action) ? 'YES' : 'NO',
                bounding_box_nonzero: rectOk(action) ? 'YES' : 'NO',
                inside_expected_sidebar: group.contains(action) ? 'YES' : 'NO',
                inside_modal: action.closest('.modal, .popup, [role="dialog"]') ? 'YES' : 'NO',
                inside_main_content: action.closest('main, #content, #main-content, .main-content') ? 'YES' : 'NO',
                inside_hidden_ancestor: hasHiddenAncestor(action) ? 'YES' : 'NO',
                actionable_signature: safeSig(action),
            });
            const roots = Array.from(document.querySelectorAll('#full_menu, nav, aside, .sidebar, .main-sidebar, .side-menu, .nav-menu, ul[role="menu"]'));
            const expected = stripCount(expectedLabel);
            let groupFound = false;
            let groupHeader = null;
            let groupNode = null;
            const scan = () => {
                let rawMatches = [];
                let actions = [];
                let fingerprints = [];
                for (const root of roots) {
                if (!isVisible(root) || inExcludedSurface(root)) continue;
                const groups = Array.from(root.querySelectorAll('li, [role="group"], ul'));
                for (const group of groups) {
                    if (inExcludedSurface(group)) continue;
                    const direct = Array.from(group.querySelectorAll(':scope > a, :scope > button, :scope > span, :scope > div, :scope > [role="menuitem"], :scope > [onclick]'))
                        .find(child => stripCount(child.innerText || child.textContent || '') === 'quan ly van ban den');
                    if (!direct) continue;
                    groupFound = true;
                    groupHeader = groupHeader || direct;
                    groupNode = groupNode || group;
                    const textNodes = Array.from(group.querySelectorAll('a, button, span, label, div, li, [role="menuitem"], [onclick], [href], [data-url], [data-href], [data-link]'));
                    for (const raw of textNodes) {
                        if (raw === direct || inExcludedSurface(raw)) continue;
                        const text = stripCount(raw.innerText || raw.textContent || '');
                        if (text !== expected) continue;
                        rawMatches.push(raw);
                        const action = actionableFrom(raw, group);
                        if (!action) continue;
                        actions.push({
                            element: action,
                            raw,
                            text,
                            visible: isVisible(action),
                            inExpectedGroup: group.contains(action),
                            navigation: isNav(action),
                        });
                    }
                }
            }
                const seen = new WeakSet();
                const deduped = [];
                for (const item of actions) {
                    if (seen.has(item.element)) continue;
                    seen.add(item.element);
                    deduped.push(item);
                    fingerprints.push(fingerprint(item.raw, item.element, groupNode || item.element));
                }
                const visible = deduped.filter(item => item.visible && item.navigation);
                const expectedGroup = visible.filter(item => item.inExpectedGroup);
                return {rawMatches, actions, deduped, visible, expectedGroup, fingerprints};
            };
            let result = scan();
            let expandRequired = result.visible.length === 0 && !!groupHeader;
            let expandClicked = false;
            let rescan = false;
            if (expandRequired && groupHeader && isVisible(groupHeader)) {
                const headerAction = actionableFrom(groupHeader, groupNode || groupHeader) || groupHeader;
                if (isNav(headerAction) || String(headerAction.tagName || '').toLowerCase() !== 'span') {
                    try { headerAction.click(); expandClicked = true; } catch (_) {}
                    await new Promise(resolve => setTimeout(resolve, 800));
                    result = scan();
                    rescan = true;
                }
            }
            const candidates = result.expectedGroup;
            if (click && result.deduped.length === 1 && result.visible.length === 1 && result.expectedGroup.length === 1) {
                candidates[0].element.click();
                return {group_found: groupFound, candidate_count: 1, clicked: true, candidate_text: candidates[0].text, candidate_in_expected_group: true, candidate_is_visible: true, candidate_is_navigation_item: true,
                    raw_text_match_count: result.rawMatches.length, actionable_ancestor_count: result.actions.length, deduped_actionable_count: result.deduped.length,
                    visible_actionable_count: result.visible.length, expected_group_actionable_count: result.expectedGroup.length,
                    menu_group_expand_required: expandRequired, menu_group_expand_clicked: expandClicked, menu_rescan_performed: rescan,
                    candidate_fingerprints: JSON.stringify(result.fingerprints.slice(0, 5))};
            }
            return {
                group_found: groupFound,
                candidate_count: result.expectedGroup.length,
                clicked: false,
                candidate_text: candidates.map(item => item.text).join('|'),
                candidate_in_expected_group: candidates.length === 1 ? candidates[0].inExpectedGroup : false,
                candidate_is_visible: candidates.length === 1 ? candidates[0].visible : false,
                candidate_is_navigation_item: candidates.length === 1 ? candidates[0].navigation : false,
                raw_text_match_count: result.rawMatches.length,
                actionable_ancestor_count: result.actions.length,
                deduped_actionable_count: result.deduped.length,
                visible_actionable_count: result.visible.length,
                expected_group_actionable_count: result.expectedGroup.length,
                menu_group_expand_required: expandRequired,
                menu_group_expand_clicked: expandClicked,
                menu_rescan_performed: rescan,
                candidate_fingerprints: JSON.stringify(result.fingerprints.slice(0, 5)),
            };
        }"""

    def _probe_exact_incoming_menu(self, scope, label: str, *, click: bool = False) -> dict:
        return scope.evaluate(self._strict_menu_probe_script(), {"expectedLabel": label, "click": click})

    def run_incoming_menu_smoke(self, page: Page) -> dict:
        page = self.open_incoming_category(page, "incoming_registry", resolve_after_click=False)
        route = self._validate_incoming_category_route(page, "incoming_registry")
        active_text = self._diagnostic_route_texts(page).get("active_menu", "")
        if "thong tin xu ly van ban" in active_text:
            raise RuntimeError("WRONG_MENU_TARGET_CLICKED")
        if not route.get("route_marker"):
            raise RuntimeError("INCOMING_REGISTRY_ROUTE_MARKER_MISSING")
        if not route.get("breadcrumb"):
            raise RuntimeError("INCOMING_REGISTRY_BREADCRUMB_MISMATCH")
        if not route.get("active_menu"):
            raise RuntimeError("INCOMING_REGISTRY_MENU_NOT_ACTIVE")
        table = self._wait_for_validated_document_table(page, allow_fallback=False)
        empty = self._has_empty_document_state(page)
        if table is None and not empty:
            raise RuntimeError("INCOMING_REGISTRY_TABLE_OR_EMPTY_STATE_NOT_VALIDATED")
        return {
            "incoming_registry_route_validated": "PASS",
            "incoming_registry_breadcrumb_validated": "PASS",
            "incoming_registry_active_menu_validated": "PASS",
            "incoming_registry_table_or_empty_state_validated": "PASS",
        }

    def _fallback_to_incoming_registry_route(self, page: Page) -> Page:
        """Reuse only the authenticated in-memory URL while setting the Registry marker."""
        parsed = urlparse(page.url or "")
        if parsed.hostname != "qlvb.laichau.gov.vn":
            raise RuntimeError("WRONG_QLVB_HOST")
        query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key != "6yXl"]
        query.append(("6yXl", QLVB_INCOMING_REGISTRY_MARKER))
        route_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(query), ""))
        self.logger.info("ROUTE_HOST: %s", parsed.hostname)
        self.logger.info("ROUTE_PATH: %s", parsed.path)
        self.logger.info("ROUTE_CATEGORY_MARKER: %s", QLVB_INCOMING_REGISTRY_MARKER)
        self._goto(page, route_url, "fallback incoming registry route")
        return page

    @staticmethod
    def _navigation_key(value: str) -> str:
        normalized = unicodedata.normalize("NFD", value or "")
        compact = "".join(char for char in normalized if unicodedata.category(char) != "Mn").casefold()
        return compact.replace("đ", "d")

    def _validate_incoming_category_route(self, page: Page, category: str) -> dict[str, bool]:
        """Validate breadcrumb, active menu and title before inspecting a document table."""
        category_terms = {
            "incoming_registry": ("van ban vao so",),
            "incoming_forwarded_processed": ("da chuyen xu ly",),
            "incoming_pending": ("van ban den cho xu ly", "cho xu ly"),
            "incoming_processed": ("van ban den da xu ly", "da xu ly"),
        }
        expected_terms = category_terms.get(category)
        if expected_terms is None:
            raise ValueError(f"Unsupported incoming category: {category}")
        selectors = {
            "breadcrumb": [".breadcrumb", ".page-breadcrumb", "[aria-label*='breadcrumb' i]"],
            "active_menu": ["[aria-current='page']", ".active", ".selected", ".current"],
            "title": ["h1", "h2", ".page-title", ".nav-title"],
        }
        result: dict[str, bool] = {key: False for key in selectors}
        parsed = urlparse(page.url or "")
        result["host"] = parsed.hostname == "qlvb.laichau.gov.vn"
        result["route_marker"] = category != "incoming_registry" or any(
            key == "6yXl" and value == QLVB_INCOMING_REGISTRY_MARKER
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        )
        try:
            page_title = clean_text(page.title())
            result["title"] = any(term in self._navigation_key(page_title) for term in expected_terms)
        except Exception:
            pass
        scopes = [page, *getattr(page, "frames", [])]
        for key, candidates in selectors.items():
            if result[key]:
                continue
            for scope in scopes:
                for selector in candidates:
                    try:
                        locator = scope.locator(selector)
                        for index in range(min(locator.count(), 20)):
                            text = clean_text(locator.nth(index).inner_text(timeout=300))
                            normalized_text = self._navigation_key(text)
                            if any(term in normalized_text for term in expected_terms):
                                result[key] = True
                                break
                    except Exception:
                        continue
                    if result[key]:
                        break
                if result[key]:
                    break
        if category == "incoming_registry":
            try:
                breadcrumb = page.locator(".breadcrumb, .page-breadcrumb, [aria-label*='breadcrumb' i]").all_inner_texts()
                breadcrumb_text = self._navigation_key(" ".join(clean_text(value) for value in breadcrumb))
                result["breadcrumb"] = "quan ly van ban den" in breadcrumb_text and "van ban vao so" in breadcrumb_text
            except Exception:
                result["breadcrumb"] = False
        # Live QLVB carries the route marker in the query string. Local/unit DOM
        # fixtures can have no query at all, so accept breadcrumb+active menu only
        # after this process has just clicked the exact incoming menu node.
        marker_valid = result["route_marker"] or (
            not parsed.query and bool(getattr(self, "_last_incoming_registry_menu_clicked", False))
        )
        result["valid"] = result["host"] and marker_valid and result["breadcrumb"] and result["active_menu"]
        return result

    def _row_scoped_attachment_fallback(self, page: Page, rec: DocumentRecord) -> list[AttachmentInfo]:
        """Use only a selected row's direct HTTP(S) Files links when NeoRemoting is absent."""
        try:
            table = self._find_document_table(page, allow_fallback=False)
            if not table:
                return []
            row_index = int(rec.metadata.get("row_locator_index", -1))
            rows = table.locator("tbody tr")
            if row_index < 0 or row_index >= rows.count():
                return []
            row = rows.nth(row_index)
            selected_id = str(rec.metadata.get("source_document_id") or "")
            attachments: list[AttachmentInfo] = []
            seen: set[str] = set()
            anchors = row.locator("a[href]")
            for index in range(min(anchors.count(), 20)):
                anchor = anchors.nth(index)
                href = (anchor.get_attribute("href") or "").strip()
                if not href or href.lower().startswith("javascript:"):
                    continue
                action_id = extract_document_id(
                    attributes={key: anchor.get_attribute(key) or "" for key in ("data-document-id", "data-doc-id", "data-vb-id", "data-id")},
                    row_id=anchor.get_attribute("id") or "",
                    onclick=anchor.get_attribute("onclick") or "",
                    href=href,
                )
                if action_id is not None and action_id.document_id != selected_id:
                    continue
                info = attachment_from_anchor(page.url, clean_text(anchor.inner_text(timeout=750)), href)
                if not info or info.href in seen:
                    continue
                seen.add(info.href)
                info.source_method = "ROW_SCOPED_FILES_FALLBACK"
                attachments.append(info)
            return attachments
        except Exception:
            return []

    def _probe_incoming_row_attachments(self, page: Page, rec: DocumentRecord) -> bool:
        """Probe one validated row only; a Files icon is never a selection gate."""
        source_document_id = str(rec.metadata.get("source_document_id") or "")
        if not source_document_id:
            return False
        adapter = NeoRemotingAttachmentDiscoveryAdapter(
            self.config.qlvb_base_url or page.url,
            timeout_ms=self.config.browser.timeout_ms,
        )
        try:
            rec.attachments = adapter.discover(
                getattr(self, "_current_table_scope", None) or page,
                document_id=source_document_id,
                category=rec.source_category or rec.direction,
                correlation_id=self.run_id,
            )
            rec.metadata["attachment_discovery_method"] = "NEOREMOTING"
            return True
        except NeoRemotingDiscoveryError as exc:
            rec.metadata["neoremoting_error"] = exc.code
            if exc.code == "NO_ATTACHMENTS":
                return False
            if exc.code in {"SESSION_EXPIRED", "NEOREMOTING_SESSION_EXPIRED", "NEOREMOTING_ACCESS_DENIED"}:
                raise RuntimeError(exc.code) from exc
            if not exc.fallback_allowed:
                raise RuntimeError(exc.code) from exc
            rec.attachments = self._row_scoped_attachment_fallback(page, rec)
            rec.metadata["attachment_discovery_method"] = "ROW_SCOPED_FILES_FALLBACK"
            return bool(rec.attachments)

    def _select_first_incoming_row_with_attachments(self, page: Page, records: list[DocumentRecord], result: dict) -> DocumentRecord | None:
        """Try at most ten table rows in order and stop at the first verified attachment list."""
        result["rows_scanned"] = 0
        result["document_ids_validated"] = 0
        result["rows_with_attachments"] = 0
        result["selected_row_index"] = None
        result["selected_document_id"] = None
        for rec in records[:MAX_INCOMING_REGISTRY_ROWS]:
            result["rows_scanned"] += 1
            source_document_id = str(rec.metadata.get("source_document_id") or "")
            if not source_document_id:
                continue
            result["document_ids_validated"] += 1
            rec.source_category = rec.source_category or "incoming_registry"
            if not self._probe_incoming_row_attachments(page, rec):
                if rec.metadata.get("neoremoting_error") == "NEOREMOTING_INVALID_RESPONSE":
                    result["invalid_response_count"] += 1
                continue
            result["rows_with_attachments"] += 1
            result["selected_row_index"] = rec.row_index
            result["selected_document_id"] = source_document_id
            result["attachment_discovery_method"] = rec.metadata.get("attachment_discovery_method", "NONE")
            # Controlled R14 acceptance: one document contributes at most its
            # first safely parsed attachment.
            rec.attachments = rec.attachments[:1]
            result["attachment_count"] = len(rec.attachments)
            return rec
        return None

    def _has_empty_document_state(self, page: Page) -> bool:
        """Detect a list empty state without inspecting links, actions, or arbitrary page content."""
        markers = (
            "Kh\u00f4ng t\u00ecm th\u1ea5y d\u1eef li\u1ec7u",
            "Kh\u00f4ng c\u00f3 d\u1eef li\u1ec7u",
            "Kh\u00f4ng c\u00f3 b\u1ea3n ghi",
            "No data available",
        )
        selectors = [
            "#content #table-vb #div_data_list",
            "#content .empty", "#content .no-data", "#content .empty-state", "#content .k-grid-norecords",
            "#content #div_data_list", "#content td", "#content [role='status']",
        ]
        try:
            main_list_text = page.evaluate(
                """() => {
                    const root = document.querySelector('#content #table-vb');
                    return root && root.offsetParent !== null ? (root.innerText || '') : '';
                }"""
            )
            if any(marker.casefold() in clean_text(main_list_text).casefold() for marker in markers):
                return True
        except Exception:
            pass
        scopes = [page, *getattr(page, "frames", [])]
        for scope in scopes:
            for selector in selectors:
                try:
                    locator = scope.locator(selector)
                    for index in range(min(locator.count(), 250)):
                        if not locator.nth(index).is_visible(timeout=200):
                            continue
                        text = clean_text(locator.nth(index).inner_text(timeout=300))
                        if any(marker.casefold() in text.casefold() for marker in markers):
                            return True
                except Exception:
                    continue
        return False

    def _wait_for_validated_document_table(self, page: Page, allow_fallback: bool) -> Locator | None:
        """Wait only for the category content to render a valid table or its explicit empty state."""
        deadline = time.monotonic() + min(15, max(3, self.config.browser.timeout_ms / 1000))
        while time.monotonic() < deadline:
            table = self._find_document_table(page, allow_fallback=allow_fallback)
            if table is not None or self._has_empty_document_state(page):
                return table
            try:
                page.wait_for_timeout(250)
            except Exception:
                break
        return None

    def _safe_normalized_text(self, value: str, limit: int = 240) -> str:
        return self._navigation_key(clean_text(value or ""))[:limit]

    def _diagnostic_empty_state_text(self, page: Page) -> str:
        markers = (
            "Khong tim thay du lieu",
            "Khong co du lieu",
            "Khong co ban ghi",
            "No data available",
        )
        try:
            text = self._safe_normalized_text(page.evaluate(
                """() => {
                    const root = document.querySelector('#content #table-vb, #content, main, body');
                    return root && root.offsetParent !== null ? (root.innerText || '') : '';
                }"""
            ), 2000)
        except Exception:
            return ""
        for marker in markers:
            normalized = self._safe_normalized_text(marker)
            if normalized and normalized in text:
                return normalized
        return ""

    def _diagnostic_route_texts(self, page: Page) -> dict[str, str]:
        result = {"breadcrumb": "", "active_menu": ""}
        try:
            texts = page.locator(".breadcrumb, .page-breadcrumb, [aria-label*='breadcrumb' i]").all_inner_texts()
            result["breadcrumb"] = self._safe_normalized_text(" / ".join(texts))
        except Exception:
            pass
        try:
            texts = page.locator("[aria-current='page'], .active, .selected, .current").all_inner_texts()
            result["active_menu"] = self._safe_normalized_text(" / ".join(texts))
        except Exception:
            pass
        return result

    def _diagnostic_table_candidates(self, page: Page) -> tuple[list[dict], str]:
        script = """() => {
            const tableSelector = 'table';
            const tables = Array.from(document.querySelectorAll(tableSelector)).slice(0, 20);
            const visible = el => !!(el && (el.offsetParent || el.getClientRects().length));
            return tables.map((table, index) => {
                const headers = Array.from(table.querySelectorAll('thead th, tr th'))
                    .map(th => (th.innerText || '').trim())
                    .filter(Boolean)
                    .slice(0, 20);
                const tbodyRows = Array.from(table.querySelectorAll('tbody tr'));
                const attrs = Array.from(table.attributes || []).map(attr => attr.name).sort();
                const cls = String(table.getAttribute('class') || '').slice(0, 160);
                const idValue = table.getAttribute('id') ? '[PRESENT]' : '';
                return {
                    index,
                    selector: table.id ? 'table#' + table.id : (cls ? 'table.' + cls.split(/\\s+/).filter(Boolean).slice(0, 3).join('.') : 'table'),
                    id: idValue,
                    class: cls,
                    attribute_names: attrs,
                    headers,
                    all_tr_count: table.querySelectorAll('tr').length,
                    thead_tr_count: table.querySelectorAll('thead tr').length,
                    tbody_tr_count: tbodyRows.length,
                    visible_tbody_tr_count: tbodyRows.filter(visible).length,
                };
            });
        }"""
        try:
            candidates = page.evaluate(script) or []
        except Exception:
            candidates = []
        try:
            main_found = page.evaluate("() => !!document.querySelector('main, #content, #main-content, .main-content, #div_data_list')")
        except Exception:
            main_found = False
        for item in candidates:
            item["headers_normalized"] = [self._safe_normalized_text(header) for header in item.get("headers", [])]
            item.pop("headers", None)
        return candidates, "YES" if main_found else "NO"

    def _diagnostic_row_shape(self, row: Locator) -> dict:
        try:
            attrs = row.evaluate("el => Array.from(el.attributes || []).map(attr => attr.name).sort()")
        except Exception:
            attrs = []
        try:
            cell_count = row.locator("td, th").count()
        except Exception:
            cell_count = 0
        try:
            cls = row.get_attribute("class") or ""
        except Exception:
            cls = ""
        return {
            "tag": "tr",
            "class": cls[:160],
            "cell_count": cell_count,
            "attribute_names": attrs,
        }

    def _diagnostic_rows(self, page: Page, table: Locator | None, headers: list[str]) -> dict:
        counters = {
            "all_tr_count": 0,
            "thead_tr_count": 0,
            "tbody_tr_count": 0,
            "visible_tbody_tr_count": 0,
            "data_row_count_before_filter": 0,
            "data_row_count_after_filter": 0,
            "row_skip_header_count": 0,
            "row_skip_hidden_count": 0,
            "row_skip_empty_count": 0,
            "row_skip_insufficient_cells_count": 0,
            "row_skip_non_document_count": 0,
            "row_skip_other_count": 0,
            "document_id_source_candidate_count": 0,
            "document_id_valid_count": 0,
            "document_id_invalid_count": 0,
            "document_id_source_locations": {
                "row_attributes": 0,
                "row_id": 0,
                "files_cell_href": 0,
                "onclick": 0,
                "data_attributes": 0,
            },
            "sample_row_shape": {},
        }
        if table is None:
            return counters
        try:
            counters["all_tr_count"] = table.locator("tr").count()
            counters["thead_tr_count"] = table.locator("thead tr").count()
            rows = table.locator("tbody tr")
            counters["tbody_tr_count"] = rows.count()
        except Exception:
            return counters
        for index in range(counters["tbody_tr_count"]):
            row = rows.nth(index)
            try:
                if not row.is_visible(timeout=200):
                    counters["row_skip_hidden_count"] += 1
                    continue
                counters["visible_tbody_tr_count"] += 1
                row_text = clean_text(row.inner_text(timeout=500))
                cells = [clean_text(value) for value in row.locator("td, th").all_inner_texts()]
                cells = [cell for cell in cells if cell]
                if not counters["sample_row_shape"]:
                    counters["sample_row_shape"] = self._diagnostic_row_shape(row)
                counters["data_row_count_before_filter"] += 1
                if not row_text or self._is_empty_row(row_text):
                    counters["row_skip_empty_count"] += 1
                    continue
                if self._is_header_row(row, row_text, cells, headers):
                    counters["row_skip_header_count"] += 1
                    continue
                if len(cells) <= 1 and len(row_text) < 15:
                    counters["row_skip_insufficient_cells_count"] += 1
                    continue
                detail_metadata = {"detail_action_index": self._extract_detail_action_index(row)}
                source_locations = counters["document_id_source_locations"]
                row_attr_names = ("data-document-id", "data-doc-id", "data-vb-id", "data-id")
                row_attr_candidates = sum(1 for key in row_attr_names if row.get_attribute(key))
                if row_attr_candidates:
                    source_locations["row_attributes"] += row_attr_candidates
                    source_locations["data_attributes"] += row_attr_candidates
                if row.get_attribute("id"):
                    source_locations["row_id"] += 1
                if row.get_attribute("onclick"):
                    source_locations["onclick"] += 1
                try:
                    actions = row.locator("a, button, [onclick], [data-url], [data-href]")
                    for action_index in range(min(actions.count(), 40)):
                        action = actions.nth(action_index)
                        if action.get_attribute("href") or action.get_attribute("data-url") or action.get_attribute("data-href"):
                            source_locations["files_cell_href"] += 1
                        if action.get_attribute("onclick"):
                            source_locations["onclick"] += 1
                        for key in row_attr_names:
                            if action.get_attribute(key):
                                source_locations["data_attributes"] += 1
                except Exception:
                    pass
                candidate_count = sum(int(value) for value in source_locations.values())
                before_valid = counters["document_id_valid_count"]
                source_id = self._extract_source_document_id(row, page.url, detail_metadata)
                if source_id is not None:
                    counters["document_id_valid_count"] += 1
                counters["document_id_source_candidate_count"] = max(
                    counters["document_id_source_candidate_count"],
                    candidate_count,
                )
                counters["data_row_count_after_filter"] += 1
                if counters["document_id_valid_count"] == before_valid and candidate_count > 0:
                    counters["document_id_invalid_count"] += 1
            except Exception:
                counters["row_skip_other_count"] += 1
        total_skipped = (
            counters["row_skip_header_count"]
            + counters["row_skip_hidden_count"]
            + counters["row_skip_empty_count"]
            + counters["row_skip_insufficient_cells_count"]
            + counters["row_skip_non_document_count"]
            + counters["row_skip_other_count"]
        )
        if counters["data_row_count_before_filter"] > counters["data_row_count_after_filter"] + total_skipped:
            counters["row_skip_other_count"] += counters["data_row_count_before_filter"] - counters["data_row_count_after_filter"] - total_skipped
        if counters["document_id_source_candidate_count"] > counters["document_id_valid_count"]:
            counters["document_id_invalid_count"] = max(
                counters["document_id_invalid_count"],
                counters["document_id_source_candidate_count"] - counters["document_id_valid_count"],
            )
        return counters

    def _first_zero_gate(self, diag: dict) -> str:
        if diag.get("CATEGORY_HOST_VALID") != "YES":
            return "CATEGORY_HOST_VALID"
        if diag.get("CATEGORY_PATH_VALID") != "YES":
            return "CATEGORY_PATH_VALID"
        if diag.get("CATEGORY_ROUTE_MARKER_PRESENT") != "YES":
            return "CATEGORY_ROUTE_MARKER_PRESENT"
        if diag.get("CATEGORY_BREADCRUMB_VALID") != "YES":
            return "CATEGORY_BREADCRUMB_VALID"
        if diag.get("CATEGORY_ACTIVE_MENU_VALID") != "YES":
            return "CATEGORY_ACTIVE_MENU_VALID"
        if int(diag.get("TABLE_CANDIDATE_COUNT", 0) or 0) > 0 and not diag.get("VALIDATED_TABLE_SELECTOR"):
            return "TABLE_HEADER_VALIDATION"
        if not diag.get("VALIDATED_TABLE_SELECTOR") and diag.get("EMPTY_STATE_FOUND") == "YES":
            return "CONFIRMED_EMPTY"
        if not diag.get("VALIDATED_TABLE_SELECTOR"):
            return "TABLE_NOT_FOUND_WITHOUT_EMPTY_STATE"
        if int(diag.get("DATA_ROW_COUNT_BEFORE_FILTER", 0) or 0) > 0 and int(diag.get("DATA_ROW_COUNT_AFTER_FILTER", 0) or 0) == 0:
            return "ROW_FILTERING"
        if int(diag.get("DATA_ROW_COUNT_AFTER_FILTER", 0) or 0) > 0 and int(diag.get("DOCUMENT_ID_VALID_COUNT", 0) or 0) == 0:
            return "DOCUMENT_ID_EXTRACTION"
        if int(diag.get("DATA_ROW_COUNT_AFTER_FILTER", 0) or 0) == 0:
            return "NO_DATA_ROWS"
        return "READY_BEFORE_ATTACHMENT_LAYER"

    def _diagnose_incoming_category(self, page: Page, category: str) -> tuple[Page, dict]:
        label = {
            "incoming_registry": "INCOMING_REGISTRY",
            "incoming_forwarded_processed": "FORWARDED_PROCESSED",
            "incoming_processed": "PROCESSED",
        }.get(category, category.upper())
        diag = {
            "CATEGORY_KEY": label,
            "CATEGORY_OPEN_ATTEMPTED": "YES",
            "CATEGORY_OPEN_METHOD": "R14_MENU_CLICK",
            "PAGE_OPEN_BEFORE_CATEGORY": "UNKNOWN",
            "PAGE_CLOSED_BEFORE_CATEGORY": "UNKNOWN",
            "PAGE_CLOSED_AFTER_CATEGORY": "UNKNOWN",
            "CATEGORY_HOST_VALID": "NO",
            "CATEGORY_PATH_VALID": "NO",
            "CATEGORY_ROUTE_MARKER_PRESENT": "NO",
            "CATEGORY_BREADCRUMB_TEXT_NORMALIZED": "",
            "CATEGORY_BREADCRUMB_VALID": "NO",
            "CATEGORY_ACTIVE_MENU_TEXT_NORMALIZED": "",
            "CATEGORY_ACTIVE_MENU_VALID": "NO",
            "EMPTY_STATE_FOUND": "NO",
            "EMPTY_STATE_TEXT_NORMALIZED": "",
            "MAIN_CONTENT_FOUND": "NO",
            "TABLE_CANDIDATE_COUNT": 0,
            "TABLE_SELECTOR_CANDIDATES": [],
            "VALIDATED_TABLE_SELECTOR": "",
            "TABLE_HEADER_COUNT": 0,
            "TABLE_HEADERS_NORMALIZED": [],
            "TABLE_HEADER_VALIDATION": "NO",
            "CATEGORY_FIRST_ZERO_GATE": "",
            "CATEGORY_RESULT": "UNKNOWN",
        }
        try:
            closed_before = bool(page.is_closed())
            diag["PAGE_OPEN_BEFORE_CATEGORY"] = "NO" if closed_before else "YES"
            diag["PAGE_CLOSED_BEFORE_CATEGORY"] = "YES" if closed_before else "NO"
            if closed_before:
                diag["CATEGORY_FIRST_ZERO_GATE"] = "PROCESS_DIRECTION_PAGE_CLOSED"
                diag["CATEGORY_RESULT"] = "PAGE_CLOSED"
                return page, diag
            page = self.open_incoming_category(page, category, resolve_after_click=False)
            diag["PAGE_CLOSED_AFTER_CATEGORY"] = "YES" if page.is_closed() else "NO"
            parsed = urlparse(page.url or "")
            diag["CATEGORY_HOST_VALID"] = "YES" if parsed.hostname == "qlvb.laichau.gov.vn" else "NO"
            diag["CATEGORY_PATH_VALID"] = "YES" if parsed.path == "/qlvbdh_lcu/main" else "NO"
            route = self._validate_incoming_category_route(page, category)
            diag["CATEGORY_ROUTE_MARKER_PRESENT"] = "YES" if route.get("route_marker") else "NO"
            diag["CATEGORY_BREADCRUMB_VALID"] = "YES" if route.get("breadcrumb") else "NO"
            diag["CATEGORY_ACTIVE_MENU_VALID"] = "YES" if route.get("active_menu") else "NO"
            route_texts = self._diagnostic_route_texts(page)
            diag["CATEGORY_BREADCRUMB_TEXT_NORMALIZED"] = route_texts["breadcrumb"]
            diag["CATEGORY_ACTIVE_MENU_TEXT_NORMALIZED"] = route_texts["active_menu"]
            empty_text = self._diagnostic_empty_state_text(page)
            diag["EMPTY_STATE_FOUND"] = "YES" if empty_text else "NO"
            diag["EMPTY_STATE_TEXT_NORMALIZED"] = empty_text
            candidates, main_found = self._diagnostic_table_candidates(page)
            diag["MAIN_CONTENT_FOUND"] = main_found
            diag["TABLE_CANDIDATE_COUNT"] = len(candidates)
            diag["TABLE_SELECTOR_CANDIDATES"] = candidates[:5]
            table = self._find_document_table(page, allow_fallback=False)
            headers: list[str] = []
            if table is not None:
                diag["VALIDATED_TABLE_SELECTOR"] = "MAIN_CONTENT_DOCUMENT_TABLE"
                headers = self._extract_headers(page, allow_fallback=False)
                diag["TABLE_HEADER_VALIDATION"] = "YES" if headers else "NO"
            diag["TABLE_HEADER_COUNT"] = len(headers)
            diag["TABLE_HEADERS_NORMALIZED"] = [self._safe_normalized_text(header) for header in headers]
            diag.update({key.upper(): value for key, value in self._diagnostic_rows(page, table, headers).items()})
            first_gate = self._first_zero_gate(diag)
            diag["CATEGORY_FIRST_ZERO_GATE"] = first_gate
            if first_gate == "CONFIRMED_EMPTY":
                diag["CATEGORY_RESULT"] = "CONFIRMED_EMPTY"
            elif first_gate == "READY_BEFORE_ATTACHMENT_LAYER":
                diag["CATEGORY_RESULT"] = "READY_FOR_ATTACHMENT_LAYER"
            else:
                diag["CATEGORY_RESULT"] = "ZERO_AT_" + first_gate
            return page, diag
        except Exception as exc:
            diag["CATEGORY_FIRST_ZERO_GATE"] = "CATEGORY_DIAGNOSTIC_EXCEPTION"
            diag["CATEGORY_RESULT"] = "FAILED"
            diag["EXACT_ERROR"] = str(exc)
            return page, diag

    def run_zero_document_diagnostic(self, page: Page, output_dir: Path) -> dict:
        output_dir.mkdir(parents=True, exist_ok=True)
        categories = []
        current_page = page
        for category in CATEGORY_ORDER:
            current_page, diag = self._diagnose_incoming_category(current_page, category)
            categories.append(diag)
        all_empty = len(categories) == len(CATEGORY_ORDER) and all(item.get("CATEGORY_RESULT") == "CONFIRMED_EMPTY" for item in categories)
        first_zero_gate = next(
            (item.get("CATEGORY_FIRST_ZERO_GATE", "UNKNOWN") for item in categories if item.get("CATEGORY_RESULT") != "CONFIRMED_EMPTY"),
            "ALL_CATEGORIES_CONFIRMED_EMPTY",
        )
        summary = {
            "PROCESS_DIRECTION_CALL_COUNT": 0,
            "PROCESS_DIRECTION_EXIT_REASON_BY_CATEGORY": {
                item["CATEGORY_KEY"]: item.get("CATEGORY_FIRST_ZERO_GATE", "UNKNOWN") for item in categories
            },
            "FIRST_ZERO_GATE": first_zero_gate,
            "ALL_CATEGORIES_CONFIRMED_EMPTY": "YES" if all_empty else "NO",
            "CATEGORY_COUNT": len(categories),
            "categories": categories,
        }
        (output_dir / "category-structure.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        lines = [
            f"PROCESS_DIRECTION_CALL_COUNT: {summary['PROCESS_DIRECTION_CALL_COUNT']}",
            "PROCESS_DIRECTION_EXIT_REASON_BY_CATEGORY: "
            + json.dumps(summary["PROCESS_DIRECTION_EXIT_REASON_BY_CATEGORY"], ensure_ascii=False),
            f"FIRST_ZERO_GATE: {first_zero_gate}",
            f"ALL_CATEGORIES_CONFIRMED_EMPTY: {summary['ALL_CATEGORIES_CONFIRMED_EMPTY']}",
        ]
        for item in categories:
            lines.extend([
                "",
                f"CATEGORY_KEY: {item.get('CATEGORY_KEY')}",
                f"CATEGORY_FIRST_ZERO_GATE: {item.get('CATEGORY_FIRST_ZERO_GATE')}",
                f"CATEGORY_RESULT: {item.get('CATEGORY_RESULT')}",
            ])
        (output_dir / "diagnostic-summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        snippet_lines = []
        for item in categories:
            snippet_lines.append(f"CATEGORY_KEY: {item.get('CATEGORY_KEY')}")
            snippet_lines.append("TABLE_SELECTOR_CANDIDATES:")
            snippet_lines.append(json.dumps(item.get("TABLE_SELECTOR_CANDIDATES", []), ensure_ascii=False, indent=2))
            snippet_lines.append("SAMPLE_ROW_SHAPE:")
            snippet_lines.append(json.dumps(item.get("SAMPLE_ROW_SHAPE", {}), ensure_ascii=False, indent=2))
        (output_dir / "sanitized-dom-snippets.txt").write_text("\n".join(snippet_lines) + "\n", encoding="utf-8")
        return summary

    def _process_direction(self, page: Page, direction: str, max_items: int,
                           fixed_url: str = "", category: str = "", planner: bool = False, knowledge: bool = False) -> dict:
        result = {
            "status": "RUNNING",
            "url": mask_url_query(fixed_url) if fixed_url else "DOM_MENU",
            "processed": 0,
            "skipped_existing": 0,
            "downloaded_files": 0,
            "failed_records": 0,
            "invalid_files": 0,
            "records_without_valid_attachment": 0,
            "session_expired_records": 0,
            "category_validated": False,
            "document_table_validated": False,
            "document_count": 0,
            "rows_scanned": 0,
            "document_ids_validated": 0,
            "rows_with_attachments": 0,
            "invalid_response_count": 0,
            "selected_row_index": None,
            "selected_document_id": None,
            "attachment_discovery_method": "NOT_RUN",
            "attachment_count": 0,
            "incoming_registry_menu_clicked": "NOT_RUN",
            "route_validation": {},
            "errors": [],
            "diagnostic_counters": {
                "PROCESS_DIRECTION_ENTERED": 1,
                "PROCESS_DIRECTION_PAGE_CLOSED": 0,
                "PROCESS_DIRECTION_CATEGORY_VALID": 0,
                "PROCESS_DIRECTION_TABLE_FOUND": 0,
                "PROCESS_DIRECTION_ROWS_FOUND": 0,
                "PROCESS_DIRECTION_ROWS_AFTER_FILTER": 0,
                "PROCESS_DIRECTION_DOCUMENT_IDS_FOUND": 0,
                "PROCESS_DIRECTION_EXIT_REASON": "RUNNING",
            },
        }
        detail_page: Page | None = None
        category_key = category or direction
        self.run_summary["process_direction_call_count"] = int(self.run_summary.get("process_direction_call_count", 0) or 0) + 1
        exit_reasons = self.run_summary.setdefault("process_direction_exit_reason_by_category", {})
        try:
            strict_incoming_category = category in {"incoming_registry", "incoming_forwarded_processed", "incoming_pending", "incoming_processed"}
            try:
                if page.is_closed():
                    result["diagnostic_counters"]["PROCESS_DIRECTION_PAGE_CLOSED"] += 1
            except Exception:
                pass
            if fixed_url:
                self._goto(page, fixed_url, f"Link cá»‘ Ä‘á»‹nh {category}")
                if not self._is_logged_in(page):
                    if strict_incoming_category:
                        raise RuntimeError("AUTH_SESSION_NOT_SHARED_TO_AUTOMATION_PAGE")
                    self.logger.warning("Trang yÃªu cáº§u Ä‘Äƒng nháº­p láº¡i (SESSION_EXPIRED).")
                    self._ensure_logged_in(page, headless_value=self.config.browser.headless)
                    self._goto(page, fixed_url, f"Retry link cá»‘ Ä‘á»‹nh {category} sau khi login")

            elif strict_incoming_category:
                page = self.open_incoming_category(
                    page,
                    category,
                    resolve_after_click=False,
                )
            else:
                page = self.open_document_direction(page, direction)

            if strict_incoming_category:
                route = self._validate_incoming_category_route(page, category)
                result["category_validated"] = route["valid"]
                result["route_validation"] = route
                result["diagnostic_counters"]["PROCESS_DIRECTION_CATEGORY_VALID"] = 1 if route["valid"] else 0
                if category == "incoming_registry":
                    result["incoming_registry_menu_clicked"] = (
                        "PASS" if self._last_incoming_registry_menu_clicked else "NOT_APPLICABLE"
                    )
                route_name = {
                    "incoming_registry": "INCOMING_REGISTRY",
                    "incoming_forwarded_processed": "FORWARDED_PROCESSED",
                    "incoming_pending": "PENDING",
                    "incoming_processed": "PROCESSED",
                }[category]
                self.logger.info("%s_ROUTE_VALIDATED: %s", route_name, "PASS" if route["valid"] else "FAIL")
                if not route["valid"]:
                    if not route.get("host"):
                        raise RuntimeError("WRONG_QLVB_HOST")
                    if not route.get("route_marker"):
                        raise RuntimeError("INCOMING_REGISTRY_ROUTE_MARKER_MISSING")
                    if not route.get("breadcrumb"):
                        raise RuntimeError("INCOMING_REGISTRY_BREADCRUMB_MISMATCH")
                    if not route.get("active_menu"):
                        raise RuntimeError("INCOMING_REGISTRY_MENU_NOT_ACTIVE")
                    raise RuntimeError("INCOMING_CATEGORY_ROUTE_NOT_VALIDATED")

                table = self._wait_for_validated_document_table(page, allow_fallback=False)
                if not table:
                    if self._has_empty_document_state(page):
                        self.logger.info("Nguá»“n %s hiá»‡n chÆ°a cÃ³ dá»¯ liá»‡u (EMPTY).", category)
                        result["status"] = "EMPTY"
                        result["confirmed_empty_state"] = True
                        result["document_count"] = 0
                        result["message"] = "Hiá»‡n chÆ°a cÃ³ dÃ¡Â»Â¯ liá»‡u"
                        result["diagnostic_counters"]["PROCESS_DIRECTION_EXIT_REASON"] = "CONFIRMED_EMPTY"
                        exit_reasons[category_key] = "CONFIRMED_EMPTY"
                        return result
                    raise RuntimeError("FIXED_URL_DOCUMENT_TABLE_NOT_FOUND")
                result["document_table_validated"] = True
                result["diagnostic_counters"]["PROCESS_DIRECTION_TABLE_FOUND"] = 1

            source_url = mask_url_query(page.url)
            strict_document_table = strict_incoming_category
            headers = self._extract_headers(page, allow_fallback=not strict_document_table)
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
                        empty_state = self._has_empty_document_state(page)
                        if result["document_table_validated"] or empty_state:
                            self.logger.info("Nguá»“n %s hiá»‡n chÆ°a cÃ³ dá»¯ liá»‡u (EMPTY).", category)
                            result["status"] = "EMPTY"
                            result["confirmed_empty_state"] = bool(empty_state)
                            result["document_count"] = 0
                            result["message"] = "Hiá»‡n chÆ°a cÃ³ vÄƒn báº£n Ä‘áº¿n chá» xá»­ lÃ½" if "pending" in category else "Hiá»‡n chÆ°a cÃ³ dá»¯ liá»‡u"
                            result["diagnostic_counters"]["PROCESS_DIRECTION_EXIT_REASON"] = (
                                "CONFIRMED_EMPTY" if empty_state else "ZERO_ROWS_WITHOUT_EMPTY_STATE"
                            )
                            exit_reasons[category_key] = result["diagnostic_counters"]["PROCESS_DIRECTION_EXIT_REASON"]
                            break

                    self.logger.warning("Khong doc duoc dong nao o danh sach %s trang %s.", direction, page_no)
                    self._save_page_error(page, f"no_rows_{direction}_page_{page_no}", extra={"headers": headers, "url": page.url})
                    result["diagnostic_counters"]["PROCESS_DIRECTION_EXIT_REASON"] = "NO_ROWS_EXTRACTED"
                    exit_reasons[category_key] = "NO_ROWS_EXTRACTED"
                    break

                result["document_count"] += len(records)
                result["diagnostic_counters"]["PROCESS_DIRECTION_ROWS_FOUND"] += len(records)
                result["diagnostic_counters"]["PROCESS_DIRECTION_ROWS_AFTER_FILTER"] += len(records)

                if strict_document_table:
                    selected = self._select_first_incoming_row_with_attachments(page, records, result)
                    result["diagnostic_counters"]["PROCESS_DIRECTION_DOCUMENT_IDS_FOUND"] = result["document_ids_validated"]
                    if selected is None:
                        result["status"] = "DONE"
                        if result["document_ids_validated"] == 0:
                            result["message"] = "NO_VALID_DOCUMENT_IDS_IN_SCANNED_ROWS"
                            result["diagnostic_counters"]["PROCESS_DIRECTION_EXIT_REASON"] = "DOCUMENT_ID_EXTRACTION"
                        else:
                            result["message"] = "NO_DOCUMENT_WITH_ATTACHMENTS_IN_SCANNED_ROWS"
                            result["diagnostic_counters"]["PROCESS_DIRECTION_EXIT_REASON"] = "NO_DOCUMENT_WITH_ATTACHMENTS"
                        exit_reasons[category_key] = result["diagnostic_counters"]["PROCESS_DIRECTION_EXIT_REASON"]
                        break
                    # A live diagnostic downloads at most one attachment from one validated row.
                    records = [selected]

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

                    if strict_document_table:
                        self.logger.info("ROWS_SCANNED: %s", result["rows_scanned"])
                        self.logger.info("DOCUMENT_IDS_VALIDATED: %s", result["document_ids_validated"])
                        self.logger.info("ROWS_WITH_ATTACHMENTS: %s", result["rows_with_attachments"])
                        self.logger.info("SELECTED_ROW_INDEX: %s", result["selected_row_index"])
                        self.logger.info("SELECTED_DOCUMENT_ID: %s", rec.metadata["source_document_id"])
                        self.logger.info("ATTACHMENT_DISCOVERY_SCOPE: SELECTED_DOCUMENT_ONLY")
                        self.logger.info("PAGE_WIDE_SCAN_USED: NO")
                        self.logger.info("HELP_FILE_COLLECTED: NO")
                        self.logger.info("PRINT_ACTION_COLLECTED: NO")
                        self.logger.info("OTHER_DOCUMENT_ACTION_COLLECTED: NO")

                    # Deduplication check
                    external_doc_id = rec.doc_id
                    already_in_queue = False

                    # Check queue directory (both formats via get_queue_item_files)
                    queue_info = self.storage.get_queue_item_files(direction, external_doc_id)
                    if queue_info is not None:
                        already_in_queue = True

                    # Check if files directory status is READY
                    existing = self.storage.existing_status(rec) if self.config.download.skip_existing else None
                    already_downloaded = existing and str(existing.get("status", "")) in DOCUMENT_QUEUEABLE_STATUSES

                    if already_in_queue or already_downloaded:
                        self.logger.info("Bo qua ho so bi trung (external_doc_id: %s) | skipped_duplicate", external_doc_id)
                        result["skipped_existing"] += 1
                        continue

                    try:
                        self._process_record(detail_page, rec, list_page=page)
                        result["processed"] += 1
                        result["downloaded_files"] += sum(1 for a in rec.attachments if a.status == ATTACHMENT_VALIDATED)
                        result["invalid_files"] += sum(1 for a in rec.attachments if a.status == ATTACHMENT_INVALID_FILE)
                        if rec.status == DOCUMENT_NO_VALID_ATTACHMENT:
                            result["records_without_valid_attachment"] += 1
                        if rec.status == DOCUMENT_SESSION_EXPIRED:
                            result["session_expired_records"] += 1
                        if rec.status not in DOCUMENT_QUEUEABLE_STATUSES:
                            if rec.status in {DOCUMENT_FAILED, DOCUMENT_SESSION_EXPIRED}:
                                result["failed_records"] += 1
                            err = {
                                "doc_id": rec.doc_id,
                                "status": rec.status,
                                "error": rec.error or rec.status,
                            }
                            result["errors"].append(err)
                            self.run_summary["errors"].append(err)
                    except Exception as exc:
                        rec.status = DOCUMENT_FAILED
                        rec.error = str(exc)
                        self._write_outputs_and_report(rec)
                        err = {"doc_id": rec.doc_id, "error": str(exc)}
                        result["errors"].append(err)
                        self.run_summary["errors"].append(err)
                        result["processed"] += 1
                        result["failed_records"] += 1
                        self.logger.error("Loi xu ly ho so %s: %s", rec.doc_id, exc)
                        self.logger.debug(traceback.format_exc())

                if result["processed"] >= max_items:
                    break
                if not self._go_next_page(page):
                    break
                page_no += 1
                headers = self._extract_headers(page, allow_fallback=not strict_document_table)

            if result["status"] == "EMPTY":
                return result
            result["status"] = "DONE" if not result["errors"] else "DONE_WITH_ERRORS"
            if result["diagnostic_counters"]["PROCESS_DIRECTION_EXIT_REASON"] == "RUNNING":
                result["diagnostic_counters"]["PROCESS_DIRECTION_EXIT_REASON"] = result["status"]
                exit_reasons[category_key] = result["status"]
            return result
        except Exception as exc:
            self._save_page_error(page, f"direction_error_{direction}")
            result["status"] = DOCUMENT_SESSION_EXPIRED if "SESSION_EXPIRED" in str(exc) else "FAILED"
            result["error"] = str(exc)
            result["diagnostic_counters"]["PROCESS_DIRECTION_EXIT_REASON"] = str(exc)
            exit_reasons[category_key] = str(exc)
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
            if not allow_fallback:
                main_selectors = "main, #content, #main-content, .main-content, #div_data_list"
                for scope in scopes:
                    roots = scope.locator(main_selectors)
                    for root_index in range(min(roots.count(), 20)):
                        root = roots.nth(root_index)
                        if not root.is_visible(timeout=300):
                            continue
                        for table in root.locator("table").all():
                            try:
                                if not table.is_visible(timeout=300):
                                    continue
                                headers = [clean_text(h) for h in table.locator("thead th, tr th").all_inner_texts()]
                                headers = [header for header in headers if header]
                                if headers:
                                    from .parser import is_document_table_headers
                                    if is_document_table_headers(headers):
                                        self.logger.info("Da tim thay bang danh sach van ban hop le trong main content.")
                                        self._current_table_scope = scope
                                        return table
                            except Exception:
                                continue
                return None
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
                                    self._current_table_scope = scope
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
                    self._current_table_scope = scope
                    return fallback
            return None
        except Exception as e:
            self.logger.error("Loi khi tim bang danh sach van ban: %s", e)
            return None

    def _extract_headers(self, page: Page, allow_fallback: bool = True) -> list[str]:
        self._current_table_container = None
        self._current_table_scope = None
        table = self._find_document_table(page, allow_fallback=allow_fallback)
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
                self.logger.debug("Bá» qua dÃ²ng tiÃªu Ä‘á» báº£ng, khÃ´ng pháº£i há»“ sÆ¡: %s", row_text[:160])
                continue
            if len(cells) <= 1 and len(row_text) < 15:
                continue
            detail_url = self._extract_detail_url(row, page.url)

            # Construct record
            rec = build_record_from_row(direction, source_url, i + 1, row_text, cells, detail_url, headers if len(headers) == len(cells) else None)
            rec.metadata["row_locator_index"] = i
            rec.metadata["detail_action_index"] = self._extract_detail_action_index(row)
            rec.metadata["row_has_attachment_indicator"] = self._row_has_attachment_indicator(row)
            source_id = self._extract_source_document_id(row, page.url, rec.metadata)
            if source_id is not None:
                rec.metadata["source_document_id"] = source_id.document_id
                rec.metadata["source_document_id_method"] = source_id.source_method

            # Validate document record immediately
            from .parser import validate_document_record
            status, reason = validate_document_record(rec)
            if status == "INVALID":
                self.logger.warning("skipped_invalid_non_document_record | Ly do: %s | doc_id: %s", reason, rec.doc_id)
                continue

            records.append(rec)
        return records

    def _row_has_attachment_indicator(self, row: Locator) -> bool:
        """Read only the selected table row; JavaScript actions remain discovery hints, never download URLs."""
        try:
            actions = row.locator("[data-attachment-count], [data-file-id], [onclick]")
            for index in range(min(actions.count(), 40)):
                action = actions.nth(index)
                count_value = (action.get_attribute("data-attachment-count") or "").strip()
                if count_value.isdigit() and int(count_value) > 0:
                    return True
                if (action.get_attribute("data-file-id") or "").strip():
                    return True
                onclick = (action.get_attribute("onclick") or "").casefold()
                if "getfileattachlst" in onclick:
                    return True
        except Exception:
            return False
        return False

    def _extract_source_document_id(self, row: Locator, base_url: str, detail_metadata: dict) -> object | None:
        """Read only explicit row/action identifiers; never mine numbers from document text."""
        try:
            row_attributes = {
                key: row.get_attribute(key) or ""
                for key in ("data-document-id", "data-doc-id", "data-vb-id", "data-id")
            }
            row_id = row.get_attribute("id") or ""
            row_onclick = row.get_attribute("onclick") or ""
            result = extract_document_id(
                attributes=row_attributes,
                row_id=row_id,
                onclick=row_onclick,
                detail_metadata=detail_metadata,
            )
            if result is not None:
                return result

            actions = row.locator("a, button, [onclick], [data-url], [data-href]")
            for index in range(min(actions.count(), 40)):
                action = actions.nth(index)
                result = extract_document_id(
                    attributes={
                        key: action.get_attribute(key) or ""
                        for key in ("data-document-id", "data-doc-id", "data-vb-id", "data-id")
                    },
                    row_id=action.get_attribute("id") or "",
                    onclick=action.get_attribute("onclick") or "",
                    href=action.get_attribute("href") or action.get_attribute("data-url") or action.get_attribute("data-href") or "",
                    detail_metadata=detail_metadata,
                )
                if result is not None:
                    return result
        except Exception:
            return None
        return None

    def _is_empty_row(self, text: str) -> bool:
        lowered = text.lower()
        for marker in self.config.selectors["list"].get("empty_markers", []):
            if marker.lower() in lowered:
                return True
        return False

    def _is_header_row(self, row: Locator, row_text: str, cells: list[str], headers: list[str] | None) -> bool:
        lowered = row_text.lower()

        # 1. Chá»©a Ä‘á»“ng thá»i nhiá»u nhÃ£n
        labels = ["trÃ­ch yáº¿u", "sá»‘ kÃ½ hiá»‡u", "sá»‘ / kÃ½ hiá»‡u", "ngÃ y vÄƒn báº£n", "cÆ¡ quan ban hÃ nh", "ngÆ°á»i kÃ½", "loáº¡i vÄƒn báº£n"]
        hits = sum(1 for kw in labels if kw in lowered)
        if hits >= 3:
            return True

        # 2. CÃ¡c cell báº¯t Ä‘áº§u báº±ng stt hoáº·c chá»©a pháº§n lá»›n cÃ¡c header truyá»n vÃ o
        if cells and cells[0].strip().lower() in ("stt", "sá»‘", "tt"):
            return True

        if headers and len(cells) >= 2:
            header_set = {clean_text(value).lower() for value in headers if clean_text(value)}
            header_hits = sum(1 for value in cells if value.lower() in header_set)
            if header_hits >= max(2, len(cells) // 2):
                return True

        # 3. CÃ³ th thay vÃ¬ td
        try:
            th_count = row.locator("th").count()
            td_count = row.locator("td").count()
            if th_count > 0 and td_count == 0:
                return True
        except Exception:
            pass

        # 4. CÃ³ class dáº¡ng header
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
                if any(word in text for word in ("chi tiáº¿t", "chi tiet", "trÃ­ch yáº¿u", "trich yeu", "xem")):
                    return i
            return fallback
        except Exception:
            return None

    def _process_record(self, page: Page, rec: DocumentRecord, list_page: Page | None = None) -> None:
        self.logger.info("Xu ly ho so: %s | %s", rec.doc_id, rec.title[:120])
        rec.status = DOCUMENT_PROCESSING
        active_page = page
        restore_list = False
        opened_detail = False
        session_page = list_page or page
        discovery_scope = getattr(self, "_current_table_scope", None) or session_page
        neoremoting_error: NeoRemotingDiscoveryError | None = None
        source_document_id = str(rec.metadata.get("source_document_id") or "")
        neoremoting_only = rec.source_category in {
            "incoming_registry",
            "incoming_forwarded_processed",
            "incoming_pending",
            "incoming_processed",
        }

        if source_document_id and not rec.attachments:
            try:
                if not self._is_logged_in(session_page):
                    raise NeoRemotingDiscoveryError("NEOREMOTING_ACCESS_DENIED")
                adapter = NeoRemotingAttachmentDiscoveryAdapter(
                    self.config.qlvb_base_url or session_page.url,
                    timeout_ms=self.config.browser.timeout_ms,
                )
                rec.attachments = adapter.discover(
                    discovery_scope,
                    document_id=source_document_id,
                    category=rec.source_category or rec.direction,
                    correlation_id=self.run_id,
                )
                rec.metadata["attachment_discovery_method"] = "NEOREMOTING"
                active_page = session_page
            except NeoRemotingDiscoveryError as exc:
                neoremoting_error = exc
                rec.metadata["neoremoting_error"] = exc.code
                if neoremoting_only or not exc.fallback_allowed:
                    rec.status = DOCUMENT_FAILED
                    rec.error = exc.code
                    rec.metadata["attachment_discovery_method"] = "NONE"
                    self._write_outputs_and_report(rec)
                    return

        if neoremoting_only and not source_document_id:
            rec.status = DOCUMENT_FAILED
            rec.error = "SELECTED_DOCUMENT_ID_REQUIRED"
            rec.metadata["attachment_discovery_method"] = "NONE"
            self._write_outputs_and_report(rec)
            return

        if not rec.attachments:
            if rec.detail_url:
                self._goto_detail_with_retry(page, rec.detail_url, f"chi tiet {rec.doc_id}")
                opened_detail = True
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
            self._ensure_usable_detail_page(active_page, rec)
            self._merge_detail_metadata(active_page, rec)
            rec.attachments = self._extract_attachments(active_page)
            rec.metadata["attachment_discovery_method"] = "DETAIL_DOM" if rec.attachments else "NONE"

        if not rec.attachments and neoremoting_error is not None:
            rec.metadata["attachment_discovery_method"] = "NONE"

        if not rec.attachments:
            rec.status = DOCUMENT_NO_VALID_ATTACHMENT
            rec.error = "NO_VALID_ATTACHMENT"
            self.logger.warning("Ho so %s chua tim thay file dinh kem.", rec.doc_id)
        elif self.config.download.dry_run:
            rec.status = DOCUMENT_NO_VALID_ATTACHMENT
            rec.error = "DRY_RUN_NO_VALID_ATTACHMENT"
            self.logger.info("DRY RUN: chi ghi metadata, khong tai tep dinh kem.")
        else:
            self._download_attachments(active_page, rec)
            validated = sum(1 for a in rec.attachments if a.status == ATTACHMENT_VALIDATED)
            invalid = sum(1 for a in rec.attachments if a.status in {ATTACHMENT_INVALID_FILE, ATTACHMENT_DOWNLOAD_FAILED})
            if validated > 0 and invalid == 0:
                rec.status = DOCUMENT_READY
                rec.error = None
            elif validated > 0:
                rec.status = DOCUMENT_READY_WITH_WARNINGS
                rec.error = f"{invalid} attachment(s) invalid or failed"
            else:
                rec.status = DOCUMENT_NO_VALID_ATTACHMENT
                rec.error = "NO_VALID_ATTACHMENT"

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
            "button:visible:has-text('ÄÃ³ng')", "button:visible:has-text('Dong')",
        ):
            try:
                loc = page.locator(selector)
                if loc.count():
                    loc.first.click(force=True)
                    return
            except Exception:
                continue

    def _ensure_usable_detail_page(self, page: Page, rec: DocumentRecord) -> None:
        try:
            if page.is_closed():
                raise RuntimeError("DETAIL_PAGE_CLOSED")
            current_url = page.url or ""
        except Exception as exc:
            raise RuntimeError(f"DETAIL_PAGE_UNUSABLE|{exc}") from exc
        if current_url.startswith("about:"):
            rec.status = DOCUMENT_FAILED
            rec.error = "DETAIL_PAGE_ABOUT_BLANK"
            raise RuntimeError("DETAIL_PAGE_ABOUT_BLANK")
        parsed = urlparse(current_url)
        if parsed.scheme in {"http", "https"} and parsed.hostname and parsed.hostname.lower() not in QLVB_ALLOWED_HOSTS:
            rec.status = DOCUMENT_FAILED
            rec.error = "DETAIL_PAGE_UNEXPECTED_HOST"
            raise RuntimeError("DETAIL_PAGE_UNEXPECTED_HOST")

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
            actions.nth(int(action_index)).evaluate("el => el.click()")
        except Exception:
            actions.nth(int(action_index)).click(force=True)

        list_page.wait_for_timeout(2000)
        self._safe_wait_networkidle(list_page, timeout=8000)
        new_pages = [p for p in list_page.context.pages if p not in before_pages]
        if new_pages:
            detail = new_pages[-1]
            detail.wait_for_load_state("domcontentloaded", timeout=self.config.browser.timeout_ms)
            if (detail.url or "").startswith("about:"):
                try:
                    detail.wait_for_url(lambda url: not str(url).startswith("about:"), timeout=3000)
                except Exception:
                    self.logger.warning("Popup chi tiet van la about:blank, dong popup va bo qua ho so %s.", rec.doc_id)
                    try:
                        detail.close()
                    except Exception:
                        pass
                    return None
            self._ensure_usable_detail_page(detail, rec)
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
            "attachment_downloaded": sum(1 for a in rec.attachments if a.status == ATTACHMENT_VALIDATED),
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

        rec.doc_no = rec.doc_no or first_pair_contains(["sá»‘", "kÃ½ hiá»‡u"])
        rec.doc_date = rec.doc_date or first_pair_contains(["ngÃ y"])
        rec.issuing_agency = rec.issuing_agency or first_pair_contains(["cÆ¡ quan", "nÆ¡i gá»­i", "Ä‘Æ¡n vá»‹", "ngÆ°á»i gá»­i"])
        rec.title = rec.title or first_pair_contains(["trÃ­ch yáº¿u", "ná»™i dung", "tiÃªu Ä‘á»", "tÃªn vÄƒn báº£n"])
        rec.summary = rec.summary or rec.title
        if not rec.doc_date:
            rec.doc_date = guess_date(body_text)

    def _extract_attachments(self, page: Page) -> list[AttachmentInfo]:
        attachments: list[AttachmentInfo] = []
        seen = set()

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
        self._download_in_progress = True
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
                    att.status = ATTACHMENT_DOWNLOAD_STARTED
                    saved = self._download_by_click_or_request(page, rec, att.href, idx)
                    att.saved_path = str(saved)
                    att.original_filename = saved.name
                    att.download_source = att.source_method or rec.metadata.get("attachment_discovery_method") or "DETAIL_DOM"
                    att.status = ATTACHMENT_VALIDATED
                    validation = self._validate_downloaded_file(saved, {})
                    att.validation_sha256 = validation["sha256"]
                    att.validation_size_bytes = validation["size_bytes"]
                    att.validation_content_type = validation.get("content_type")

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
                    att.status = ATTACHMENT_INVALID_FILE if self._is_invalid_file_error(exc) else ATTACHMENT_DOWNLOAD_FAILED
                    att.error = str(exc)
                    self.logger.warning("Tai tep loi lan %s/%s: %s | %s", attempt, attempts, att.href, exc)
                    time.sleep(1 + attempt)
            if att.status != ATTACHMENT_VALIDATED:
                self.logger.error("Khong tai duoc tep sau %s lan: %s | %s", attempts, att.href, last_exc)

        rec.metadata["download_stats"] = {
            "downloaded_files": downloaded_files,
            "downloaded_archives": downloaded_archives,
            "extracted_files": extracted_files,
            "materialized_files": materialized_files,
            "invalid_files": sum(1 for a in rec.attachments if a.status == ATTACHMENT_INVALID_FILE),
            "failed_files": sum(1 for a in rec.attachments if a.status == ATTACHMENT_DOWNLOAD_FAILED),
        }
        self._download_in_progress = False
        self._last_download_event_at = 0.0

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

    def _is_download_response_candidate(self, page: Page, href: str, response) -> bool:
        if getattr(response, "status", 0) != 200:
            return False
        url = getattr(response, "url", "") or ""
        if not self._is_allowed_download_url(url):
            return False
        headers = getattr(response, "headers", {}) or {}
        content_type = headers.get("content-type", "").lower()
        content_disposition = headers.get("content-disposition", "").lower()
        if "attachment" not in content_disposition:
            return False
        if content_type.startswith("text/html"):
            return False
        if href and not href.lower().startswith("javascript:"):
            expected = urljoin(page.url, href)
            parsed_expected = urlparse(expected)
            parsed_actual = urlparse(url)
            if parsed_expected.hostname and parsed_actual.hostname and parsed_expected.hostname.lower() != parsed_actual.hostname.lower():
                return False
            if parsed_expected.path and parsed_actual.path != parsed_expected.path:
                return False
        return True

    def _is_allowed_download_url(self, value: str) -> bool:
        parsed = urlparse(value or "")
        if parsed.scheme in {"about", "data", "javascript"}:
            return False
        if parsed.scheme in {"http", "https"}:
            return bool(parsed.hostname and parsed.hostname.lower() in QLVB_ALLOWED_HOSTS)
        return True

    def _temp_download_path(self, target: Path) -> Path:
        candidate = target.with_name(target.name + ".part")
        counter = 2
        while candidate.exists():
            candidate = target.with_name(f"{target.name}.{counter}.part")
            counter += 1
        return candidate

    def _finalize_validated_download(
        self,
        target: Path,
        headers: dict,
        source: str,
        source_url: str,
        write_body,
    ) -> tuple[Path, dict]:
        if not self._is_allowed_download_url(source_url):
            raise RuntimeError("DOWNLOAD_SOURCE_URL_INVALID")
        part_path = self._temp_download_path(target)
        write_body(part_path)
        validation = self._validate_downloaded_file(
            part_path,
            headers,
            expected_filename=target.name,
            source_url=source_url,
        )
        part_path.replace(target)
        self.logger.info("Tai tep hop le qua %s: %s", source, target.name)
        return target, validation

    def _download_by_click_or_request(self, page: Page, rec: DocumentRecord, href: str, idx: int) -> Path:
        locator = self._locator_for_href(page, href)
        intercepted: tuple[Path, dict] | None = None

        def handle_response(response):
            nonlocal intercepted
            if intercepted is not None:
                return
            if self._is_download_response_candidate(page, href, response):
                try:
                    filename = self._filename_from_response(response.url, response.headers, idx)
                    target = self.storage.next_download_path(rec, filename, idx)
                    intercepted = self._finalize_validated_download(
                        target,
                        response.headers,
                        "response_interceptor",
                        response.url,
                        lambda part_path: part_path.write_bytes(response.body()),
                    )
                except Exception as exc:
                    self.logger.warning("Bo qua response download khong hop le: %s", exc)

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
                final_path, _validation = self._finalize_validated_download(
                    target,
                    {},
                    "browser_download",
                    href,
                    lambda part_path: download.save_as(str(part_path)),
                )
                page.remove_listener("response", handle_response)
                return final_path
            except Exception as exc:
                self.logger.warning("Click khong bat duoc download (%s), chuyen sang tai truc tiep neu co the.", exc)
                page.remove_listener("response", handle_response)
                if intercepted and intercepted[0].exists():
                    self.logger.info("Da bat duoc file thong qua response interceptor: %s", intercepted[0])
                    return intercepted[0]

        if href.lower().startswith("javascript:"):
            raise RuntimeError("Link táº£i lÃ  javascript vÃ  click khÃ´ng táº¡o download. Cáº§n vÃ¡ selector/luá»“ng táº£i theo log.")

        response = page.context.request.get(href, timeout=self.config.browser.timeout_ms)
        body = response.body()
        self._record_direct_download_transport(rec, href, response, body)
        if not response.ok:
            raise RuntimeError(f"DOWNLOAD_HTTP_ERROR|{response.status}")
        filename = self._filename_from_response(href, response.headers, idx)
        target = self.storage.next_download_path(rec, filename, idx)
        final_path, _validation = self._finalize_validated_download(
            target,
            response.headers,
            "direct_request",
            href,
            lambda part_path: part_path.write_bytes(body),
        )
        return final_path

    @staticmethod
    def _record_direct_download_transport(rec: DocumentRecord, request_url: str, response, body: bytes = b"") -> None:
        """Persist only safe request diagnostics; never retain query or credential material."""
        final_url = getattr(response, "url", "") or request_url
        parsed = urlparse(final_url)
        headers = getattr(response, "headers", {}) or {}
        content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
        rec.metadata["last_download_transport"] = {
            "method": "AUTHENTICATED_DIRECT_REQUEST",
            "url": f"{parsed.scheme}://{parsed.netloc}{parsed.path}",
            "request_method": "GET",
            "authenticated_context_used": True,
            "request_host": urlparse(request_url).hostname or "",
            "request_path": urlparse(request_url).path or "/",
            "request_query_present": bool(urlparse(request_url).query),
            "referer_present": False,
            "http_status": int(getattr(response, "status", 0) or 0),
            "initial_status": int(getattr(response, "status", 0) or 0),
            "final_status": int(getattr(response, "status", 0) or 0),
            "redirect_count": "NOT_EXPOSED_BY_APIRESPONSE",
            "final_host": parsed.hostname or "",
            "final_path": parsed.path or "/",
            "content_type": content_type,
            "content_disposition_present": bool(headers.get("content-disposition")),
            "content_length_header": str(headers.get("content-length") or ""),
            "body_length": len(body),
            "body_prefix_class": classify_download_body_prefix(body),
        }

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
            window.open = function(url, target, features) {
                window.__smartofficeCapturedDownloadUrl = url || target;
                return null;
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

    def _validate_downloaded_file(
        self,
        path: Path,
        response_headers: dict,
        expected_filename: str | None = None,
        source_url: str | None = None,
    ) -> dict:
        if source_url and not self._is_allowed_download_url(source_url):
            raise RuntimeError("DOWNLOAD_SOURCE_URL_INVALID")
        if not path.exists():
            raise RuntimeError("DOWNLOADED_FILE_MISSING")

        size_bytes = path.stat().st_size
        min_size = max(1, int(getattr(self.config.download, "min_file_size_bytes", 1) or 1))
        if size_bytes < min_size:
            raise RuntimeError(f"DOWNLOADED_FILE_TOO_SMALL|{size_bytes}")

        data = path.read_bytes()
        if not data:
            raise RuntimeError("EMPTY_DOWNLOAD_BODY|DOWNLOADED_FILE_EMPTY")

        headers = {str(k).lower(): str(v) for k, v in (response_headers or {}).items()}
        content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
        filename = expected_filename or path.name
        if filename.endswith(".part"):
            filename = filename[:-5]
        suffix = Path(filename).suffix.lower()
        prefix = data[:4096].lower()
        prefix_class = classify_download_body_prefix(data)

        if (
            content_type.startswith("text/html")
            or b"<!doctype html" in prefix
            or b"<html" in prefix
            or b"<form" in prefix and any(marker in prefix for marker in (b"password", b"login", b"dang nhap"))
        ):
            raise RuntimeError("LOGIN_HTML_RESPONSE|DOWNLOADED_HTML_LOGIN_PAGE|SESSION_EXPIRED")
        if prefix_class == "JSON":
            raise RuntimeError("UNSUPPORTED_FILE_RESPONSE|JSON_RESPONSE")
        if prefix_class == "UNKNOWN_BINARY":
            raise RuntimeError("UNSUPPORTED_FILE_RESPONSE|DOWNLOADED_FILE_INVALID")

        import zipfile
        import io

        is_pdf = suffix == ".pdf" or content_type == "application/pdf" or prefix_class == "PDF"
        is_docx = suffix == ".docx" or content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        is_xlsx = suffix == ".xlsx" or content_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        is_zip = (
            suffix == ".zip"
            or content_type in {"application/zip", "application/x-zip-compressed"}
            or prefix_class == "DOCX_XLSX_PPTX_ZIP"
        )
        is_ole = suffix in {".doc", ".xls"} or prefix_class == "OLE_OFFICE"

        if is_pdf and not data.startswith(b"%PDF"):
            raise RuntimeError("FILE_SIGNATURE_MISMATCH|DOWNLOADED_FILE_INVALID")
        if is_ole and not data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
            raise RuntimeError("FILE_SIGNATURE_MISMATCH|DOWNLOADED_FILE_INVALID")

        if is_zip or is_docx or is_xlsx:
            if not data.startswith(b"PK"):
                raise RuntimeError("FILE_SIGNATURE_MISMATCH|DOWNLOADED_FILE_INVALID")
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    names = zf.namelist()
                    if len(names) == 0:
                        raise RuntimeError("DOWNLOADED_ZIP_INVALID" if is_zip else "DOWNLOADED_FILE_INVALID")
                    if is_docx and ("[Content_Types].xml" not in names or "word/document.xml" not in names):
                        raise RuntimeError("DOWNLOADED_FILE_INVALID")
                    if is_xlsx and ("[Content_Types].xml" not in names or "xl/workbook.xml" not in names):
                        raise RuntimeError("DOWNLOADED_FILE_INVALID")
            except zipfile.BadZipFile as exc:
                raise RuntimeError("DOWNLOADED_FILE_INVALID") from exc

        return {
            "size_bytes": size_bytes,
            "sha256": hashlib.sha256(data).hexdigest(),
            "content_type": content_type,
            "filename": filename,
            "body_prefix_class": prefix_class,
        }

    @staticmethod
    def _is_invalid_file_error(exc: Exception) -> bool:
        text = str(exc)
        markers = (
            "DOWNLOADED_",
            "INVALID_FILE",
            "CONTENT_TYPE",
            "CAPTURED_DOWNLOAD_URL_INVALID",
            "UNEXPECTED_DOWNLOAD_HOST",
            "UNEXPECTED_DOWNLOAD_PATH",
            "DOWNLOAD_SOURCE_URL_INVALID",
        )
        return any(marker in text for marker in markers)

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
        final_path, _validation = self._finalize_validated_download(
            target,
            response.headers,
            "javascript_adapter",
            absolute,
            lambda part_path: part_path.write_bytes(response.body()),
        )
        return final_path

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
