# LỆNH: Tinh giản giao diện về chuẩn chuyên nghiệp (bản khó tính)

> Bạn là **senior product designer gu tiết chế**. Nhiệm vụ: **gỡ nhiễu**, đưa
> KMG Club từ "hội chợ hiệu ứng" về **utility app đáng tin**. Không thêm cái đẹp -
> **bớt cái thừa**. Nguyên tắc vàng: **Restraint > Maximalism. Nội dung dẫn, chrome
> phục vụ.** Mọi hiệu ứng phải "trả tiền vé" bằng công dụng; không thì **cắt**.
> Tiêu chuẩn: *nhìn phải đắt hơn nhờ ÍT đi, không phải nhiều hơn.*

## Ràng buộc bất di bất dịch
- **No-CDN** - self-host mọi thứ trong `static/`.
- Không đổi logic nghiệp vụ (`views/services/models`); **giữ 87 test PASS**.
- Comment tiếng Việt; responsive tới 400px; giữ dark mode `data-bs-theme`.
- CSS trang đặt trong `<style>` của template hoặc class trong `app.css` - **cấm inline `style="..."`**.
- **Không commit** (người dùng tự commit).

---

## DANH SÁCH CẮT - làm đúng thứ tự

### CẮT 1 - Con trỏ tuỳ biến (nốt nhạc) → mặc định
`static/css/app.css`: xoá 2 khối `cursor: url("data:image/svg+xml...")` trên `body`
và trên `a, button, .btn, .nav-link, .cursor-pointer`, và rule `input,textarea,select{cursor:auto}`.
**Nghiệm thu:** con trỏ hệ thống bình thường khắp nơi, không SVG.

### CẮT 2 - Nền ảnh động 5 cảnh → nền tĩnh dịu
- Gỡ `<script src="...scene-theme.js">` khỏi `base.html`; bỏ `class="scene-0"` trên `<body>`.
- `app.css`: xoá `.scene-bg-container`, `.scene-layer`, `.scene-layer.active`,
  `@keyframes cosmicDrift`, và mọi tàn dư `body.scene-*`.
- Thay bằng nền **phẳng**: giữ `body { background: var(--bs-body-bg) }`. Tối đa cho phép
  **một** lớp gradient rất nhẹ on-brand (vd `radial-gradient` mờ ở một góc, alpha ≤ 0.06),
  **KHÔNG ảnh, KHÔNG animation, KHÔNG cross-fade.**
- Giữ file `static/img/scene-*.jpg` (đừng xoá) - có thể tái dùng làm ảnh bìa.
**Nghiệm thu:** nền đứng yên; mọi trang đọc rõ mà không cần lớp kính.

### CẮT 3 - Glassmorphism → bề mặt ĐẶC
- Bỏ **mọi** `backdrop-filter` / `-webkit-backdrop-filter` (card, hero, navbar, inline).
- `--app-surface` và `--app-surface-2` chuyển sang **màu đặc** (alpha = 1):
  sáng `#ffffff` / `#f1f5f9`; tối `#1e293b` / `#0f172a`.
- Cho phép giữ blur ở **tối đa 1 chỗ** (navbar) nếu thật sự cần; còn lại đặc hết.
**Nghiệm thu:** không còn kính chồng chéo; tương phản ổn định ở mọi trang.

### CẮT 4 - Emoji + icon rỗng → MỘT bộ icon thật
- Self-host **Bootstrap Icons** (tải `bootstrap-icons.css` + `fonts/*.woff2` về
  `static/vendor/bootstrap-icons/`, nhúng trong `base.html`). Không CDN.
- Thay **mọi emoji trong chrome** (🔎 🗓 📍 🕒 ✨ 📋 ☕ ⚪ 🔵 🟢 …) bằng `<i class="bi bi-...">`
  phù hợp (search, calendar-event, geo-alt, clock, robot, list-check, check-circle…).
- Đảm bảo **không còn `<i class="bi">` rỗng** (tức là font icon phải nạp được).
**Nghiệm thu:** 0 emoji trong UI chrome; 0 icon trống; icon đơn sắc theo màu chữ.

### CẮT 5 - Giảm chuyển động
- Bỏ `.btn:hover { transform: translateY(...) }` và `.card-event:hover { transform: scale/translateY mạnh }`
  → chỉ giữ đổi `box-shadow` nhẹ.
- Bỏ `progress-bar-striped progress-bar-animated` (hiệu ứng kẻ sọc chạy) trong `board.html`.
- Chuyển động chỉ còn ở: trạng thái focus, và fade rất nhẹ khi cần. Giữ `prefers-reduced-motion`.
**Nghiệm thu:** giao diện "tĩnh và chắc", không nhấp nhổm khi rê chuột.

### CẮT 6 - Thống nhất hệ thống (hết inline, hết CSS chết)
- Tạo **một** class `.page-header` (kicker brand + tiêu đề + mô tả + slot action, viền
  accent trên) trong `app.css`, và **dùng ở MỌI trang** (Danh sách, board, my_tasks,
  detail…). Xoá các header viết inline (`style="border-top:3px solid var(--brand)"`…).
- Xoá `.hero` nếu không trang nào dùng, hoặc gộp vào `.page-header`.
- Định nghĩa **thang chữ** (h1..h6, .kicker, .small) MỘT lần; cấm cỡ `rem` tuỳ hứng rải rác.
- Ép **thang spacing** bội số 8px (`.25rem`). Dời CSS trong `style="..."` của template vào class.
**Nghiệm thu:** `grep -rn 'style="' templates/` gần như trống; header mọi trang giống hệt.

### CẮT 7 - Chi tiết tay nghề
- **Brand:** xanh `#2563eb` là xanh SaaS mặc định, thiếu bản sắc. Đề xuất 2–3 mã có
  cá tính hơn cho user chọn (giữ độ tương phản nút ≥ 4.5:1), sửa đúng `--brand` ở `:root`.
- **Favicon:** thay `logo.jpg` bằng icon **phẳng** (SVG hoặc PNG 32px nền trong).
- **Heading:** giảm `letter-spacing` từ `-0.02em` xuống `-0.01em` (hoặc 0 ở cỡ nhỏ) cho
  dấu tiếng Việt thở.
- **Navbar contrast:** đặt nền navbar **đặc hơn** (vd `rgba(15,23,42,.9)`) để chữ trắng
  luôn rõ, không phụ thuộc nền.

---

## Definition of Done (tự kiểm trước khi báo xong)
- [ ] Không con trỏ tuỳ biến, không nền động, không glass thừa, không emoji-icon, không icon rỗng.
- [ ] `grep -rn 'backdrop-filter\|cursor: url\|-striped' static/css templates` → sạch.
- [ ] `grep -rn 'style="' templates/` → gần như 0.
- [ ] `python manage.py test` 87/87 PASS; `python manage.py check` 0 lỗi.
- [ ] Xem **2 theme + khổ 400px**: header đồng nhất, tương phản đạt, không giật.
- [ ] Đặt ảnh trước/sau cạnh nhau: bản mới **ít hiệu ứng hơn mà trông chuyên nghiệp hơn**.

> Nếu vẫn muốn giữ chút "sống động": mức TRẦN cho phép là **một** ảnh tĩnh on-brand phủ
> mờ 8–12% sau nội dung, **không animation**. Vượt mức đó là quay lại hội chợ - đừng.
