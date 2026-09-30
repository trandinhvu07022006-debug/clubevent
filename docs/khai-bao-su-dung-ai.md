# Khai báo sử dụng công cụ AI trong quá trình phát triển

Tài liệu này ghi lại **trung thực** những phần của dự án được viết hoặc sửa với
sự hỗ trợ của công cụ AI, để giảng viên đánh giá đúng phần đóng góp của nhóm.

> Nhóm cần kiểm tra quy định của môn học về việc dùng AI và bổ sung mục 3
> trước khi nộp.

---

## 1. Công cụ

| Công cụ | Dùng để làm gì |
|---|---|
| Claude (Anthropic), qua Claude Code trong VS Code | Viết code, viết test, rà lỗi, viết tài liệu (phiên ngày 30/09/2026, chi tiết ở mục 2) |
| Gemini / OpenAI (tích hợp **trong sản phẩm**) | Chức năng AI gợi ý công việc và tóm tắt phản hồi — là tính năng của hệ thống, không phải công cụ viết code |

## 2. Phiên làm việc với Claude Code — 30/09/2026

Nhóm giao yêu cầu: "đánh giá trang web còn thiếu gì, làm cho đầy đủ", sau đó
yêu cầu thêm chức năng giao việc cho Ban chủ nhiệm và kiểm thử theo vai người
dùng. Mọi commit do AI tạo đều có dòng `Co-Authored-By: Claude`.

### 2.1. Chức năng mới do AI viết

Viết theo đặc tả có sẵn trong `docs/ke-hoach-chuc-nang.md` (tài liệu kế hoạch
của nhóm), Sprint 3–5:

| Mã | Chức năng | File chính |
|---|---|---|
| F4.7 | Mã giao dịch nhóm + VietQR, xác nhận thanh toán theo nhóm | `registrations/vietqr.py`, `registrations/services.py` |
| F7.1 | Thông báo + email theo nghiệp vụ | `registrations/services.py`, `events/services.py`, `organizing/services.py`, `templates/emails/notice.*` |
| F4.8 | Danh sách chờ tự cấp vé | `registrations/services.py` (`join_waitlist`, `promote_from_waitlist`…) |
| F5.4 | Tiến độ check-in theo loại vé, lượt vừa vào | `registrations/services.py::checkin_progress_data` |
| F7.2 | Nhắc lịch 24h, lệnh `run_periodic` | `events/services.py`, `events/management/commands/` |
| F7.3 | Chuông thông báo trong app | `notifications/views.py`, `templates/base.html` |
| F7.4 | File lịch `.ics` + giờ kết thúc sự kiện | `events/services.py::event_ics` |
| F2.5 | Danh mục sự kiện, lọc kết hợp, lịch tháng | `events/views.py`, `templates/events/list.html`, `calendar.html` |
| F8.1–F8.2 | Lịch sử tham gia, giấy chứng nhận + trang xác thực | `events/services.py`, `templates/events/certificate*.html` |
| (GĐ 3) | Ngân sách sự kiện (khoản chi, thu–chi, CSV) | `organizing/models.py::Expense`, `templates/organizing/budget.html` |
| (mới) | Ban chủ nhiệm giao việc, việc chung CLB, mức ưu tiên, "Tôi đã giao" | `organizing/views.py::task_assign`, `templates/organizing/assign.html` |
| — | In vé / lưu PDF, chia sẻ sự kiện, trang "Vé của tôi" chia tab | `templates/registrations/ticket_print.html`, `my_tickets.html` |

### 2.2. Lỗi có sẵn do AI phát hiện và sửa

| Lỗi | Mức độ |
|---|---|
| Trang check-in lỗi 500 (thiếu `{% load static %}`) | Nghiêm trọng — chức năng cốt lõi không dùng được |
| XSS ở `qr-scan.js` (chèn tên người dùng vào `innerHTML`) | Bảo mật |
| Xoá công việc bằng GET; open redirect qua tham số `next` | Bảo mật |
| CSV chèn BOM ở mỗi dòng, giờ hiển thị theo UTC | Dữ liệu sai |
| SQLite: người đặt vé sau gặp "database is locked" thay vì "hết chỗ" | Demo race condition hỏng (đã đo 10/10 lần) |
| Thiếu `CSRF_TRUSTED_ORIGINS` (qua ngrok HTTPS mọi form bị 403) | Demo camera hỏng |
| API quét mã nhận body không phải JSON object → 500 | Độ bền |
| 2 lỗi chỉ xảy ra trên MySQL (bulk_create không trả id; lọc theo tháng cần bảng múi giờ) | Sẽ hỏng khi chạy MySQL |
| Giấy chứng nhận ghi "truy cập đường dẫn" nhưng không in đường dẫn | Tìm ra khi kiểm thử theo vai |

### 2.3. Test và tài liệu do AI viết

- Test mới: `registrations/test_features.py`, `registrations/test_seed.py`,
  `events/test_features.py`, `notifications/test_views.py`,
  `organizing/test_assign.py` (từ 118 lên 213 test).
- Kịch bản kiểm thử theo vai người dùng qua HTTP (69 bước) — chạy ngoài repo.
- Cập nhật `README.md`, `docs/bang-test-case.md`, `docs/huong-dan-deploy.md`,
  `docs/kich-ban-demo.md`; viết `docs/giai-thich-code.md` và tài liệu này.

### 2.4. Phần KHÔNG do phiên này viết

- Toàn bộ code, thiết kế và tài liệu có trong Git trước ngày 30/09/2026 (nhóm
  tự khai ở mục 3 nếu có dùng AI).
- Các thay đổi chưa commit trong `aiassist/` và `static/js/chatbot.js` đã có sẵn
  trước phiên này (được commit riêng, ghi rõ trong nội dung commit).
- Tài liệu kế hoạch `docs/ke-hoach-chuc-nang.md` là đặc tả AI làm theo.

## 3. Các lần dùng AI trước đó — NHÓM TỰ ĐIỀN

| Ngày | Công cụ | Phần việc | Người dùng |
|---|---|---|---|
| | | | |

## 4. Nhóm đã làm gì để hiểu và kiểm soát phần AI viết

*(Nhóm tự điền, ví dụ: đã đọc `docs/giai-thich-code.md`, mỗi người chạy lại
test và kịch bản demo của module mình, tự trả lời được các câu hỏi bảo vệ.)*
