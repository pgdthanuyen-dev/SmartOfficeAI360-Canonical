import sys
import time
import json
from tools.qlvb_downloader.config import load_config
from tools.qlvb_downloader.downloader import QLVBDownloader
from tools.qlvb_downloader.paths import get_app_data_dir

def run_tests():
    print("=== CHẠY KIỂM THỬ BATCH QC-003 ===")
    config = load_config()
    config.use_fixed_urls = True
    config.browser.headless = False
    config.download.max_items_per_run = 1
    config.download.max_pages_per_direction = 1
    config.browser.timeout_ms = 180000
    config.download.dry_run = False
    config.save()
    print("Đã lưu cấu hình.")

    dl = QLVBDownloader(config)
    try:
        summary = dl.run(headless=False)
        print("\n=== KẾT QUẢ BATCH ===")
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        
        with open("batch_result.json", "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Lỗi khi chạy batch: {e}")

if __name__ == "__main__":
    run_tests()
