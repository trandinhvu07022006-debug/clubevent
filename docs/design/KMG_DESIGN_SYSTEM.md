# KMG Design System 1.0

Tài liệu quy chuẩn hệ thống giao diện cho **KMG Platform** (CLB Guitar KMA).

## 1. Bản sắc thương hiệu (Giữ nguyên 100%)
- **Xanh mực (Deep Ink Blue):** `--brand` (`#34477d` Sáng / `#5068c0` Tối) — dùng cho nút hành động chính, mục đang chọn, header điều hướng.
- **Vàng cát ấm (Warm Gold):** `--accent` (`#a87d26` Sáng / `#d9a441` Tối) — dùng cho điểm nhấn văn hoá CLB, huy hiệu ghi nhận, sao đánh giá.
- **Nền giấy ấm / Đêm xanh mực:** `--app-bg` (`#f7f6f3` Sáng / `#14161d` Tối), bề mặt thẻ đặc `--app-surface` (`#ffffff` Sáng / `#1d202a` Tối).
- **Kiểu chữ:** Self-hosted `Be Vietnam Pro` (`static/css/fonts.css`), không gọi CDN bên ngoài.

## 2. Thứ tự nạp Stylesheet (`templates/base.html`)
1. `css/fonts.css` — phông chữ tiếng Việt cục bộ.
2. `vendor/bootstrap/bootstrap.min.css` & `vendor/bootstrap-icons/bootstrap-icons.css`.
3. `css/tokens.css` — Single Source of Truth cho biến màu, bán kính, bóng đổ Sáng/Tối.
4. `css/app.css` — lớp ứng dụng chính & cầu nối an toàn Dark Mode.
5. `css/site.css` — lớp trang công khai & footer.
6. `css/kmg_editorial.css` — lớp trang chủ Portal (`/portal/`) và không gian Workspace (`/workspace/*`).
7. `css/sidebar.css` — bố cục sidebar cố định/thu gọn.
8. `css/components/icons.css` — kiểu dáng cho `KMG Soft Icons 1.0`.

## 3. Quy tắc Light / Dark Parity
- **Tuyệt đối không dùng** class cứng theo theme sáng: `text-bg-light`, `alert-light`, `bg-light`, `text-dark`, `btn-outline-dark` trên nội dung thông thường.
- **Dùng biến ngữ nghĩa Bootstrap 5.3 / Token KMG:** `bg-body-secondary text-body border`, `text-body-secondary`, `btn-outline-secondary`, `--app-surface`, `--app-border`.
- **Trang kiểm tra trực quan nội bộ:** `/dev/design-system/` (chỉ mở khi `DEBUG=True` hoặc tài khoản `is_admin_role`).
