# Sổ tay quản trị pilot KMG

Tài liệu này dành cho Admin Server và người vận hành. Cơ cấu đã chốt: Chuyên môn, Truyền thông–Sự kiện, Kỹ thuật. Người phụ trách, domain và lịch pilot cần điền trong [kế hoạch pilot](PILOT_PLAN.md) trước khi mở thật.

## Khởi tạo và phân quyền

Triển khai theo [runbook](deployment/DEPLOYMENT_AND_BACKUP.md). Chạy migration, `bootstrap_kmg`, rồi `createsuperuser`. Bootstrap chỉ tạo danh mục; không chạy `seed_demo` hoặc `seed_kmg` trên môi trường thật. Đặt `ALLOW_DEMO_SEED=False`.

Admin Server dùng `/taikhoan/quanly/` để bổ nhiệm Chủ nhiệm, Phó chủ nhiệm, Trưởng ban và Cố vấn. Chủ nhiệm/Phó chủ nhiệm duyệt Guest thành thành viên và phân ít nhất một ban ở `/workspace/quan-tri/`. Trưởng ban cấp gói ủy quyền cho Phó ban trong phạm vi được phép. Không cấp quyền bằng kỹ năng và không dùng Django Admin để bỏ qua luồng duyệt.

Khi chuyển ban hoặc kết thúc nhiệm kỳ, dùng luồng nghiệp vụ để thu hồi quyền và ghi lịch sử. Không chỉnh trực tiếp DB. Người gắn với sổ quỹ/khoản chi được bảo vệ khỏi xóa; dùng khóa/ngừng hoạt động để giữ minh chứng.

## Kiểm tra trước nâng cấp

1. Chốt commit/tag, review CI, lưu phiên bản image và cấu hình (bí mật lưu riêng).
2. Backup và xác minh restore trên môi trường riêng. Thống nhất khoảng dừng và đầu mối hỗ trợ.
3. Rà soát dữ liệu cũ trước constraint mới: phiếu `CONFIRMED` phải có người duyệt khác người lập và có thời điểm duyệt. Chạy truy vấn chỉ đọc dưới đây qua Django shell trên bản sao staging; xử lý sai lệch bằng quy trình được BCN duyệt, không tự điền người duyệt giả.

```python
from django.db.models import F, Q
from finance.models import FinancialTransaction
bad = FinancialTransaction.objects.filter(status="CONFIRMED").filter(
    Q(approved_by__isnull=True) | Q(approved_at__isnull=True) | Q(approved_by=F("created_by"))
)
print(list(bad.values_list("id", "tx_code")))
```

Migration `finance.0003` sẽ dừng nếu dữ liệu không đáp ứng constraint. Backup trước migration; không bỏ constraint để ép deploy. Ràng buộc và guard bảo vệ các thao tác ứng dụng/ORM thông thường, không ngăn người có quyền SQL trực tiếp sửa mọi trường.

## Theo dõi hằng ngày

- `/health/` trả 200 khi DB/cache sẵn sàng; 503 là lỗi phụ thuộc. Không coi HTTP 200 trang chủ là kiểm tra đủ.
- Theo dõi `docker compose ... ps` và health scheduler. Có container chạy chưa đồng nghĩa các công việc nền thành công.
- Xem log scheduler/web, số email `email_pending=True`, thời điểm gửi thử gần nhất và lỗi loại nào. Không chép thông tin OTP/khóa/dữ liệu cá nhân vào báo cáo sự cố.
- Kiểm tra tuổi backup, dung lượng đĩa, HTTP 5xx và độ trễ. Thiết lập một hệ thống cảnh báo ngoài ứng dụng và người nhận; repo chưa kết nối dịch vụ cảnh báo thực.
- Chỉ một scheduler cho mỗi deployment; không chạy thêm cron hai lệnh nghiệp vụ trùng lịch.

## Khi gửi thông báo thất bại

OTP lỗi phải được phản ánh cho người dùng. Đăng ký qua API vẫn có thể trả 201 vì tài khoản Guest đã tạo, kèm `otp_sent=false`, `delivery_error` và `retry_url`; không diễn giải thành đã gửi OTP thành công. API gửi lại trả 503 khi provider không nhận. Mã cũ còn hạn được giữ khi phát hành mã mới thất bại.

Reminder lưu thông báo trong app và trạng thái email cùng transaction. Email thất bại được giữ để lần chạy `run_kmg_operations` sau thử lại. Lệnh báo lỗi nếu còn email chờ; kiểm tra SMTP trước khi chạy lại. Không xóa reminder hoặc sửa cờ bằng tay để ép gửi. SMTP có cửa sổ có thể gửi trùng khi sự cố xảy ra sau tiếp nhận nhưng trước commit.

## Khi có sự cố

| Sự cố | Hành động đầu tiên | Điều kiện phục hồi |
|---|---|---|
| Không truy cập/health 503 | Kiểm tra DB, Redis, disk, log, cấu hình proxy | Health ổn và luồng đăng nhập/nghiệp vụ chính chạy lại |
| Scheduler unhealthy | Xem mã thoát/lỗi SMTP, tránh tạo scheduler thứ hai | Một chu kỳ thành công và backlog xử lý được |
| Nghi lộ quyền/tài liệu | Hạn chế tính năng bị ảnh hưởng, giữ log, báo người phụ trách | Tái hiện, sửa và kiểm thử quyền âm tính đạt |
| Sai số liệu quỹ | Dừng duyệt phiếu liên quan, đối soát lịch sử | Điều chỉnh qua bút toán, hai người xác nhận |
| Deploy/migration lỗi | Giữ môi trường lỗi để điều tra, kích hoạt phương án quay lui | Bản cũ và dữ liệu tương thích được kiểm chứng |
| Mất/hỏng DB hoặc tệp | Restore sang project mới cùng khóa gốc | Đối soát, UAT khói, rồi chuyển lưu lượng |

Không đổi `CHAT_MASTER_KEK` hoặc `CERT_SIGNING_KEY` như cách xử lý lỗi thông thường. Chưa có quy trình tái mã hóa toàn bộ chat để xoay KEK. Giữ khóa gốc trong nơi lưu bí mật có bản dự phòng, tách khỏi backup dữ liệu.

## Bàn giao

Ghi người trực chính/dự phòng, quyền truy cập host, nơi giữ khóa, nơi lưu backup mã hóa, lịch restore drill, kênh báo lỗi và cách liên hệ BCN. Chỉ đánh dấu hoàn thành khi người nhận đã tự thực hiện thử, không chỉ nhận tài liệu.
