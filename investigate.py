from __future__ import annotations
import json
import time
import os
import hashlib
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

from tools.qlvb_downloader.config import load_config
from tools.qlvb_downloader.paths import configure_bundled_playwright
from tools.qlvb_downloader.downloader import QLVBDownloader

import sys
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

def run_investigation():
    configure_bundled_playwright()
    
    # 1. Load config
    cfg = load_config()
    # Override settings for investigation
    cfg.download.dry_run = False
    cfg.browser.headless = False
    cfg.download.max_items_per_run = 1
    
    # Create Data Root for investigation outputs
    inv_data_root = Path("Data_Investigation")
    inv_data_root.mkdir(exist_ok=True)
    
    downloader = QLVBDownloader(cfg)
    
    print("==================================================")
    print("I. BASELINE & CONFIGURATION")
    print(f"Data Root: {cfg.root_path}")
    print(f"Browser Profile: {cfg.browser_profile_path}")
    print("==================================================")

    with sync_playwright() as p:
        launch_kwargs = {
            "headless": False,
            "slow_mo": cfg.browser.slow_mo_ms,
            "accept_downloads": True,
            "args": ["--disable-blink-features=AutomationControlled", "--disable-popup-blocking"]
        }
        if cfg.browser.chromium_channel:
            launch_kwargs["channel"] = cfg.browser.chromium_channel
            
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(cfg.browser_profile_path),
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            **launch_kwargs
        )
        context.set_default_timeout(30000)
        
        # Track pages
        page_history = {}
        
        def on_page(page):
            pid = id(page)
            opener = page.opener
            opener_id = id(opener) if opener else None
            page_history[pid] = {"page": page, "opener_id": opener_id, "url_history": [], "created_at": time.time()}
            
            def log_url(frame):
                if frame == page.main_frame:
                    page_history[pid]["url_history"].append((time.time(), page.url))
            page.on("framenavigated", log_url)
            page_history[pid]["url_history"].append((time.time(), page.url))
            
            print(f"[PAGE CREATED] ID: {pid}, Opener ID: {opener_id}, Initial URL: {page.url}")

        context.on("page", on_page)
        
        page = context.pages[0] if context.pages else context.new_page()
        on_page(page) # register initial page
        
        # Ensure logged in
        print("Logging in...")
        downloader._ensure_logged_in(page, headless_value=False)
        
        url = cfg.outgoing_issued_url
        print(f"Navigating to {url}")
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        
        print("==================================================")
        print("III. XÁC NHẬN TRANG DANH SÁCH")
        pid = id(page)
        print(f"Page ID: {pid}")
        print(f"URL: {page.url}")
        parsed_url = urlparse(page.url)
        print(f"Hostname: {parsed_url.hostname}")
        print(f"Title: {page.title()}")
        
        try:
            breadcrumb = page.locator(".breadcrumb, .page-title, h1, h2, .nav-title").first.inner_text(timeout=2000)
            print(f"Breadcrumb: {breadcrumb}")
        except:
            print("Breadcrumb: Not found")
            
        print(f"Total pages in context: {len(context.pages)}")
        for ctx_page in context.pages:
            print(f" - Tab ID: {id(ctx_page)}, Title: '{ctx_page.title()}', URL: {ctx_page.url}")
            
        # Wait for table
        table = downloader._find_document_table(page)
        if not table:
            print("ERROR: Table not found!")
            return
            
        headers = downloader._extract_headers(page)
        print(f"Table headers: {headers}")
        
        # Find first row
        rows_locator = page.locator(cfg.selectors["list"].get("rows", ["table tbody tr"])[0])
        if rows_locator.count() == 0:
            print("ERROR: No rows found!")
            return
            
        row = rows_locator.nth(0)
        print("==================================================")
        print("IV. XÁC ĐỊNH CHÍNH XÁC PHẦN TỬ ĐƯỢC CLICK")
        print(f"Row index: 0")
        print(f"Bypassing record parsing")
        # Find click element
        click_el = None
        try:
            # find index of Trích yếu ignoring case
            ty_idx = next(i for i, h in enumerate(headers) if "trích yếu" in h.lower())
            cell_loc = row.locator("td").nth(ty_idx)
            print("Trích yếu cell outerHTML:")
            print(cell_loc.evaluate("el => el.outerHTML"))
            a_tags = cell_loc.locator("a")
            if a_tags.count() > 0:
                for i in range(a_tags.count()):
                    a = a_tags.nth(i)
                    txt = a.inner_text().strip()
                    if txt and txt != "" and not a.locator("i, img, span.icon").count() > 0:
                        click_el = a
                        break
                if not click_el:
                    click_el = a_tags.first
            else:
                click_el = cell_loc
        except StopIteration:
            print("ERROR: Trích yếu column not found")
            return
                
        if not click_el:
            print("ERROR: Cannot find element to click in Trích yếu column")
            return
            
        print("Click element info:")
        try:
            print(f"Tag: {click_el.evaluate('el => el.tagName')}")
            print(f"Href: {click_el.get_attribute('href')}")
            print(f"Onclick: {click_el.get_attribute('onclick')}")
            print(f"Data-url: {click_el.get_attribute('data-url')}")
            print(f"Data-href: {click_el.get_attribute('data-href')}")
            print(f"Target: {click_el.get_attribute('target')}")
            print(f"Text: {click_el.inner_text()}")
            print("OuterHTML:")
            print(click_el.evaluate("el => el.outerHTML"))
        except Exception as e:
            print(f"Error getting click info: {e}")
            
        print("==================================================")
        print("V. THEO DÕI PAGE/POPUP SAU CLICK TRÍCH YẾU")
        print("Pages before click:")
        for ctx_page in context.pages:
            print(f" - Tab ID: {id(ctx_page)}, Title: '{ctx_page.title()}', URL: {ctx_page.url}")
            
        print("Clicking...")
        click_el.scroll_into_view_if_needed()
        click_el.click()
        
        print("Waiting 10 seconds to observe pages...")
        for _ in range(10):
            time.sleep(1)
            
        print("Pages after 10 seconds:")
        detail_page = None
        for pid, info in page_history.items():
            pg = info["page"]
            if pg.is_closed():
                print(f" - Tab ID: {pid} (CLOSED)")
                continue
                
            print(f" - Tab ID: {pid}, Opener: {info['opener_id']}")
            print(f"   Current URL: {pg.url}, Title: '{pg.title()}'")
            print(f"   URL History:")
            for t, u in info["url_history"]:
                print(f"     {u}")
            
            # Check markers
            try:
                body = pg.locator("body").inner_text(timeout=1000).lower()
                has_detail = "thông tin văn bản đi" in body or "trích yếu" in body or "văn bản đính kèm" in body
                print(f"   Has detail markers: {has_detail}")
                if has_detail:
                    detail_page = pg
            except:
                print("   Could not read body")
                
        if not detail_page:
            print("ERROR: Detail page not found!")
            return
            
        print("==================================================")
        print("VI. XÁC ĐỊNH ĐÚNG NÚT “NÉN VÀ TẢI TẤT CẢ”")
        
        container = detail_page.locator("text='Văn bản đính kèm'").locator("xpath=..")
        if container.count() == 0:
            print("Could not find 'Văn bản đính kèm' container directly, searching broadly...")
            container = detail_page.locator("body")
            
        print(f"Detail Page ID: {id(detail_page)}")
        
        zip_btns = detail_page.locator("a", has_text="Nén và tải tất cả")
        if zip_btns.count() == 0:
            zip_btns = detail_page.locator("a[onclick*='zipfileDownload_']")
            
        print(f"Found {zip_btns.count()} zip download buttons")
        if zip_btns.count() > 0:
            btn = zip_btns.first
            print(f"Text: {btn.inner_text()}")
            print(f"Tag: {btn.evaluate('el => el.tagName')}")
            print(f"Href: {btn.get_attribute('href')}")
            print(f"Onclick: {btn.get_attribute('onclick')}")
            print(f"Target: {btn.get_attribute('target')}")
            print(f"Visible: {btn.is_visible()}")
            print("OuterHTML:")
            print(btn.evaluate("el => el.outerHTML"))
        else:
            print("ERROR: Zip button not found!")
            return

        print("==================================================")
        print("VII. TRACE NETWORK CHÍNH XÁC MỘT THAO TÁC")
        
        # Setup network tracking
        requests = []
        responses = []
        downloads = []
        
        def on_request(request):
            requests.append({
                "url": request.url,
                "method": request.method,
                "type": request.resource_type,
                "time": time.time()
            })
            if "zipfile" in request.url.lower() or request.method == "POST":
                print(f"[REQ] {request.method} {request.url} ({request.resource_type})")
            
        def on_response(response):
            try:
                responses.append({
                    "url": response.url,
                    "status": response.status,
                    "content-type": response.headers.get("content-type"),
                    "content-disposition": response.headers.get("content-disposition"),
                    "time": time.time()
                })
                if "zipfile" in response.url.lower() or response.headers.get("content-disposition"):
                    print(f"[RESP] {response.status} {response.url} - {response.headers.get('content-type')}")
            except:
                pass
                
        def on_download(download):
            print(f"[DOWNLOAD START] URL: {download.url}")
            downloads.append(download)
            
        for ctx_page in context.pages:
            ctx_page.on("request", on_request)
            ctx_page.on("response", on_response)
            ctx_page.on("download", on_download)
            
        print(f"Timestamp before click: {time.time()}")
        print("Clicking Zip button...")
        try:
            with detail_page.expect_download(timeout=15000) as download_info:
                btn.click()
            download = download_info.value
            if download not in downloads:
                downloads.append(download)
        except Exception as e:
            print(f"Exception while waiting for download: {e}")
            # Try just click without expecting download in case it fails or it's a fake download
            try:
                btn.click(force=True)
            except:
                pass
                
        print("Waiting 5 seconds for network traffic...")
        time.sleep(5)
        
        print("==================================================")
        print("VIII. KIỂM TRA FILE THỰC TẾ")
        
        if downloads:
            dl = downloads[0]
            print(f"Download object URL: {dl.url}")
            print(f"Suggested filename: {dl.suggested_filename}")
            
            dest_path = inv_data_root / dl.suggested_filename
            try:
                dl.save_as(str(dest_path))
                print(f"Saved to: {dest_path}")
                
                size = dest_path.stat().st_size
                print(f"Size: {size} bytes")
                
                with open(dest_path, "rb") as f:
                    content = f.read()
                    sha256 = hashlib.sha256(content).hexdigest()
                    print(f"SHA256: {sha256}")
                    print(f"Magic bytes: {content[:8].hex()}")
                    
                    if content.startswith(b"PK"):
                        print("File is ZIP")
                        import zipfile
                        try:
                            with zipfile.ZipFile(dest_path) as z:
                                print(f"Zip test result: {z.testzip()}")
                                print("Files in ZIP:")
                                for zi in z.infolist():
                                    print(f" - {zi.filename} ({zi.file_size} bytes)")
                        except Exception as e:
                            print(f"Error reading zip: {e}")
                    elif content.startswith(b"%PDF"):
                        print("File is PDF")
                    elif b"<!DOCTYPE html" in content[:200].lower() or b"<html" in content[:200].lower():
                        print("File is HTML")
                        print("First 200 bytes:", content[:200])
                    else:
                        print("File is UNKNOWN_FILE_TYPE")
            except Exception as e:
                print(f"Failed to save/analyze download: {e}")
        else:
            print("NO DOWNLOAD TRIGGERED")
            
        print("==================================================")
        print("IX. KIỂM TRA NGUYÊN NHÂN about:blank")
        
        for pid, info in page_history.items():
            pg = info["page"]
            if not pg.is_closed() and pg.url == "about:blank":
                print(f"Tab {pid} is about:blank!")
                print(f"Opener ID: {info['opener_id']}")
                print(f"Created At: {info['created_at']}")
                print(f"URL History: {info['url_history']}")
                try:
                    body = pg.locator("body").inner_html(timeout=1000)
                    print(f"Body HTML snippet: {body[:200]}")
                except:
                    print("Could not read body")
        
        print("DONE INVESTIGATION")

if __name__ == "__main__":
    run_investigation()
