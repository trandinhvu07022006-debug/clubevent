# Bảng test case và RTM

Mã test case khớp với tên hàm test trong code, để điền RTM (ma trận truy vết
yêu cầu) làm bằng chứng kiểm thử.

Phương pháp: **phân hoạch tương đương** (chia đầu vào thành các nhóm cho kết
quả giống nhau) và **giá trị biên** (thử ở ranh giới, nơi lỗi hay xảy ra).

## M4 - Đăng ký vé (F4.1)

| Mã | Tình huống | Kết quả mong đợi | Hàm test |
|---|---|---|---|
| TC07-1 | Đặt 2 vé, còn 10 chỗ | Thành công, còn 8 chỗ | `test_tc07_1_book_two_tickets_when_seats_available` |
| TC07-2 | Đặt đúng 4 vé (biên trên) | Thành công | `test_tc07_2_book_exactly_the_limit` |
| TC07-3 | Đặt 5 vé (vượt biên) | Báo lỗi, không trừ chỗ | `test_tc07_3_book_over_the_limit_is_rejected` |
| TC07-3b | Đặt 3 vé rồi đặt thêm 2 vé | Báo lỗi (tổng 5 > 4) | `test_tc07_3b_limit_counts_tickets_across_several_bookings` |
| TC07-4 | Đặt 1 vé khi còn đúng 1 chỗ | Thành công, hết chỗ | `test_tc07_4_book_the_last_seat` |
| TC07-5 | Đặt khi còn 0 chỗ | Báo hết chỗ | `test_tc07_5_book_when_sold_out` |
| **TC07-7** | **2 người cùng đặt chỗ cuối** | **Đúng 1 người thành công** | `test_only_one_of_two_concurrent_bookings_succeeds` |
| TC07-8 | Đặt vé miễn phí | Vé ở trạng thái Đã xác nhận | `test_tc07_8_free_ticket_is_confirmed_immediately` |
| TC07-9 | Đặt vé có phí | Vé ở trạng thái Chờ thanh toán | `test_tc07_9_paid_ticket_waits_for_payment` |
| TC07-10 | Sự kiện chưa mở / đã đóng / đã huỷ | Bị chặn | `test_tc07_10_cannot_book_when_event_not_open` |
| TC07-11 | Quá hạn đăng ký | Bị chặn | `test_tc07_11_cannot_book_after_deadline` |
| TC07-12 | Kiểm tra mã vé | Không trùng, không phải ID tăng dần | `test_ticket_codes_are_unique_and_unguessable` |

## M4 - Huỷ vé (F4.3, F4.5)

| Mã | Tình huống | Kết quả mong đợi | Hàm test |
|---|---|---|---|
| TC08-1 | Huỷ vé còn hạn | Chỗ được trả lại | `test_cancel_returns_the_seat` |
| TC08-2 | Huỷ khi còn dưới 24h | Bị chặn | `test_cannot_cancel_within_24h_of_event` |
| TC08-3 | Huỷ vé của người khác | Bị chặn | `test_cannot_cancel_someone_elses_ticket` |
| TC08-4 | Vé chờ thanh toán quá 24h | Tự huỷ, trả lại chỗ | `test_expired_pending_ticket_is_released` |
| TC08-5 | Vé đã xác nhận, đặt lâu rồi | Không bị huỷ | `test_confirmed_ticket_is_not_released` |

## M5 - Check-in (F5.1)

| Mã | Tình huống | Kết quả mong đợi | Hàm test |
|---|---|---|---|
| TC10-1 | Vé đã xác nhận | HỢP LỆ, chuyển Đã check-in | `test_tc10_1_valid_ticket` |
| **TC10-2** | **Quét lại lần 2** | **ĐÃ SỬ DỤNG** | `test_tc10_2_second_scan_reports_used` |
| TC10-3 | Mã không tồn tại | KHÔNG HỢP LỆ | `test_tc10_3_unknown_code` |
| TC10-4 | Vé chưa thanh toán | KHÔNG HỢP LỆ | `test_tc10_4_unpaid_ticket_rejected` |
| TC10-5 | Vé đã huỷ | KHÔNG HỢP LỆ | `test_tc10_5_cancelled_ticket_rejected` |
| TC10-6 | Vé của sự kiện khác | KHÔNG HỢP LỆ | `test_tc10_6_ticket_of_another_event_rejected` |
| TC10-7 | Nhập mã chữ thường, thừa dấu cách | Vẫn hợp lệ | `test_code_is_case_insensitive_and_trimmed` |

## M1 - Phân quyền (F0.1, F1.x)

| Mã | Tình huống | Kết quả mong đợi | Hàm test |
|---|---|---|---|
| TC01-1 | Chưa đăng nhập vào trang cần quyền | Chuyển về trang login | `test_anonymous_is_redirected_to_login` |
| TC01-2 | Thành viên gõ URL tạo sự kiện | 403 Forbidden | `test_member_cannot_open_lead_pages` |
| TC01-3 | TV BTC gõ URL tạo sự kiện | 403 Forbidden | `test_staff_cannot_open_lead_pages` |
| TC01-4 | TV BTC vào trang xác nhận thanh toán | 200 OK | `test_staff_can_open_payment_page` |
| TC01-5 | Trưởng BTC vào trang quản lý tài khoản | 403 (chỉ Admin) | `test_only_admin_can_manage_accounts` |
| TC01-6 | Tài khoản bị khoá, đúng role | 403 Forbidden | `test_locked_account_is_blocked` |
| TC01-7 | Kiểm tra mật khẩu trong DB | Đã băm, không phải chuỗi thô | `test_password_is_hashed` |

## M2 - Máy trạng thái sự kiện (F2.4)

| Mã | Tình huống | Kết quả mong đợi | Hàm test |
|---|---|---|---|
| TC04-1 | Đang chuẩn bị → Mở đăng ký | Hợp lệ | `test_valid_transitions` |
| TC04-2 | Đang chuẩn bị → Đã diễn ra | Bị chặn | `test_invalid_transitions_are_rejected` |
| TC04-3 | Đã huỷ → bất kỳ trạng thái nào | Bị chặn (trạng thái cuối) | `test_cancelled_is_a_final_state` |
| TC04-4 | Kiểm tra điều kiện cho đăng ký | Chỉ khi Mở đăng ký và chưa quá hạn | `test_is_registerable_only_when_open_and_before_deadline` |

## M3 - Công việc BTC (F3.x)

| Mã | Tình huống | Kết quả mong đợi | Hàm test |
|---|---|---|---|
| TC13-1 | Task quá deadline, chưa xong | Tính là quá hạn | `test_overdue_detection` |
| TC13-2 | Task không có deadline | Không bao giờ quá hạn | `test_task_without_deadline_is_never_overdue` |
| TC13-3 | Đánh dấu Xong rồi lùi lại | `done_at` được ghi rồi xoá | `test_done_at_is_set_and_cleared` |
| TC13-4 | BTC khác sửa tiến độ việc không phải của mình | Bị chặn | `test_only_assignee_or_lead_can_update` |
| TC13-5 | 1/4 task xong | Tiến độ = 25% | `test_event_task_progress` |

## M6 - Phản hồi & thống kê (F6.x)

| Mã | Tình huống | Kết quả mong đợi | Hàm test |
|---|---|---|---|
| TC15-1 | Người đã check-in gửi đánh giá | Thành công | `test_checked_in_user_can_submit` |
| TC15-2 | Người không check-in gửi đánh giá | Bị chặn | `test_user_who_did_not_check_in_cannot_submit` |
| TC15-3 | Gửi đánh giá lần 2 | Bị chặn | `test_cannot_submit_twice` |
| TC15-4 | Gửi sau 7 ngày | Bị chặn | `test_cannot_submit_after_window_closes` |
| TC15-5 | Thống kê với 4 vé (1 đã huỷ) | Không tính vé đã huỷ | `test_statistics_are_computed_correctly` |

## Tích hợp AI

Không test nội dung AI sinh ra (mỗi lần một khác, không ổn định). Chỉ test
phần tích hợp, dùng **mock** (giả lập API) để kết quả ổn định và không tốn
quota.

| Mã | Tình huống | Kết quả mong đợi | Hàm test |
|---|---|---|---|
| TCAI-1 | AI trả JSON bọc trong ```json | Parse được | `test_parse_json_wrapped_in_code_fence` |
| TCAI-2 | AI thêm câu dẫn trước JSON | Parse được | `test_parse_json_with_leading_text` |
| TCAI-3 | AI trả JSON hỏng | Báo AIError, không crash | `test_invalid_json_raises_ai_error` |
| TCAI-4 | AI trả `days_before` = 999 hoặc số âm | Kẹp vào khoảng hợp lệ | `test_clamps_days_before_into_valid_range` |
| TCAI-5 | AI trả chữ thay vì số | Không crash | `test_handles_non_numeric_days_before` |
| **TCAI-6** | **API hết quota** | **Dùng danh sách mặc định, không crash** | `test_falls_back_when_api_fails` |
| TCAI-7 | AI trả danh sách rỗng | Fallback | `test_falls_back_when_ai_returns_nothing_usable` |

## Trợ lý tra cứu (rule-based)

| Mã | Tình huống | Kết quả mong đợi | Hàm test |
|---|---|---|---|
| TCBOT-1 | Chuẩn hoá "Còn vé không" | Ra "con ve khong" | `test_removes_vietnamese_diacritics` |
| TCBOT-2 | Chuẩn hoá chữ "đ" | "Đăng ký" ra "dang ky" | `test_handles_letter_d_with_stroke` |
| TCBOT-3 | Hỏi có dấu | Nhận đúng ý định | `test_detects_intent_with_diacritics` |
| TCBOT-4 | Hỏi KHÔNG dấu | Vẫn nhận đúng ý định | `test_detects_intent_without_diacritics` |
| TCBOT-5 | Hỏi ngoài phạm vi | Trả lời gợi ý chủ đề, không bịa | `test_unknown_question_suggests_topics` |
| TCBOT-6 | Hỏi sự kiện sắp tới | Liệt kê đúng sự kiện đang mở | `test_upcoming_events_lists_open_events` |
| TCBOT-7 | Sự kiện đang chuẩn bị | **Không lộ ra** cho người ngoài | `test_upcoming_events_hides_draft_events` |
| TCBOT-8 | Hỏi còn chỗ | Trả về số chỗ đúng với DB | `test_seats_left_reports_real_number` |
| TCBOT-9 | Hết chỗ | Báo "hết chỗ" | `test_seats_left_says_sold_out` |
| TCBOT-10 | Chưa đăng nhập hỏi vé của tôi | Yêu cầu đăng nhập | `test_personal_question_requires_login` |
| **TCBOT-11** | **Hỏi vé của tôi** | **Không lộ vé của người khác** | `test_my_tickets_does_not_leak_other_users_tickets` |
| TCBOT-12 | BTC hỏi việc của tôi | Liệt kê task được giao | `test_my_tasks_for_staff` |
| TCBOT-13 | Có task quá hạn | Đánh dấu QUÁ HẠN | `test_my_tasks_marks_overdue` |
| TCBOT-14 | Thành viên thường hỏi việc | Báo chỉ dành cho BTC | `test_my_tasks_blocked_for_plain_member` |
| TCBOT-15 | Gọi API bằng GET | Từ chối 405 (chỉ nhận POST để bắt buộc kiểm CSRF) | `test_api_rejects_get` |
| TCBOT-16 | Gửi JSON hỏng | Trả 400, không crash | `test_api_handles_broken_json` |

---

## Tổng kết

83 test case, chạy bằng `python manage.py test`. Tất cả đều pass.

Khi điền RTM, mỗi dòng nối: **Yêu cầu (F-x.x) → Use case (UC-xx) → Test case
(TC-xx) → Kết quả**. Cột Test case lấy từ bảng trên, cột Yêu cầu lấy từ tiêu
đề mỗi phần.
