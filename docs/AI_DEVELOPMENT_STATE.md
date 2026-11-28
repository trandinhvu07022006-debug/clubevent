# AI Development State — Clubevent & KMG AI

Tài liệu trạng thái dùng chung cho **Antigravity** và **ChatGPT / OpenAI Codex CLI**. Các Agent phải đọc file này cùng `AGENTS.md` trước khi làm việc và cập nhật khi bàn giao.

---

## 1. Trạng thái hệ thống hiện tại
- **Cập nhật lần cuối:** 2026-11-28 (Antigravity — hoàn tất **KMG Product Refinement 4.0 / Re-Audit Remediation / Roadmap 5.0 phần tự động hóa** trên nhánh `feature/mysql-production-readiness`; xem `docs/audit/15_INDEPENDENT_REAUDIT_REMEDIATION.md` và `docs/audit/16_MASTER_ROADMAP_CONSOLIDATION_HANDOFF.md`)
- **Thư mục gốc dự án:** `D:\clubevent\clubevent`
- **Nhánh Git hiện hành:** `feature/mysql-production-readiness` (baseline `52f45db`).
- **Phần cứng dev:** Intel Core i5-12500H (12 nhân / 16 luồng), RAM 16 GB DDR4-3200 (`16,869,548,032` bytes), NVIDIA GeForce RTX 3050 Laptop GPU (**4 GB VRAM**, `4,293,918,720` bytes) + Intel Iris Xe Graphics.
- **Môi trường kiểm thử:** Python 3.14 (`.\venv\Scripts\python.exe`), Django 5.2.17, SQLite/`LocMemCache` (chưa cài Docker Desktop, Redis Server, Playwright và Ollama tại máy dev Windows; MySQL 8.4 chỉ dành cho dev, không dùng làm test DB).

### Kết quả kiểm chứng sau lượt chỉnh sửa mã nguồn cuối cùng
- `.\venv\Scripts\python.exe -m compileall -q .`: exit `0`.
- `.\venv\Scripts\python.exe manage.py check --settings=config.settings_test`: **0 issues (0 silenced)** (exit `0`).
- `.\venv\Scripts\python.exe manage.py makemigrations --check --dry-run --settings=config.settings_test`: **No changes detected** (exit `0`).
- `.\venv\Scripts\python.exe manage.py check --deploy --settings=config.settings` *(mô phỏng `DEBUG=False`, `KMG_ENV=prod`, `DB_ENGINE=mysql`, `USE_HTTPS=True`, `ALLOW_DEMO_SEED=False`, biến môi trường tạm)*: **0 issues (0 silenced)** (exit `0`).
- `.\venv\Scripts\python.exe -m coverage run --omit="*/migrations/*,*/test*.py" manage.py test --settings=config.settings_test`: **Ran 706 tests in 203.978s — OK (`skipped=3` test tích hợp MySQL thật)**; tổng coverage **79%** (`18,724` stmts, `3,883` miss, `96` file đạt 100%) — đạt ngưỡng `--fail-under=78`.
- `.\venv\Scripts\python.exe manage.py evaluate_ai --with-migrate --settings=config.settings_test`: **EVAL ĐẠT** (`dev` **38/38**, `holdout` **22/22**, `blind` **50/50**, RAG `dev` **13/13**, `holdout` **8/8**, Che PII **6/6**, Fallback đạt, Bảo mật & Music/Companion **7/7**, p50=`0.10ms`, p95=`0.19ms`).
- `.\venv\Scripts\python.exe -m unittest deployment/test_backup_restore.py deployment/test_scheduler.py -v`: **Ran 17 tests in 0.203s — OK (`skipped=1` symlink Windows)**.
- Coverage các mô-đun trọng yếu: `aiassist/business_queries.py` **99%**, `organization/business_consolidation.py` **94%**, `organization/importers.py` **93%**, `organization/permissions.py` **85%**, `deployment/sqlite_to_mysql.py` **85%**, `deployment/mysql_backup.py` **78%**.
- **Codex CLI:** Bỏ qua theo chỉ đạo trực tiếp của người dùng (`"bỏ qua codex và bạn hoàn thiện nốt công việc còn lại đi"`).

---

## 2. Các thay đổi chính trên nhánh `feature/mysql-production-readiness`

1. **Sprint A & B — An toàn chuyển đổi MySQL & Backup/Restore (`33f0082`):**
   - `deployment/sqlite_to_mysql.py`, `deployment/mysql_backup.py`, `core/test_importers_and_migration.py`.
2. **Sprint C — KMG AI & Quyền nghiệp vụ (`67cf549`):**
   - `aiassist/business_queries.py`, `aiassist/views.py`, `aiassist/test_business_queries.py`, `aiassist/test_ai_consolidation.py`.
3. **Sprint E — Frontend Refinement & KMG Soft Icons (`fa91ea0`, đợt vá CI & Dark-mode sau `afe00d6`):**
   - `templates/**`, `static/css/tokens.css`, `pages/tests.py`, `pages/test_sprint_e_ui.py`, `finance/test_phase5_finance.py`.
4. **Kiến trúc sản phẩm, Hiệu năng truy vấn & Diễn tập hợp nhất nghiệp vụ (`afe00d6`, đợt hoàn thiện Roadmap 5.0):**
   - `organization/permissions.py` (`_preloaded` trong `summarize_actor_context()`), `organization/views.py` (tối ưu N+1 `workspace_home`), `organization/business_consolidation.py`, `core/management/commands/audit_unified_business.py`, `core/test_unified_business_rehearsal.py`, `core/test_uat_e2e.py` (query budget `dashboard <= 30`, `workspace_home <= 45`).
   - Báo cáo kiến trúc & kiểm toán: `docs/PRODUCT_ARCHITECTURE.md`, `docs/UNIFIED_BUSINESS_SYSTEM_PLAN.md`, `docs/audit/14_KMG_PRODUCT_REFINEMENT_REPORT.md`, `docs/audit/15_INDEPENDENT_REAUDIT_REMEDIATION.md`, `docs/audit/16_MASTER_ROADMAP_CONSOLIDATION_HANDOFF.md`.

---

## 3. Blocker môi trường & Việc chờ xác nhận

- **GitHub Actions CI (`46145635488` tại `7e7c512`):** Đã đạt xanh cả 3 job `test-sqlite` (706 tests OK, skipped=2), `test-mysql-redis` (706 tests OK, 17 deploy tests OK, coverage 79%, `EVAL ĐẠT`), và `docker-build-check` (success). Đã bổ sung job thứ 4 `playwright-ui-audit` theo phê duyệt `D-03` của Chủ dự án (2026-11-28).
- **Ollama Local LLM benchmark:** Phần cứng `RTX 3050 (4 GB VRAM)` sẵn sàng cho mô hình `Q4_K_M` 1.5B–3B, nhưng chưa cài Ollama tại máy dev nên benchmark thực tế giữ trạng thái `BLOCKED`.
- **Browser screenshot responsive (`320px–1920px`) & UAT 7 vai trò:** Chạy tự động qua GitHub Actions `playwright-ui-audit` trên staging SQLite cô lập (`deployment/playwright_ui_audit.py`), sau đó Chủ dự án/đại diện CLB thực hiện `UAT-05` thực tế trước khi phát hành.

---

## 4. Trạng thái môi trường phối hợp Antigravity ↔ Codex & Khóa File

| File / Thư mục | Chủ sở hữu | Nhánh | Mục đích | Thời điểm khóa |
|---|---|---|---|---|
| *(Trống — đã giải phóng toàn bộ khóa file sau kiểm thử)* | — | `feature/mysql-production-readiness` | — | 2026-11-28 |

- **Hàng đợi bàn giao còn lại (Chủ dự án / BCN / Môi trường ngoài):**
  - `[D-01]` **ĐÃ DUYỆT (2026-11-28):** Chốt `organization.Department`, `operations.ClubTask`, `organization.MembershipApplication` là nguồn dữ liệu chính thức (`docs/UNIFIED_BUSINESS_SYSTEM_PLAN.md`), giữ nguyên bảng & route cũ.
  - `[D-03]` **ĐÃ DUYỆT (2026-11-28):** Bổ sung job `playwright-ui-audit` vào `.github/workflows/ci.yml` + `deployment/playwright_ui_audit.py` để kiểm thử & chụp screenshot Light/Dark (`320–1920px`) trên staging cô lập trong CI.
  - `[D-02]` Chủ dự án duyệt gallery KMG Soft Icons (`UI-01`, `UI-04`) sau khi xem screenshot từ CI artifact `playwright-ui-audit-report`.
  - `[AI-10]` BCN & Ban Chuyên môn duyệt **46 mục tri thức pending** theo danh mục `docs/audit/17_AI_46_KNOWLEDGE_REVIEW_QUEUE.md`.
  - `[UAT-05]` Chủ dự án và đại diện vai trò CLB nghiệm thu người dùng thật trên staging.
  - `[D-04 / REL-04]` Kiểm tra CI xanh cùng SHA mới nhất (gồm cả `playwright-ui-audit`), diễn tập Docker/MySQL restore (`BK-04`) và Chủ dự án quyết định Go/No-Go trước khi tạo PR hoặc merge `main`.

---

## 5. Hướng dẫn Rollback & Khắc phục RC1
- Chi tiết khắc phục `AUD-001`–`AUD-014`: xem `docs/audit/08_INDEPENDENT_REVIEW_REMEDIATION.md` và `docs/audit/09_RELEASE_CANDIDATE_READINESS.md`.
- Nhánh `main` không bị thay đổi (`315535c`).
- Trên nhánh `feature/kmg-system-stabilization` có thêm migration `aiassist/migrations/0006_clubknowledge_visibility.py` và `aiassist/migrations/0007_rc1_security_hardening.py` (sau `0005`). Nếu DB đã chạy `migrate` trên nhánh mới và cần quay về `main`, chạy `python manage.py migrate aiassist 0004` trước khi `git checkout main`.
