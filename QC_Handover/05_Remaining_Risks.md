# Báo Cáo Rủi Ro (Remaining Risks)

## 1. Lỗi trích xuất với PDF dạng Ảnh (Scan)
- **Tình trạng:** Hệ thống Extractor hiện tại sử dụng `pdfminer.six` chỉ có thể bóc tách text điện tử. Các công văn/văn bản nhà nước được scan từ máy in sẽ không có lớp Text layer.
- **Rủi ro:** Hệ thống sẽ ghi nhận trạng thái `EXTRACTION_ERROR` hoặc `EMPTY_TEXT` và phần `full_text_excerpt` bị rỗng.
- **Biện pháp (Phase sau):** Đội ngũ dự kiến tích hợp công nghệ Tesseract OCR / Google Vision API để khắc phục ở Phase tiếp theo.

## 2. Phụ thuộc thư viện bên thứ 3
- **Tình trạng:** Khả năng bóc text DOCX phụ thuộc `python-docx`. Nếu người dùng cài thiếu thư viện, hệ thống sẽ rơi vào `UNSUPPORTED_FORMAT`.
- **Rủi ro:** Một số văn bản sẽ không có nội dung xem trước.
- **Tác động:** Không gây sập hệ thống (Nhờ cơ chế Graceful Degradation). Văn bản vẫn được đồng bộ sang Planner KPI để đọc thủ công.

## 3. Giao diện (GUI)
- **Tình trạng:** UI chưa được refactor lớn ở bản Build QC này.
- **Rủi ro:** UI có thể hơi đứng khựng (block main thread) nếu ấn nút Download và có hàng trăm file tải cùng lúc, do quá trình Sync mạng chưa được đưa 100% vào Async/Thread.
