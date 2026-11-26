# PHASE 3 — BÁO CÁO KIỂM TOÁN & HOÀN THIỆN NGHIỆP VỤ KMG (BUSINESS LOGIC REPORT)

**Ngày thực hiện:** 2026-11-26  
**Nhánh làm việc:** `feature/kmg-system-stabilization`  

---

## 1. Kết quả rà soát 6 phân hệ nghiệp vụ

| Phân hệ | Trạng thái | Kết quả kiểm toán & Cải tiến |
|---|---|---|
| **P3.1 Organization & HR** (`organization`, `recruitment`, `pages`) | **VERIFIED** | Cơ cấu Ban, nhiệm kỳ, bổ nhiệm đơn nhiệm (`Appointment.singleton_active_key`), ủy quyền theo gói (`PermissionGrant`), lịch sử thành viên bất biến (`MemberLifecycleEvent`), chuyển Ban và tạm khóa (`SUSPENDED`) được bảo vệ bởi `organization/test_phase1_foundation.py` và `organization/test_bootstrap.py`. |
| **P3.2 Operations** (`operations`, `organizing`, `notifications`) | **VERIFIED** | Vòng đời công việc Kanban, hạn chót, nộp trễ (`is_late`), nghiệm thu chống tự duyệt (`PA-04`), nhắc việc idempotent `T-48h`/`T-12h` và lịch CLB (`ClubEventProfile` + RSVP) hoạt động nhất quán (`operations/test_phase2_operations.py`). |
| **P3.3 Events & Ticketing** (`events`, `registrations`) | **FIXED & VERIFIED** | **Phát hiện & vá lỗ hổng race condition đa hạng vé:** Trước đây `book_tickets()` và `join_waitlist()` chỉ khóa dòng `TicketType`, nên cùng một người dùng gửi song song yêu cầu cho 2 hạng vé khác nhau (VIP & Standard) của cùng một sự kiện có thể vượt trần `MAX_TICKETS_PER_USER_PER_EVENT = 4`. Đã bổ sung khóa hàng `User` (`UserModel.objects.select_for_update().only("pk").get(pk=user.pk)`) trước khi khóa `TicketType` để tuần tự hóa theo từng người dùng mà vẫn giữ 100% song song giữa các sinh viên khác nhau và tránh deadlock với `cancel_ticket` / `promote_from_waitlist`. |
| **P3.4 Finance** (`finance`, `organizing`) | **VERIFIED** | Maker-Checker độc lập (`created_by != approved_by`), sổ cái `CONFIRMED` bất biến, sửa sai qua `ADJUSTMENT`, đồng bộ `organizing.Expense` và chống giả mạo SePay webhook bằng kiểm tra `BANK_ACCOUNT` + số tiền (`registrations/test_features.py`, `finance/test_phase5_finance.py`). |
| **P3.5 Evaluation & Recruitment** (`evaluations`, `recruitment`) | **VERIFIED** | Quy trình tuyển thành viên 1 đợt, duyệt hồ sơ, phỏng vấn/casting, nâng quyền `MEMBER`, cùng đánh giá định kỳ 7 tiêu chí, phản hồi hai chiều (`BE-06`) và vinh danh công khai tách điểm số hoạt động ổn định. |
| **P3.6 Public Portal** (`public_portal`, `pages/services.py`) | **FIXED & VERIFIED** | **Phát hiện & vá rò rỉ số liệu trên `pages/services.py::club_numbers()`:** Trước đây `club_numbers()` đếm toàn bộ `User(is_locked=False)` (gồm cả tài khoản `GUEST`) làm số thành viên, và đếm cả `Ticket(CHECKED_IN)` của sự kiện `INTERNAL` ra trang công khai. Đã sửa để chỉ đếm thành viên chính thức (`ClubMembershipStatus.ACTIVE` hoặc role `MEMBER/STAFF/LEAD`) và chỉ đếm check-in của sự kiện `EventVisibility.PUBLIC`. |

---

## 2. Bằng chứng kiểm thử Phase 3
- `python manage.py test registrations.test_phase3_business_logic pages.tests --settings=config.settings_test`: **Ran 27 tests in 9.348s — OK**.
  - `test_same_user_racing_two_ticket_types_cannot_exceed_per_event_limit` (**VERIFIED**)
  - `test_multiple_students_across_two_ticket_types_never_oversell` (**VERIFIED**: 30/30 VIP + 30/30 Standard)
  - `test_club_numbers_excludes_guests_and_internal_checkins` (**VERIFIED**)
  - `test_waitlist_promotion_consistency_with_expiry_and_cancel` (**VERIFIED**)
