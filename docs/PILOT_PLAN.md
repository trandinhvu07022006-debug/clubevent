# Kế hoạch vận hành thử nghiệm KMG

Cập nhật 18/11/2026. Các mục chưa đánh dấu chưa được nghiệm thu; không suy ra đã đạt từ việc test tự động chạy xanh.

## Phạm vi đã chốt

Chủ dự án chọn giữ cơ cấu **Chuyên môn / Truyền thông–Sự kiện / Kỹ thuật**. Tài liệu Phase 0 là baseline lịch sử; ma trận quyền v1.2 và hành vi được nghiệm thu là căn cứ cho pilot. Kỹ năng chỉ dùng gợi ý, không tự cấp quyền; Admin Server độc quyền bổ nhiệm lãnh đạo cấp cao.

Đề xuất 20–30 người thuộc 1–2 ban, thử 1–2 tuần sau khi đạt điều kiện mở. Ngày bắt đầu, danh sách người tham gia và người phụ trách do BCN chốt; chưa cam kết ngày go-live khi chưa có máy chủ, domain và kênh gửi thật.

| Mở đợt đầu | Mở sau nghiệm thu riêng |
|---|---|
| Tài khoản, OTP email, duyệt thành viên và phân ban | SMS khi gateway được kiểm chứng |
| Giao/nhận/nộp/sửa/duyệt việc, gia hạn | Quỹ thật sau đối soát và nghiệm thu hai người duyệt |
| Sự kiện nội bộ, RSVP, nhắc lịch, điểm danh | Tài liệu nhạy cảm sau kiểm tra ACL và restore |
| Thông báo trong app/email | Social/chat, đánh giá, vinh danh theo nhu cầu |

Web Push, WebSocket và quản lý cuộc thi ngoài phạm vi đợt đầu. Chat hiện không phải E2EE. Quỹ ban đầu dùng dữ liệu thử, được ghi rõ là thử nghiệm.

## Thứ tự thực hiện

1. Review và chốt commit ứng viên phát hành; chạy CI MySQL/Redis, kiểm tra migration và build container.
2. Dựng staging Linux/Compose, HTTPS, khóa độc lập, email thật; bootstrap danh mục và tài khoản riêng.
3. Diễn tập migration trên bản sao dữ liệu được phép dùng; lưu thời gian, lỗi và cách quay lui.
4. Kiểm thử các vai trò, luồng nghiệp vụ, thiết bị và tải cao điểm; lưu bằng chứng UAT.
5. Backup/restore sang môi trường khác; đối soát DB/tệp, mở được chat và xác thực chứng nhận.
6. BCN xác nhận mở pilot; hỗ trợ và triage lỗi hằng ngày, tổng kết trước khi mở rộng.

## Ma trận nghiệm thu người dùng

| Mã | Tình huống | Kết quả mong đợi | Thực tế |
|---|---|---|---|
| U01 | Đăng ký → OTP → duyệt/phân ban | Guest bị chặn nội bộ; sau duyệt vào đúng phạm vi | Chưa UAT |
| U02 | Kênh gửi lỗi rồi gửi lại OTP | Báo đúng lỗi, giữ mã cũ còn hạn nếu gửi mới thất bại | Chưa UAT |
| U03 | Thành viên một/đa ban đăng nhập | Quyền đúng từng ban | Chưa UAT |
| U04 | Trưởng ban A gọi URL/API/tệp riêng ban B | Không đọc/ghi trái quyền | Chưa UAT |
| U05 | Phó ban trước/sau ủy quyền và thu hồi | Đúng gói, đúng trần, thu hồi có hiệu lực | Chưa UAT |
| U06 | Giao → nhận → nộp → sửa → duyệt | Có lịch sử, không tự nghiệm thu | Chưa UAT |
| U07 | Gia hạn và nộp trễ | Hạn/trạng thái đúng, không mất bài | Chưa UAT |
| U08 | RSVP, miễn trừ, điểm danh | Không phạt oan người tạm khóa/được miễn | Chưa UAT |
| U09 | Scheduler lặp, SMTP lỗi rồi phục hồi | Một thông báo app; email lỗi được thử lại | Chưa UAT |
| U10 | Chuyển ban/miễn nhiệm/tạm khóa/khiếu nại | Thu hồi quyền đúng, giữ quyền khiếu nại | Chưa UAT |
| U11 | Cố vấn thử ghi dữ liệu | Chỉ đọc, hạn chế thông tin riêng tư | Chưa UAT |
| U12 | Đặt vé cuối/duyệt phiếu đồng thời | Không vượt quota hoặc ghi sổ hai lần | Chưa UAT |
| U13 | Lập → duyệt → điều chỉnh quỹ | Hai người khác nhau; không sửa/xóa phiếu đã ghi sổ qua app | Chưa UAT |
| U14 | Điện thoại và máy tính | Đăng nhập, form, upload, QR dùng được | Chưa UAT |
| U15 | Restore DB/tệp/khóa | Dữ liệu đối soát đúng, chat/chứng nhận hoạt động | Chưa UAT |

Email qua SMTP không có bảo đảm exactly-once: sự cố sau khi SMTP nhận thư nhưng trước commit có thể làm gửi lại thư. Thông báo trong app được chống trùng bằng transaction và ràng buộc dữ liệu.

## Điều kiện mở pilot

- [ ] Có commit/tag cụ thể; CI MySQL/Redis/container xanh.
- [ ] HTTPS/domain và email giao nhận thật; SMS được kiểm chứng hoặc công bố chưa mở.
- [ ] Không còn lỗi chặn luồng hoặc vượt quyền nghiêm trọng trong phạm vi mở.
- [ ] Migration rehearsal và UAT được đại diện người dùng xác nhận.
- [ ] Scheduler heartbeat/alert và đầu mối nhận cảnh báo ngoài ứng dụng hoạt động.
- [ ] Backup mã hóa, lưu ngoài máy chủ; restore đạt mục tiêu đề xuất RPO ≤24 giờ, RTO ≤2 giờ.
- [ ] Có rollback, đầu mối hỗ trợ và thông tin cho người dùng về dữ liệu/giới hạn chat.
- [ ] Không có tài khoản mẫu; ALLOW_DEMO_SEED=False.

## Trách nhiệm và theo dõi

| Vai trò | Trách nhiệm | Người phụ trách |
|---|---|---|
| Chủ dự án/BCN | Chốt phạm vi, chính sách và mở rộng | Chưa điền |
| Quản trị kỹ thuật | Deploy, migration, khóa, backup/restore, monitoring | Chưa điền |
| Đại diện Trưởng ban | Nghiệm thu công việc/sự kiện/quyền | Chưa điền |
| Thành viên/Cố vấn | Nghiệm thu sử dụng và quyền hạn | Chưa điền |
| Đầu mối hỗ trợ | Triage và phối hợp xử lý sự cố | Chưa điền |

Mẫu lỗi: thời gian, vai trò, trang, bước tái hiện, mong đợi/thực tế, mức độ, người xử lý, bản sửa và xác nhận lại. Không ghi mật khẩu/OTP/chat riêng vào báo cáo. Theo dõi lỗi nghiêm trọng, hoàn thành luồng chính, độ trễ p95, HTTP 5xx và tuổi backup. Chốt ngưỡng hiệu năng trên staging theo quy mô pilot; không coi mục tiêu 1.000 user ảo trong thiết kế là kết quả đã đạt.
