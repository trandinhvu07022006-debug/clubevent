# Khai báo sử dụng công cụ AI trong quá trình phát triển

Tài liệu này ghi **trung thực** vai trò của nhóm và phần việc có dùng công cụ
AI, để giảng viên đánh giá đúng đóng góp của từng bên. Mọi commit có AI tham
gia đều mang dòng `Co-Authored-By: Claude` trong Git.

---

## 1. Vai trò của nhóm

AI là công cụ thực hiện; **bài toán, đặc tả, quyết định và kiểm chứng là của
nhóm**. Cụ thể:

### 1.1. Xác định bài toán và đặc tả

- Khảo sát nhu cầu CLB, xác định phạm vi và những gì không làm (Chương 1 báo cáo).
- Viết tài liệu kế hoạch `docs/ke-hoach-chuc-nang.md`: danh sách chức năng có
  mã (F0.x–F8.x), quy tắc nghiệp vụ (4 vé/người, hạn thanh toán, huỷ trước
  24h…), thứ tự Sprint. **AI viết code theo đặc tả này**, không tự đặt ra yêu cầu.
- Thiết kế mô hình dữ liệu, máy trạng thái vé và sự kiện.

### 1.2. Ra quyết định kỹ thuật và nghiệp vụ

- Chọn tự xác nhận thanh toán qua webhook ngân hàng thay vì cổng VNPay/MoMo;
  chọn dịch vụ SePay sau khi so sánh chi phí và hạn mức miễn phí.
- Quyết định quy tắc chuyển thiếu tiền: không xác nhận, ghi nhật ký cho BTC.
- Quyết định dữ liệu demo, khôi phục thông tin gốc của sự kiện Minishow Tròn.
- Duyệt hoặc từ chối từng thay đổi AI đề xuất trước khi đưa lên Git.

### 1.3. Triển khai, cấu hình và kiểm thử thực tế

Những việc này AI không làm thay được:

- Đăng ký SePay, liên kết tài khoản ngân hàng, cấu hình webhook (URL, loại
  giao dịch, xác thực API Key).
- Cài và cấu hình ngrok để webhook truy cập được từ Internet.
- **Kiểm thử bằng giao dịch thật** ngày 01/10/2026: quét VietQR bằng app ngân
  hàng và ví MoMo, chuyển tiền, đối chiếu lịch sử giao dịch MB với nhật ký hệ
  thống (2 giao dịch, vé tự xác nhận sau ~5 giây).
- Xử lý sự cố bảo mật: phát hiện khoá bị lộ trong lúc trao đổi và tự đổi
  (rotate) khoá SePay, authtoken ngrok.
- Chạy toàn bộ test, đo độ phủ, chụp minh chứng cho báo cáo.

### 1.4. Phân công và trách nhiệm từng thành viên

Mỗi module có một người làm chủ: nắm yêu cầu, duyệt code (kể cả phần AI hỗ
trợ), chạy test, demo và trả lời câu hỏi về module đó. Khớp bảng phân công
mục 7 `README.md`.

| Thành viên | Phụ trách | Phần AI hỗ trợ trong module | Trách nhiệm kiểm tra và bảo vệ |
|---|---|---|---|
| Trần Đình Vũ (leader) | Quản lý dự án, đặc tả, review, deploy; trợ lý AI; thanh toán | Webhook SePay, VietQR | Cấu hình SePay + ngrok, kiểm thử bằng giao dịch thật, xử lý khoá bị lộ, duyệt toàn bộ thay đổi trước khi lên Git |
| Trần Quốc Huy | `accounts/`: tài khoản, phân quyền, nhật ký thao tác; bảo mật | Sửa lỗi open redirect | Kiểm tra phân quyền 5 vai, các test bảo mật (vượt quyền, CSRF, XSS) |
| Trần Xuân Tiến | `events/`: sự kiện, danh mục, lịch, chứng nhận | Danh mục, lịch tháng, `.ics`, nhắc lịch, chứng nhận | Kiểm tra máy trạng thái sự kiện, quy trình cấp và xác thực chứng nhận |
| Trần Văn Tùng | `registrations/`: đặt vé, huỷ vé, danh sách chờ, check-in | Mã giao dịch nhóm, danh sách chờ, tiến độ check-in | Kiểm thử race condition chỗ cuối (10/10 lần), check-in 3 trạng thái |
| Hoàng Mạnh Cường | `organizing/`, `feedback/`, `notifications/` | Giao việc Ban chủ nhiệm, ngân sách, thông báo + email | Kiểm tra luồng giao việc, thu chi ngân sách, thông báo đúng người |
| Nguyễn Văn Nam | `templates/`, `static/`; bảng test case, dữ liệu demo | Sửa lỗi XSS ở `qr-scan.js`, test mới | Kiểm tra giao diện điện thoại và chế độ tối, đối chiếu bảng test case với kết quả chạy |

---

## 2. Công cụ AI đã dùng

| Công cụ | Dùng để làm gì |
|---|---|
| Claude (Anthropic), qua Claude Code trong VS Code | Viết code và test theo đặc tả của nhóm, rà lỗi, viết tài liệu |
| Gemini / OpenAI (tích hợp **trong sản phẩm**) | Tính năng gợi ý công việc và tóm tắt phản hồi của hệ thống, không phải công cụ viết code |

## 3. Phần việc có AI tham gia

### 3.1. Phiên 30/09/2026

Nhóm giao yêu cầu đánh giá web còn thiếu gì và làm đầy đủ theo kế hoạch
Sprint 3–5, thêm chức năng giao việc cho Ban chủ nhiệm, kiểm thử theo vai.

**Chức năng AI viết theo đặc tả của nhóm:**

| Mã | Chức năng |
|---|---|
| F4.7 | Mã giao dịch nhóm + VietQR, xác nhận thanh toán theo nhóm |
| F4.8 | Danh sách chờ tự cấp vé |
| F5.4 | Tiến độ check-in theo loại vé |
| F7.1–F7.4 | Thông báo + email nghiệp vụ, nhắc lịch, chuông thông báo, file `.ics` |
| F2.5 | Danh mục sự kiện, lọc kết hợp, lịch tháng |
| F8.1–F8.2 | Lịch sử tham gia, giấy chứng nhận + trang xác thực |
| (GĐ 3) | Ngân sách sự kiện |
| (mới) | Ban chủ nhiệm giao việc, việc chung CLB, mức ưu tiên |

**Lỗi có sẵn AI phát hiện và sửa:** trang check-in lỗi 500; XSS ở `qr-scan.js`;
xoá công việc bằng GET và open redirect; CSV lỗi BOM, giờ hiển thị UTC; SQLite
"database is locked" khi đặt chỗ cuối; thiếu `CSRF_TRUSTED_ORIGINS`; API quét
mã lỗi 500 với dữ liệu sai; 2 lỗi chỉ xảy ra trên MySQL; giấy chứng nhận thiếu
đường dẫn xác thực.

**Test và tài liệu:** test mới cho các chức năng trên (từ 118 lên 213 test);
cập nhật README, bảng test case, hướng dẫn deploy, kịch bản demo; viết
`docs/giai-thich-code.md`.

### 3.2. Phiên 01/10/2026

| Việc | Ai làm |
|---|---|
| Quyết định tích hợp tự xác nhận thanh toán, chọn SePay | Nhóm |
| Code webhook `/ve/thanhtoan/webhook/sepay/` và 6 test | AI |
| Đăng ký SePay, liên kết ngân hàng, cấu hình webhook, ngrok | Nhóm |
| Giao dịch thật để kiểm thử, đối chiếu lịch sử ngân hàng | Nhóm |
| Ẩn QR check-in với vé chưa thanh toán | AI, theo phản hồi của nhóm khi thử giao diện |
| Làm gọn dữ liệu demo, khôi phục Minishow Tròn | AI, theo yêu cầu của nhóm |
| Đổi khoá bị lộ, chặn file sao lưu khỏi Git | Nhóm quyết định, AI hỗ trợ thao tác |
| Chụp ảnh minh hoạ web | AI chụp tự động; nhóm chụp ảnh terminal và app ngân hàng |

Lỗi do AI gây ra và được test bắt: khi thêm webhook, AI vô tình làm mất
`@require_POST` của nút xác nhận tay; test bảo mật `GetMustNotChangeDataTests`
báo lỗi, đã sửa trước khi commit.

### 3.3. Phiên 02/10/2026 (đợt 7: chống gom vé)

| Việc | Ai làm |
|---|---|
| Đề xuất xác minh OTP để chặn gom vé bằng nhiều tài khoản | Nhóm |
| Code xác minh email bằng OTP (F1.7) và một hộp thư một tài khoản (F1.8) | AI |
| Cấu hình Gmail SMTP (App Password), thử nhận mã ở hộp thư thật | Nhóm, AI hỗ trợ thao tác |
| Chỉ ra OTP email vẫn bị vượt bằng nhiều tài khoản Gmail ảo | Nhóm |
| Đề xuất vé ghi danh (F5.5) và chuyển nhượng vé (F4.10) | AI đề xuất, nhóm duyệt |
| Code vé ghi danh, chuyển nhượng vé và 39 test mới | AI |
| Báo lỗi "bấm Gửi lại mã không có thư mới" khi dùng thử | Nhóm (AI sửa) |
| Cập nhật báo cáo, chụp ảnh minh hoạ, đo lại số test và độ phủ | AI, theo yêu cầu của nhóm |

Lỗi do AI gây ra và được test bắt: bản đầu của hàm kiểm tra mã OTP ném lỗi bên
trong `@transaction.atomic`, nên số lần nhập sai bị rollback và kẻ dò mã được
thử vô hạn. Test `test_wrong_code_counts_attempts_then_burns` báo lỗi ngay lần
chạy đầu, đã sửa trước khi commit.

## 4. Nhóm kiểm soát phần AI viết như thế nào

- Mọi thay đổi chỉ vào Git khi **toàn bộ test đạt** (hiện 373 test).
- Chức năng thanh toán được kiểm chứng bằng **giao dịch thật**, không chỉ test tự động.
- Mỗi thành viên chạy lại test và kịch bản demo của module mình, đọc
  `docs/giai-thich-code.md` và tự trả lời các câu hỏi bảo vệ trong đó.
