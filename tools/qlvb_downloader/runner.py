from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.qlvb_downloader.config import VERSION, load_config
from tools.qlvb_downloader.downloader import QLVBDownloader


def parse_bool(value: str | bool | None) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    value = value.strip().lower()
    if value in ["1", "true", "yes", "y", "co", "có", "bat", "bật"]:
        return True
    if value in ["0", "false", "no", "n", "khong", "không", "tat", "tắt"]:
        return False
    raise argparse.ArgumentTypeError("Giá trị headless phải là true/false")


def main() -> None:
    import sys
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    parser = argparse.ArgumentParser(description=f"Smart Office AI 360 - QLVB Downloader {VERSION}")
    parser.add_argument("--config", default="", help="Đường dẫn file cấu hình JSON")
    parser.add_argument("--directions", default="both", choices=["incoming", "outgoing", "both"], help="Tải văn bản đến/đi/cả hai")
    parser.add_argument("--headless", default=None, type=parse_bool, help="true: chạy ẩn, false: hiện trình duyệt")
    parser.add_argument("--max-items", default=None, type=int, help="Số dòng tối đa mỗi lần chạy")
    parser.add_argument("--print-config", action="store_true", help="Chỉ kiểm tra và in cấu hình đã chuẩn hóa, không mở trình duyệt")
    parser.add_argument("--dry-run", default=None, type=parse_bool, help="true: chỉ quét metadata, không tải file")
    parser.add_argument("--login-only", action="store_true", help="Chỉ mở trình duyệt để người dùng đăng nhập/giải captcha rồi thoát")
    args = parser.parse_args()

    config_path = Path(args.config) if args.config else None
    cfg = load_config(config_path)
    print(f"Config path: {config_path or 'auto-discovered'}")
    print(f"Data Root: {cfg.root_path}")
    print(f"Profile path: {cfg.browser_profile_path}")
    
    if args.dry_run is not None:
        cfg.download.dry_run = args.dry_run

    if args.print_config:
        safe = {
            "version": VERSION,
            "qlvb_base_url": cfg.qlvb_base_url,
            "login_url": cfg.login_url,
            "username": cfg.username,
            "password_saved": bool(cfg.password),
            "incoming_pending_url": cfg.incoming_pending_url,
            "incoming_processed_url": cfg.incoming_processed_url,
            "outgoing_issued_url": cfg.outgoing_issued_url,
            "save_root": str(cfg.root_path),
            "browser_profile": str(cfg.browser_profile_path),
            "download": cfg.download.__dict__,
            "browser": {k: v for k, v in cfg.browser.__dict__.items() if k != "password"},
        }
        print(json.dumps(safe, ensure_ascii=False, indent=2))
        return

    directions = ["incoming", "outgoing"] if args.directions == "both" else [args.directions]

    try:
        downloader = QLVBDownloader(cfg)
        summary = downloader.run(directions=directions, headless=args.headless, max_items=args.max_items, login_only=args.login_only)
        
        # Calculate strict status
        total_processed = 0
        total_errors = 0
        total_downloaded = 0
        all_empty = True
        
        for k, v in summary.get('directions', {}).items():
            st = v.get('status', '')
            if st != 'EMPTY':
                all_empty = False
            
            p = v.get('processed', 0)
            e = len(v.get('errors', []))
            if st == 'ERROR':
                e += 1
            d = v.get('downloaded_files', 0)
            
            total_processed += p
            total_errors += e
            total_downloaded += d

        overall_status = summary.get('status', 'DONE')
        if summary.get('status') == 'FAILED':
            overall_status = 'FAILED'
        elif all_empty:
            overall_status = 'EMPTY'
        elif total_errors > 0:
            if total_processed == total_errors and total_downloaded == 0:
                overall_status = 'FAILED'
            else:
                overall_status = 'PARTIAL_FAILED'
        elif total_processed > 0 and total_downloaded == 0 and total_errors > 0:
             overall_status = 'FAILED'
        elif total_processed == 0 and not all_empty:
             overall_status = 'FAILED'

        print(f"\n=== SMART OFFICE AI 360 - QLVB DOWNLOADER {VERSION} SUMMARY ===")
        print(f"Tổng quan: {overall_status}")
        for k, v in summary.get('directions', {}).items():
            print(f"- Luồng: {k}")
            print(f"  + Lọc URL: {mask_url_query(v.get('url', ''))}")
            print(f"  + Xử lý: {v.get('processed', 0)}")
            print(f"  + Bỏ qua (trùng): {v.get('skipped_existing', 0)}")
            print(f"  + Gói ZIP đã tải: {v.get('downloaded_archives', 0)}")
            print(f"  + Tệp đính kèm đã giải nén: {v.get('extracted_files', 0)}")
            print(f"  + Tổng tệp đã tạo: {v.get('materialized_files', 0)}")
            if v.get('errors'):
                print(f"  + Lỗi: {len(v.get('errors'))}")
        print("\nHoàn tất chạy tiến trình.")
        
        import sys
        if overall_status == 'FAILED':
            sys.exit(1)
        elif overall_status == 'PARTIAL_FAILED':
            sys.exit(2)
        else:
            sys.exit(0)
    except SystemExit:
        raise
    except Exception as e:
        err_msg = str(e)
        import sys
        is_login_err = any(w in err_msg.lower() for w in ["đăng nhập", "captcha", "otp", "login", "mật khẩu", "mat khau", "password"])
        
        print(f"\n=== SMART OFFICE AI 360 - QLVB DOWNLOADER {VERSION} FAILED ===")
        if is_login_err:
            print("TRẠNG THÁI: Chưa đăng nhập thành công")
        else:
            print("TRẠNG THÁI: Lỗi thực thi")
        print(f"CHI TIẾT: {err_msg}")
        sys.exit(1)


if __name__ == "__main__":
    main()
