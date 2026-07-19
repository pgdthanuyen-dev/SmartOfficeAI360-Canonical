# Kế hoạch Thiết kế & Triển khai Công cụ Audit và Khắc phục Dữ liệu QLVB Downloader

Kế hoạch này đề xuất việc xây dựng công cụ audit dữ liệu hàng đợi, phân loại nguyên nhân và thiết lập cơ chế kiểm tra (validation), cách ly (quarantine), đồng thời sửa lỗi parser của Playwright để tránh việc tải nhầm danh sách tài khoản người dùng thay vì văn bản hành chính.

---

## User Review Required

> [!IMPORTANT]
> **Cơ chế Cách ly Dữ liệu (Quarantine):**
> Để đảm bảo an toàn tuyệt đối và tránh mất mát dữ liệu gốc trước khi sếp phê duyệt xóa, chúng tôi đề xuất di chuyển toàn bộ thư mục lỗi sang một thư mục cách ly riêng biệt:
> `Data/quarantine/<timestamp>/queue/<direction>/<doc_id>/` (đối với thư mục queue)
> `Data/quarantine/<timestamp>/files/<direction>/<folder_name>/` (đối với thư mục files gốc)
> Lệnh audit mặc định chạy ở chế độ **Dry-run (chỉ báo cáo, không di chuyển)**. Dữ liệu chỉ thực sự bị cách ly khi người dùng thêm tham số `--apply` ở dòng lệnh hoặc click xác nhận trên giao diện.

> [!IMPORTANT]
> **Tiêu chí Nhận diện Tài khoản người dùng (Non-document Records):**
> Các bản ghi sẽ bị phân loại là `INVALID` (Không phải văn bản) nếu vi phạm một trong các tiêu chí sau:
> 1. Số ký hiệu (`doc_no`) hoặc Trích yếu (`title`) khớp với biểu thức chính quy (Regex) của username: dạng chữ thường phân tách bởi dấu chấm, ví dụ: `mnmt.phanthimai`, `mnhn.dangthithuy`.
> 2. Trích yếu chứa cấu trúc phân tách `username | Họ tên`.
> 3. Số ký hiệu giống tên người viết hoa hoàn toàn (không chứa ký tự `/` hành chính và không phải số thuần túy).
> 4. Số ký hiệu không chứa định dạng số văn bản hành chính, chứa dấu chấm và có độ dài dài (không có `/`).

---

## Proposed Changes

Chúng tôi đề xuất triển khai các thay đổi trên các thành phần sau:

### 1. Sửa lỗi Parser & Downloader (Ngăn ngừa lỗi từ gốc)

#### [MODIFY] [parser.py](file:///d:/Laptrinh/SmartOfficeAI360/tools/qlvb_downloader/parser.py)
- Thêm hàm `is_document_table_headers(headers: list[str]) -> bool`:
  - Kiểm tra xem tiêu đề cột của bảng có chứa các trường cốt lõi của văn bản (Số ký hiệu, Ngày ký/ban hành, Trích yếu/nội dung). Nếu không khớp tối thiểu tiêu chí (phải có cột Trích yếu/Nội dung và ít nhất 1 cột Số/Ngày/Cơ quan), trả về `False`.
- Thêm hàm `validate_record_data(...) -> tuple[str, str]` và `validate_document_record(record) -> tuple[str, str]`:
  - Phân loại bản ghi thành 3 trạng thái: `VALID` (Hợp lệ), `SUSPICIOUS` (Nghi ngờ - thiếu file chính hoặc lỗi checksum/size), `INVALID` (Không phải văn bản - khớp mẫu tài khoản).

#### [MODIFY] [downloader.py](file:///d:/Laptrinh/SmartOfficeAI360/tools/qlvb_downloader/downloader.py)
- Thay đổi `_extract_headers(page)` và thêm `_find_document_table(page) -> Locator`:
  - Quét tất cả các thẻ `table` hiển thị trên trang. Sử dụng `is_document_table_headers` để xác định chính xác bảng chứa văn bản thay vì lấy bảng đầu tiên một cách mù quáng (ví dụ bảng chọn người nhận, danh bạ người dùng hiển thị trước).
  - Lưu bảng này vào `self._current_table_container`.
- Thay đổi `_extract_records_from_current_page`:
  - Hạn chế phạm vi tìm kiếm dòng (`tr`) chỉ nằm bên trong `self._current_table_container` (hoặc parent container của nó nếu là Kendo Grid/DevExpress Grid) để không lấy nhầm dòng của các bảng khác trên trang.
  - Tích hợp `validate_document_record(rec)` trước khi tải. Nếu bản ghi không hợp lệ (`INVALID`), bỏ qua lập tức và ghi log:
    `[BỎ QUA]skipped_invalid_non_document_record | Lý do: <reason> | doc_id: <doc_id>`
    và không ghi manifest hay tạo `.ready`.

---

### 2. Công cụ Audit & Cách ly Hàng đợi (Audit Tool)

#### [NEW] [audit_queue.py](file:///d:/Laptrinh/SmartOfficeAI360/tools/qlvb_downloader/audit_queue.py)
Viết script chạy CLI độc lập `python -m tools.qlvb_downloader.audit_queue`:
- Quét qua:
  - `Data/queue/incoming/` và `Data/queue/outgoing/`
  - `Data/files/incoming/` và `Data/files/outgoing/`
- Đối với mỗi thư mục, nạp manifest hoặc status/metadata, chạy qua hàm kiểm tra để đánh giá phân loại:
  - **VALID** (Đề xuất: `KEEP`)
  - **SUSPICIOUS** (Đề xuất: `REVIEW` nếu thiếu file chính/lỗi checksum)
  - **INVALID** (Đề xuất: `DELETE_CANDIDATE` nếu là tài khoản người dùng)
- Ghi báo cáo ra 2 tệp tin:
  - Tệp JSON: `Data/reports/queue_audit_<timestamp>.json`
  - Tệp văn bản: `Data/reports/queue_audit_<timestamp>.txt` (định dạng bảng báo cáo đẹp mắt để dễ đọc).
- Hỗ trợ tham số `--apply`:
  - Nếu có `--apply`, di chuyển các thư mục được đề xuất `DELETE_CANDIDATE` hoặc lỗi nặng sang thư mục cách ly `Data/quarantine/<timestamp>/`.

---

### 3. Cập nhật Giao diện (GUI Integration)

#### [MODIFY] [gui_tk.py](file:///d:/Laptrinh/SmartOfficeAI360/tools/qlvb_downloader/gui_tk.py)
- **Tab Hàng đợi (Queue):**
  - Bổ sung cột mới **"Đánh giá dữ liệu"** (hiển thị: Hợp lệ / Nghi ngờ / Tài khoản người dùng).
  - Thêm nút bấm **"Kiểm tra dữ liệu (Audit)"** để gọi trực tiếp script audit chạy ngầm.
  - Thêm nút bấm **"Cách ly dữ liệu lỗi"** (mặc định dry-run, hiển thị hộp thoại xác nhận trước khi thực hiện `--apply`).
  - Khóa (disable) nút "Thử đồng bộ KPI" và hạn chế nút "Đồng bộ tất cả" đối với các dòng có trạng thái dữ liệu là Nghi ngờ hoặc Không phải văn bản.

---

## Giai đoạn Triển khai Chi tiết

1. **Giai đoạn 1 (Sửa lỗi Parser & Downloader):**
   - Viết các hàm kiểm tra tiêu đề và phân loại dữ liệu trong `parser.py`.
   - Cấu trúc lại việc chọn table và trích xuất row trong `downloader.py`.
   - Kiểm thử việc quét danh sách trên trang QLVB mẫu (nếu có).

2. **Giai đoạn 2 (Xây dựng công cụ Audit CLI):**
   - Viết `audit_queue.py` thực hiện quét thư mục, ghi báo cáo ra TXT/JSON và cơ chế di chuyển files cách ly khi có `--apply`.
   - Chạy thử công cụ audit ở chế độ Dry-run đối với 210 thư mục hiện có trong `Data` và kiểm tra báo cáo.

3. **Giai đoạn 3 (Cập nhật GUI & Chặn đồng bộ lỗi):**
   - Sửa bảng Treeview của GUI để nạp thông tin đánh giá dữ liệu từ manifest.
   - Thêm các nút thao tác trên GUI và ràng buộc không cho phép đồng bộ hồ sơ lỗi.

4. **Giai đoạn 4 (Viết tests bổ sung):**
   - Bổ sung các test cases kiểm chứng việc loại bỏ dòng tài khoản, giữ dòng văn bản thật (như `419/QĐ/ĐU`, `1091/CV`), đánh giá REVIEW dòng thiếu file chính và báo lỗi manifest/sha256.

---

## Verification Plan

### Automated Tests
- Tạo mới file test `tests/test_audit_validation.py` chạy qua các case dữ liệu kiểm thử:
  - Tài khoản người dùng bị loại bỏ hoàn toàn.
  - Văn bản có số hành chính hợp lệ được giữ.
  - Kiểm tra báo cáo lỗi khi sai checksum file hoặc thiếu manifest.
- Chạy lại toàn bộ test:
  ```bash
  python -m tests.test_storage_queue
  python -m tests.test_duplicate_check
  ```

### Manual Verification
1. **Chạy thử lệnh audit:**
   - Chạy `python -m tools.qlvb_downloader.audit_queue` không có tham số để sinh báo cáo, xác nhận không có file nào bị xóa/di chuyển.
   - Xem báo cáo `Data/reports/queue_audit_*.txt` để kiểm tra danh sách đề xuất.
   - Chạy `python -m tools.qlvb_downloader.audit_queue --apply` để thực hiện cách ly, sau đó xác nhận các thư mục tài khoản đã được chuyển sang `Data/quarantine/`.
2. **Kiểm tra giao diện:**
   - Chạy GUI và kiểm tra xem tab Hàng đợi có hiển thị trạng thái "Không phải văn bản" đối với các dòng bị lỗi.
   - Xác nhận nút "Đồng bộ KPI" bị khóa đối với các hàng lỗi này.
