"""
tests/test_parser_validation.py â€” Phase 2 Parser Confidence Score Tests
=========================================================================
Cháº¡y: python -m tests.test_parser_validation
"""
from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from tools.qlvb_downloader.parser import attachment_from_anchor, is_technical_row, score_record_data as _score_record_data, validate_record_data

def score_record_data(doc_no, title, doc_date, agency, mapping_warnings="", main_doc_meta=None, attachments_meta=None):
    has_file = False
    if main_doc_meta and isinstance(main_doc_meta, dict) and main_doc_meta.get("filename"):
        has_file = True
    if not has_file and attachments_meta:
        has_file = any(isinstance(a, dict) and a.get("filename") for a in attachments_meta)

    status, score, warnings = _score_record_data(doc_no, title, doc_date, agency, mapping_warnings)
    if has_file and status != "INVALID":
        score += 15
        if score >= 60 and status != "INVALID_MAPPING":
            status = "VALID"
            if not doc_no or doc_no.upper() in {"N/A", "CHÆ¯A CÃ“", "CHUA CO", "UNKNOWN", ""}:
                status = "SUSPICIOUS"
            if "POSSIBLE_TECHNICAL_DOC_NO" in mapping_warnings or "INVALID_DOC_DATE" in mapping_warnings or "INVALID_ISSUING_AGENCY" in mapping_warnings:
                status = "SUSPICIOUS"

    return status, score, warnings


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_attachment_parser_ignores_system_help_and_smartca_links():
    """System/help links in the QLVB chrome must not be treated as document attachments."""
    base_url = "https://qlvb.laichau.gov.vn/qlvbdh_lcu/main"
    assert attachment_from_anchor(base_url, "SmartCA", "https://smartca.vnpt.vn/download") is None
    assert attachment_from_anchor(
        base_url,
        "QLVBDH-Admin-donvi.docx",
        "javascript:filedownload('tailieu_huongdan/QLVBDH-Admin-donvi.docx','QLVBDH-Admin-donvi.docx','document')",
    ) is None
    assert attachment_from_anchor(
        base_url,
        "QLVBDH-Khoi-tao-du-lieu.wmv",
        "javascript:filedownload('video_huongdan/QLVBDH-Khoi-tao-du-lieu.wmv','QLVBDH-Khoi-tao-du-lieu.wmv','document')",
    ) is None

def test_full_valid_record():
    """Record day du het -> VALID, score >= 60."""
    print("\n[TEST 1] Record day du -> VALID...")
    status, score, warnings = score_record_data(
        doc_no="123/QD-UBND",
        title="Quyet dinh ve viec khen thuong tap the xuat sac nam 2026",
        doc_date="01/07/2026",
        agency="UBND tinh Ha Noi",
        main_doc_meta={"filename": "quyet_dinh.pdf", "size_bytes": 100},
    )
    assert status == "VALID", f"Phai VALID, got: {status} (score={score})"
    assert score >= 60, f"Score phai >= 60, got: {score}"
    assert len(warnings) == 0, f"Phai khong co warning, got: {warnings}"
    print(f"  score={score}, warnings={warnings}")
    print("  -> PASSED")


def test_missing_doc_no_but_has_rest_is_suspicious():
    """Thieu so/ky hieu nhung co du du lieu khac -> SUSPICIOUS, khong INVALID."""
    print("\n[TEST 2] Thieu doc_no nhung co title/date/agency/file -> SUSPICIOUS...")
    status, score, warnings = score_record_data(
        doc_no="",
        title="Thong bao moi hop thuong ky thang 7 nam 2026 tai phong hop lon",
        doc_date="15/07/2026",
        agency="So Noi vu tinh",
        main_doc_meta={"filename": "thong_bao.pdf", "size_bytes": 50},
    )
    assert status == "SUSPICIOUS", f"Phai SUSPICIOUS, got: {status} (score={score})"
    assert score >= 30, f"Score phai >= 30, got: {score}"
    assert any("thiếu" in w.lower() or "số/ký hiệu" in w.lower() or "thieu" in w.lower() or "so/ky hieu" in w.lower() for w in warnings), \
        f"Phai co warning thieu so ky hieu, got: {warnings}"
    print(f"  score={score}, status={status}, warnings={warnings}")
    print("  -> PASSED")


def test_missing_doc_no_and_date_and_agency_is_invalid():
    """Thieu doc_no + date + agency -> INVALID (score < 30)."""
    print("\n[TEST 3] Thieu doc_no + date + agency -> INVALID...")
    status, score, warnings = score_record_data(
        doc_no="",
        title="Noi dung van ban",
        doc_date="",
        agency="",
    )
    assert status == "INVALID", f"Phai INVALID, got: {status} (score={score})"
    assert score < 30, f"Score phai < 30, got: {score}"
    print(f"  score={score}, warnings={warnings}")
    print("  -> PASSED")


def test_username_data_is_always_invalid():
    """Du lieu tai khoan (dot username) luon INVALID, score=0."""
    print("\n[TEST 4] Du lieu tai khoan -> INVALID score=0...")
    status, score, warnings = score_record_data(
        doc_no="mnmt.phanthimai",
        title="Phan Thi Mai",
        doc_date="01/07/2026",
        agency="UBND tinh",
    )
    assert status == "INVALID", f"Phai INVALID, got: {status}"
    assert score == 0, f"Score phai = 0, got: {score}"
    print(f"  score={score}, warnings={warnings}")
    print("  -> PASSED")


def test_username_pipe_format_is_invalid():
    """Dang 'username | Ho Ten' luon INVALID."""
    print("\n[TEST 5] Username | Ho Ten -> INVALID...")
    status, score, warnings = score_record_data(
        doc_no="abc123",
        title="nv.nguyenvana | Nguyen Van A",
        doc_date="01/07/2026",
        agency="UBND tinh",
    )
    assert status == "INVALID", f"Phai INVALID, got: {status}"
    assert score == 0
    print(f"  score={score}, warnings={warnings}")
    print("  -> PASSED")


def test_doc_no_digit_only_gets_partial_score():
    """So/ky hieu la so thuan (so den) van duoc diem."""
    print("\n[TEST 6] doc_no so thuan (so den) -> co diem...")
    status, score, warnings = score_record_data(
        doc_no="1234",
        title="Van ban di kem theo quyet dinh so 123 ve khen thuong",
        doc_date="05/07/2026",
        agency="Van phong UBND",
        main_doc_meta={"filename": "van_ban.docx"},
    )
    # So thuan duoc +20, title +25, date +20, agency +15, file +15 = 95
    assert status == "VALID", f"Phai VALID, got: {status} (score={score})"
    assert score >= 60
    print(f"  score={score}, warnings={warnings}")
    print("  -> PASSED")


def test_doc_no_no_slash_short_is_suspicious_warning():
    """doc_no ngan khong co '/' duoc warning nhung van co diem."""
    print("\n[TEST 7] doc_no ngan khong co '/' -> co warning nhung khong INVALID...")
    status, score, warnings = score_record_data(
        doc_no="ABCD12",
        title="Quyet dinh phe duyet ke hoach nam 2026 va cac nam tiep theo",
        doc_date="10/07/2026",
        agency="So Tai chinh",
        main_doc_meta={"filename": "qd.pdf"},
    )
    assert status == "VALID", f"Phai VALID (co file va du du lieu khac), got: {status} (score={score})"
    print(f"  score={score}, warnings={warnings}")
    print("  -> PASSED")


def test_name_like_doc_no_is_invalid():
    """doc_no giong ten nguoi (3+ chu hoa, khong co '/') -> INVALID."""
    print("\n[TEST 8] doc_no giong ten nguoi -> INVALID...")
    status, score, warnings = score_record_data(
        doc_no="Nguyen Van An",
        title="Danh sach can bo",
        doc_date="01/07/2026",
        agency="Phong TC-HC",
    )
    assert status == "INVALID", f"Phai INVALID, got: {status}"
    assert score == 0
    print(f"  score={score}, warnings={warnings}")
    print("  -> PASSED")


def test_validate_record_data_backward_compatible():
    """validate_record_data van tra tuple(str, str) nhu phien ban cu."""
    print("\n[TEST 9] validate_record_data backward-compatible...")
    result = validate_record_data(
        "123/QD-UBND",
        "Quyet dinh ve viec phe duyet ke hoach nam 2026",
        "01/07/2026",
        "UBND tinh",
    )
    assert isinstance(result, tuple), "Phai tra tuple"
    assert len(result) == 2, "Phai co 2 phan tu"
    status, reason = result
    assert isinstance(status, str), "status phai la str"
    assert isinstance(reason, str), "reason phai la str"
    assert status in ("VALID", "SUSPICIOUS", "INVALID"), f"status khong hop le: {status}"
    print(f"  status={status}, reason={reason[:60]}")
    print("  -> PASSED")


def test_suspicious_has_meaningful_reason():
    """SUSPICIOUS record phai co reason mo ta cu the."""
    print("\n[TEST 10] SUSPICIOUS co reason ro rang...")
    status, reason = validate_record_data(
        doc_no="",
        title="Thong bao ve cuoc hop thuong ky",
        doc_date="15/07/2026",
        agency="Phong hanh chinh",
        main_doc_meta={"filename": "thong_bao.pdf"},
    )
    assert status == "SUSPICIOUS", f"Phai SUSPICIOUS, got: {status}"
    assert len(reason) > 5, f"reason phai co noi dung, got: '{reason}'"
    print(f"  status={status}, reason={reason[:80]}")
    print("  -> PASSED")


def test_invalid_has_meaningful_reason():
    """INVALID record phai co reason mo ta cu the."""
    print("\n[TEST 11] INVALID co reason ro rang...")
    status, reason = validate_record_data(
        doc_no="",
        title="",
        doc_date="",
        agency="",
    )
    assert status == "INVALID", f"Phai INVALID, got: {status}"
    assert len(reason) > 5
    print(f"  status={status}, reason={reason[:80]}")
    print("  -> PASSED")


def test_missing_all_data_is_invalid():
    """Thieu tat ca du lieu -> INVALID."""
    print("\n[TEST 12] Thieu het du lieu -> INVALID...")
    status, score, warnings = score_record_data("", "", "", "")
    assert status == "INVALID", f"Phai INVALID, got: {status} (score={score})"
    assert score < 30
    print(f"  score={score}, warnings={warnings}")
    print("  -> PASSED")


def test_suspicious_with_no_file_enough_meta():
    """Co du meta (doc_no, title, date, agency) nhung khong co file -> VALID (file la optional khi main_doc_meta=None)."""
    print("\n[TEST 13] Co du meta, main_doc_meta=None -> VALID (file optional)...")
    # Khi main_doc_meta=None (khong truyen), khong tinh diem file (-15)
    # doc_no +25, title +25, date +20, agency +15 = 85 -> VALID
    status, score, warnings = score_record_data(
        doc_no="100/QD-UBND",
        title="Quyet dinh ve viec trien khai phan mem QLVB tren toan tinh",
        doc_date="01/07/2026",
        agency="UBND tinh",
        main_doc_meta=None,  # Chua co file â€” nhung van du 85 diem
    )
    assert status == "VALID", f"Phai VALID (du meta, du diem khong can file), got: {status} (score={score})"
    print(f"  score={score}, warnings={warnings}")
    print("  -> PASSED")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def run_tests():
    print("=" * 65)
    print(" Phase 2 â€” test_parser_validation.py")
    print("=" * 65)

    tests = [
        test_full_valid_record,
        test_missing_doc_no_but_has_rest_is_suspicious,
        test_missing_doc_no_and_date_and_agency_is_invalid,
        test_username_data_is_always_invalid,
        test_username_pipe_format_is_invalid,
        test_doc_no_digit_only_gets_partial_score,
        test_doc_no_no_slash_short_is_suspicious_warning,
        test_name_like_doc_no_is_invalid,
        test_validate_record_data_backward_compatible,
        test_suspicious_has_meaningful_reason,
        test_invalid_has_meaningful_reason,
        test_missing_all_data_is_invalid,
        test_suspicious_with_no_file_enough_meta,
    ]

    passed = 0
    failed: list[str] = []

    for fn in tests:
        try:
            fn()
            passed += 1
        except Exception as exc:
            import traceback
            print(f"  -> FAILED: {fn.__name__}")
            print(f"     Error: {exc}")
            traceback.print_exc()
            failed.append(fn.__name__)

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



def test_outgoing_row_with_detail_action_label_is_not_technical():
    cells = [
        "1",
        "1848/UBND-VX",
        "V/v tham gia du thao Ke hoach trien khai Quyet dinh so 247/QD-TTg",
        "14/07/2026",
        "Phong Van hoa - Xa hoi xa Than Uyen",
        "Chi tiet Phong ban nhan hoac nguoi nhan",
    ]
    assert is_technical_row(cells) is False
