# Báo cáo 14 — KMG Product Refinement 4.0 (Product Consolidation)

**Ngày thực hiện:** 2026-11-28  
**Nhánh làm việc:** `feature/mysql-production-readiness` (không merge `main`, không deploy production)  
**Baseline đối chiếu:** `52f45dbf746fe88718d20ffdec108086e7825919`

---

## A. Sửa lỗi và Quality Gate

### 1. Sửa `aiassist/business_queries.py`
- **`query_finance_summary`**: Thay quyền không tồn tại `finance.transaction.view` bằng `finance.services.can_view_club_finance(user)` (đối chiếu `club.finance.view_summary`, `club.finance.create_transaction`, `club.finance.approve_transaction` và logic `finance_hub`); đồng thời sửa `TransactionStatus.APPROVED` (không tồn tại) thành `TransactionStatus.CONFIRMED`.
- **`query_department_ops`**: Thay `club.task.assign` (không tồn tại) bằng kiểm tra `dept.task.assign` theo **phạm vi từng Ban thực tế** (`Department.objects.filter(is_active=True)`), chỉ trả số liệu thuộc các Ban được ủy quyền và không mở rộng thành xem toàn CLB (chỉ `club.event.approve` hoặc `club.dept.supervise_ops` mới xem toàn CLB).
- **`query_my_evaluations`**: Sửa `EvaluationStatus.FINALIZED, EvaluationStatus.ACKNOWLEDGED` (không tồn tại) thành `EvaluationStatus.CONFIRMED`, sửa reverse URL `evaluations:my_evaluations` thành `evaluations:hub` (chỉ gắn link khi user có quyền `club.event.view_internal`).
- **`query_club_analytics`**: Bổ sung quyền `club.overview.supervise` cho Cố vấn, sửa reverse URL `organization:hub` thành định tuyến theo quyền thực tế (`organization:governance_center` cho BCN, `organization:advisor_overview` cho Cố vấn, `organization:workspace_home` cho trường hợp khác).
- **Bảo vệ tài khoản khóa & chưa đăng nhập**: Bổ sung `_check_active_user(user)` cho `query_my_practice`, `query_my_recruitment_status`, `query_my_training`, `query_my_evaluations`.

### 2. Kiểm thử & Coverage (`--fail-under=78`)
- Thêm `aiassist/test_business_queries.py` (7 test cases): phủ nhánh trả lời thành công, từ chối, khác Ban, thu hồi quyền (`end_appointment`), tài khoản bị khóa và chưa đăng nhập cho toàn bộ 7 hàm trong `business_queries.py`.
- Thêm `core/test_importers_and_migration.py` (6 test cases): phủ `organization/importers.py` (CSV/XLSX, structure, members, skills, appointments, history, validate/update/skip) và `deployment/sqlite_to_mysql.py` (orphan detection, dry-run, mocked MySQL execute mode, backup & reconciliation).
- **Kết quả Coverage đạt được:**
  - **Toàn hệ thống:** **79%** (`18,282` stmts, `3,822` miss, `95` file đạt 100%) — **ĐẠT cổng `--fail-under=78`**.
  - `aiassist/business_queries.py`: **20% → 99%** (`138` stmts, `2` miss).
  - `organization/importers.py`: **58% → 93%** (`340` stmts, `23` miss).
  - `deployment/sqlite_to_mysql.py`: **50% → 92%** (`248` stmts, `20` miss).
  - Các nghiệp vụ bảo mật trọng yếu: `registrations/services.py` **94%**, `finance/api_views.py` **90%**, `finance/views.py` **88%**, `social/crypto.py` **93%**, `social/models.py` **98%**, `organization/permissions.py` **85%**.

---

## B. Product Architecture
- Tạo `docs/PRODUCT_ARCHITECTURE.md`:
  - Kiểm kê toàn bộ chức năng và lập ma trận **Vai trò → Nhu cầu → Chức năng → Quyền hạn → Nguồn dữ liệu → Điểm truy cập** cho 7 vai trò (Khách/Ứng viên, Thành viên, TV BTC, Trưởng/Phó ban, BCN, Cố vấn, Quản trị viên).
  - Tổ chức điều hướng theo **6 nhóm nghiệp vụ**: `Tổng quan`, `Hoạt động & Âm nhạc`, `Công việc`, `Tổ chức`, `Cộng đồng`, `Quản lý` + `Trợ lý AI` xuyên suốt + `Hồ sơ & Cài đặt` tập trung tại menu tài khoản.

---

## C. Unified Business System
- Tạo `docs/UNIFIED_BUSINESS_SYSTEM_PLAN.md`:
  - Xác định nguồn dữ liệu chính thức (Canonical): `organization.Department`, `operations.ClubTask`, `organization.MembershipApplication`.
  - Lập kế hoạch chuyển đổi đầy đủ: ánh xạ trường/ID/FK, quy tắc phát hiện bản ghi trùng, đối soát số lượng & nội dung, kiểm thử idempotency, sao lưu/khôi phục/rollback, tương thích URL cũ và lộ trình cutover điểm ghi dữ liệu.
  - **Tuân thủ an toàn:** Không xóa model/bảng cũ và không tự ý migrate DB thật.

---

## D. Frontend Refinement
- Cập nhật `templates/base.html`:
  - Tổ chức lại sidebar theo đúng **6 nhóm nghiệp vụ** + **Trợ lý AI** (`Trợ lý KMG`).
  - Loại bỏ mục `Hồ sơ cá nhân` trùng lặp khỏi sidebar (tập trung trong menu tài khoản ở footer sidebar).
  - Việt hóa nhãn điều hướng (`Xác nhận thanh toán`, `Trợ lý KMG`), giữ nguyên bảng màu, Be Vietnam Pro, Light/Dark mode và KMG Soft Icons 1.0.

---

## E. KMG AI & Kiểm duyệt 46 mục tri thức
- Kiểm toán 46 ứng viên trong `aiassist/datasets/v2/kmg_ai_knowledge_candidates.jsonl`:
  - Toàn bộ `46/46` mục có `audience: "public"`, `0` mục rỗng, `0` phát hiện PII (SĐT, email, MSSV).
  - Phân loại trạng thái chờ duyệt: `24` mục `pending_music_mentor_review` (Guitar, Vocal, Theory, Band, Stage, Equipment, Creative, Student Life) và `22` mục `pending_owner_review` (quy trình CLB công khai).
- Thêm `aiassist/test_ai_consolidation.py` (4 test cases): kiểm thử 3 nhóm năng lực (Gia sư âm nhạc, Bạn đồng hành sinh viên, Trợ lý vận hành CLB), tiếng Việt có dấu / không dấu / viết tắt / nhiều ý / tiếp nối, Egress Policy + `redact` PII, cơ chế đồng ý / tắt cá nhân hóa / xóa `MusicLearningProfile`, và kiểm định import 46 mục `ClubKnowledge`.
- Chạy `manage.py evaluate_ai --with-migrate --settings=config.settings_test`: **EVAL ĐẠT** (`dev` 38/38, `holdout` 22/22, `blind` 50/50, RAG `dev` 13/13, `holdout` 8/8, PII 6/6, Music/Companion 7/7).

---

## F. Trải nghiệm sản phẩm thật & Blocker môi trường
- **Đã thực hiện:** Kiểm thử toàn bộ test suite trên SQLite cách ly (`config.settings_test`), `manage.py check`, `makemigrations --check --dry-run`, `compileall`, và `evaluate_ai`.
- **Blocker môi trường tại máy dev Windows:**
  - Chưa cài `playwright` (`find_spec('playwright') == None`), Docker Desktop và Redis Server nên chưa chụp ảnh responsive `320px–1920px` (Light/Dark) trên trình duyệt thật tại local.
  - **Khuyến nghị:** Push nhánh `feature/mysql-production-readiness` lên GitHub để runner CI xác nhận `test-mysql-redis`, `docker-build-check`, và thực hiện UAT + Playwright trên môi trường kiểm thử riêng trước khi phê duyệt phát hành.

---

## G. Danh sách file đã tạo/sửa đổi
- Sửa: `aiassist/business_queries.py`, `templates/base.html`, `docs/AI_DEVELOPMENT_STATE.md`.
- Tạo mới: `aiassist/test_business_queries.py`, `aiassist/test_ai_consolidation.py`, `core/test_importers_and_migration.py`, `docs/PRODUCT_ARCHITECTURE.md`, `docs/UNIFIED_BUSINESS_SYSTEM_PLAN.md`, `docs/audit/14_KMG_PRODUCT_REFINEMENT_REPORT.md`.

## H. Quyết định cần Chủ dự án phê duyệt
1. Phê duyệt thiết kế điều hướng 6 nhóm nghiệp vụ trên `templates/base.html` & `docs/PRODUCT_ARCHITECTURE.md`.
2. Phê duyệt kích hoạt `46` mục tri thức `PUBLIC` trong AI Studio (`approve_kb`) sau khi rà soát nội dung chuyên môn.
3. Phê duyệt chạy Playwright E2E + UAT 7 vai trò và lộ trình cutover theo `docs/UNIFIED_BUSINESS_SYSTEM_PLAN.md` trước khi merge `main`.
