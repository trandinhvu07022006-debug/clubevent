# ERD — SƠ ĐỒ QUAN HỆ THỰC THỂ KMG PLATFORM

Tài liệu tổng hợp sơ đồ thực thể (ERD) trích xuất trực tiếp từ `99` model thực tế của hệ thống KMG (`MySQL 8.4`, `InnoDB`).

## 1. Lõi Danh tính, Tổ chức & Phân quyền (`accounts`, `organization`)

```mermaid
erDiagram
    accounts_user ||--o| accounts_userprofile : has_profile
    accounts_user ||--o{ accounts_usersession : has_sessions
    accounts_user ||--o| organization_clubmembership : membership
    accounts_user ||--o{ organization_departmentmembership : dept_roles
    organization_department ||--o{ organization_departmentmembership : contains
    accounts_user ||--o{ organization_appointment : holds_office
    organization_position ||--o{ organization_appointment : defines
    organization_department ||--o{ organization_appointment : scope_dept
    organization_position ||--o{ organization_positionpermission : default_perms
    organization_permission ||--o{ organization_positionpermission : granted_via
    accounts_user ||--o{ organization_permissiongrant : delegated_to
    organization_appointment ||--o{ organization_permissiongrant : binds_term
    organization_skillcategory ||--o{ organization_skill : categorizes
    accounts_user ||--o{ organization_userskill : declares
    organization_skill ||--o{ organization_userskill : verified_skill
    accounts_user ||--o{ organization_memberlifecycleevent : immutable_history
```

## 2. Sự kiện, Đặt vé, Check-in & Đánh giá (`events`, `registrations`, `feedback`)

```mermaid
erDiagram
    accounts_user ||--o{ events_event : creates
    events_event ||--o{ events_tickettype : sells
    events_event ||--o{ registrations_ticket : issues
    events_tickettype ||--o{ registrations_ticket : typed_as
    accounts_user ||--o{ registrations_ticket : owns
    registrations_ticket ||--o{ registrations_tickettransfer : transfers
    events_tickettype ||--o{ registrations_waitlistentry : queues
    events_event ||--o{ feedback_feedback : receives
    events_event ||--o| feedback_feedbacksummary : summarizes
```

## 3. Vận hành, Công việc, Tài chính & Tài liệu (`operations`, `organizing`, `finance`, `programs`)

```mermaid
erDiagram
    organization_department ||--o{ operations_clubtask : owns_task
    events_event ||--o{ operations_clubtask : links_event
    operations_clubtask ||--o{ operations_clubtaskassignee : assigns
    operations_clubtask ||--o{ operations_tasksubmission : submissions
    operations_tasksubmission ||--o{ operations_taskreview : reviews
    events_event ||--o| operations_clubeventprofile : extends
    operations_clubeventprofile ||--o{ operations_eventattendance : rsvp_checkin
    organizing_department ||--o{ organizing_task : legacy_tasks
    events_event ||--o{ organizing_expense : legacy_expenses
    finance_fundcategory ||--o{ finance_financialtransaction : classifies
    organizing_expense ||--o| finance_financialtransaction : bridges_cm03
    operations_clubeventprofile ||--o{ finance_financialtransaction : event_ledger
    organization_department ||--o{ programs_confidentialdocument : vaults
    programs_confidentialdocument ||--o{ programs_documentversion : versions
    programs_confidentialdocument ||--o{ programs_documentaclentry : acl_rules
```

## 4. Mạng xã hội nội bộ, Nhắn tin Mã hóa, Đánh giá & AI (`social`, `evaluations`, `aiassist`)

```mermaid
erDiagram
    organization_department ||--o{ social_socialpost : dept_feed
    social_socialpost ||--o{ social_socialcomment : comments
    social_conversation ||--o{ social_conversationmember : members
    social_conversation ||--o{ social_chatmessage : encrypted_msgs
    social_chatmessage ||--o{ social_chatattachment : vault_files
    evaluations_evaluationcycle ||--o{ evaluations_memberevaluation : reviews
    accounts_user ||--o{ evaluations_memberrecognition : recognizes
    accounts_user ||--o{ notifications_notification : notifies
```
