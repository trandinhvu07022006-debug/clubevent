# Hướng dẫn deploy lên link thật

Dự án đã chuẩn bị sẵn mọi thứ để deploy: WhiteNoise phục vụ file static,
hỗ trợ cả MySQL lẫn PostgreSQL, trang lỗi riêng, cấu hình HTTPS bật qua biến
môi trường. Việc còn lại chỉ là chọn host và điền biến môi trường.

---

## 0. Trước khi deploy — hiểu rõ mình đang làm gì

Chạy `python manage.py runserver` là web server chỉ tồn tại **trên máy đó**,
địa chỉ `127.0.0.1` nghĩa là "chính máy đang gõ lệnh". Gửi địa chỉ đó cho
người khác thì máy họ trỏ về máy họ, không vào được máy bạn.

Deploy là copy code và database sang một máy chủ bật 24/7 có tên miền công
khai, ai có internet cũng vào được.

**Khi bảo vệ vẫn nên demo trên localhost**, vì không phụ thuộc wifi phòng học.
Link online là để giảng viên tự vào xem sau và để viết chương "Triển khai"
trong báo cáo.

---

## 1. Chọn host

| | PythonAnywhere free | Render free |
|---|---|---|
| Ngủ sau 15 phút không dùng | Không ngủ | **Ngủ, request đầu chờ 30–60s** |
| Database | **MySQL sẵn** | Chỉ PostgreSQL |
| Ảnh upload sau redeploy | **Không mất** | Mất |
| Gọi API AI ra ngoài | **Bị chặn** | Chạy được |
| Deploy từ GitHub | Thủ công hơn | **Tự động** |

Điều kiện gói free của hai nhà này thay đổi thường xuyên. **Kiểm tra lại trên
trang chính thức trước khi đăng ký**, đừng tin bảng này như số liệu cuối cùng.

**Đề xuất: chọn PythonAnywhere.** Không ngủ và không mất ảnh là hai thứ ảnh
hưởng trực tiếp tới việc giảng viên tự vào xem. Đổi lại chức năng AI sẽ tự
chuyển sang danh sách mặc định — ghi rõ điều đó trong báo cáo, nó chứng minh
cơ chế thứ lỗi mình thiết kế có tác dụng thật.

Trợ lý tra cứu (chatbot) chạy tốt trên mọi host vì không gọi API ra ngoài.

---

## 2. Deploy lên PythonAnywhere

### 2.1 Đẩy code lên GitHub

```bash
git init
git add .
git commit -m "Đồ án CNPM - hệ thống hỗ trợ tổ chức sự kiện CLB"
git remote add origin https://github.com/<tài-khoản>/<tên-repo>.git
git push -u origin main
```

Kiểm tra `.env` **không** nằm trong danh sách file đã commit:

```bash
git ls-files | grep "^.env$"     # phải không ra gì
```

### 2.2 Tạo tài khoản và clone code

Đăng ký tài khoản Beginner (miễn phí) tại pythonanywhere.com. Mở **Bash
console** rồi chạy:

```bash
git clone https://github.com/<tài-khoản>/<tên-repo>.git clubevent
cd clubevent
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2.3 Tạo database MySQL

Vào tab **Databases**, đặt mật khẩu MySQL, rồi tạo database tên `clubevent`.
Tên đầy đủ sẽ có dạng `<tàikhoản>$clubevent` — nhớ tên này.

### 2.4 Tạo file .env trên server

Trong Bash console:

```bash
cd ~/clubevent
nano .env
```

Dán nội dung sau, sửa lại cho khớp:

```
DEBUG=False
SECRET_KEY=<dán chuỗi sinh ở bước dưới>
ALLOWED_HOSTS=<tàikhoản>.pythonanywhere.com
USE_HTTPS=True

DB_ENGINE=mysql
DB_NAME=<tàikhoản>$clubevent
DB_USER=<tàikhoản>
DB_PASSWORD=<mật khẩu MySQL vừa đặt>
DB_HOST=<tàikhoản>.mysql.pythonanywhere-services.com
DB_PORT=3306
```

Sinh `SECRET_KEY` ngẫu nhiên:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(60))"
```

**Không bao giờ dùng lại SECRET_KEY của môi trường dev.** Khoá này dùng để ký
session và token CSRF, lộ ra là người khác giả mạo được phiên đăng nhập.

### 2.5 Migrate và nạp dữ liệu

```bash
python manage.py migrate
python manage.py seed_demo
python manage.py collectstatic --noinput
```

### 2.6 Cấu hình web app

Vào tab **Web**, bấm **Add a new web app**, chọn **Manual configuration** và
Python 3.11 (đừng chọn "Django", vì template đó tạo project mới đè lên).

Sau đó điền:

- **Source code**: `/home/<tàikhoản>/clubevent`
- **Virtualenv**: `/home/<tàikhoản>/clubevent/venv`
- **WSGI configuration file**: bấm vào link để sửa, xoá hết nội dung cũ, dán:

```python
import os
import sys

path = "/home/<tàikhoản>/clubevent"
if path not in sys.path:
    sys.path.insert(0, path)

os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

Bấm **Reload**. Mở `https://<tàikhoản>.pythonanywhere.com` là thấy trang chủ.

WhiteNoise đã lo phần file static nên **không cần** khai báo Static files
mapping trong tab Web.

### 2.7 Đặt lịch huỷ vé quá hạn

Tab **Tasks**, thêm một task chạy hằng ngày:

```
cd ~/clubevent && ./venv/bin/python manage.py release_expired
```

---

## 3. Deploy lên Render

### 3.1 Thêm 2 file vào repo

`build.sh` ở thư mục gốc:

```bash
#!/usr/bin/env bash
set -o errexit
pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate
```

Thêm vào `requirements.txt`:

```
gunicorn>=21.0
psycopg[binary]>=3.1
```

### 3.2 Tạo dịch vụ

Tạo **PostgreSQL** trước, copy chuỗi *Internal Database URL*.

Tạo **Web Service** trỏ vào repo GitHub, điền:

- Build Command: `./build.sh`
- Start Command: `gunicorn config.wsgi:application`

Environment Variables:

```
DEBUG=False
SECRET_KEY=<chuỗi ngẫu nhiên>
ALLOWED_HOSTS=<tên-app>.onrender.com
USE_HTTPS=True
DATABASE_URL=<Internal Database URL vừa copy>
PYTHON_VERSION=3.11.9
```

`settings.py` tự đọc `DATABASE_URL` nên không cần điền từng biến DB riêng.

### 3.3 Nạp dữ liệu demo

Mở tab **Shell** của web service:

```bash
python manage.py seed_demo
```

### 3.4 Chống ngủ

Render free ngủ sau 15 phút. Trước khi demo hoặc trước khi gửi link cho giảng
viên, mở link trước 1–2 phút cho nó thức dậy. Dùng cron-job.org ping mỗi 10
phút cũng được, nhưng tốn quota giờ chạy và một số host coi là lách luật.

---

## 4. Kiểm tra sau khi deploy

Chạy lần lượt, tất cả phải đạt:

| Kiểm tra | Cách làm | Đạt khi |
|---|---|---|
| Trang chủ lên | Mở link | Thấy danh sách sự kiện, **có CSS** (nền tối ở thanh menu) |
| Static file | F12 → tab Network → reload | Không có file nào đỏ 404 |
| Đăng nhập | `truongbtc` / `demo1234` | Vào được, hiện tên và vai trò |
| Phân quyền | Đăng nhập `thanhvien`, gõ `/sukien/tao/` | Hiện trang 403 riêng, không phải trang trắng |
| Trang 404 | Gõ một URL bừa | Hiện trang 404 riêng |
| Biểu đồ | Mở `/thongke/` | Thấy biểu đồ, không phải khung trắng |
| Trợ lý | Mở `/troly/`, hỏi "còn vé không" | Trả lời có số chỗ |
| AI | Mở bảng công việc, bấm AI gợi ý | Có gợi ý, **hoặc** báo dùng danh sách mặc định — cả hai đều đúng |
| HTTPS | Nhìn thanh địa chỉ | Có ổ khoá |

Nếu mất CSS: chưa chạy `collectstatic`, hoặc quên đặt `DEBUG=False`.

Nếu lỗi `DisallowedHost`: `ALLOWED_HOSTS` chưa có tên miền của host.

---

## 5. Những lỗi đã được xử lý sẵn trong code

Ghi phần này vào chương "Triển khai" của báo cáo, nó cho thấy nhóm đã lường
trước vấn đề chứ không phải deploy xong mới chữa cháy.

| Vấn đề khi deploy | Cách dự án xử lý |
|---|---|
| `DEBUG=False` thì Django không phục vụ file static | Gắn WhiteNoise, nén và thêm mã băm vào tên file để browser cache đúng |
| Thư viện minified trỏ tới file `.map` không tồn tại làm `collectstatic` chết | Đã bỏ dòng `sourceMappingURL` khỏi các file trong `static/vendor/` |
| Wifi chập chờn làm mất CSS nếu dùng CDN | Bootstrap và Chart.js tải sẵn về `static/vendor/`, không phụ thuộc mạng |
| Host free chỉ có PostgreSQL | `settings.py` nhận `DB_ENGINE=postgres` và cả `DATABASE_URL`. Nhờ dùng ORM nên không sửa dòng code nghiệp vụ nào |
| Trang lỗi mặc định trắng trơn | Có `403.html`, `404.html`, `500.html` riêng |
| Ảnh upload mất sau redeploy | Ảnh bìa mặc định để trong `static/` nên không bao giờ mất |
| Host chặn gọi API ra ngoài | Chức năng AI có fallback, hệ thống vẫn chạy bình thường |
| Bật HTTPS khi chưa có SSL làm site không vào được | Nhóm cấu hình HTTPS tách riêng sau biến `USE_HTTPS` |
| Vé chờ thanh toán quá hạn không ai dọn | Lệnh `release_expired` đặt vào cron |

---

## 6. Bảo mật khi deploy

- `DEBUG=False`. Để `True` trên môi trường thật là hiện nguyên trang lỗi
  kèm mã nguồn và biến môi trường cho bất kỳ ai gõ sai URL.
- `SECRET_KEY` sinh ngẫu nhiên, khác với môi trường dev, không commit.
- `ALLOWED_HOSTS` khai báo đúng tên miền, không để `*`.
- `USE_HTTPS=True` khi host đã có SSL.
- File `.env` không commit. Kiểm tra lại bằng `git ls-files | grep .env`.
- Đổi mật khẩu các tài khoản demo, hoặc xoá hẳn nếu deploy để dùng thật.

Kiểm tra tự động bằng lệnh có sẵn của Django:

```bash
DEBUG=False USE_HTTPS=True python manage.py check --deploy
```

Phải ra `System check identified no issues`.
