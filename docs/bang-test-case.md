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
| TC01-6 | Tài khoản bị khoá khi đang đăng nhập | Bị đăng xuất ngay, về trang đăng nhập | `test_locked_account_is_blocked` |
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

## Nền tảng thông báo (F7.0)

| Mã | Tình huống | Kết quả mong đợi | Hàm test |
|---|---|---|---|
| T7.0.1 | Gọi notify với template | 1 Notification + 1 mail | `test_notify_creates_notification_and_sends_email` |
| T7.0.2 | User không có email | Có Notification, 0 mail, không lỗi | `test_notify_skips_email_if_user_has_none` |
| T7.0.3 | Backend email ném lỗi | Không crash, Notification tạo | `test_notify_catches_email_exceptions` |
| T7.0.4 | transaction bị rollback | 0 Notification, 0 mail | `test_notify_on_commit_respects_transaction` |

## Quên mật khẩu (F1.4)

| Mã | Tình huống | Kết quả mong đợi | Hàm test |
|---|---|---|---|
| T1.4.1 | Email tồn tại | 1 mail, có link /taikhoan/datlai/ | `test_t141_email_exists` |
| T1.4.2 | Email không tồn tại | 0 mail, cùng trang "đã gửi" | `test_t142_email_not_exists` |
| T1.4.3 | Email của tài khoản bị khoá | 0 mail, cùng trang "đã gửi" | `test_t143_locked_account` |
| T1.4.4 | Mở link, đặt mật khẩu mới | Đăng nhập được bằng mật khẩu mới | `test_t144_reset_password` |
| T1.4.5 | Dùng lại link cũ lần 2 | Báo link không hợp lệ | `test_t145_reuse_token` |
| T1.4.6 | Gửi 6 yêu cầu trong 1 giờ | Chỉ 5 mail | `test_t146_rate_limit` |
| T1.4.7 | Email viết hoa | Vẫn nhận mail | `test_t147_case_insensitive_email` |

## Mã giao dịch nhóm + VietQR (F4.7) - `registrations/test_features.py`

| Mã | Tình huống | Kết quả mong đợi | Hàm test |
|---|---|---|---|
| T4.7.1 | `crc16_ccitt("123456789")` | `"29B1"` | `test_t4_7_1_crc_check_value` |
| T4.7.2 | `tlv("00","01")` | `"000201"` | `test_t4_7_2_tlv` |
| T4.7.3 | Đặt 3 vé một lần | Cả 3 cùng `booking_ref` | `test_t4_7_3_same_ref_in_one_booking` |
| T4.7.4 | Hai lần đặt khác nhau | `booking_ref` khác nhau | `test_t4_7_4_different_bookings_different_refs` |
| T4.7.5 | `confirm_booking` | Mọi vé PENDING của nhóm → CONFIRMED, 1 AuditLog | `test_t4_7_5_confirm_booking_confirms_group` |
| T4.7.6 | Nhóm có 1 vé đã huỷ | Chỉ xác nhận vé còn PENDING | `test_t4_7_6_confirm_booking_skips_cancelled` |
| T4.7.7 | Thiếu `BANK_BIN` | Trang vé render bình thường, không có QR | `test_t4_7_7_my_tickets_renders_without_bank` |
| T4.7.8 | Data migration | Không còn vé nào `booking_ref == ""` | `test_t4_7_8_data_migration_leaves_no_empty_ref` |
| Thủ công | Quét VietQR bằng app ngân hàng thật | App hiện đúng STK, tên, số tiền, nội dung | - (phải thử trước khi demo) |

## Thông báo theo nghiệp vụ (F7.1)

| Mã | Tình huống | Kết quả mong đợi | Hàm test |
|---|---|---|---|
| T7.1.1 | Đặt vé miễn phí | 1 thông báo "đã xác nhận" + 1 mail | `test_t7_1_1_free_booking_notifies` |
| T7.1.2 | Đặt vé có phí | Mail có nội dung CK, số tiền, STK | `test_t7_1_2_paid_booking_email_has_transfer_content` |
| T7.1.3 | BTC xác nhận | Đúng 1 mail cho người đặt | `test_t7_1_3_confirm_payment_notifies_once` |
| T7.1.4 | 3 vé cùng người tự huỷ | Gộp thành 1 thông báo, 1 mail | `test_t7_1_4_expired_grouped_per_user` |
| T7.1.5 | Huỷ sự kiện, 1 người giữ 4 vé | Mỗi người đúng 1 mail | `test_t7_1_5_cancel_event_one_mail_per_user` |
| T7.1.6 | Được giao việc | Chỉ báo khi người phụ trách đổi, không báo tự giao | `test_notify_only_when_assignee_changes_and_not_self` |
| T7.1.7 | Đặt vé lỗi (rollback) | 0 thông báo, 0 mail | `test_no_notification_when_booking_rolls_back` |

## Danh sách chờ (F4.8)

| Mã | Tình huống | Kết quả mong đợi | Hàm test |
|---|---|---|---|
| T4.8.1 | Vào chờ khi còn chỗ | Lỗi "vẫn còn chỗ" | `test_t4_8_1_cannot_wait_when_seats_left` |
| T4.8.2 | Vào chờ 2 lần cùng loại vé | Lần 2 lỗi | `test_t4_8_2_cannot_wait_twice` |
| T4.8.3 | 3 vé + 1 lượt chờ, xin chờ thêm | Lỗi giới hạn | `test_t4_8_3_limit_counts_waiting` |
| T4.8.4 | A, B, C chờ; 1 vé bị huỷ | A được vé, B vị trí 1, C vị trí 2 | `test_t4_8_4_first_in_line_gets_ticket` |
| T4.8.5-6 | Vé có phí cấp cho người chờ rồi hết hạn TT | Vé PENDING có mã GD; hết hạn → B tự được cấp | `test_t4_8_5_and_6_paid_promotion_then_expiry_moves_on` |
| T4.8.7 | Người đầu hàng bị khoá | SKIPPED, người kế tiếp được vé | `test_t4_8_7_locked_user_skipped` |
| T4.8.8 | Người đầu hàng đã đủ 4 vé | SKIPPED, người kế tiếp được vé | `test_t4_8_8_user_with_max_tickets_skipped` |
| T4.8.9 | Huỷ vé sau hạn đăng ký | Không cấp cho ai | `test_t4_8_9_no_promotion_after_deadline` |
| T4.8.10 | Huỷ sự kiện | Mọi lượt chờ → CANCELLED, có thông báo | `test_t4_8_10_cancel_event_cancels_waitlist` |
| T4.8.11 | `sold` sau mọi kịch bản | Bằng số vé còn hiệu lực thật | `assert_sold_consistent` (gọi trong các test trên) |
| T4.8.12 | 2 luồng cùng huỷ vé đồng thời | Chưa tự động hoá - chạy thủ công trên MySQL | - |

## Hạn thanh toán (B2), check-in (F5.3, F5.4)

| Mã | Tình huống | Kết quả mong đợi | Hàm test |
|---|---|---|---|
| B2.1 | Đặt vé 2 giờ trước giờ diễn ra | Hạn TT không vượt giờ diễn ra | `test_b2_deadline_capped_at_event_start` |
| B2.2 | Chạy dọn sau giờ diễn ra | Vé PENDING bị huỷ dù chưa đủ 24h | `test_b2_expired_after_event_start_even_if_under_24h` |
| T5.3.6 | Body không phải JSON object | 400, `result=INVALID` | `test_t5_3_6_scan_non_object_json_is_400` |
| T5.4.1 | Tiến độ sau check-in | `done/total`, theo loại vé, lượt gần nhất | `test_t5_4_1_progress_by_type_and_recent` |
| T5.4.2 | Thành viên gọi API tiến độ | 403 | `test_t5_4_2_member_blocked` |

## Nhắc lịch (F7.2) - `events/test_features.py`

| Mã | Tình huống | Kết quả mong đợi | Hàm test |
|---|---|---|---|
| T7.2.1 | Sự kiện sau 20h | Được nhắc | `test_t7_2_1_event_in_20h_is_reminded` |
| T7.2.2 | Sự kiện sau 30h | Chưa nhắc | `test_t7_2_2_event_in_30h_not_yet` |
| T7.2.3 | Chạy lệnh 2 lần | Chỉ 1 lượt mail | `test_t7_2_3_run_twice_sends_once` |
| T7.2.4 | Vé PENDING | Không nhắc | `test_t7_2_4_pending_ticket_not_reminded` |
| T7.2.5 | Người có 3 vé | 1 mail | `test_t7_2_5_three_tickets_one_mail` |

## Chuông thông báo (F7.3) - `notifications/test_views.py`

| Mã | Tình huống | Kết quả mong đợi | Hàm test |
|---|---|---|---|
| T7.3.1 | 12 thông báo chưa đọc | Badge hiện "9+" | `test_t7_3_1_badge_count` |
| T7.3.2 | Mở thông báo của người khác | 404 | `test_t7_3_2_open_other_users_notification_404` |
| T7.3.3 | `url="https://evil.com"` | Không chuyển ra ngoài | `test_t7_3_3_no_open_redirect` |
| T7.3.4 | Khách vào trang chủ | Không truy vấn bảng thông báo | `test_t7_3_4_guest_home_no_notification_queries` |

## File lịch .ics (F7.4), danh mục (F2.5)

| Mã | Tình huống | Kết quả mong đợi | Hàm test |
|---|---|---|---|
| T7.4.1 | Xuống dòng | CRLF | `test_t7_4_1_crlf` |
| T7.4.2 | Tên có `,` `;` | Được thoát | `test_t7_4_2_escape_comma_semicolon` |
| T7.4.3 | Tiếng Việt dài | Không dòng nào > 75 byte, giải mã UTF-8 được | `test_t7_4_3_lines_max_75_bytes_and_utf8` |
| T7.4.4 | Bản nháp, khách tải | 404 | `test_t7_4_4_draft_hidden_from_guest` |
| T2.5.1 | Lọc `category` | Đúng sự kiện | `test_filter_category` |
| T2.5.2 | Kết hợp `category` + `status` + `q` | Đúng giao | `test_combine_three_params` |
| T2.5.3 | Tham số lạ | Bỏ qua, không lỗi | `test_unknown_params_ignored` |
| B4 | Giờ kết thúc trước giờ bắt đầu | Form báo lỗi | `test_ends_before_start_rejected` |

## Lịch sử tham gia & chứng nhận (F8.1, F8.2)

| Mã | Tình huống | Kết quả mong đợi | Hàm test |
|---|---|---|---|
| T8.1.1 | Hồ sơ người có 2 vé check-in cùng sự kiện | Hiện 1 dòng | `test_t8_1_profile_history` |
| T8.2.1 | Chưa check-in | 404 | `test_t8_2_1_not_checked_in_404` |
| T8.2.2 | Sự kiện chưa DONE | 404 | `test_t8_2_2_event_not_done_404` |
| T8.2.3 | Token đúng | Xác thực OK | `test_t8_2_3_valid_token` |
| T8.2.4 | Sửa 1 ký tự token | "Không xác thực được" | `test_t8_2_4_tampered_token` |
| T8.2.5 | Trang xác thực | Không có email/SĐT, MSSV đã che | `test_t8_2_5_public_page_minimal_data` |

## Ngân sách sự kiện

| Mã | Tình huống | Kết quả mong đợi | Hàm test |
|---|---|---|---|
| NS.1 | Thu/chi/lãi lỗ | Thu = vé đã xác nhận + check-in | `test_summary` |
| NS.2 | Thành viên vào trang ngân sách | 403 | `test_member_forbidden` |
| NS.3 | Trưởng BTC thêm/xoá khoản chi, xuất CSV | Chạy đúng | `test_lead_crud_and_csv` |

## Rà soát chất lượng - lỗi hồi quy (`core/test_quality.py`)

| Mã | Lỗi đã sửa | Kết quả mong đợi | Hàm test |
|---|---|---|---|
| QA-1 | Thống kê tổng hợp nhân số liệu khi JOIN vé × phản hồi × công việc (code cũ báo 36 thay vì 3) | Số vé, doanh thu, số phản hồi đúng | `test_counts_not_multiplied_by_feedback_and_tasks` |
| QA-2 | Thống kê tổng hợp lệch thống kê từng sự kiện | Hai nơi ra cùng con số | `test_dashboard_matches_event_statistics` |
| QA-3 | Tài khoản bị khoá vẫn dùng được phiên đang mở | Bị đăng xuất, không đặt vé được | `test_locked_member_is_logged_out_on_next_request` |
| QA-4 | Huỷ vé bằng GET (CSRF qua đường link) | 405, vé không đổi | `test_cancel_ticket_get_405` |
| QA-5 | Xác nhận TT, đổi trạng thái việc, AI tóm tắt, xoá loại vé bằng GET | 405 | `test_other_mutations_get_405` |
| QA-6 | Admin tự đổi vai trò của mình | Bị chặn | `test_admin_cannot_change_own_role` |
| QA-7 | MSSV trùng khác hoa/thường | Bị chặn | `test_mssv_duplicate_case_insensitive` |
| QA-8 | Ảnh đại diện không giới hạn dung lượng | > 2 MB bị từ chối | `test_avatar_over_2mb_rejected` |
| QA-9 | Sức chứa nhỏ hơn tổng số vé | Form báo lỗi | `test_capacity_below_ticket_quota_rejected` |
| QA-10 | Thêm loại vé cho sự kiện đã diễn ra (chỉ ẩn nút) | Server chặn | `test_cannot_add_ticket_type_to_done_event` |
| QA-11 | API trợ lý nhận JSON không phải object → 500 | 400 | `test_non_object_json_is_400` |

---

## Tổng kết

200 test, chạy bằng `python manage.py test`. Tất cả đều pass.

Khi điền RTM, mỗi dòng nối: **Yêu cầu (F-x.x) → Use case (UC-xx) → Test case
(TC-xx) → Kết quả**. Cột Test case lấy từ bảng trên, cột Yêu cầu lấy từ tiêu
đề mỗi phần.
