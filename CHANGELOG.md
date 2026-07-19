# Changelog

## [V22.2.2-QC Hotfix 3] - 2026-07-12
### Fixed
- QC-003: nhận diện CAPTCHA Lai Châu và không tải lại form trong lúc nhập mã xác nhận.
- Nhận diện detail URL trong href, onclick, data-url và data-href; hỗ trợ tab mới và modal/AJAX.
- Giữ và tái sử dụng browser profile khi phiên QLVB còn hiệu lực.
- Đóng gói Chromium trong bộ EXE để chạy trên Windows không cài Python/Playwright/Chromium.
- Bổ sung ma trận hồi quy QC-003 và cô lập dữ liệu tạm giữa các unit test.

## [V22.2.0-QC] - 2026-07-10
### Added & Upgraded (Phase 1-3)
- **Phase 1 (Sync Reliability)**:
  - Thêm retry, exponential backoff, timeout tách biệt trong `sync_client.py`.
  - Tích hợp X-Idempotency-Key chống tạo trùng lặp nhiệm vụ trên backend.
  - Hỗ trợ polling tự động xác nhận qua `/api/document-ingest/status/{id}`.
  - Nâng cấp `sync_batch` xử lý hàng loạt.
- **Phase 2 (Text Extraction & Soft Validation)**:
  - Bổ sung `extractor.py` tự động trích xuất nội dung từ PDF, DOCX, TXT.
  - Cập nhật manifest schema bổ sung optional fields: `full_text_excerpt`, `full_text_word_count`, `full_text_status`.
  - Cập nhật `parser.py` dùng cơ chế `confidence_score`, phân loại mềm SUSPICIOUS thay vì từ chối cứng. Bắt buộc thiếu số/ký hiệu phải review.
- **Phase 3 (SQLite Index)**:
  - Xây dựng lớp DB `index_db.py` tối ưu tra cứu, lọc và phân trang.
  - Tích hợp tự động quá trình Extractor và DB Upsert vào `storage.py` (atomic commit với cơ chế graceful degradation).
  - Cung cấp tính năng `rebuild_index_from_queue` để khôi phục metadata khi di chuyển DB.
