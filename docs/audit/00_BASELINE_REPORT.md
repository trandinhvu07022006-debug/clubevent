# PHASE 0 — BÁO CÁO ĐƯỜNG CƠ SỞ (BASELINE REPORT)

**Ngày kiểm kê:** 2026-11-26  
**Thực hiện:** Antigravity  
**Nhánh làm việc:** `feature/kmg-system-stabilization` (tách từ `feature/kmg-ai-v2` @ `57ad934`)  

---

## 1. Trạng thái Git & Nhánh tại thời điểm tiếp nhận

| Nhánh / Mốc | Commit SHA | Ghi chú |
|---|---|---|
| `main` (`origin/main`) | `315535c` | Nhánh gốc ổn định, chưa gộp các đợt AI v2 và vá bảo mật |
| `feature/sprint7-chong-gom-ve` | `458ef9e` | Nhánh Sprint 7 cũ |
| `feature/kmg-ai-v2` (`origin/feature/kmg-ai-v2`) | `57ad934` | Đi trước `main` 4 commit (`c76d415`, `d870275`, `424dfa6`, `57ad934`) |
| `feature/kmg-system-stabilization` | Từ `57ad934` | Nhánh làm việc chuẩn cho quá trình ổn định hóa & nâng cấp KMG v1.0 |

---

## 2. Kiểm kê quy mô hệ thống

Kiểm tra bằng `django.setup()` trên `config.settings_test`:
- **Django Apps:** 24 app (gồm hệ thống lõi sự kiện `accounts`, `events`, `organizing`, `registrations`, `feedback`, `aiassist`, `notifications`, `pages`, `recruitment` và các phân hệ quản trị mở rộng `core`, `organization`, `operations`, `programs`, `social`, `finance`, `evaluations`, `public_portal`, `deployment`).
- **Models:** 99 models.
- **Migrations:** 84 tệp migration (không tính `__init__.py`).
- **Templates:** 103 tệp HTML.
- **Static assets:** 6 tệp JS, 6 tệp CSS.
- **Management commands:** 47 lệnh quản trị.
- **Automated test files:** 63 tệp test (`test*.py`).
- **CI/Deployment:** `.github/workflows/ci.yml`, `Dockerfile`, `compose.yaml`, `deployment/` (`gunicorn.conf.py`, `nginx.conf.template`, `scheduler.py`, `healthcheck.py`, `backup_restore.py`, `volume_archive.py`, `generate_prod_env.py`), `requirements.txt`, `requirements-production.txt`.

---

## 3. Kết quả kiểm tra đường cơ sở (tại mốc `57ad934`)

| Hạng mục | Kết quả ghi nhận | Nguồn |
|---|---|---|
| `manage.py check --settings=config.settings_test` | **0 issues (0 silenced)** | Chạy trực tiếp |
| `manage.py makemigrations --check --dry-run` | **No changes detected** | Chạy trực tiếp |
| `manage.py check --deploy` (mô phỏng HTTPS) | **0 issues (0 silenced)** | Chạy trực tiếp |
| `pip check` | **No broken requirements found** | Chạy trực tiếp |
| Full test suite (SQLite + `LocMemCache`) | **595 tests — OK (skipped=2 `RedisRateLimitTests`)** | Chạy trực tiếp |
| GitHub Actions CI (MySQL 8.4) | **595 tests, 1 error (`DataError 1406`)** tại `events/test_features.py::test_t7_4_3_lines_max_75_bytes_and_utf8` | Báo cáo CI |
| `manage.py evaluate_ai --with-migrate` | **EVAL ĐẠT** (`dev` 38/38, `holdout` 22/22, `blind` 50/50; RAG `dev` 13/13, `holdout` 7/8; PII 6/6) | Chạy trực tiếp |
| Coverage (7 app trọng yếu, bỏ migrations & test) | **77%** tổng hợp (`8,657` stmts, `1,959` missed). Vùng thấp: `accounts/sms.py` (28%), `finance/views.py` (37%), `organization/api_views.py` (38%), `accounts/services.py` (43%) | `coverage report` |
| Pilot Load Simulation (`test_pilot_load.py`, service/test client) | Book 100->60: 0 oversell (P95 581.8ms / 605.3ms dưới coverage); Check-in 100: P95 8.7ms; Chat 100: P95 16.5ms | Chạy trực tiếp |

---

## 4. Danh sách lỗi & rủi ro phát hiện ở Phase 0

| Mã | Mức | Mô tả | Hướng xử lý |
|---|---|---|---|
| **BL-01** | **P0 (CI Fail)** | `events/test_features.py:109` tạo `Event.name` dài 204 ký tự vượt giới hạn `max_length=200`, gây lỗi MySQL `DataError 1406`. | Sửa dữ liệu test về <=200 ký tự mà vẫn >75 byte UTF-8; kiểm tra roundtrip gập/mở dòng. |
| **BL-02** | **P1 (Production)** | `config/settings.py:50` mặc định `ALLOW_DEMO_SEED=True` kể cả khi `DEBUG=False`; `USE_X_FORWARDED_HOST=True` bật theo `TRUST_PROXY_HEADERS` trong khi `nginx.conf.template` chưa ghi đè `X-Forwarded-Host`; `SECURE_HSTS_SECONDS` bỏ qua biến env trong `.env.production.example`. | Đồng bộ `ALLOW_DEMO_SEED` theo `DEBUG`, tách `TRUST_X_FORWARDED_HOST` và đặt `proxy_set_header X-Forwarded-Host $http_host;` trong Nginx, đọc `SECURE_HSTS_SECONDS` từ env. |
| **BL-03** | **P1 (CI/CD)** | `.github/workflows/ci.yml` thiếu kiểm tra Docker build, coverage, static check, dependency audit và bộ test `deployment/`. | Bổ sung đầy đủ các job/step kiểm tra trong CI. |
| **BL-04** | **P1 (Env)** | Môi trường Windows dev hiện tại chưa cài Docker Desktop và Redis server (MySQL 8.4 đã sẵn sàng cục bộ nhưng chưa mở `test_kmg_ci`). | Báo rõ blocker môi trường cho Docker build & Redis live test; chuẩn hóa CI & script test. |
| **BL-05** | **P2 (QA/Coverage)** | Độ phủ test còn thấp ở `finance/views.py` (37%), `organization/api_views.py` (38%), `accounts/services.py` (43%), `accounts/sms.py` (28%). | Bổ sung bộ integration/API/security regression tests ở Phase 2–6. |
