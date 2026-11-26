# ĐÁNH GIÁ SẴN SÀNG RELEASE CANDIDATE 1 — KMG RC1 READINESS REPORT

**Dự án:** Clubevent & KMG AI Platform (KMA Guitar Club)  
**Nhánh phát hành ứng viên:** `feature/kmg-system-stabilization`  
**Trạng thái đề xuất:** **READY FOR CI & INDEPENDENT RC1 RE-AUDIT** *(có điều kiện hoàn tất các bước ngoài máy dev bên dưới trước khi merge `main`)*  
**Ngày lập:** 2026-11-26  

---

## 1. Tóm tắt Mức độ Đạt chuẩn (RC1 Gate Summary)

| Cổng kiểm soát (Release Gate) | Tình trạng tại máy dev Windows | Trạng thái trên CI GitHub Actions | Ghi chú |
|---|---|---|---|
| **Static check, Deploy check & Migrations** | **VERIFIED** (`0 issues`, `No changes detected`) | Có trong `test-mysql-redis` | Bao gồm `aiassist/0007_rc1_security_hardening` |
| **Production Fail-Closed Config (`AUD-002`)** | **VERIFIED** (`core.test_secret_guard` PASS) | Có | Từ chối key yếu/trùng, wildcard `*`, `ALLOW_DEMO_SEED=True`, proxy không nhất quán |
| **AI Egress, Canonical RBAC & Privacy (`AUD-003..007`)** | **VERIFIED** (141/141 `aiassist` tests + `evaluate_ai` PASS) | Có | Cloud LLM chỉ nhận `PUBLIC`; Local không fallback ra Cloud cho `INTERNAL`/`CONFIDENTIAL`/`PRIVATE_PII` |
| **Concurrency, Lock Order & Finance ACL (`AUD-008..009`)** | **VERIFIED** (`registrations` + `finance` concurrency/regressions PASS) | Có trên cả SQLite & MySQL 8.4 + Redis 7 | Khóa theo thứ tự `User -> TicketType -> Ticket -> WaitlistEntry` + bounded deadlock retry |
| **Test Suite & Coverage Gate (`AUD-012`)** | **VERIFIED** (**657 tests**, **78%** coverage) | Bắt buộc `--fail-under=78` trong `.github/workflows/ci.yml` | 2 skip `RedisRateLimitTests` ở local SQLite; chạy full trên CI Redis |
| **Docker Compose Full Stack (`AUD-001`)** | **BLOCKED** *(chưa cài Docker Desktop trên Windows)* | Đã sửa `.github/workflows/ci.yml` (`docker-build-check`) | Kiểm chứng thực tế MySQL, Redis, migrate, web, scheduler, Nginx & HTTP `/health/` khi push |
| **Playwright Headless UI (`360px–1920px`) (`AUD-010`)** | **BLOCKED** *(thiếu `playwright` / browser binary)* | Chưa có job Playwright | Đã phủ tầng view/HTML/viewport qua `core/test_uat_e2e.py` (PASS) |
| **Disaster Recovery Live Drill (`AUD-013`)** | **BLOCKED** *(thiếu Docker Desktop)* | Unit tests (`test_backup_restore.py`, `test_scheduler.py`) PASS | Live MySQL/Redis/media/vault restore drill cần thực thi trên host Docker Staging |
| **Human UAT Pilot 7 Vai trò (`AUD-011`)** | **REVIEW_REQUIRED** | N/A | Cần Ban Chủ nhiệm / Chủ dự án diễn tập & ký nhận trên Staging |

---

## 2. Đề xuất Quy tắc Bảo vệ Nhánh `main` (GitHub Branch Protection / Ruleset — `AUD-014`)

Trước khi hợp nhất RC1 vào `main`, chủ repository nên bật các quy tắc sau trên GitHub Repository Settings → Branches / Rulesets cho nhánh `main`:

1. **Require a pull request before merging** (tối thiểu 1 phê duyệt review từ Chủ dự án / Technical Auditor).
2. **Require status checks to pass before merging** với đủ 3 job CI bắt buộc:
   - `test-mysql-redis` (Django suite + coverage `--fail-under=78` + `ruff` + `pip-audit` + `evaluate_ai --with-migrate` + `deployment` unittests)
   - `test-sqlite`
   - `docker-build-check` (`docker compose config -q`, build, khởi động full stack, verify Nginx `/health/` & login + static CSS)
3. **Require linear history** hoặc squash/merge commit kiểm soát; **Restrict deletions** & **Block force pushes** trên `main`.
4. **Không lưu bất kỳ `.env`, `.env.production` hay dữ liệu UAT thật nào vào Git** (`.gitignore` đã loại trừ).

---

## 3. Các Hạng mục Còn `BLOCKED` / `REVIEW_REQUIRED` (Trung thực Trạng thái)

1. **`docker-build-check` live execution (`AUD-001`)**: Đã hoàn chỉnh pipeline trong `.github/workflows/ci.yml`; cần kết quả thực tế từ GitHub Actions runner sau push cuối cùng.
2. **MySQL 8.4 + Redis 7 live integration (`657 tests`, gồm `RedisRateLimitTests`)**: Cần kết quả từ job `test-mysql-redis` trên GitHub Actions sau push.
3. **Live Backup & Restore Docker Volume Drill (`AUD-013`)**: Cần thực hiện 1 lần trên staging Linux/Docker bằng `deployment/backup_restore.py` trước go-live.
4. **Playwright Visual Regression (`360px–1920px`) (`AUD-010`) & Local Ollama Latency Benchmark**: Máy Windows dev thiếu Playwright binary và Ollama; giữ trạng thái `BLOCKED`.
5. **Human UAT 7 Vai trò (`AUD-011`)**: Giữ trạng thái `REVIEW_REQUIRED` theo `docs/UAT_PILOT_MATRIX.md`.

---

## 4. Hướng dẫn Rollback Khẩn cấp cho RC1

- Nhánh `main` không hề bị tác động (giữ nguyên tại `315535c`).
- Nếu cần đưa DB thử nghiệm (đã migrate lên nhánh `feature/kmg-system-stabilization`) quay lại trạng thái tương thích `main`:
  ```bash
  python manage.py migrate aiassist 0004
  git checkout main
  ```
- Không có migration thay đổi bảng nghiệp vụ ở `registrations` hay `finance` trong đợt RC1 (`0007_rc1_security_hardening` chỉ nằm trong `aiassist`).
