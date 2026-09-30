# Hệ thống hỗ trợ tổ chức sự kiện cho câu lạc bộ sinh viên

Đồ án môn **Công nghệ phần mềm** — Django 5 + MySQL.

Hệ thống hỗ trợ trọn vòng đời một sự kiện CLB: chuẩn bị (phân công công việc
BTC) → mở đăng ký / bán vé → check-in → thu phản hồi và thống kê. Có tích hợp
AI để gợi ý công việc và tóm tắt phản hồi, cùng một trợ lý tra cứu chạy nội bộ.

Dự án đã sẵn sàng deploy lên host thật — xem `docs/huong-dan-deploy.md`.

---

## 1. Chạy dự án

### Cách nhanh nhất (không cần cài MySQL)

Dùng cho bạn làm frontend hoặc khi chỉ muốn xem giao diện.

```bash
pip install -r requirements.txt

# Tạo file .env
cp .env.example .env
# Mở .env, sửa dòng DB_ENGINE thành: DB_ENGINE=sqlite

python manage.py migrate
python manage.py seed_demo          # nạp dữ liệu demo
python manage.py runserver
```

Mở http://127.0.0.1:8000

### Chạy với MySQL (không bắt buộc)

SQLite đã đủ để chạy và demo mọi chức năng, **kể cả race condition**: SQLite
được cấu hình `transaction_mode=IMMEDIATE`, nên 2 người cùng đặt chỗ cuối thì
chỉ 1 người thành công, người kia nhận "hết chỗ" (đã đo 10/10 lần). Khác biệt
duy nhất khi trình bày: SQLite khoá cả file DB, còn MySQL khoá đúng dòng loại vé
bằng `SELECT ... FOR UPDATE`. Muốn demo đúng cơ chế khoá dòng thì dùng MySQL:

```bash
# 1. Tạo database trong MySQL
mysql -u root -p
CREATE DATABASE clubevent CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
exit

# 2. Cấu hình .env
cp .env.example .env
# Sửa DB_NAME, DB_USER, DB_PASSWORD cho khớp máy mình

# 3. Migrate và nạp dữ liệu
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

### Tài khoản demo

Mật khẩu chung: **`demo1234`**

| Tên đăng nhập | Vai trò | Dùng để demo |
|---|---|---|
| `admin` | Admin | Quản lý tài khoản, gán role, xem nhật ký |
| `truongbtc` | Trưởng BTC | Tạo sự kiện, phân công việc, xem thống kê |
| `btc1`, `btc2` | Thành viên BTC | Nhận việc, xác nhận thanh toán, check-in |
| `thanhvien`, `thanhvien2` | Thành viên | Đăng ký vé, gửi đánh giá |

### Dữ liệu demo

| Sự kiện | Trạng thái | Dùng để demo |
|---|---|---|
| Acoustic Night #5 | Mở đăng ký, còn nhiều chỗ | Đặt vé, giới hạn 4 vé, công việc BTC |
| Workshop Guitar | Mở đăng ký, **còn đúng 1 chỗ** | **Race condition** — 2 người cùng đặt chỗ cuối |
| Minishow Tròn | Đã diễn ra | Thống kê, phản hồi, AI tóm tắt, ngân sách, giấy chứng nhận (`thanhvien` đã check-in) |
| Giao lưu Guitar liên CLB | Mở đăng ký, **hết vé** | Danh sách chờ (đã có 3 người chờ) |

Nạp lại từ đầu: `python manage.py seed_demo --reset`

---

## Tính năng chính

| Nhóm | Chức năng |
|---|---|
| Sự kiện | Máy trạng thái, loại vé, **danh mục** + lọc kết hợp, **lịch tháng**, giờ kết thúc, **tải file lịch `.ics`**, chia sẻ link |
| Vé | Đặt vé chống race condition, **mã giao dịch nhóm + VietQR** chuyển khoản, **danh sách chờ tự cấp vé**, in vé / lưu PDF, huỷ vé |
| BTC | Xác nhận thanh toán **theo nhóm** (tìm theo nội dung CK), check-in bằng **camera QR** + bảng điểm danh cập nhật 5 giây, công việc Kanban + AI gợi ý, **ngân sách thu–chi** + CSV |
| Thông báo | **Chuông trong app** + email: đặt vé, xác nhận, hết hạn, huỷ sự kiện, cấp vé từ danh sách chờ, **nhắc lịch 24h**, giao việc |
| Thành viên | Hồ sơ + **lịch sử tham gia**, **giấy chứng nhận** in A4 có QR xác thực công khai, gửi đánh giá |
| Quản trị | Phân quyền 4 vai trò, khoá tài khoản, nhật ký thao tác, thống kê tổng hợp |

---

## 2. Cấu hình AI (không bắt buộc)

Hệ thống chạy bình thường khi không có AI — sẽ dùng danh sách công việc mặc
định thay cho gợi ý AI. Muốn bật AI thật thì thêm vào `.env`:

```
AI_PROVIDER=gemini
AI_API_KEY=<key của bạn>
AI_MODEL=gemini-3.6-flash
```

Hoặc dùng OpenAI: `AI_PROVIDER=openai`, `AI_MODEL=gpt-4o-mini`.

**Không commit file `.env` lên Git.** File `.gitignore` đã chặn sẵn.

---

## 3. Cấu trúc code

Mỗi app Django ứng với một module trong SRS:

```
config/          Settings, URL gốc
accounts/        M1 - Tài khoản & phân quyền (4 role) + nhật ký thao tác
events/          M2 - Quản lý sự kiện, loại vé, máy trạng thái sự kiện
organizing/      M3 - Phân công công việc BTC
registrations/   M4 - Đăng ký vé + M5 - Check-in
feedback/        M6 - Phản hồi & thống kê
aiassist/        Tích hợp AI + trợ lý tra cứu rule-based
templates/       Giao diện (Bootstrap 5)
static/vendor/   Bootstrap và Chart.js tải sẵn về, KHÔNG dùng CDN
docs/            Tài liệu, kịch bản demo, bảng test case, hướng dẫn deploy
```

Vì sao Bootstrap và Chart.js để trong `static/vendor/` chứ không lấy từ CDN:
wifi phòng học chập chờn là mất sạch giao diện giữa lúc demo. Để sẵn trong
dự án thì rút mạng vẫn chạy.

Kiến trúc tách 3 tầng theo MVC:

- **View** (`views.py`) chỉ nhận request và trả response.
- **Service** (`services.py`) chứa toàn bộ quy tắc nghiệp vụ.
- **Model** (`models.py`) truy cập dữ liệu và máy trạng thái.

Nhờ tách Service mà quy tắc nghiệp vụ test được bằng unit test, không cần
dựng HTTP request.

### Các file nên đọc trước khi bảo vệ

| File | Nội dung |
|---|---|
| `registrations/services.py` | Đặt vé có transaction, check-in — phần kỹ thuật quan trọng nhất |
| `accounts/permissions.py` | Phân quyền kiểm tra ở server |
| `events/models.py` | Máy trạng thái sự kiện (`ALLOWED_TRANSITIONS`) |
| `aiassist/services.py` | Gọi AI có fallback khi lỗi |
| `aiassist/chatbot.py` | Trợ lý tra cứu: nhận diện ý định, không gọi API ngoài |
| `config/settings.py` | Các quy tắc nghiệp vụ tập trung ở cuối file |

---

## 4. Kiểm thử

```bash
python manage.py test                 # chạy toàn bộ 200 test
python manage.py test registrations   # chỉ test đặt vé và check-in
python manage.py test aiassist        # chỉ test AI và trợ lý tra cứu
```

Test chạy hơi lâu (khoảng 30 giây) vì bcrypt băm mật khẩu chậm có chủ đích —
đó là tính năng bảo mật, không phải lỗi.

Mã test khớp với bảng test case trong báo cáo (`TC07-x`, `TC10-x`) để điền
RTM. Test đáng chú ý:

- `RaceConditionTests` — 2 thread cùng đặt chỗ cuối, đúng 1 người thành công.
- `CheckInTests` — 3 kết quả check-in theo đặc tả UC10.
- `UrlPermissionTests` — gõ URL không đúng quyền thì bị 403.
- `SuggestTasksFallbackTests` — AI lỗi thì hệ thống vẫn chạy.
- `AnswerTests` — trợ lý tra cứu, gồm cả test không được lộ vé của người khác.

---

## 5. Quy tắc nghiệp vụ chính

Đặt tập trung ở cuối `config/settings.py` cho dễ sửa và dễ test:

| Hằng số | Giá trị | Ý nghĩa |
|---|---|---|
| `MAX_TICKETS_PER_USER_PER_EVENT` | 4 | Tối đa 4 vé/người/sự kiện |
| `PAYMENT_DEADLINE_HOURS` | 24 | Vé chờ thanh toán quá 24h thì tự huỷ |
| `CANCEL_BEFORE_HOURS` | 24 | Huỷ vé trước giờ diễn ra 24h |
| `FEEDBACK_WINDOW_DAYS` | 7 | Gửi đánh giá trong 7 ngày sau sự kiện |

Máy trạng thái:

- **Sự kiện:** Đang chuẩn bị → Mở đăng ký → Đóng đăng ký → Đã diễn ra, hoặc → Đã huỷ
- **Vé:** Chờ thanh toán → Đã xác nhận → Đã check-in, hoặc → Đã huỷ
- **Công việc:** Chưa làm → Đang làm → Xong

---

## 6. Lệnh quản trị

```bash
python manage.py seed_demo            # nạp dữ liệu demo
python manage.py seed_demo --reset    # xoá hết rồi nạp lại
python manage.py run_periodic         # tác vụ định kỳ: huỷ vé quá hạn, dọn danh sách chờ,
                                      # nhắc lịch 24h, xoá thông báo cũ (chạy mỗi 15 phút)
python manage.py release_expired      # chỉ huỷ vé quá hạn thanh toán, trả lại chỗ
python manage.py send_reminders       # chỉ gửi nhắc lịch
python manage.py createsuperuser      # tạo tài khoản vào /admin/
python manage.py collectstatic        # gom file static, chỉ cần khi deploy
```

Khi deploy thật, đưa `run_periodic` vào cron chạy mỗi 15 phút:

```
*/15 * * * * cd /duong/dan/du-an && python manage.py run_periodic
```

> **Cảnh báo:** đổi `SECRET_KEY` sẽ làm **mọi giấy chứng nhận đã cấp mất hiệu
> lực xác thực** (mã xác thực là chữ ký theo khoá này). Không đổi khoá tuỳ tiện.

---

## 7. Phân công và quy ước Git

| Người | Phụ trách |
|---|---|
| A (leader) | PM, SRS, review PR, `aiassist/`, deploy |
| B | Phân tích & thiết kế, sau đó `organizing/` và `feedback/` |
| C | `accounts/`, `events/`, `registrations/` |
| D | `templates/`, `static/` |
| E | Test case, `tests.py`, seed data, tài liệu |

Quy ước:

- Nhánh `main` luôn phải chạy được. Không push thẳng vào `main`.
- Code trên nhánh `feature/<tên-chức-năng>`, merge qua Pull Request, cần 1
  người review.
- Comment trong code viết bằng tiếng Việt.
- Đổi model thì phải chạy `makemigrations` và commit cả file migration.
