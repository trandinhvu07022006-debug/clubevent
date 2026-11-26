# CHECKLIST DỮ LIỆU & CẤU HÌNH PRODUCTION — KMG PLATFORM

Tài liệu rà soát bắt buộc trước khi cấp quyền go-live môi trường `kmg_prod` (MySQL 8.4).

## 1. Phân tách dữ liệu (5 nhóm độc lập)
1. **Danh mục dùng chung (`bootstrap_kmg`):** 3 Ban chính thức (`MEDIA_EVENT`, `SPECIALTY`, `TECHNICAL`), 6 Chức vụ, danh mục Quyền nguyên tử, Kỹ năng và Chính sách mặc định. **Không tạo user mẫu.**
2. **Dữ liệu chính thức CLB (`kmg_import_org` / Quản trị web):** Hồ sơ thành viên chính thức, cán bộ đương nhiệm có phê duyệt `--approve-by`, sự kiện thật.
3. **Dữ liệu Demo / Staging (`seed_demo`, `seed_kmg`, `seed_staging`):** **Chỉ chạy trên `kmg_dev` / `kmg_staging`**, bị chặn cứng khi `KMG_ENV=prod` hoặc `ALLOW_DEMO_SEED=False`.
4. **Dữ liệu Load Test:** Cách ly trong DB riêng `kmg_staging` / `test_kmg_ci`.
5. **Dữ liệu nhạy cảm & Bí mật:** `.env.production`, khóa `SECRET_KEY`, `CERT_SIGNING_KEY`, `CHAT_MASTER_KEK`, `DB_PASSWORD`, bản backup DB, `private_vault/` — **tuyệt đối không đưa lên GitHub**.

## 2. Checklist Go-Live Production
- [ ] `KMG_ENV=prod`, `DEBUG=False`, `ALLOW_DEMO_SEED=False`.
- [ ] `DB_ENGINE=mysql`, `DB_NAME=kmg_prod`, charset `utf8mb4`, `STRICT_TRANS_TABLES`.
- [ ] 3 khóa mật mã `SECRET_KEY`, `CERT_SIGNING_KEY`, `CHAT_MASTER_KEK` độc lập >= 32 ký tự và sao lưu ở Password Manager.
- [ ] Redis thật hoạt động cho cache & rate limit (`CACHE_URL=redis://...`).
- [ ] HTTPS (`USE_HTTPS=True`), `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` khớp tên miền chính thức.
- [ ] SMTP thật & `SEPAY_API_KEY` (nếu dùng VietQR tự động) đã kiểm chứng.
- [ ] Chạy `python manage.py check --deploy --settings=config.settings` đạt `0 issues`.
- [ ] Chạy `python manage.py migrate --noinput` + `python manage.py bootstrap_kmg` + `createsuperuser` cho Admin Server.
- [ ] Nhập danh sách thành viên thật qua `kmg_import_org --dry-run` trước khi commit.
- [ ] Thiết lập lịch backup tự động định kỳ + kiểm chứng khôi phục bản sao lưu đầu tiên.
