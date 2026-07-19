# Release Notes - SmartOfficeAI360 (V22.2.0-QC)

**Version:** V22.2.0-QC  
**Tag:** `smartofficeai360-v22.2.0-qc-phase1-3`  
**Ngày release:** 2026-07-10  

## 📦 Nội dung bản cập nhật (Đã bao gồm)

Bản build QC này tập trung vào sự ổn định của luồng xử lý văn bản, hoàn thiện 3 giai đoạn (Phase) kỹ thuật cốt lõi:

1. **Phase 1: Sync Reliability (Độ tin cậy Đồng bộ)**
   - Hệ thống tự động Retry đồng bộ khi rớt mạng hoặc backend trả lỗi 5xx.
   - Cơ chế Backoff theo thời gian mũ (exponential backoff) tránh spam server.
   - Bổ sung X-Idempotency-Key chống trùng lặp văn bản.
   - Thêm Polling tự động xác nhận Planner KPI đã xử lý (Ingest) xong văn bản.

2. **Phase 2: Text Extraction & Soft Validation (Trích xuất & Kiểm duyệt mềm)**
   - Engine `extractor.py` tự động đọc nội dung PDF, DOCX, TXT.
   - Chuyển `parser.py` sang mô hình chấm điểm (Confidence Score 0-100).
   - Văn bản thiếu số/ký hiệu sẽ được phân loại mềm thành `SUSPICIOUS` (Đưa vào Audit Queue) thay vì vứt bỏ.

3. **Phase 3: SQLite Index (Hệ quản trị siêu tốc)**
   - Dựng lớp cơ sở dữ liệu `index_db.py` tại local hỗ trợ tìm kiếm, phân trang mượt mà.
   - Tích hợp nguyên tử vào `storage.py`. Hỗ trợ công cụ Rebuild database từ Queue.

## 🚧 Các tính năng CHƯA bao gồm (Ngoài phạm vi bản QC này)
Để đội ngũ QC khoanh vùng kiểm thử, lưu ý các tính năng sau **chưa có** trong V22.2.0-QC:
- OCR cho PDF scan ảnh (hệ thống hiện tại sẽ báo lỗi `EXTRACTION_ERROR` nhưng luồng vẫn chạy bình thường).
- Scheduler tự động (Vẫn phải bấm Sync/Download thủ công).
- Tray icon (Chạy ẩn dưới thanh taskbar).
- Mã hóa password bằng Windows Credential Manager.
- Dashboard biểu đồ thống kê.
