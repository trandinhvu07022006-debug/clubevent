# LỆNH: Nâng cấp điều hướng & thành phần giao diện (học từ Parroto)

> Bạn là **senior product designer kiêm front-end**. Nhiệm vụ: nâng KMG Club từ
> "một thanh menu dài" lên **ứng dụng quản lý có cấu trúc** - người dùng biết
> ngay mình ở đâu, việc gì đang chờ, bấm gì tiếp theo.
> Tham chiếu: giao diện Parroto (app học từ vựng). **Học cách tổ chức, KHÔNG
> chép độ rối.** Parroto cần giữ chân người dùng nên nhồi nhiều thứ; web CLB
> thì ngược lại: *vào - làm xong việc - thoát*.

## Ràng buộc bất di bất dịch

- **No-CDN.** Wifi phòng học chập chờn là mất sạch CSS giữa lúc demo. Mọi thứ
  self-host trong `static/vendor/`.
- **Không thêm thư viện JS.** Bootstrap 5.3 bundle đã có sẵn Offcanvas,
  Dropdown, Collapse, Tab - đủ cho toàn bộ việc dưới đây.
- **Không đổi logic nghiệp vụ** (`views/services/models`) ngoài phần context
  processor ở mục 1. **Giữ 87 test PASS** (`python manage.py test`).
- **Màu lấy từ token** trong `:root` của `static/css/app.css`. Không hardcode
  mã hex vào template.
- **Giữ dark mode** `data-bs-theme`. Mọi thành phần mới phải thử ở cả 2 theme.
- **Comment tiếng Việt**, giao diện tiếng Việt.

## Hiện trạng - đọc trước khi sửa

Đây là những thứ đã làm và **phải giữ**, agent hay vô tình phá:

| Thứ đã có | Ở đâu | Lưu ý |
|---|---|---|
| Hệ token màu (xanh mực) | `app.css` mục 1 | Đổi màu cả web chỉ sửa 4 dòng đầu |
| `--brand` vs `--brand-text` | `app.css` mục 1 | **Hai vai trò khác nhau** - xem dưới |
| Vùng chạm chuẩn WCAG | `app.css` mục 13 | Nút ≥44px trên cảm ứng, ≥36px trên chuột |
| Chống iOS tự zoom | `app.css` mục 13 | Ô nhập ≥16px trên màn nhỏ |
| Bố cục chữ | `app.css` mục 2b | `text-wrap: balance`, `.prose`, `clamp()` |
| Ảnh nền núi sương mù | `app.css` mục 2 | Voan 0.58 - đã đo, đừng hạ thêm |
| Avatar dùng chung | `templates/partials/avatar.html` | Dùng lại, đừng viết mới |

**Về `--brand` và `--brand-text`** - lỗi dễ mắc nhất:
- `--brand` là màu **NỀN** (nút, pill, badge có chữ trắng đè lên). Phải đậm.
- `--brand-text` là màu **CHỮ** (link, nhãn, icon trên nền trang). Ở theme tối
  nó sáng hơn hẳn.
- Dùng `--brand` làm màu chữ trên nền tối → tương phản chỉ ~2.3:1, **không đọc
  được**. Dùng `--brand-text` làm nền nút → chữ trắng mờ.

---

## Học gì - và KHÔNG học gì - từ Parroto

**Học:**

| Kỹ thuật | Vì sao hiệu quả |
|---|---|
| Sidebar trái cố định | Chứa nhiều mục không chen chúc; nhóm theo vai trò; thu gọn được |
| Badge số trên mục nav | Biến điều hướng thành bảng tin - biết ngay chỗ cần xử lý |
| Segmented control | Chuyển chế độ trong cùng ngữ cảnh, không mất vị trí |
| Hàng danh sách có icon | Icon + tiêu đề + số liệu phụ → quét mắt nhanh |
| Phân cấp CTA 3 bậc | Đặc = chính, viền = phụ, đỏ = phá huỷ |
| Empty state có hình + lời dẫn | Màn hình trống thành hướng dẫn bước tiếp theo |
| Hồ sơ ghim đáy sidebar | Luôn thấy đang đăng nhập bằng ai, vai trò gì |

**KHÔNG học** (gây nhiễu, không hợp web nội bộ CLB):

- Dải 9 icon chia sẻ mạng xã hội nổi bên phải.
- Banner quảng cáo + nút tải app trên cùng.
- Chồng huy hiệu game hoá ở thanh trên (kim cương, điểm, PRO…).
- Bong bóng chat nổi góc màn hình - đã có trang Hỗ trợ riêng.

---

## Nhiệm vụ - làm theo thứ tự ưu tiên

### 1. Sidebar + badge ★★★ - **DỪNG LẠI CHO DUYỆT SAU MỤC NÀY**

**Vấn đề:** navbar trong `templates/base.html` hiện có **6 mục + nút theme +
menu người dùng** trên một hàng với tài khoản trưởng ban; tài khoản admin còn
thêm mục "Tài khoản" thành **7 mục**. Ở laptop 1366px đã sát mép; thêm một mục
nữa là vỡ.

**Làm:** với người **đã đăng nhập**, chuyển điều hướng sang sidebar trái, nhóm
theo vai trò. Khách vãng lai giữ navbar trên như cũ (ít mục).

```
CHUNG          Sự kiện · Vé của tôi · Hỗ trợ
BAN TỔ CHỨC    Việc của tôi (3) · Xác nhận TT (5)      <- chỉ is_staff_btc
QUẢN TRỊ       Thống kê · Tài khoản                     <- is_lead / is_admin_role
────────────────────────────────────────
[avatar] Tên người dùng · Vai trò       [Thu gọn]
```

Giữ đúng các điều kiện phân quyền đang có trong `base.html`
(`user.is_staff_btc`, `user.is_lead`, `user.is_admin_role`) và đúng logic
đánh dấu `active` theo `request.resolver_match`.

**Badge lấy từ model có sẵn** (đã kiểm tra):

| Mục | Đếm gì | Nguồn |
|---|---|---|
| Xác nhận TT | Vé `status=TicketStatus.PENDING` | `registrations/models.py:19` |
| Việc của tôi | Task `status__in=[TODO, DOING]` được giao cho user | `organizing/models.py:15` |

- Dự án **chưa có context processor tự viết** nào (`config/settings.py:84`).
  Tạo mới, ví dụ `core/context_processors.py`, rồi đăng ký vào
  `TEMPLATES[0]["OPTIONS"]["context_processors"]`.
- **Chỉ query khi `user.is_authenticated`** và đúng vai trò - khách không được
  tốn query nào.
- **Cache 30–60 giây** theo user (Django cache framework có sẵn). Không cache
  thì mỗi lần tải bất kỳ trang nào cũng bắn thêm 2 query COUNT.
- Badge = 0 thì **ẩn**, không hiện số 0.
- Badge dùng nền `--brand` (hoặc `--bs-danger` cho việc quá hạn), chữ trắng.

**Mobile (< 992px):** sidebar thành Bootstrap `.offcanvas` mở bằng nút
hamburger. Không tự viết JS trượt ngăn kéo.

**Thu gọn (desktop):** nút "Thu gọn" rút sidebar về chỉ còn icon. Nhớ trạng
thái bằng `localStorage` (bọc `try/catch` giống đoạn đổi theme sẵn có trong
`base.html`). Khi thu gọn, mỗi icon cần `title` / `aria-label` để còn biết là gì.

**Nghiệm thu mục 1:**
- [ ] Đăng nhập 4 vai trò (khách, thành viên, BTC, admin) - mỗi vai trò thấy
      đúng nhóm mục của mình, không thiếu không thừa.
- [ ] Badge đúng số khi tạo thêm vé chờ thanh toán / task mới.
- [ ] Khách vãng lai: số query **không tăng** so với trước (dùng
      `django.test.utils.CaptureQueriesContext` hoặc debug toolbar).
- [ ] Mobile: mở/đóng offcanvas được, không tràn ngang.
- [ ] Thu gọn/mở rộng, tải lại trang vẫn giữ trạng thái.
- [ ] 87 test PASS.

> **Sau mục 1, DỪNG và gửi ảnh chụp cả 2 theme + mobile để duyệt.** Mục này
> động vào `base.html` nên ảnh hưởng MỌI trang - phải duyệt trước khi làm tiếp.

### 2. Empty state ★★★

Hiện `templates/events/list.html` (khối `{% empty %}`) chỉ có icon lịch và câu
"Không tìm thấy sự kiện nào".

**Làm:** partial dùng chung `templates/partials/empty_state.html`, nhận tham số
`icon`, `title`, `desc`, `action_url`, `action_label`. Công thức: **hình/icon lớn
+ câu dẫn + MỘT hành động tiếp theo.**

Áp dụng cho: danh sách sự kiện, vé của tôi, việc của tôi, danh sách phản hồi,
danh sách người tham gia.

Ví dụ nội dung:
- Vé của tôi trống → "Bạn chưa đăng ký sự kiện nào" + nút "Xem sự kiện sắp tới".
- Việc của tôi trống → "Không còn việc nào - tuyệt vời!" (trạng thái *tích
  cực*, như Parroto) - không cần nút.

Dùng Bootstrap Icons có sẵn trong `static/vendor/bootstrap-icons/`. **Không**
thêm ảnh minh hoạ nặng.

### 3. Segmented control ★★

**a) Bộ lọc trạng thái** - `.filter-pill` trong `events/list.html` đang là các
pill rời. Gom thành một khối liền mạch (dùng `.btn-group` của Bootstrap), mục
đang chọn nền `--brand`. Giữ nguyên cơ chế lọc bằng query string `?status=`.

**b) Trang chi tiết sự kiện** - `events/detail.html` đang đổ mọi thứ vào một
trang. Tách tab: `Thông tin · Loại vé · Người tham gia · Công việc` (Bootstrap
`.nav-tabs` / Tab JS). Tab nào người xem không có quyền thì **không render**,
không chỉ ẩn bằng CSS.

Trên màn hẹp: segmented control phải **cuộn ngang** được
(`overflow-x: auto`), không được xuống dòng thành nhiều hàng lộn xộn.

### 4. Hàng danh sách có icon ★★

Mẫu thống nhất:

```
[icon/avatar]  Tiêu đề đậm                         [số liệu bên phải]
               dòng phụ nhỏ, màu --bs-secondary
```

Áp cho: loại vé (icon vé), người tham gia (dùng `partials/avatar.html`), công
việc (icon theo trạng thái). Viết thành **một class dùng chung** trong
`app.css`, không viết CSS riêng mỗi trang.

### 5. Thanh tiến độ có nhãn ★★

Học từ "Đã học 49/49 từ". Áp cho: `Đã bán 87/100 vé`, `Hoàn thành 12/15 công
việc`. Tận dụng `.progress.seats` sẵn có trong `app.css`; chỉ chuẩn hoá phần
nhãn số đi kèm. Luôn kèm `role="progressbar"` và `aria-valuenow/min/max`.

### 6. Chuẩn hoá 3 bậc nút ★

Ghi thành quy tắc (comment) trong `app.css` mục 4 và rà soát toàn bộ template:

| Bậc | Class | Quy tắc |
|---|---|---|
| Chính | `btn-primary` | **Tối đa 1 nút / màn hình** |
| Phụ | `btn-outline-secondary` | Hành động thay thế |
| Phá huỷ | `btn-outline-danger` | Huỷ vé, xoá - luôn có bước xác nhận |

---

## Bài học từ lần triển khai sidebar - ĐỌC TRƯỚC KHI SỬA GIAO DIỆN

Lần làm sidebar vừa rồi mắc 6 lỗi. Không lỗi nào hiện ra ở theme sáng; tất cả
chỉ lộ khi xem **theme tối** - vì không ai chụp kiểm tra theme tối trước khi báo xong.

| Lỗi | Nguyên nhân | Cách đúng |
|---|---|---|
| Hai màu xanh khác nhau | Bootstrap GHI CỨNG `#0d6efd` vào 12 nhóm thành phần; đổi `--bs-primary` không chạm tới | Đã có "cầu nối" ở `app.css` mục 16. Thành phần Bootstrap mới nào dùng màu primary → kiểm tra xem nó có trong mục 16 chưa |
| Khối trắng giữa nền tối, chữ 2.25:1 | Dùng `bg-light`, `bg-white`, `text-dark`, `btn-light` - luôn sáng, không đổi theo theme | Dùng token (`var(--app-surface)`…) hoặc class tự đổi theo theme (`bg-body`, `text-body`, `bg-*-subtle`, `text-bg-*`) |
| Bộ lọc bị cắt mất 2 mục | Dùng `w-lg-auto` - class **không tồn tại** trong Bootstrap | Bootstrap không có width theo breakpoint. Viết class riêng trong `app.css` |
| Icon "Hỗ trợ" không hiện | `bi-chat-stars` không có trong bộ icon đang self-host | Tra `static/vendor/bootstrap-icons/bootstrap-icons.css` trước khi dùng |
| Sidebar trong suốt | Bootstrap ép `.offcanvas-lg` trong suốt kèm `!important` trên màn ≥ 992px | Đã sửa ở `app.css` mục 16 |
| Nút giao diện biến mất (theme sáng) | Tái dùng class `.nav-theme-toggle` viết cho navbar tối (chữ trắng cứng) | Dời thành phần sang nền khác → kiểm tra lại màu của nó |

**Lệnh kiểm tra BẮT BUỘC** chạy trước khi báo xong, cả hai phải trả về rỗng:

```bash
# 1. Class màu cố định (được phép giữ nếu nằm TRÊN ẢNH TỐI cố định và gắn data-on-dark-image)
grep -rnE "\b(bg-light|bg-white|text-dark|text-black|btn-light)\b" templates/ \
  | grep -vE "text-dark-emphasis|bg-dark-subtle|bg-light-subtle|data-on-dark-image"

# 2. Class width theo breakpoint - không tồn tại trong Bootstrap
grep -rnoE "\bw-(sm|md|lg|xl|xxl)-[a-z0-9]+\b" templates/
```

Và kiểm tra icon: mọi `bi-xxx` trong template phải có `.bi-xxx::before` trong
`static/vendor/bootstrap-icons/bootstrap-icons.css`.

## Checklist nghiệm thu chung (áp cho MỌI mục)

- [ ] **Chụp màn hình thật** để tự kiểm tra - không báo "xong" chỉ dựa vào
      việc code chạy. Chrome headless có sẵn trên máy:
      `chrome --headless=new --screenshot=out.png --window-size=1400,1000 <url>`.
      Lưu ý: headless **không hạ được viewport dưới ~482px**; cần kiểm trên
      điện thoại thật cho khổ 360–390px.
- [ ] Cả theme sáng và tối.
- [ ] Đích chạm ≥44px trên cảm ứng (mục 13 đã lo, nhưng thành phần mới phải
      kế thừa đúng class).
- [ ] Không tràn ngang: `document.documentElement.scrollWidth` bằng
      `clientWidth` ở mọi trang.
- [ ] Tương phản chữ ≥4.5:1 (đồ hoạ ≥3:1). Đo, đừng đoán.
- [ ] Không phát sinh request tới domain ngoài (mở tab Network kiểm tra).
- [ ] `python manage.py check` sạch, **87 test PASS**.

## Tiêu chuẩn "đẹp" để tự chấm

Một thay đổi chỉ đáng giữ nếu trả lời "có" cho câu: *"Người dùng làm xong việc
**nhanh hơn** hoặc **ít nhầm hơn** nhờ nó không?"* Nếu chỉ để trông giống
Parroto - **cắt**.
