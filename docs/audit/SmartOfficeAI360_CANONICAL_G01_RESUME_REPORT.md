# SmartOfficeAI360 Canonical G01 Resume Report

- Thời gian: 2026-07-19, Asia/Bangkok
- Trạng thái cuối: **BLOCKED**
- Lý do dừng: patch portable apply thành công trong `verifyRepo`, nhưng SHA-256 byte-for-byte của cả 5 file G01 trong `verifyRepo` **không khớp** với Source A. Theo yêu cầu, không áp patch vào Canonical, không normalize line ending, không copy đè, không commit.

## 1. Trạng thái Canonical trước khi tiếp tục

- Canonical: `D:\Laptrinh\SmartOfficeAI360-Canonical`
- Git repo: YES
- Branch: `main`
- HEAD: `67efa8426833e54c1dc6bcf097882ff379ddae97`
- Baseline commit yêu cầu: `67efa84`
- Baseline tag: `canonical-baseline-a-pre-g01-20260718`
- Working tree: clean theo `git status --short`
- Remote: không có output từ `git remote -v`

## 2. Lý do patch cũ không portable

Patch cũ `D:\Laptrinh\SmartOfficeAI360_G01_DOWNLOADER_HARDENING.patch` có diff header chứa đường dẫn tuyệt đối, ví dụ:

```text
D:\Laptrinh\SmartOfficeAI360_Baseline_20260718\source_snapshot\tools\qlvb_downloader\models.py
```

Ở lượt trước, `git apply --check` fail với lỗi:

```text
error: invalid path 'D:\Laptrinh\SmartOfficeAI360_Baseline_20260718\source_snapshot\tools\qlvb_downloader\models.py'
```

Patch cũ không được sửa tay và không được dùng để apply.

## 3. Cách tạo patch portable

Đã clone Canonical baseline sang:

`D:\Laptrinh\SmartOfficeAI360_G01_PATCH_WORK`

Sau đó copy đúng 5 file G01 từ Source A:

- `tools/qlvb_downloader/models.py`
- `tools/qlvb_downloader/storage.py`
- `tools/qlvb_downloader/downloader.py`
- `tests/test_javascript_download_adapter.py`
- `tests/test_storage_queue.py`

Kết quả `workRepo` sau copy:

```text
 M tests/test_javascript_download_adapter.py
 M tests/test_storage_queue.py
 M tools/qlvb_downloader/downloader.py
 M tools/qlvb_downloader/models.py
 M tools/qlvb_downloader/storage.py
```

Patch mới được sinh bằng Python ghi nguyên byte stdout của:

```powershell
git -C D:\Laptrinh\SmartOfficeAI360_G01_PATCH_WORK diff --binary -- <5 G01 files>
```

## 4. Đường dẫn patch mới

`D:\Laptrinh\SmartOfficeAI360_G01_DOWNLOADER_HARDENING_PORTABLE.patch`

- Patch size: `76758` bytes
- UTF-8 BOM: NO
- First line: `diff --git a/tests/test_javascript_download_adapter.py b/tests/test_javascript_download_adapter.py`

## 5. Patch header validation

- `diff --git` count: `5`
- Absolute path hits: `0`
- Không chứa: `D:\Laptrinh`, `source_snapshot`, `SmartOfficeAI360_Baseline`, `SmartOfficeAI360\tools`

Diff headers:

```text
diff --git a/tests/test_javascript_download_adapter.py b/tests/test_javascript_download_adapter.py
diff --git a/tests/test_storage_queue.py b/tests/test_storage_queue.py
diff --git a/tools/qlvb_downloader/downloader.py b/tools/qlvb_downloader/downloader.py
diff --git a/tools/qlvb_downloader/models.py b/tools/qlvb_downloader/models.py
diff --git a/tools/qlvb_downloader/storage.py b/tools/qlvb_downloader/storage.py
```

## 6. Số file trong patch

`PORTABLE_PATCH_FILE_COUNT: 5`

## 7. Kết quả apply --check tại verifyRepo

Verify repo:

`D:\Laptrinh\SmartOfficeAI360_G01_PATCH_VERIFY`

- HEAD before apply: `67efa8426833e54c1dc6bcf097882ff379ddae97`
- Working tree before apply: clean
- `git apply --check`: PASS
- `git apply`: PASS

Sau apply, chỉ 5 file thay đổi:

```text
 M tests/test_javascript_download_adapter.py
 M tests/test_storage_queue.py
 M tools/qlvb_downloader/downloader.py
 M tools/qlvb_downloader/models.py
 M tools/qlvb_downloader/storage.py
```

Diff stat:

```text
tests/test_javascript_download_adapter.py | 166 +++++++-
tests/test_storage_queue.py               |  66 +++-
tools/qlvb_downloader/downloader.py       | 609 ++++++++++++++++++++++--------
tools/qlvb_downloader/models.py           |  23 +-
tools/qlvb_downloader/storage.py          |  26 +-
5 files changed, 719 insertions(+), 171 deletions(-)
```

## 8. SHA-256 Source A và verifyRepo

| File | Source A SHA-256 | Verify SHA-256 | Match |
|---|---|---|---|
| `tools/qlvb_downloader/models.py` | `F57534AE74F779CBA2980487B525C96981C73A40E5E076DE6075C2AAAA511F99` | `E16342F99AB1AFE50F62203FA1406F944825E3315D158282311D2B9D3C66E9C2` | NO |
| `tools/qlvb_downloader/storage.py` | `9A13509C0148EDD7E915C6B7E1FC3549F0A673C137F69B77317B8EE8411F328F` | `C00A358C6A6415AA483452BC9723AD14CF5A4B919E0F8A7BD002A78AB70425A2` | NO |
| `tools/qlvb_downloader/downloader.py` | `ABC47FD8EC3639BB893551EA09E07EDFD15AE24F57FEFED56DBA42CBAD2D84E1` | `F3CF9A67B52E4204ADFE0D1894F679CE7684A4EE72F6160949B64EBA62397880` | NO |
| `tests/test_javascript_download_adapter.py` | `93CEE028E9CCDE05F29B26BEF80C961CA017F60A14C782F959AB25D28342E50B` | `DEF5BB29B38B3A5867DA58A748E35C43CC8DC82ABD2C09B683779CCFE3DF452C` | NO |
| `tests/test_storage_queue.py` | `D57E39B43BB2DBE79091CFD9061D0E90F38CB16A50577CA9D2DCF8E53B2C53A2` | `6FE1F6F3A908EC97A6424DEB4E9C7405CB59CEDD43DE954E6344CAF1692C4638` | NO |

## 9. Line-ending evidence for mismatch

Không normalize hay sửa file. Chỉ đọc byte để giải thích mismatch.

| File | Source A bytes / CRLF / LF-only | Verify bytes / CRLF / LF-only |
|---|---|---|
| `tools/qlvb_downloader/models.py` | 4253 / 96 / 32 | 4285 / 128 / 0 |
| `tools/qlvb_downloader/storage.py` | 14516 / 0 / 345 | 14861 / 345 / 0 |
| `tools/qlvb_downloader/downloader.py` | 81991 / 1633 / 44 | 82035 / 1677 / 0 |
| `tests/test_javascript_download_adapter.py` | 18166 / 0 / 478 | 18644 / 478 / 0 |
| `tests/test_storage_queue.py` | 8821 / 0 / 210 | 9031 / 210 / 0 |

Kết luận bằng chứng: verifyRepo sau `git apply` có CRLF toàn bộ ở 5 file, trong khi Source A có LF hoặc mixed CRLF/LF. Vì yêu cầu SHA byte tuyệt đối, điều kiện không đạt.

## 10. Test verifyRepo

Not run. Reason: stopped at mandatory SHA-256 mismatch gate before verify test.

## 11. Kết quả apply vào Canonical

Not applied. Reason: verify SHA-256 mismatch.

## 12. SHA-256 Source A và Canonical

Not executed after patch, because patch was not applied to Canonical.

## 13. Test Canonical

Not run after G01. Reason: patch was not applied to Canonical.

## 14. Compileall

Not run. Reason: stopped before Canonical apply.

## 15. git diff --check

Not run after G01. Reason: stopped before Canonical apply.

## 16. Commit G01

Not created.

## 17. Tag G01

Not created.

## 18. Commit audit

Not created.

## 19. Git log cuối của Canonical

```text
67efa84 (HEAD -> main, tag: canonical-baseline-a-pre-g01-20260718) chore: establish reviewed SmartOfficeAI360 canonical baseline
```

## 20. Git status cuối của Canonical

`git status --short`: clean.

Canonical still has only baseline commit and baseline tag.

## 21. Rủi ro còn lại

1. Patch portable đúng path và apply được, nhưng không tái tạo byte-identical file so với Source A vì line-ending conversion.
2. Canonical chưa có G01 commit/tag.
3. Work/verify repos đã được tạo theo yêu cầu và chưa bị xóa: `D:\Laptrinh\SmartOfficeAI360_G01_PATCH_WORK`, `D:\Laptrinh\SmartOfficeAI360_G01_PATCH_VERIFY`.
4. Patch portable mới đã được tạo nhưng chưa được áp vào Canonical.
5. Cần quyết định chiến lược line ending trước khi tiếp tục: tạo patch theo binary/literal line endings hoặc cấu hình clone/temp repo để không CRLF-convert, nhưng việc đó cần một lượt thao tác riêng có điều kiện rõ.

## 22. Nội dung chưa xác minh

- Chưa chạy verifyRepo test sau patch.
- Chưa chạy compileall sau patch.
- Chưa chạy `git diff --check` sau patch.
- Chưa apply patch vào Canonical.
- Chưa đối chiếu SHA Source A vs Canonical sau patch.
- Chưa tạo G01 commit/tag.
- Chưa tạo provenance/audit docs commit.
- Chưa chạy hậu kiểm cuối.

## 23. Khuyến nghị bước tiếp theo

Tạo lại patch portable bằng quy trình kiểm soát line ending rõ ràng, ví dụ clone tạm với cấu hình không chuyển CRLF tự động rồi sinh/apply patch sao cho SHA verify khớp Source A byte-for-byte. Không nên apply patch hiện tại vào Canonical vì nó đã fail cổng SHA bắt buộc.

## 24. Tóm tắt terminal

```text
CANONICAL_BASELINE: PASS
OLD_PATCH_PORTABLE: NO
PORTABLE_PATCH_CREATED: YES
PORTABLE_PATCH_BOM_FREE: YES
PORTABLE_PATCH_ABSOLUTE_PATHS: NO
PORTABLE_PATCH_FILE_COUNT: 5
VERIFY_PATCH_CHECK: PASS
VERIFY_SHA256_MATCH: NO
VERIFY_TESTS: NOT_RUN_BLOCKED_BY_SHA_MISMATCH
VERIFY_COMPILE: NOT_RUN_BLOCKED_BY_SHA_MISMATCH
VERIFY_DIFF_CHECK: NOT_RUN_BLOCKED_BY_SHA_MISMATCH
CANONICAL_PATCH_CHECK: NOT_RUN_BLOCKED_BY_VERIFY_SHA_MISMATCH
CANONICAL_PATCH_APPLIED: NO
CANONICAL_SHA256_MATCH: NO
CANONICAL_TESTS: NOT_RUN_BLOCKED_BEFORE_CANONICAL_APPLY
CANONICAL_COMPILE: NOT_RUN_BLOCKED_BEFORE_CANONICAL_APPLY
CANONICAL_DIFF_CHECK: NOT_RUN_BLOCKED_BEFORE_CANONICAL_APPLY
G01_COMMIT: NOT_CREATED
G01_TAG: NOT_CREATED
AUDIT_DOCS_COMMIT: NOT_CREATED
CANONICAL_WORKTREE_CLEAN: YES
REMOTE_CONFIGURED: NO
SOURCE_A_CHANGED: NO
SOURCE_B_CHANGED: NO
BUILD_CREATED: NO
REAL_QLVB_USED: NO
REAL_PLANNER_SYNC_USED: NO
RECOMMENDATION: BLOCKED
```
