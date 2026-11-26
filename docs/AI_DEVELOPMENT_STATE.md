# AI Development State — Clubevent & KMG AI

Tài liệu trạng thái dùng chung cho **Antigravity**, **ChatGPT** và **OpenAI Codex CLI**. Các Agent phải đọc file này trước khi làm việc và cập nhật khi bàn giao.

---

## 1. Trạng thái hệ thống hiện tại
- **Cập nhật lần cuối:** 2026-11-26 (Antigravity)
- **Thư mục gốc dự án:** `D:\clubevent\clubevent`
- **Nhánh Git & Mốc hiện tại:** `feature/kmg-ai-v2` (tạo từ `main` @ `315535ceaa230ef6ecdb9fc6ced96cc1c379b657`; `origin/main` trùng SHA `315535ceaa230ef6ecdb9fc6ced96cc1c379b657`; nhánh `feature/sprint7-chong-gom-ve` cũ hơn tại `458ef9e`)
- **Runtime:** Python 3.14 (`.\venv\Scripts\python.exe`), Django 5.2.17, SQLite/LocMemCache tại máy dev (chưa cài MySQL/Redis/Docker local).
- **Kiểm tra nền & sau sửa đổi (2026-11-26):**
  - `phase0_snapshot.py --repo D:\clubevent\clubevent`: `head=315535ce...`, `tracked_file_count=468` (trước khi thêm file mới trên nhánh feature).
  - Foundation `0.2.1` (`python -m unittest discover -s tests -v`): **25/25 OK** (`0.003s`).
  - `python manage.py check --settings=config.settings_test`: **0 issues (0 silenced)** (exit `0`).
  - `python manage.py makemigrations --check --dry-run --settings=config.settings_test`: **No changes detected** (exit `0`).
  - `python manage.py check --deploy --settings=config.settings` (mô phỏng production `DEBUG=False`, `USE_HTTPS=True`, env tạm): **0 issues (0 silenced)** (exit `0`).
  - `python manage.py test aiassist.test_chat_boundaries --settings=config.settings_test -v 2`: **6/6 OK** (`1.662s`, exit `0`).
  - `python manage.py test registrations.test_security_boundaries aiassist.test_safety aiassist.test_foundation_integration core.test_secret_guard pages.tests --settings=config.settings_test -v 2`: **64/64 OK** (`10.203s`, exit `0`).
  - `python manage.py test --settings=config.settings_test` (toàn cục sau lượt sửa cuối): **Ran 578 tests in 141.976s — OK (skipped=2)**, exit `0`. (2 test bị skip là `RedisRateLimitTests` do chưa có `KMG_TEST_REDIS_URL`).
  - `evaluate_ai` (chạy bên trong suite `aiassist.test_safety` & `aiassist.test_llmops`): **EVAL ĐẠT** (Ý định dev `38/38` 100%, holdout `22/22` 100%, blind `31/50` 62%; RAG dev `13/13` 100%, holdout `6/8` 75%; PII `6/6`; Fallback OK). *Lưu ý:* chạy `manage.py evaluate_ai --settings=config.settings_test` trực tiếp trên DB SQLite tạm chưa migrate báo `no such table: aiassist_clubknowledge` vì `settings_test.py` dùng thư mục tạm mới mỗi process.

---

## 2. Kết quả System Audit & Phân loại P0–P3

| ID | Mức | Trạng thái | Vị trí (`file:dòng`) | Mô tả & Xác minh |
|---|---|---|---|---|
| **P0-01** | P0 | **Đã sửa & verify** | `registrations/services.py:179-231, 728-747`; `registrations/views.py:49-83, 195-204` | **Vượt rào đặt vé / waitlist sự kiện `INTERNAL` & tráo `ticket_type_id`:** `book()` và `book_tickets()` / `join_waitlist()` trước đây không kiểm tra `EventVisibility.INTERNAL` và `book()` không đối chiếu `ticket_type.event_id == event.id`. Đã khóa ở cả service và view (`Http404` / `BookingError`), kiểm tra `is_locked`, kèm test hồi quy `registrations/test_security_boundaries.py`. |
| **P0-02** | P0 | **Đã sửa & verify** | `pages/services.py:26-49, 113-125` | **Rò rỉ sự kiện `INTERNAL` trên trang công khai & gợi ý của Khách:** `public_events()`, `club_numbers()` và `suggestions` không lọc `visibility=EventVisibility.PUBLIC`. Đã lọc chuẩn theo `can_view_internal_events(user)` và xác minh bằng test. |
| **P0-03** | P0 | **Đã sửa & verify** | `aiassist/chatbot.py:118-126`; `aiassist/views.py:100-106, 160-220`; `aiassist/test_chat_boundaries.py` | **Chat Safety Patch (rò rỉ sự kiện `INTERNAL` qua `chat_history` / `AIInteractionLog`):** Tích hợp `PRIVATE_INTENTS` mở rộng (`upcoming_events`, `seats_left`), `CHAT_HISTORY_POLICY_VERSION = 2` loại bỏ history cũ chưa gắn policy, và sửa lỗi `StreamingHttpResponse` / bản sao `list(chat_history)` khi chạy test thật trên Django (`TransactionTestCase` + truyền `list(chat_history)` vào `answer`/`stream_answer`). |
| **P0-04** | P0 | **Đã sửa & verify** | `aiassist/management/commands/export_finetune_dataset.py:22-140` | **Xuất dữ liệu fine-tune có nguy cơ lộ `INTERNAL` PostMortem, Đề xuất chưa duyệt & PII:** `build_finetune_records()` trước đây xuất `EventPostMortem` cả sự kiện `INTERNAL`, xuất `DepartmentProposal` cả bản `DRAFT`/`REJECTED`, không lọc `PRIVATE_INTENTS` và không chạy `redact()`. Đã lọc `visibility=PUBLIC`, `ProposalStatus.APPROVED`, loại `PRIVATE_INTENTS`, bọc `redact()` toàn bộ và kiểm chứng trong `aiassist/test_safety.py::ExportFinetuneIsolationTests`. |
| **P1-01** | P1 | **Đã sửa & verify** | `aiassist/views.py:80-90, 160-220`; `aiassist/chatbot.py:201-218, 250-260` | **Quota chat AI không nguyên tử (`check-then-record`):** Đã chuyển sang `_reserve_ai_attempt(request)` (`record=True`) trước khi vào nhánh LLM cho cả JSON và SSE, tính cả lỗi và ngắt stream, không tính câu rule-based/rỗng. |
| **P1-02** | P1 | **Đã sửa & verify** | `config/settings.py:26-39, 53-58, 212-226, 354, 407-429`; `requirements-production.txt`; `Dockerfile:5` | **Hạ tầng production Docker (`CACHE_URL`, `TRUST_PROXY_HEADERS`, `requirements-production.txt`):** `Dockerfile` tham chiếu `requirements-production.txt` nhưng file chưa tồn tại; `config/settings.py` chưa đọc `KMG_ENV_FILE`, `CACHE_URL`, `TRUST_PROXY_HEADERS`, `TRUST_X_FORWARDED_FOR`, `MEDIA_ROOT`, `LOG_ROOT`, `LOG_TO_CONSOLE` mà `compose.yaml` và `settings_test.py` truyền vào. Đã bổ sung `requirements-production.txt` và nối đầy đủ cấu hình trong `config/settings.py`, kiểm chứng qua `SecretGuardTests.test_cache_url_and_proxy_headers_configured_when_set`. |
| **P1-03** | P1 | **Đã thêm (chưa chạy trên runner GitHub)** | `.github/workflows/ci.yml` | **Thiếu CI pipeline:** Đã bổ sung workflow GitHub Actions kiểm thử với service MySQL 8.4 + Redis 7 (`check`, `makemigrations --check --dry-run`, `check --deploy`, `manage.py test`). |
| **P1-04** | P1 | **Còn tồn đọng (Blocker môi trường)** | `registrations/tests.py:277`; `core/test_rate_limit_concurrency.py:42` | **Kiểm thử cạnh tranh trên MySQL 8.4 & Redis thật chưa chạy tại máy local:** Máy Windows hiện tại chưa cài MySQL, Redis, Docker; toàn bộ test chạy trên SQLite (`IMMEDIATE`) + `LocMemCache`. Cần chạy trên CI hoặc môi trường MySQL/Redis cách ly trước pilot. |
| **P2-01** | P2 | **Đang nâng cấp (Foundation 0.2.1 đã tích hợp bước 1)** | `aiassist/core/*`; `aiassist/adapters.py`; `aiassist/chatbot.py:331-334`; `aiassist/test_foundation_integration.py` | **Tích hợp KMG AI Foundation 0.2.1 có feature flag (`AI_FOUNDATION_AGENT=False` mặc định):** Đưa lõi độc lập vào `aiassist/core/`, tạo `build_server_actor()` từ `request.user` phía server, `ToolRegistry` chỉ đọc công khai không PII (`list_public_events`, `search_club_knowledge`, `get_club_overview`), `retrieve_knowledge_bm25()` (BM25 + chuẩn hóa tiếng Việt không dấu), `DjangoGatewayProvider` có fallback an toàn về `ask_assistant` / `UNKNOWN_TEXT`. |
| **P2-02** | P2 | **Còn tồn đọng** | `aiassist/chatbot.py:53-116, 247-260`; `aiassist/views.py:176-227` | **Chất lượng intent blind (`31/50 = 62%`), RAG holdout (`6/8 = 75%`) và pseudo-streaming SSE:** Đã cập nhật mô tả SSE phản ánh đúng cơ chế chia nhỏ câu trả lời hoàn chỉnh; chưa triển khai provider streaming thật, nâng cấp intent tiếng Việt / hybrid BM25+embedding cho `retrieve_knowledge()`, circuit breaker hoặc token budget. |
| **P2-03** | P2 | **Còn tồn đọng** | `registrations/services.py:356`; `events/views.py:348`; `organizing/views.py:526, 771`; `feedback/views.py:64` | **Gia cố phụ trợ:** `auto_confirm_transfer` bỏ qua so khớp `account` nếu webhook không gửi `accountNumber`; các endpoint AI dành cho Lead (`suggest_tasks`, `summarize_feedback`, `event_media_ai`, `event_report_generate`) chưa có rate-limit riêng (chỉ có `@lead_required`). |
| **P3-01** | P3 | **Còn tồn đọng** | `aiassist/management/commands/evaluate_ai.py` | Chạy trực tiếp `evaluate_ai --settings=config.settings_test` ngoài `TestCase` báo thiếu bảng do DB tạm chưa migrate (cần cờ `--migrate` hoặc dùng DB đã migrate như `settings_local`). |

---

## 3. Thay đổi thực tế trên nhánh `feature/kmg-ai-v2`
- **File sửa:** `aiassist/chatbot.py`, `aiassist/views.py`, `aiassist/test_safety.py`, `aiassist/management/commands/export_finetune_dataset.py`, `registrations/services.py`, `registrations/views.py`, `pages/services.py`, `config/settings.py`, `core/test_secret_guard.py`, `AGENTS.md` (hợp nhất `AGENTS_PROPOSED.md` vào Mục 6).
- **File mới:** `aiassist/test_chat_boundaries.py`, `aiassist/core/{__init__,contracts,tools,retrieval,agent}.py`, `aiassist/adapters.py`, `aiassist/test_foundation_integration.py`, `registrations/test_security_boundaries.py`, `requirements-production.txt`, `.github/workflows/ci.yml`.
- **Chưa commit / chưa push:** Mọi thay đổi đang nằm an toàn trên working tree của nhánh `feature/kmg-ai-v2` (chưa đụng `main`, chưa push remote, chưa đụng DB thật hay `.env`).

---

## 4. Hướng dẫn Rollback
- Nếu cần quay lại nguyên trạng trước lượt bàn giao: `git checkout main` (nhánh `main` vẫn giữ nguyên tại `315535c`), hoặc xóa nhánh thử nghiệm bằng `git branch -D feature/kmg-ai-v2` sau khi kiểm tra không còn dữ liệu cần giữ. Không có migration mới nào được tạo trong đợt này.

---

## 5. Trạng thái môi trường phối hợp Antigravity ↔ Codex & Khóa File
- **Codex CLI:** `@openai/codex` (`0.172.0`), cấu hình `~/.codex/config.toml` dùng tài khoản ChatGPT (`forced_login_method = "chatgpt"`).
- **Bảng Khoá File Đang Hoạt Động (`Active File Locks`):**

| File / Thư mục | Chủ sở hữu (`antigravity` / `codex`) | Nhánh / Worktree | Mục đích | Thời điểm khóa |
|---|---|---|---|---|
| *(Trống — đã giải phóng toàn bộ khóa sau kiểm thử)* | — | — | — | — |

- **Hàng đợi Bàn giao Nhiệm vụ (`Task Handoff Queue`):**
  - `[T-001]` Review chéo nhánh `feature/kmg-ai-v2` (`codex exec review --base main` sau khi commit) — trạng thái `READY`.
  - `[T-002]` Chạy CI thực tế trên MySQL 8.4 + Redis 7 để xác minh race condition đặt vé, `RedisRateLimitTests`, và build `Dockerfile` — trạng thái `READY`.
  - `[T-003]` Nâng cấp chất lượng KMG AI (P2): cải thiện intent tiếng Việt (`blind` >= 85%), tích hợp `retrieve_knowledge_bm25` vào `services.retrieve_knowledge`, nâng cấp streaming SSE thật & ma trận UAT 100 người dùng đồng thời — trạng thái `READY`.

- **Nhật ký Review Chéo (`Cross-Review Log`):**

| Ngày | Nhánh / Phạm vi | Người thực hiện → Người review | Kết quả | Ghi chú |
|---|---|---|---|---|
| 2026-11-26 | Thiết lập phối hợp Antigravity ↔ Codex | `antigravity` | Sẵn sàng | Khởi tạo `AGENTS.md`, `docs/AI_DEVELOPMENT_STATE.md`, skill `codex-collab`, `~/.codex/config.toml` |
| 2026-11-26 | `feature/kmg-ai-v2` (Phase 0 Audit + Chat Safety + P0/P1 + Foundation 0.2.1) | `antigravity` → chờ `ChatGPT` / `codex` | 578/578 test đạt (2 skip Redis) | Chưa commit/push; chờ duyệt nhánh và chạy MySQL/Redis CI |
