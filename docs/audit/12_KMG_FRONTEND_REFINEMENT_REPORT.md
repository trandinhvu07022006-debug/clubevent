# Báo cáo Cải tiến Giao diện & Trải nghiệm — KMG UI/UX Refinement 3.0 (Sprint 1 & Design Gate)

**Ngày lập:** 2026-11-26  
**Nhánh Git:** `feature/kmg-system-stabilization`  
**Trạng thái chung:** `Sprint 1 VERIFIED` · `Design Approval Gate REVIEW_REQUIRED` · `Chrome Remote Debugging BLOCKED`

---

## 1. Kết quả kiểm tra hiện trạng (Baseline trước chỉnh sửa)

Đo đạc trực tiếp trên cây mã nguồn `5162738` và máy chủ SQLite demo (`127.0.0.1:8019` với dữ liệu `seed_kmg` + `seed_demo`):

- **Quy mô template:** `103` tệp `.html` trên 17 app (`department_detail.html` 673 dòng, `governance_center.html` 564 dòng, `public_portal/home.html` 448 dòng, `workspace_home.html` 444 dòng, `base.html` 423 dòng, `floating_chat.html` 403 dòng).
- **Mức độ phân mảnh CSS/HTML:** `133` thuộc tính `style="..."` inline, `68` mã màu hex cứng trong HTML, `368` khối `.card` + `185` khối `.kmg-card`.
- **Lỗi P0 xác nhận trực tiếp qua HTTP:**
  - `GET /static/css/kmg_editorial.css` trên `/portal/` trả **`HTTP 404`**, đồng thời `templates/base.html` không nạp tệp này khiến toàn bộ 185 thẻ `.kmg-card`, 26 `.kmg-kicker`, 20 `.kmg-badge-gold`, 14 `.kmg-dept-icon` trong workspace bị mất style nền/viền.
  - `templates/base.html:213` gắn `text-primary` cứng trên `<i class="bi bi-grid-1x2-fill text-primary">` làm icon mục `Không gian CLB` đang chọn bị chìm xanh-trên-nền-xanh.
  - Hơn 50 vị trí dùng class cứng theo nền sáng (`text-bg-light`, `alert-light`, `bg-light`, `text-dark`, `btn-outline-dark`) trên `giam-sat/`, `quan-tri/`, `huan-luyen/`, `dao-tao/`, `tin-nhan/`, `danh-gia/`, `tai-chinh/`.
  - `templates/registrations/my_tickets.html:38` tham chiếu `--app-bg` chưa định nghĩa.
  - `templates/500.html` dùng font `system-ui` và nút `#0d6efd` không khớp nhận diện Xanh mực `#34477d` và chưa có Dark Mode.

---

## 2. Các hạng mục Sprint 1 đã triển khai (An toàn, bảo toàn bản sắc)

1. **Thiết lập tầng Design Tokens thống nhất (`static/css/tokens.css`):**
   - Hợp nhất Light/Dark token giữ nguyên bản sắc Xanh mực (`#34477d` / `#5068c0`), Vàng cát ấm (`#a87d26` / `#d9a441`), Giấy ấm (`#f7f6f3` / `#14161d`), bổ sung `--app-bg` và cầu nối `--kmg-*`.
2. **Khôi phục & đồng bộ `static/css/kmg_editorial.css`:**
   - Khôi phục đầy đủ `.kmg-public-body`, `.kmg-public-header` (thêm `color: #ffffff;` sửa tương phản header), `.kmg-hero`, `.kmg-kicker`, `.kmg-card`, `.kmg-badge-gold`, `.kmg-dept-icon`, `.kmg-stat-box`, `.kmg-footer` đồng bộ với `tokens.css` cả Light & Dark.
   - Nhúng `tokens.css`, `kmg_editorial.css`, `sidebar.css`, `components/icons.css` vào `templates/base.html` và `templates/public_portal/home.html`.
3. **Vá lỗi Dark Mode & Trang lỗi:**
   - Sửa icon active sidebar tại `templates/base.html` + thêm cầu nối Dark Mode trong `static/css/app.css` (Section 21) cho `.text-bg-light`, `.alert-light`, `.bg-light`, `.btn-outline-dark`.
   - Sửa `templates/registrations/my_tickets.html` (`var(--bs-body-bg)`), `templates/social/messaging.html` (`btn-outline-secondary`), `templates/finance/hub.html` (`bg-body-secondary text-body`), `templates/evaluations/hub.html` (bỏ `text-dark` khỏi nút viền vàng).
   - Chuẩn hoá `templates/403.html`, `templates/404.html`, `templates/500.html` theo nhận diện KMG ở cả Sáng & Tối (`500.html` giữ HTML độc lập không phụ thuộc base/asset).
4. **Xây dựng KMG Soft Icons 1.0 & Trang đối chiếu `/dev/design-system/`:**
   - Tạo `core/icons.py` với `30` biểu tượng SVG nét mềm `24x24` (`stroke-width: 1.65`, `round`, `currentColor`) phân 7 nhóm chức năng + xuất tệp SVG nguồn tại `static/icons/kmg/*.svg`.
   - Bổ sung template tag `{% kmg_icon %}` trong `events/templatetags/ui.py` (tự động `escape()` tránh XSS) và partial `templates/components/icon.html`.
   - Mở route nội bộ `/dev/design-system/` (`pages/views.py`, khoá bằng `DEBUG=True` hoặc `is_admin_role` / `is_superuser`, trả `404` với người dùng thường khi `DEBUG=False`) hiển thị bảng màu, bảng đối chiếu từng cặp Bootstrap Icons vs KMG Soft Icons 1.0 và mẫu tinh giản card.
5. **Hệ thống tài liệu thiết kế:**
   - `docs/design/KMG_UI_UX_MASTER_PLAN.md`
   - `docs/design/KMG_DESIGN_SYSTEM.md`
   - `docs/design/KMG_SOFT_ICONS.md`
   - `docs/design/UI_TERMINOLOGY_VI.md`
   - `docs/design/COMPONENT_GUIDELINES.md`

---

## 3. Kết quả kiểm chứng sau chỉnh sửa cuối cùng

| Hạng mục kiểm thử | Lệnh / Cơ chế | Kết quả | Ghi chú |
|---|---|---|---|
| **Design System Unit Tests** | `manage.py test pages.test_design_system --settings=config.settings_test -v 2` | **PASS (4/4 OK)** | Kiểm tra static assets, escaping XSS của `{% kmg_icon %}`, nạp CSS ở `/portal/` & dashboard, kiểm soát truy cập `404/200` của `/dev/design-system/` |
| **Toàn bộ Test Suite** | `manage.py test --settings=config.settings_test` | **661 tests OK (skipped=2)** trong `198.105s` | 2 test skip thuộc `RedisRateLimitTests` do không có `KMG_TEST_REDIS_URL` cục bộ |
| **Kiểm định AI** | `manage.py evaluate_ai --with-migrate --settings=config.settings_test` | **EVAL ĐẠT** | `dev` `38/38`, `holdout` `22/22`, `blind` `50/50`; RAG `dev` `13/13`, `holdout` `7/8` (88%); Che PII `6/6`; Fallback đạt |
| **Kiểm tra HTTP & Static Asset thực tế** | Script đối chiếu trên máy chủ cô lập `127.0.0.1:8019` | **11/11 routes HTTP 200** | Đã kiểm chứng `/`, `/portal/`, `/sukien/`, `/taikhoan/dangnhap/`, `/tong-quan/`, `/workspace/`, `/workspace/quan-tri/`, `/workspace/tai-chinh/`, `/workspace/tin-nhan/`, `/workspace/danh-gia/`, `/dev/design-system/`; `broken=[]`, không còn `btn-outline-dark` hay `alert-light` |
| **Ảnh chụp trình duyệt Chrome trực quan (`360px–1920px`)** | Tác nhân `browser` qua Chrome DevTools MCP | **BLOCKED** | Lỗi môi trường: chưa bật Chrome Remote Debugging (`ENOENT: ...\Google\Chrome\User Data\DevToolsActivePort`) |

---

## 4. Cổng phê duyệt thiết kế (Design Approval Gate — Chờ quyết định của Chủ dự án)

Trước khi thực hiện **Sprint 2–4** (thay thế đồng loạt trên toàn bộ 103 template), đề nghị Chủ dự án mở `/dev/design-system/` (ở cả **Nền sáng** và **Nền tối**) và xác nhận 3 điểm:

1. **Bộ biểu tượng KMG Soft Icons 1.0:** Đồng ý thay thế dần 30 biểu tượng Bootstrap Icons cốt lõi sang SVG nét mềm KMG Soft Icons 1.0 trên Sidebar, Header, Buttons và KPI Tiles?
2. **Đơn giản hoá điều hướng kép:** Có đồng ý giữ `/portal/` là trang giới thiệu công khai chuyên sâu hoặc gộp điểm vào giữa `/` (`pages:home`) và `/portal/` (`public_portal:home`), và giữa `/tong-quan/` với `/workspace/`?
3. **Thuần Việt hoá nhãn kỹ thuật:** Đồng ý ẩn các mã nội bộ (`D04 v1.1`, `Phase 5 · WF22`, `INV-03/04`, `BE-07`, `Stage Spec`) khỏi tiêu đề/nút giao diện người dùng cuối để thay bằng tiếng Việt tự nhiên như `docs/design/UI_TERMINOLOGY_VI.md`?
