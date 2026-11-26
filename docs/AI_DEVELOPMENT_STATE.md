# AI Development State — Clubevent & KMG AI

Tài liệu trạng thái dùng chung cho **Antigravity** và **ChatGPT / OpenAI Codex CLI**. Các Agent phải đọc file này cùng `AGENTS.md` trước khi làm việc và cập nhật khi bàn giao.

---

## 1. Trạng thái hệ thống hiện tại
- **Cập nhật lần cuối:** 2026-11-26 (Antigravity — hoàn tất Master Task Phase 0 → Phase 7 trên nhánh ổn định hóa)
- **Thư mục gốc dự án:** `D:\clubevent\clubevent`
- **Nhánh Git hiện hành:** `feature/kmg-system-stabilization` (tách từ `feature/kmg-ai-v2` @ `57ad934`; `main` vẫn giữ nguyên tại `315535c`, `feature/sprint7-chong-gom-ve` tại `458ef9e`).
- **Phần cứng dev:** Intel Core i5-12500H (12 nhân / 16 luồng), RAM 16 GB DDR4-3200 (`16,869,548,032` bytes), NVIDIA GeForce RTX 3050 Laptop GPU (**4 GB VRAM**, `4,293,918,720` bytes) + Intel Iris Xe Graphics.
- **Môi trường kiểm thử:** Python 3.14 (`.\venv\Scripts\python.exe`), Django 5.2.17, SQLite/`LocMemCache` (chưa cài Docker Desktop, Redis Server và Ollama tại máy dev Windows; MySQL 8.4 đã cài cho DB phát triển `clubevent`, không dùng DB dev làm test).

### Kết quả kiểm chứng sau lượt chỉnh sửa mã nguồn cuối cùng
- `.\venv\Scripts\python.exe manage.py check --settings=config.settings_test`: **0 issues (0 silenced)** (exit `0`).
- `.\venv\Scripts\python.exe manage.py makemigrations --check --dry-run --settings=config.settings_test`: **No changes detected** (exit `0`).
- `.\venv\Scripts\python.exe manage.py check --deploy --settings=config.settings` *(mô phỏng `DEBUG=False`, `USE_HTTPS=True`, `ALLOW_DEMO_SEED=False`, biến môi trường tạm)*: **0 issues (0 silenced)** (exit `0`).
- `.\venv\Scripts\python.exe -m coverage run --omit="*/migrations/*,*/test*.py" manage.py test --settings=config.settings_test`: **Ran 633 tests in 164.387s — OK (skipped=2)** (`RedisRateLimitTests` skip do thiếu `KMG_TEST_REDIS_URL`).
- `.\venv\Scripts\python.exe manage.py evaluate_ai --with-migrate --settings=config.settings_test`: **EVAL ĐẠT** (`dev` **38/38** 100%, `holdout` **22/22** 100%, `blind` **50/50** 100%; RAG `dev` **13/13** 100%, `holdout` **7/8** 88%; PII **6/6**; Fallback OK).
- `.\venv\Scripts\python.exe -m unittest deployment/test_backup_restore.py deployment/test_scheduler.py -v`: **Ran 17 tests — OK (skipped=1 symlink Windows)**.
- **Coverage (`14,532` stmts trên 11 app + `63` file 100%):** Tổng hợp **77%**. Các vùng đã nâng rõ rệt trong Phase 6: `accounts/sms.py` **98%** (từ 28%), `finance/views.py` **88%** (từ 37%), `finance/api_views.py` **89%** (từ 58%), `accounts/services.py` **79%** (từ 43%), `organization/api_views.py` **54%** (từ 38%).

---

## 2. Các thay đổi chính trên nhánh `feature/kmg-system-stabilization`

1. **Sửa lỗi CI MySQL & Đồng bộ Production/CI (Phase 1):**
   - `events/test_features.py`: sửa `test_t7_4_3_lines_max_75_bytes_and_utf8` đưa `Event.name` về `169` ký tự (`<=200`) mà vẫn >200 byte UTF-8 để test line-folding không gây `DataError 1406`.
   - `config/settings.py` & `deployment/nginx.conf.template`: `ALLOW_DEMO_SEED` mặc định theo `DEBUG` (fail-closed `False` ở prod), tách `TRUST_X_FORWARDED_HOST` + ghi đè `proxy_set_header X-Forwarded-Host $http_host;`, đọc `SECURE_HSTS_SECONDS` từ env, thêm `SECURE_REFERRER_POLICY` và CSP + `Referrer-Policy` trên Nginx.
   - `.github/workflows/ci.yml`: bổ sung `test-mysql-redis`, `test-sqlite`, `docker-build-check`, `ruff`, `pip-audit`, `coverage` và `deployment` tests.
2. **Gia cố Bảo mật & Nghiệp vụ (Phase 2 & Phase 3):**
   - `operations/services.py` & `operations/views.py`: kiểm tra tệp bài nộp `submit_task_deliverable` qua `validate_and_prepare_vault_file` và gắn `X-Content-Type-Options: nosniff`, `Cache-Control: private, no-store` khi tải xuống.
   - `social/views.py`: siết whitelist MIME ảnh raster khi phục vụ inline trên MXH và tin nhắn.
   - `registrations/services.py`: khóa hàng `User` trước `TicketType` trong `book_tickets` và `join_waitlist` để chặn race condition vượt trần 4 vé/người khi đặt song song nhiều hạng vé khác nhau trên cùng sự kiện.
   - `pages/services.py`: `club_numbers()` chỉ đếm thành viên chính thức và check-in của sự kiện `PUBLIC`.
   - `finance/views.py` & `organization/api_views.py`: sửa lỗi thiếu `dept_txs`/`club_events` cho Cố vấn tại `finance_hub` và bổ sung mặc định `affiliation="KMA"` tại `/api/v1/auth/register/`.
3. **An toàn AI & Phân loại tri thức (Phase 5):**
   - `aiassist/models.py` + `aiassist/migrations/0006_clubknowledge_visibility.py` + `services.py` + `adapters.py` + `export_finetune_dataset.py` + `seed_ai_knowledge.py`: thêm `KnowledgeVisibility` (`PUBLIC` / `INTERNAL` mặc định / `CONFIDENTIAL`), lọc theo quyền truy cập (`can_view_internal_events` & lãnh đạo) trên cả Hybrid RAG lẫn Foundation BM25.
   - `aiassist/privacy.py`: thêm `sanitize_untrusted_input()` và bọc `<USER_QUERY>...</USER_QUERY>` chống prompt injection.
4. **Báo cáo & Kiểm thử mới (Phase 0–7):**
   - Báo cáo từng phase trong `docs/audit/00_BASELINE_REPORT.md` → `07_PRODUCTION_READINESS_REPORT.md` và báo cáo tổng hợp `docs/KMG_MASTER_UPGRADE_REPORT.md`.
   - Test mới: `core/test_security_phase2.py`, `registrations/test_phase3_business_logic.py`, `aiassist/test_phase5_ai_safety.py`, `accounts/test_phase6_coverage.py`, `finance/test_phase6_coverage.py`, `organization/test_phase6_api_coverage.py`, `registrations/test_phase6_perf.py`.

---

## 3. Blocker môi trường & Việc chờ xác nhận

- **GitHub Actions CI (`test-mysql-redis` & `docker-build-check`):** Cần push nhánh `feature/kmg-system-stabilization` lên `origin` để kiểm chứng MySQL 8.4, Redis 7 và build Docker trên runner Linux (máy dev thiếu Docker Desktop và Redis Server).
- **Ollama Local LLM benchmark:** Phần cứng `RTX 3050 (4 GB VRAM)` sẵn sàng cho mô hình `Q4_K_M` 1.5B–3B, nhưng chưa cài Ollama tại máy dev nên benchmark thực tế giữ trạng thái `BLOCKED`.
- **Browser screenshot responsive (`360px–1920px`) & UAT 7 vai trò:** Giữ trạng thái `REVIEW_REQUIRED` để thực hiện kiểm tra trực quan và UAT trước khi phát hành chính thức.

---

## 4. Trạng thái môi trường phối hợp Antigravity ↔ Codex & Khóa File

| File / Thư mục | Chủ sở hữu | Nhánh | Mục đích | Thời điểm khóa |
|---|---|---|---|---|
| *(Trống — đã giải phóng khóa sau Sprint A; tiếp tục khóa Sprint B)* | — | — | — | — |

- **Hàng đợi bàn giao:**
  - `[T-010]` Push nhánh `feature/kmg-system-stabilization` lên `origin` và theo dõi kết quả GitHub Actions (`test-mysql-redis`, `docker-build-check`) — `READY`.
  - `[T-011]` Review chéo nhánh `feature/kmg-system-stabilization` qua ChatGPT / `codex exec review --base main` — `READY`.
  - `[T-012]` Thực hiện UAT 7 vai trò theo `docs/UAT_PILOT_MATRIX.md` và chụp ảnh responsive `360px–1920px` trước khi tạo PR merge vào `main` — `READY`.

---

## 5. Hướng dẫn Rollback
- Nhánh `main` không bị thay đổi (`315535c`).
- Trên nhánh `feature/kmg-system-stabilization` có thêm migration `aiassist/migrations/0006_clubknowledge_visibility.py` (sau `0005`). Nếu DB đã chạy `migrate` trên nhánh mới và cần quay về `main`, chạy `python manage.py migrate aiassist 0004` trước khi `git checkout main`.
