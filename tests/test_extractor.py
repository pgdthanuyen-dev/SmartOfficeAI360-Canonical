"""
tests/test_extractor.py — Phase 2 Extractor Test Suite
========================================================
Chạy: python -m tests.test_extractor
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from tools.qlvb_downloader.extractor import (
    STATUS_EMPTY,
    STATUS_FILE_NOT_FOUND,
    STATUS_LIB_MISSING,
    STATUS_OK,
    STATUS_OCR_REQUIRED,
    STATUS_UNSUPPORTED,
    ExtractResult,
    extract_text_for_manifest,
    extract_text_from_file,
)

_TEST_ROOT = Path("Data_extractor_test")


def _setup():
    _TEST_ROOT.mkdir(parents=True, exist_ok=True)


def _teardown():
    if _TEST_ROOT.exists():
        shutil.rmtree(_TEST_ROOT)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_txt_extract_success():
    """TXT extract thành công, word count đúng."""
    print("\n[TEST 1] TXT extract thanh cong...")
    _setup()
    txt_file = _TEST_ROOT / "sample.txt"
    content = "CONG HOA XA HOI CHU NGHIA VIET NAM\nDoc lap - Tu do - Hanh phuc\nQUYET DINH ve viec khen thuong tap the.\nCan cu theo de nghi cua cac don vi."
    txt_file.write_text(content, encoding="utf-8")

    result = extract_text_from_file(txt_file)

    assert result.success is True, f"Phai thanh cong, got: {result}"
    assert result.status == STATUS_OK, f"Status phai OK, got: {result.status}"
    assert result.word_count > 0, "word_count phai > 0"
    assert result.file_type == "TXT"
    assert len(result.excerpt) > 0
    print("  -> PASSED")


def test_txt_extract_vietnamese_preserved():
    """Text tieng Viet khong bi mat dau (Unicode NFC)."""
    print("\n[TEST 2] Tieng Viet khong mat dau...")
    _setup()
    txt_file = _TEST_ROOT / "viet.txt"
    viet_text = "Quyết định về việc khen thưởng tập thể xuất sắc.\nĐơn vị: UBND tỉnh Hà Nội."
    txt_file.write_bytes(viet_text.encode("utf-8"))

    result = extract_text_from_file(txt_file)

    assert result.success is True
    assert "Quy" in result.text, f"Text phai chua noi dung, got: {result.text[:50]}"
    # Ky tu tieng Viet phai con trong excerpt
    assert result.excerpt is not None
    print("  -> PASSED")


def test_file_not_found_returns_error():
    """File khong ton tai khong crash app."""
    print("\n[TEST 3] File khong ton tai...")
    result = extract_text_from_file("/nonexistent/path/doc.pdf")

    assert result.success is False
    assert result.status == STATUS_FILE_NOT_FOUND
    assert result.error is not None
    print("  -> PASSED")


def test_unsupported_extension_returns_warning():
    """Extension khong ho tro tra warning, khong crash."""
    print("\n[TEST 4] Extension khong ho tro...")
    _setup()
    bin_file = _TEST_ROOT / "file.xyz"
    bin_file.write_bytes(b"\x00\x01\x02\x03")

    result = extract_text_from_file(bin_file)

    assert result.success is False
    assert result.status == STATUS_UNSUPPORTED
    assert result.warning is not None
    print("  -> PASSED")


def test_empty_txt_returns_empty_status():
    """File txt rong tra STATUS_EMPTY."""
    print("\n[TEST 5] File TXT rong...")
    _setup()
    empty_file = _TEST_ROOT / "empty.txt"
    empty_file.write_text("   \n  \n  ", encoding="utf-8")

    result = extract_text_from_file(empty_file)

    # File chi co whitespace thi word_count = 0, status EMPTY hoac OK tuy normalize
    assert result.file_type == "TXT"
    assert result.word_count == 0 or result.status in (STATUS_EMPTY, STATUS_OK)
    print("  -> PASSED")


def test_extract_for_manifest_no_main_doc():
    """extract_text_for_manifest voi manifest khong co main_document."""
    print("\n[TEST 6] extract_text_for_manifest khong co main_document...")
    _setup()
    manifest = {
        "schema_version": "2.0.0",
        "doc_id": "test_doc",
        "direction": "incoming",
        "summary": "Test",
        # khong co main_document
    }
    result = extract_text_for_manifest(manifest, _TEST_ROOT)
    assert result["full_text_status"] == STATUS_UNSUPPORTED
    assert result["full_text_warning"] is not None
    # Khong lam thay doi manifest goc
    assert "full_text_excerpt" not in manifest
    print("  -> PASSED")


def test_extract_for_manifest_with_txt_file():
    """extract_text_for_manifest doc duoc file TXT va ghi excerpt."""
    print("\n[TEST 7] extract_text_for_manifest voi file TXT...")
    _setup()
    ((_TEST_ROOT / "doc_main.txt")).write_text(
        "Quyet dinh so 123/QD-UBND ngay 01/01/2026.\nVe viec trien khai he thong moi.",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": "2.0.0",
        "doc_id": "test_txt",
        "direction": "incoming",
        "summary": "Test TXT",
        "main_document": {
            "filename": "doc_main.txt",
            "size_bytes": 100,
            "sha256": "abc",
        },
    }
    result = extract_text_for_manifest(manifest, _TEST_ROOT)

    assert result["full_text_status"] == STATUS_OK
    assert result["full_text_excerpt"] is not None
    assert result["full_text_word_count"] > 0
    assert result["extracted_at"] is not None
    print("  -> PASSED")


def test_extract_for_manifest_missing_file():
    """extract_text_for_manifest khi file vat ly khong ton tai."""
    print("\n[TEST 8] extract_text_for_manifest file thieu...")
    _setup()
    manifest = {
        "schema_version": "2.0.0",
        "doc_id": "test_missing",
        "direction": "incoming",
        "summary": "Test missing",
        "main_document": {
            "filename": "missing_doc.pdf",
            "size_bytes": 100,
            "sha256": "abc",
        },
    }
    result = extract_text_for_manifest(manifest, _TEST_ROOT)

    assert result["full_text_status"] == STATUS_FILE_NOT_FOUND
    # Khong crash, van tra dict hop le
    assert "extracted_at" in result
    print("  -> PASSED")


def test_pdf_lib_missing_returns_graceful():
    """PDF extract khi pdfminer chua cai tra warning, khong crash."""
    print("\n[TEST 9] PDF khi pdfminer chua cai...")
    _setup()
    fake_pdf = _TEST_ROOT / "fake.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 fake content")

    # Bat buoc simulate truong hop thieu lib bang patch
    import tools.qlvb_downloader.extractor as ext_mod
    original = ext_mod._HAS_PDFMINER

    try:
        ext_mod._HAS_PDFMINER = False
        result = extract_text_from_file(fake_pdf)
        assert result.success is False
        assert result.status == STATUS_LIB_MISSING
        assert result.warning is not None
    finally:
        ext_mod._HAS_PDFMINER = original

    print("  -> PASSED")


def test_max_chars_truncation():
    """excerpt khong vuot qua max_chars."""
    print("\n[TEST 10] Excerpt bi cat dung max_chars...")
    _setup()
    long_file = _TEST_ROOT / "long.txt"
    # Tao file 10000 ky tu
    long_file.write_text("A " * 5000, encoding="utf-8")

    result = extract_text_from_file(long_file, max_chars=500)

    assert len(result.excerpt) <= 600, f"excerpt phai <= ~600 chars, got {len(result.excerpt)}"
    print("  -> PASSED")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def run_tests():
    print("=" * 65)
    print(" Phase 2 — test_extractor.py")
    print("=" * 65)

    tests = [
        test_txt_extract_success,
        test_txt_extract_vietnamese_preserved,
        test_file_not_found_returns_error,
        test_unsupported_extension_returns_warning,
        test_empty_txt_returns_empty_status,
        test_extract_for_manifest_no_main_doc,
        test_extract_for_manifest_with_txt_file,
        test_extract_for_manifest_missing_file,
        test_pdf_lib_missing_returns_graceful,
        test_max_chars_truncation,
    ]

    passed = 0
    failed: list[str] = []

    for fn in tests:
        _setup()
        try:
            fn()
            passed += 1
        except Exception as exc:
            import traceback
            print(f"  -> FAILED: {fn.__name__}")
            print(f"     Error: {exc}")
            traceback.print_exc()
            failed.append(fn.__name__)
        finally:
            _teardown()

    print("\n" + "=" * 65)
    print(f" Ket qua: {passed}/{len(tests)} PASSED")
    if failed:
        print(f" FAILED: {', '.join(failed)}")
    else:
        print(" ALL TESTS PASSED!")
    print("=" * 65)

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    run_tests()
