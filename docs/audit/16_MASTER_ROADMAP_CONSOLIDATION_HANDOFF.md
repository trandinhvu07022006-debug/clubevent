# Báo cáo Bàn giao Hợp nhất — KMG Master Roadmap 5.0 (Sprint 0–8)

- **Ngày lập:** 2026-11-28
- **Nhánh Git:** `feature/mysql-production-readiness`
- **Baseline kiểm duyệt:** `52f45dbf746fe88718d20ffdec108086e7825919`
- **Các commit đã đẩy trước lượt này:** `33f0082`, `67cf549`, `fa91ea0`, `afe00d6`
- **Ghi chú điều phối:** Người dùng chỉ định **bỏ qua Codex CLI** (`bỏ qua codex và bạn hoàn thiện nốt công việc còn lại đi`). Không tự merge `main`, không chuyển dữ liệu thật, không deploy production, không hạ ngưỡng `--fail-under=78`, và không tự đánh dấu các cổng do Chủ dự án/BCN/người dùng thật duyệt (`D-01`–`D-04`, `AI-10`, `UAT-05`, `REL-04`) là `Đã xác minh`.

---

## 1. Tóm tắt kết quả xác minh cục bộ sau bản vá cuối cùng

| Hạng mục kiểm định | Lệnh thực thi | Kết quả quan sát |
|---|---|---|
| Compile tĩnh toàn bộ repo | `.\venv\Scripts\python.exe -m compileall -q .` | Exit `0` |
| Django system check | `.\venv\Scripts\python.exe manage.py check --settings=config.settings_test` | `System check identified no issues (0 silenced)` |
| Kiểm tra đồng bộ migration | `.\venv\Scripts\python.exe manage.py makemigrations --check --dry-run --settings=config.settings_test` | `No changes detected` |
| Deploy check mô phỏng prod (`MySQL + HTTPS + ALLOW_DEMO_SEED=False`) | `.\venv\Scripts\python.exe manage.py check --deploy --settings=config.settings` | `System check identified no issues (0 silenced)` |
| Backup/Restore & Scheduler unit tests | `.\venv\Scripts\python.exe -m unittest deployment/test_backup_restore.py deployment/test_scheduler.py -v` | `Ran 17 tests in 0.203s — OK (skipped=1)` *(symlink Windows)* |
| Đánh giá chất lượng AI | `.\venv\Scripts\python.exe manage.py evaluate_ai --with-migrate --settings=config.settings_test` | `EVAL ĐẠT` (`dev` 38/38, `holdout` 22/22, `blind` 50/50, RAG `dev` 13/13, `holdout` 8/8, PII `6/6`, Fallback đạt, Bảo mật & Music/Companion `7/7`, p50=`0.10ms`, p95=`0.19ms`) |
| Toàn bộ Test Suite + Coverage | `.\venv\Scripts\python.exe -m coverage run --omit="*/migrations/*,*/test*.py" manage.py test --settings=config.settings_test` & `coverage report --skip-covered --fail-under=78` | `Ran 706 tests in 203.978s — OK (skipped=3)` *(3 test tích hợp MySQL thật `@skipUnless(mysql)` chạy trên CI `test-mysql-redis`)*; **TOTAL 79%** (`18,724` stmts, `3,883` miss, `96` file đạt 100%) |

### Độ phủ (Coverage) tại các mô-đun trọng yếu
- `aiassist/business_queries.py`: **99%** (`148` stmts, `2` miss)
- `organization/business_consolidation.py`: **94%** (`95` stmts, `6` miss)
- `organization/importers.py`: **93%** (`340` stmts, `23` miss)
- `organization/permissions.py`: **85%** (`236` stmts, `35` miss)
- `deployment/sqlite_to_mysql.py`: **85%** (`442` stmts, `65` miss)
- `deployment/mysql_backup.py`: **78%** (`111` stmts, `24` miss)

---

## 2. Bản vá bổ sung sau kiểm duyệt CI `46144239649` (`afe00d6`)

1. **Khắc phục lỗi `test-sqlite` và `test-mysql-redis` trên CI (`afe00d6`):**
   - **Nguyên nhân:** Commit `fa91ea0` đã gỡ mã quy tắc kỹ thuật `INV-04` khỏi `templates/finance/hub.html`, trong khi `finance/test_phase5_finance.py` (`test_inv04_advisor_hard_read_only`, được kế thừa bởi `FinanceViewsAndApiCoverageTests`) vẫn assert chuỗi `"INV-04"`.
   - **Bản vá:** Cập nhật `finance/test_phase5_finance.py` kiểm tra đúng thông điệp tiếng Việt `"Chế độ Cố vấn — chỉ xem báo cáo tổng hợp."` và bỏ nốt nhãn kỹ thuật `CM-03` khỏi `templates/finance/hub.html`, `templates/finance/transaction_detail.html`, `templates/organization/department_detail.html`.
2. **Giảm N+1 query tại `organization:workspace_home` (`QA-06`):**
   - **Nguyên nhân:** `PermissionEngine.summarize_actor_context()` gọi `cls.authorize()` 11 lần và `cls.get_department_access_mode()` nhiều lần mà không tái sử dụng dữ liệu đã nạp trong cùng lần tổng hợp; `workspace_home` đồng thời gọi `.count()` từng Ban trong vòng lặp (`64–68` truy vấn).
   - **Bản vá:** Truyền trạng thái `_preloaded` nội bộ trong `PermissionEngine.summarize_actor_context()` (`organization/permissions.py`) để đánh giá 0 truy vấn phụ cho các kiểm tra trong cùng context; annotate `active_member_count` và dùng lại `my_dept_mode_map` tại `organization/views.py`; thiết lập assertion ngân sách truy vấn tại `core/test_uat_e2e.py` (`dashboard <= 30`, `workspace_home <= 45`).
3. **Diễn tập hợp nhất nghiệp vụ không ghi DB thật (`BUS-01` / `BUS-03`):**
   - Hoàn thiện `organization/business_consolidation.py` (`run_unified_business_rehearsal`), `core/management/commands/audit_unified_business.py`, `core/test_unified_business_rehearsal.py` (chứng minh dry-run 0 ghi, execute chuyển sang `organization.Department`/`operations.ClubTask`/`organization.MembershipApplication`, chạy lại idempotent và không xóa bảng cũ).
4. **Đồng bộ Dark-mode (`UI-05` / `UI-09`):**
   - Bổ sung override `[data-bs-theme="dark"]` cho `.text-bg-light`, `.alert-light`, `.table-light` trong `static/css/tokens.css`.

---

## 3. Tổng hợp trạng thái 63 nhiệm vụ (`KMG_Master_Roadmap_5.0.xlsx`)

> Quy ước trạng thái:
> - `AUTOMATED_VERIFIED`: Đã cài đặt và xác minh qua test tự động cục bộ (`SQLite` cách ly) + kiểm tra tĩnh/deploy.
> - `PENDING_CI_RUN`: Đang chờ kết quả chạy mới của GitHub Actions (`test-sqlite`, `test-mysql-redis`, `docker-build-check`) trên commit mới push.
> - `BLOCKED_ENV`: Môi trường cục bộ không có dịch vụ ngoài (`Docker`, `Redis`, `Playwright`, `Ollama`).
> - `AWAITING_HUMAN_APPROVAL`: Thuộc thẩm quyền phê duyệt của Chủ dự án / BCN / người dùng thật.

### Sprint 0 — Baseline & Điều phối (`G0`)
| Mã | Ưu tiên | Trạng thái | Bằng chứng & Ghi chú |
|---|---|---|---|
| `GOV-01` | P0 | `AUTOMATED_VERIFIED` | Đối chiếu baseline `52f45db` → `afe00d6` → HEAD mới; kiểm tra diff & CI `46144239649` (`docs/AI_DEVELOPMENT_STATE.md`, `docs/audit/14..16`). |
| `GOV-02` | P0 | `AUTOMATED_VERIFIED` | Tuân thủ Single-Writer trên `feature/mysql-production-readiness`; khóa file được ghi và giải phóng đầy đủ trước push; bỏ qua Codex theo chỉ đạo người dùng. |
| `GOV-03` | P0 | `AUTOMATED_VERIFIED` | Chạy cô lập hoàn toàn qua `config.settings_test`, `core/db_guard.py`, mock AI/email/SMS; không chạm DB dev/prod. |
| `GOV-04` | P1 | `AUTOMATED_VERIFIED` | Đã lập ma trận truy vết lỗi → bản vá → test → SHA → trạng thái tại `docs/audit/15_INDEPENDENT_REAUDIT_REMEDIATION.md` và báo cáo này. |
| `BUS-01` | P1 | `AUTOMATED_VERIFIED` | Kiểm kê và đối chiếu 3 cặp mô hình song song trong `docs/UNIFIED_BUSINESS_SYSTEM_PLAN.md` & `organization/business_consolidation.py`. |

### Sprint 1 — Chuyển đổi MySQL (`G1`)
| Mã | Ưu tiên | Trạng thái | Bằng chứng & Ghi chú |
|---|---|---|---|
| `DB-01` | P0 | `AUTOMATED_VERIFIED` | `deployment/sqlite_to_mysql.py` (`33f0082`) kiểm kê `include_auto_created=True` (M2M/ACL), kiểm thử trong `core/test_importers_and_migration.py`. |
| `DB-02` | P0 | `AUTOMATED_VERIFIED` | Snapshot qua SQLite backup API, `PRAGMA integrity_check`, manifest SHA-256, bắt buộc `--backup-dir` ngoài repo. |
| `DB-03` | P0 | `AUTOMATED_VERIFIED` | Guard đích từ chối alias/DB thật/DB có dữ liệu ngoài bootstrap khi không hợp lệ. |
| `DB-04` | P1 | `AUTOMATED_VERIFIED` | `_validate_mysql_dry_run()` đối chiếu schema/độ dài/NULL/unique/collation, không ghi dữ liệu trong dry-run. |
| `DB-05` | P0 | `AUTOMATED_VERIFIED` | `MigrationAbortError` trong `transaction.atomic`, khôi phục FK checks trong `finally`, không dùng `break` trước commit. |
| `DB-06` | P0 | `AUTOMATED_VERIFIED` | Ánh xạ natural key cho `django_content_type`/`auth_permission`, giữ PK/FK/ciphertext, loại trừ `django_session`/`django_migrations`/`sqlite_sequence`. |
| `DB-07` | P0 | `AUTOMATED_VERIFIED` | Đối soát theo PK, FK, nội dung và `compute_club_fund_summary()` trước khi commit. |
| `DB-08` | P0 | `CI_VERIFIED` | Đạt thực tế trên MySQL 8.4 tại GitHub Actions CI run [`46145635488`](https://github.com/trandinhvu07022006-debug/clubevent/actions/runs/46145635488) (`7e7c512`, `RealMySqlMigrationIntegrationTests` pass trong 706 tests OK). |

### Sprint 2 — Backup / Restore & Nhập liệu (`G2`)
| Mã | Ưu tiên | Trạng thái | Bằng chứng & Ghi chú |
|---|---|---|---|
| `BK-01` | P0 | `AUTOMATED_VERIFIED` | `deployment/mysql_backup.py` (`33f0082`) kiểm tra `key_fingerprints`, target sạch, chống symlink/overlap trước SQL import. |
| `BK-02` | P0 | `AUTOMATED_VERIFIED` | `deployment/test_backup_restore.py` (`17 tests — OK`, skip 1 test symlink do Windows OS) xác minh backup không ghi đè bản cũ và manifest cuối cùng. |
| `BK-03` | P0 | `AUTOMATED_VERIFIED` | Kiểm thử fail giữa DB và archive volume không kích hoạt dịch vụ đích. |
| `BK-04` | P0 | `BLOCKED_ENV` | Đã verify unit mock; diễn tập live Docker + MySQL 8.4 container bị chặn cục bộ do máy dev chưa cài Docker Desktop. |
| `DB-09` | P1 | `AUTOMATED_VERIFIED` | Diễn tập migration/rehearsal idempotent đã kiểm chứng trong `core/test_importers_and_migration.py` và `core/test_unified_business_rehearsal.py`; bản chạy MySQL đầy đủ phụ thuộc `DB-08`/`BK-04`. |
| `IMP-01` | P1 | `AUTOMATED_VERIFIED` | `organization/importers.py` đạt coverage **93%**, idempotent và dry-run an toàn (`core/test_importers_and_migration.py`). |
| `IMP-02` | P0 | `AUTOMATED_VERIFIED` | Kiểm tra thẩm quyền import bổ nhiệm qua `PermissionEngine` và test từ chối leo quyền/thu hồi/khác Ban. |
| `IMP-03` | P1 | `AUTOMATED_VERIFIED` | `organization/staging_seeder.py` đạt coverage **94%** và chặn chạy ngoài vùng cho phép. |

### Sprint 3 — KMG AI (`G3`)
| Mã | Ưu tiên | Trạng thái | Bằng chứng & Ghi chú |
|---|---|---|---|
| `AI-01` | P0 | `AUTOMATED_VERIFIED` | `can_view_club_finance` + `PermissionEngine` (`67cf549`), test cho Cố vấn/BCN/Admin/TV thường/thu hồi/khóa tại `aiassist/test_business_queries.py`. |
| `AI-02` | P0 | `AUTOMATED_VERIFIED` | Tái sử dụng `TransactionStatus.CONFIRMED` & `compute_club_fund_summary()`, khớp số liệu với bút toán `CREDIT`/`DEBIT`. |
| `AI-03` | P0 | `AUTOMATED_VERIFIED` | `EvaluationStatus.CONFIRMED`, lọc theo `member=self`, URL `evaluations:hub`. |
| `AI-04` | P0 | `AUTOMATED_VERIFIED` | Phân tách `dept.task.view_all` theo từng Ban và quyền giám sát CLB; test cross-department & revoked. |
| `AI-05` | P0 | `AUTOMATED_VERIFIED` | Khôi phục các route hợp lệ `organization:governance_center`, `organization:advisor_overview`, `organization:workspace_home`. |
| `AI-06` | P1 | `AUTOMATED_VERIFIED` | Hợp nhất truy vấn `organization.MembershipApplication` và `recruitment.Application`, lịch tập & đào tạo theo nguồn chính thức. |
| `AI-07` | P0 | `AUTOMATED_VERIFIED` | Test JSON `chat_api` và SSE `chat_stream_api` đầy đủ nhánh happy/deny/empty (`aiassist/test_business_queries.py`, `test_ai_consolidation.py`). |
| `AI-08` | P0 | `AUTOMATED_VERIFIED` | Hồi quy Egress Policy: chặn `CONFIDENTIAL`/`INTERNAL` đi Cloud LLM, giữ nguyên ranh giới fallback. |
| `AI-09` | P0 | `AUTOMATED_VERIFIED` | Export canary `CONFIDENTIAL` và bảo vệ nhật ký/lịch sử hội thoại (`aiassist/test_ai_consolidation.py`). |
| `AI-10` | P1 | `AWAITING_HUMAN_APPROVAL` | Đã kiểm toán kỹ thuật **46/46** mục pending (`public`, 0 PII) và xuất danh mục kiểm duyệt từng mục tại `docs/audit/17_AI_46_KNOWLEDGE_REVIEW_QUEUE.md`; chờ BCN & Chuyên môn duyệt nội dung. |
| `AI-11` | P1 | `AUTOMATED_VERIFIED` | Gia sư nhạc, người bạn đồng hành, tiếng Việt có dấu/không dấu/viết tắt/đa ý, consent opt-in/tắt/xóa hồ sơ (`aiassist/test_kmg_companion.py`, `test_ai_consolidation.py`). |
| `AI-12` | P1 | `AUTOMATED_VERIFIED` | `evaluate_ai --with-migrate`: `EVAL ĐẠT` (100% dev/holdout/blind/RAG/PII/Music-Companion; chạy offline/mock, chưa benchmark Ollama cục bộ). |

### Sprint 4 — Chất lượng & CI (`G4`)
| Mã | Ưu tiên | Trạng thái | Bằng chứng & Ghi chú |
|---|---|---|---|
| `QA-01` | P0 | `AUTOMATED_VERIFIED` | Toàn bộ coverage **79%** (>= 78%); `business_queries.py` **99%**, `importers.py` **93%**, `sqlite_to_mysql.py` **85%**. |
| `QA-02` | P0 | `CI_VERIFIED` | Run [`46145635488`](https://github.com/trandinhvu07022006-debug/clubevent/actions/runs/46145635488) (`7e7c512`): `test-sqlite` OK (706, skipped=2), `test-mysql-redis` OK (706 + 17 deploy + 79% coverage + EVAL ĐẠT), `docker-build-check` OK. Cần xác nhận thêm job `playwright-ui-audit` mới thêm ở commit tiếp theo. |
| `QA-03` | P0 | `AUTOMATED_VERIFIED` | Hồi quy đặt vé đồng thời, giới hạn 4 vé, waitlist, QR check-in, `[LOAD-50-BOOK] ok=30/30` & `[PILOT-BOOK-100] ok=60, sold=60/60`. |
| `QA-04` | P0 | `AUTOMATED_VERIFIED` | Maker-checker, Cố vấn chỉ đọc, scope Ban/tài nguyên, khóa/thu hồi quyền và bảo vệ tệp (`core.test_uat_e2e`, `finance`, `organization`). |
| `QA-05` | P1 | `AUTOMATED_VERIFIED` | `manage.py check --deploy` (prod MySQL + HTTPS mô phỏng) đạt **0 issues**; kiểm tra static & error pages (`404` không traceback). |
| `QA-06` | P1 | `AUTOMATED_VERIFIED` | Sửa N+1 tại `PermissionEngine.summarize_actor_context()` và `workspace_home`; xác nhận query budget (`dashboard <= 30`, `workspace_home <= 45`) cùng load test cục bộ. |

### Sprint 5 — Hợp nhất Nghiệp vụ (`G5`)
| Mã | Ưu tiên | Trạng thái | Bằng chứng & Ghi chú |
|---|---|---|---|
| `BUS-02` | P1 | `APPROVED_DESIGN` | **Chủ dự án đã phê duyệt `D-01` (2026-11-28):** chọn `organization.Department`, `operations.ClubTask` và `organization.MembershipApplication` là nguồn dữ liệu chính thức tại `docs/UNIFIED_BUSINESS_SYSTEM_PLAN.md` (giữ nguyên bảng/route cũ). |
| `BUS-03` | P1 | `AUTOMATED_VERIFIED` | Tạo service & lệnh diễn tập `organization/business_consolidation.py` + `core/test_unified_business_rehearsal.py` (dry-run/execute/idempotent, giữ nguyên bảng cũ). |
| `BUS-04` | P1 | `AUTOMATED_VERIFIED` | Cầu nối tương thích ngược route/view công việc, Ban và ứng tuyển (`fa91ea0`), đã test qua `pages/test_sprint_e_ui.py`. |
| `BUS-05` | P1 | `AWAITING_HUMAN_APPROVAL` | Ma trận Vai trò → Nhu cầu → Chức năng → Quyền → Nguồn dữ liệu đã lập tại `docs/PRODUCT_ARCHITECTURE.md`; chờ Chủ dự án/đại diện CLB rà soát cuối. |
| `BUS-06` | P1 | `AUTOMATED_VERIFIED` | Phân định `Tổng quan` và `Không gian CLB` theo vai trò với lối tắt và tương thích route (`fa91ea0`). |
| `UAT-01` | P0 | `PENDING_CI_RUN` | **Chủ dự án đã phê duyệt `D-03` (2026-11-28):** bổ sung job `playwright-ui-audit` vào `.github/workflows/ci.yml` + `deployment/playwright_ui_audit.py` chạy staging SQLite cô lập và upload ảnh chụp/report artifact. |

### Sprint 6 — Frontend & Thiết kế (`G6`)
| Mã | Ưu tiên | Trạng thái | Bằng chứng & Ghi chú |
|---|---|---|---|
| `UI-01` | P1 | `AWAITING_HUMAN_APPROVAL` | Phong cách thẩm mỹ gốc giữ nguyên; chờ Chủ dự án duyệt trực quan (`D-02`). |
| `UI-02` | P1 | `AUTOMATED_VERIFIED` | Sidebar 6 nhóm nghiệp vụ + Trợ lý AI, bỏ mục trùng lặp (`fa91ea0`, `pages/test_sprint_e_ui.py`). |
| `UI-03` | P1 | `AUTOMATED_VERIFIED` | Ưu tiên việc cần xử lý, lịch và thông báo quan trọng trên `dashboard.html`/`workspace_home.html`. |
| `UI-04` | P1 | `AWAITING_HUMAN_APPROVAL` | Mở rộng `{% kmg_icon %}` nhất quán; chờ Chủ dự án duyệt gallery KMG Soft Icons 2 theme (`D-02`). |
| `UI-05` | P1 | `AUTOMATED_VERIFIED` | Chuẩn hóa tokens & bổ sung dark-mode overrides `.text-bg-light`/`.alert-light`/`.table-light` trong `static/css/tokens.css`. |
| `UI-06` | P1 | `AUTOMATED_VERIFIED` | Gỡ nốt `INV-04`, `CM-03`, `Chỉ thị 3.4` khỏi template UI; `pages/test_sprint_e_ui.py` kiểm tra sạch thuật ngữ kỹ thuật. |
| `UI-07` | P1 | `AUTOMATED_VERIFIED` | Kiểm thử form/luồng nghiệp vụ allow/deny/CSRF/maker-checker trong toàn suite 706 tests. |
| `UI-08` | P1 | `AUTOMATED_VERIFIED` | Đồng bộ chat UI & widget, link quyền hợp lệ, hiển thị rõ nguồn, hồ sơ học nhạc. |
| `UI-09` | P1 | `AUTOMATED_VERIFIED` *(cấp DOM/CSS)* | Đã rà soát thuộc tính a11y (`aria-label`, `data-bs-theme`, landmark, `viewport` meta) qua `core/test_uat_e2e.py`; chưa quét visual trình duyệt thật tại 7 viewport. |

### Sprint 7 — Trình duyệt & UAT (`G7`)
| Mã | Ưu tiên | Trạng thái | Bằng chứng & Ghi chú |
|---|---|---|---|
| `UAT-02` | P0 | `AUTOMATED_VERIFIED` | `core/test_uat_e2e.py` phủ các kịch bản `UT-01`..`UT-14` ở tầng Django TestClient & query budget. |
| `UAT-03` | P1 | `PENDING_CI_RUN` | Thực thi qua job `playwright-ui-audit` trên 7 viewport (`320–1920px`) & 2 theme (`light`/`dark`), upload screenshot artifact để Chủ dự án rà soát. |
| `UAT-04` | P1 | `BLOCKED_ENV` | Chờ môi trường trình duyệt để đo LCP/CLS/INP thực tế (trình duyệt lab/field). |
| `UAT-05` | P0 | `AWAITING_HUMAN_APPROVAL` | Bắt buộc Chủ dự án và đại diện các vai trò CLB nghiệm thu thực tế trên staging; không coi test tự động là UAT thật. |

### Sprint 8 — Release & Bàn giao (`G8`)
| Mã | Ưu tiên | Trạng thái | Bằng chứng & Ghi chú |
|---|---|---|---|
| `REL-01` | P0 | `CI_VERIFIED` | Đã qua `check --deploy` và `docker-build-check` + `test-mysql-redis` tại run `46145635488` (`7e7c512`). |
| `REL-02` | P0 | `AWAITING_HUMAN_APPROVAL` | Tài liệu runbook/backup đã có (`docs/deployment/DEPLOYMENT_AND_BACKUP.md`); mục tiêu `RPO<=24h` / `RTO<=4h` và diễn tập live cần Chủ dự án xác nhận (`D-04`). |
| `REL-03` | P0 | `PENDING_CI_RUN` | Chờ CI xanh trên commit push mới và quyết định tạo PR/rà soát từ Chủ dự án (đã bỏ qua bước Codex CLI theo yêu cầu người dùng). |
| `REL-04` | P0 | `AWAITING_HUMAN_APPROVAL` | Cổng Go/No-Go chuyển dữ liệu & phát hành thuộc toàn quyền Chủ dự án. |
| `REL-05` | P1 | `AUTOMATED_VERIFIED` | Đã đồng bộ `docs/AI_DEVELOPMENT_STATE.md`, `docs/audit/14..16` theo đúng nhánh, kết quả test thực tế và danh mục mở. |

---

## 4. Cổng nghiệm thu (`G0`–`G8`) & Quyết định mở (`D-01`–`D-04`)

| Cổng / Quyết định | Trạng thái hiện tại | Hành động tiếp theo cần thiết |
|---|---|---|
| `G0`–`G3` (cấp mã nguồn & SQLite/MySQL/AI) | `CI_VERIFIED` *(riêng `BK-04` chờ Docker staging, `AI-10` chờ BCN/CM duyệt 46 mục)* | `DB-08` đã xanh tại CI `46145635488`; BCN/CM duyệt `docs/audit/17_AI_46_KNOWLEDGE_REVIEW_QUEUE.md` |
| `G4` (CI & Chất lượng) | `CI_VERIFIED` *(cần xanh thêm job `playwright-ui-audit` mới)* | Xác nhận CI mới xanh đầy đủ cả 4 job (`test-sqlite`, `test-mysql-redis`, `docker-build-check`, `playwright-ui-audit`) |
| `G5` / `D-01` (Canonical model) | `APPROVED_DESIGN` | Chủ dự án đã duyệt `D-01` (`2026-11-28`); rà soát cuối `BUS-05` cùng đại diện CLB nếu cần |
| `G6` / `D-02` (Icon & Điều hướng) | `AWAITING_HUMAN_APPROVAL` | Chủ dự án duyệt gallery KMG Soft Icons (`UI-04`) từ screenshot artifact `playwright-ui-audit-report` |
| `G7` / `D-03` (Browser & UAT thật) | `PENDING_CI_RUN` / `AWAITING_HUMAN_APPROVAL` | `D-03` đã duyệt cho GitHub Actions Playwright CI; sau khi có ảnh artifact, tổ chức `UAT-05` với người dùng thật |
| `G8` / `D-04` (Go/No-Go Production) | `AWAITING_HUMAN_APPROVAL` | Chủ dự án chốt `RPO/RTO`, cửa sổ bảo trì, cutover và ký `REL-04` |
