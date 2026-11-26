# KMG Soft Icons 1.0

Bộ biểu tượng SVG nội bộ đồng bộ với tinh thần nhẹ nhàng, nghệ thuật và thân thiện của **CLB Guitar KMG**.

## 1. Thông số kỹ thuật
- Khung chuẩn: `viewBox="0 0 24 24"`.
- Độ dày nét (`stroke-width`): `1.65px` ở kích thước mặc định (`1.45px` với `xl`, `1.7px` với `sm`).
- Đầu nét & góc nối: `stroke-linecap="round"`, `stroke-linejoin="round"`.
- Màu sắc: `stroke="currentColor"`, `fill="none"` -> tự động thích ứng Light / Dark Mode và trạng thái `.active` trong sidebar/button.
- Nguồn chuẩn duy nhất (Single Source of Truth): `core/icons.py` (`KMG_SOFT_ICONS`) + template tag `{% kmg_icon "tên" %}` (`events/templatetags/ui.py`) + partial `templates/components/icon.html`.

## 2. Cách sử dụng trong Django Template
```django
{% load ui %}
{% kmg_icon "guitar" "md" "me-1" %}
```
Hoặc dùng qua component:
```django
{% include "components/icon.html" with name="sparkles" size="sm" css_class="me-1" %}
```

## 3. Lộ trình chuyển đổi (Chờ phê duyệt Gate)
- **Hiện tại (Sprint 1):** Cho phép xem đối chiếu trực tiếp 30 icon mẫu trên 7 nhóm chức năng tại `/dev/design-system/`.
- **Sau phê duyệt (Sprint 2):** Thay thế từng nhóm từ Sidebar, Navbar, Buttons, KPI Tiles sang `{% kmg_icon %}` để đạt đồng nhất nét vẽ 100%.
