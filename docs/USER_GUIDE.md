# Hướng dẫn người dùng pilot KMG

Cơ cấu pilot: Chuyên môn, Truyền thông–Sự kiện và Kỹ thuật. Dùng tài khoản cá nhân; không dùng tài khoản demo trên môi trường thật.

## Đăng ký và gia nhập

1. Đăng ký tại `/taikhoan/dangky/`. Ưu tiên email; chỉ dùng SMS khi quản trị xác nhận gateway hoạt động.
2. Nhập OTP đúng hạn, không chia sẻ mã. Khi gửi lại thất bại, mã đã nhận trước đó vẫn dùng được đến hạn nếu chưa được thay thế thành công.
3. Xác minh xong vẫn là Khách. Gửi đơn hoặc liên hệ BCN để duyệt và phân ban.
4. Sau duyệt, vào `/workspace/`; người đa ban chọn đúng ban trước khi thao tác.

Quên mật khẩu: dùng liên kết trên trang đăng nhập. Nếu chỉ có số điện thoại và chưa có cách khôi phục phù hợp, liên hệ đầu mối pilot; không gửi mật khẩu qua tin nhắn.

## Thành viên

| Công việc | Trang | Cần kiểm tra |
|---|---|---|
| Nhận/thực hiện việc | `/workspace/cong-viec/` | Hạn, người phụ trách, đầu ra nghiệm thu |
| Nộp bài/gia hạn | Chi tiết công việc | Tệp đã lưu, lý do và phản hồi người duyệt |
| RSVP | `/workspace/su-kien/` | Hạn trả lời, lý do từ chối/miễn trừ |
| Nhắc việc | Chuông và `/thongbao/` | Xem trong app dù chưa nhận email |
| Đào tạo/lịch tập | `/workspace/dao-tao/` | Thời gian, nhạc cụ, trạng thái đăng ký |
| Tài liệu | `/workspace/tai-lieu/` | Không chia sẻ tệp nội bộ ra ngoài phạm vi |
| Khiếu nại | Cổng trạng thái hoặc khu vực kỷ luật | Lý do, minh chứng, người xem xét độc lập |

Khi mạng chậm, kiểm tra lại trạng thái trước khi bấm nộp/duyệt lần nữa. Nếu có sai lệch, giữ lịch sử và báo người phụ trách.

## Trưởng ban và Phó ban

Vào `/workspace/ban/<slug>/`. Giao việc kèm đầu ra/hạn; người nhận không tự nghiệm thu. Phó ban chỉ có quyền trong gói ủy quyền còn hiệu lực và chịu trần quyền. Chức danh ban A không cấp quyền quản lý ban B.

Kỹ năng xác minh giúp gợi ý nhân sự, không cấp quyền tài liệu. Kiểm tra ACL khi chia sẻ và thu hồi quyền khi chuyển ban/kết thúc nhiệm kỳ.

## BCN và Cố vấn

BCN dùng `/workspace/quan-tri/` để duyệt/phân ban và xử lý việc thuộc phạm vi. Cảnh báo chuyên cần cần người xem xét minh chứng; người ra quyết định ban đầu không tự phân xử khiếu nại của quyết định đó. Admin Server thực hiện bổ nhiệm lãnh đạo cấp cao tại Quản lý tài khoản.

Cố vấn dùng `/workspace/giam-sat/` và báo cáo được cấp, chỉ đọc. Nếu cần sửa số liệu, gửi nhận xét cho người phụ trách. Phiếu đánh giá thành viên là riêng tư; vinh danh công khai tách khỏi điểm số.

## Quỹ, chat và báo lỗi

Quỹ tại `/workspace/tai-chinh/` dùng dữ liệu thử đến khi có thông báo mở thật. Người lập/người duyệt khác nhau. Phiếu đã ghi sổ chỉ điều chỉnh bằng bút toán mới; Django Admin phục vụ tra cứu bản ghi được bảo vệ.

Chat kiểm tra thành viên hội thoại và mã hóa tại máy chủ; không phải E2EE chống người nắm máy chủ/khóa. Web Push chưa mở; dùng chuông/email.

Khi báo lỗi, gửi thời gian, vai trò, trang, các bước và kết quả cho đầu mối pilot. Không gửi mật khẩu/OTP hoặc ảnh có thông tin riêng của người khác. Dùng kênh dự phòng do BCN chỉ định nếu công việc bị gián đoạn.
