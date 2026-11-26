# DATA DICTIONARY — KMG PLATFORM (MYSQL 8.4 REAL SCHEMA)

**Tổng số Model tường minh đã kiểm kê:** `99` model (chuẩn hóa cho MySQL 8.4 `InnoDB`, `utf8mb4`, `utf8mb4_0900_ai_ci`, `STRICT_TRANS_TABLES`).

---

## 1. Kiểm duyệt Overlap & Nguồn dữ liệu Legacy vs Enterprise

| Nhóm đối tượng | Model Legacy | Model Enterprise / Hiện đại | Quan hệ & Trạng thái hiện hành | Hướng xử lý Phase 7 |
|---|---|---|---|---|
| **Cơ cấu Ban** | `organizing.Department` (`organizing_department`) | `organization.Department` (`organization_department`) | Không có FK trực tiếp giữa 2 bảng. Legacy giữ `organizing.Task`, `pages.ClubOfficer`, `recruitment.RecruitmentRound/Application`. Enterprise giữ `DepartmentMembership`, `Appointment`, `ClubTask`, `Finance`, `Programs`, `Social`, `Evaluations`. | **Không xóa ngay**; đồng bộ song song theo `slug`/`code` ở tầng nhập liệu & chuyển đổi dữ liệu; lên kế hoạch hợp nhất có migration chuyển FK ở Phase 8. |
| **Công việc** | `organizing.Task` (`organizing_task`) | `operations.ClubTask` + `operations.ClubTaskAssignee` | Tách biệt hoàn toàn: `Task` 1 người nhận / 3 trạng thái (`TODO/DOING/DONE`); `ClubTask` đa người nhận / 10 trạng thái + `TaskSubmission` + `TaskReview` bất biến. | Bảo toàn cả 2 bảng; mọi nhiệm vụ mới cấp CLB đi vào `operations.ClubTask`. |
| **Ứng tuyển** | `recruitment.Application` (`recruitment_application`) | `organization.MembershipApplication` (`organization_membershipapplication`) | `recruitment.Application` gắn với đợt tuyển (`RecruitmentRound`) và `organizing.Department`; `MembershipApplication` theo quy trình `WF01` gắn `organization.Department`. | Giữ cả 2 để không gãy dữ liệu đợt tuyển công khai; map bổ sung khi duyệt thành viên. |
| **Tài chính** | `organizing.Expense` (`organizing_expense`) | `finance.FinancialTransaction` (`finance_financialtransaction`) | Đã nối qua `FinancialTransaction.legacy_expense` (`OneToOneField`, cầu nối `CM-03`) và khóa chỉnh sửa/xóa khi `CONFIRMED`. | Duy trì bất biến sổ cái `CM-03`; kiểm tra cân bằng khi chuyển đổi. |
| **Cán bộ / Nhiệm kỳ** | `pages.ClubOfficer` (gồm migration `0002_seed_board_2026_2027`) | `organization.Appointment` + `Position` | `pages.ClubOfficer` hiển thị Trang chủ/Giới thiệu; `Appointment` điều khiển quyền backend thật với `singleton_active_key`. | Giữ `0002` không sửa lịch sử migration; đồng bộ dữ liệu thật qua `kmg_import_org` & quản trị web. |
| **SQLite / File cục bộ** | `db.sqlite3`, `test_db.sqlite3`, `.local-pilot/db.sqlite3`, `.env.mau-de-chay-nhanh`, `chay-thu.bat/.sh` | MySQL 8.4 (`kmg_dev`, `kmg_staging`, `kmg_prod`) | Còn tồn tại đường chạy SQLite thử nhanh ở local; production/staging cần fail-closed chỉ nhận MySQL 8.4. | Bắt buộc MySQL khi `DEBUG=False` hoặc `KMG_ENV in (staging, prod)` (trừ bước build `collectstatic` trong Docker); cô lập SQLite cho unit test nhẹ. |

---

## 2. Chi tiết Bảng & Trường theo từng App

### App `accounts`
- **Phân loại nguồn dữ liệu:** Dữ liệu danh tính & bảo mật (nhạy cảm — không dùng PII thật trên staging)

#### `accounts.AccountStatusHistory` -> Bảng `accounts_accountstatushistory`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `user_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `old_status` | `CharField` | NOT NULL | — | — |
| `new_status` | `CharField` | NOT NULL | — | — |
| `changed_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `reason` | `CharField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `accounts.AuditLog` -> Bảng `accounts_auditlog`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `user_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `action` | `CharField` | INDEX, NOT NULL | — | — |
| `target` | `CharField` | NOT NULL | — | — |
| `note` | `CharField` | NOT NULL | — | — |
| `ip_address` | `CharField` | NOT NULL | — | — |
| `metadata` | `JSONField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | INDEX, NOT NULL | — | — |

#### `accounts.EmailOTP` -> Bảng `accounts_emailotp`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `user_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `code_hash` | `CharField` | NOT NULL | — | — |
| `attempts` | `PositiveSmallIntegerField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | INDEX, NOT NULL | — | — |
| `used_at` | `DateTimeField` | NULL | — | — |

#### `accounts.EmailVerificationToken` -> Bảng `accounts_emailverificationtoken`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `user_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `email` | `CharField` | NOT NULL | — | — |
| `token_hash` | `CharField` | UNIQUE, NOT NULL | — | — |
| `expires_at` | `DateTimeField` | NOT NULL | — | — |
| `used_at` | `DateTimeField` | NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `accounts.OTPVerificationChallenge` -> Bảng `accounts_otpverificationchallenge`
- **Indexes:** `(user, channel, used_at)`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `user_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `channel` | `CharField` | INDEX, NOT NULL | — | — |
| `destination` | `CharField` | NOT NULL | — | — |
| `code_hash` | `CharField` | NOT NULL | — | — |
| `attempts` | `PositiveSmallIntegerField` | NOT NULL | — | — |
| `max_attempts` | `PositiveSmallIntegerField` | NOT NULL | — | — |
| `expires_at` | `DateTimeField` | NOT NULL | — | — |
| `used_at` | `DateTimeField` | NULL | — | — |
| `invalidated_at` | `DateTimeField` | NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `accounts.User` -> Bảng `accounts_user`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `password` | `CharField` | NOT NULL | — | — |
| `last_login` | `DateTimeField` | NULL | — | — |
| `is_superuser` | `BooleanField` | NOT NULL | — | — |
| `username` | `CharField` | UNIQUE, NOT NULL | — | — |
| `first_name` | `CharField` | NOT NULL | — | — |
| `last_name` | `CharField` | NOT NULL | — | — |
| `email` | `CharField` | NOT NULL | — | — |
| `is_staff` | `BooleanField` | NOT NULL | — | — |
| `is_active` | `BooleanField` | NOT NULL | — | — |
| `date_joined` | `DateTimeField` | NOT NULL | — | — |
| `affiliation` | `CharField` | NOT NULL | — | — |
| `mssv` | `CharField` | UNIQUE, NULL | — | — |
| `school` | `CharField` | NOT NULL | — | — |
| `full_name` | `CharField` | NOT NULL | — | — |
| `display_name` | `CharField` | NOT NULL | — | — |
| `phone` | `CharField` | NOT NULL | — | — |
| `normalized_phone` | `CharField` | UNIQUE, NULL | — | — |
| `normalized_email` | `CharField` | UNIQUE, NULL | — | — |
| `email_canonical` | `CharField` | INDEX, NOT NULL | — | — |
| `role` | `CharField` | NOT NULL | — | — |
| `account_status` | `CharField` | INDEX, NOT NULL | — | — |
| `email_verified_at` | `DateTimeField` | NULL | — | — |
| `phone_verified_at` | `DateTimeField` | NULL | — | — |
| `authz_version` | `PositiveIntegerField` | NOT NULL | — | — |
| `avatar` | `FileField` | NULL | — | — |
| `is_locked` | `BooleanField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `accounts.UserProfile` -> Bảng `accounts_userprofile`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `user_id` | `OneToOneField` | UNIQUE, INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `stage_name` | `CharField` | NOT NULL | — | — |
| `bio` | `TextField` | NOT NULL | — | — |
| `faculty` | `CharField` | NOT NULL | — | — |
| `cohort` | `CharField` | NOT NULL | — | — |
| `date_of_birth` | `DateField` | NULL | — | — |
| `social_url` | `CharField` | NOT NULL | — | — |
| `privacy_show_phone` | `BooleanField` | NOT NULL | — | — |
| `privacy_show_email` | `BooleanField` | NOT NULL | — | — |
| `privacy_show_dob` | `BooleanField` | NOT NULL | — | — |
| `updated_at` | `DateTimeField` | NOT NULL | — | — |

#### `accounts.UserSession` -> Bảng `accounts_usersession`
- **Indexes:** `(user, revoked_at)`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `user_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `session_key` | `CharField` | INDEX, NOT NULL | — | — |
| `device_label` | `CharField` | NOT NULL | — | — |
| `ip_address` | `CharField` | NOT NULL | — | — |
| `user_agent` | `CharField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |
| `last_seen_at` | `DateTimeField` | NOT NULL | — | — |
| `revoked_at` | `DateTimeField` | NULL | — | — |
| `revoked_reason` | `CharField` | NOT NULL | — | — |

### App `admin`
- **Phân loại nguồn dữ liệu:** Django admin audit

#### `admin.LogEntry` -> Bảng `django_admin_log`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `AutoField` | PK, UNIQUE, NOT NULL | — | — |
| `action_time` | `DateTimeField` | NOT NULL | — | — |
| `user_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `content_type_id` | `ForeignKey` | INDEX, NULL | `django_content_type` | `SET_NULL` |
| `object_id` | `TextField` | NULL | — | — |
| `object_repr` | `CharField` | NOT NULL | — | — |
| `action_flag` | `PositiveSmallIntegerField` | NOT NULL | — | — |
| `change_message` | `TextField` | NOT NULL | — | — |

### App `aiassist`
- **Phân loại nguồn dữ liệu:** Kho tri thức RAG (PUBLIC/INTERNAL/CONFIDENTIAL), Prompt & Log che PII

#### `aiassist.AIInteractionLog` -> Bảng `aiassist_aiinteractionlog`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `question` | `CharField` | NOT NULL | — | — |
| `intent` | `CharField` | NOT NULL | — | — |
| `source` | `CharField` | NOT NULL | — | — |
| `answer_preview` | `TextField` | NOT NULL | — | — |
| `feedback` | `CharField` | NOT NULL | — | — |
| `feedback_note` | `CharField` | NOT NULL | — | — |
| `classification` | `CharField` | INDEX, NOT NULL | — | — |
| `latency_ms` | `PositiveIntegerField` | NULL | — | — |
| `model_name` | `CharField` | NOT NULL | — | — |
| `prompt_version` | `CharField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `aiassist.AIPromptProfile` -> Bảng `aiassist_aipromptprofile`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `task_key` | `CharField` | UNIQUE, NOT NULL | — | — |
| `brand_voice` | `TextField` | NOT NULL | — | — |
| `extra_instructions` | `TextField` | NOT NULL | — | — |
| `few_shot_examples` | `JSONField` | NOT NULL | — | — |
| `is_active` | `BooleanField` | NOT NULL | — | — |
| `updated_at` | `DateTimeField` | NOT NULL | — | — |

#### `aiassist.ClubKnowledge` -> Bảng `aiassist_clubknowledge`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `title` | `CharField` | NOT NULL | — | — |
| `category` | `CharField` | NOT NULL | — | — |
| `visibility` | `CharField` | INDEX, NOT NULL | — | — |
| `keywords` | `CharField` | NOT NULL | — | — |
| `content` | `TextField` | NOT NULL | — | — |
| `priority` | `PositiveSmallIntegerField` | NOT NULL | — | — |
| `is_active` | `BooleanField` | NOT NULL | — | — |
| `updated_at` | `DateTimeField` | NOT NULL | — | — |

### App `auth`
- **Phân loại nguồn dữ liệu:** Django auth chuẩn

#### `auth.Group` -> Bảng `auth_group`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `AutoField` | PK, UNIQUE, NOT NULL | — | — |
| `name` | `CharField` | UNIQUE, NOT NULL | — | — |

#### `auth.Permission` -> Bảng `auth_permission`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `AutoField` | PK, UNIQUE, NOT NULL | — | — |
| `name` | `CharField` | NOT NULL | — | — |
| `content_type_id` | `ForeignKey` | INDEX, NOT NULL | `django_content_type` | `CASCADE` |
| `codename` | `CharField` | NOT NULL | — | — |

### App `contenttypes`
- **Phân loại nguồn dữ liệu:** Django content types

#### `contenttypes.ContentType` -> Bảng `django_content_type`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `AutoField` | PK, UNIQUE, NOT NULL | — | — |
| `app_label` | `CharField` | NOT NULL | — | — |
| `model` | `CharField` | NOT NULL | — | — |

### App `evaluations`
- **Phân loại nguồn dữ liệu:** Đánh giá định kỳ & vinh danh

#### `evaluations.EvaluationCriterionScore` -> Bảng `evaluations_evaluationcriterionscore`
- **Constraints:** `uniq_eval_criterion`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `evaluation_id` | `ForeignKey` | INDEX, NOT NULL | `evaluations_memberevaluation` | `CASCADE` |
| `criterion` | `CharField` | NOT NULL | — | — |
| `rating_level` | `PositiveSmallIntegerField` | NOT NULL | — | — |
| `auto_evidence` | `CharField` | NOT NULL | — | — |
| `comment` | `CharField` | NOT NULL | — | — |

#### `evaluations.EvaluationCycle` -> Bảng `evaluations_evaluationcycle`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `code` | `CharField` | UNIQUE, NOT NULL | — | — |
| `name` | `CharField` | NOT NULL | — | — |
| `starts_on` | `DateField` | NOT NULL | — | — |
| `ends_on` | `DateField` | NOT NULL | — | — |
| `response_deadline` | `DateField` | NULL | — | — |
| `status` | `CharField` | NOT NULL | — | — |
| `created_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `PROTECT` |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `evaluations.EvaluationResponse` -> Bảng `evaluations_evaluationresponse`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `evaluation_id` | `ForeignKey` | INDEX, NOT NULL | `evaluations_memberevaluation` | `CASCADE` |
| `author_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `is_member_response` | `BooleanField` | NOT NULL | — | — |
| `message` | `TextField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `evaluations.MemberEvaluation` -> Bảng `evaluations_memberevaluation`
- **Constraints:** `uniq_eval_cycle_member_department`
- **Indexes:** `(cycle, department, status); (member, status)`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `cycle_id` | `ForeignKey` | INDEX, NOT NULL | `evaluations_evaluationcycle` | `PROTECT` |
| `member_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `department_id` | `ForeignKey` | INDEX, NOT NULL | `organization_department` | `PROTECT` |
| `status` | `CharField` | NOT NULL | — | — |
| `overall_rating` | `CharField` | NOT NULL | — | — |
| `strengths` | `TextField` | NOT NULL | — | — |
| `growth_areas` | `TextField` | NOT NULL | — | — |
| `development_plan` | `TextField` | NOT NULL | — | — |
| `telemetry_snapshot` | `JSONField` | NOT NULL | — | — |
| `drafted_by_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `PROTECT` |
| `finalized_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `PROTECT` |
| `finalized_at` | `DateTimeField` | NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |
| `updated_at` | `DateTimeField` | NOT NULL | — | — |

#### `evaluations.MemberRecognition` -> Bảng `evaluations_memberrecognition`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `recipient_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `scope` | `CharField` | NOT NULL | — | — |
| `department_id` | `ForeignKey` | INDEX, NULL | `organization_department` | `SET_NULL` |
| `cycle_id` | `ForeignKey` | INDEX, NULL | `evaluations_evaluationcycle` | `SET_NULL` |
| `title` | `CharField` | NOT NULL | — | — |
| `citation` | `TextField` | NOT NULL | — | — |
| `status` | `CharField` | NOT NULL | — | — |
| `is_public` | `BooleanField` | NOT NULL | — | — |
| `proposed_by_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `PROTECT` |
| `verified_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `PROTECT` |
| `verified_at` | `DateTimeField` | NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

### App `events`
- **Phân loại nguồn dữ liệu:** Sự kiện công khai/nội bộ & loại vé

#### `events.Event` -> Bảng `events_event`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `name` | `CharField` | NOT NULL | — | — |
| `description` | `TextField` | NOT NULL | — | — |
| `location` | `CharField` | NOT NULL | — | — |
| `category` | `CharField` | INDEX, NOT NULL | — | — |
| `starts_at` | `DateTimeField` | NOT NULL | — | — |
| `ends_at` | `DateTimeField` | NULL | — | — |
| `register_deadline` | `DateTimeField` | NOT NULL | — | — |
| `capacity` | `PositiveIntegerField` | NOT NULL | — | — |
| `budget` | `PositiveIntegerField` | NOT NULL | — | — |
| `cover` | `FileField` | NULL | — | — |
| `status` | `CharField` | NOT NULL | — | — |
| `visibility` | `CharField` | INDEX, NOT NULL | — | — |
| `created_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `reminder_sent_at` | `DateTimeField` | NULL | — | — |
| `require_id_check` | `BooleanField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `events.TicketType` -> Bảng `events_tickettype`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `event_id` | `ForeignKey` | INDEX, NOT NULL | `events_event` | `CASCADE` |
| `name` | `CharField` | NOT NULL | — | — |
| `price` | `PositiveIntegerField` | NOT NULL | — | — |
| `quota` | `PositiveIntegerField` | NOT NULL | — | — |
| `sold` | `PositiveIntegerField` | NOT NULL | — | — |

### App `feedback`
- **Phân loại nguồn dữ liệu:** Đánh giá sự kiện & tóm tắt AI

#### `feedback.Feedback` -> Bảng `feedback_feedback`
- **Constraints:** `unique_feedback_per_user_event`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `event_id` | `ForeignKey` | INDEX, NOT NULL | `events_event` | `CASCADE` |
| `user_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `rating` | `PositiveSmallIntegerField` | NOT NULL | — | — |
| `content` | `TextField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `feedback.FeedbackSummary` -> Bảng `feedback_feedbacksummary`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `event_id` | `OneToOneField` | UNIQUE, INDEX, NOT NULL | `events_event` | `CASCADE` |
| `positive` | `TextField` | NOT NULL | — | — |
| `negative` | `TextField` | NOT NULL | — | — |
| `suggestion` | `TextField` | NOT NULL | — | — |
| `feedback_count` | `PositiveIntegerField` | NOT NULL | — | — |
| `generated_at` | `DateTimeField` | NOT NULL | — | — |

### App `finance`
- **Phân loại nguồn dữ liệu:** Sổ cái tài chính bất biến Maker-Checker (CONFIRMED không sửa/xóa)

#### `finance.FinancialTransaction` -> Bảng `finance_financialtransaction`
- **Constraints:** `fin_confirmed_independent_checker`
- **Indexes:** `(status, tx_type); (department, status); (transaction_date); (status, transaction_date, id)`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `tx_code` | `CharField` | UNIQUE, NOT NULL | — | — |
| `tx_type` | `CharField` | NOT NULL | — | — |
| `status` | `CharField` | NOT NULL | — | — |
| `category_id` | `ForeignKey` | INDEX, NOT NULL | `finance_fundcategory` | `PROTECT` |
| `department_id` | `ForeignKey` | INDEX, NULL | `organization_department` | `PROTECT` |
| `club_event_id` | `ForeignKey` | INDEX, NULL | `operations_clubeventprofile` | `PROTECT` |
| `legacy_expense_id` | `OneToOneField` | UNIQUE, INDEX, NULL | `organizing_expense` | `SET_NULL` |
| `title` | `CharField` | NOT NULL | — | — |
| `description` | `TextField` | NOT NULL | — | — |
| `amount` | `PositiveBigIntegerField` | NOT NULL | — | — |
| `adjustment_direction` | `CharField` | NOT NULL | — | — |
| `adjusted_from_id` | `ForeignKey` | INDEX, NULL | `finance_financialtransaction` | `PROTECT` |
| `transaction_date` | `DateField` | NOT NULL | — | — |
| `receipt` | `FileField` | NOT NULL | — | — |
| `receipt_original_name` | `CharField` | NOT NULL | — | — |
| `receipt_content_type` | `CharField` | NOT NULL | — | — |
| `receipt_checksum_sha256` | `CharField` | NOT NULL | — | — |
| `created_by_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `PROTECT` |
| `approved_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `PROTECT` |
| `approved_at` | `DateTimeField` | NULL | — | — |
| `rejection_reason` | `CharField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |
| `updated_at` | `DateTimeField` | NOT NULL | — | — |

#### `finance.FundCategory` -> Bảng `finance_fundcategory`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `code` | `CharField` | UNIQUE, NOT NULL | — | — |
| `name` | `CharField` | NOT NULL | — | — |
| `tx_type` | `CharField` | NOT NULL | — | — |
| `description` | `CharField` | NOT NULL | — | — |
| `is_active` | `BooleanField` | NOT NULL | — | — |
| `display_order` | `PositiveSmallIntegerField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `finance.MemberContribution` -> Bảng `finance_membercontribution`
- **Indexes:** `(member, status); (period_label)`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `member_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `department_id` | `ForeignKey` | INDEX, NULL | `organization_department` | `SET_NULL` |
| `period_label` | `CharField` | NOT NULL | — | — |
| `title` | `CharField` | NOT NULL | — | — |
| `amount` | `PositiveBigIntegerField` | NOT NULL | — | — |
| `status` | `CharField` | NOT NULL | — | — |
| `ledger_transaction_id` | `OneToOneField` | UNIQUE, INDEX, NULL | `finance_financialtransaction` | `SET_NULL` |
| `paid_on` | `DateField` | NULL | — | — |
| `note` | `CharField` | NOT NULL | — | — |
| `recorded_by_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `PROTECT` |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

### App `notifications`
- **Phân loại nguồn dữ liệu:** Thông báo, nhắc lịch & đăng ký Web Push

#### `notifications.Notification` -> Bảng `notifications_notification`
- **Indexes:** `(user, is_read, -created_at)`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `user_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `kind` | `CharField` | NOT NULL | — | — |
| `title` | `CharField` | NOT NULL | — | — |
| `message` | `CharField` | NOT NULL | — | — |
| `url` | `CharField` | NOT NULL | — | — |
| `is_read` | `BooleanField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `notifications.NotificationPreference` -> Bảng `notifications_notificationpreference`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `user_id` | `OneToOneField` | UNIQUE, INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `email_important` | `BooleanField` | NOT NULL | — | — |
| `email_task_deadline` | `BooleanField` | NOT NULL | — | — |
| `email_event_rsvp` | `BooleanField` | NOT NULL | — | — |
| `web_push_enabled` | `BooleanField` | NOT NULL | — | — |
| `updated_at` | `DateTimeField` | NOT NULL | — | — |

#### `notifications.PushSubscription` -> Bảng `notifications_pushsubscription`
- **Constraints:** `uniq_push_sub_user_endpoint`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `user_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `endpoint` | `CharField` | NOT NULL | — | — |
| `p256dh` | `CharField` | NOT NULL | — | — |
| `auth` | `CharField` | NOT NULL | — | — |
| `user_agent` | `CharField` | NOT NULL | — | — |
| `is_active` | `BooleanField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `notifications.ScheduledReminder` -> Bảng `notifications_scheduledreminder`
- **Constraints:** `uniq_scheduled_reminder_once`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `target_type` | `CharField` | NOT NULL | — | — |
| `target_id` | `PositiveBigIntegerField` | NOT NULL | — | — |
| `recipient_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `stage` | `CharField` | NOT NULL | — | — |
| `sent_in_app` | `BooleanField` | NOT NULL | — | — |
| `sent_email` | `BooleanField` | NOT NULL | — | — |
| `sent_at` | `DateTimeField` | NOT NULL | — | — |
| `notification_id` | `OneToOneField` | UNIQUE, INDEX, NULL | `notifications_notification` | `SET_NULL` |
| `email_category` | `CharField` | NOT NULL | — | — |
| `email_pending` | `BooleanField` | INDEX, NOT NULL | — | — |
| `email_attempts` | `PositiveIntegerField` | NOT NULL | — | — |
| `email_last_attempt_at` | `DateTimeField` | NULL | — | — |
| `email_last_error` | `CharField` | NOT NULL | — | — |

### App `operations`
- **Phân loại nguồn dữ liệu:** Dữ liệu vận hành cốt lõi Phase 2 (công việc, RSVP, kỷ luật, khiếu nại)

#### `operations.Appeal` -> Bảng `operations_appeal`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `appellant_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `target_type` | `CharField` | NOT NULL | — | — |
| `discipline_case_id` | `ForeignKey` | INDEX, NULL | `operations_disciplinecase` | `SET_NULL` |
| `task_review_id` | `ForeignKey` | INDEX, NULL | `operations_taskreview` | `SET_NULL` |
| `original_actor_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `reason` | `TextField` | NOT NULL | — | — |
| `evidence_url` | `CharField` | NOT NULL | — | — |
| `status` | `CharField` | INDEX, NOT NULL | — | — |
| `decided_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `decided_at` | `DateTimeField` | NULL | — | — |
| `decision_note` | `TextField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |
| `updated_at` | `DateTimeField` | NOT NULL | — | — |

#### `operations.ClubAnnouncement` -> Bảng `operations_clubannouncement`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `title` | `CharField` | NOT NULL | — | — |
| `content` | `TextField` | NOT NULL | — | — |
| `department_id` | `ForeignKey` | INDEX, NULL | `organization_department` | `CASCADE` |
| `is_pinned` | `BooleanField` | NOT NULL | — | — |
| `send_email` | `BooleanField` | NOT NULL | — | — |
| `published_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `recipient_count` | `PositiveIntegerField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `operations.ClubEventProfile` -> Bảng `operations_clubeventprofile`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `event_id` | `OneToOneField` | UNIQUE, INDEX, NOT NULL | `events_event` | `CASCADE` |
| `event_scope` | `CharField` | INDEX, NOT NULL | — | — |
| `approval_status` | `CharField` | INDEX, NOT NULL | — | — |
| `lead_department_id` | `ForeignKey` | INDEX, NOT NULL | `organization_department` | `PROTECT` |
| `require_club_rsvp` | `BooleanField` | NOT NULL | — | — |
| `default_opt_out_rsvp` | `BooleanField` | NOT NULL | — | — |
| `rsvp_freeze_at` | `DateTimeField` | NULL | — | — |
| `rsvp_frozen_at` | `DateTimeField` | NULL | — | — |
| `policy_version_id` | `ForeignKey` | INDEX, NULL | `organization_policyversion` | `SET_NULL` |
| `proposal_note` | `TextField` | NOT NULL | — | — |
| `review_note` | `CharField` | NOT NULL | — | — |
| `proposed_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `approved_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `approved_at` | `DateTimeField` | NULL | — | — |
| `published_at` | `DateTimeField` | NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |
| `updated_at` | `DateTimeField` | NOT NULL | — | — |

#### `operations.ClubTask` -> Bảng `operations_clubtask`
- **Indexes:** `(department, workflow_status, deadline); (reassignment_needed, department)`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `title` | `CharField` | NOT NULL | — | — |
| `description` | `TextField` | NOT NULL | — | — |
| `department_id` | `ForeignKey` | INDEX, NOT NULL | `organization_department` | `CASCADE` |
| `event_id` | `ForeignKey` | INDEX, NULL | `events_event` | `SET_NULL` |
| `recommended_skill_id` | `ForeignKey` | INDEX, NULL | `organization_skill` | `SET_NULL` |
| `category_tag` | `CharField` | NOT NULL | — | — |
| `priority` | `CharField` | NOT NULL | — | — |
| `workflow_status` | `CharField` | INDEX, NOT NULL | — | — |
| `submission_mode` | `CharField` | NOT NULL | — | — |
| `progress_percent` | `PositiveSmallIntegerField` | NOT NULL | — | — |
| `deadline` | `DateTimeField` | INDEX, NOT NULL | — | — |
| `reassignment_needed` | `BooleanField` | INDEX, NOT NULL | — | — |
| `reassignment_reason` | `CharField` | NOT NULL | — | — |
| `created_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `completed_at` | `DateTimeField` | NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |
| `updated_at` | `DateTimeField` | NOT NULL | — | — |

#### `operations.ClubTaskAssignee` -> Bảng `operations_clubtaskassignee`
- **Constraints:** `uniq_club_task_assignee`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `task_id` | `ForeignKey` | INDEX, NOT NULL | `operations_clubtask` | `CASCADE` |
| `user_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `role` | `CharField` | NOT NULL | — | — |
| `personal_status` | `CharField` | NOT NULL | — | — |
| `progress_percent` | `PositiveSmallIntegerField` | NOT NULL | — | — |
| `is_active` | `BooleanField` | NOT NULL | — | — |
| `accepted_at` | `DateTimeField` | NULL | — | — |
| `assigned_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `assigned_at` | `DateTimeField` | NOT NULL | — | — |

#### `operations.DisciplineCase` -> Bảng `operations_disciplinecase`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `target_user_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `department_id` | `ForeignKey` | INDEX, NULL | `organization_department` | `SET_NULL` |
| `trigger_type` | `CharField` | INDEX, NOT NULL | — | — |
| `term_label` | `CharField` | NOT NULL | — | — |
| `violation_count` | `PositiveSmallIntegerField` | NOT NULL | — | — |
| `threshold_applied` | `PositiveSmallIntegerField` | NOT NULL | — | — |
| `policy_version_id` | `ForeignKey` | INDEX, NULL | `organization_policyversion` | `SET_NULL` |
| `summary` | `CharField` | NOT NULL | — | — |
| `evidence_snapshot` | `JSONField` | NOT NULL | — | — |
| `status` | `CharField` | INDEX, NOT NULL | — | — |
| `created_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `reviewed_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `reviewed_at` | `DateTimeField` | NULL | — | — |
| `resolution_note` | `TextField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |
| `updated_at` | `DateTimeField` | NOT NULL | — | — |

#### `operations.EventAttendance` -> Bảng `operations_eventattendance`
- **Constraints:** `uniq_club_event_attendance_user`
- **Indexes:** `(user, checkin_status)`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `club_event_id` | `ForeignKey` | INDEX, NOT NULL | `operations_clubeventprofile` | `CASCADE` |
| `user_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `rsvp_status` | `CharField` | INDEX, NOT NULL | — | — |
| `decline_reason` | `CharField` | NOT NULL | — | — |
| `exemption_reviewed_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `exemption_reviewed_at` | `DateTimeField` | NULL | — | — |
| `exemption_note` | `CharField` | NOT NULL | — | — |
| `checkin_status` | `CharField` | INDEX, NOT NULL | — | — |
| `checked_in_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `checked_in_at` | `DateTimeField` | NULL | — | — |
| `responded_at` | `DateTimeField` | NULL | — | — |
| `updated_at` | `DateTimeField` | NOT NULL | — | — |

#### `operations.EventAttendanceHistory` -> Bảng `operations_eventattendancehistory`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `attendance_id` | `ForeignKey` | INDEX, NOT NULL | `operations_eventattendance` | `CASCADE` |
| `previous_rsvp_status` | `CharField` | NOT NULL | — | — |
| `new_rsvp_status` | `CharField` | NOT NULL | — | — |
| `actor_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `note` | `CharField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `operations.EventDepartmentRole` -> Bảng `operations_eventdepartmentrole`
- **Constraints:** `uniq_club_event_dept_role`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `club_event_id` | `ForeignKey` | INDEX, NOT NULL | `operations_clubeventprofile` | `CASCADE` |
| `department_id` | `ForeignKey` | INDEX, NOT NULL | `organization_department` | `CASCADE` |
| `role_type` | `CharField` | NOT NULL | — | — |
| `responsibility_note` | `CharField` | NOT NULL | — | — |

#### `operations.TaskExtensionRequest` -> Bảng `operations_taskextensionrequest`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `task_id` | `ForeignKey` | INDEX, NOT NULL | `operations_clubtask` | `CASCADE` |
| `requested_by_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `requested_deadline` | `DateTimeField` | NOT NULL | — | — |
| `reason` | `CharField` | NOT NULL | — | — |
| `status` | `CharField` | NOT NULL | — | — |
| `reviewed_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `reviewed_at` | `DateTimeField` | NULL | — | — |
| `review_note` | `CharField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `operations.TaskReview` -> Bảng `operations_taskreview`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `task_id` | `ForeignKey` | INDEX, NOT NULL | `operations_clubtask` | `CASCADE` |
| `submission_id` | `ForeignKey` | INDEX, NULL | `operations_tasksubmission` | `SET_NULL` |
| `reviewer_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `PROTECT` |
| `decision` | `CharField` | NOT NULL | — | — |
| `quality_score` | `PositiveSmallIntegerField` | NOT NULL | — | — |
| `feedback` | `TextField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `operations.TaskSubmission` -> Bảng `operations_tasksubmission`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `task_id` | `ForeignKey` | INDEX, NOT NULL | `operations_clubtask` | `CASCADE` |
| `submitted_by_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `submission_note` | `TextField` | NOT NULL | — | — |
| `evidence_url` | `CharField` | NOT NULL | — | — |
| `attachment` | `FileField` | NULL | — | — |
| `is_late` | `BooleanField` | NOT NULL | — | — |
| `submitted_at` | `DateTimeField` | NOT NULL | — | — |

### App `organization`
- **Phân loại nguồn dữ liệu:** Danh mục cấu trúc chuẩn (`bootstrap_kmg`) + Dữ liệu nhân sự chính thức CLB

#### `organization.Appointment` -> Bảng `organization_appointment`
- **Indexes:** `(user, is_active, ended_at); (department, is_active)`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `user_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `position_id` | `ForeignKey` | INDEX, NOT NULL | `organization_position` | `PROTECT` |
| `scope_type` | `CharField` | NOT NULL | — | — |
| `department_id` | `ForeignKey` | INDEX, NULL | `organization_department` | `CASCADE` |
| `event_id` | `ForeignKey` | INDEX, NULL | `events_event` | `CASCADE` |
| `title_note` | `CharField` | NOT NULL | — | — |
| `term_label` | `CharField` | NOT NULL | — | — |
| `started_at` | `DateTimeField` | NOT NULL | — | — |
| `ends_at` | `DateTimeField` | NULL | — | — |
| `ended_at` | `DateTimeField` | NULL | — | — |
| `ended_reason` | `CharField` | NOT NULL | — | — |
| `is_active` | `BooleanField` | INDEX, NOT NULL | — | — |
| `singleton_active_key` | `CharField` | UNIQUE, NULL | — | — |
| `appointed_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `revoked_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `organization.ClubMembership` -> Bảng `organization_clubmembership`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `user_id` | `OneToOneField` | UNIQUE, INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `member_code` | `CharField` | UNIQUE, NOT NULL | — | — |
| `status` | `CharField` | INDEX, NOT NULL | — | — |
| `joined_at` | `DateField` | NOT NULL | — | — |
| `left_at` | `DateField` | NULL | — | — |
| `suspended_until` | `DateTimeField` | NULL | — | — |
| `suspended_reason` | `CharField` | NOT NULL | — | — |
| `is_featured` | `BooleanField` | NOT NULL | — | — |
| `featured_title` | `CharField` | NOT NULL | — | — |
| `approved_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `created_at` | `DateTimeField` | NOT NULL | — | — |
| `updated_at` | `DateTimeField` | NOT NULL | — | — |

#### `organization.Department` -> Bảng `organization_department`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `code` | `CharField` | UNIQUE, NOT NULL | — | — |
| `name` | `CharField` | NOT NULL | — | — |
| `slug` | `SlugField` | UNIQUE, INDEX, NOT NULL | — | — |
| `short_description` | `CharField` | NOT NULL | — | — |
| `description` | `TextField` | NOT NULL | — | — |
| `icon` | `CharField` | NOT NULL | — | — |
| `is_demo` | `BooleanField` | NOT NULL | — | — |
| `is_active` | `BooleanField` | NOT NULL | — | — |
| `custom_categories` | `JSONField` | NOT NULL | — | — |
| `display_order` | `PositiveSmallIntegerField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `organization.DepartmentMembership` -> Bảng `organization_departmentmembership`
- **Constraints:** `uniq_dept_membership_user_dept`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `user_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `department_id` | `ForeignKey` | INDEX, NOT NULL | `organization_department` | `CASCADE` |
| `status` | `CharField` | INDEX, NOT NULL | — | — |
| `joined_at` | `DateField` | NOT NULL | — | — |
| `left_at` | `DateField` | NULL | — | — |
| `note` | `CharField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |
| `updated_at` | `DateTimeField` | NOT NULL | — | — |

#### `organization.MemberLifecycleEvent` -> Bảng `organization_memberlifecycleevent`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `user_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `event_type` | `CharField` | INDEX, NOT NULL | — | — |
| `department_id` | `ForeignKey` | INDEX, NULL | `organization_department` | `SET_NULL` |
| `actor_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `title` | `CharField` | NOT NULL | — | — |
| `note` | `CharField` | NOT NULL | — | — |
| `metadata` | `JSONField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | INDEX, NOT NULL | — | — |

#### `organization.MembershipApplication` -> Bảng `organization_membershipapplication`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `user_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `primary_department_id` | `ForeignKey` | INDEX, NOT NULL | `organization_department` | `CASCADE` |
| `secondary_department_id` | `ForeignKey` | INDEX, NULL | `organization_department` | `SET_NULL` |
| `declared_skills_text` | `CharField` | NOT NULL | — | — |
| `motivation` | `TextField` | NOT NULL | — | — |
| `portfolio_url` | `CharField` | NOT NULL | — | — |
| `status` | `CharField` | INDEX, NOT NULL | — | — |
| `screening_note` | `CharField` | NOT NULL | — | — |
| `screened_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `screened_at` | `DateTimeField` | NULL | — | — |
| `reviewed_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `reviewed_at` | `DateTimeField` | NULL | — | — |
| `decision_note` | `CharField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `organization.Permission` -> Bảng `organization_permission`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `code` | `CharField` | UNIQUE, NOT NULL | — | — |
| `name` | `CharField` | NOT NULL | — | — |
| `module` | `CharField` | INDEX, NOT NULL | — | — |
| `scope_type` | `CharField` | NOT NULL | — | — |
| `is_mutation` | `BooleanField` | NOT NULL | — | — |

#### `organization.PermissionGrant` -> Bảng `organization_permissiongrant`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `grantee_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `bound_appointment_id` | `ForeignKey` | INDEX, NOT NULL | `organization_appointment` | `CASCADE` |
| `bundle_code` | `CharField` | NOT NULL | — | — |
| `scope_type` | `CharField` | NOT NULL | — | — |
| `department_id` | `ForeignKey` | INDEX, NULL | `organization_department` | `CASCADE` |
| `reason` | `CharField` | NOT NULL | — | — |
| `starts_at` | `DateTimeField` | NOT NULL | — | — |
| `expires_at` | `DateTimeField` | NULL | — | — |
| `is_active` | `BooleanField` | INDEX, NOT NULL | — | — |
| `granted_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `revoked_at` | `DateTimeField` | NULL | — | — |
| `revoked_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `organization.PolicyVersion` -> Bảng `organization_policyversion`
- **Constraints:** `uniq_policy_key_version`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `policy_key` | `CharField` | INDEX, NOT NULL | — | — |
| `version_number` | `PositiveIntegerField` | NOT NULL | — | — |
| `title` | `CharField` | NOT NULL | — | — |
| `config` | `JSONField` | NOT NULL | — | — |
| `is_current` | `BooleanField` | INDEX, NOT NULL | — | — |
| `effective_from` | `DateTimeField` | NOT NULL | — | — |
| `approved_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `organization.Position` -> Bảng `organization_position`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `code` | `CharField` | UNIQUE, NOT NULL | — | — |
| `name` | `CharField` | NOT NULL | — | — |
| `scope_type` | `CharField` | NOT NULL | — | — |
| `is_officer` | `BooleanField` | NOT NULL | — | — |
| `is_singleton` | `BooleanField` | NOT NULL | — | — |
| `is_read_only` | `BooleanField` | NOT NULL | — | — |
| `rank_order` | `PositiveSmallIntegerField` | NOT NULL | — | — |

#### `organization.PositionPermission` -> Bảng `organization_positionpermission`
- **Constraints:** `uniq_position_permission`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `position_id` | `ForeignKey` | INDEX, NOT NULL | `organization_position` | `CASCADE` |
| `permission_id` | `ForeignKey` | INDEX, NOT NULL | `organization_permission` | `CASCADE` |

#### `organization.ResourceAccessRule` -> Bảng `organization_resourceaccessrule`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `resource_type` | `CharField` | NOT NULL | — | — |
| `resource_code` | `CharField` | UNIQUE, NOT NULL | — | — |
| `title` | `CharField` | NOT NULL | — | — |
| `department_id` | `ForeignKey` | INDEX, NULL | `organization_department` | `CASCADE` |
| `classification` | `CharField` | NOT NULL | — | — |
| `recommended_skill_id` | `ForeignKey` | INDEX, NULL | `organization_skill` | `SET_NULL` |
| `created_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `organization.Skill` -> Bảng `organization_skill`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `category_id` | `ForeignKey` | INDEX, NOT NULL | `organization_skillcategory` | `CASCADE` |
| `code` | `CharField` | UNIQUE, NOT NULL | — | — |
| `name` | `CharField` | NOT NULL | — | — |
| `description` | `CharField` | NOT NULL | — | — |
| `is_active` | `BooleanField` | NOT NULL | — | — |

#### `organization.SkillCategory` -> Bảng `organization_skillcategory`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `code` | `CharField` | UNIQUE, NOT NULL | — | — |
| `name` | `CharField` | NOT NULL | — | — |
| `department_id` | `ForeignKey` | INDEX, NULL | `organization_department` | `SET_NULL` |
| `display_order` | `PositiveSmallIntegerField` | NOT NULL | — | — |

#### `organization.UserSkill` -> Bảng `organization_userskill`
- **Constraints:** `uniq_user_skill_pair`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `user_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `skill_id` | `ForeignKey` | INDEX, NOT NULL | `organization_skill` | `CASCADE` |
| `proficiency` | `CharField` | NOT NULL | — | — |
| `verification_status` | `CharField` | INDEX, NOT NULL | — | — |
| `experience_note` | `CharField` | NOT NULL | — | — |
| `evidence_url` | `CharField` | NOT NULL | — | — |
| `verified_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `verified_at` | `DateTimeField` | NULL | — | — |
| `review_note` | `CharField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

### App `organizing`
- **Phân loại nguồn dữ liệu:** Module Legacy M3 (giữ tương thích ngược, cầu nối CM-03 tới Finance)

#### `organizing.Department` -> Bảng `organizing_department`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `name` | `CharField` | UNIQUE, NOT NULL | — | — |
| `slug` | `SlugField` | UNIQUE, INDEX, NOT NULL | — | — |
| `description` | `CharField` | NOT NULL | — | — |
| `icon` | `CharField` | NOT NULL | — | — |
| `lead_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `order` | `PositiveSmallIntegerField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `organizing.EventPostMortem` -> Bảng `organizing_eventpostmortem`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `event_id` | `OneToOneField` | UNIQUE, INDEX, NOT NULL | `events_event` | `CASCADE` |
| `executive_summary` | `TextField` | NOT NULL | — | — |
| `highlights` | `JSONField` | NOT NULL | — | — |
| `financial_analysis` | `TextField` | NOT NULL | — | — |
| `feedback_analysis` | `TextField` | NOT NULL | — | — |
| `lessons_learned` | `JSONField` | NOT NULL | — | — |
| `action_items` | `JSONField` | NOT NULL | — | — |
| `stats_snapshot` | `JSONField` | NOT NULL | — | — |
| `markdown_content` | `TextField` | NOT NULL | — | — |
| `generated_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `generated_at` | `DateTimeField` | NOT NULL | — | — |

#### `organizing.Expense` -> Bảng `organizing_expense`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `event_id` | `ForeignKey` | INDEX, NOT NULL | `events_event` | `CASCADE` |
| `title` | `CharField` | NOT NULL | — | — |
| `category` | `CharField` | NOT NULL | — | — |
| `amount` | `PositiveIntegerField` | NOT NULL | — | — |
| `paid_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `PROTECT` |
| `spent_on` | `DateField` | NOT NULL | — | — |
| `note` | `CharField` | NOT NULL | — | — |
| `receipt` | `FileField` | NULL | — | — |
| `created_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `PROTECT` |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `organizing.Task` -> Bảng `organizing_task`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `event_id` | `ForeignKey` | INDEX, NULL | `events_event` | `CASCADE` |
| `department_id` | `ForeignKey` | INDEX, NULL | `organizing_department` | `SET_NULL` |
| `title` | `CharField` | NOT NULL | — | — |
| `description` | `TextField` | NOT NULL | — | — |
| `assignee_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `deadline` | `DateTimeField` | NULL | — | — |
| `status` | `CharField` | NOT NULL | — | — |
| `priority` | `CharField` | NOT NULL | — | — |
| `note` | `CharField` | NOT NULL | — | — |
| `created_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `created_by_ai` | `BooleanField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |
| `done_at` | `DateTimeField` | NULL | — | — |
| `due_reminded_at` | `DateTimeField` | NULL | — | — |
| `overdue_reminded_at` | `DateTimeField` | NULL | — | — |

### App `pages`
- **Phân loại nguồn dữ liệu:** Ban quản trị theo nhiệm kỳ (`ClubOfficer`, legacy migration `0002`)

#### `pages.ClubOfficer` -> Bảng `pages_clubofficer`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `name` | `CharField` | NOT NULL | — | — |
| `position` | `CharField` | NOT NULL | — | — |
| `department_id` | `ForeignKey` | INDEX, NULL | `organizing_department` | `SET_NULL` |
| `term` | `CharField` | NOT NULL | — | — |
| `photo` | `FileField` | NULL | — | — |
| `user_id` | `OneToOneField` | UNIQUE, INDEX, NULL | `accounts_user` | `SET_NULL` |
| `order` | `PositiveSmallIntegerField` | NOT NULL | — | — |
| `is_current` | `BooleanField` | NOT NULL | — | — |

### App `programs`
- **Phân loại nguồn dữ liệu:** Kho tài liệu mật (PrivateVault), đề xuất & đào tạo thực hành

#### `programs.ConfidentialDocument` -> Bảng `programs_confidentialdocument`
- **Indexes:** `(department, classification, is_archived)`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `code` | `CharField` | UNIQUE, NOT NULL | — | — |
| `title` | `CharField` | NOT NULL | — | — |
| `description` | `TextField` | NOT NULL | — | — |
| `department_id` | `ForeignKey` | INDEX, NULL | `organization_department` | `CASCADE` |
| `category_id` | `ForeignKey` | INDEX, NULL | `programs_documentcategory` | `SET_NULL` |
| `custom_category_label` | `CharField` | NOT NULL | — | — |
| `classification` | `CharField` | INDEX, NOT NULL | — | — |
| `owner_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `is_archived` | `BooleanField` | INDEX, NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |
| `updated_at` | `DateTimeField` | NOT NULL | — | — |

#### `programs.DepartmentProposal` -> Bảng `programs_departmentproposal`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `code` | `CharField` | UNIQUE, NOT NULL | — | — |
| `title` | `CharField` | NOT NULL | — | — |
| `proposal_type` | `CharField` | NOT NULL | — | — |
| `scope` | `CharField` | INDEX, NOT NULL | — | — |
| `department_id` | `ForeignKey` | INDEX, NOT NULL | `organization_department` | `CASCADE` |
| `proposer_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `summary` | `TextField` | NOT NULL | — | — |
| `objectives` | `TextField` | NOT NULL | — | — |
| `estimated_budget` | `DecimalField` | NOT NULL | — | — |
| `proposed_start_at` | `DateTimeField` | NULL | — | — |
| `proposed_location` | `CharField` | NOT NULL | — | — |
| `status` | `CharField` | INDEX, NOT NULL | — | — |
| `is_escalated_to_bcn` | `BooleanField` | NOT NULL | — | — |
| `attachment` | `FileField` | NULL | — | — |
| `linked_event_id` | `OneToOneField` | UNIQUE, INDEX, NULL | `operations_clubeventprofile` | `SET_NULL` |
| `linked_course_id` | `OneToOneField` | UNIQUE, INDEX, NULL | `programs_trainingcourse` | `SET_NULL` |
| `submitted_at` | `DateTimeField` | NULL | — | — |
| `approved_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `approved_at` | `DateTimeField` | NULL | — | — |
| `decision_note` | `CharField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |
| `updated_at` | `DateTimeField` | NOT NULL | — | — |

#### `programs.DepartmentShowcaseItem` -> Bảng `programs_departmentshowcaseitem`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `department_id` | `ForeignKey` | INDEX, NOT NULL | `organization_department` | `CASCADE` |
| `category_label` | `CharField` | NOT NULL | — | — |
| `item_type` | `CharField` | NOT NULL | — | — |
| `title` | `CharField` | NOT NULL | — | — |
| `summary` | `TextField` | NOT NULL | — | — |
| `external_url` | `CharField` | NOT NULL | — | — |
| `linked_document_id` | `ForeignKey` | INDEX, NULL | `programs_confidentialdocument` | `SET_NULL` |
| `is_pinned` | `BooleanField` | NOT NULL | — | — |
| `created_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `programs.DocumentAccessLog` -> Bảng `programs_documentaccesslog`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `document_id` | `ForeignKey` | INDEX, NOT NULL | `programs_confidentialdocument` | `CASCADE` |
| `version_id` | `ForeignKey` | INDEX, NULL | `programs_documentversion` | `SET_NULL` |
| `actor_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `action` | `CharField` | INDEX, NOT NULL | — | — |
| `ip_address` | `GenericIPAddressField` | NULL | — | — |
| `user_agent` | `CharField` | NOT NULL | — | — |
| `reason` | `CharField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | INDEX, NOT NULL | — | — |

#### `programs.DocumentACLEntry` -> Bảng `programs_documentaclentry`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `document_id` | `ForeignKey` | INDEX, NOT NULL | `programs_confidentialdocument` | `CASCADE` |
| `subject_type` | `CharField` | INDEX, NOT NULL | — | — |
| `user_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `CASCADE` |
| `position_id` | `ForeignKey` | INDEX, NULL | `organization_position` | `CASCADE` |
| `position_department_id` | `ForeignKey` | INDEX, NULL | `organization_department` | `CASCADE` |
| `task_id` | `ForeignKey` | INDEX, NULL | `operations_clubtask` | `CASCADE` |
| `department_id` | `ForeignKey` | INDEX, NULL | `organization_department` | `CASCADE` |
| `permission_level` | `CharField` | NOT NULL | — | — |
| `is_break_glass` | `BooleanField` | NOT NULL | — | — |
| `bound_dept_membership_id` | `ForeignKey` | INDEX, NULL | `organization_departmentmembership` | `SET_NULL` |
| `bound_appointment_id` | `ForeignKey` | INDEX, NULL | `organization_appointment` | `SET_NULL` |
| `reason` | `CharField` | NOT NULL | — | — |
| `expires_at` | `DateTimeField` | NULL | — | — |
| `is_active` | `BooleanField` | INDEX, NOT NULL | — | — |
| `granted_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `revoked_at` | `DateTimeField` | NULL | — | — |
| `revoked_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `revoked_reason` | `CharField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `programs.DocumentCategory` -> Bảng `programs_documentcategory`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `department_id` | `ForeignKey` | INDEX, NULL | `organization_department` | `CASCADE` |
| `code` | `CharField` | UNIQUE, NOT NULL | — | — |
| `name` | `CharField` | NOT NULL | — | — |
| `description` | `CharField` | NOT NULL | — | — |
| `display_order` | `PositiveSmallIntegerField` | NOT NULL | — | — |
| `is_active` | `BooleanField` | NOT NULL | — | — |

#### `programs.DocumentVersion` -> Bảng `programs_documentversion`
- **Constraints:** `uniq_doc_version_num`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `document_id` | `ForeignKey` | INDEX, NOT NULL | `programs_confidentialdocument` | `CASCADE` |
| `version_number` | `PositiveIntegerField` | NOT NULL | — | — |
| `file` | `FileField` | NOT NULL | — | — |
| `original_filename` | `CharField` | NOT NULL | — | — |
| `content_type` | `CharField` | NOT NULL | — | — |
| `file_size` | `PositiveBigIntegerField` | NOT NULL | — | — |
| `checksum_sha256` | `CharField` | NOT NULL | — | — |
| `change_note` | `CharField` | NOT NULL | — | — |
| `uploaded_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `is_current` | `BooleanField` | INDEX, NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `programs.PracticeParticipant` -> Bảng `programs_practiceparticipant`
- **Constraints:** `uniq_practice_part_sess_user`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `session_id` | `ForeignKey` | INDEX, NOT NULL | `programs_practicesession` | `CASCADE` |
| `user_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `assigned_role` | `CharField` | NOT NULL | — | — |
| `skill_id` | `ForeignKey` | INDEX, NULL | `organization_skill` | `SET_NULL` |
| `response_status` | `CharField` | INDEX, NOT NULL | — | — |
| `note` | `CharField` | NOT NULL | — | — |
| `updated_at` | `DateTimeField` | NOT NULL | — | — |

#### `programs.PracticeSession` -> Bảng `programs_practicesession`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `department_id` | `ForeignKey` | INDEX, NOT NULL | `organization_department` | `CASCADE` |
| `club_event_id` | `ForeignKey` | INDEX, NULL | `operations_clubeventprofile` | `SET_NULL` |
| `title` | `CharField` | NOT NULL | — | — |
| `repertoire_note` | `TextField` | NOT NULL | — | — |
| `location` | `CharField` | NOT NULL | — | — |
| `starts_at` | `DateTimeField` | NOT NULL | — | — |
| `ends_at` | `DateTimeField` | NOT NULL | — | — |
| `lead_coordinator_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `status` | `CharField` | INDEX, NOT NULL | — | — |
| `created_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `created_at` | `DateTimeField` | NOT NULL | — | — |
| `updated_at` | `DateTimeField` | NOT NULL | — | — |

#### `programs.ProposalComment` -> Bảng `programs_proposalcomment`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `proposal_id` | `ForeignKey` | INDEX, NOT NULL | `programs_departmentproposal` | `CASCADE` |
| `author_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `body` | `TextField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `programs.ProposalReview` -> Bảng `programs_proposalreview`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `proposal_id` | `ForeignKey` | INDEX, NOT NULL | `programs_departmentproposal` | `CASCADE` |
| `reviewer_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `PROTECT` |
| `stage` | `CharField` | NOT NULL | — | — |
| `decision` | `CharField` | NOT NULL | — | — |
| `feedback` | `TextField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `programs.TrainingCourse` -> Bảng `programs_trainingcourse`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `department_id` | `ForeignKey` | INDEX, NOT NULL | `organization_department` | `CASCADE` |
| `title` | `CharField` | NOT NULL | — | — |
| `description` | `TextField` | NOT NULL | — | — |
| `custom_category` | `CharField` | NOT NULL | — | — |
| `target_skill_id` | `ForeignKey` | INDEX, NULL | `organization_skill` | `SET_NULL` |
| `instructor_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `location` | `CharField` | NOT NULL | — | — |
| `starts_at` | `DateTimeField` | NOT NULL | — | — |
| `ends_at` | `DateTimeField` | NOT NULL | — | — |
| `capacity` | `PositiveIntegerField` | NOT NULL | — | — |
| `status` | `CharField` | INDEX, NOT NULL | — | — |
| `created_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `created_at` | `DateTimeField` | NOT NULL | — | — |
| `updated_at` | `DateTimeField` | NOT NULL | — | — |

#### `programs.TrainingEnrollment` -> Bảng `programs_trainingenrollment`
- **Constraints:** `uniq_training_enroll_course_user`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `course_id` | `ForeignKey` | INDEX, NOT NULL | `programs_trainingcourse` | `CASCADE` |
| `user_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `status` | `CharField` | INDEX, NOT NULL | — | — |
| `attendance_count` | `PositiveSmallIntegerField` | NOT NULL | — | — |
| `completion_note` | `CharField` | NOT NULL | — | — |
| `enrolled_at` | `DateTimeField` | NOT NULL | — | — |
| `completed_at` | `DateTimeField` | NULL | — | — |
| `updated_at` | `DateTimeField` | NOT NULL | — | — |

### App `public_portal`
- **Phân loại nguồn dữ liệu:** Liên hệ công khai

#### `public_portal.ContactSubmission` -> Bảng `public_portal_contactsubmission`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `full_name` | `CharField` | NOT NULL | — | — |
| `email` | `CharField` | NOT NULL | — | — |
| `phone` | `CharField` | NOT NULL | — | — |
| `topic` | `CharField` | NOT NULL | — | — |
| `message` | `TextField` | NOT NULL | — | — |
| `status` | `CharField` | INDEX, NOT NULL | — | — |
| `ip_hash` | `CharField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

### App `recruitment`
- **Phân loại nguồn dữ liệu:** Module Tuyển thành viên theo đợt Legacy (cầu nối với organization.Department)

#### `recruitment.Application` -> Bảng `recruitment_application`
- **Constraints:** `uniq_application_per_round`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `round_id` | `ForeignKey` | INDEX, NOT NULL | `recruitment_recruitmentround` | `CASCADE` |
| `user_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `department_id` | `ForeignKey` | INDEX, NULL | `organizing_department` | `SET_NULL` |
| `strengths` | `CharField` | NOT NULL | — | — |
| `level` | `CharField` | NOT NULL | — | — |
| `portfolio_url` | `CharField` | NOT NULL | — | — |
| `motivation` | `TextField` | NOT NULL | — | — |
| `status` | `CharField` | INDEX, NOT NULL | — | — |
| `interview_at` | `DateTimeField` | NULL | — | — |
| `review_note` | `CharField` | NOT NULL | — | — |
| `reviewer_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `reviewed_at` | `DateTimeField` | NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `recruitment.RecruitmentRound` -> Bảng `recruitment_recruitmentround`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `name` | `CharField` | NOT NULL | — | — |
| `description` | `TextField` | NOT NULL | — | — |
| `opens_at` | `DateTimeField` | NOT NULL | — | — |
| `closes_at` | `DateTimeField` | NOT NULL | — | — |
| `created_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

### App `registrations`
- **Phân loại nguồn dữ liệu:** Vé, chuyển nhượng vé & danh sách chờ (khóa dòng MySQL SELECT ... FOR UPDATE)

#### `registrations.Ticket` -> Bảng `registrations_ticket`
- **Indexes:** `(event, status)`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `code` | `CharField` | UNIQUE, INDEX, NOT NULL | — | — |
| `event_id` | `ForeignKey` | INDEX, NOT NULL | `events_event` | `CASCADE` |
| `ticket_type_id` | `ForeignKey` | INDEX, NOT NULL | `events_tickettype` | `PROTECT` |
| `user_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `status` | `CharField` | NOT NULL | — | — |
| `booking_ref` | `CharField` | INDEX, NOT NULL | — | — |
| `price` | `PositiveIntegerField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |
| `confirmed_at` | `DateTimeField` | NULL | — | — |
| `checked_in_at` | `DateTimeField` | NULL | — | — |
| `checked_in_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |

#### `registrations.TicketTransfer` -> Bảng `registrations_tickettransfer`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `ticket_id` | `ForeignKey` | INDEX, NOT NULL | `registrations_ticket` | `CASCADE` |
| `from_user_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `to_user_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `old_code` | `CharField` | INDEX, NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `registrations.WaitlistEntry` -> Bảng `registrations_waitlistentry`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `ticket_type_id` | `ForeignKey` | INDEX, NOT NULL | `events_tickettype` | `CASCADE` |
| `user_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `status` | `CharField` | NOT NULL | — | — |
| `ticket_id` | `OneToOneField` | UNIQUE, INDEX, NULL | `registrations_ticket` | `SET_NULL` |
| `note` | `CharField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | INDEX, NOT NULL | — | — |
| `resolved_at` | `DateTimeField` | NULL | — | — |

### App `sessions`
- **Phân loại nguồn dữ liệu:** Phiên làm việc người dùng

#### `sessions.Session` -> Bảng `django_session`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `session_key` | `CharField` | PK, UNIQUE, NOT NULL | — | — |
| `session_data` | `TextField` | NOT NULL | — | — |
| `expire_date` | `DateTimeField` | INDEX, NOT NULL | — | — |

### App `social`
- **Phân loại nguồn dữ liệu:** Mạng xã hội nội bộ, tin nhắn mã hóa AES-256-GCM & chia sẻ nhạc

#### `social.ChatAttachment` -> Bảng `social_chatattachment`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `message_id` | `ForeignKey` | INDEX, NOT NULL | `social_chatmessage` | `CASCADE` |
| `file` | `FileField` | NOT NULL | — | — |
| `original_filename` | `CharField` | NOT NULL | — | — |
| `content_type` | `CharField` | NOT NULL | — | — |
| `file_size` | `PositiveIntegerField` | NOT NULL | — | — |
| `checksum_sha256` | `CharField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `social.ChatMessage` -> Bảng `social_chatmessage`
- **Indexes:** `(conversation, id)`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `conversation_id` | `ForeignKey` | INDEX, NOT NULL | `social_conversation` | `CASCADE` |
| `sender_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `PROTECT` |
| `reply_to_id` | `ForeignKey` | INDEX, NULL | `social_chatmessage` | `SET_NULL` |
| `ciphertext` | `BinaryField` | NOT NULL | — | — |
| `iv_nonce` | `BinaryField` | NOT NULL | — | — |
| `has_attachment` | `BooleanField` | NOT NULL | — | — |
| `is_recalled` | `BooleanField` | NOT NULL | — | — |
| `recalled_at` | `DateTimeField` | NULL | — | — |
| `created_at` | `DateTimeField` | INDEX, NOT NULL | — | — |

#### `social.ChatReaction` -> Bảng `social_chatreaction`
- **Constraints:** `uniq_chat_react_msg_u`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `message_id` | `ForeignKey` | INDEX, NOT NULL | `social_chatmessage` | `CASCADE` |
| `user_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `emoji` | `CharField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `social.Conversation` -> Bảng `social_conversation`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `conv_type` | `CharField` | INDEX, NOT NULL | — | — |
| `title` | `CharField` | NOT NULL | — | — |
| `department_id` | `ForeignKey` | INDEX, NULL | `organization_department` | `CASCADE` |
| `club_event_id` | `ForeignKey` | INDEX, NULL | `operations_clubeventprofile` | `CASCADE` |
| `task_id` | `ForeignKey` | INDEX, NULL | `operations_clubtask` | `CASCADE` |
| `direct_pair_key` | `CharField` | UNIQUE, NULL | — | — |
| `channel_scope_key` | `CharField` | UNIQUE, NULL | — | — |
| `encrypted_dek` | `TextField` | NOT NULL | — | — |
| `created_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `last_message_at` | `DateTimeField` | INDEX, NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `social.ConversationMember` -> Bảng `social_conversationmember`
- **Constraints:** `uniq_conv_member_user`
- **Indexes:** `(user, left_at)`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `conversation_id` | `ForeignKey` | INDEX, NOT NULL | `social_conversation` | `CASCADE` |
| `user_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `member_role` | `CharField` | NOT NULL | — | — |
| `joined_at` | `DateTimeField` | NOT NULL | — | — |
| `left_at` | `DateTimeField` | INDEX, NULL | — | — |
| `last_read_message_id` | `PositiveBigIntegerField` | NULL | — | — |
| `last_read_at` | `DateTimeField` | NULL | — | — |
| `is_muted` | `BooleanField` | NOT NULL | — | — |

#### `social.MessageAbuseReport` -> Bảng `social_messageabusereport`
- **Constraints:** `uniq_msg_abuse_rep_msg`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `reporter_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `reported_user_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `conversation_id` | `ForeignKey` | INDEX, NOT NULL | `social_conversation` | `CASCADE` |
| `message_id` | `ForeignKey` | INDEX, NOT NULL | `social_chatmessage` | `CASCADE` |
| `reason` | `TextField` | NOT NULL | — | — |
| `verified_plaintext_snapshot` | `TextField` | NOT NULL | — | — |
| `hmac_proof` | `CharField` | NOT NULL | — | — |
| `status` | `CharField` | INDEX, NOT NULL | — | — |
| `handled_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `resolution_note` | `CharField` | NOT NULL | — | — |
| `resolved_at` | `DateTimeField` | NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `social.MusicPlaylist` -> Bảng `social_musicplaylist`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `owner_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `title` | `CharField` | NOT NULL | — | — |
| `description` | `CharField` | NOT NULL | — | — |
| `visibility` | `CharField` | INDEX, NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |
| `updated_at` | `DateTimeField` | NOT NULL | — | — |

#### `social.MusicShare` -> Bảng `social_musicshare`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `sender_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `recipient_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `source_playlist_item_id` | `ForeignKey` | INDEX, NULL | `social_playlistitem` | `SET_NULL` |
| `source_provider` | `CharField` | NOT NULL | — | — |
| `track_url` | `CharField` | NOT NULL | — | — |
| `title` | `CharField` | NOT NULL | — | — |
| `artist_name` | `CharField` | NOT NULL | — | — |
| `personal_message` | `CharField` | NOT NULL | — | — |
| `is_saved_to_playlist` | `BooleanField` | NOT NULL | — | — |
| `saved_item_id` | `ForeignKey` | INDEX, NULL | `social_playlistitem` | `SET_NULL` |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `social.PlaylistItem` -> Bảng `social_playlistitem`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `playlist_id` | `ForeignKey` | INDEX, NOT NULL | `social_musicplaylist` | `CASCADE` |
| `source_provider` | `CharField` | NOT NULL | — | — |
| `external_track_id` | `CharField` | NOT NULL | — | — |
| `track_url` | `CharField` | NOT NULL | — | — |
| `title` | `CharField` | NOT NULL | — | — |
| `artist_name` | `CharField` | NOT NULL | — | — |
| `duration_seconds` | `PositiveIntegerField` | NULL | — | — |
| `sort_order` | `PositiveSmallIntegerField` | NOT NULL | — | — |
| `added_at` | `DateTimeField` | NOT NULL | — | — |

#### `social.SocialComment` -> Bảng `social_socialcomment`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `post_id` | `ForeignKey` | INDEX, NOT NULL | `social_socialpost` | `CASCADE` |
| `author_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `parent_id` | `ForeignKey` | INDEX, NULL | `social_socialcomment` | `CASCADE` |
| `content` | `TextField` | NOT NULL | — | — |
| `is_deleted` | `BooleanField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `social.SocialModerationLog` -> Bảng `social_socialmoderationlog`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `post_id` | `ForeignKey` | INDEX, NOT NULL | `social_socialpost` | `CASCADE` |
| `report_id` | `ForeignKey` | INDEX, NULL | `social_socialreport` | `SET_NULL` |
| `actor_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `PROTECT` |
| `action` | `CharField` | NOT NULL | — | — |
| `note` | `CharField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `social.SocialPost` -> Bảng `social_socialpost`
- **Indexes:** `(visibility, moderation_status, is_deleted, -created_at); (department, is_deleted, -created_at); (author, is_deleted, -created_at)`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `author_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `department_id` | `ForeignKey` | INDEX, NULL | `organization_department` | `SET_NULL` |
| `visibility` | `CharField` | INDEX, NOT NULL | — | — |
| `content` | `TextField` | NOT NULL | — | — |
| `shared_post_id` | `ForeignKey` | INDEX, NULL | `social_socialpost` | `SET_NULL` |
| `link_url` | `CharField` | NOT NULL | — | — |
| `moderation_status` | `CharField` | INDEX, NOT NULL | — | — |
| `is_deleted` | `BooleanField` | INDEX, NOT NULL | — | — |
| `deleted_at` | `DateTimeField` | NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |
| `updated_at` | `DateTimeField` | NOT NULL | — | — |

#### `social.SocialPostAttachment` -> Bảng `social_socialpostattachment`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `post_id` | `ForeignKey` | INDEX, NOT NULL | `social_socialpost` | `CASCADE` |
| `attachment_type` | `CharField` | NOT NULL | — | — |
| `file` | `FileField` | NOT NULL | — | — |
| `original_filename` | `CharField` | NOT NULL | — | — |
| `content_type` | `CharField` | NOT NULL | — | — |
| `file_size` | `PositiveIntegerField` | NOT NULL | — | — |
| `checksum_sha256` | `CharField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `social.SocialPostAudienceMember` -> Bảng `social_socialpostaudiencemember`
- **Constraints:** `uniq_soc_post_aud_user`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `post_id` | `ForeignKey` | INDEX, NOT NULL | `social_socialpost` | `CASCADE` |
| `user_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `added_at` | `DateTimeField` | NOT NULL | — | — |

#### `social.SocialReaction` -> Bảng `social_socialreaction`
- **Constraints:** `uniq_soc_react_post_u, uniq_soc_react_cmt_u`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `post_id` | `ForeignKey` | INDEX, NULL | `social_socialpost` | `CASCADE` |
| `comment_id` | `ForeignKey` | INDEX, NULL | `social_socialcomment` | `CASCADE` |
| `user_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `reaction_type` | `CharField` | NOT NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |

#### `social.SocialReport` -> Bảng `social_socialreport`

| Cột DB | Kiểu Django | Khóa / Ràng buộc | Tham chiếu (FK) | `on_delete` |
|---|---|---|---|---|
| `id` | `BigAutoField` | PK, UNIQUE, NOT NULL | — | — |
| `post_id` | `ForeignKey` | INDEX, NOT NULL | `social_socialpost` | `CASCADE` |
| `reporter_id` | `ForeignKey` | INDEX, NOT NULL | `accounts_user` | `CASCADE` |
| `reason` | `TextField` | NOT NULL | — | — |
| `status` | `CharField` | INDEX, NOT NULL | — | — |
| `handled_by_id` | `ForeignKey` | INDEX, NULL | `accounts_user` | `SET_NULL` |
| `resolution_note` | `CharField` | NOT NULL | — | — |
| `resolved_at` | `DateTimeField` | NULL | — | — |
| `created_at` | `DateTimeField` | NOT NULL | — | — |
