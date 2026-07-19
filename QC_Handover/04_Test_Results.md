# Danh sách Test Cases (Unit Tests & Acceptance Tests)

Tại phiên bản V22.2.0-QC, hệ thống đã vượt qua toàn bộ các Unit test. Đội QC có thể tham chiếu danh sách này để tránh test trùng lặp mức code:

## 1. Hệ thống Sync Client (`test_sync_retry.py`) - 12/12 PASSED
- [x] Upload thành công.
- [x] Timeout lần 1, thành công lần 2.
- [x] Lỗi HTTP 500 tự động Retry. Lỗi HTTP 4xx (Bad Request) ngắt ngay lập tức.
- [x] Tồn tại X-Idempotency-Key.
- [x] Batch Sync không bị gián đoạn nếu 1 tài liệu lỗi.
- [x] Chức năng Polling xác nhận Ingest ID hoạt động chuẩn xác.

## 2. Text Extractor (`test_extractor.py`) - 10/10 PASSED
- [x] PDF Text Extraction chuẩn xác.
- [x] Xử lý lỗi an toàn (Graceful) với file PDF trống, Scan ảnh, hoặc hỏng cấu trúc.
- [x] Giới hạn excerpt 500 ký tự. Xóa Unicode BOM.

## 3. Storage & Index (`test_index_db.py`, `test_storage_queue.py`) - 12/12 PASSED
- [x] SQLite Upsert, Search, Paginate, Filter hoạt động tốt.
- [x] Hàm lưu file (storage) tích hợp nguyên tử cả Extractor và Indexer. Lỗi từ hai nhánh này không làm hỏng quy trình sinh `.ready`.

## 4. Parser / Validation (`test_parser_validation.py`, `test_audit_validation.py`) - 13/13 PASSED
- [x] Chấm điểm (Scoring) thay cho filter cứng.
- [x] Bắt lỗi "Thiếu số/ký hiệu" giáng cấp thành SUSPICIOUS. 

## 5. Acceptance Test Pipeline (7 Fake Docs) - PASSED
- Cả 7 kịch bản (PDF Text, DOCX, TXT, Lỗi định dạng, File mất vật lý) đều đã ghi Index thành công.
