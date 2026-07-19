import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import json
from tools.qlvb_downloader.config import load_config
from tools.qlvb_downloader.downloader import QLVBDownloader

def check_urls():
    cfg = load_config()
    dl = QLVBDownloader(cfg)
    
    # We will test the URLs configured
    urls = [
        ("incoming_pending", cfg.incoming_pending_url),
        ("incoming_processed", cfg.incoming_processed_url),
        ("outgoing_issued", cfg.outgoing_issued_url),
    ]
    
    results = {}
    for link_type, url in urls:
        if not url:
            print(f"\n--- {link_type} ---")
            print("URL is empty.")
            continue
            
        print(f"\n--- Checking {link_type} ---")
        print(f"URL: {url[:80]}...")
        
        try:
            res = dl.validate_fixed_qlvb_url(url, link_type)
            print(json.dumps(res, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"Error checking {link_type}: {e}")

if __name__ == "__main__":
    check_urls()
