# PHASE 1 — BÁO CÁO ỔN ĐỊNH HÓA HỆ THỐNG (STABILIZATION REPORT)

**Ngày thực hiện:** 2026-11-26  
**Nhánh làm việc:** `feature/kmg-system-stabilization`  

---

## 1. Các thay đổi đã triển khai

| ID | Hạng mục | Trạng thái | File thay đổi | Chi tiết kỹ thuật & Xác minh |
|---|---|---|---|---|
| **P1-01** | Sửa lỗi CI MySQL `DataError 1406` | **VERIFIED** | `events/test_features.py:108-119` | Rút ngắn dữ liệu test `Event.name` từ 204 ký tự (`* 6`) xuống 169 ký tự (`* 5`, đúng giới hạn `max_length=200` của model), vẫn vượt 200 byte UTF-8 để test RFC 5545 line folding `<= 75` bytes, thêm kiểm tra `line.decode("utf-8")` từng dòng và khôi phục nội dung khi unfold. Không sửa schema DB. |
| **P1-02a** | Hardening `ALLOW_DEMO_SEED` & `SECURE_HSTS_SECONDS` & `Referrer-Policy` | **VERIFIED** | `config/settings.py:50-62, 460-476`; `core/test_secret_guard.py` | Đặt `ALLOW_DEMO_SEED = env_bool("ALLOW_DEMO_SEED", DEBUG)` (fail-closed `False` khi `DEBUG=False`); đọc `SECURE_HSTS_SECONDS` từ env đồng bộ với `.env.production.example`; bật `SECURE_REFERRER_POLICY="same-origin"` ở chế độ production. |
| **P1-02b** | Đồng bộ `USE_X_FORWARDED_HOST` giữa Django và Nginx | **VERIFIED** | `config/settings.py:56-62`; `deployment/nginx.conf.template:18-19`; `core/test_secret_guard.py` | Tách `TRUST_X_FORWARDED_HOST` (mặc định `False`) để không tự động tin `X-Forwarded-Host`; đồng thời bổ sung `proxy_set_header X-Forwarded-Host $http_host;` trong `nginx.conf.template` để ghi đè mọi header giả mạo từ client. |
| **P1-03** | Nâng cấp GitHub Actions CI/CD | **IMPLEMENTED (chờ chạy trên runner GitHub)** | `.github/workflows/ci.yml` | Bổ sung 3 jobs rõ ràng: `test-mysql-redis` (MySQL 8.4 + Redis 7 + `pip check` + `compileall` + `ruff` + `pip-audit` + `check --deploy` + `deployment` tests + `coverage` + `evaluate_ai --with-migrate`), `test-sqlite`, và `docker-build-check`. |

---

## 2. Bằng chứng kiểm thử Phase 1

- `python -m compileall -q .`: **exit 0**.
- `python -m unittest deployment/test_backup_restore.py deployment/test_scheduler.py -v`: **Ran 17 tests — OK (skipped=1 `test_export_refuses_symlinks` do Windows không tạo symlink không đặc quyền)**.
- `python manage.py test events.test_features core.test_secret_guard --settings=config.settings_test`: **Ran 38 tests in 5.104s — OK**.

---

## 3. Blocker môi trường tại máy dev Windows
- **Docker build & Redis live test:** Máy Windows local hiện chưa cài Docker Desktop và Redis Server, nên job `docker-build-check` và 2 test `RedisRateLimitTests` cần chạy trên GitHub Actions runner (`ubuntu-latest`) sau khi push nhánh.
