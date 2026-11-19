# Triển khai và khôi phục pilot KMG

Runbook cập nhật 18/11/2026 cho Linux, Docker Engine + Compose v2 và Python 3.12 trên host. Stack gồm Django/Gunicorn, MySQL 8.4, Redis, Nginx và một scheduler. CI chứa kiểm tra container và restore drill; cần có kết quả chạy thực tế trước nghiệm thu. Máy phát triển Windows dùng trong đợt sửa này chưa có Docker.

## Chuẩn bị môi trường

1. Chọn host, domain và người vận hành. Dùng project `kmg` cho ví dụ dưới đây; giữ tên project nhất quán để không tạo nhầm bộ volume.
2. Từ một checkout đã review, tạo `.env.production` từ `.env.production.example` khi chưa tồn tại; không ghi đè file cấu hình đang dùng.
3. Sinh riêng ba khóa mạnh ≥32 ký tự cho `SECRET_KEY`, `CERT_SIGNING_KEY`, `CHAT_MASTER_KEK`; điền mật khẩu DB/root khác nhau. Lưu khóa trong kho bí mật có bản dự phòng. Không commit hoặc đưa chúng vào log.
4. Giữ `ALLOW_DEMO_SEED=False`. Điền SMTP thật, địa chỉ gửi, SITE_URL và CSRF_TRUSTED_ORIGINS. SMS chỉ mở khi gateway thật đã được kiểm tra.

Compose không publish MySQL/Redis/Gunicorn ra host. Nginx mặc định chỉ bind `127.0.0.1:8080` để một TLS terminator tin cậy trên host chuyển tiếp. Redis nằm trong mạng riêng của stack; không mở cổng Redis ra Internet.

## Khởi động và khởi tạo

```sh
docker compose --project-name kmg --env-file .env.production up --build -d --wait --wait-timeout 240
docker compose --project-name kmg --env-file .env.production exec web python manage.py bootstrap_kmg
docker compose --project-name kmg --env-file .env.production exec web python manage.py createsuperuser
curl --fail http://127.0.0.1:8080/health/
```

Service `migrate` chạy trước web. Bootstrap tạo danh mục, không tạo tài khoản mẫu. Admin Server bổ nhiệm cán bộ tại `/taikhoan/quanly/`. Không chạy seed demo để tạo tài khoản thật.

Trước khi nâng cấp DB cũ, thực hiện truy vấn kiểm tra phiếu đã ghi sổ trong [sổ tay quản trị](../ADMIN_HANDBOOK.md). Constraint mới sẽ từ chối phiếu thiếu người duyệt độc lập; không tự sửa dữ liệu sai để ép migration chạy.

## HTTPS

Cấu hình TLS terminator của host với chứng chỉ/domain thật, chuyển tiếp tới `http://127.0.0.1:8080`, giữ Host là domain. Chỉ sau khi TLS hoạt động mới đặt:

```dotenv
ALLOWED_HOSTS=ten-mien-thuc.example
SITE_URL=https://ten-mien-thuc.example
CSRF_TRUSTED_ORIGINS=https://ten-mien-thuc.example
PROXY_SCHEME=https
USE_HTTPS=True
```

Đây là placeholder, phải thay bằng domain thật. Giữ `BIND_ADDRESS=127.0.0.1`; không cho người dùng đi thẳng vào cổng HTTP nội bộ. Không dùng header client để tự quyết định HTTPS; template Nginx ghi đè header bằng cấu hình cố định. Nếu TLS terminator ở máy khác, thiết kế lại bind/firewall và chuỗi IP tin cậy trước khi mở.

Chạy lại Compose để áp dụng env. Kiểm tra đăng nhập/form POST/CSRF, cookie Secure, OTP, upload/tải tệp và camera QR trên thiết bị thật. HTTPS termination và kênh gửi không được repo tự cấp hay tự cấu hình tài khoản.

## Scheduler và monitoring

Scheduler chạy `run_periodic` và `run_kmg_operations` mỗi 900 giây. Các bước lỗi trả exit code thất bại; heartbeat chỉ khỏe khi cả hai lệnh hoàn thành thành công và còn mới. Lệnh có timeout; lỗi SMTP/backlog khiến cần xử lý vận hành, không có nghĩa phải tạo thêm scheduler.

```sh
docker compose --project-name kmg --env-file .env.production ps
docker compose --project-name kmg --env-file .env.production logs --tail=100 scheduler
docker compose --project-name kmg --env-file .env.production exec -T scheduler python deployment/scheduler_healthcheck.py
docker compose --project-name kmg --env-file .env.production exec -T web python manage.py check --deploy
```

Kết nối cảnh báo bên ngoài cho web health, scheduler unhealthy, 5xx, disk và backup trễ. Healthcheck của Docker phát hiện lỗi nhưng không thay thế việc gửi thông báo cho người trực.

## Sao lưu đồng bộ

Backup gồm `database.sql`, `media.tar.gz`, `private_vault.tar.gz` và manifest SHA-256. Tiện ích tạm dừng Nginx/web/scheduler để DB và tệp đồng bộ, sau đó khởi động lại đúng các service đã chạy. Dừng cả writer ngoài stack nếu có. Đây là backup có khoảng bảo trì ngắn, không phải zero-downtime.

Tạo thư mục backup riêng có quyền hạn chế. Từ checkout đúng phiên bản:

```sh
python -m deployment.backup_restore backup --project kmg --env-file .env.production --output backups/backup-20261118-0100 --maintenance
```

Thư mục đầu ra phải chưa tồn tại. Không có `manifest.json` hoàn chỉnh hoặc hash không khớp nghĩa là backup chưa đạt. Công cụ không tự mã hóa gói backup hoặc upload ra ngoài; cấu hình mã hóa và lưu ngoài host trước khi mở pilot. Không dùng backup chưa mã hóa ở nơi công khai.

Giữ riêng ba khóa gốc; manifest chỉ lưu fingerprint, không chứa khóa. Đề xuất chạy hằng ngày trong cửa sổ bảo trì, giữ 14 bản gần nhất sau khi xác nhận bản ngoài host và restore thành công. Chưa có tác vụ tự xóa backup để tránh mất bản duy nhất còn dùng được. Lập lịch và kiểm tra mã thoát của lệnh trên bằng scheduler host; không dùng scheduler nghiệp vụ của ứng dụng để backup chính nó.

## Khôi phục sang project mới

Giữ nguyên backup nguồn. Chuẩn bị `.env.restore` với ba khóa gốc, mật khẩu DB cho môi trường mới và `HTTP_PORT=8081` nếu chạy cùng host. Build hoặc nạp đúng image của phiên bản backup trước khi restore; không tự dùng image mới có schema khác.

```sh
python -m deployment.backup_restore restore --project kmg-restore-20261118 --env-file .env.restore --input backups/backup-20261118-0100
```

Restore từ chối project nguồn, volume/container đã tồn tại, volume ngoài project, khóa khác, hash sai hoặc archive có đường dẫn không an toàn. Tiện ích chỉ khởi động DB/Redis và nhập vào volume mới; web/scheduler giữ dừng. Nếu thất bại, giữ môi trường mới để điều tra và chọn project mới cho lần thử lại; không ghi đè dữ liệu pilot.

Kiểm tra trước khi khởi động web:

```sh
docker compose --project-name kmg-restore-20261118 --env-file .env.restore run --rm --no-deps web python manage.py migrate --check
docker compose --project-name kmg-restore-20261118 --env-file .env.restore run --rm --no-deps web python manage.py check
```

Đối soát số bản ghi, các tệp đại diện, chứng từ, khóa chat và chứng nhận. Sau đó khởi động toàn stack, thử health và UAT khói. Chỉ chuyển domain/lưu lượng khi người phụ trách xác nhận. Không để hai scheduler của bản cũ và mới cùng phục vụ một nhóm người dùng trong lúc chuyển đổi.

## Rollback và nghiệm thu

Nếu chỉ lỗi code và schema tương thích, dùng image/commit trước đã lưu rồi kiểm tra lại. Nếu migration hoặc dữ liệu đã thay đổi không tương thích, khôi phục backup vào project mới và chuyển lưu lượng sau đối soát. Không tự chạy migration ngược trên dữ liệu thật khi chưa diễn tập.

Mục tiêu đề xuất RPO ≤24 giờ, RTO ≤2 giờ. Ghi thời điểm backup, bắt đầu restore, hoàn thành, số liệu đối soát, người xác nhận và sai lệch. Việc script tồn tại hoặc unit test đạt chưa chứng minh các mục tiêu này; phải diễn tập trên hạ tầng pilot.
