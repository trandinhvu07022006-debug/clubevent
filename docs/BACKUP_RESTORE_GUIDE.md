# HƯỚNG DẪN SAO LƯU & KHÔI PHỤC MYSQL 8.4 — KMG PLATFORM

Hệ thống có 2 công cụ bổ trợ cho 2 mô hình triển khai:
1. **Docker Compose stack:** `python -m deployment.backup_restore` (xem thêm `docs/deployment/DEPLOYMENT_AND_BACKUP.md`).
2. **MySQL 8.4 độc lập / Host Linux hoặc Windows:** `deployment/mysql_backup.py`.

## 1. Thành phần mỗi gói sao lưu
- `database.sql`: xuất bằng `mysqldump --single-transaction --quick --routines --triggers --hex-blob --no-tablespaces --set-gtid-purged=OFF` (truyền mật khẩu qua biến `MYSQL_PWD`, không lộ trên tham số dòng lệnh).
- `media.tar.gz`: lưu ảnh sự kiện / avatar.
- `private_vault.tar.gz`: lưu chứng từ tài chính, file bài nộp, tài liệu mật & tệp đính kèm chat.
- `manifest.json`: chứa dấu vân tay SHA-256 của 3 khóa (`SECRET_KEY`, `CERT_SIGNING_KEY`, `CHAT_MASTER_KEK`) và checksum SHA-256 của từng file artifact. **Tuyệt đối không đóng gói `.env` hay khóa bí mật thô.**

## 2. Quy tắc An toàn & Kiểm chứng Khôi phục
- Lệnh khôi phục (`restore_mysql_backup`) **từ chối chạy nếu CSDL đích đã tồn tại bảng** (tránh ghi đè DB đang chạy).
- Luôn kiểm tra checksum (`validate_backup`) trước khi khôi phục.
- Khóa `SECRET_KEY`, `CERT_SIGNING_KEY`, `CHAT_MASTER_KEK` phải được lưu dự phòng tách biệt trong trình quản lý mật khẩu để giải mã chứng nhận & tin nhắn lịch sử sau khôi phục.
- Sau khi khôi phục sang DB kiểm chứng, chạy `python manage.py check --deploy` và kiểm tra số bảng / tổng giao dịch tài chính.
