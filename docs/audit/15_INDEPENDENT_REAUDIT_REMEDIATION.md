# Báo cáo 15 — Independent Re-Audit Remediation (Release Blocker Remediation)

**Ngày thực hiện:** 2026-11-28  
**Nhánh làm việc:** `feature/mysql-production-readiness` (không merge `main`, không deploy production, không thao tác DB thật)  
**Baseline kiểm duyệt:** `52f45dbf746fe88718d20ffdec108086e7825919` *(các thay đổi hiện tại đang ở working tree, chưa tạo commit mới)*

---

## Sprint A — P0: An toàn chuyển đổi dữ liệu (`deployment/sqlite_to_mysql.py`)

| Mã lỗi | Nguyên nhân trước khi sửa | Bản vá đã áp dụng | Kiểm thử tái hiện & xác minh |
|---|---|---|---|
| **A-01: Commit dở dang khi lỗi cột hoặc đối soát** | `if report.errors: break` thoát vòng lặp mà không raise exception nên `transaction.atomic` vẫn commit; toàn bộ đối soát (`COUNT(*)`, `fk_orphans`, tài chính) nằm **ngoài** `transaction.atomic`. | Thêm `MigrationAbortError`; chuyển toàn bộ kiểm tra cột bắt buộc và đối soát sau ghi (`COUNT(*)`, dải PK `MIN(id)/MAX(id)`, `_check_target_orphans`, `_target_finance_totals`) **vào trong** `with transaction.atomic(using=target_alias):`, buộc rollback 100% khi `report.errors` khác rỗng. | `core/test_importers_and_migration.py`: `test_execute_mode_with_mocked_mysql_connection` (case #3 lỗi tài chính cố ý buộc `atomic.__exit__` nhận exception và rollback). |
| **A-02: Thiếu bảng trung gian M2M & loại trừ phiên** | `_ordered_django_tables()`, `_check_sqlite_orphans()`, `_check_target_orphans()` gọi `apps.get_models()` (bỏ qua bảng trung gian M2M); sao chép cả `django_session`. | Đổi sang `apps.get_models(include_auto_created=True)`; loại trừ có giải trình `django_session`, `django_migrations`, `sqlite_sequence` (`excluded_tables`); ánh xạ `django_content_type` và `auth_permission` theo natural key (`_build_natural_key_maps`, `_remap_natural_key_columns`). | `SqliteBackupGuardAndNaturalKeyTests` + `core/test_phase7_mysql_readiness.py`. |
| **A-03: Chưa bắt buộc snapshot nhất quán & integrity_check trước EXECUTE** | `EXECUTE` cho phép không truyền `backup_dir` và đọc trực tiếp từ `src_path` đang chạy; chưa kiểm `PRAGMA integrity_check` và chưa chặn backup trong repo. | Bắt buộc `--backup-dir` ngoài thư mục repo (`REPO_ROOT`) khi `dry_run=False`; chạy `backup_sqlite_source()` bằng `sqlite3.Connection.backup()`, xác minh `PRAGMA integrity_check == ok`, ghi SHA-256 (`0o700`/`0o600`) và đọc dữ liệu từ chính file snapshot đó. | `test_execute_mode_with_mocked_mysql_connection` (#0) + `test_backup_inside_repo_rejected_and_session_excluded`. |
| **A-04: Dry-run schema MySQL & Test MySQL thật (`DB-08`)** | `dry_run=True` chỉ chạy `_normalize_row` trên SQLite; chưa có test tích hợp execute trên MySQL thật. | Thêm `_validate_mysql_dry_run()` (tồn tại bảng, collation `utf8mb4_*`, `VARCHAR(N)`, `NOT NULL`, `UNIQUE`), đối chiếu chữ ký PK (`COUNT/MIN/MAX/SUM(id)`), và bổ sung `RealMySqlMigrationIntegrationTests` (`@skipUnless(connection.vendor == "mysql")`) cho CI `test-mysql-redis`. | `test_mysql_dry_run_schema_collation_varchar_and_unique_checks` (PASS local); `RealMySqlMigrationIntegrationTests` (sẽ chạy trên CI MySQL 8.4). |

---

## Sprint B — P0: Sao lưu và khôi phục (`deployment/mysql_backup.py` & `deployment/backup_restore.py`)

| Mã lỗi | Nguyên nhân trước khi sửa | Bản vá đã áp dụng | Kiểm thử tái hiện & xác minh |
|---|---|---|---|
| **B-01: `restore_mysql_backup` không kiểm tra fingerprint khóa** | Chỉ gọi `validate_backup()`, bỏ qua `key_fingerprints` trong `manifest.json`. | Đối chiếu `compose_backups.key_fingerprints(key_env)` với `manifest["key_fingerprints"]` **trước khi** chạm vào DB hoặc thư mục đích. | `MysqlBackupSecurityTests.test_backup_refuses_overwrite_and_restore_checks_keys_and_nonempty_dirs` (PASS). |
| **B-02: `restore_mysql_backup` không kiểm tra media/vault/symlink/trùng path trước import DB** | Kiểm tra DB trống nhưng không kiểm tra `target_media` / `target_vault` (hoặc symlink/lồng nhau) trước khi chạy `mysql` import. | Chặn symlink (`is_symlink()`), chặn `target_media` / `target_vault` trùng/lồng nhau hoặc nằm trong `source_dir`, và bắt buộc cả hai thư mục đích trống **trước khi** gọi `mysql` import. | `MysqlBackupSecurityTests` (PASS — từ chối trước khi gọi `mysql`). |
| **B-03: `create_mysql_backup` có thể ghi đè backup cũ & thiếu phân quyền** | Dùng `dest.mkdir(exist_ok=True)` và mở file `"wb"`. | Đổi sang `dest.mkdir(mode=0o700, parents=False, exist_ok=False)`, mở artifact bằng `"xb"` (`0o600`) và ghi `manifest.pending.json` → `manifest.json` nguyên tử. | `MysqlBackupSecurityTests` (PASS — `FileExistsError` khi ghi trùng). |

---

## Sprint C — P0: KMG AI (`aiassist/business_queries.py`)

- **`query_finance_summary`**: Tái sử dụng `can_view_club_finance(user)` và `compute_club_fund_summary()` từ `finance/services.py` (bao gồm cả bút toán `ADJUSTMENT` `CREDIT`/`DEBIT`), đồng bộ 100% số liệu với `finance_hub`.
- **`query_department_ops`**: Kiểm tra `dept.task.assign` hoặc `dept.task.view_all` theo từng `Department` thực tế; không mở rộng xem toàn CLB nếu không có `club.event.approve` / `club.dept.supervise_ops`.
- **`query_my_recruitment_status`**: Hợp nhất truy vấn cả canonical `organization.MembershipApplication` và legacy `recruitment.Application` (strictly `user=user`) để không báo nhầm "chưa nộp đơn".
- **`query_my_evaluations` & `query_club_analytics`**: Dùng `EvaluationStatus.CONFIRMED`, sửa route `evaluations:hub`, `organization:governance_center` / `organization:advisor_overview` / `organization:workspace_home`, và bảo vệ `_check_active_user` cho mọi `query_my_*`.
- **Kiểm thử JSON API, SSE & Egress/Export Canary:** Bổ sung `test_finance_adjustment_and_json_sse_endpoints` trong `aiassist/test_business_queries.py` và `test_confidential_knowledge_never_exported_by_default` trong `aiassist/test_ai_consolidation.py`.

---

## Sprint E — Hoàn thiện sản phẩm (UI/UX, KMG Soft Icons, Việt hóa, Sáng/Tối & Thống nhất cũ/mới)

- **KMG Soft Icons 1.0 & Tinh giản theo vai trò:**
  - Triển khai `{% kmg_icon %}` đồng bộ cho các KPI, đầu mục bảng và lối tắt trên `templates/pages/dashboard.html` và `templates/organization/workspace_home.html`, giữ nguyên bộ token và phong cách KMG.
  - Bố cục sidebar 6 nhóm nghiệp vụ (`Tổng quan`, `Hoạt động & Âm nhạc`, `Công việc`, `Tổ chức`, `Cộng đồng`, `Quản lý`) + `Trợ lý KMG` xuyên suốt, bỏ trùng lặp `Hồ sơ cá nhân` khỏi sidebar (`templates/base.html`).
- **Thống nhất nghiệp vụ cũ/mới trên giao diện:**
  - Liên kết trực tiếp 2 chiều giữa `organizing:my_tasks` ↔ `operations:task_list` và `organizing:department_list` ↔ `organization:workspace_home`, kèm lối tắt `Không gian nội bộ CLB` trên `pages/dashboard.html` cho thành viên CLB.
- **Việt hóa & Tương thích Light/Dark Mode:**
  - Loại bỏ `KMG Platform`, `WF13–WF15`, `INV-01`, `INV-04`, `PA-01`, `BE-07`, `Demo`, `Read-Only`, `ACTIVE` khỏi giao diện người dùng tại `workspace_home.html`, `task_list.html`, `document_vault.html`, `post_card.html`, `abuse_reports.html`, `advisor_overview.html`, `dashboard.html` và các tiêu đề trang.
  - Thay `table-light`, `alert-light`, `text-bg-light` bằng class thích ứng theme (`bg-body-tertiary`, `bg-body-secondary text-body`) để đảm bảo độ tương phản ở cả Light và Dark mode.
- **Kiểm thử tự động Sprint E (`pages/test_sprint_e_ui.py`):**
  - Chạy `manage.py test pages organizing operations organization.test_permission_matrix --settings=config.settings_test`: **Ran 114 tests in 40.111s — OK**.

---

## Tổng hợp Chất lượng & Blocker môi trường (Sprint D)

| Kiểm thử / Cổng chất lượng | Kết quả thực tế | Ghi chú |
|---|---|---|
| Toàn bộ Django test suite (`config.settings_test`, SQLite) | **PASS** (exit `0`), tổng coverage **79%** (`18,597` stmts, `3,889` miss, `95` file 100%) | Đạt cổng `--fail-under=78` (không hạ ngưỡng, không xóa test) |
| Coverage mục tiêu từng module | `business_queries.py`: **99%**, `importers.py`: **93%**, `sqlite_to_mysql.py`: **85%**, `mysql_backup.py`: **78%** | `business_queries.py` >= 95% đạt; `sqlite_to_mysql.py` còn nhánh MySQL thật chạy ở CI |
| `manage.py evaluate_ai --with-migrate --settings=config.settings_test` | **EVAL ĐẠT** (`dev` 38/38, `holdout` 22/22, `blind` 50/50, RAG `dev` 13/13, `holdout` 8/8, PII 6/6, Music/Companion 7/7) | — |
| `deployment/test_backup_restore.py` & `deployment/test_scheduler.py` | **17 tests — OK (`skipped=1` symlink Windows)** | — |
| `codex login status` / Cross-review (`G0`–`G4`) | **`Not logged in`** (chưa chạy được `codex exec review --uncommitted`) | Người dùng cần chạy `codex login` trước khi kích hoạt review chéo |
| MySQL 8.4 + Redis 7 + Docker + Playwright live restore | **BLOCKED tại máy dev Windows** (thiếu Docker Desktop, Redis Server, Playwright) | Cần phê duyệt commit & push lên nhánh feature để CI GitHub Actions chạy `test-mysql-redis` & `docker-build-check` |

---

## Cập nhật Bổ sung — Sprint 6 (`UI-06`, `UI-08`, `UAT-02`)
- **Việt hóa toàn diện theo `docs/design/UI_TERMINOLOGY_VI.md`:** Loại bỏ hoàn toàn `Intelligent Music Companion`, `LLMOps & AI Training Studio`, `modun/Modun`, `Eval Suite`, `D04 v1.1`, `Nâng Role`, `READ_ONLY`, `Hard Read-Only`, `WF09–WF24`, `INV-01/03/04`, `PA-01..07`, `BE-02/04/05/07`, `SEC-01/04/05`, `CM-01` khỏi toàn bộ giao diện và HTML comments gửi về client tại `templates/aiassist/chat.html`, `studio.html`, `aiassist/views.py`, `templates/evaluations/*.html`, `templates/finance/*.html`, `templates/operations/*.html`, `templates/programs/*.html`, `templates/social/*.html`, `templates/organization/advisor_overview.html`, `department_detail.html`, `governance_center.html`, `templates/accounts/membership_status.html`.
- **Nâng cấp `templates/aiassist/chat.html` (`UI-08`):** Tích hợp `{% kmg_icon %}` (`sparkles`, `message`, `sliders`, `music`, `send`) và thống nhất tiếng Việt tự nhiên.
- **Kiểm chứng sau chỉnh sửa cuối:** `manage.py test pages.test_sprint_e_ui core.test_uat_e2e aiassist.test_business_queries aiassist.test_ai_consolidation core.test_importers_and_migration --settings=config.settings_test` → **Ran 28 tests in 3.735s — OK (`skipped=1` `RealMySqlMigrationIntegrationTests` trên SQLite)**.
