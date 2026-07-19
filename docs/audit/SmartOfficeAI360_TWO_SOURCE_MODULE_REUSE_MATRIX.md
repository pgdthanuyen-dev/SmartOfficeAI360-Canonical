# SmartOfficeAI360 Two-Source Module Reuse Matrix

| Module | Nguồn A | Nguồn B | Chọn bản nào | Cách kế thừa | Có nên viết lại | Nhận xét |
|---|---|---|---|---|---|---|
| browser/session | Playwright + login gate + safe detail-page guard | Playwright + auth state save/load + relogin pause | Chọn A | Giữ flow session của A; chỉ học UX pause/resume đăng nhập của B | Không viết lại toàn bộ | A an toàn hơn với page-context guard. |
| downloader | tools/qlvb_downloader/downloader.py:581-1568+ | core/downloader/qlvb_downloader.py:509-1106 | Chọn A | Giữ máy trạng thái tải của A; kế thừa adapter NeoRemoting/getFileAttachLst và download.jsp từ B | Không | A giảm báo DONE giả tốt hơn. |
| selector/config | config.py + open_document_direction + host checks | load_config trong qlvb_downloader.py | Chọn A | Chuẩn hóa selector/config từ A, thêm selector thực chiến của B khi cần | Không | A có cấu trúc dễ bảo trì hơn. |
| parser | parser.py:61-317 | extract_main_table_records + doc_id heuristics | Chọn A | Giữ parser/validation của A; lấy heuristics bóc doc_id từ B nếu hữu ích | Không | A có canonical mapping và scoring. |
| extractor | extractor.py:142-340 | extract_text + header OCR vùng PDF | Chọn lai | Giữ schema extractor A, cấy OCR + region extraction từ B | Có, mức refactor | Đây là điểm giao thoa tốt nhất. |
| OCR | Chưa có runtime OCR hoàn chỉnh | ocr_image / ocr_pdf_with_pymupdf | Chọn B | Tách OCR của B thành module độc lập, bỏ phụ thuộc UI monolith | Có, refactor mạnh | B có giá trị tái sử dụng cao nhất ở mảng này. |
| storage | storage.py:34-300 | sync_to_ready + metadata.json/status.json | Chọn A | Giữ manifest v2/SQLite/hash của A; map dữ liệu từ B vào schema mới | Không | A sẵn sàng cho audit/sync hơn. |
| SQLite | index_db.py + storage upsert | docs/attachments/runs schema | Chọn A | Giữ DB của A; chỉ tham khảo schema runs của B nếu cần lịch sử crawl | Không | A gần mục tiêu trạng thái hơn. |
| queue | READY manifest + .ready/READY.ok | workspace_shared/QUEUE/READY | Chọn A | Giữ queue durable của A; học cách B hiển thị queue trong GUI | Không | A có checkpoint tốt hơn. |
| audit | audit_queue hidden import + GUI actions | Không thấy module audit tương đương | Chọn A | Giữ audit/quarantine của A | Không | B thiếu lớp audit vận hành. |
| sync client | sync_client.py:209-620 | M365 export package, không có sync runtime | Chọn A | Giữ transport layer của A, đổi payload từ document-ingest sang approved-task sync | Không | Đây là nền tốt nhất cho Planner KPI. |
| GUI | customtkinter, tabs overview/config/download/queue/sync | app_unified.py dashboard/AI/routing/M365 | Chọn B ở mức ý tưởng | Thiết kế lại GUI trên nền A, tái tạo các màn hình review/routing của B thay vì copy file | Có, viết lại có chọn lọc | B phong phú hơn nhưng nợ kỹ thuật cao. |
| logger | logger hidden import + structured logs quanh downloader/sync | print/log UI rải rác | Chọn A | Giữ logger của A | Không | A ổn hơn cho truy vết. |
| tests | 72 test safe subset pass | 1 file test, 1 fail | Chọn A | Giữ test A và bổ sung case OCR/AI từ B | Không | A vượt trội rõ. |
| packaging | SmartOfficeAI360.spec + launcher bats | 0_Dong_goi_EXE.bat dùng pip install pyinstaller | Chọn A | Giữ spec/launcher của A, chỉ tham khảo lời nhắc cài đặt từ B | Không | A phù hợp production hơn. |
