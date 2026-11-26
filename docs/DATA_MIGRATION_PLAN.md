# KẾ HOẠCH CHUYỂN ĐỔI DỮ LIỆU SQLITE SANG MYSQL 8.4

Tài liệu quy chuẩn chuyển đổi an toàn dữ liệu hiện tại (SQLite) sang **MySQL 8.4 (`InnoDB`, `utf8mb4_0900_ai_ci`)** bằng công cụ `manage.py migrate_sqlite_to_mysql` (`deployment/sqlite_to_mysql.py`).

---

## 1. Quy trình 6 bước chuẩn

1. **Kiểm kê nguồn (Inventory):**
   - Kiểm tra kích thước tệp SQLite nguồn, danh sách bảng, tổng số dòng từng bảng, danh sách migration đã áp dụng (`django_migrations`), và số lượng tệp trong `MEDIA_ROOT` / `PRIVATE_VAULT_ROOT`.
   - Phát hiện dữ liệu bẩn tương thích kém giữa SQLite và MySQL: chuỗi rỗng `""` trên các cột `UNIQUE NULL` (`accounts_user.mssv`, `normalized_email`, `normalized_phone`, `organization_appointment.singleton_active_key`) và các bản ghi mồ côi khóa ngoại (orphan FK).
2. **Sao lưu trước chuyển đổi (Pre-Migration Backup):**
   - Dùng `sqlite3.Connection.backup()` tạo bản chụp nhất quán + `manifest.json` kèm SHA-256 ở thư mục ngoài Git (`--backup-dir`).
3. **Diễn tập khô (`--dry-run`):**
   - Quét chuẩn hoá `"" -> NULL` trên bộ nhớ, đối chiếu sơ đồ cột & mã hoá UTF-8/4-byte emoji, và ghi nhận tổng số liệu sổ cái tài chính `CONFIRMED` trước khi ghi.
4. **Chuẩn bị lược đồ đích MySQL 8.4:**
   - Khởi tạo DB trống với `CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci` và chạy `python manage.py migrate --noinput`.
5. **Nạp dữ liệu bảo toàn toàn vẹn (`--execute`):**
   - Chạy trong giao dịch nguyên tử, giữ nguyên 100% PK IDs, mã vé (`Ticket.code`), mã giao dịch (`booking_ref`), bản ghi tài chính bất biến (`FinancialTransaction`), lịch sử vòng đời (`MemberLifecycleEvent`), và dữ liệu nhị phân mã hóa `AES-256-GCM` (`ChatMessage.ciphertext`, `iv_nonce`).
6. **Đối soát sau chuyển đổi (Reconciliation):**
   - So sánh `COUNT(*)` trên từng bảng (`source_rows == target_rows`).
   - Quét lại toàn bộ khóa ngoại trên MySQL đích (bảo đảm `0` orphan).
   - Đối soát tổng `SUM(amount)` nhóm theo `tx_type` với các giao dịch `CONFIRMED`.
   - Kiểm tra trực tiếp giải mã thử bản ghi `ChatMessage` và khả năng đọc file trong `media/` & `private_vault/`.

---

## 2. Lệnh thực thi mẫu

```powershell
# Bước 1: Dry-run kiểm kê (không ghi sang MySQL)
.\venv\Scripts\python.exe manage.py migrate_sqlite_to_mysql --source db.sqlite3 --report-json C:\backup\mig-dry.json

# Bước 2: Chuyển đổi thật sang MySQL (tự sao lưu trước)
.\venv\Scripts\python.exe manage.py migrate_sqlite_to_mysql --source db.sqlite3 --execute --backup-dir C:\backup\sqlite_pre --report-json C:\backup\mig-exec.json
```

## 3. Kế hoạch Rollback
- Nếu phát hiện lệch bất kỳ bảng hoặc số dư tài chính nào trong bước đối soát, giao dịch `transaction.atomic()` hoặc bản sao lưu MySQL/SQLite trước chuyển đổi (`--backup-dir` / `deployment/mysql_backup.py`) cho phép khôi phục nguyên trạng 100% mà không mất dữ liệu nguồn.
- Luôn giữ lại bản SQLite nguồn và bản chụp `.manifest.json` ngoài kho Git tối thiểu 30 ngày sau go-live.
