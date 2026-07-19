# Hướng dẫn Cài đặt & Chạy thử (QC)

## 1. Môi trường yêu cầu
- **Hệ điều hành:** Windows 10/11
- **Ngôn ngữ:** Python 3.10 trở lên.

## 2. Các bước khởi chạy (Môi trường test)

**Bước 1: Clone và Checkout tag**
```bash
git clone <url_du_an>
cd SmartOfficeAI360
git checkout tags/smartofficeai360-v22.2.0-qc-phase1-3
```

**Bước 2: Cài đặt Dependency**
```bash
pip install -r requirements.txt
```
*(Hệ thống sử dụng các thư viện như `requests`, `pdfminer.six`, `python-docx`, `playwright`).*

**Bước 3: Mở ứng dụng**
Khởi chạy giao diện chính của SmartOfficeAI360:
```bash
python -m tools.qlvb_downloader.gui_tk
```

## 3. Cách test luồng đồng bộ
- Giao diện (GUI) sẽ tự động nạp danh sách các văn bản đang tồn đọng trong thư mục Queue nội bộ.
- Nhấn nút **Đồng bộ** (hoặc Download) để quan sát hệ thống xử lý.
- Mở file `Data/logs/...` để theo dõi tiến trình Retry, Idempotency và lỗi tự phục hồi (Graceful degradation).
