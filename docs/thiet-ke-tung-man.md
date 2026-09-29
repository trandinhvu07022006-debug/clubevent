# Thiết kế lại bố cục từng màn — Ngữ cảnh & Prompt

> Bản giao việc cho người/agent làm giao diện. Mỗi màn gồm: **Ngữ cảnh** (file,
> biến view, field model) → **Prompt thiết kế** (bố cục cụ thể) → **Nghiệm thu**.
> Màn **Danh sách sự kiện đã làm xong** — dùng làm MẪU CHUẨN cho các màn sau.

---

## 0. Nền chung (đọc trước, áp cho mọi màn)

### Ràng buộc bắt buộc
1. **KHÔNG CDN** — mọi asset self-host trong `static/`.
2. **Không đổi logic** trong `views.py`/`services.py`/`models.py` trừ khi ghi rõ.
   Phần lớn chỉ sửa `templates/`.
3. **Không phá test** — chạy `python manage.py test` phải vẫn 87/87 PASS.
4. Dark mode qua `data-bs-theme`; comment tiếng Việt; responsive tới ~400px.

### 7 nguyên tắc bố cục
1. Mỗi màn có **đúng 1 hành động chính** nổi bật.
2. **Page header thống nhất**: kicker + tiêu đề + mô tả ngắn + primary action.
3. Lưới có chủ đích: nội dung chính rộng, phụ trợ hẹp, **sidebar dính (sticky)**.
4. Nhịp 8px, **bỏ "card lồng card"**, ưu tiên khoảng trắng + đường phân tách nhẹ.
5. **Dữ liệu quan trọng phải nổi** (giá / chỗ / hạn / trạng thái).
6. Trạng thái **empty / lỗi** đều được thiết kế.
7. Mobile: stack theo thứ tự ưu tiên, tap target ≥ 44px, không tràn ngang.

### Quy ước kỹ thuật (theo mẫu `templates/events/list.html`)
- CSS riêng của trang đặt trong khối **`<style>` đầu `{% block content %}`** —
  KHÔNG sửa `static/css/app.css` (đang được chỉnh liên tục, dễ đụng nhau).
- **Tận dụng class có sẵn:** `.card`, `.card-event`, `.status-pill` (kèm
  `bg-*-subtle text-*-emphasis` của BS 5.3), `.progress.seats`, `.hero`,
  `.cover-overlay`, `.checkin-result`, `.checkin-code`, `#code-input`,
  `.chat-log/.chat-msg/.chat-bot/.chat-user`, `.event-cover(-lg)`, `.avatar(-sm/-lg)`,
  `.star-rating`, `.task-overdue/.task-done`.
- Màu nhấn dùng biến `var(--brand)` / `var(--accent)` để **đổi theo cảnh nền**.
- Header mỗi trang: viền trên `3px solid var(--brand)` + kicker chữ nhỏ brand.
- Trạng thái → luôn map ra pill mềm (`bg-success-subtle` OPEN, `bg-secondary-subtle`
  DRAFT, `bg-danger-subtle` CANCELLED, `bg-dark-subtle` DONE, `bg-warning-subtle` còn lại).

---

## ✅ 1. Danh sách sự kiện — ĐÃ XONG (mẫu chuẩn)
`templates/events/list.html`. Đã có: page header + kicker, toolbar (pill trạng
thái + search + số đếm), thẻ sự kiện (badge ngày, pill trạng thái, chip giá,
scrim, clamp tên, thanh chỗ, CTA theo ngữ cảnh, click cả thẻ). **Các màn sau bám
theo phong cách này.**

---

## 2. Chi tiết sự kiện  *(ưu tiên cao — làm tiếp theo)*

**Ngữ cảnh** — `templates/events/detail.html`, view `events.views.event_detail`.
- Biến: `event`, `my_ticket_count` (số vé user đang giữ), `stat` (dict thống kê,
  CHỈ có khi user là lead — xem `feedback.services.event_statistics`).
- `event`: `name, description, cover, starts_at, register_deadline, location,
  status, get_status_display, is_registerable, is_past, total_quota, seats_left,
  task_progress, next_statuses`; `ticket_types.all` (mỗi vé: `name, price, is_free,
  quota, sold, remaining, is_sold_out`).
- Vấn đề hiện tại: 2 cột nhưng ảnh bìa nằm trong card nhỏ, khối đăng ký không dính,
  chọn loại vé bằng `<select>` khó thấy giá/chỗ, nút quản trị lead dàn ngang rối.

**Prompt thiết kế**
- **Hero ảnh bìa full-width** (dùng `.event-cover-lg` + `.cover-overlay`): tên sự
  kiện + pill trạng thái + `🗓 giờ/ngày` + `📍 địa điểm` đè lên đáy ảnh (chữ trắng,
  có scrim). Ảnh chưa upload thì dùng `cover-{{ event|cover_index }}.jpg`.
- **2 cột** dưới hero:
  - **Chính (col-lg-8):** mô tả (`linebreaksbr`); nếu là lead → hàng **KPI tiles**
    từ `stat` (vé đã đăng ký / check-in / tỉ lệ / doanh thu đã thu) + 1 card
    "Quản trị" gọn (Sửa · Công việc {{task_progress}}% · Người tham gia · Phản hồi ·
    đổi trạng thái bằng select+nút từ `next_statuses`).
  - **Sidebar (col-lg-4) DÍNH (`position-sticky top-0`, chừa khoảng cho navbar):**
    card **Đăng ký** — nếu `is_registerable`: chọn loại vé dạng **thẻ radio**
    (tên + giá/"Miễn phí" + "còn N"/"hết chỗ", vé hết thì disable), ô số lượng,
    nút **Đăng ký** (primary, to). Chưa đăng nhập → nút "Đăng nhập để đăng ký".
    Không đăng ký được → thông báo trạng thái (đã đóng/đã diễn ra/đã huỷ). Dưới là
    card "Các loại vé" (list giá + `sold/quota`), và nút "Gửi đánh giá" khi `DONE`.
- Form đăng ký POST `registrations:book` giữ nguyên field `ticket_type`, `quantity`.

**Nghiệm thu:** hero đọc rõ; card đăng ký dính khi cuộn ở desktop, xuống dưới hero
ở mobile; loại vé hết chỗ bị mờ + không chọn được; đủ tương phản sáng/tối.

---

## 3. Check-in (kiosk)  *(ưu tiên cao)*

**Ngữ cảnh** — `templates/registrations/checkin.html`, view `registrations.views.checkin`.
- Biến: `event`, `result`, `ticket`, `note`, `css_class` (`success`/`warning`/`danger`),
  `total`, `done`, `percent`. Form POST field `code`. `ticket`: `code, user.full_name,
  ticket_type.name, get_status_display, checked_in_at`.

**Prompt thiết kế** — tối ưu cho BTC đứng ở cửa, dùng điện thoại 1 tay:
- **Header kiosk:** tên sự kiện + **vòng/thanh tiến độ lớn** `done/total` và `percent`.
- **Ô nhập mã cực to** (`#code-input` có sẵn) + nút "Check-in" chiếm hết chiều ngang;
  **auto-focus** và tự chọn lại nội dung sau mỗi lần gửi (JS nhỏ trong trang).
- **Kết quả full-card** tô theo `css_class` (xanh/vàng/đỏ) — dùng `.checkin-result`:
  biểu tượng lớn (✓ / ⚠ / ✕) nhìn từ xa là biết, `note`, và thông tin vé (`full_name`,
  loại vé, mã in bằng `.checkin-code`). Không có kết quả thì ẩn.
- **Bộ đếm đã check-in** luôn hiển thị nổi bật.

**Nghiệm thu:** phân biệt xanh/vàng/đỏ từ xa; ô mã auto-focus; đếm + % rõ; bấm gọn
một tay trên mobile; không cần cuộn để thấy kết quả.

---

## 4. Dashboard thống kê  *(ưu tiên cao)*

**Ngữ cảnh** — `templates/events/dashboard.html`, view `events.views.dashboard`.
- Biến: `rows` (mỗi sự kiện: `event, sold, checked_in, checkin_rate, pending,
  cancelled, revenue, rating_avg, rating_count, task_total, task_done,
  task_on_time_rate`), `checkin_chart`, `rating_chart` (đổ qua `|json_script`),
  `upcoming, total_sold, total_revenue, total_checked, checkin_rate`.
- Dùng Chart.js self-host + `static/js/charts.js`. Nhãn cột đã sửa "Doanh thu (đã thu)".

**Prompt thiết kế**
- **Hàng KPI tiles** đầu trang (4 ô): Sự kiện sắp tới (`upcoming`), Vé đã bán
  (`total_sold`), Doanh thu đã thu (`total_revenue`), Tỉ lệ check-in (`checkin_rate`%)
  — mỗi ô: nhãn nhỏ + **số lớn** + icon nhẹ.
- **2 biểu đồ** trong 2 card cạnh nhau (check-in stacked bar; điểm đánh giá bar).
  Áp **palette biểu đồ nhất quán** (gọi skill `dataviz` để chọn màu chuẩn, hợp
  brand, đọc được ở cả 2 theme).
- **Bảng so sánh** `rows`: header dính, cuộn ngang trên mobile, trong ô có **mini-bar**
  (tỉ lệ check-in) và sao (rating). Hàng rỗng → empty state.

**Nghiệm thu:** KPI quét được trong 3 giây; biểu đồ rõ ở sáng/tối; bảng cuộn ngang
gọn ở mobile; màu biểu đồ đồng bộ toàn app.

---

## 5. Vé của tôi

**Ngữ cảnh** — `templates/registrations/my_tickets.html`, view `registrations.views.my_tickets`.
- Biến: `tickets` (mỗi vé: `code, event, ticket_type, status, get_status_display,
  qr` (data-URI hoặc None), `is_active, price, created_at, checked_in_at, can_cancel`).
- Huỷ vé: POST `registrations:cancel pk`.

**Prompt thiết kế**
- Mỗi vé là **thẻ kiểu "cuống vé"** (ticket stub): một bên là **QR** (nếu `qr`),
  bên kia là tên sự kiện + `🗓` thời gian + loại vé + **mã `.checkin-code`** + pill
  trạng thái. Gợi ý đường **răng cưa/notch** ngăn 2 phần cho ra chất "vé".
- Nhóm **Sắp tới** / **Đã qua** (so `event.starts_at`); vé chờ thanh toán nhắc hạn 24h.
- Nút **Huỷ vé** chỉ hiện khi `can_cancel`. Empty state có nút "Xem sự kiện đang mở".

**Nghiệm thu:** QR đủ lớn để quét; trạng thái rõ; huỷ đúng điều kiện; đẹp khi stack mobile.

---

## 6. Phản hồi & thống kê (1 sự kiện)

**Ngữ cảnh** — `templates/feedback/list.html`, view `feedback.views.feedback_list`.
- Biến: `event, feedbacks, stat, type_chart, rating_dist, summary`
  (`summary`: `positive, negative, suggestion, feedback_count, generated_at`).
- Đã dùng Chart.js. Nút "Tóm tắt phản hồi" POST `feedback:ai_summarize`.

**Prompt thiết kế**
- **KPI tiles** (vé đăng ký / tỉ lệ check-in / điểm TB + số đánh giá / công việc xong).
- 2 biểu đồ (số vé theo loại; phân bố sao) — palette đồng bộ với Dashboard.
- **Tóm tắt AI thành "insight panel" nổi bật**: 3 cột **Được khen / Bị góp ý / Đề xuất**
  với icon + màu, tách khỏi danh sách phản hồi thô bên dưới.
- Danh sách phản hồi: avatar + sao + nội dung + thời gian, phân tách nhẹ.

**Nghiệm thu:** insight panel bắt mắt, tách bạch; biểu đồ nhất quán; danh sách dễ đọc.

---

## 7. Công việc BTC: Bảng + Việc của tôi

**Ngữ cảnh** — `organizing/board.html` (view `task_board`: `event, tasks,
overdue_count`) và `organizing/my_tasks.html` (view `my_tasks`: `tasks, overdue_count`).
- `Task`: `title, description, assignee, deadline, status` (TODO/DOING/DONE),
  `note, is_overdue, created_by_ai, get_status_display`. Đổi trạng thái: POST
  `organizing:set_status pk` (field `status`, `note`, `next`).

**Prompt thiết kế**
- **Bảng công việc = Kanban 3 cột** (Chưa làm / Đang làm / Xong), mỗi cột có tiêu đề
  + **đếm số**. Thẻ task: tên, **avatar người phụ trách**, deadline (đỏ nếu
  `is_overdue` — dùng `.task-overdue`), **badge "AI" nếu `created_by_ai`**, ghi chú.
  Đầu trang: thanh **tiến độ `task_progress`%** + cảnh báo `overdue_count` nếu > 0.
  Nút đổi trạng thái ngay trên thẻ (form POST nhỏ).
- **Việc của tôi:** danh sách sắp theo deadline, quá hạn nổi đỏ, đổi trạng thái nhanh
  (Chưa/Đang/Xong) + ô ghi chú tiến độ. Có thể nhóm theo trạng thái.

**Nghiệm thu:** 3 cột ở desktop, **stack dọc ở mobile**; quá hạn thấy ngay; người phụ
trách + task do AI tạo được đánh dấu rõ; đổi trạng thái không rời trang quá lâu.

---

## 8. Chat trợ lý

**Ngữ cảnh** — `templates/aiassist/chat.html`, view `aiassist.views.chat_page`
(biến `suggestions`). Gửi câu hỏi: POST JSON `aiassist:chat_api`. Đã có
`static/js/chatbot.js` + các class `.chat-*` (theme-aware).

**Prompt thiết kế**
- Khung chat **canh giữa, chiều cao cố định**, `.chat-log` cuộn trong.
- **Chip gợi ý** (`suggestions`) đặt dưới ô nhập hoặc ở màn chào ban đầu, bấm là hỏi luôn.
- **Typing indicator** khi chờ trả lời; ô nhập **dính đáy**; nút gửi rõ.
- Màn trống → lời chào + gợi ý; mobile chiếm gần hết chiều cao.

**Nghiệm thu:** đọc rõ ở cả 2 theme; chip gợi ý bấm được; ô nhập dính; cuộn mượt.

---

## 9. Trang phụ (gộp, ưu tiên thấp)

- **Người tham gia** (`registrations/participants.html`): toolbar giống Danh sách
  (pill trạng thái + search + số đếm) + **bảng** (cuộn ngang mobile) + nút xuất CSV.
- **Xác nhận thanh toán** (`registrations/payment_list.html`): bảng vé chờ + nút
  "Xác nhận" nổi bật + search theo mã.
- **Các form** (`events/form.html`, `organizing/form.html`, `events/ticket_type_form.html`,
  `feedback/form.html`): **card canh giữa** (max ~640px), nhãn rõ, nhóm field hợp lý,
  1 primary + 1 secondary (Huỷ). Lỗi field hiển thị tử tế.
- **Tài khoản** (`accounts/login, register, profile, user_list, user_role, audit_log`):
  login/register = card hẹp canh giữa; profile = avatar lớn + thông tin + form đổi mật
  khẩu; user_list/audit = bảng có search/phân trang.

**Nghiệm thu chung:** đồng bộ page header + card + spacing với các màn trên; không tràn
ngang; đẹp ở sáng/tối + mobile.

---

## Thứ tự đề xuất
2 → 3 → 4 → 5 → 6 → 7 → 8 → 9. Mỗi màn: xong thì tự chạy lại `manage.py test`,
xem ở **cả sáng/tối + khổ 400px**, **không commit** (người dùng tự commit).
