# Giải thích code - tài liệu ôn bảo vệ

Mỗi mục: **luồng chạy → file cần đọc → vì sao làm vậy → câu hỏi hay gặp + đáp án.**
Cách ôn hiệu quả: mở đúng file, đọc hàm được nêu, tự trả lời câu hỏi TRƯỚC khi
xem đáp án. Người phụ trách module nào (bảng phân công trong README) thì phải
trả lời trôi chảy các câu của module đó.

---

## 1. Kiến trúc 3 tầng

**Luồng:** URL → `views.py` (nhận request, kiểm quyền, trả response) →
`services.py` (quy tắc nghiệp vụ) → `models.py` (dữ liệu, máy trạng thái).

**Vì sao:** logic nằm ở service nên test được bằng unit test mà không cần giả
lập HTTP; cùng một hàm dùng lại cho web, API JSON và lệnh định kỳ. Ví dụ
`book_tickets()` được gọi từ view đặt vé; `promote_from_waitlist()` được gọi
từ cả view huỷ vé lẫn lệnh `run_periodic`.

**Lỗi nghiệp vụ** ném exception riêng (`BookingError`, `FeedbackError`), view
bắt và hiện `messages.error` - người dùng thấy câu tiếng Việt, không thấy trang lỗi.

> **Hỏi:** Sao không viết logic thẳng trong view cho nhanh?
> **Đáp:** View gắn với HTTP nên khó test và không tái sử dụng được. Ví dụ danh
> sách chờ phải chạy cả khi người dùng huỷ vé (có request) lẫn khi lệnh định kỳ
> huỷ vé quá hạn (không có request) - logic chỉ viết một lần trong service.

---

## 2. Đặt vé và race condition - `registrations/services.py::book_tickets`

**Luồng:** khoá dòng loại vé (`select_for_update`) → kiểm tra sự kiện mở, hạn
đăng ký, giới hạn 4 vé/người, số chỗ → `_issue_tickets` trừ `sold` và tạo vé →
đăng ký gửi thông báo sau khi commit.

**Vì sao khoá dòng:** hai người cùng đọc `sold=49/50` rồi cùng ghi → bán 51 vé.
`SELECT … FOR UPDATE` bắt giao dịch thứ hai chờ giao dịch thứ nhất commit rồi
mới đọc, nên nó thấy `sold=50` và bị chặn. `@transaction.atomic` bảo đảm trừ
chỗ và tạo vé cùng thành công hoặc cùng huỷ.

**Vì sao có cột `sold`** thay vì đếm bảng vé: chỉ cần khoá 1 dòng loại vé.

**SQLite:** `config/settings.py` đặt `transaction_mode=IMMEDIATE` - mỗi giao
dịch giành quyền ghi ngay từ đầu, nên người sau xếp hàng và nhận "hết chỗ"
(không đặt thì người sau nhận lỗi "database is locked"). MySQL khoá đúng dòng,
SQLite khoá cả file - kết quả nghiệp vụ như nhau.

> **Hỏi:** Test race condition viết thế nào?
> **Đáp:** `RaceConditionTests` dùng `TransactionTestCase` + 2 thread cùng đặt
> chỗ cuối, kiểm tra đúng 1 người thành công và `sold` không vượt `quota`.
> Phải dùng `TransactionTestCase` vì `TestCase` bọc cả test trong 1 transaction
> nên 2 thread không thấy dữ liệu của nhau.

> **Hỏi:** Vì sao `_issue_tickets` tạo từng vé mà không dùng `bulk_create`?
> **Đáp:** Trên MySQL `bulk_create` không trả về id, vé không có id thì không
> gắn được vào lượt chờ. Mỗi lần tối đa 4 vé nên không ảnh hưởng tốc độ.

---

## 3. Mã giao dịch nhóm + VietQR - `registrations/vietqr.py`

**Vấn đề:** 1 lần đặt 4 vé có 4 mã vé 12 ký tự, nhưng nội dung chuyển khoản chỉ
~25 ký tự. **Giải pháp:** mọi vé của 1 lần đặt chung `booking_ref` 8 ký tự; nội
dung CK là `KMG <booking_ref>`. Bảng chữ bỏ 0/O, 1/I/L cho khỏi đọc nhầm.

**VietQR:** chuỗi theo chuẩn EMVCo, mỗi trường = mã 2 số + độ dài 2 số + giá
trị (`tlv`), cuối là CRC-16/CCITT để app ngân hàng kiểm tra chuỗi không bị sửa.
Sinh hoàn toàn offline, ảnh QR bằng thư viện `qrcode`. Thiếu cấu hình `BANK_*`
thì ẩn phần QR, trang vẫn chạy.

**Xác nhận:** BTC dán nội dung CK vào ô tìm kiếm → `confirm_booking()` xác nhận
cả nhóm, chỉ những vé còn "Chờ thanh toán", ghi 1 dòng nhật ký.

> **Hỏi:** Hệ thống có tự biết người dùng đã chuyển tiền không?
> **Đáp:** Không. Hệ thống không đọc được tài khoản ngân hàng, BTC đối chiếu sao
> kê rồi bấm xác nhận. Tự động hoá cần dịch vụ webhook ngân hàng (Casso, SePay)
> - đã ghi ở mục Giai đoạn 3 của kế hoạch.

> **Hỏi:** Làm sao biết chuỗi QR đúng chuẩn?
> **Đáp:** Test `crc16_ccitt("123456789") == "29B1"` là giá trị kiểm chuẩn của
> thuật toán; và bắt buộc quét thử bằng app ngân hàng thật trước khi demo.

---

## 4. Danh sách chờ - `promote_from_waitlist`

**Luồng:** loại vé hết chỗ → người dùng "Vào danh sách chờ" (mỗi lượt = 1 vé).
Khi `sold` giảm (huỷ vé, vé quá hạn thanh toán bị huỷ) → ngay trong cùng
transaction, cùng khoá dòng → lặp: còn chỗ và còn người chờ thì cấp vé cho
người đầu hàng. Người bị khoá tài khoản hoặc đã đủ 4 vé bị đánh dấu "Bỏ qua",
cấp cho người kế tiếp.

**Vì sao tự cấp, không "mời rồi chờ đồng ý":** đơn giản hơn nhiều. Vé có phí
cấp ở trạng thái Chờ thanh toán; không trả tiền thì vé tự huỷ quá hạn → chỗ lại
chuyển tiếp cho người sau. Không cần thêm trạng thái "đã mời".

> **Hỏi:** 2 người huỷ vé cùng lúc, có ai được cấp 2 vé không?
> **Đáp:** Không. Cả 2 giao dịch phải khoá dòng loại vé trước khi giảm `sold`;
> giao dịch sau chờ giao dịch trước commit (đã chuyển lượt #1 sang "Đã có vé")
> nên đọc thấy người #2 là đầu hàng.

> **Hỏi:** Sao không dùng ràng buộc unique để chặn chờ trùng?
> **Đáp:** Cần ràng buộc "unique khi đang chờ" (có điều kiện); MySQL không hỗ
> trợ loại này và Django chỉ cảnh báo rồi bỏ qua. Nên chặn trong service, dưới
> khoá dòng loại vé.

---

## 5. Thông báo - `notifications/services.py`

**Một cửa vào duy nhất:** `notify()` tạo thông báo trong app + gửi email; lỗi
email chỉ ghi log, **không bao giờ** làm hỏng nghiệp vụ chính.
`notify_many()` gửi hàng loạt qua 1 kết nối SMTP.

**Vì sao `notify_on_commit`:** đặt vé chạy trong transaction; nếu gửi email bên
trong mà bước sau lỗi → rollback, vé không tồn tại nhưng email "đặt vé thành
công" đã gửi đi, không thu hồi được. `transaction.on_commit` chỉ chạy khi dữ
liệu đã lưu thật.

**Gộp theo người:** huỷ sự kiện với người giữ 4 vé → 1 thông báo; vé quá hạn
gom theo (người, sự kiện).

**Chuông (F7.3):** mở thông báo lấy theo `(id, user)` để chống xem thông báo
của người khác (IDOR); trước khi chuyển trang kiểm tra URL nội bộ (chống open
redirect). Khách chưa đăng nhập không phát sinh truy vấn thông báo nào.

> **Hỏi:** Test chuyện rollback thì không gửi mail thế nào?
> **Đáp:** `test_no_notification_when_booking_rolls_back` - đặt vé lỗi trong
> `captureOnCommitCallbacks(execute=True)`, kiểm tra 0 thông báo, 0 mail.

---

## 6. Tác vụ định kỳ - `events/management/commands/run_periodic.py`

Chạy mỗi 15 phút: huỷ vé quá hạn → dọn danh sách chờ hết hạn → nhắc lịch 24h →
xoá thông báo cũ. Mỗi bước bọc try/except riêng, một bước lỗi không chặn bước sau.

**Nhắc lịch không gửi trùng:** đánh dấu `reminder_sent_at` **trước** khi gửi,
trong cùng transaction có khoá dòng sự kiện. Chạy lệnh 2 lần, hay 2 máy chạy
song song, cũng chỉ 1 lượt email. Cửa sổ "trong 24h tới" thay vì "đúng 24h" để
lịch chạy trễ không bỏ sót.

**Hạn thanh toán:** `min(lúc đặt + 24h, giờ diễn ra)` - đặt lúc 20h cho sự kiện
8h sáng mai thì hạn là 8h sáng, không phải 20h mai.

> **Hỏi:** Sao không dùng Celery?
> **Đáp:** Ràng buộc dự án: không thêm hạ tầng nặng (Redis, Celery). Quy mô CLB
> chỉ cần cron / Task Scheduler gọi management command.

---

## 7. Check-in bằng camera - `static/js/qr-scan.js`

- Camera chỉ bật được trên HTTPS hoặc `localhost` → không đủ điều kiện thì ẩn
  nút, dùng ô nhập mã (luôn chạy được).
- Giải mã: `BarcodeDetector` của trình duyệt nếu có, không thì thư viện `jsQR`.
- Chặn quét lặp cùng 1 mã trong 3 giây (camera đọc 1 vé nhiều lần mỗi giây).
- Mã không đúng dạng 12 ký tự hex → báo "không phải mã vé", không gọi server.
- Dữ liệu từ server gán bằng `textContent`, **không** ghép vào `innerHTML` -
  tên người dùng do họ tự đặt, ghép vào HTML là lỗ hổng XSS nhắm vào máy BTC.
- Tiến độ cập nhật mỗi 5 giây (polling), dừng khi tab ẩn; nhiều cửa check-in
  thấy chung một con số.

> **Hỏi:** 2 máy cùng quét 1 vé một lúc?
> **Đáp:** `check_in()` khoá dòng vé; máy sau đọc thấy "Đã check-in" → báo vàng.

---

## 8. Giấy chứng nhận - `events/services.py::cert_token`

**Điều kiện:** sự kiện đã diễn ra và người dùng có vé đã check-in.
**Mã xác thực:** chữ ký HMAC của Django (`signing.Signer`) trên mã vé - không cần
bảng mới, không làm giả được nếu không có `SECRET_KEY`.
**Trang xác thực công khai:** mọi lý do không hợp lệ đều cùng 1 câu (không lộ
thông tin), chỉ hiện họ tên, MSSV đã che, tên sự kiện.
**In PDF:** trang HTML khổ A4 ngang + `window.print()`, không sinh PDF ở server
(font tiếng Việt đã self-host hiển thị chuẩn, khỏi thêm thư viện).

> **Hỏi:** Đổi `SECRET_KEY` thì sao?
> **Đáp:** Mọi chứng nhận đã cấp mất hiệu lực xác thực - đã ghi cảnh báo trong README.

---

## 9. File lịch `.ics` - `event_ics`

Tự sinh theo RFC 5545, không thêm thư viện. 3 bẫy đã xử lý: xuống dòng phải là
CRLF; thoát ký tự `, ; \`; gập dòng dài hơn **75 byte** (không phải 75 ký tự -
tiếng Việt có dấu chiếm 2–3 byte) mà không cắt giữa một ký tự.

---

## 10. Giao việc và ngân sách - `organizing/`

- **Giao việc (Ban chủ nhiệm = Trưởng BTC + Admin):** `task_assign` - chọn sự
  kiện hoặc để trống (= việc chung CLB), người nhận là bất kỳ ai trong BTC kể
  cả Ban chủ nhiệm. Chỉ báo khi người phụ trách **thực sự đổi**, không báo khi
  tự giao cho mình. Tab "Tôi đã giao" lọc theo `created_by`.
- **Ngân sách:** thu = tổng giá vé đã xác nhận/check-in (tự tính), chi = các
  `Expense` ghi tay. Chỉ Trưởng BTC trở lên xem (dữ liệu tài chính).

> **Hỏi:** Thành viên BTC gõ thẳng URL `/congviec/giao-viec/` thì sao?
> **Đáp:** 403 - phân quyền kiểm tra ở server bằng decorator `lead_required`,
> không chỉ ẩn nút.

---

## 11. Bảo mật - tổng hợp để trả lời nhanh

| Rủi ro | Cách chặn | Ở đâu |
|---|---|---|
| Gõ URL vượt quyền | Decorator kiểm quyền ở server → 403 | `accounts/permissions.py` |
| CSRF | Form POST có token; thao tác đổi dữ liệu bắt buộc POST | mọi view `@require_POST` |
| Xem dữ liệu người khác (IDOR) | Lấy theo `(id, user=request.user)` | huỷ vé, in vé, thông báo, lượt chờ |
| Open redirect | `url_has_allowed_host_and_scheme` | mở thông báo, đổi trạng thái việc |
| XSS | Template tự escape; JS dùng `textContent` | `qr-scan.js` |
| Đoán mã vé | UUID ngẫu nhiên 12 ký tự hex | `make_ticket_code` |
| Mật khẩu | bcrypt, link đặt lại sống 2 giờ, giới hạn 5 yêu cầu/giờ | `settings.py`, `accounts/views.py` |
| Dò email qua "quên mật khẩu" | Luôn hiện cùng một câu | Django mặc định |

---

## 12. Tự kiểm tra trước buổi bảo vệ

```
python manage.py test                  # 213 test phải xanh
python manage.py seed_demo --reset     # dữ liệu demo sạch
python manage.py run_periodic          # thử lệnh định kỳ
```

Rồi đi đúng kịch bản trong `docs/kich-ban-demo.md`, kể cả phần mở rộng E1–E6.
