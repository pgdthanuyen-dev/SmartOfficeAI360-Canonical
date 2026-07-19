# Checklist Kiểm thử (QC Checklist)

Đội QC vui lòng thực hiện tuần tự các bài kiểm tra sau để xác nhận chất lượng (Sign-off) bản Build:

## 1. Giao diện người dùng (GUI)
- [ ] 1.1. App mở lên không bị Crash hay văng lỗi Console.
- [ ] 1.2. Nút bấm Đồng bộ/Download phản hồi và chạy bình thường.
- [ ] 1.3. UI tải được danh sách văn bản cũ siêu nhanh nhờ SQLite.

## 2. Kiểm duyệt văn bản (Soft Validation)
- [ ] 2.1. Nạp một file chuẩn (Có đủ tên, số/ký hiệu, file đính kèm) -> Kết quả phải là `VALID`.
- [ ] 2.2. Nạp một file **Thiếu số/ký hiệu** -> Kết quả bắt buộc phải là `SUSPICIOUS` (Nằm trong Audit).
- [ ] 2.3. Nạp một file thiếu trắng mọi thứ -> Kết quả là `INVALID`.

## 3. Trích xuất Text (Graceful Degradation)
- [ ] 3.1. Quét một file PDF thông thường -> Cần có trích xuất text 500 ký tự đầu trong `manifest.json`.
- [ ] 3.2. Quét một file Word (.docx) -> Có trích xuất text.
- [ ] 3.3. Cố tình đưa file rác / File PDF bị hỏng -> Pipeline KHÔNG ĐƯỢC CRASH. Manifest ghi `EXTRACTION_ERROR`.

## 4. Chống lỗi đồng bộ mạng (Sync & Retry)
- [ ] 4.1. Ngắt mạng (hoặc trỏ sai API URL) -> Hệ thống phải thử lại (Retry) 3 lần, giãn thời gian lâu dần.
- [ ] 4.2. Khôi phục mạng ở lần thử thứ 3 -> Quá trình đồng bộ hoàn tất thành công.
- [ ] 4.3. Kiểm tra Logs -> Header gửi đi phải có `X-Idempotency-Key` sinh từ doc_id.
