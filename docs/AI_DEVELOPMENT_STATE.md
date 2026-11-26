# AI Development State — Clubevent & KMG AI

Tài liệu trạng thái dùng chung cho **Antigravity** và **ChatGPT**. Các Agent cần đọc file này trước khi làm việc và cập nhật khi bàn giao.

---

## 1. Trạng thái hệ thống hiện tại
- **Cập nhật lần cuối:** 2026-11-26 (Antigravity — hoàn tất tuần tự Phase 1–4)
- **Thư mục gốc dự án:** `D:\clubevent\clubevent`
- **Nhánh Git & Mốc hiện tại:** `feature/kmg-ai-v2` (tạo từ `main` @ `315535ceaa230ef6ecdb9fc6ced96cc1c379b657`; các commit nền đã đẩy lên `origin/feature/kmg-ai-v2`: `c76d415`, `d870275`, `424dfa6`, tiếp nối bởi đợt hoàn thiện Phase 1–4).
- **Phần cứng dev:** Intel Core i5-12500H (12 nhân / 16 luồng), RAM 16 GB DDR4-3200 (`16,869,548,032` bytes), NVIDIA GeForce RTX 3050 Laptop GPU + Intel Iris Xe Graphics.
- **Runtime:** Python 3.14 (`.\venv\Scripts\python.exe`), Django 5.2.17, SQLite/`LocMemCache` trên máy dev (chưa cài MySQL, Redis, Docker, Ollama local).

### Kết quả kiểm chứng sau đợt chỉnh sửa cuối
- `python manage.py check --settings=config.settings_test`: **0 issues (0 silenced)** (exit `0`).
- `python manage.py makemigrations --check --dry-run --settings=config.settings_test`: **No changes detected** (exit `0`).
- `python manage.py check --deploy --settings=config.settings` (mô phỏng `DEBUG=False`, `USE_HTTPS=True`, biến môi trường tạm): **chạy lại xác nhận 0 issues**.
- `python manage.py test --settings=config.settings_test` (chạy toàn bộ dưới `coverage`): **Ran 595 tests in 146.366s — OK (skipped=2)**, exit `0`. (2 test bị skip là `RedisRateLimitTests` do chưa có `KMG_TEST_REDIS_URL`).
- `python manage.py evaluate_ai --with-migrate --settings=config.settings_test`: **EVAL ĐẠT**:
  - Ý định: `dev` **38/38 (100%)**, `holdout` **22/22 (100%)**, `blind` **50/50 (100%)** (tăng từ 62% lên 100%).
  - Truy xuất tri thức (Hybrid BM25 + Lexical RAG): `dev` **13/13 (100%)**, `holdout` **7/8 (88%)** (tăng từ 62% lên 88%).
  - Che PII: **6/6 đạt**, Fallback khi AI lỗi: **đạt**.
- **Mô phỏng tải 100 sinh viên (`registrations/test_pilot_load.py`):**
  - `PILOT-BOOK-100` (100 luồng tranh 60 vé): `ok=60`, `rejected=40`, `sold=60/60` (0 oversell), P95 = `605.3ms` (dưới coverage; standalone `581.8ms`).
  - `PILOT-CHECKIN-100` (10 luồng quét trùng + 100 vé): `checked_in=100/100`, quét trùng trả đúng `1 OK / 9 USED`, P95 = `8.8ms` (standalone `8.7ms`).
  - `PILOT-CHAT-100` (100 lượt chat phân tách IP): `ok=100/100`, P95 = `17.1ms` (standalone `16.5ms`).
- **Độ bao phủ mã nguồn (`coverage report` trên 7 app cốt lõi, bỏ `migrations` và `test*.py`):**
  - **Tổng hợp:** `8,657` statements, `1,959` missed → **77%** (cộng thêm `45` file đạt 100% được skip ở danh sách thiếu).
  - Trọng tâm AI & Nghiệp vụ chính: `events/models.py` **99%**, `events/services.py` **98%**, `organizing/services.py` **96%**, `registrations/services.py` **95%**, `aiassist/core/retrieval.py` **91%**, `aiassist/providers.py` **91%**, `aiassist/chatbot.py` **90%**, `aiassist/services.py` **89%**, `aiassist/adapters.py` **86%**, `registrations/views.py` **85%**, `aiassist/views.py` **82%**, `aiassist/core/agent.py` **82%**, `organization/permissions.py` **83%**, `organization/services.py` **81%**.
  - Khu vực coverage còn thấp cần bổ sung thêm test: `finance/views.py` (37%), `organization/api_views.py` (38%), `accounts/sms.py` (28%), `accounts/services.py` (43%), `organization/management/commands/seed_kmg.py` (9%).

---

## 2. Kết quả System Audit & Trạng thái các hạng mục P0–P3

| ID | Mức | Trạng thái | Vị trí (`file:dòng` / module) | Mô tả & Xác minh |
|---|---|---|---|---|
| **P0-01** | P0 | **Đã sửa & verify** | `registrations/services.py`, `registrations/views.py`, `registrations/test_security_boundaries.py` | Chặn đặt vé / waitlist sự kiện `INTERNAL` trái phép, khóa đối chiếu `ticket_type.event_id == event.id`, chặn tài khoản `is_locked`. |
| **P0-02** | P0 | **Đã sửa & verify** | `pages/services.py` | Lọc `EventVisibility.PUBLIC` cho `public_events()`, `club_numbers()` và `suggestions`. |
| **P0-03** | P0 | **Đã sửa & verify** | `aiassist/chatbot.py`, `aiassist/views.py`, `aiassist/migrations/0005_scrub_internal_event_logs.py`, `aiassist/test_chat_boundaries.py` | Chat Safety Patch (`PRIVATE_INTENTS`, `CHAT_HISTORY_POLICY_VERSION = 2`, dọn log sự kiện nội bộ cũ bằng migration `0005`, test SSE bằng `TransactionTestCase`). |
| **P0-04** | P0 | **Đã sửa & verify** | `aiassist/management/commands/export_finetune_dataset.py`, `aiassist/test_safety.py` | Chỉ xuất sự kiện `PUBLIC`, đề xuất `APPROVED`, loại `PRIVATE_INTENTS`, che PII bằng `redact()`. |
| **P1-01** | P1 | **Đã sửa & verify** | `aiassist/views.py`, `aiassist/chatbot.py` | Dự trữ lượt AI nguyên tử (`_reserve_ai_attempt`) cho cả JSON và SSE. |
| **P1-02** | P1 | **Đã sửa & verify** | `config/settings.py`, `requirements-production.txt`, `core/test_secret_guard.py` | Bổ sung `requirements-production.txt`, đọc `KMG_ENV_FILE`, `CACHE_URL`, `TRUST_PROXY_HEADERS`, `TRUST_X_FORWARDED_FOR`, `MEDIA_ROOT`, `LOG_ROOT`, `LOG_TO_CONSOLE`. |
| **P1-03** | P1 | **Đã thêm (chưa chạy trên runner GitHub)** | `.github/workflows/ci.yml` | Workflow GitHub Actions kiểm thử với MySQL 8.4 + Redis 7. |
| **P1-04** | P1 | **Blocker môi trường local** | `registrations/tests.py`, `core/test_rate_limit_concurrency.py` | Máy Windows dev chưa có MySQL, Redis, Docker; cần chạy CI hoặc môi trường thật có `KMG_TEST_REDIS_URL` & MySQL 8.4 trước pilot. |
| **P2-01** | P2 | **Đã tích hợp** | `aiassist/core/*`, `aiassist/adapters.py`, `aiassist/test_foundation_integration.py` | Tích hợp `KMG AI Foundation 0.2.1` với `AI_FOUNDATION_AGENT` feature flag, `build_server_actor()`, `ToolRegistry` chỉ đọc công khai không PII, BM25 retrieval. |
| **P2-02** | P2 | **Đã nâng cấp & verify** | `aiassist/chatbot.py`, `aiassist/services.py`, `aiassist/providers.py`, `static/js/chatbot.js`, `templates/partials/floating_chat.html`, `aiassist/test_providers.py`, `aiassist/test_phase2_features.py` | Nâng `blind` intent lên **100%** (50/50), Hybrid BM25+Lexical RAG lên **88%** `holdout`, trả nguồn trích dẫn (`sources`) ra UI an toàn qua `textContent`, thêm `aiassist/providers.py` (Circuit Breaker, Daily Budget Tracker, OpenAI/Local/Ollama adapter không cần API key, fallback tự động & streaming SSE thật từ Gemini/OpenAI/Ollama). |
| **P2-03** | P2 | **Đã sửa & verify** | `registrations/services.py:364`, `registrations/test_features.py`, `events/views.py`, `organizing/views.py`, `feedback/views.py` | Sửa `auto_confirm_transfer` kiểm tra `(account or "").strip() != settings.BANK_ACCOUNT` (chặn webhook thiếu `accountNumber`); bổ sung rate-limit `kmg_ai_lead` (20 lượt / 300s) kèm fallback cho các endpoint AI của BTC/Lead. |
| **P3-01** | P3 | **Đã sửa & verify** | `aiassist/management/commands/evaluate_ai.py` | Thêm cờ `--with-migrate` để chạy trực tiếp trên DB kiểm thử rỗng (`evaluate_ai --with-migrate --settings=config.settings_test`). |

---

## 3. Tài liệu & Tệp mới bổ sung trên nhánh `feature/kmg-ai-v2`
- **Mã nguồn & kiểm thử:**
  - Multi-provider Gateway & SSE: `aiassist/providers.py`, `aiassist/test_providers.py`, cập nhật `aiassist/services.py`, `aiassist/chatbot.py`, `config/settings.py`.
  - Hybrid RAG, Intent, UI nguồn trích dẫn & Gia cố: `static/js/chatbot.js`, `templates/partials/floating_chat.html`, `aiassist/migrations/0005_scrub_internal_event_logs.py`, `aiassist/management/commands/evaluate_ai.py`, `aiassist/test_phase2_features.py`, `registrations/services.py`, `registrations/test_features.py`, `events/views.py`, `organizing/views.py`, `feedback/views.py`.
  - Mô phỏng Pilot 100 sinh viên: `registrations/test_pilot_load.py`.
- **Tài liệu mới:**
  - `docs/LOCAL_LLM_READINESS.md` — Đánh giá phần cứng (`i5-12500H` + `16 GB` + `RTX 3050`), cấu hình Ollama/Local LLM và quy trình benchmark.
  - `docs/UAT_PILOT_MATRIX.md` — Ma trận UAT cho 7 vai trò & 7 nhóm kịch bản trọng tâm trước Pilot.

---

## 4. Những điểm còn tồn đọng ngoài phạm vi môi trường local (Blocker / Việc cần làm khi lên Server)
1. **Kiểm thử trên MySQL 8.4 + Redis 7 thật & Docker build:** Hiện máy dev chưa cài MySQL, Redis, Docker; cần push nhánh hoặc chạy CI (`.github/workflows/ci.yml`) để xác nhận khóa dòng InnoDB, `RedisRateLimitTests` và build image `Dockerfile`.
2. **Benchmark Local LLM trực tiếp trên Ollama:** Cần cài Ollama và kéo mô hình `qwen2.5:3b` trên máy có GPU RTX 3050 rồi chạy `evaluate_ai --llm-judge` để đo tốc độ token thực tế.
3. **Nâng coverage ở các màn hình phụ ít đường dẫn test:** Đẩy `finance/views.py` (37%) và `organization/api_views.py` (38%) lên >=80% khi có thời gian, và thực hiện diễn tập UAT 7 vai trò theo `docs/UAT_PILOT_MATRIX.md`.

---

## 5. Hướng dẫn Rollback
- Nếu cần quay lại nguyên trạng `main`: `git checkout main` (nhánh `main` vẫn giữ nguyên tại `315535c`, chưa hề thay đổi).
- Lưu ý: Trên nhánh `feature/kmg-ai-v2` đã có thêm migration dữ liệu `aiassist/migrations/0005_scrub_internal_event_logs.py`. Trước khi chuyển về `main` trên DB đã chạy `migrate`, cần chạy `python manage.py migrate aiassist 0004` trước.
