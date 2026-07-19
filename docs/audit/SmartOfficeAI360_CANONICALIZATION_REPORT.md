# SmartOfficeAI360 Canonicalization Report

- Thời gian thực hiện: 2026-07-19, Asia/Bangkok
- Trạng thái cuối: **BLOCKED**
- Lý do BLOCKED: `git apply --check D:\Laptrinh\SmartOfficeAI360_G01_DOWNLOADER_HARDENING.patch` fail vì patch chứa đường dẫn tuyệt đối trong diff header, Git báo `error: invalid path 'D:\Laptrinh\SmartOfficeAI360_Baseline_20260718\source_snapshot\tools\qlvb_downloader\models.py'`.
- Hành động sau lỗi: dừng đúng yêu cầu; không apply patch, không sửa tay patch, không dùng `--reject`, không tạo G01 commit, không tạo G01 tag, không copy code từ Source B.

## 1. Canonical Path

`D:\Laptrinh\SmartOfficeAI360-Canonical`

## 2. Nguồn baseline

- Baseline source: `D:\Laptrinh\SmartOfficeAI360_Baseline_20260718\source_snapshot`
- Baseline root: `D:\Laptrinh\SmartOfficeAI360_Baseline_20260718`
- Manifest: `D:\Laptrinh\SmartOfficeAI360_Baseline_20260718\08_repository_manifest_sha256.txt`
- Source A tham chiếu: `D:\Laptrinh\SmartOfficeAI360`
- Source A commit tham chiếu: `19ff09329fae5c0ce8b800688a3fc36122484082`
- Source B tham khảo: `D:\Laptrinh\SmartOfficeAI360_V18_9_5_FINAL_FULL_PILOT_TEST`

## 3. Patch đã kiểm tra

- Patch path: `D:\Laptrinh\SmartOfficeAI360_G01_DOWNLOADER_HARDENING.patch`
- `git apply --check`: **FAIL**
- Patch applied: **NO**
- Error:

```text
error: invalid path 'D:\Laptrinh\SmartOfficeAI360_Baseline_20260718\source_snapshot\tools\qlvb_downloader\models.py'
```

## 4. File được nhập

- Imported file count: **83**
- Danh sách đầy đủ: `D:\Laptrinh\SmartOfficeAI360_CANONICAL_IMPORTED_FILES.txt`

## 5. File bị loại trừ

- Excluded count từ `source_snapshot`: **0**
- Danh sách: `D:\Laptrinh\SmartOfficeAI360_CANONICAL_EXCLUDED_FILES.txt`
- Sau khi chạy test baseline, Canonical có artifact ignored: `.pytest_cache/`, `Data/`, `tests/__pycache__/`, `tools/__pycache__/`, `tools/qlvb_downloader/__pycache__/`. Các artifact này không được stage nhờ `.gitignore`.

## 6. Quét secret

- SECRET_SCAN: **PASS**
- Có keyword nhạy cảm trong code/config mẫu/test/tài liệu, nhưng không phát hiện nghi vấn secret thật.
- Không in giá trị theo nguyên tắc bảo mật.
- Hit files: 15
- Suspect real secret: 0

## 7. Baseline test

Command:

```powershell
python -m pytest tests -q
```

Result:

```text
98 passed in 59.66s
```

## 8. Manifest verification

- BASELINE_MANIFEST_VERIFIED: **YES**
- Checked: **83**
- Missing: **0**
- Mismatch: **0**

## 9. Baseline Git

Commands executed:

```powershell
git init
git branch -M main
git add --all
git commit -m "chore: establish reviewed SmartOfficeAI360 canonical baseline"
git tag -a canonical-baseline-a-pre-g01-20260718 -m "Reviewed canonical baseline imported from Source A snapshot before G01"
```

Baseline commit:

```text
67efa84 chore: establish reviewed SmartOfficeAI360 canonical baseline
```

Baseline tag:

```text
canonical-baseline-a-pre-g01-20260718
```

Note: annotated tag creation initially failed because Git identity was not configured globally. The tag was then created using per-command identity (`-c user.name=... -c user.email=...`) without changing global/local Git config.

## 10. G01 SHA-256 đối chiếu

Not executed. Reason: patch check failed before apply. No G01 files were modified in Canonical.

Expected G01 files were:

- `tools/qlvb_downloader/models.py`
- `tools/qlvb_downloader/storage.py`
- `tools/qlvb_downloader/downloader.py`
- `tests/test_javascript_download_adapter.py`
- `tests/test_storage_queue.py`

## 11. Full test sau G01

Not executed. Reason: patch check failed and task requires stopping on critical failure.

## 12. Compileall

Not executed. Reason: patch check failed and G01 was not applied.

## 13. git diff --check

Not executed after G01. Reason: patch check failed and G01 was not applied.

Baseline add produced LF/CRLF warnings on imported historical files; no formatting changes were made manually.

## 14. Danh sách commit

```text
67efa84 (HEAD -> main, tag: canonical-baseline-a-pre-g01-20260718) chore: establish reviewed SmartOfficeAI360 canonical baseline
```

## 15. Danh sách tag

```text
canonical-baseline-a-pre-g01-20260718
```

Missing because blocked before G01:

```text
canonical-g01-downloader-hardened-20260718
```

## 16. Git status cuối

`git status --short` trong Canonical: sạch đối với tracked/untracked không ignored.

Ignored artifacts exist from baseline tests and are intentionally not committed.

## 17. Remote

`git remote -v`: no output. Remote configured: **NO**.

## 18. Source A/B không bị thay đổi

- Source A: không chạy lệnh ghi/sửa/xóa/reset/stash/clean. `git status --short` sau bước này vẫn là trạng thái dirty đã ghi nhận trước đó.
- Source B: không phải Git repo; không chạy lệnh ghi/sửa/xóa trong lượt canonicalization này.
- Không copy code từ Source B.

## 19. Rủi ro còn lại

1. Patch G01 hiện không apply được bằng `git apply --check` vì chứa path tuyệt đối trong diff header.
2. Canonical mới chỉ có baseline commit/tag, chưa có G01 hardening.
3. `CANONICAL_PROVENANCE.md` và `docs/audit` chưa được tạo/commit vì quy trình dừng trước G01.
4. Baseline test tạo artifact ignored trong Canonical; chúng không làm bẩn Git nhưng vẫn tồn tại trên filesystem.
5. Git identity mặc định của máy chưa cấu hình; các commit/tag đã tạo dùng identity theo từng lệnh.

## 20. Khuyến nghị bước tiếp theo

1. Tạo lại patch G01 ở định dạng Git portable với đường dẫn tương đối repo, ví dụ:
   `diff --git a/tools/qlvb_downloader/models.py b/tools/qlvb_downloader/models.py`.
2. Không sửa thủ công trong Canonical hiện tại nếu chưa có patch hợp lệ đã được review.
3. Sau khi có patch hợp lệ, chạy lại từ bước `git apply --check` trên Canonical hiện có.
4. Chỉ khi G01 apply và test pass, mới tạo G01 commit/tag và commit tài liệu audit/provenance.

## 21. Nội dung chưa xác minh

- Chưa áp dụng G01 patch.
- Chưa đối chiếu SHA-256 năm file G01 với Source A sau patch.
- Chưa chạy full test sau G01.
- Chưa chạy compileall sau G01.
- Chưa chạy git diff --check sau G01.
- Chưa tạo G01 commit/tag.
- Chưa tạo audit docs commit.

## 22. Xác nhận tuân thủ

- Không sửa Source A.
- Không sửa Source B.
- Không xóa/reset/clean/stash Source A hoặc Source B.
- Không sao chép Data/session/cookie/token/hồ sơ thật.
- Không sao chép code từ Source B.
- Không cài/nâng cấp dependency.
- Không build EXE.
- Không chạy QLVB thật.
- Không tải văn bản thật.
- Không gọi Planner KPI thật.
- Không tạo remote.
- Không push.
- Không chạy migration.
- Không tiếp tục Giai đoạn 2.

## 23. Tóm tắt terminal

```text
CANONICAL_PATH: D:\Laptrinh\SmartOfficeAI360-Canonical
SOURCE_SNAPSHOT: D:\Laptrinh\SmartOfficeAI360_Baseline_20260718\source_snapshot
BASELINE_MANIFEST_VERIFIED: YES
SECRET_SCAN: PASS
BASELINE_TESTS: 98 passed in 59.66s
BASELINE_COMMIT: 67efa84
BASELINE_TAG: canonical-baseline-a-pre-g01-20260718
PATCH_CHECK: FAIL
PATCH_APPLIED: NO
G01_FILE_COUNT: 0
G01_SHA256_MATCH_SOURCE_A: NO
FULL_TESTS: NOT_RUN_BLOCKED_BEFORE_G01
COMPILE_CHECK: NOT_RUN_BLOCKED_BEFORE_G01
DIFF_CHECK: NOT_RUN_BLOCKED_BEFORE_G01
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
