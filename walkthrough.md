# Walkthrough - SmartOfficeAI360 Desktop Agent GUI, Audit & Sync Integration

Chúng ta đã hoàn thành việc xây dựng, hoàn thiện giao diện người dùng Desktop Agent bằng **CustomTkinter**, tích hợp client đồng bộ hóa gói hàng đợi sang **Planner KPI** backend, đồng thời phát triển công cụ audit/cách ly dữ liệu lỗi để xử lý tình trạng cào nhầm danh sách tài khoản người dùng.

---

## 1. Kết quả Đạt được & Tác vụ đã triển khai

### A. Giao diện Người dùng Đa nhiệm (CustomTkinter)
- **Thanh Sidebar 8 Tab chính:** Tổng quan, Đăng nhập QLVB, Cấu hình, Tải văn bản, Hàng đợi, Đồng bộ KPI, Nhật ký, Trợ giúp.
- **Tương tác nền (Subprocess Popen & Threads):** 
  - Toàn bộ các tác vụ cào dữ liệu Playwright, chạy doctor kiểm tra, xuất gói chẩn đoán được chạy bất đồng bộ qua `subprocess.Popen` trong một luồng nền (`threading.Thread`).
  - Giao diện mainloop cập nhật log console trực tiếp từ tiến trình con qua `queue.Queue` và vòng lặp `.after(100)` giúp giao diện không bao giờ bị treo (Not Responding).
  - Nút "Dừng an toàn" (Safe Terminate) cho phép hủy lập tức tiến trình con Playwright/runner.
- **Hiển thị An toàn / Masking Secrets:**
  - Mật khẩu QLVB và `PLANNER_INGEST_TOKEN` được ẩn bằng dấu `*`.
  - Tích hợp thêm checkbox "Hiển thị mật khẩu và Token" để người dùng dễ dàng bật/tắt hiển thị mật khẩu khi cấu hình.

### B. Công cụ Audit & Cách ly Dữ liệu (Audit Tool)
- **Tập lệnh CLI mới [audit_queue.py](file:///d:/Laptrinh/SmartOfficeAI360/tools/qlvb_downloader/audit_queue.py):**
  - Quét toàn bộ thư mục trong `Data/queue/` và `Data/files/`.
  - Phân loại dữ liệu thành 3 nhóm: `VALID` (Hợp lệ), `SUSPICIOUS` (Nghi ngờ - thiếu file chính hoặc sai lệch checksum/size), `INVALID` (Không phải văn bản - trùng định dạng tài khoản người dùng).
  - Tự động sinh báo cáo chi tiết dưới dạng JSON (`Data/reports/latest_audit.json`) và văn bản ASCII table đẹp mắt (`Data/reports/latest_audit.txt`).
  - Hỗ trợ tham số `--apply` thực hiện di chuyển (cách ly) dữ liệu lỗi sang thư mục cách ly `Data/quarantine/<timestamp>/` một cách an toàn.
- **Tiêu chí Nhận diện Tài khoản người dùng (Non-document Records):**
  - Tích hợp biểu thức chính quy (Regex) trong `parser.py` để quét `doc_no` và `title` xem có khớp mẫu username viết thường phân tách bởi dấu chấm (như `mnmt.phanthimai`, `mnhn.dangthithuy`), cấu trúc `username | Họ tên`, hoặc số ký hiệu giống tên người viết hoa không chứa ký tự `/` hành chính.

### C. Cập nhật Giao diện Người dùng (gui_tk.py)
- **Cột "Đánh giá dữ liệu":** Bổ sung cột mới vào bảng Treeview hiển thị hàng đợi, phân loại rõ ràng hồ sơ: Hợp lệ / Nghi ngờ / Tài khoản.
- **Nút thao tác mới:**
  - **Kiểm tra dữ liệu (Audit):** Click để chạy công cụ audit ngầm và hiển thị popup báo cáo phân loại dữ liệu chi tiết.
  - **Cách ly dữ liệu lỗi:** Thực thi di chuyển các thư mục lỗi sang khu vực cách ly sau khi người dùng click xác nhận.
- **Ràng buộc an toàn:** Vô hiệu hóa nút đồng bộ KPI đối với các bản ghi thuộc diện "Nghi ngờ" hoặc "Tài khoản" để ngăn đẩy dữ liệu rác lên Planner KPI backend.

### D. Module Đồng bộ hóa (Sync Client)
- **Logic nạp gói hàng đợi:** Đọc `manifest.json`, xác định file chính và danh sách file đính kèm.
- **Tích hợp API:** Gửi dữ liệu multipart/form-data lên đầu endpoint `/api/document-ingest/upload` kèm Bearer Token và cập nhật trạng thái `SYNCED` / `FAILED` an toàn.

### E. Đóng gói Ứng dụng độc lập (PyInstaller .exe)
- Cập nhật [SmartOfficeAI360.spec](file:///d:/Laptrinh/SmartOfficeAI360/SmartOfficeAI360.spec) bổ sung hidden import `'tools.qlvb_downloader.audit_queue'` để đóng gói trọn vẹn executable.

---

## 2. Kết quả Xác minh & Chạy thử nghiệm

### A. Chạy test tự động
Chúng ta đã chạy và kiểm chứng thành công các bài test:
1. **Test nạp/ghi Queue & Manifest:**
   `python -m tests.test_storage_queue` -> **PASSED** (Ghi manifest 2.0.0 chính xác, checksum SHA256 và size khớp).
2. **Test Chống trùng (Deduplication):**
   `python -m tests.test_duplicate_check` -> **PASSED** (Bỏ qua hồ sơ cũ/READY/fallback READY.ok trùng).
3. **Test Client Đồng bộ hóa (Mock requests.post):**
   `python -m tests.test_sync_client` -> **PASSED** (Mock upload và kiểm chứng ghi nhận SYNCED / FAILED thành công).
4. **Test Audit & Phân loại dữ liệu mới:**
   `python -m tests.test_audit_validation` -> **PASSED** (Xác minh nhận diện đúng tài khoản, giữ văn bản hành chính như `419/QĐ/ĐU`, và test thành công luồng cách ly dữ liệu lỗi thực tế).

### B. Chạy thử Audit trên dữ liệu thực tế
- Chạy `python -m tools.qlvb_downloader.audit_queue` phát hiện chính xác 199 thư mục tài khoản lỗi (INVALID) và 11 thư mục thiếu file văn bản chính (SUSPICIOUS). Báo cáo đã được sinh thành công tại `Data/reports/latest_audit.txt`.

---

## 3. Lưu ý quan trọng khi triển khai & Kiểm thử
- **Đăng nhập và CAPTCHA:** Việc tải văn bản thật trên hệ thống QLVB thực tế yêu cầu người dùng phải đăng nhập thành công qua trình duyệt và vượt qua CAPTCHA trước. Các test tự động hiện tại đã xác nhận luồng xử lý login failure sạch, ghi nhận lưu trữ, manifest, sha256, dedup và fallback queue.
- **Mock Test cho Sync Client:** Kiểm thử tự động `tests/test_sync_client.py` hiện là bài test mock (giả lập requests.post) để xác nhận luồng xử lý manifest cục bộ hoạt động đúng.
- **Đồng bộ End-to-End:** Việc đồng bộ đầu-cuối (end-to-end) sang Planner KPI thật sẽ cần được kiểm tra thêm sau khi backend deploy đầy đủ API nhận tài liệu tại `/api/document-ingest/upload`.
- **Cài đặt Browser cho máy người dùng:** Do bộ cài không đóng gói trình duyệt Chromium (để tránh phình dung lượng bộ cài lên hàng trăm MB), máy người dùng cuối cần chạy lệnh cài đặt trình duyệt của Playwright:
  ```bash
  python -m playwright install chromium
  ```
  (Hoặc chạy Option 1 "Cai dat lan dau / cap nhat moi truong" trong tệp BAT dieu khien đi kèm).
