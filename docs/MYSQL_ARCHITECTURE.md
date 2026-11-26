# KIẾN TRÚC MYSQL 8.4 THỐNG NHẤT — KMG PLATFORM

## 1. Nguyên tắc chuẩn hóa
- **Hệ quản trị chính thức:** MySQL `8.4.x` (`InnoDB`), bộ mã ký tự `utf8mb4`, collation `utf8mb4_0900_ai_ci`, chế độ chặt `STRICT_TRANS_TABLES`.
- **Khóa dòng thực (Row-Level Locking):** Tất cả nghiệp vụ đặt vé (`SELECT ... FOR UPDATE`), hàng chờ, chuyển nhượng vé, cập nhật sổ cái tài chính bất biến và bổ nhiệm đơn nhiệm (`Appointment.singleton_active_key`) dựa trên giao dịch ACID của InnoDB.
- **Fail-Closed tại Staging & Production:**
  - Khi `DEBUG=False` hoặc `KMG_ENV` thuộc `staging` / `prod`, hệ thống **bắt buộc từ chối khởi động (`ImproperlyConfigured`)** nếu engine CSDL không phải `django.db.backends.mysql`, trừ trường hợp chạy lệnh build static trong Dockerfile (`KMG_BUILD_STATIC=1` + `collectstatic`).
  - Mọi kết nối MySQL bắt buộc cấu hình `charset=utf8mb4`, `use_unicode=True` và `SET sql_mode='STRICT_TRANS_TABLES'`.

## 2. Phân tách 3 môi trường độc lập

| Môi trường | `KMG_ENV` | Tên CSDL | `DEBUG` | `ALLOW_DEMO_SEED` | Nguồn cấu hình mẫu | Mục đích |
|---|---|---|---|---|---|---|
| **Phát triển (Dev)** | `dev` | `kmg_dev` | `True` | `True` (tuỳ chọn) | `.env.dev.example` | Phát triển tính năng hằng ngày trên máy dev với MySQL thật |
| **Kiểm thử tiền phát hành (Staging)** | `staging` | `kmg_staging` | `False` / tùy kiểm thử | Có thể bật theo biến môi trường riêng | `.env.staging.example` | Chạy dữ liệu giả lập quy mô lớn (`seed_staging`), diễn tập chuyển đổi & load test |
| **Vận hành chính thức (Production)** | `prod` | `kmg_prod` | `False` | **Bị ép `False` (chặn cứng)** | `.env.production.example` | Dữ liệu thật của CLB KMG, cấm tuyệt đối mọi lệnh `seed_demo` / `seed_staging` / reset DB |

> **Lưu ý về `settings_test.py` và SQLite:**
> - CI (`test-mysql-redis`) và kiểm thử chuẩn chạy trên MySQL 8.4 thực (`test_kmg_ci`) + Redis.
> - `settings_test.py` chỉ giữ fallback SQLite khi chạy offline không có tham số `KMG_TEST_DB_ENGINE=mysql`, **không được dùng kết quả SQLite thay thế kiểm thử concurrency / MySQL collation**.
> - `settings_local.py` / `chay-thu.bat` chỉ là chế độ xem thử nhanh cục bộ, không dùng cho vận hành CLB.

## 3. Lưu ý tương thích MySQL 8.4 đã chuẩn hoá trong schema
- Các cột `UNIQUE` cho phép trống (`accounts.User.mssv`, `normalized_email`, `normalized_phone`, `Appointment.singleton_active_key`) dùng `NULL` thay vì chuỗi rỗng `""` để tránh lỗi trùng khóa trên MySQL.
- Không dùng partial unique index `UniqueConstraint(condition=...)` vì MySQL bỏ qua mệnh đề `WHERE` trong index.
- Tiêu chuẩn `utf8mb4` đảm bảo lưu trữ chính xác tên tiếng Việt có dấu kết hợp đầy đủ ký tự 4-byte như emoji.
