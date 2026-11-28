# Kế hoạch Hợp nhất Hệ thống Nghiệp vụ (Unified Business System — Consolidation 4.0)

> **Quyết định `D-01` (`BUS-02`):** **ĐÃ ĐƯỢC CHỦ DỰ ÁN PHÊ DUYỆT (2026-11-28)** — Chốt `organization.Department`, `operations.ClubTask` và `organization.MembershipApplication` làm nguồn dữ liệu chính thức (Canonical Source), đồng thời **giữ nguyên bảng/model cũ và tương thích route cũ** trong suốt giai đoạn chuyển tiếp.

**Nguyên tắc an toàn:** Không xóa model hoặc bảng cũ; không tự ý migrate cơ sở dữ liệu thật trong giai đoạn lập kế hoạch & diễn tập. Mọi bước chuyển đổi phải idempotent, có đối soát và có phương án rollback.

---

## 1. Kiểm kê & Xác định Nguồn dữ liệu Chính thức (Canonical Source)

| Cặp mô hình song song | Nguồn chính thức (Canonical) | Nguồn cũ (Legacy) | Lý do lựa chọn |
|---|---|---|---|
| `organizing.Department` vs `organization.Department` | **`organization.Department`** | `organizing.Department` | Có `code` duy nhất, `is_active`, `is_demo`, `custom_categories`, gắn `DepartmentMembership`, `Appointment`, `PermissionEngine` (`ScopeType.DEPARTMENT`), `ClubTask`, `MemberEvaluation`, `FinancialTransaction`. |
| `organizing.Task` vs `operations.ClubTask` | **`operations.ClubTask`** | `organizing.Task` | Hỗ trợ đa người nhận (`TaskAssignee`), nộp bài vào `private_vault` có kiểm tra MIME/SHA-256 (`TaskSubmission`), gia hạn (`TaskExtensionRequest`), duyệt hai chiều (`TaskReview`), phân loại theo Ban & `reassignment_needed`. |
| `recruitment.Application` vs `organization.MembershipApplication` | **`organization.MembershipApplication`** | `recruitment.Application` | Gắn trực tiếp `organization.Department` (nguyện vọng 1 & 2), hỗ trợ quy trình 2 bước `SUBMITTED -> DEPT_SCREENED -> APPROVED/REJECTED` liên kết `ClubMembership` và `MemberLifecycleEvent` bất biến. |

---

## 2. Ánh xạ Trường dữ liệu, ID & Khóa ngoại

### 2.1 `organizing.Department` → `organization.Department`
- **Khóa đối chiếu tự nhiên (Natural Key):** `slug` (chuẩn hóa lowercase) hoặc `code` sinh từ `slug.upper().replace("-", "_")[:32]`.
- **Ánh xạ trường:**
  - `organizing.Department.name` → `organization.Department.name`
  - `organizing.Department.slug` → `organization.Department.slug`
  - `organizing.Department.description` → `organization.Department.short_description` (cắt 255) & `description`
  - `organizing.Department.icon` → `organization.Department.icon`
  - `organizing.Department.order` → `organization.Department.display_order`
  - `organizing.Department.lead` → Tạo `Appointment(position=DEPT_HEAD, scope_type=DEPARTMENT, department=target_dept)` nếu chưa có Trưởng ban đương nhiệm (tôn trọng `singleton_active_key`).
  - `organizing.Department.members` (M2M) → Tạo `DepartmentMembership(user=u, department=target_dept, status=ACTIVE)` nếu chưa tồn tại.
- **Bảng ánh xạ ID trung gian:** Lưu `legacy_organizing_dept_id -> canonical_org_dept_id` trong JSON/log đối soát để chuyển FK của `Task`.

### 2.2 `organizing.Task` → `operations.ClubTask`
- **Khóa chống trùng (Idempotency Key):** `(legacy_source="organizing.Task", legacy_id=task.id)` lưu trong `category_tag` hoặc bảng ánh xạ/metadata đối soát; phát hiện trùng theo `(title, department_id, created_at)` nếu chưa có bảng map.
- **Ánh xạ trường:**
  - `title` → `title`
  - `description` (+ `note` nếu có) → `description`
  - `event` → `event` (cùng FK tới `events.Event`)
  - `department` → ánh xạ qua bảng ID sang `organization.Department` (nếu `organizing.Task.department` là `NULL`, gán về Ban mặc định `CHUNG` hoặc `BAN_CHU_NHIEM` được đánh dấu `is_active=True`).
  - `priority`: `LOW -> LOW`, `NORMAL -> MEDIUM`, `HIGH -> HIGH`, `URGENT -> URGENT`.
  - `status`: `TODO -> ASSIGNED`, `DOING -> IN_PROGRESS`, `DONE -> APPROVED` (kèm `completed_at=done_at`).
  - `deadline` → `deadline` (nếu `NULL`, mặc định `created_at + 7 ngày` vì `ClubTask.deadline` NOT NULL).
  - `assignee` → tạo `TaskAssignee(task=club_task, user=assignee, role=LEAD)` nếu `assignee` khác `None`.
  - `created_by` → `created_by`.

### 2.3 `recruitment.Application` → `organization.MembershipApplication`
- **Khóa chống trùng:** `(user_id, created_at.date(), primary_department_id)` hoặc đối chiếu `user` đã có `MembershipApplication` đang mở / đã `APPROVED`.
- **Ánh xạ trường:**
  - `user` → `user`
  - `department` → ánh xạ sang `organization.Department` → `primary_department`
  - `strengths` + `level` → `declared_skills_text` (ví dụ `f"{strengths} ({get_level_display()})"[:255]`)
  - `motivation` → `motivation`
  - `portfolio_url` → `portfolio_url`
  - `status`:
    - `PENDING` → `SUBMITTED`
    - `INTERVIEW` → `DEPT_SCREENED` (bảo toàn `interview_at` và `review_note` vào `screening_note`)
    - `APPROVED` → `APPROVED`
    - `REJECTED` → `REJECTED`
  - `reviewer` / `reviewed_at` / `review_note` → `reviewed_by` / `reviewed_at` / `decision_note`.

---

## 3. Quy tắc Phát hiện Trùng, Đối soát & Idempotency

1. **Phát hiện trùng:**
   - Department: trùng `slug` hoặc `code` không phân biệt hoa thường.
   - Task: trùng bản ghi đã ánh xạ `legacy_id` hoặc trùng `(department_id, title, created_at)` trong vòng ±1 giây.
   - Application: trùng `(user_id, primary_department_id, status)` khi `created_at` chênh lệch < 60 giây hoặc cùng `user` đã là `ClubMembership(ACTIVE)`.
2. **Đối soát số lượng & nội dung:**
   - Sau khi chạy script chuyển đổi ở chế độ `--execute`, kiểm tra:
     - `count(legacy) == count(mapped) + count(skipped_duplicate)`
     - Mọi `ClubTask` chuyển từ `DONE` đều có `completed_at` và trạng thái `APPROVED`.
     - Không phát sinh FK mồ côi (`_check_target_orphans`).
3. **Kiểm thử Idempotency:**
   - Chạy chuyển đổi lần 1 (`created = N, skipped = 0`), chạy lại lần 2 trên cùng DB (`created = 0, skipped = N`), tổng số bản ghi đích không đổi.

---

## 4. Sao lưu, Khôi phục, Rollback & Chuyển đổi Điểm ghi (Cutover Plan)

1. **Sao lưu trước chuyển đổi:**
   - `mysqldump --single-transaction --routines --triggers` (MySQL) hoặc `backup_sqlite_source()` (SQLite) kèm manifest SHA-256.
2. **Rollback:**
   - Nếu phát hiện sai lệch sau dry-run/execute: phục hồi snapshot trước chuyển đổi; giữ nguyên 100% bảng `organizing_*` và `recruitment_*` ở trạng thái Read-Only trong suốt giai đoạn chuyển tiếp.
3. **Tương thích đường dẫn & dữ liệu cũ (Backward Compatibility):**
   - Giữ các URL hiện có (`/congviec/viec-cua-toi/`, `/congviec/ban/`, `/tuyen-thanh-vien/`) hoạt động bình thường; giai đoạn 1 chuyển view đọc/ghi sang Canonical Service hoặc tạo adapter đồng bộ 2 chiều trong transaction; giai đoạn 2 redirect vĩnh viễn khi UAT xác nhận ổn định.
4. **Thứ tự Cutover Điểm ghi:**
   - Bước 1: Đồng bộ `Department` (`organizing` -> `organization`).
   - Bước 2: Chạy backfill `Task` -> `ClubTask` và `Application` -> `MembershipApplication` ở chế độ `--dry-run` → kiểm tra báo cáo đối soát.
   - Bước 3: Chuyển điểm ghi UI/API mới sang `operations.services` và `organization.services`; giữ view cũ đọc dữ liệu hợp nhất.
   - Bước 4: Đóng băng ghi vào bảng legacy (`organizing.Task`, `recruitment.Application`), chỉ giữ archive chỉ đọc trước khi cân nhắc deprecate ở phiên bản sau.
