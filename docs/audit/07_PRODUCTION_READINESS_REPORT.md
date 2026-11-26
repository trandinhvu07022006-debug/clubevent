# PHASE 7 — BÁO CÁO SẴN SÀNG TRIỂN KHAI (PRODUCTION READINESS REPORT)

**Ngày thực hiện:** 2026-11-26  
**Nhánh làm việc:** `feature/kmg-system-stabilization`  

---

## 1. Thành phần triển khai & Vận hành hiện có (`P7.1` & `P7.2`)

- **Container & Reverse Proxy:** `Dockerfile` (Python 3.12-slim, user không phải root `kmg`, `collectstatic` tích hợp), `compose.yaml` (MySQL 8.4 `utf8mb4_0900_ai_ci`, Redis 7 AOF, migrate container, Gunicorn `web`, `scheduler`, Nginx), `deployment/gunicorn.conf.py` (`forwarded_allow_ips = ""`), `deployment/nginx.conf.template` (chặn `/private_vault/`, `X-Forwarded-Host $http_host`, `Referrer-Policy`, `CSP`).
- **Healthcheck & Scheduler:** `deployment/healthcheck.py` (`/health/` HTTP 200 JSON), `deployment/scheduler.py` (chạy định kỳ `run_periodic` và `run_kmg_operations`, trạng thái nguyên tử JSON) và `deployment/scheduler_healthcheck.py`.
- **Backup & Khôi phục thảm họa (`deployment/backup_restore.py`, `deployment/volume_archive.py`):** Đóng gói sao lưu MySQL dump + Media + Private Vault + manifest khóa ký (`SECRET_KEY`, `CERT_SIGNING_KEY`, `CHAT_MASTER_KEK`) có kiểm tra hash/tampering trước khi giải nén sang project mới cách ly (`RPO <= 24h`, `RTO <= 4h`).
- **Kiểm chứng trên nhánh ổn định:**
  - `python manage.py check --deploy --settings=config.settings` (biến prod giả lập HTTPS): **0 issues (0 silenced)** — **VERIFIED**.
  - `python -m unittest deployment/test_backup_restore.py deployment/test_scheduler.py -v`: **17 tests — OK (skipped=1 symlink trên Windows)** — **VERIFIED**.
  - Docker build & startup stack thực tế (`docker build`, `docker compose up`): **BLOCKED** trên máy Windows dev (chưa cài Docker Desktop) — cần chạy qua GitHub Actions (`docker-build-check`) hoặc VPS Linux.

---

## 2. Tài liệu vận hành, UAT & Bàn giao (`P7.3` & `P7.4`)

| Hạng mục | Tài liệu hiện có trong repo | Trạng thái |
|---|---|---|
| Kế hoạch Pilot & Ma trận UAT 7 vai trò | `docs/PILOT_PLAN.md`, `docs/UAT_PILOT_MATRIX.md` | **IMPLEMENTED** (cần diễn tập trực tiếp với 5–10 tài khoản thật trước sự kiện) |
| Hướng dẫn Deploy & Backup/Restore | `docs/huong-dan-deploy.md`, `docs/deployment/DEPLOYMENT_AND_BACKUP.md`, `.env.production.example` | **IMPLEMENTED** |
| Sổ tay Quản trị & Người dùng | `docs/ADMIN_HANDBOOK.md`, `docs/USER_GUIDE.md` | **IMPLEMENTED** |
| Tài liệu Bàn giao Nhiệm kỳ & AI | `docs/LOCAL_HANDOVER.md`, `docs/LOCAL_LLM_READINESS.md`, `docs/AI_DEVELOPMENT_STATE.md` | **IMPLEMENTED** |
| Phê duyệt phát hành KMG v1.0 | — | **REVIEW_REQUIRED** (chờ CI MySQL+Redis+Docker xanh trên GitHub Actions, review độc lập và duyệt merge vào `main`) |

---

## 3. Kế hoạch Rollback khi nâng cấp lên KMG v1.0
1. Trước mọi đợt migrate trên server thật: chạy sao lưu bằng `deployment/backup_restore.py`.
2. Trên nhánh `feature/kmg-system-stabilization` có 1 migration mới là `aiassist/migrations/0006_clubknowledge_visibility.py` (nối sau `0005_scrub_internal_event_logs.py`). Nếu cần quay lại `main` (`315535c`) sau khi đã migrate trên DB, chạy `python manage.py migrate aiassist 0004` rồi `git checkout main`.
