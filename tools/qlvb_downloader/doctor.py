from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

# Guided imports for PyInstaller packaging dependency tracing
try:
    import playwright
except ImportError:
    pass
try:
    import tkinter
except ImportError:
    pass

from tools.qlvb_downloader.config import VERSION, find_config_file, load_config, project_root
from tools.qlvb_downloader.paths import configure_bundled_playwright

REQUIRED_DIRS = [
    "Data/config",
    "Data/files/incoming",
    "Data/files/outgoing",
    "Data/queue/incoming",
    "Data/queue/outgoing",
    "Data/logs/errors",
    "Data/logs/page_probe",
    "Data/reports",
    "Data/index",
    "Data/support_packages",
    "Data/runtime/playwright_profile",
]

PLACEHOLDER_VALUES = [
    "https://QLVB_CUA_DON_VI",
    "https://QLVB_CUA_DON_VI/login",
    "https://QLVB_CUA_DON_VI/van-ban-den",
    "https://QLVB_CUA_DON_VI/van-ban-di",
    "TEN_DANG_NHAP_CUA_SEP",
]


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def ensure_dirs(root: Path) -> list[dict]:
    checks = []
    for rel in REQUIRED_DIRS:
        path = root / rel
        path.mkdir(parents=True, exist_ok=True)
        checks.append({"name": rel, "ok": path.exists(), "detail": str(path)})
    return checks


def module_exists(name: str) -> bool:
    import importlib
    try:
        importlib.import_module(name)
        return True
    except Exception:
        return False


def safe_url(value: str) -> bool:
    if not value:
        return False
    parsed = urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def mask_config_dict(data: dict) -> dict:
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            lk = str(k).lower()
            if any(x in lk for x in ["password", "mat_khau", "pass", "token", "secret"]):
                out[k] = "***" if v else ""
            elif isinstance(v, dict):
                out[k] = mask_config_dict(v)
            elif isinstance(v, list):
                out[k] = [mask_config_dict(i) if isinstance(i, dict) else i for i in v]
            else:
                out[k] = v
        return out
    return data


def read_json_safely(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def check_config(root: Path) -> tuple[list[dict], dict]:
    checks = []
    config_path = find_config_file()
    raw = {}
    if not config_path:
        example = root / "Data/config/qlvb_downloader_config.example.json"
        target = root / "Data/config/qlvb_downloader_config.json"
        if example.exists() and not target.exists():
            shutil.copyfile(example, target)
            config_path = target
            checks.append({
                "name": "Tạo cấu hình mặc định",
                "ok": True,
                "level": "WARN",
                "detail": f"Đã tạo {target}. Sếp cần mở mục 2 để thay thông tin thật.",
            })
        else:
            checks.append({"name": "File cấu hình", "ok": False, "level": "ERROR", "detail": "Chưa có Data/config/qlvb_downloader_config.json"})
            return checks, {}

    raw = read_json_safely(config_path)
    checks.append({"name": "File cấu hình", "ok": True, "level": "OK", "detail": str(config_path)})

    try:
        cfg = load_config(config_path)
    except Exception as exc:
        checks.append({"name": "Đọc cấu hình", "ok": False, "level": "ERROR", "detail": str(exc)})
        return checks, raw

    fields = [
        ("Địa chỉ QLVB", cfg.qlvb_base_url or cfg.login_url, True, "ERROR"),
        ("Link incoming_pending", cfg.incoming_pending_url, True, "WARN"),
        ("Link incoming_processed", cfg.incoming_processed_url, True, "WARN"),
        ("Link outgoing_issued", cfg.outgoing_issued_url, True, "WARN"),
    ]
    url_ok_map = {}
    for label, value, is_url, fail_level in fields:
        value = str(value or "").strip()
        is_placeholder = value in PLACEHOLDER_VALUES or "QLVB_CUA_DON_VI" in value or "TEN_DANG_NHAP" in value
        ok = bool(value) and not is_placeholder and (safe_url(value) if is_url else True)
        url_ok_map[label] = ok
        checks.append({
            "name": label,
            "ok": ok,
            "level": "OK" if ok else fail_level,
            "detail": "Đã khai báo" if ok else "Chưa khai báo đúng/đang dùng giá trị mẫu",
        })

    has_any_list_url = any(
        url_ok_map.get(name, False)
        for name in ["Link incoming_pending", "Link incoming_processed", "Link outgoing_issued"]
    )
    checks.append({
        "name": "Tối thiểu một danh sách QLVB",
        "ok": has_any_list_url,
        "level": "OK" if has_any_list_url else "ERROR",
        "detail": "Có thể chạy tải theo link đã khai báo" if has_any_list_url else "Cần khai báo ít nhất link văn bản đến hoặc link văn bản đi",
    })

    writable_root = cfg.root_path
    try:
        writable_root.mkdir(parents=True, exist_ok=True)
        test_file = writable_root / ".write_test.tmp"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
        writable = True
        detail = str(writable_root)
    except Exception as exc:
        writable = False
        detail = str(exc)
    checks.append({"name": "Quyền ghi thư mục Data", "ok": writable, "level": "OK" if writable else "ERROR", "detail": detail})

    if cfg.password:
        source_str = getattr(cfg, "password_source", "CONFIG")
        if source_str == "ENV":
            checks.append({"name": "Mật khẩu", "ok": True, "level": "OK", "detail": "Đã cung cấp (Nguồn: ENV)"})
        elif source_str == "CONFIG":
            checks.append({"name": "Mật khẩu", "ok": True, "level": "WARN", "detail": "Đã cung cấp (Nguồn: CONFIG). Khuyến nghị đổi sang ENV để bảo mật."})
        else:
            checks.append({"name": "Mật khẩu", "ok": True, "level": "OK", "detail": "Đã cung cấp (Nguồn: CONFIG)"})
    else:
        checks.append({"name": "Mật khẩu", "ok": True, "level": "OK", "detail": "Chưa cung cấp (Nguồn: MANUAL - Sẽ dùng đăng nhập thủ công/lưu phiên)"})

    return checks, raw


def check_environment(root: Path, launch_browser: bool = False) -> list[dict]:
    bundled_browser = configure_bundled_playwright()
    checks = []
    if bundled_browser:
        checks.append({"name": "Chromium dong goi", "ok": True, "level": "OK", "detail": str(bundled_browser)})
    py_ok = sys.version_info >= (3, 10)
    checks.append({
        "name": "Python",
        "ok": py_ok,
        "level": "OK" if py_ok else "ERROR",
        "detail": f"{sys.version.split()[0]} - {sys.executable}",
    })

    try:
        import pip  # noqa: F401
        pip_ok = True
    except Exception:
        pip_ok = False
    checks.append({"name": "pip", "ok": pip_ok, "level": "OK" if pip_ok else "ERROR", "detail": "Đã có pip" if pip_ok else "Chưa có pip"})

    for mod in ["playwright", "tkinter"]:
        ok = module_exists(mod)
        checks.append({"name": f"Thư viện {mod}", "ok": ok, "level": "OK" if ok else "ERROR", "detail": "Đã cài" if ok else "Chưa cài"})

    if module_exists("playwright"):
        checks.append({"name": "Playwright CLI", "ok": True, "level": "OK", "detail": "Đã có thư viện Playwright; nếu chưa mở được Chromium hãy chạy cài đặt lần đầu."})

        if launch_browser:
            try:
                from playwright.sync_api import sync_playwright
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    browser.close()
                checks.append({"name": "Chromium Playwright", "ok": True, "level": "OK", "detail": "Mở thử trình duyệt thành công"})
            except Exception as exc:
                checks.append({"name": "Chromium Playwright", "ok": False, "level": "ERROR", "detail": "Chưa cài browser hoặc lỗi mở Chromium: " + str(exc)[:500]})
    else:
        checks.append({"name": "Chromium Playwright", "ok": False, "level": "ERROR", "detail": "Cài thư viện trước rồi chạy python -m playwright install chromium"})

    checks.append({"name": "Hệ điều hành", "ok": True, "level": "OK", "detail": f"{platform.system()} {platform.release()} ({platform.machine()})"})
    return checks


def write_reports(root: Path, payload: dict) -> None:
    logs = root / "Data/logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "environment_check_report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "SMART OFFICE AI 360 - BAO CAO KIEM TRA MOI TRUONG/CAU HINH",
        f"Phien ban: {VERSION}",
        f"Thoi gian: {payload.get('time')}",
        "",
    ]
    for group in ["environment", "directories", "config"]:
        lines.append(f"=== {group.upper()} ===")
        for c in payload.get(group, []):
            mark = "[OK]" if c.get("ok") else "[LOI]"
            level = c.get("level", "")
            lines.append(f"{mark} {c.get('name')}: {c.get('detail')} {('(' + level + ')') if level else ''}")
        lines.append("")
    (logs / "environment_check_report.txt").write_text("\n".join(lines), encoding="utf-8")


def create_support_package(root: Path) -> Path:
    out_dir = root / "Data/support_packages"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"support_qlvb_{now_stamp()}.zip"
    candidates = [
        root / "Data/logs/environment_check_report.txt",
        root / "Data/logs/environment_check_report.json",
        root / "Data/logs/qlvb_downloader_last_run_summary.json",
        root / "Data/logs/qlvb_downloader_last_run_report.html",
    ]
    config_path = find_config_file()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in candidates:
            if p.exists():
                z.write(p, p.relative_to(root))
        if config_path and config_path.exists():
            raw = read_json_safely(config_path)
            masked = mask_config_dict(raw)
            z.writestr("Data/config/qlvb_downloader_config_masked.json", json.dumps(masked, ensure_ascii=False, indent=2))
        errors = root / "Data/logs/errors"
        if errors.exists():
            count = 0
            for p in sorted(errors.rglob("*"), key=lambda x: x.stat().st_mtime if x.is_file() else 0, reverse=True):
                if p.is_file() and count < 80:
                    z.write(p, p.relative_to(root))
                    count += 1
        probe = root / "Data/logs/page_probe"
        if probe.exists():
            for p in probe.rglob("*"):
                if p.is_file():
                    z.write(p, p.relative_to(root))
    return out


def print_checks(title: str, checks: list[dict]) -> None:
    print("\n" + title)
    print("-" * len(title))
    for c in checks:
        mark = "[OK]" if c.get("ok") else "[LOI]"
        level = c.get("level", "")
        print(f"{mark} {c.get('name')}: {c.get('detail')} {('(' + level + ')') if level else ''}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description=f"Smart Office AI 360 - First Run Guard {VERSION}")
    parser.add_argument("--prepare", action="store_true", help="Tạo thư mục và cấu hình mẫu nếu thiếu")
    parser.add_argument("--check", action="store_true", help="Kiểm tra môi trường và cấu hình")
    parser.add_argument("--launch-browser-check", action="store_true", help="Mở thử Chromium Playwright")
    parser.add_argument("--support-package", action="store_true", help="Xuất gói log/lỗi để gửi kỹ thuật")
    args = parser.parse_args()

    root = project_root()
    payload = {"version": VERSION, "time": datetime.now().isoformat(timespec="seconds"), "root": str(root)}

    if args.prepare or args.check:
        payload["directories"] = ensure_dirs(root)
    else:
        payload["directories"] = []

    if args.support_package:
        # Always update the latest report before packing, but do not force browser launch.
        payload["environment"] = check_environment(root, launch_browser=False)
        payload["config"], raw = check_config(root)
        write_reports(root, payload)
        out = create_support_package(root)
        print(f"[OK] Da xuat goi chan doan: {out}")
        return

    payload["environment"] = check_environment(root, launch_browser=args.launch_browser_check)
    payload["config"], raw = check_config(root)
    write_reports(root, payload)

    print_checks("KIEM TRA MOI TRUONG", payload["environment"])
    print_checks("KIEM TRA THU MUC", payload["directories"])
    print_checks("KIEM TRA CAU HINH", payload["config"])
    print(f"\nBao cao da luu: {root / 'Data/logs/environment_check_report.txt'}")

    hard_errors = [c for group in ["environment", "config"] for c in payload.get(group, []) if not c.get("ok") and c.get("level") == "ERROR"]
    if hard_errors:
        sys.exit(2)


if __name__ == "__main__":
    main()
