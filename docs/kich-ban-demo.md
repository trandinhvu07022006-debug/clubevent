# Kịch bản demo (khoảng 8 phút)

## Chuẩn bị trước khi vào phòng

1. Chạy trên **MySQL**, không dùng SQLite. Phần chống race condition chỉ
   thể hiện đúng trên MySQL.
2. Nạp lại dữ liệu sạch: `python manage.py seed_demo --reset`
3. Mở sẵn **2 trình duyệt**: một cửa sổ thường và một cửa sổ ẩn danh, để đăng
   nhập 2 tài khoản cùng lúc.
4. Điện thoại mở sẵn trang check-in. Nếu cần vào từ điện thoại, chạy
   `python manage.py runserver 0.0.0.0:8000` rồi truy cập theo IP máy, hoặc
   dùng ngrok.
5. **Dự phòng:** máy thứ 2 đã cài sẵn project, và một video quay đủ luồng.

## Các bước

| # | Người | Thao tác | Nói gì |
|---|---|---|---|
| 1 | A | Giới thiệu bài toán, kết quả khảo sát (30s) | "Chúng em khảo sát 40 thành viên CLB…" |
| 2 | D | Khách đăng ký tài khoản mới, đăng nhập, thử vào URL `/sukien/tao/` | "Gõ thẳng URL cũng bị chặn 403, vì phân quyền kiểm tra ở server, không chỉ ẩn nút" |
| 3 | E | Đăng nhập `admin`, gán role Thành viên BTC cho tài khoản vừa tạo, mở nhật ký thao tác | "Mọi thao tác quan trọng đều được ghi log để truy vết" |
| 4 | C | Đăng nhập `truongbtc`, tạo sự kiện mới, thêm 2 loại vé, chuyển sang Mở đăng ký | "Sự kiện có máy trạng thái, không thể nhảy từ Đang chuẩn bị sang Đã diễn ra" |
| 5 | A | Bấm **AI gợi ý công việc**, tick chọn vài việc, lưu | "AI chỉ gợi ý, Trưởng BTC vẫn quyết định. Nếu AI lỗi, hệ thống dùng danh sách mặc định" |
| 6 | B | Đăng nhập `btc1`, mở **Việc của tôi**, đánh dấu một việc thành Xong | "Tiến độ sự kiện tự cập nhật, việc quá hạn tô đỏ" |
| 7 | D | `thanhvien` đặt 2 vé sự kiện Acoustic Night. Rồi thử đặt thêm 5 vé | "Bị chặn vì giới hạn 4 vé mỗi người — đây là test giá trị biên TC07-3" |
| 8 | **C** | **Mở sự kiện Workshop (còn 1 chỗ) trên 2 trình duyệt, cùng bấm Đăng ký** | **"Chỉ 1 người thành công. Vì `SELECT ... FOR UPDATE` khoá dòng loại vé, giao dịch thứ hai phải chờ rồi mới đọc được số chỗ đã cập nhật"** |
| 9 | B | Đăng nhập `btc1`, vào **Xác nhận thanh toán**, xác nhận vé vừa đặt | "Vé chuyển từ Chờ thanh toán sang Đã xác nhận, giờ mới check-in được" |
| 10 | E | Quét QR trên điện thoại: lần 1 hợp lệ (xanh), **quét lại lần 2 báo Đã sử dụng (vàng)**, nhập mã sai báo Không hợp lệ (đỏ) | "Ba kết quả đúng đặc tả UC10. Mã vé là UUID ngẫu nhiên nên không đoán được" |
| 11 | D | Mở sự kiện Minishow Tròn, gửi đánh giá 5 sao | "Chỉ người đã check-in mới được đánh giá" |
| 12 | B | Vào **Phản hồi & thống kê**, bấm **AI tóm tắt phản hồi** | "AI đọc 9 phản hồi, tách ra điểm khen, điểm chê, đề xuất cải thiện. Không gửi kèm tên hay MSSV" |
| 13 | D | Mở **Trợ lý**, hỏi "còn vé không" và "việc của tôi có gì" | "Trợ lý này KHÔNG dùng AI sinh ngôn ngữ. Nó nhận diện ý định bằng từ khoá rồi tra thẳng DB, nên không bao giờ bịa thông tin và chạy được cả khi không có mạng ra ngoài" |
| 14 | A | Mở **Thống kê tổng hợp** xem biểu đồ, rồi mở Git log + bảng test case + RTM (30s) | "83 unit test, mã test khớp với bảng test case trong báo cáo" |

Mỗi người đều thao tác ít nhất một lần, nên giảng viên hỏi ai làm gì thì ai
cũng trả lời được. Mỗi bước nên nối với tài liệu: "đây là UC07, sequence
diagram trang 15".

## Câu hỏi hay gặp và cách trả lời

**Sao chọn Incremental mà không phải Waterfall?**
Chỉ có 11 ngày, yêu cầu còn có thể thay đổi. Chia 5 sprint, mỗi sprint ra một
phần chạy được nên phát hiện vấn đề sớm. Waterfall phù hợp khi yêu cầu đã rõ
và ổn định từ đầu.

**Hai người cùng mua chỗ cuối thì xử lý thế nào?**
Mở `registrations/services.py`, hàm `book_tickets`. Hai lớp bảo vệ:
`select_for_update()` khoá dòng loại vé ở tầng CSDL, và `@transaction.atomic`
bảo đảm trừ chỗ và tạo vé là một khối không tách được.

**Nếu bỏ transaction thì sao?**
Hai giao dịch cùng đọc `sold = 19`, cả hai đều thấy còn chỗ, cả hai đều ghi
`sold = 20`. Kết quả là bán 21 vé cho 20 chỗ. Có test `RaceConditionTests`
chứng minh điều này.

**Mật khẩu lưu thế nào? Sao không dùng MD5?**
bcrypt, xem `config/settings.py`. bcrypt và PBKDF2 đều là hàm băm **chậm** và
có **salt**. MD5/SHA1 nhanh nên brute-force rất dễ, và không có salt thì tra
bảng rainbow là ra.

**Phân quyền kiểm tra ở đâu?**
`accounts/permissions.py`, dùng decorator `@lead_required`, `@staff_required`,
`@admin_required` gắn trên từng view. Kiểm tra ở server, nên gõ thẳng URL
cũng bị 403. Có test `UrlPermissionTests` chứng minh.

**Mã vé có đoán được không?**
Không. Dùng UUID4 (122 bit ngẫu nhiên), không phải ID tăng dần. Nếu dùng ID
tăng dần thì ai cũng suy ra mã vé của người khác rồi check-in hộ.

**Trợ lý tra cứu có phải AI không?**
Không, và nhóm ghi rõ điều đó trong báo cáo. Nó là hỏi đáp theo ý định
(intent-based QA): chuẩn hoá câu hỏi bằng cách bỏ dấu tiếng Việt, so khớp
từ khoá có chấm điểm theo độ dài, rồi truy vấn DB và trả lời theo mẫu câu.
Đổi lại nó có 3 ưu điểm mà chatbot LLM không có: chạy được trên host chặn
kết nối ngoài, test được từng ý định vì kết quả xác định, và không bao giờ
bịa thông tin sai về sự kiện.

**Sao không dùng LLM cho trợ lý luôn?**
Vì với bài toán tra cứu phạm vi hẹp thì LLM kém hơn ở mọi mặt: mỗi câu hỏi
tốn một lần gọi API nên dễ hết quota giữa demo, kết quả không xác định nên
gần như không test được, và có nguy cơ trả lời sai thông tin sự kiện. Nhóm
vẫn dùng LLM ở hai chỗ nó thực sự mạnh là sinh gợi ý công việc và tóm tắt
văn bản tự do.

**AI hết quota thì hệ thống có chết không?**
Không. Xem `aiassist/services.py`, mọi lỗi được gom về `AIError` và có
fallback là danh sách công việc mặc định. Đây là fault tolerance. Có test
`SuggestTasksFallbackTests`.
