from __future__ import annotations

import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from .config import VERSION, load_config
from .downloader import QLVBDownloader
from .models import now_iso
from .paths import configure_bundled_playwright


def _bool(v: str) -> bool:
    return str(v).strip().lower() in ["1", "true", "yes", "y", "co", "có"]


def main() -> None:
    configure_bundled_playwright()
    parser = argparse.ArgumentParser(description=f"Smart Office AI 360 - QLVB Page Probe {VERSION}")
    parser.add_argument("--config", default="", help="Duong dan file cau hinh")
    parser.add_argument("--url", default="", help="URL can kiem tra; bo trong dung link van ban den")
    parser.add_argument("--headless", default="false", help="true/false")
    args = parser.parse_args()
    cfg = load_config(Path(args.config) if args.config else None)
    url = args.url or cfg.incoming_url or cfg.outgoing_url or cfg.qlvb_base_url or cfg.login_url
    result = {"version": VERSION, "time": now_iso(), "url": url, "checks": {}}
    downloader = QLVBDownloader(cfg)
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(cfg.browser_profile_path),
            headless=_bool(args.headless),
            accept_downloads=True,
            slow_mo=cfg.browser.slow_mo_ms,
            channel=cfg.browser.chromium_channel or None,
        )
        page = context.new_page()
        page.set_default_timeout(cfg.browser.timeout_ms)
        try:
            downloader._ensure_logged_in(page, headless_value=_bool(args.headless))
            page.goto(url, wait_until="domcontentloaded", timeout=cfg.browser.timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except PlaywrightTimeoutError:
                pass
            body_text = page.locator("body").inner_text(timeout=8000) if page.locator("body").count() else ""
            result["final_url"] = page.url
            result["body_length"] = len(body_text)
            result["body_excerpt"] = body_text[:2000]
            for group, selectors in cfg.selectors.items():
                result["checks"][group] = {}
                if isinstance(selectors, dict):
                    for key, values in selectors.items():
                        if isinstance(values, list):
                            total = 0
                            matched = []
                            for sel in values[:30]:
                                try:
                                    c = page.locator(sel).count()
                                    total += c
                                    if c:
                                        matched.append({"selector": sel, "count": c})
                                except Exception:
                                    pass
                            result["checks"][group][key] = {"total": total, "matched": matched[:10]}
            out_dir = cfg.root_path / "logs" / "page_probe"
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "page_probe.html").write_text(page.content(), encoding="utf-8", errors="ignore")
            page.screenshot(path=str(out_dir / "page_probe.png"), full_page=True)
            (out_dir / "page_probe.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(result, ensure_ascii=False, indent=2))
        finally:
            context.close()


if __name__ == "__main__":
    main()
