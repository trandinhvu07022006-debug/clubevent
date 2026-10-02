# LỆNH: Kế hoạch phát triển chức năng - bản chi tiết tới từng bước logic

> Bạn là **backend + fullstack engineer** tiếp quản dự án KMG Club. Tài liệu này
> mô tả ĐẦY ĐỦ logic cho từng chức năng mới: dữ liệu, luồng xử lý, trường hợp
> biên, bảo mật, test. **Làm đúng thứ tự Sprint ở mục 3**, vì các chức năng phụ
> thuộc nhau. Chỗ nào tài liệu đã quyết định thì làm theo; chỗ nào thấy sai thì
> DỪNG và hỏi, đừng tự đổi thiết kế.

---

## 0. Ràng buộc bất di bất dịch

1. **No-CDN.** Mọi thư viện front-end self-host trong `static/vendor/` (kèm file
   LICENSE). Wifi phòng học chập chờn là mất sạch lúc demo.
2. **Không thêm hạ tầng nặng:** KHÔNG Celery, KHÔNG Redis, KHÔNG Django
   Channels/WebSocket, KHÔNG reportlab. Tác vụ định kỳ dùng management command;
   cập nhật "thời gian thực" dùng polling.
3. **Giữ kiến trúc tầng service.** Logic nghiệp vụ nằm trong `services.py`, view
   chỉ nhận request/trả response (đọc docstring đầu `registrations/services.py`).
   Lỗi nghiệp vụ ném exception riêng (kiểu `BookingError`), view bắt và hiện
   `messages.error`.
4. **Mọi thao tác ghi quan trọng phải `@transaction.atomic`**, và thao tác nào
   đụng vào số chỗ (`TicketType.sold`) phải khoá dòng bằng `select_for_update()`
   - đúng như `book_tickets()` đang làm.
5. **Tác dụng phụ (gửi email, tạo thông báo) chỉ chạy SAU KHI commit**, bằng
   `transaction.on_commit(...)`. Lý do ở mục 1.2.
6. **Hành động quan trọng ghi `AuditLog.write(user, action, target, note)`.**
7. **Giữ 87 test cũ PASS** và viết test mới cho mỗi chức năng; cập nhật
   `docs/bang-test-case.md` theo mã chức năng ở mục 2.
8. **Chạy được trên MySQL** (DB demo chính), không chỉ SQLite. Có một bẫy
   MySQL ở mục 4.3 - đọc kỹ.
9. Giao diện, comment, thông báo lỗi: **tiếng Việt**. Màu lấy từ token trong
   `static/css/app.css`; nút tuân theo mục 13 "VÙNG CHẠM" của file đó.

---

## 1. Hiện trạng đã khảo sát (đừng khảo sát lại, đọc ở đây)

### 1.1. Đã có

| Mô-đun | Có gì | File chính |
|---|---|---|
| M1 Tài khoản | 4 vai trò MEMBER/STAFF/LEAD/ADMIN, đăng ký (bắt buộc email, MSSV), đăng nhập, đổi mật khẩu, khoá tài khoản, nhật ký | `accounts/` |
| M2 Sự kiện | Máy trạng thái `ALLOWED_TRANSITIONS`, loại vé có quota | `events/models.py` |
| M3 Công việc | Kanban, giao việc, AI gợi ý | `organizing/` |
| M4 Vé | Đặt vé chống race condition, huỷ vé, xác nhận thanh toán thủ công, tự huỷ vé quá hạn (`release_expired`), xuất CSV | `registrations/services.py` |
| M5 Check-in | Gõ mã → 3 kết quả OK/USED/INVALID, có khoá dòng | `registrations/services.py::check_in` |
| M6 Phản hồi | Đánh giá sao + AI tóm tắt | `feedback/` |

Hằng số cấu hình đang có (`config/settings.py:233-236`):
`MAX_TICKETS_PER_USER_PER_EVENT=4`, `PAYMENT_DEADLINE_HOURS=24`,
`CANCEL_BEFORE_HOURS=24`, `FEEDBACK_WINDOW_DAYS=7`.

Mã vé: `uuid4().hex[:12].upper()` → luôn khớp regex `^[0-9A-F]{12}$`.
Ảnh QR trên vé chứa **đúng mã vé**, không chứa URL (`registrations/views.py::my_tickets`).

### 1.2. Chưa có (đã grep toàn bộ code để xác nhận)

Không có: email (`send_mail`, `EMAIL_BACKEND`), quên mật khẩu, quét QR bằng
camera, thông tin chuyển khoản, danh sách chờ, thông báo trong app, file lịch
`.ics`, danh mục sự kiện, lịch sử/chứng nhận tham gia, context processor tự viết.

### 1.3. Lỗi/khiếm khuyết CÓ SẴN phát hiện khi khảo sát - sửa trong kế hoạch này

| # | Vấn đề | Ở đâu | Sửa ở |
|---|---|---|---|
| B1 | Huỷ sự kiện dùng `.update()` đổi hàng loạt vé sang CANCELLED - **không báo cho ai**, không trả `sold`, và sau khi `.update()` thì không còn biết ai từng giữ vé | `events/views.py:112-117` | 5.3 |
| B2 | Hạn thanh toán = lúc đặt + 24h, **có thể rơi SAU giờ diễn ra** (đặt lúc 20h, sự kiện 8h sáng mai → hạn thanh toán 20h mai) | `release_expired_tickets` | 5.2 |
| B3 | Email chỉ được kiểm trùng ở form đăng ký, **không có ràng buộc unique ở DB**. Hiện 42/42 user có email, 0 trùng - nhưng không có gì bảo đảm về sau | `accounts/forms.py:11` | 4.1 |
| B4 | `Event` không có giờ kết thúc (`ends_at`) - cần cho file lịch và tính "đang diễn ra" | `events/models.py` | 9.2 |

---

## 2. Danh mục chức năng mới và mã truy vết

Theo quy ước mã hiện có trong `bang-test-case.md` (M = mô-đun, F = chức năng).

| Mã | Chức năng | Mô-đun | Sprint |
|---|---|---|---|
| **F7.0** | Nền tảng thông báo (email + trong app, một cửa vào duy nhất) | M7 mới | 1 |
| **F1.4** | Quên mật khẩu | M1 | 1 |
| **F5.3** | Quét QR bằng camera | M5 | 2 |
| **F5.4** | Màn hình điểm danh cập nhật liên tục | M5 | 2 |
| **F4.7** | Mã giao dịch nhóm + VietQR chuyển khoản | M4 | 3 |
| **F7.1** | Email/thông báo theo sự kiện nghiệp vụ | M7 | 3 |
| **F4.8** | Danh sách chờ | M4 | 4 |
| **F7.2** | Nhắc lịch trước 24h | M7 | 4 |
| **F7.3** | Chuông thông báo trong app | M7 | 5 |
| **F7.4** | Thêm vào lịch (`.ics`) | M7 | 5 |
| **F2.5** | Danh mục sự kiện | M2 | 5 |
| **F8.1** | Lịch sử tham gia | M8 mới | 5 |
| **F8.2** | Giấy chứng nhận + trang tra cứu | M8 | 5 |

Giai đoạn 3 (ngân sách, album, thành viên CLB, webhook ngân hàng) chỉ phác thảo
ở mục 11 - **không làm** khi chưa xong Sprint 1-5.

---

## 3. Thứ tự Sprint và phụ thuộc

```
Sprint 1:  F7.0 nền tảng thông báo ──┬──> F1.4 quên mật khẩu
                                     │
Sprint 2:  F5.3 camera, F5.4 điểm danh   (độc lập, làm song song được)
                                     │
Sprint 3:  F4.7 mã nhóm + VietQR ────┼──> F7.1 email nghiệp vụ (cần F4.7 để gửi QR)
                                     │
Sprint 4:  F4.8 danh sách chờ ───────┘    F7.2 nhắc lịch
Sprint 5:  F7.3 chuông · F7.4 .ics · F2.5 danh mục · F8.1-F8.2 chứng nhận
```

**Cuối mỗi Sprint DỪNG lại**: chạy toàn bộ test, chụp màn hình các trang mới
(cả theme sáng/tối), báo cáo để duyệt rồi mới sang Sprint sau.

---

## 4. SPRINT 1

### 4.1. F7.0 - Nền tảng thông báo

**Mục tiêu:** mọi chỗ cần báo cho người dùng chỉ gọi MỘT hàm. Hàm đó tự lo:
tạo thông báo trong app, gửi email, không bao giờ làm hỏng nghiệp vụ chính.

#### Cấu hình - thêm vào `config/settings.py`

```python
# --- Email ---
# Dev/demo: in email ra terminal, KHÔNG cần mạng. Deploy: đổi sang SMTP qua .env.
EMAIL_BACKEND = env("EMAIL_BACKEND",
                    "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", "")
EMAIL_PORT = int(env("EMAIL_PORT", "587"))
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_TIMEOUT = 10          # BẮT BUỘC: SMTP treo sẽ treo luôn request người dùng
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "KMG Club <no-reply@kmgclub.local>")

# Địa chỉ gốc để tạo link TUYỆT ĐỐI trong email. Cần vì lệnh chạy định kỳ
# (nhắc lịch) không có request để suy ra tên miền.
SITE_URL = env("SITE_URL", "http://127.0.0.1:8000").rstrip("/")
```

Thêm các biến tương ứng vào `.env.example` (có comment tiếng Việt, để trống giá trị bí mật).

#### Model - app mới `notifications`

```python
class NotificationKind(models.TextChoices):
    TICKET_CONFIRMED = "TICKET_OK", "Vé đã xác nhận"
    TICKET_PENDING   = "TICKET_PEND", "Vé chờ thanh toán"
    TICKET_EXPIRED   = "TICKET_EXP", "Vé hết hạn thanh toán"
    EVENT_CANCELLED  = "EVENT_CXL", "Sự kiện bị huỷ"
    EVENT_REMINDER   = "REMINDER", "Nhắc lịch"
    WAITLIST_PROMOTED= "WAIT_OK", "Có vé từ danh sách chờ"
    TASK_ASSIGNED    = "TASK", "Được giao việc"

class Notification(models.Model):
    user       = FK(User, CASCADE, related_name="notifications")
    kind       = CharField(max_length=12, choices=NotificationKind.choices)
    title      = CharField(max_length=120)
    message    = CharField(max_length=255)
    url        = CharField(max_length=255, blank=True)   # đường dẫn NỘI BỘ, vd "/ve/cua-toi/"
    is_read    = BooleanField(default=False)
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "is_read", "-created_at"])]
```

Chỉ tạo model ở Sprint 1 (để F7.1 ghi vào được). Giao diện chuông làm ở F7.3.

#### Hàm dùng chung - `notifications/services.py`

```python
logger = logging.getLogger(__name__)

def notify(user, kind, title, message, url="", email_template=None, context=None):
    """
    CỬA VÀO DUY NHẤT để báo cho người dùng. Gọi từ bất kỳ service nào.

    - Luôn tạo Notification (trong app).
    - Nếu có email_template và user có email: gửi email.
    - KHÔNG BAO GIỜ ném lỗi ra ngoài: gửi mail lỗi thì ghi log và bỏ qua.
      Đặt vé thành công mà báo lỗi vì SMTP chết là sai.
    - Phải gọi SAU KHI commit (xem notify_on_commit).
    """
    Notification.objects.create(user=user, kind=kind, title=title[:120],
                                message=message[:255], url=url)
    if email_template and user.email:
        try:
            send_templated_email(email_template, {**(context or {}), "user": user,
                                 "site_url": settings.SITE_URL}, [user.email])
        except Exception:                     # SMTP, timeout, template lỗi...
            logger.exception("Gửi email '%s' cho user %s thất bại",
                             email_template, user.pk)


def notify_on_commit(*args, **kwargs):
    """Dùng hàm này bên trong service @transaction.atomic."""
    transaction.on_commit(lambda: notify(*args, **kwargs))


def send_templated_email(template, context, recipients):
    """
    Render 3 file: templates/emails/<template>_subject.txt  (1 dòng)
                   templates/emails/<template>.txt          (bản chữ thuần)
                   templates/emails/<template>.html         (bản HTML)
    Gửi bằng EmailMultiAlternatives (bản chữ + bản HTML).
    """
```

**Vì sao `on_commit` là BẮT BUỘC:** `book_tickets()` chạy trong
`@transaction.atomic`. Nếu gửi email bên trong rồi một bước sau lỗi → giao
dịch rollback, vé KHÔNG tồn tại, nhưng email "đặt vé thành công" **đã bay đi,
không thu hồi được**. `on_commit` chỉ chạy khi dữ liệu đã thật sự được lưu.
Lưu ý phụ: nếu `on_commit` được gọi khi không ở trong transaction, Django chạy
ngay lập tức - vẫn đúng.

**Gửi hàng loạt** (huỷ sự kiện có 100 người): mở MỘT kết nối
`get_connection()` rồi `connection.send_messages(list)`, không mở 100 kết nối.
Viết thêm `notify_many(users, ...)` dùng cách này.

**Template email:** HTML đơn giản, CSS inline (trình đọc mail bỏ `<style>`),
không ảnh ngoài. Luôn có link tuyệt đối `{{ site_url }}...`.

#### Test F7.0

| Mã | Tình huống | Mong đợi |
|---|---|---|
| T7.0.1 | Gọi `notify` với template | 1 Notification + `len(mail.outbox)==1` |
| T7.0.2 | User không có email | Có Notification, không có mail, không lỗi |
| T7.0.3 | Backend email ném lỗi (mock `send_templated_email` raise) | Không ném ra ngoài, Notification vẫn tạo, có log |
| T7.0.4 | `notify_on_commit` trong transaction bị rollback | 0 Notification, 0 mail (dùng `self.captureOnCommitCallbacks(execute=True)` trong TestCase) |

### 4.2. F1.4 - Quên mật khẩu

Dùng view có sẵn của Django, **không tự viết logic token**.

#### URL - thêm vào `accounts/urls.py`

| URL | View Django | Template |
|---|---|---|
| `quenmatkhau/` | `PasswordResetView` | `accounts/password_reset_form.html` |
| `quenmatkhau/dagui/` | `PasswordResetDoneView` | `accounts/password_reset_done.html` |
| `datlai/<uidb64>/<token>/` | `PasswordResetConfirmView` | `accounts/password_reset_confirm.html` |
| `datlai/xong/` | `PasswordResetCompleteView` | `accounts/password_reset_complete.html` |

Vì các URL nằm trong namespace `accounts`, phải truyền `success_url=reverse_lazy("accounts:...")`
cho từng view - mặc định Django tìm tên không có namespace và sẽ lỗi `NoReverseMatch`.

Cấu hình PasswordResetView: `email_template_name="emails/password_reset.txt"`,
`html_email_template_name="emails/password_reset.html"`,
`subject_template_name="emails/password_reset_subject.txt"`,
`form_class=AppPasswordResetForm`.

Thêm link "Quên mật khẩu?" vào `accounts/login.html`, ngay dưới ô mật khẩu.

#### Logic

```python
class AppPasswordResetForm(PasswordResetForm):
    def get_users(self, email):
        # Không gửi link cho tài khoản bị khoá: có đặt lại được mật khẩu thì
        # vẫn không đăng nhập được (confirm_login_allowed chặn), chỉ gây rối.
        return (u for u in super().get_users(email) if not u.is_locked)
```

`settings.PASSWORD_RESET_TIMEOUT = 2 * 60 * 60`  (link sống 2 giờ, mặc định Django là 3 ngày - quá dài).

**Quy tắc bảo mật - KHÔNG được vi phạm:**
- Email có tồn tại hay không, màn hình **đều hiện cùng một câu** "Nếu email có
  trong hệ thống, bạn sẽ nhận được link". Không bao giờ báo "email không tồn
  tại" - kẻ xấu sẽ dùng nó dò danh sách email. (Django đã làm đúng mặc định,
  đừng "cải tiến" chỗ này.)
- Token tự hết hiệu lực sau khi đổi mật khẩu thành công (Django băm cả mật khẩu
  hiện tại vào token) - không cần làm gì thêm.
- **Chặn spam:** tối đa 5 yêu cầu/giờ mỗi session, dùng đúng mẫu
  `_is_rate_limited` trong `aiassist/views.py`. Vượt ngưỡng vẫn hiện trang
  "đã gửi" (không lộ thông tin), chỉ là không gửi mail.
- Khi đặt lại thành công: `AuditLog.write(user, "Đặt lại mật khẩu", user.username)`
  - làm bằng cách override `form_valid` của `PasswordResetConfirmView`.

**Sửa B3 (email không unique ở DB):** thêm migration ràng buộc unique cho
`User.email`... NHƯNG `email` là trường kế thừa từ `AbstractUser`, không đổi
`unique=True` trực tiếp được. Làm bằng
`Meta.constraints = [UniqueConstraint(Lower("email"), name="uniq_user_email_ci",
condition=~Q(email=""))]`. **Cảnh báo:** MySQL không hỗ trợ ràng buộc có
`condition` (xem 4.3 - Django chỉ cảnh báo W036 rồi bỏ qua). Vì vậy: tạo
constraint để chạy trên SQLite/PostgreSQL, **và** giữ kiểm tra trùng ở form,
**và** sửa `clean_email` của RegisterForm so sánh không phân biệt hoa thường
(`email__iexact`). Trước khi migrate, chạy câu truy vấn kiểm tra trùng (hiện tại: 0).

#### Test F1.4

| Mã | Tình huống | Mong đợi |
|---|---|---|
| T1.4.1 | Email tồn tại | 1 mail, có link `/taikhoan/datlai/` |
| T1.4.2 | Email không tồn tại | 0 mail, **cùng trang "đã gửi"** |
| T1.4.3 | Email của tài khoản bị khoá | 0 mail, cùng trang "đã gửi" |
| T1.4.4 | Mở link, đặt mật khẩu mới | Đăng nhập được bằng mật khẩu mới, có AuditLog |
| T1.4.5 | Dùng lại link cũ lần 2 | Báo link không hợp lệ |
| T1.4.6 | Gửi 6 yêu cầu trong 1 giờ | Chỉ 5 mail |
| T1.4.7 | Email viết hoa `ABC@X.COM` khi user lưu `abc@x.com` | Vẫn nhận mail (Django so sánh không phân biệt hoa thường) |

### 4.3. BẪY MySQL - đọc trước khi viết bất kỳ ràng buộc nào

- **`UniqueConstraint(..., condition=...)` KHÔNG hoạt động trên MySQL.** Django
  bỏ qua kèm cảnh báo `models.W036`. Mọi quy tắc "duy nhất có điều kiện" phải
  được bảo đảm ở tầng service bằng khoá dòng (xem 7.1).
- `select_for_update()` trên SQLite là no-op (SQLite khoá cả file). Test race
  condition thật phải chạy trên MySQL - giống ghi chú trong `kich-ban-demo.md`.
- Chạy `python manage.py check --deploy` và `makemigrations --check` trên MySQL
  trước khi báo xong Sprint.

---

## 5. SPRINT 2

### 5.1. F5.3 - Quét QR bằng camera

**Nguyên tắc:** camera là lớp TĂNG CƯỜNG. Ô gõ tay hiện có **phải luôn còn** và
luôn dùng được. Bất cứ khi nào camera không khả dụng → im lặng rơi về gõ tay.

#### Backend - endpoint JSON mới

`POST /ve/checkin/<event_id>/quet/` → name `registrations:checkin_scan`,
decorator `@staff_required` + `@require_POST`. **Không viết logic check-in mới**:
gọi lại `check_in(request.user, code, event=event)` có sẵn.

Request: `{"code": "A1B2C3D4E5F6"}`, header `X-CSRFToken` (lấy từ cookie/form như `chatbot.js`).

Response 200:
```json
{
  "result": "OK" | "USED" | "INVALID",
  "message": "Hợp lệ. Mời Nguyễn Văn A vào.",
  "attendee": {"name": "Nguyễn Văn A", "mssv": "2021xxxx", "ticket_type": "Vé thường"} | null,
  "done": 57,
  "total": 100
}
```
`attendee` = null khi không tìm thấy vé. `done/total` tính giống view `checkin` hiện có
- tách phần tính này thành hàm `checkin_progress(event)` trong services để 2 view dùng chung.

Body không phải JSON hợp lệ → 400 `{"result":"INVALID","message":"Dữ liệu không hợp lệ."}`.

#### Frontend - `static/js/qr-scan.js` (file mới, nạp ở `checkin.html`)

**Chọn bộ giải mã (theo thứ tự):**
1. `BarcodeDetector` có sẵn của trình duyệt, nếu `await BarcodeDetector.getSupportedFormats()`
   chứa `"qr_code"` (Chrome Android, Edge).
2. Không có → nạp **lười** (chỉ khi bấm "Bật camera") thư viện **jsQR** tự host tại
   `static/vendor/jsqr/jsQR.js` (giấy phép Apache-2.0, ghi rõ phiên bản và kèm LICENSE).
   Cần cho **iPhone/Safari và Firefox** - chúng không có BarcodeDetector.

**Luồng chạy - viết đúng thứ tự này:**

```
0. Khi tải trang:
   nếu KHÔNG (window.isSecureContext && navigator.mediaDevices?.getUserMedia):
       ẩn nút "Bật camera"
       hiện dòng nhỏ: "Camera cần kết nối HTTPS. Đang dùng chế độ nhập mã."
       DỪNG (ô gõ tay vẫn hoạt động như cũ)

1. Bấm "Bật camera":
   stream = getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false })
     - NotAllowedError  -> "Bạn đã chặn quyền camera. Mở cài đặt trình duyệt để cho phép."
     - NotFoundError    -> "Không tìm thấy camera."
     - lỗi khác         -> "Không bật được camera." ; mọi trường hợp: về chế độ gõ tay
   gắn stream vào <video autoplay muted playsinline>
       (THIẾU playsinline thì iPhone mở video toàn màn hình và vỡ giao diện)

2. Vòng quét:
   dùng requestAnimationFrame nhưng CHỈ giải mã mỗi 120ms (~8 lần/giây) - đủ nhanh,
   đỡ nóng máy và tốn pin.
   Với jsQR: vẽ khung hình lên <canvas> thu nhỏ còn rộng 640px, lấy ImageData,
   gọi jsQR(data, w, h, { inversionAttempts: "dontInvert" }).
   Nếu state == BUSY: bỏ qua khung hình.

3. Đọc được chuỗi raw:
   code = raw.trim().toUpperCase()
   nếu code KHÔNG khớp /^[0-9A-F]{12}$/:
       báo đỏ "Đây không phải mã vé KMG Club" - KHÔNG gọi server
       (người dùng hay đưa nhầm QR khác: link Zalo, mã chuyển khoản...)
       tiếp tục quét
   nếu code == lastCode và (bây giờ - lastTime) < 3000ms:
       bỏ qua (camera đọc lại cùng một vé nhiều lần/giây -> nếu không chặn,
       lần 2 sẽ báo vàng "đã check-in" ngay sau khi vừa báo xanh, gây hoang mang)
   state = BUSY; lastCode = code; lastTime = now
   POST tới checkin_scan

4. Nhận kết quả:
   phủ màn hình màu theo result: OK=xanh, USED=vàng, INVALID=đỏ (tái dùng đúng
   3 màu của trang check-in hiện tại), chữ to: tên + loại vé + message
   rung: navigator.vibrate?.(OK ? 120 : [80, 60, 80])
   tiếng bíp bằng WebAudio (OscillatorNode, 880Hz cho OK, 220Hz cho lỗi) -
       KHÔNG dùng file âm thanh; tạo AudioContext ở lần chạm "Bật camera"
       (trình duyệt chặn âm thanh khi chưa có thao tác người dùng)
   cập nhật thanh tiến độ done/total
   sau 1800ms: tắt lớp phủ, state = SCANNING

5. Lỗi mạng / server 5xx:
   báo đỏ "Mất kết nối, thử lại", state = SCANNING (không kẹt BUSY)

6. Tiết kiệm tài nguyên:
   document "visibilitychange" -> hidden: dừng mọi track của stream (tắt đèn camera)
                                -> visible: nếu trước đó đang bật thì bật lại
   "pagehide": dừng track
   Nút "Tắt camera" luôn hiện khi camera đang chạy.
```

**Ô gõ tay** vẫn gửi form POST như cũ (không đổi). Có thể nâng cấp nó dùng
chung endpoint JSON để không tải lại trang, nhưng KHÔNG bắt buộc.

#### BẪY DEMO - phải cập nhật `docs/kich-ban-demo.md`

Trình duyệt **chỉ cho mở camera trên HTTPS hoặc `localhost`**. Kịch bản demo
hiện hướng dẫn mở trang check-in trên điện thoại qua `http://<IP LAN>:8000` →
**camera sẽ không bật được**. Sửa kịch bản:
- Cách chính: chạy `ngrok http 8000`, mở link `https://...ngrok...` trên điện thoại.
  Nhớ thêm tên miền ngrok vào `ALLOWED_HOSTS` và `CSRF_TRUSTED_ORIGINS`.
- Dự phòng: dùng ô gõ tay (luôn chạy được).
Ghi rõ điều này trong kịch bản để không "chết" camera trước hội đồng.

#### Test F5.3

Backend (tự động):

| Mã | Tình huống | Mong đợi |
|---|---|---|
| T5.3.1 | POST mã hợp lệ | `result=OK`, `done` tăng 1 |
| T5.3.2 | POST lại cùng mã | `result=USED` |
| T5.3.3 | Mã của sự kiện khác | `INVALID` |
| T5.3.4 | Thành viên thường gọi endpoint | 403 hoặc chuyển trang như `staff_required` |
| T5.3.5 | GET thay vì POST | 405 |
| T5.3.6 | Body không phải JSON | 400 |

Frontend (thủ công, ghi vào bảng test): Android Chrome qua ngrok; iPhone Safari
qua ngrok; laptop không HTTPS → nút camera ẩn, gõ tay chạy; đưa QR chuyển khoản
ngân hàng → báo "không phải mã vé", không gọi server (xem tab Network).

### 5.2. Sửa B2 - hạn thanh toán không được vượt giờ diễn ra

Trong `release_expired_tickets()` và mọi chỗ hiển thị hạn thanh toán, hạn thực tế là:

```python
def payment_deadline(ticket):
    return min(ticket.created_at + timedelta(hours=settings.PAYMENT_DEADLINE_HOURS),
               ticket.event.starts_at)
```

Thêm property `Ticket.payment_deadline` và dùng nó. Điều kiện huỷ trong
`release_expired_tickets` đổi thành: vé PENDING **và** `payment_deadline < now`
(truy vấn: lọc `created_at__lt=now-24h` HOẶC `event__starts_at__lt=now`).
Test: vé đặt 2 giờ trước giờ diễn ra, chạy lệnh sau giờ diễn ra → bị huỷ dù chưa đủ 24h.

### 5.3. Sửa B1 - huỷ sự kiện (làm luôn ở Sprint 2 vì đơn giản, email bổ sung ở Sprint 3)

Chuyển logic trong `events/views.py::event_set_status` nhánh CANCELLED vào
hàm service mới `events/services.py::cancel_event(user, event)`:

```python
@transaction.atomic
def cancel_event(user, event):
    # 1. LẤY DANH SÁCH NGƯỜI BỊ ẢNH HƯỞNG TRƯỚC - sau .update() là mất thông tin
    affected_user_ids = list(event.tickets
                             .exclude(status=TicketStatus.CANCELLED)
                             .values_list("user_id", flat=True).distinct())
    # 2. Đổi trạng thái sự kiện (qua kiểm tra ALLOWED_TRANSITIONS như cũ)
    # 3. Huỷ vé hàng loạt
    event.tickets.exclude(status=TicketStatus.CANCELLED).update(status=TicketStatus.CANCELLED)
    # 4. Trả sold về 0 cho mọi loại vé của sự kiện (sự kiện đã huỷ, cho số liệu nhất quán)
    event.ticket_types.update(sold=0)
    # 5. Huỷ mọi mục danh sách chờ còn hiệu lực (khi đã có F4.8)
    # 6. AuditLog như cũ
    # 7. notify_many(...) qua on_commit - chỉ báo MỖI NGƯỜI MỘT LẦN dù họ giữ 4 vé
    return affected_user_ids
```

Nội dung báo: tên sự kiện, lời xin lỗi, và **nếu có vé đã xác nhận có phí**:
"BTC sẽ liên hệ hoàn tiền" (hệ thống không tự hoàn tiền - nói rõ, đừng hứa).

### 5.4. F5.4 - Màn hình điểm danh cập nhật liên tục

**Không dùng WebSocket.** Polling là đủ cho quy mô CLB.

`GET /ve/checkin/<event_id>/tiendo/` (`@staff_required`) → JSON:
```json
{"done": 57, "total": 100, "percent": 57,
 "by_type": [{"name": "Vé thường", "done": 40, "total": 70}, ...],
 "recent": [{"name": "Nguyễn Văn A", "at": "18:42"}, ...]}      // 10 lượt gần nhất
```
Truy vấn: 1 aggregate `Count` có `filter=Q(status=CHECKED_IN)` nhóm theo loại vé;
`recent` = vé CHECKED_IN sắp theo `-checked_in_at`, `select_related("user")`, lấy 10.

Frontend: trên trang check-in, gọi mỗi **5 giây**; **ngừng gọi khi tab ẩn**
(`document.hidden`), gọi ngay 1 lần khi tab hiện lại. Cập nhật số, thanh tiến
độ (có `aria-valuenow`), danh sách gần nhất. Nhiều BTC check-in ở nhiều cửa sẽ
thấy tổng số chung.

Test: T5.4.1 số liệu đúng sau 3 lần check-in; T5.4.2 thành viên thường bị chặn.

---

## 6. SPRINT 3

### 6.1. F4.7 - Mã giao dịch nhóm + VietQR

#### Vấn đề cần giải trước: một lần đặt nhiều vé

Một lần `book_tickets` có thể tạo tới 4 vé, **mỗi vé một mã riêng**. Người dùng
chuyển khoản MỘT lần cho cả 4 vé. Nội dung chuyển khoản ngân hàng giới hạn
khoảng 25 ký tự và không dấu → không nhét được 4 mã 12 ký tự. Hiện cũng không
có gì gom 4 vé đó lại với nhau.

**Giải pháp:** thêm `Ticket.booking_ref`.

```python
def make_booking_ref():
    # 8 ký tự, bỏ các ký tự dễ nhầm khi đọc/gõ: 0/O, 1/I/L
    alphabet = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
    return "".join(secrets.choice(alphabet) for _ in range(8))

class Ticket:
    booking_ref = CharField("Mã giao dịch", max_length=8, db_index=True, blank=True)
```

- `book_tickets`: sinh MỘT `booking_ref` cho cả lần đặt, gán cho mọi vé trong `bulk_create`.
- Migration: trường `blank=True` default `""`; **data migration** gán cho vé cũ
  `booking_ref = code[:8]` (mỗi vé cũ thành một giao dịch riêng) để không vé
  nào có mã rỗng.
- Không cần unique toàn cục (31^8 ≈ 8.5×10^11 tổ hợp, trùng gần như không thể);
  nhưng khi sinh, thử lại tối đa 5 lần nếu đã tồn tại mã đó trong các vé PENDING.

**Xác nhận theo nhóm** - service mới, giữ `confirm_payment` cũ cho từng vé:

```python
@transaction.atomic
def confirm_booking(staff, booking_ref):
    tickets = list(Ticket.objects.select_for_update()
                   .filter(booking_ref=booking_ref, status=TicketStatus.PENDING))
    if not tickets:
        raise BookingError("Không có vé nào đang chờ thanh toán với mã giao dịch này.")
    now = timezone.now()
    for t in tickets:
        t.status = TicketStatus.CONFIRMED; t.confirmed_at = now
    Ticket.objects.bulk_update(tickets, ["status", "confirmed_at"])
    AuditLog.write(staff, "Xác nhận thanh toán", booking_ref,
                   f"{len(tickets)} vé - {tickets[0].user} - {tickets[0].event.name}")
    notify_on_commit(...)   # F7.1
    return tickets
```

Trang `payment_list`: nhóm hiển thị theo `booking_ref` (tổng tiền, số vé,
người đặt), tìm kiếm theo `booking_ref` **hoặc** mã vé, nút "Xác nhận cả nhóm".

#### VietQR - sinh hoàn toàn offline

Cấu hình `.env`: `BANK_BIN` (6 số, mã ngân hàng NAPAS, vd Vietcombank 970436),
`BANK_ACCOUNT`, `BANK_ACCOUNT_NAME` (không dấu, IN HOA).
**Thiếu bất kỳ biến nào → ẩn toàn bộ phần VietQR**, trang vé hiện như cũ. Không được lỗi.

Nội dung chuyển khoản: `f"KMG {booking_ref}"` → 12 ký tự, chỉ chữ số/chữ hoa ASCII.
Số tiền: tổng `price` các vé PENDING cùng `booking_ref`.

Chuỗi VietQR theo chuẩn EMVCo (mỗi trường = `ID 2 số` + `độ dài 2 số` + `giá trị`):

```python
def tlv(tag, value):
    return f"{tag}{len(value):02d}{value}"

def vietqr_payload(bin_code, account, amount, content):
    merchant = tlv("00", "A000000727") \
             + tlv("01", tlv("00", bin_code) + tlv("01", account)) \
             + tlv("02", "QRIBFTTA")                 # chuyển tới SỐ TÀI KHOẢN
    payload = (tlv("00", "01")                        # phiên bản định dạng
             + tlv("01", "12")                        # 12 = QR động (có số tiền)
             + tlv("38", merchant)
             + tlv("53", "704")                       # VND
             + tlv("54", str(int(amount)))
             + tlv("58", "VN")
             + tlv("62", tlv("08", content))          # nội dung chuyển khoản
             + "6304")                                # CRC: tag+độ dài, chưa có giá trị
    return payload + crc16_ccitt(payload)

def crc16_ccitt(data: str) -> str:
    # CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, không đảo bit, không XOR cuối
    crc = 0xFFFF
    for byte in data.encode("ascii"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return f"{crc:04X}"
```

Ảnh QR: tái dùng `qr_data_uri()` có sẵn trong `registrations/views.py` (chuyển
nó vào một module tiện ích dùng chung, vd `core/qr.py`).

Hiển thị trên "Vé của tôi" với nhóm vé PENDING: ảnh QR + **ghi rõ bằng chữ**
ngân hàng, số tài khoản, chủ tài khoản, số tiền, nội dung chuyển khoản (có nút
sao chép), hạn thanh toán (`payment_deadline` ở 5.2), và câu: "Ghi đúng nội
dung để BTC đối chiếu. Vé chỉ có hiệu lực sau khi BTC xác nhận."

**Không** tự động xác nhận: hệ thống không đọc được tài khoản ngân hàng.

#### Test F4.7

| Mã | Tình huống | Mong đợi |
|---|---|---|
| T4.7.1 | `crc16_ccitt("123456789")` | `"29B1"` (giá trị kiểm chuẩn của CRC-16/CCITT-FALSE) |
| T4.7.2 | `tlv("00","01")` | `"000201"` |
| T4.7.3 | Đặt 3 vé một lần | Cả 3 cùng `booking_ref` |
| T4.7.4 | Hai lần đặt khác nhau | `booking_ref` khác nhau |
| T4.7.5 | `confirm_booking` | Mọi vé PENDING của nhóm → CONFIRMED, 1 AuditLog |
| T4.7.6 | `confirm_booking` khi 1 vé đã bị huỷ | Chỉ xác nhận vé còn PENDING |
| T4.7.7 | Thiếu `BANK_BIN` | Trang vé render bình thường, không có QR |
| T4.7.8 | Data migration | Không còn vé nào `booking_ref == ""` |
| **Thủ công BẮT BUỘC** | Quét QR bằng app ngân hàng thật | App hiện đúng STK, tên, số tiền, nội dung. CRC sai là app từ chối - phải thử thật trước khi báo xong |

### 6.2. F7.1 - Báo theo sự kiện nghiệp vụ

Mọi dòng dưới đây gọi `notify_on_commit` (hoặc `notify_many`) **bên trong
service**, không trong view.

| Sự kiện | Gọi ở | Người nhận | Nội dung chính | Link |
|---|---|---|---|---|
| Đặt vé miễn phí | `book_tickets` | người đặt | Số vé, mã vé, giờ, địa điểm | Vé của tôi |
| Đặt vé có phí | `book_tickets` | người đặt | Số tiền, **VietQR + nội dung CK**, hạn thanh toán | Vé của tôi |
| BTC xác nhận | `confirm_booking` / `confirm_payment` | người đặt | Vé đã có hiệu lực, mang QR đến cửa | Vé của tôi |
| Vé tự huỷ quá hạn | `release_expired_tickets` | người đặt | Vé đã huỷ vì chưa thanh toán | Chi tiết sự kiện |
| Sự kiện bị huỷ | `cancel_event` | mọi người giữ vé (mỗi người 1 lần) | Xin lỗi, thông tin hoàn tiền | Trang sự kiện |
| Được giao việc | nơi tạo/sửa Task khi `assignee` đổi | người được giao | Tên việc, deadline | Việc của tôi |
| Có vé từ danh sách chờ | F4.8 | người được lên | Xem 7.1 | Vé của tôi |

**Gộp theo người:** `release_expired_tickets` có thể huỷ 3 vé của cùng một người
cùng lúc → gom theo `(user, event)`, gửi 1 thông báo. Được giao việc: chỉ báo
khi `assignee` THỰC SỰ đổi (so sánh giá trị cũ), không báo khi sửa mô tả; và
không báo nếu người giao tự giao cho chính mình.

Test: với mỗi dòng bảng, 1 test kiểm `len(mail.outbox)` và Notification đúng
người, đúng số lượng (đặc biệt: huỷ sự kiện với 1 người giữ 4 vé → đúng 1 mail).

---

## 7. SPRINT 4

### 7.1. F4.8 - Danh sách chờ

#### Quyết định thiết kế (đã chốt - đừng đổi)

- **Mỗi lượt chờ = 1 vé.** Không cho chờ nhiều vé một lượt: chờ 3 vé thì khi
  trả ra 1 chỗ sẽ phải chọn giữa "giữ chỗ lẻ" hay "bỏ qua" - phức tạp mà ít giá
  trị. Ai muốn nhiều vé thì chờ nhiều lượt (vẫn trong giới hạn 4 vé/người).
- **Tự động cấp vé cho người đầu hàng, KHÔNG có bước "mời rồi chờ đồng ý".**
  Người dùng đã chủ động xin chờ. Vé có phí được cấp ở trạng thái PENDING → đi
  qua đúng luồng thanh toán + tự huỷ quá hạn sẵn có. Nếu họ không trả tiền, vé
  hết hạn → chỗ lại được trả → tự chuyển cho người kế tiếp. Không cần trạng
  thái "đã mời", không cần lệnh quét lời mời hết hạn.

#### Model

```python
class WaitlistStatus(models.TextChoices):
    WAITING   = "WAITING", "Đang chờ"
    PROMOTED  = "PROMOTED", "Đã có vé"
    SKIPPED   = "SKIPPED", "Bỏ qua"         # tới lượt nhưng không đủ điều kiện
    CANCELLED = "CANCELLED", "Đã rời"
    EXPIRED   = "EXPIRED", "Hết hạn"        # sự kiện kết thúc/đóng mà chưa tới lượt

class WaitlistEntry(models.Model):
    ticket_type = FK(TicketType, CASCADE, related_name="waitlist")
    user        = FK(User, CASCADE, related_name="waitlist_entries")
    status      = CharField(max_length=10, choices=..., default=WAITING)
    ticket      = OneToOneField(Ticket, SET_NULL, null=True, blank=True)  # vé được cấp
    note        = CharField(max_length=255, blank=True)                   # lý do SKIPPED
    created_at  = DateTimeField(auto_now_add=True, db_index=True)
    resolved_at = DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "id"]   # id phá thế hoà khi created_at trùng
```

**KHÔNG dùng `UniqueConstraint(condition=...)`** để chặn một người chờ 2 lần -
MySQL bỏ qua (mục 4.3). Chặn ở service, dưới khoá dòng `TicketType`.

#### Tách lõi tạo vé ra khỏi `book_tickets`

Refactor, KHÔNG đổi hành vi:

```python
def _issue_tickets(user, ticket_type, quantity, booking_ref):
    """Trừ sold + tạo vé. GIẢ ĐỊNH ticket_type ĐÃ bị select_for_update ở nơi gọi."""
    # đúng phần (5) hiện tại của book_tickets
```

`book_tickets` = khoá dòng + các kiểm tra (2)(3)(4) + `_issue_tickets`. Chạy lại
toàn bộ test M4 sau refactor, phải xanh 100% trước khi viết tiếp.

#### Vào danh sách chờ

```python
@transaction.atomic
def join_waitlist(user, ticket_type_id):
    tt = TicketType.objects.select_for_update().select_related("event").get(pk=ticket_type_id)
    ev = tt.event
    if ev.status != EventStatus.OPEN or now > ev.register_deadline:
        raise BookingError("Sự kiện không còn nhận đăng ký.")
    if tt.remaining > 0:
        raise BookingError("Loại vé này vẫn còn chỗ, bạn có thể đặt vé ngay.")
    if WaitlistEntry.objects.filter(ticket_type=tt, user=user, status=WAITING).exists():
        raise BookingError("Bạn đã ở trong danh sách chờ của loại vé này.")
    owned   = số vé còn hiệu lực của user ở sự kiện (như book_tickets bước 3)
    waiting = số lượt WAITING của user ở MỌI loại vé của sự kiện này
    if owned + waiting + 1 > settings.MAX_TICKETS_PER_USER_PER_EVENT:
        raise BookingError("Bạn đã đạt giới hạn vé cho sự kiện này (tính cả lượt chờ).")
    entry = WaitlistEntry.objects.create(ticket_type=tt, user=user)
    return entry, waitlist_position(entry)
```

Vì mọi `join_waitlist` cho cùng một loại vé phải xếp hàng chờ khoá dòng
`TicketType`, kiểm tra "đã tồn tại chưa" rồi mới tạo là an toàn trên cả MySQL.

`waitlist_position(entry)` = số lượt WAITING cùng loại vé có
`(created_at, id)` nhỏ hơn + 1.

#### Rời danh sách chờ

`leave_waitlist(user, entry_id)`: chỉ chủ lượt chờ, chỉ khi WAITING → CANCELLED,
`resolved_at=now`. Không cần khoá TicketType.

#### Đẩy người kế tiếp lên - trái tim của chức năng

```python
def promote_from_waitlist(ticket_type):
    """
    GỌI BÊN TRONG transaction, KHI ticket_type ĐÃ bị select_for_update.
    Lặp: còn chỗ và còn người chờ -> cấp vé cho người đầu hàng.
    """
    ev = ticket_type.event
    if ev.status != EventStatus.OPEN or timezone.now() > ev.register_deadline:
        return []                                   # hết hạn đăng ký: không cấp nữa
    promoted = []
    while ticket_type.remaining > 0:
        entry = (WaitlistEntry.objects.select_for_update()
                 .filter(ticket_type=ticket_type, status=WAITING)
                 .select_related("user").order_by("created_at", "id").first())
        if entry is None:
            break
        u = entry.user
        owned = số vé còn hiệu lực của u ở sự kiện
        if u.is_locked:
            _resolve(entry, SKIPPED, "Tài khoản bị khoá"); continue
        if owned + 1 > settings.MAX_TICKETS_PER_USER_PER_EVENT:
            _resolve(entry, SKIPPED, "Đã đủ số vé tối đa"); continue
        ref = make_booking_ref()
        [ticket] = _issue_tickets(u, ticket_type, 1, ref)
        entry.ticket = ticket
        _resolve(entry, PROMOTED)
        promoted.append(entry)
        notify_on_commit(u, WAITLIST_PROMOTED, ...)   # vé có phí: kèm VietQR + hạn TT
    return promoted
```

**Phải gọi `promote_from_waitlist` ở MỌI chỗ làm `sold` giảm**, ngay sau khi
giảm, vẫn trong cùng transaction và cùng khoá:

| Chỗ | Ghi chú |
|---|---|
| `cancel_ticket` | sau `ticket_type.save(update_fields=["sold"])` |
| `release_expired_tickets` | sau mỗi vé bị huỷ; hoặc gom theo loại vé rồi gọi 1 lần/loại |
| Tăng `quota` của loại vé (nếu sau này có chức năng sửa loại vé) | ghi chú TODO trong code |

`cancel_event` KHÔNG gọi hàm này (sự kiện đã huỷ) mà đổi mọi lượt WAITING → CANCELLED.

**Vì sao không bị cấp trùng khi 2 người huỷ vé cùng lúc:** cả hai giao dịch đều
phải khoá dòng `TicketType` trước khi giảm `sold`. Giao dịch thứ hai chờ giao
dịch thứ nhất commit (đã cấp vé cho người #1 và đổi lượt đó sang PROMOTED), rồi
mới đọc → thấy người #2 là đầu hàng. Không ai được cấp 2 lần.

**Dọn dẹp khi sự kiện kết thúc:** trong lệnh định kỳ (mục 7.2), mọi lượt WAITING
của sự kiện có status DONE/CANCELLED hoặc đã quá `register_deadline` → EXPIRED,
kèm thông báo "Rất tiếc, không có chỗ trống cho bạn".

#### Giao diện

- Trang chi tiết, loại vé hết chỗ: nút **"Vào danh sách chờ"** thay cho nút đặt
  vé. Đang chờ: hiện **"Bạn đang ở vị trí thứ N"** + nút "Rời danh sách chờ".
- "Vé của tôi": thêm khối "Đang chờ" liệt kê các lượt WAITING và vị trí.
- Trang người tham gia (BTC): tab "Danh sách chờ" - thứ tự, tên, MSSV, thời
  điểm vào hàng, trạng thái.
- Vị trí là con số **tại thời điểm xem**, có thể đổi. Không hứa "chắc chắn có vé".

#### Test F4.8 - phần quan trọng nhất của cả kế hoạch

| Mã | Tình huống | Mong đợi |
|---|---|---|
| T4.8.1 | Vào chờ khi còn chỗ | Lỗi "vẫn còn chỗ" |
| T4.8.2 | Vào chờ 2 lần cùng loại vé | Lần 2 lỗi |
| T4.8.3 | Có 3 vé + 1 lượt chờ, xin chờ thêm | Lỗi giới hạn (3+1+1 > 4) |
| T4.8.4 | A, B, C chờ; 1 vé bị huỷ | A được vé, B vị trí 1, C vị trí 2 |
| T4.8.5 | Vé cấp cho người chờ, loại vé có phí | Vé PENDING, có `booking_ref`, có thông báo |
| T4.8.6 | Vé đó hết hạn thanh toán (chạy `release_expired`) | Vé A bị huỷ, **B được cấp tự động** |
| T4.8.7 | Người đầu hàng bị khoá tài khoản | Lượt đó SKIPPED, người kế tiếp được vé |
| T4.8.8 | Người đầu hàng đã tự mua đủ 4 vé | SKIPPED, người kế tiếp được vé |
| T4.8.9 | Huỷ vé sau `register_deadline` | Không cấp cho ai, lượt chờ giữ WAITING |
| T4.8.10 | Huỷ sự kiện | Mọi lượt WAITING → CANCELLED, có thông báo |
| T4.8.11 | `sold` sau mọi kịch bản trên | Luôn bằng số vé PENDING+CONFIRMED+CHECKED_IN thật |
| T4.8.12 | **2 luồng cùng huỷ vé đồng thời** (dùng `TransactionTestCase` + threading, chạy trên MySQL như test race condition hiện có) | 2 người chờ đầu mỗi người đúng 1 vé, không ai 2 vé, `sold` đúng |

T4.8.11 nên viết thành một hàm kiểm tra bất biến `assert_sold_consistent(ticket_type)`
và gọi ở cuối MỌI test M4.

### 7.2. F7.2 - Nhắc lịch trước 24h + lệnh định kỳ tổng

Model: thêm `Event.reminder_sent_at = DateTimeField(null=True, blank=True)`.

Lệnh `python manage.py send_reminders`:

```python
now = timezone.now()
events = Event.objects.filter(status__in=[OPEN, CLOSED],
                              starts_at__gt=now,
                              starts_at__lte=now + timedelta(hours=24),
                              reminder_sent_at__isnull=True)
for ev in events:
    with transaction.atomic():
        ev = Event.objects.select_for_update().get(pk=ev.pk)
        if ev.reminder_sent_at: continue            # tiến trình khác đã gửi
        ev.reminder_sent_at = now
        ev.save(update_fields=["reminder_sent_at"])
        users = người có vé CONFIRMED (distinct) - KHÔNG gửi cho vé PENDING
        notify_many(users, EVENT_REMINDER, ...)     # qua on_commit
```

- Đánh dấu `reminder_sent_at` TRƯỚC khi gửi, trong cùng transaction: lệnh chạy
  2 lần (hoặc 2 máy chạy song song) cũng không gửi trùng.
- Cửa sổ "trong 24h tới" thay vì "đúng 24h": lịch chạy trễ vẫn không bỏ sót.
- Sự kiện được tạo khi chỉ còn 10 giờ nữa diễn ra → vẫn được nhắc 1 lần.

**Lệnh tổng** `python manage.py run_periodic` chạy tuần tự: `release_expired`
→ dọn danh sách chờ hết hạn (7.1) → `send_reminders` → xoá Notification đã đọc
quá 90 ngày. Mỗi bước bọc try/except riêng, một bước lỗi không chặn bước sau,
in ra số lượng đã xử lý.

Lịch chạy: **mỗi 15 phút**. Windows: Task Scheduler. Linux/host: cron
`*/15 * * * * cd /app && python manage.py run_periodic`. Ghi hướng dẫn vào
`docs/huong-dan-deploy.md`.

Test: T7.2.1 sự kiện sau 20h → được nhắc; T7.2.2 sự kiện sau 30h → chưa; T7.2.3
chạy lệnh 2 lần → chỉ 1 lượt mail; T7.2.4 vé PENDING không được nhắc; T7.2.5
người có 3 vé nhận 1 mail.

---

## 8. SPRINT 5 - phần A: F7.3 Chuông thông báo

**Context processor** `notifications/context_processors.py::unread`
- Khách: trả `{}`, **không truy vấn gì**.
- Đã đăng nhập: `{"unread_count": user.notifications.filter(is_read=False).count()}`.
- Nếu đã làm sidebar ở `docs/de-xuat-giao-dien.md` (badge vé chờ, việc của tôi),
  **gộp chung vào context processor đó**, cache 30 giây theo user, không tạo
  hai processor chạy hai lượt truy vấn.

**URL** (app `notifications`, tiền tố `/thongbao/`):

| URL | Method | Làm gì |
|---|---|---|
| `/thongbao/` | GET | Danh sách, phân trang 20 (dùng `core.pagination.paginate`) |
| `/thongbao/<id>/mo/` | POST | Đánh dấu đã đọc rồi chuyển tới `url` |
| `/thongbao/doc-het/` | POST | Đánh dấu tất cả đã đọc |

**Bảo mật `/mo/`:**
- `get_object_or_404(Notification, pk=id, user=request.user)` - không bao giờ lấy
  theo id đơn thuần (IDOR: người này mở thông báo của người khác).
- Trước khi chuyển trang: `url_has_allowed_host_and_scheme(n.url,
  allowed_hosts={request.get_host()})`; không hợp lệ → về `/thongbao/`. Dù `url`
  do code sinh ra, vẫn phải chặn open redirect.
- Là POST (đổi dữ liệu) nên có CSRF - mỗi dòng thông báo là một `<form>` nhỏ.

**Giao diện:** icon chuông trên navbar (hoặc sidebar), badge số chưa đọc (>9 hiện
"9+", =0 thì ẩn), dropdown 5 thông báo mới nhất + link "Xem tất cả". Tuân theo
vùng chạm 44px.

Test: T7.3.1 badge đúng số; T7.3.2 mở thông báo của người khác → 404; T7.3.3
`url="https://evil.com"` → không chuyển ra ngoài; T7.3.4 khách truy cập trang chủ
→ số truy vấn không tăng (`assertNumQueries`).

## 9. SPRINT 5 - phần B: F7.4, F2.5

### 9.1. F7.4 - Tải file lịch `.ics`

`GET /sukien/<pk>/lich.ics` - công khai với sự kiện không phải DRAFT; DRAFT thì
chỉ BTC. Tự sinh, **không thêm thư viện**.

```
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//KMG Club//Su kien//VI
CALSCALE:GREGORIAN
METHOD:PUBLISH
BEGIN:VEVENT
UID:event-<pk>@kmgclub
DTSTAMP:<now UTC, dạng 20260930T120000Z>
DTSTART:<starts_at UTC>
DTEND:<ends_at UTC, hoặc starts_at + 2 giờ nếu chưa có ends_at>
SUMMARY:<tên>
LOCATION:<địa điểm>
DESCRIPTION:<mô tả cắt 500 ký tự>\n\nChi tiết: <SITE_URL>/sukien/<pk>/
URL:<SITE_URL>/sukien/<pk>/
STATUS:CONFIRMED            (CANCELLED nếu sự kiện đã huỷ)
BEGIN:VALARM
TRIGGER:-PT1H
ACTION:DISPLAY
DESCRIPTION:Sắp tới giờ sự kiện
END:VALARM
END:VEVENT
END:VCALENDAR
```

Quy tắc RFC 5545 - làm sai là Google Calendar/iPhone từ chối file:
- Xuống dòng bằng **CRLF** (`\r\n`), không phải `\n`.
- Thoát ký tự trong giá trị: `\` → `\\`, `;` → `\;`, `,` → `\,`, xuống dòng → `\n`.
- **Gập dòng dài hơn 75 BYTE** (không phải 75 ký tự - tiếng Việt có dấu chiếm
  2-3 byte UTF-8): chèn `\r\n ` (CRLF + 1 dấu cách); không được cắt giữa một ký tự nhiều byte.
- Thời gian đổi sang UTC, hậu tố `Z`.
- Header: `Content-Type: text/calendar; charset=utf-8`,
  `Content-Disposition: attachment; filename="su-kien-<pk>.ics"`.

**Sửa B4:** thêm `Event.ends_at` (null=True), thêm vào form tạo/sửa sự kiện,
validate `ends_at > starts_at`.

Nút "Thêm vào lịch" ở trang chi tiết và trong email xác nhận vé.

Test: T7.4.1 có CRLF; T7.4.2 tên có dấu phẩy được thoát; T7.4.3 không dòng nào
quá 75 byte và file vẫn giải mã UTF-8 được; T7.4.4 DRAFT với khách → 404.
Thủ công: nhập file vào Google Calendar và lịch iPhone, giờ hiển thị đúng giờ Việt Nam.

### 9.2. F2.5 - Danh mục sự kiện

Dùng **TextChoices trên Event**, không làm bảng riêng (CLB ít khi thêm danh mục,
bảng riêng thêm CRUD và phân quyền không cần thiết):

```python
class EventCategory(models.TextChoices):
    MUSIC     = "MUSIC", "Âm nhạc"
    ACADEMIC  = "ACADEMIC", "Học thuật"
    VOLUNTEER = "VOLUNTEER", "Thiện nguyện"
    SPORT     = "SPORT", "Thể thao"
    SOCIAL    = "SOCIAL", "Giao lưu"
    OTHER     = "OTHER", "Khác"

Event.category = CharField(max_length=10, choices=..., default=OTHER, db_index=True)
```

Migration có default `OTHER` cho sự kiện cũ. Thêm vào form. Trang danh sách: lọc
`?category=` **kết hợp** được với `?status=` và `?q=` hiện có - sửa cả link bộ lọc
trạng thái để giữ lại `category` (hiện tại link lọc trạng thái chỉ giữ `q`).
Giá trị `category` lạ trên URL → bỏ qua, không lỗi 500.

Test: lọc đúng; kết hợp 3 tham số; tham số lạ không lỗi.

## 10. SPRINT 5 - phần C: F8.1, F8.2

### 10.1. F8.1 - Lịch sử tham gia

Trên trang hồ sơ: danh sách sự kiện user **đã check-in** (vé CHECKED_IN), sự
kiện mới nhất lên đầu, mỗi sự kiện 1 dòng dù có nhiều vé. Tổng số sự kiện đã
tham gia. Truy vấn: `Event.objects.filter(tickets__user=u,
tickets__status=CHECKED_IN).distinct().order_by("-starts_at")`.

### 10.2. F8.2 - Giấy chứng nhận tham gia

**Điều kiện cấp:** user có ít nhất 1 vé CHECKED_IN **và** sự kiện ở trạng thái DONE.

**Không cần model mới.** Mã xác thực là chữ ký của Django:

```python
signer = signing.Signer(salt="kmg-certificate")
def cert_token(ticket):    # dùng vé check-in SỚM NHẤT của user cho sự kiện
    return signer.sign(ticket.code).split(":", 1)[1]   # chỉ lấy phần chữ ký

def verify(code, token):
    try:
        signer.unsign(f"{code}:{token}")
        return True
    except signing.BadSignature:
        return False
```

**Giấy chứng nhận = trang HTML in được**, KHÔNG sinh PDF phía server:
- `GET /chungnhan/<event_pk>/` (đăng nhập, đúng điều kiện cấp, không thì 404).
- Bố cục khổ A4 ngang bằng `@page { size: A4 landscape; margin: 0 }` và
  `@media print` (ẩn navbar, footer, nút). Nút "In / Lưu PDF" gọi `window.print()`.
- Nội dung: logo, "GIẤY CHỨNG NHẬN THAM GIA", họ tên, MSSV, tên sự kiện, ngày
  diễn ra, ngày cấp, chữ ký (tên Trưởng BTC tạo sự kiện), mã tra cứu, **QR dẫn
  tới trang xác thực**.
- Lý do chọn HTML: font Be Vietnam Pro đã self-host hiển thị tiếng Việt chuẩn;
  reportlab phải tự đăng ký font TTF mới ra được dấu tiếng Việt - rủi ro cao, thêm thư viện.

**Trang xác thực công khai** `GET /chungnhan/xacthuc/<code>/<token>/`:
- Chữ ký sai hoặc vé không CHECKED_IN hoặc sự kiện chưa DONE → trang "Không xác
  thực được", **cùng một thông báo cho mọi lý do**.
- Hợp lệ → hiện họ tên, **MSSV che bớt** (giữ 4 ký tự đầu và 2 cuối, giữa là `*`),
  tên sự kiện, ngày. Không hiện email, số điện thoại. Trang công khai → tối thiểu dữ liệu cá nhân.

**Cảnh báo phải ghi trong README:** đổi `SECRET_KEY` sẽ làm **mọi chứng nhận đã
cấp mất hiệu lực xác thực**. Ghi rõ để không ai đổi khoá tuỳ tiện.

Test: T8.2.1 chưa check-in → 404; T8.2.2 sự kiện chưa DONE → 404; T8.2.3 token
đúng → xác thực OK; T8.2.4 sửa 1 ký tự token → "không xác thực được"; T8.2.5 trang
xác thực không chứa email/SĐT và MSSV đã che.

---

## 11. Giai đoạn 3 - chỉ phác thảo, CHƯA làm

| Chức năng | Ý chính | Rủi ro cần cân nhắc trước |
|---|---|---|
| Ngân sách sự kiện | Model `Expense(event, title, amount, paid_by, receipt_image)`; thu = tổng vé CONFIRMED+CHECKED_IN; báo cáo lãi/lỗ | Chỉ LEAD/ADMIN xem; ảnh hoá đơn là dữ liệu nhạy cảm |
| Album ảnh | Model `Photo(event, image, uploaded_by)`; nén ảnh bằng Pillow khi tải lên (tối đa 1600px) | Dung lượng lưu trữ trên host miễn phí rất hạn chế |
| Thành viên CLB theo khoá/ban | Model `Membership(user, term, department, position)` | Là thay đổi lớn về phân quyền - cần thiết kế riêng |
| Webhook ngân hàng tự xác nhận | Dịch vụ trung gian (Casso, SePay…) gọi webhook khi có tiền vào; đối chiếu nội dung `KMG <booking_ref>` → `confirm_booking` | Phải xác thực chữ ký webhook; xử lý chuyển thiếu/thừa tiền; phụ thuộc bên thứ ba |

**Không làm:** cổng VNPay/MoMo (cần đăng ký doanh nghiệp), app di động riêng,
mạng xã hội/bình luận/like.

---

## 12. Tổng hợp thay đổi CSDL (để lên kế hoạch migration)

| Sprint | Migration |
|---|---|
| 1 | App `notifications`: bảng `Notification` · ràng buộc email không trùng (không hiệu lực trên MySQL) |
| 2 | (không) |
| 3 | `Ticket.booking_ref` + data migration điền cho vé cũ |
| 4 | Bảng `WaitlistEntry` · `Event.reminder_sent_at` |
| 5 | `Event.ends_at` · `Event.category` (default OTHER) |

Mỗi migration: chạy thử trên bản sao DB MySQL có dữ liệu `seed_demo` trước.
Cập nhật `seed_demo` để tạo dữ liệu mẫu cho chức năng mới (vài lượt chờ, vài
thông báo, một sự kiện DONE có người check-in để demo chứng nhận).

## 13. Định nghĩa "XONG" cho mỗi chức năng

- [ ] Logic nằm trong service; view mỏng.
- [ ] Ghi dữ liệu trong `@transaction.atomic`; đụng `sold` thì có `select_for_update`.
- [ ] Email/thông báo đi qua `notify_on_commit`, lỗi gửi mail không làm hỏng nghiệp vụ.
- [ ] Test tự động theo đúng bảng trong tài liệu này, **87 test cũ vẫn PASS**.
- [ ] `docs/bang-test-case.md` có các dòng mã mới.
- [ ] Chạy được trên **MySQL**; `makemigrations --check` sạch.
- [ ] Chụp màn hình trang mới ở theme sáng + tối; kiểm tra trên điện thoại
      (headless Chrome trên máy này không hạ viewport dưới ~482px).
- [ ] Không có request ra tên miền ngoài (tab Network), trừ SMTP khi đã cấu hình.
- [ ] Thông báo lỗi tiếng Việt, rõ nguyên nhân, không lộ thông tin nội bộ.
- [ ] `docs/kich-ban-demo.md` được cập nhật nếu chức năng xuất hiện khi demo.
