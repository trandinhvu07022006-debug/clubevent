# Bàn giao chạy local KMG

Theo lựa chọn của chủ dự án, đợt này bàn giao local; chưa triển khai máy chủ/domain. Cơ cấu giữ nguyên Chuyên môn / Truyền thông–Sự kiện / Kỹ thuật.

## Chạy lần đầu

Cài Python 3.12 và thư viện trong môi trường riêng:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Nhấp đúp `chay-pilot-local.bat`, hoặc chạy:

```powershell
.\.venv\Scripts\python.exe -m deployment.local_pilot
```

Mở http://127.0.0.1:8001. Dùng tài khoản hiện có của bản local; danh sách đã bàn giao được ghi riêng trong `.local-pilot/TAI_KHOAN_LOCAL.md` (không đưa vào Git). Dừng bằng Ctrl+C. Đổi cổng bằng `--port 8002`.

Launcher migrate, bootstrap, collectstatic, kiểm tra rồi chạy server loopback; không tự thêm tài khoản demo. Nếu chưa cài thư viện, cài theo lệnh trên rồi chạy lại. Lệnh `--prepare-only` khởi tạo mà không chạy server.

## Dữ liệu riêng và tài khoản tự tạo

Mọi trạng thái local nằm trong `.local-pilot/`: `db.sqlite3`, `keys.json`, `media`, `private_vault`, `staticfiles`, `logs`. Không đọc `.env`, không dùng MySQL/CSDL mặc định của dự án. Cấu hình bật DEBUG để phục vụ media trong môi trường phát triển, chỉ chạy loopback; không dùng cấu hình này để mở ra mạng. Thư mục bị loại khỏi Git và Docker build. Giữ DB/tệp/keys.json cùng nhau khi chuyển máy; mất khóa thì cần khôi phục khóa gốc.

Để dùng DB local mới không có persona mẫu, chạy launcher không có `--demo`, rồi tạo Admin Server:

```text
python -m deployment.local_pilot --prepare-only
python manage.py createsuperuser --settings=config.settings_local
python -m deployment.local_pilot
```

Không dùng các lệnh trên để xóa demo đã tồn tại: launcher không tự reset hoặc xóa dữ liệu. Với DB mới dành riêng cho kịch bản UAT đầy đủ, có thể chọn `--demo` để tạo persona mẫu trong [kế hoạch UAT](PILOT_PLAN.md). Không nạp demo vào DB đã có danh sách thành viên riêng. Khi có `.local-pilot/roster-customized.lock`, cấu hình local tắt các lệnh seed demo để tránh tạo lại tài khoản cũ; giữ tệp này khi chuyển bản local sang máy khác.

## OTP và tác vụ nền

Email/SMS được in ở terminal, AI ở chế độ mock. Đây là kiểm thử local, không phải xác nhận gửi email/SMS thật. Launcher không chạy scheduler ngầm; trong terminal thứ hai có thể chủ động chạy một chu kỳ:

```text
python manage.py run_periodic --settings=config.settings_local
python manage.py run_kmg_operations --settings=config.settings_local
```

Khi chuyển sang máy chủ, dùng Compose/MySQL/Redis và quy trình trong [runbook](deployment/DEPLOYMENT_AND_BACKUP.md); không copy bộ tài khoản demo làm tài khoản thật. Docker/Redis thực, HTTPS, SMTP, load test và UAT trên người dùng vẫn cần nghiệm thu trước khi vận hành.
