# Ngữ cảnh & Prompt cải tiến Front-end — KMG Club

> Tài liệu này là **bản giao việc** cho người/agent tiếp tục làm giao diện.
> Đọc hết mục 1–3 để nắm bối cảnh, rồi thực thi mục 4 theo đúng thứ tự ưu tiên.

---

## 1. Bối cảnh dự án

- **Hệ thống:** web quản lý sự kiện cho câu lạc bộ sinh viên (đồ án môn Công nghệ
  phần mềm). Vòng đời: chuẩn bị → mở đăng ký/bán vé → check-in → phản hồi & thống kê.
- **Công nghệ:** Django 5, Bootstrap 5.3.3 (self-hosted), Chart.js (self-hosted),
  server-rendered templates. Kiến trúc 3 tầng View / Service / Model.
- **Thư mục gốc chạy được:** `D:\clubevent\clubevent` (chứa `manage.py`, là git repo).
- **Chạy để xem:** `.\venv\Scripts\python.exe manage.py runserver` → http://127.0.0.1:8000
- **Tài khoản demo** (mật khẩu chung `demo1234`): `admin`, `truongbtc`, `btc1`,
  `btc2`, `thanhvien`, `thanhvien2`.

## 2. RÀNG BUỘC BẮT BUỘC (không được vi phạm)

1. **KHÔNG dùng CDN.** Mọi CSS/JS/font/asset phải nằm trong `static/` và self-host.
   Lý do gốc: wifi phòng học chập chờn, rớt mạng giữa lúc demo là mất sạch giao diện.
   Đây là nguyên tắc đã ghi trong README và sẽ bị hỏi khi bảo vệ.
2. **Không đổi logic nghiệp vụ** (views/services/models) trừ khi thật sự cần cho UI.
   Ưu tiên chỉ sửa `templates/` và `static/`.
3. **Không phá test.** Sau khi xong chạy `python manage.py test` phải vẫn 87/87 PASS.
4. **Giữ phân quyền phía server** — không chuyển kiểm tra quyền xuống client.
5. **Comment trong code viết bằng tiếng Việt.**
6. **Dark mode dùng cơ chế Bootstrap 5.3:** `data-bs-theme` trên thẻ `<html>`.
   Component tùy biến phải dùng biến theme, không hard-code màu.
7. **Responsive tới ~400px** (BTC dùng điện thoại để check-in).

## 3. Hiện trạng Front-end (đã làm)

Đã dựng xong **lớp design system** và áp cho khung + trang landing:

| File | Trạng thái | Nội dung |
|---|---|---|
| `static/css/app.css` | ✅ Đã có design system | Tokens màu, dark mode, glassmorphism, nền slideshow, con trỏ tùy biến, nút/card/navbar/hero/status-pill/progress/checkin/chat/avatar |
| `templates/base.html` | ✅ Khung mới | Navbar kính dính (sticky), nút đổi sáng/tối, dropdown avatar, highlight menu đang mở, nền slideshow |
| `templates/events/list.html` | ✅ Đã nâng cấp | Hero, toolbar lọc dạng card, thẻ sự kiện có pill trạng thái + thanh tiến trình chỗ |

**Token & thương hiệu hiện tại** (trong `app.css`):
- Màu chính `--brand: #2563eb`, đậm `--brand-strong: #1d4ed8`, accent `--accent: #f59e0b`.
- Font: body `Inter`, tiêu đề `Outfit` (⚠️ **đang tải từ Google Fonts CDN — cần sửa, xem P1**).
- Nền: slideshow 3 ảnh `static/img/bg_music_{1,2,3}.jpg` + lớp phủ mờ, thẩm mỹ "vũ trụ âm nhạc".

**Class dùng lại được** (đã định nghĩa sẵn, cứ tận dụng khi làm màn mới):
`.hero`, `.card-event`, `.status-pill` (kèm `bg-*-subtle text-*-emphasis` của BS 5.3),
`.progress.seats`, `.cover-overlay`, `.checkin-result`, `.checkin-code`, `#code-input`,
`.chat-log/.chat-msg/.chat-bot/.chat-user/.chat-links`, `.event-cover`, `.event-cover-lg`,
`.avatar` / `.avatar-initials` (+ `-sm`/`-lg`), `.star-rating`, `.task-overdue`/`.task-done`.

**Chưa nâng cấp bố cục** (vẫn dùng layout cũ, nhưng đã tự hưởng màu/nút/card mới):
`events/detail.html`, `registrations/checkin.html`, `events/dashboard.html`,
`feedback/list.html`, `organizing/board.html`, `aiassist/chat.html`,
`registrations/my_tickets.html`, các trang `accounts/*`, `*/form.html`.

---

## 4. VIỆC CẦN LÀM (theo thứ tự ưu tiên)

### 🔴 P1 — Self-host font (sửa vi phạm nguyên tắc no-CDN)

**Vấn đề:** `base.html` đang tải Inter + Outfit từ `fonts.googleapis.com`. Rớt mạng
lúc demo → font "premium" biến mất, tụt về font hệ thống; đồng thời mâu thuẫn với
chính nguyên tắc self-host của dự án.

**Cần làm:**
1. Tải các file `.woff2` về `static/vendor/fonts/`:
   - Inter: weight 400, 500, 600.
   - Outfit: weight 500, 600, 700, 800.
2. Tạo `static/css/fonts.css` khai báo `@font-face` cho từng weight, dùng
   `font-display: swap`, `src: url('../vendor/fonts/....woff2') format('woff2')`.
3. Trong `base.html`: **xoá 3 dòng** `<link rel="preconnect">` + `<link ... fonts.googleapis.com>`,
   thêm `<link rel="stylesheet" href="{% static 'css/fonts.css' %}">` **trước** `app.css`.
4. Giữ nguyên fallback stack trong `--bs-body-font-family` / `--app-heading-font`.

**Nghiệm thu:** tắt mạng → mở trang → vẫn đúng Inter/Outfit; xem source không còn
`googleapis.com`.

### 🟡 P2 — Tối ưu hiệu ứng kính (mượt + đọc rõ + a11y)

Kính mờ đẹp nhưng rủi ro trên máy demo/máy chiếu yếu.

1. **Hiệu năng:** giảm `backdrop-filter: blur()` — chỉ giữ ở **navbar + hero**;
   `.card` đổi sang nền **đục hơn** (nâng alpha `--app-surface` ~ `0.92`) và bỏ blur
   ở card để không chồng nhiều lớp GPU.
2. **Tương phản:** đảm bảo chữ trên card/hero đạt ≥ 4.5:1 ở cả sáng lẫn tối.
3. **Chuyển động:** thêm `@media (prefers-reduced-motion: reduce)` để tắt slideshow
   và các `transform` hover (điểm cộng a11y khi chấm).
4. **Con trỏ tùy biến (SVG):** chỉ áp cho vùng không nhập liệu; `input/textarea/select`
   trả về con trỏ mặc định. Cân nhắc bỏ hẳn nếu gây rối.

**Nghiệm thu:** cuộn/hover mượt trên máy yếu; bật "giảm chuyển động" thì nền đứng yên.

### 🟢 P3 — Lan design ra các màn hình lõi

Làm lần lượt, mỗi màn tận dụng class sẵn có ở mục 3.

1. **`events/detail.html`** *(ưu tiên cao)*: hero ảnh bìa full-width + `.cover-overlay`
   (tên/ngày/địa điểm đè lên ảnh); card đăng ký **`position-sticky top-0`** khi cuộn ở
   desktop; bộ chọn loại vé dạng **thẻ radio** (giá + số còn + trạng thái hết vé);
   thanh tiến trình chỗ.
2. **`registrations/checkin.html`** *(ưu tiên cao)*: **chế độ kiosk** — ô nhập mã to
   (`#code-input`), kết quả **full-card xanh/đỏ** (`.checkin-result`), **bộ đếm đã
   check-in**, tối ưu bấm bằng ngón tay trên điện thoại.
3. **`events/dashboard.html`** *(ưu tiên cao)*: **hàng KPI tiles** phía trên + bảng so
   sánh có **mini-bar** trong ô; áp palette biểu đồ nhất quán (dùng skill `dataviz`).
   Nhớ nhãn cột đã sửa "Doanh thu (đã thu)".
4. **`feedback/list.html`**: biến card tóm tắt AI thành **insight panel** nổi bật;
   phân bố sao dạng bar ngang; đồng bộ màu biểu đồ.
5. **`organizing/board.html`**: **Kanban 3 cột** (Chưa làm / Đang làm / Xong) với viền
   màu trạng thái + thanh tiến độ theo sự kiện.
6. **`aiassist/chat.html`**: chip gợi ý gọn, typing indicator, tối ưu mobile.
7. **`accounts/login|register|profile`, `registrations/my_tickets`**: card gọn, canh
   giữa, khoảng thở hợp lý.

**Nghiệm thu mỗi màn:** đẹp & đọc rõ ở **cả sáng lẫn tối**, không vỡ ở **~400px**,
không đổi hành vi nghiệp vụ.

## 5. Quy ước khi làm

- Đụng tối thiểu vào `views.py`/`services.py`; nếu buộc phải thêm dữ liệu cho template
  thì nói rõ lý do.
- Luôn `{% load static %}` (và `ui` nếu dùng filter tùy biến như `cover_index`, `initials`).
- Sau khi xong: chạy `python manage.py test` (giữ 87 PASS) và tự xem trên trình duyệt
  ở cả 2 theme + khổ điện thoại.
- **Không commit git** — người dùng tự quản lý commit.
