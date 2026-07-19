# SmartOfficeAI360 - G01 Downloader Hardening Report

Thoi gian thuc hien: 2026-07-18 23:00-23:17 +07:00  
Repository: `D:\Laptrinh\SmartOfficeAI360`  
Baseline audit da co: `D:\Laptrinh\SmartOfficeAI360_AUDIT_REPORT.md`  
Baseline Giai doan 0: `D:\Laptrinh\SmartOfficeAI360_Baseline_20260718`  
Patch Giai doan 1: `D:\Laptrinh\SmartOfficeAI360_G01_DOWNLOADER_HARDENING.patch`

## 1. Baseline path

Da tao baseline ngoai repository:

```text
D:\Laptrinh\SmartOfficeAI360_Baseline_20260718
```

Noi dung baseline:

- `01_git_status_before.txt`
- `02_git_diff_stat_before.txt`
- `03_git_diff_before.patch`
- `04_git_diff_binary_before.patch`
- `05_untracked_files_before.txt`
- `06_tracked_files.txt`
- `07_test_results_before.txt`
- `08_repository_manifest_sha256.txt`
- `09_sensitive_files_excluded.txt`
- `source_snapshot`

`source_snapshot` sao luu 83 file nguon/test/tai lieu/cau hinh mau, da loai tru `.git`, `Data`, profile/session/cookie/token, cache, build/dist, venv, backup lon va dinh dang ho so that.

## 2. Git branch va commit

- Branch: `main`
- Commit: `19ff09329fae5c0ce8b800688a3fc36122484082`
- Khong commit, tag, push, branch, stash, reset hoac clean.

## 3. Git status truoc/sau

Working tree da dirty tu truoc. `git status --short` sau Giai doan 0 va sau Giai doan 1 van cung tap file tracked/untracked nhu baseline, khong co file moi bat ngo trong repository.

Các file dirty tu truoc gom nhieu file tracked nhu `tools/qlvb_downloader/downloader.py`, `storage.py`, `models.py`, `parser.py`, `runner.py`, `tests/test_parser_validation.py`, `tests/test_qc003_matrix.py`, `tests/test_storage_queue.py`, cac BAT/config mau; va cac file/thư mục untracked trong `Data*`, `audit_recovery_20260718`, `restore_checkpoint_20260718`, `tests/test_javascript_download_adapter.py`, `tools/qlvb_downloader/repair_queue_mapping.py`, scratch files.

## 4. File da sua trong Giai doan 1

So sanh `source_snapshot` baseline voi sau sua, Giai doan 1 chi tac dong:

- `D:\Laptrinh\SmartOfficeAI360\tools\qlvb_downloader\models.py`
- `D:\Laptrinh\SmartOfficeAI360\tools\qlvb_downloader\storage.py`
- `D:\Laptrinh\SmartOfficeAI360\tools\qlvb_downloader\downloader.py`
- `D:\Laptrinh\SmartOfficeAI360\tests\test_javascript_download_adapter.py`
- `D:\Laptrinh\SmartOfficeAI360\tests\test_storage_queue.py`

Luu y: `tests/test_javascript_download_adapter.py` da la file untracked tu truoc baseline; lan nay co bo sung test vao file do.

## 5. Mo ta loi DONE/READY gia da xu ly

Truoc G01, downloader co the:

- Tang `processed` hai lan quanh mot record do cong trong `try` va `finally`.
- Dem `downloaded_files` bang attachment status `DOWNLOADED`, trong khi khong phai moi duong download deu validate magic bytes/content.
- Ghi `READY_NO_ATTACHMENT`, nhung storage lai dung `startswith("READY")`, nen co nguy co tao queue item va `.ready` cho ho so khong co tep hop le.
- Chap nhan direct request/response interceptor/browser download ma chua qua mot validator tap trung.
- Bat response theo HTTP 200/content-type qua rong.

Sau G01:

- `processed` chi tang mot lan trong `_process_direction` tai `tools/qlvb_downloader/downloader.py:581`.
- `downloaded_files` chi dem attachment `VALIDATED` tai `tools/qlvb_downloader/downloader.py:691` va `tools/qlvb_downloader/downloader.py:1295`.
- Queue chi chap nhan status trong allowlist `READY`, `READY_WITH_WARNINGS` tai `tools/qlvb_downloader/models.py:26` va `tools/qlvb_downloader/storage.py:144`.
- `NO_VALID_ATTACHMENT` khong tao `.ready` tai `tools/qlvb_downloader/storage.py:137`.

## 6. Thiet ke trang thai moi

Attachment status tai `tools/qlvb_downloader/models.py:12-17`:

- `DISCOVERED`
- `DOWNLOAD_STARTED`
- `DOWNLOADED_RAW`
- `VALIDATED`
- `INVALID_FILE`
- `DOWNLOAD_FAILED`

Document status tai `tools/qlvb_downloader/models.py:19-26`:

- `PROCESSING`
- `READY`
- `READY_WITH_WARNINGS`
- `NO_VALID_ATTACHMENT`
- `INVALID_DOCUMENT`
- `FAILED`
- `SESSION_EXPIRED`

Allowlist queue:

```python
DOCUMENT_QUEUEABLE_STATUSES = {DOCUMENT_READY, DOCUMENT_READY_WITH_WARNINGS}
```

## 7. Bo kiem tra file moi

Validator tap trung nam tai `tools/qlvb_downloader/downloader.py:1527`.

Kiem tra:

- File ton tai.
- Size lon hon nguong toi thieu.
- Khong rong.
- Khong phai HTML/login page.
- Source URL khong phai `about:`, `data:`, `javascript:` va khong vuot host QLVB cho phep.
- Content-Type hop le neu co.
- PDF bat dau bang `%PDF`.
- ZIP/DOCX/XLSX bat dau bang `PK` va mo duoc bang `zipfile`.
- DOCX co `[Content_Types].xml` va `word/document.xml`.
- XLSX co `[Content_Types].xml` va `xl/workbook.xml`.
- DOC/XLS OLE co magic bytes OLE.
- SHA-256 duoc tinh tai thoi diem validation.

Tat ca cac duong download deu qua `_finalize_validated_download` tai `tools/qlvb_downloader/downloader.py:1355`.

## 8. Chong bat nham response

Response interceptor duoc harden tai `tools/qlvb_downloader/downloader.py:1316`:

- Chi nhan HTTP 200.
- Chi nhan host thuoc `QLVB_ALLOWED_HOSTS`.
- Tu choi `about:`, `data:`, `javascript:`.
- Bat buoc `content-disposition` co `attachment`.
- Tu choi `text/html`.
- Voi href khong phai JavaScript, response path phai khop href path da click.
- Neu response khong hop le thi bo qua va log canh bao, khong ghi thanh file chinh thuc.

Nguon download duoc log theo:

- `browser_download`
- `response_interceptor`
- `direct_request`
- `javascript_adapter`

URL co query nhay cam khong duoc them vao bao cao nay.

## 9. Xu ly about:blank

Detail/page guard nam tai `tools/qlvb_downloader/downloader.py:1046`.

Popup/new page trong `_open_detail_by_saved_action` tai `tools/qlvb_downloader/downloader.py:1063`:

- Neu popup la `about:blank`, cho dieu huong ngan.
- Neu van `about:blank`, dong popup va bo qua detail.
- Khong tiep tuc merge metadata/tai file tren page trang.

`_is_logged_in` tai `tools/qlvb_downloader/downloader.py:429` khong con tra `True` chi vi body khong rong. Ham chi chap nhan marker dang nhap ro rang hoac marker danh sach van ban.

## 10. downloaded_files moi

`downloaded_files` chi tang sau khi:

1. Da download raw vao file `.part`.
2. Da validate thanh cong.
3. Da rename sang ten chinh thuc.
4. Attachment status la `VALIDATED`.

Bang chung:

- `_download_attachments`: `tools/qlvb_downloader/downloader.py:1253`
- Gan `VALIDATED`: `tools/qlvb_downloader/downloader.py:1269`
- Tang counter: `tools/qlvb_downloader/downloader.py:1275`
- Direction counter: `tools/qlvb_downloader/downloader.py:691`

## 11. Tao .ready moi

Storage khong dung `startswith("READY")` nua. Tai `tools/qlvb_downloader/storage.py:137-145`:

- Chi queue khi `record.status in DOCUMENT_QUEUEABLE_STATUSES`.
- Chi queue khi co it nhat 01 attachment `VALIDATED`.
- Neu status queueable nhung khong co attachment hop le, record bi ha ve `NO_VALID_ATTACHMENT`.
- `.ready` chi duoc tao cuoi pipeline sau manifest va SQLite upsert attempt tai `tools/qlvb_downloader/storage.py:279`.

## 12. Test bo sung

Test moi/chinh sua:

- `tests/test_javascript_download_adapter.py:318` - PDF hop le duoc accept va hash.
- `tests/test_javascript_download_adapter.py:327` - DOCX hop le duoc accept.
- `tests/test_javascript_download_adapter.py:335` - HTML gia PDF bi reject.
- `tests/test_javascript_download_adapter.py:343` - HTML gia ZIP bi reject.
- `tests/test_javascript_download_adapter.py:351` - File rong bi reject.
- `tests/test_javascript_download_adapter.py:359` - ZIP hong bi reject.
- `tests/test_javascript_download_adapter.py:375` - `about:blank` source bi reject.
- `tests/test_javascript_download_adapter.py:383` - Response dung content-type nhung sai href context bi bo qua.
- `tests/test_javascript_download_adapter.py:400` - `downloaded_files` chi dem `VALIDATED`.
- `tests/test_javascript_download_adapter.py:423` - `processed` khong tang hai lan.
- `tests/test_javascript_download_adapter.py:444` - Direction thanh `DONE_WITH_ERRORS` khi khong co attachment hop le.
- `tests/test_storage_queue.py:153` - `READY` khong co attachment valid khong tao `.ready`.
- `tests/test_storage_queue.py:183` - Attachment valid tao manifest va `.ready` dung mot lan.

## 13. Ket qua test

Baseline test truoc sua:

```text
98 passed in 50.87s
```

Targeted tests sau sua:

```text
30 passed in 2.99s
```

Full suite sau sua:

```text
111 passed in 56.52s
```

## 14. Ket qua compileall

Lenh:

```powershell
python -m compileall tools tests
```

Ket qua: **PASS**, exit code `0`.

## 15. Ket qua git diff --check

Lenh:

```powershell
git diff --check
```

Ket qua: **FAIL do loi co san tu baseline**, khong con loi moi trong `downloader.py`.

Con lai:

```text
tools/qlvb_downloader/runner.py:48: trailing whitespace.
tools/qlvb_downloader/runner.py:75: trailing whitespace.
tools/qlvb_downloader/runner.py:81: trailing whitespace.
tools/qlvb_downloader/runner.py:86: trailing whitespace.
tools/qlvb_downloader/runner.py:92: trailing whitespace.
tools/qlvb_downloader/runner.py:125: trailing whitespace.
```

Khong sua `runner.py` vi loi nay da co o baseline va nam ngoai pham vi Giai doan 1.

## 16. Rui ro con lai

- Chua chay QLVB live, nen chua xac minh DOM/download production.
- Validator co the can mo rong them content-type thuc te cua QLVB neu backend tra MIME khac.
- `READY_WITH_WARNINGS` da co logic khi co file valid kem file fail, nhung UX hien tai chua hien thi chi tiet canh bao tot.
- `.part` loi co the con o thu muc file khi download invalid, dung lam forensic; can chinh sach don dep rieng trong giai doan sau.
- `git diff --check` van fail do `runner.py` baseline whitespace.
- File encoding trong repo co lich su mojibake; G01 bo sung fallback Unicode, nhung nen co giai doan rieng chuan hoa encoding sau khi baseline sach.

## 17. Noi dung chua xac minh

- QLVB live.
- Tai van ban that.
- Planner KPI production.
- API Task Planner KPI.
- SharePoint/OneDrive.
- OCR/AI/review queue.
- Migration/schema production.
- Build release production.

## 18. De xuat buoc tiep theo

Khuyen nghi: **READY_FOR_REVIEW** cho Giai doan 1.

Buoc tiep theo nen lam:

1. Reviewer doi chieu patch G01 voi baseline snapshot.
2. Neu chap nhan, chay smoke local co mock download day du.
3. Sau do moi lap ke hoach pilot QLVB that co gioi han, khong sync production.
4. Tach mot viec rieng de chuan hoa encoding/line endings va whitespace baseline, tranh tron voi logic downloader.

## 19. Xac nhan an toan

- Khong xoa/reset/clean/checkout de file.
- Khong stash.
- Khong commit/tag/push/branch.
- Khong `git add -A`.
- Khong dua `Data`, session, token, cookie, ho so that vao Git.
- Khong cai/nang cap dependency.
- Khong chay QLVB that.
- Khong tai van ban that.
- Khong goi Planner KPI production.
- Khong chay migration.
- Khong build release production.

## 20. Tom tat terminal

```text
BASELINE: PASS
EXISTING_TESTS: PASS
NEW_TESTS: PASS
TOTAL_TESTS: 111
FALSE_DONE_FIXED: YES
FALSE_READY_FIXED: YES
FILE_VALIDATION_CENTRALIZED: YES
ABOUT_BLANK_GUARDED: YES
RESPONSE_BINDING_HARDENED: YES
DOWNLOADED_FILES_COUNTS_VALIDATED_ONLY: YES
READY_ALLOWLIST_ENFORCED: YES
COMPILE_CHECK: PASS
WORKTREE_NEW_UNEXPECTED_FILES: NO
COMMIT_CREATED: NO
BUILD_CREATED: NO
REAL_DATA_TOUCHED: NO
RECOMMENDATION: READY_FOR_REVIEW
```

