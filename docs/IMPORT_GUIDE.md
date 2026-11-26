# HƯỚNG DẪN NHẬP DỮ LIỆU TỔ CHỨC TỪ CSV / EXCEL (`kmg_import_org`)

Công cụ `manage.py kmg_import_org` hỗ trợ định dạng **`.csv` (UTF-8 / UTF-8-SIG BOM)** và **`.xlsx` (Excel)**, kiểm tra lỗi từng dòng, chống trùng, chạy lại an toàn (idempotent) và hỗ trợ `--dry-run`.

## 1. Các loại dữ liệu hỗ trợ (`--kind`)

| Loại (`--kind`) | Các cột chính | Quy tắc an toàn |
|---|---|---|
| `structure` | `department_code, department_name, slug, short_description, is_demo, skill_category_code, skill_category_name, skill_code, skill_name` | Tạo Ban/Kỹ năng mới, không ghi đè Ban hiện hữu nếu thiếu `--update-existing` |
| `members` | `username, full_name, email, phone, mssv, affiliation, school, department_code, joined_at, membership_status, note` | Chặn tự gán quyền `ADMIN`/`SUPERUSER`; tài khoản mới luôn dùng `set_unusable_password()` để chủ tài khoản tự kích hoạt/đặt mật khẩu an toàn |
| `skills` | `username_or_email, skill_code, proficiency, verified_by, experience_note` | Tham chiếu mã kỹ năng thật (`GUITAR_ACOUSTIC`, `VOCAL_LEAD`...) |
| `appointments` | `username_or_email, position_code, department_code, term_label, ends_at, title_note` | **Bắt buộc truyền `--approve-by <admin_username>`**; kiểm tra `PermissionEngine` và khóa đơn nhiệm `singleton_active_key` |
| `history` | `username_or_email, event_type, department_code, title, note` | Tự bỏ qua bản ghi đã tồn tại (tránh nhân đôi sự kiện vòng đời) |

## 2. Quy trình chạy chuẩn
```powershell
# Bước 1: Dry-run kiểm tra lỗi trước (luôn rollback, 0 tác động DB)
.\venv\Scripts\python.exe manage.py kmg_import_org --kind members --file C:\data\kmg_members.xlsx --dry-run --report-json C:\data\import-dry.json

# Bước 2: Chạy thật sau khi error_count = 0
.\venv\Scripts\python.exe manage.py kmg_import_org --kind members --file C:\data\kmg_members.xlsx --report-json C:\data\import-commit.json

# Nhập quyết định bổ nhiệm (bắt buộc có tài khoản phê duyệt)
.\venv\Scripts\python.exe manage.py kmg_import_org --kind appointments --file C:\data\board_2026.csv --approve-by admin --dry-run
```
