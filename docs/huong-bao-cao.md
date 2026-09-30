# Hướng viết báo cáo — Hệ thống hỗ trợ tổ chức sự kiện CLB (KMG Club)

Khung báo cáo cho môn **Công nghệ phần mềm**. Mỗi chương ghi: nên viết gì,
**lấy minh chứng ở đâu trong repo**, và lỗi hay mắc. Nguyên tắc chung:

1. **Báo cáo phải khớp sản phẩm.** Giảng viên mở web và Git song song với báo cáo.
2. **Mỗi khẳng định đi kèm bằng chứng**: số liệu đo được, ảnh chụp, mã test, commit.
3. **Viết thật**, kể cả phần chưa làm được và phần dùng AI.

Độ dài gợi ý: 40–60 trang (không tính phụ lục).

---

## Chương 1. Giới thiệu và khảo sát (4–6 trang)

- Bối cảnh: CLB quản lý sự kiện bằng Google Form + Excel + Zalo → rời rạc,
  không chống được bán vượt chỗ, không biết ai đã đến.
- Kết quả khảo sát thành viên (số người, câu hỏi, biểu đồ) — nhóm có số liệu
  khảo sát trong kịch bản demo ("khảo sát 40 thành viên").
- So sánh với giải pháp có sẵn (Google Form, Ticketbox, Luma): vì sao tự làm —
  cần phân công BTC, check-in, thống kê cho CLB, miễn phí, không phụ thuộc mạng ngoài.
- Mục tiêu, phạm vi, **những gì KHÔNG làm** (cổng VNPay/MoMo, app di động —
  lấy từ mục 11 `docs/ke-hoach-chuc-nang.md`).

## Chương 2. Quy trình phát triển (3–5 trang)

- Mô hình: Incremental / Scrum theo Sprint (Sprint 1–5 trong kế hoạch).
- Bảng Sprint: mục tiêu, chức năng, thời gian. Nguồn: mục 2–3 `docs/ke-hoach-chuc-nang.md`.
- Công cụ: Git + GitHub (nhánh `feature/…`, Pull Request), VS Code, Claude Code.
- **Viết đúng thực tế Git**: nếu phần lớn commit từ một tài khoản, giải thích
  lý do (ví dụ gộp code cuối kỳ) và nêu cách đã khắc phục (nhánh + PR từ
  `feature/sprint3-5-hoan-thien`). Đừng mô tả quy trình mà Git không chứng minh được.
- Phân công theo bảng mục 7 `README.md` + phần trăm đóng góp thật.

## Chương 3. Phân tích yêu cầu — SRS (8–12 trang)

- Tác nhân: Khách, Thành viên, Thành viên BTC, Trưởng BTC, Admin (Ban chủ nhiệm).
- **Danh sách yêu cầu chức năng có mã** M1–M8 / F0.x–F8.x (giữ đúng mã trong
  `docs/bang-test-case.md` để RTM khớp). Bổ sung các chức năng mới: F4.7 VietQR,
  F4.8 danh sách chờ, F7.x thông báo, F2.5 danh mục, F8.x chứng nhận, ngân
  sách, giao việc của Ban chủ nhiệm.
- Sơ đồ Use Case tổng quát + đặc tả chi tiết 4–6 use case quan trọng:
  **UC07 Đặt vé**, **UC10 Check-in**, Vào danh sách chờ, Xác nhận thanh toán
  theo nhóm, Giao việc, Xác thực chứng nhận.
  Mỗi đặc tả: tiền điều kiện, luồng chính, luồng thay thế, hậu điều kiện.
- Quy tắc nghiệp vụ (bảng mục 5 `README.md`): 4 vé/người, hạn thanh toán
  min(24h, giờ diễn ra), huỷ trước 24h, đánh giá trong 7 ngày.
- Yêu cầu phi chức năng: bảo mật, hiệu năng, khả dụng khi mất mạng ngoài
  (no-CDN), tương thích điện thoại, giao diện sáng/tối.

## Chương 4. Thiết kế (10–14 trang)

- **Kiến trúc 3 tầng** View – Service – Model (lý do: mục 1 `docs/giai-thich-code.md`).
- **Sơ đồ lớp / ERD**: User, Event, TicketType, Ticket, WaitlistEntry, Task,
  Expense, Feedback, FeedbackSummary, Notification, AuditLog. Lấy trực tiếp từ
  các file `*/models.py`.
- **Sơ đồ trạng thái** (4 máy trạng thái):
  - Sự kiện: Đang chuẩn bị → Mở đăng ký → Đóng đăng ký → Đã diễn ra / Đã huỷ
    (`events/models.py::ALLOWED_TRANSITIONS`).
  - Vé: Chờ thanh toán → Đã xác nhận → Đã check-in / Đã huỷ.
  - Lượt chờ: Đang chờ → Đã có vé / Bỏ qua / Đã rời / Hết hạn.
  - Công việc: Chưa làm ⇄ Đang làm ⇄ Xong.
- **Sơ đồ tuần tự** cho 3 luồng đáng giá nhất:
  1. Đặt vé có khoá dòng (2 người cùng đặt chỗ cuối).
  2. Huỷ vé → cấp vé tự động cho người đầu danh sách chờ.
  3. Đặt vé → commit → gửi thông báo (vì sao `on_commit`).
- Thiết kế giao diện: ảnh chụp các màn chính (sáng + tối, máy tính + điện thoại),
  nguyên tắc token màu và vùng chạm 44px (`static/css/app.css` mục 1, 13).
- Thiết kế bảo mật: bảng mục 11 `docs/giai-thich-code.md`.

## Chương 5. Cài đặt (5–8 trang)

- Công nghệ: Django 5, SQLite/MySQL, Bootstrap 5 self-host, Chart.js, qrcode,
  jsQR, Gemini/OpenAI (có fallback khi AI lỗi).
- **Trích đoạn code ngắn** kèm giải thích (tối đa 15–20 dòng mỗi đoạn):
  `book_tickets` (khoá dòng), `promote_from_waitlist`, `notify_on_commit`,
  `vietqr_payload` + CRC, `cert_token`.
- Xử lý các vấn đề kỹ thuật thật đã gặp (rất nên viết — thể hiện chiều sâu):
  - SQLite "database is locked" → `transaction_mode=IMMEDIATE` (đo 10/10 lần).
  - MySQL `bulk_create` không trả id → tạo vé từng cái.
  - JOIN nhiều bảng nhân số liệu thống kê (36 thay vì 3) → gom nhóm từng bảng.
  - Camera chỉ chạy trên HTTPS → ngrok + ô nhập mã dự phòng.

## Chương 6. Kiểm thử (6–10 trang) — chương dễ ghi điểm nhất

| Loại kiểm thử | Số liệu | Nguồn |
|---|---|---|
| Unit + integration test | **233 test, 100% pass** | `python manage.py test` |
| Độ phủ code | **86%** | `coverage run manage.py test` + `coverage report` |
| Race condition | 2 người đặt chỗ cuối, **10/10 lần đúng** | `RaceConditionTests` + đo trên file SQLite |
| Kiểm thử theo vai người dùng qua HTTP | **69/69 bước đạt**, 6 vai | kịch bản UAT (Khách, Thành viên, BTC, Trưởng BTC, Admin, Hệ thống) |
| Kiểm thử bảo mật | Vượt quyền, IDOR, CSRF qua GET, open redirect, XSS | `core/test_quality.py`, `notifications/test_views.py` |
| Hiệu năng truy vấn | Không có N+1; 5–21 truy vấn cố định mỗi trang | đo bằng `CaptureQueriesContext` |

- Phương pháp thiết kế test: phân hoạch tương đương, giá trị biên (TC07-2/3:
  đúng 4 vé / 5 vé).
- **Bảng test case + RTM**: chép từ `docs/bang-test-case.md`, nối
  Yêu cầu → Use case → Test case → Kết quả.
- **Lỗi tìm được nhờ kiểm thử** (bảng QA-1…QA-11 và các lỗi trong
  `docs/khai-bao-su-dung-ai.md` mục 2.2): mô tả lỗi, cách phát hiện, cách sửa,
  test hồi quy. Đây là bằng chứng kiểm thử có tác dụng thật.
- Kiểm thử thủ công còn lại: camera trên điện thoại thật, quét VietQR bằng app
  ngân hàng, chạy trên MySQL. Ghi rõ đã làm hay chưa.

## Chương 7. Triển khai (2–3 trang)

- Tóm tắt `docs/huong-dan-deploy.md`: PythonAnywhere, biến môi trường,
  `run_periodic` mỗi 15 phút, email SMTP, sao lưu dữ liệu.
- Link sản phẩm thật (nếu đã deploy) + tài khoản demo.

## Chương 8. Đánh giá và bài học (3–4 trang) — đừng bỏ qua

- Đã đạt: bảng chức năng so với kế hoạch (làm được / chưa làm).
- **Chưa tốt và nguyên cứu** — viết thật:
  - Có lỗi lọt vào nhánh chính (trang check-in lỗi 500, XSS) vì chưa chạy test
    trước khi commit và chưa có review.
  - Commit gộp, nội dung commit chưa mô tả đúng.
- Cách đã khắc phục: bộ test tự động, kiểm thử theo vai, nhánh + Pull Request,
  rà soát bảo mật.
- **Sử dụng AI**: tóm tắt từ `docs/khai-bao-su-dung-ai.md` — công cụ, phần AI
  làm, phần nhóm tự làm, cách nhóm kiểm soát và hiểu code AI viết.
- Hướng phát triển (chỉ liệt kê, không làm): điểm rèn luyện, tự xác nhận
  chuyển khoản qua webhook, PWA check-in khi mất mạng, nền tảng nhiều CLB.

## Phụ lục

- A. Hướng dẫn cài đặt (từ `README.md`).
- B. Bảng test case đầy đủ.
- C. Kịch bản demo (`docs/kich-ban-demo.md`).
- D. Khai báo sử dụng AI.

---

## Ảnh chụp nên có

Trang chủ + bộ lọc danh mục · Lịch tháng · Chi tiết sự kiện (hết vé, nút danh
sách chờ) · Vé của tôi (khối Cần thanh toán có VietQR) · Xác nhận thanh toán
theo nhóm · Check-in (3 màu kết quả) · Chuông thông báo · Giao việc + "Tôi đã
giao" · Ngân sách · Giấy chứng nhận + trang xác thực · Thống kê tổng hợp ·
2–3 màn trên điện thoại · 2–3 màn chế độ tối · Màn hình 233 test pass ·
Báo cáo coverage · Git log / Pull Request.

## Lỗi hay mắc khi viết

- Sơ đồ vẽ theo ý tưởng ban đầu, không khớp code cuối cùng → vẽ lại từ `models.py`.
- Chép nguyên code dài vào báo cáo → chỉ trích đoạn cốt lõi, phần còn lại trỏ tới file.
- Chỉ ghi "đã test kỹ" → luôn kèm con số và mã test.
- Giấu phần chưa làm hoặc phần dùng AI → giảng viên hỏi ra sẽ mất điểm nặng hơn.
