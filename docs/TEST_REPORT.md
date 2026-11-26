# BÁO CÁO KIỂM THỬ & ĐO TẢI — KMG PHASE 7 (MYSQL 8.4 PRODUCTION READINESS)

**Nhánh Git:** `feature/mysql-production-readiness`  
**Cơ sở dữ liệu kiểm thử:** MySQL `8.4.13` (`InnoDB`, `utf8mb4`, `utf8mb4_0900_ai_ci`, `STRICT_TRANS_TABLES`)  
**Ngày kiểm chứng:** 2026-11-26

---

## 1. Tổng hợp kết quả kiểm thử tự động

| Hạng mục | Môi trường | Lệnh thực thi | Kết quả thực tế | Ghi chú / Skip |
|---|---|---|---|---|
| **Toàn bộ Test Suite Django** | **MySQL 8.4** (`test_kmg_ci`) | `manage.py test --settings=config.settings_test --noinput` | **670 tests OK trong `240.097s` (`skipped=2`)** | 2 test skip thuộc `RedisRateLimitTests` do máy dev Windows chưa cài Redis Server |
| **Deployment Tests** | Host Windows | `python -m unittest deployment/test_backup_restore.py deployment/test_scheduler.py -v` | **17 tests OK trong `0.241s` (`skipped=1`)** | 1 test symlink bỏ qua trên Windows không bật Developer Symlink |
| **Deploy Security Check** | Production sim (`KMG_ENV=prod`, `DB_ENGINE=mysql`, `DEBUG=False`, `USE_HTTPS=True`) | `manage.py check --deploy --settings=config.settings` | **0 issues (0 silenced)** | Bắt buộc MySQL, từ chối SQLite fail-closed |
| **AI Quality Gate** | Cô lập (`settings_test`) | `manage.py evaluate_ai --with-migrate --settings=config.settings_test` | **EVAL ĐẠT** | `dev` `38/38`, `holdout` `22/22`, `blind` `50/50`, RAG `13/13` & `7/8`, Che PII `6/6` |

---

## 2. Kiểm thử chuyên biệt Phase 7 (`core/test_phase7_mysql_readiness.py` — Đạt trên MySQL 8.4)
- `test_production_config_rejects_sqlite_fail_closed`: xác nhận `KMG_ENV=prod` + `DEBUG=False` + `DB_ENGINE=sqlite` bị chặn khởi động bằng `ImproperlyConfigured`.
- `test_seed_guard_blocks_production_and_disabled_demo_seed`: xác nhận `seed_demo`, `seed_kmg`, `seed_staging` bị chặn khi `KMG_ENV=prod` hoặc `ALLOW_DEMO_SEED=False`.
- `test_csv_import_dry_run_commit_idempotent_and_row_errors`: xác nhận import `.csv` kiểm tra lỗi từng dòng, chặn leo quyền `ADMIN`, hỗ trợ `--dry-run` rollback hoàn toàn và chạy lại idempotent.
- `test_xlsx_import_skills_and_requires_approver_for_appointments`: xác nhận import `.xlsx` kỹ năng (`GUITAR_ACOUSTIC`), và từ chối bổ nhiệm chức vụ nếu thiếu `--approve-by`.
- `test_staging_seeder_deterministic_utf8_emoji_and_n1_bounds`: xác nhận `seed_staging` tái lập kết quả theo `--seed`, lưu chuẩn `utf8mb4` + emoji và trang `/sukien/` chạy trong `<= 6` truy vấn (`4` queries thực tế, không N+1).
- `test_sqlite_inventory_backup_and_dirty_unique_detection`: xác nhận sao lưu SQLite SHA-256, phát hiện chuỗi rỗng `""` trên cột `UNIQUE NULL` và kiểm tra tổng quỹ tài chính.
- `test_aes256_gcm_chat_ciphertext_binary_integrity`: xác nhận giải mã AES-256-GCM toàn vẹn dữ liệu nhị phân tiếng Việt + emoji.
- `test_sepay_webhook_replay_is_idempotent`: xác nhận webhook SePay gọi lặp lại trả `200`, chỉ xác nhận vé 1 lần và không nhân đôi `TicketType.sold`.
- `test_finance_duplicate_tx_code_blocked_and_term_revocation_bumps_authz`: xác nhận `tx_code` duy nhất ở tầng MySQL và miễn nhiệm cuối nhiệm kỳ tăng ngay `User.authz_version` (`INV-06`).

---

## 3. Diễn tập thực tế trên MySQL 8.4 cục bộ (tách biệt hoàn toàn khỏi DB `clubevent`)

1. **Chuyển đổi `db.sqlite3` -> MySQL (`kmg_dev`):**
   - Đạt **`ok=True`**, chuyển **809 bản ghi**, `0` khóa ngoại mồ côi (`fk_orphans={}`), tự động chuẩn hoá `"" -> NULL` và bù default Django model cho bảng ở migration cũ hơn (`events_event.visibility`, `aiassist_clubknowledge.visibility`).
2. **Sao lưu & Khôi phục MySQL 8.4 (`kmg_dev` -> `kmg_restore_tmp`):**
   - Thời gian sao lưu + nén + kiểm chứng khôi phục: **`8.51s`**.
   - Số bảng nguồn `110` = số bảng sau khôi phục `110` (`database.sql` `295,314` bytes), kiểm chứng **chặn ghi đè DB không trống (`overwrite_blocked=True`)** và checksum SHA-256 hợp lệ.
3. **Sinh dữ liệu Staging quy mô đầy đủ (`kmg_staging`, `seed=2026`, `scale=full`):**
   - Hoàn tất trong **`9.04s`** trên MySQL 8.4: `120` thành viên, `500` khách, `200` đơn ứng tuyển, `40` sự kiện, `2.500` vé, `800` công việc, `3.000` điểm danh, `300` giao dịch tài chính, `150` tài liệu, `500` bài đăng, `2.000` bình luận, `20.000` tin nhắn mã hóa AES-256-GCM, `10.000` thông báo, `50.000` nhật ký (`AuditLog` + `AIInteractionLog`).

---

## 4. Kết quả đo tải tăng dần trên `kmg_staging` (MySQL 8.4, `DEBUG=False`, WhiteNoise manifest)

Kịch bản hỗn hợp (đọc `/sukien/`, đọc chi tiết sự kiện, và đặt vé đồng thời tranh chấp quota `30` vé qua `SELECT ... FOR UPDATE`):

| Mức đồng thời (`C`) | Tổng tác vụ | Thời gian (s) | Throughput (ops/s) | `p95` (ms) | `p99` (ms) | Tỷ lệ lỗi | Deadlock | CPU time (s) | Ghi chú RAM RSS |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| **10** | 60 | 2.547 | 23.56 | 721.45 | 725.74 | 0.0% | 0 | 2.781 | Chưa đo tự động (thiếu `psutil`, ctypes trả `0.0`) |
| **25** | 150 | 5.680 | 26.41 | 1501.67 | 1714.19 | 0.0% | 0 | 6.859 | Chưa đo tự động |
| **50** | 300 | 12.291 | 24.41 | 3183.57 | 3447.31 | 0.0% | 0 | 14.078 | Chưa đo tự động |

- **Kiểm chứng chống bán lố vé (`oversell_check`):** `sold=30 / quota=30` (`0` oversell, `0` deadlock dưới cả 3 mức tải đồng thời).
- **Giới hạn phép đo:** Thực hiện qua Django `Client` đa luồng trên 1 tiến trình Python tại máy dev Windows (chưa có Redis cache và multi-worker Gunicorn/Nginx Linux). Không suy diễn thông số vượt quá quy mô đã đo.
