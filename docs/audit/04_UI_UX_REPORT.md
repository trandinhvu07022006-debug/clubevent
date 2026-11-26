# PHASE 4 — BÁO CÁO RÀ SOÁT UI/UX & ACCESSIBILITY (UI/UX REPORT)

**Ngày thực hiện:** 2026-11-26  
**Nhánh làm việc:** `feature/kmg-system-stabilization`  

---

## 1. Tổng quan hệ thống giao diện & phân tách không gian

- **Design System (`static/css/app.css`, `static/css/site.css`, `templates/base.html`):**
  - Toàn bộ CSS, font chữ (`fonts.css`), `bootstrap.min.css` và `bootstrap-icons.css` đều được **self-host** trong `static/vendor/` (không phụ thuộc CDN bên ngoài khi demo hoặc mất Internet).
  - Hỗ trợ **Light / Dark mode** qua `data-bs-theme` lưu `localStorage`, áp dụng ngay trong `<head>` trước khi render CSS để tránh nháy sáng/tối.
  - Đã định nghĩa media query cho người dùng giảm chuyển động `@media (prefers-reduced-motion: reduce)`.

- **Phân tách không gian làm việc theo vai trò (`templates/base.html`):**
  - **Public Website:** Thanh menu công khai `site-nav` cho Khách (`/` — `public_portal`, `/gioi-thieu/`).
  - **Sidebar nội bộ (`#appSidebar` + offcanvas mobile):** Chia rõ các nhóm `Khám phá`, `Cá nhân` (Vé của tôi, Thông báo có badge unread, Hồ sơ cá nhân, Ứng tuyển / Các Ban, Hỗ trợ AI), `Tổ chức` (`user.is_staff_btc`), `Quản trị` (`user.is_lead` + `user.is_admin_role`), và `KMG Platform` (`/workspace/`).
  - **KMG AI Assistant:** Có cả trang chat chuyên biệt (`/troly/`) và Floating Chat Widget (`templates/partials/floating_chat.html`, `static/js/chatbot.js`), hiển thị nguồn trích dẫn (`sources`) an toàn bằng `textContent`.

---

## 2. Responsive & Accessibility đã xác minh ở mã nguồn

| Tiêu chí | Thực tế trên mã nguồn | Trạng thái |
|---|---|---|
| **Breakpoints responsive** | `static/css/app.css` & `site.css` có `@media (max-width: 575.98px)`, `(max-width: 767.98px)`, `(min-width: 768px)`, `(max-width: 991.98px)` và `(min-width: 992px)` bao phủ dải `360px / 390px / 768px / 1024px / 1440px / 1920px`. | **IMPLEMENTED** |
| **Vùng chạm thiết bị di động** | `@media (pointer: coarse)` đặt `min-height: 44px` / `44x44` cho nút điều khiển, chip và chuông thông báo. | **IMPLEMENTED** |
| **Điều hướng bàn phím & Screen Reader** | Có `.skip-link` (`#main`), `aria-label` trên nút mở menu mobile, nút đổi theme, sidebar navigation và vùng ARIA thông báo. | **IMPLEMENTED** |
| **Chụp ảnh & kiểm thử trình duyệt thực tế (`360px–1920px`)** | Chưa cài Playwright/headless test runner trong bộ CI và chưa thực hiện đợt chụp ảnh màn hình trước/sau tự động trong phiên này. | **REVIEW_REQUIRED** |
