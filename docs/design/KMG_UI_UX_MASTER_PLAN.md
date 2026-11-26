# KMG UI/UX MASTER PLAN — REFINEMENT 3.0

**Phiên bản:** 3.0 (Sprint Baseline & Design System Plan)  
**Nhánh thực thi:** `feature/kmg-system-stabilization`  
**Ngày lập:** 2026-11-26  
**Triết lý thiết kế:** *Giữ nguyên bản sắc — Tinh giản thị giác — Mềm mại trong chi tiết — Chuyên nghiệp trong vận hành — Thuần Việt trong trải nghiệm.*

---

## 1. Phạm vi & Hiện trạng xác minh thực tế (Phase 0 Baseline)

Kiểm tra thực tế trên mã nguồn `HEAD` (`5162738`) và máy chủ thử nghiệm SQLite cục bộ (`127.0.0.1:8019`, dữ liệu mẫu `seed_kmg` + `seed_demo`) ghi nhận:

### 1.1. Tài sản & Cấu trúc Frontend hiện tại
- **Thư viện:** Self-hosted Bootstrap 5.3 + Bootstrap Icons + phông chữ `Be Vietnam Pro` (`static/css/fonts.css`, 5 mức `400..800`, không phụ thuộc CDN).
- **Stylesheet:** `static/css/app.css` (911 dòng), `static/css/site.css`, `static/css/sidebar.css` (63 dòng).
- **Template:** **103** tệp `.html` trải khắp 17 thư mục app + `base/` + `partials/`.
- **Mức độ phình & lặp giao diện:**
  - `department_detail.html` (673 dòng), `governance_center.html` (564 dòng), `public_portal/home.html` (448 dòng), `workspace_home.html` (444 dòng), `base.html` (423 dòng), `floating_chat.html` (403 dòng), `events/detail.html` (348 dòng).
  - **133** thuộc tính `style="..."` inline trong template; **68** mã màu hex cứng trong HTML; **368** lần dùng `.card` và **185** lần dùng `.kmg-card`.

### 1.2. Các lỗi & bất cập đã xác minh bằng dữ liệu thực tế

| Mã | Mức độ | Màn hình / Tệp bị ảnh hưởng | Nguyên nhân gốc rễ (Root Cause) | Phương án xử lý | Rủi ro | Tiêu chí nghiệm thu (AC) |
|---|---|---|---|---|---|---|
| **UI-001** | **P0** | `/portal/` (`public_portal/home.html`) & toàn bộ 185 thẻ `.kmg-card`, 26 `.kmg-kicker`, 20 `.kmg-badge-gold`, 14 `.kmg-dept-icon` tại `/workspace/*` | Tệp `static/css/kmg_editorial.css` đã bị xoá khỏi working tree (`GET /static/css/kmg_editorial.css` trả **HTTP 404**), đồng thời `templates/base.html` không nhúng tệp này nên toàn bộ khối `.kmg-card` trong workspace mất nền, viền và bo góc | Khôi phục `static/css/kmg_editorial.css` đồng bộ token với `tokens.css` & `app.css` ở cả Sáng/Tối; nhúng trong `base.html` | Thấp (CSS bổ sung) | `GET /static/css/kmg_editorial.css` -> **200**, không còn 404 console/network |
| **UI-002** | **P0** | `templates/base.html:213` (Sidebar mục `Không gian CLB`) | Gắn cứng class `text-primary` lên `<i class="bi bi-grid-1x2-fill text-primary">` đè mất màu trắng của `.nav-link.active`, khiến icon chìm xanh-trên-xanh khi đang ở `/workspace/` | Bỏ `text-primary` cứng (hoặc cho phép kế thừa `currentColor` khi `.active`) | Thấp | Icon mục đang chọn luôn tương phản >= 4.5:1 trên nền `--brand` ở cả Sáng và Tối |
| **UI-003** | **P0** | `giam-sat/` (57 badge), `quan-tri/` (24), `huan-luyen/` (9), `dao-tao/` (8), `tin-nhan/` (7 + `btn-outline-dark`), `danh-gia/` (4 `text-dark`), `tai-chinh/` (`alert-light`), `events/detail.html` | Dùng class cứng theo theme sáng (`text-bg-light`, `alert-light`, `bg-light`, `text-dark`, `btn-outline-dark`) khiến trong `[data-bs-theme="dark"]` chữ đen trên nền tối hoặc khung trắng chói mắt | Thay dần bằng biến ngữ nghĩa (`bg-body-secondary text-body border`, `btn-outline-secondary`) + thêm bridge CSS trong `app.css` cho `[data-bs-theme="dark"]` | Thấp | Không còn chữ không đọc được hay hộp trắng gắt ở Dark Mode |
| **UI-004** | **P1** | `templates/registrations/my_tickets.html:38` | `.ticket-notch-top, .ticket-notch-bottom` dùng `background: var(--app-bg)` nhưng biến `--app-bg` chưa từng được định nghĩa | Đổi sang `var(--bs-body-bg)` và định nghĩa alias `--app-bg: var(--bs-body-bg)` trong `tokens.css` | Rất thấp | Vết khuyết cuống vé khớp nền giấy Sáng / nền đêm Tối |
| **UI-005** | **P1** | `templates/500.html`, `403.html`, `404.html` | `500.html` dùng font `system-ui` + nút `#0d6efd` xanh Bootstrap mặc định không có dark mode; `403`/`404` đơn điệu và chỉ trỏ về `events:list` | Đồng bộ bảng màu KMG `#34477d` + dark mode cho `500.html`; giữ HTML thuần không extends `base.html`; bổ sung lựa chọn về Trang chủ / Tổng quan cho `403`/`404` | Rất thấp | `500.html` render độc lập 0 dependency, đúng màu KMG ở cả Light & Dark |
| **UI-006** | **P1** | Toàn bộ nút/nav dùng `bi-*` (cạnh sắc, nét không đều: `bi-grid-1x2-fill` đặc bên cạnh `bi-calendar2-heart` rỗng, `bi-robot` cứng nhắc cho AI) | Dùng hỗn hợp icon đặc/rỗng và các icon có hình khối vuông góc thiếu mềm mại | Xây dựng **KMG Soft Icon System 1.0** (`24x24`, `stroke-width: 1.6`, `linecap="round"`, `linejoin="round"`, `currentColor`) + `/dev/design-system/` để Chủ dự án duyệt trước khi thay toàn cục | Trung bình (thay thế diện rộng cần duyệt) | Đạt sự đồng nhất nét vẽ ở 100% nhóm icon cốt lõi sau khi qua Cổng phê duyệt |
| **UI-007** | **P1** | Điều hướng kép & Trùng bề mặt (`/`, `/portal/`, `/tong-quan/`, `/workspace/`, `/workspace/quan-tri/`...) | Tồn tại song song 2 trang chào (`/`, `/portal/`) và 2 dashboard (`/tong-quan/`, `/workspace/`); thanh sidebar lặp mục `Các Ban`, card lồng card | Tinh giản card lồng nhau, gom nhóm điều hướng rõ ràng, phân tách công cụ hiển thị theo vai trò (sau Cổng phê duyệt IA) | Cao | Không còn chức năng bị ẩn nhầm hoặc mất quyền D04; giảm số cấp card lồng <= 2 |
| **UI-008** | **P1** | Tiếng Anh lẫn trong UI (`KMG Internal Workspace`, `LLMOps & AI Training Studio`, `Eval Suite`, `Guest`, `Stage Spec`, `FOH`, `Cross-Department Read-Only`, `modun AI`) | Thuật ngữ kỹ thuật/nội bộ từ các Phase phát triển được render thẳng lên template người dùng cuối | Chuẩn hoá bộ từ điển thuật ngữ Việt-Anh (`docs/design/UI_TERMINOLOGY_VI.md`), sửa lỗi chính tả (`modun` -> `mô-đun`) và bản địa hoá nhãn UI | Thấp | Chỉ giữ thuật ngữ được phép (`AI`, `QR`, `OTP`, `PDF`, `Excel`, `email`, `Guitar`, `Acoustic`, `Jam Session`, `Workshop`) |
| **UI-009** | **P2** | `department_detail.html` (673 dòng), `governance_center.html` (564 dòng), `floating_chat.html` (403 dòng) | Template quá dài, CSS/JS inline trộn với logic trình bày nhiều panel cùng lúc trên màn hình | Tách component dùng chung (`templates/components/`) + tối ưu tab/progressive disclosure, đưa CSS inline về stylesheet | Trung bình | HTML gọn hơn, dễ bảo trì, không gãy test hay form CSRF |
| **UI-010** | **P2** | Live Browser Visual Inspection (`360px`–`1920px`, Light/Dark) | Máy dev chưa bật Chrome Remote Debugging (`DevToolsActivePort` không tồn tại) và chưa cài Playwright | Bổ sung kịch bản kiểm chứng HTTP/DOM tự động + ghi nhận `BLOCKED` trung thực cho ảnh chụp trình duyệt tới khi Chrome/Playwright khả dụng | Môi trường | Kiểm chứng được 100% route 200 & token parity trên DOM; ảnh chụp hoàn tất khi bật Chrome remote debugging |

---

## 2. Lộ trình triển khai theo 6 Sprint & Cổng phê duyệt thiết kế

### Sprint 1 — Bảo toàn thẩm mỹ, vá CSS thiếu, đồng bộ Dark Mode & Prototype Design System *(Thực thi ngay — An toàn)*
- Tạo tầng **Design Tokens** chuẩn (`static/css/tokens.css`) kế thừa trọn vẹn bảng màu Xanh mực `#34477d`, Vàng cát `#a87d26`, Giấy ấm `#f7f6f3` và bộ token Dark Mode `#14161d` / `#5068c0` / `#d9a441`.
- Khôi phục `static/css/kmg_editorial.css` nối liền mạch tới biến của `tokens.css` để không lệch giữa 2 tông giấy ấm (`#f7f6f3` vs `#f7f6f2`) và đồng nhất `.kmg-card` ở cả Light & Dark.
- Liên kết đầy đủ `tokens.css`, `kmg_editorial.css`, `sidebar.css`, `components/icons.css` trong `templates/base.html` và `public_portal/home.html`.
- Vá lỗi tương phản tức thì: icon active sidebar (`UI-002`), bridge Dark Mode cho `.text-bg-light` / `.alert-light` / `.bg-light` / `.btn-outline-dark` (`UI-003`), `--app-bg` tại `my_tickets.html` (`UI-004`), chuẩn hoá `403.html` / `404.html` / `500.html` (`UI-005`).
- Xây dựng **KMG Soft Icons 1.0** (`static/icons/kmg/` + `templates/components/icon.html` + template tag `{% kmg_icon %}`) và trang đối chiếu nội bộ `/dev/design-system/` (chỉ mở khi `DEBUG=True` hoặc `is_server_admin`).

### CỔNG PHÊ DUYỆT THIẾT KẾ (Design Approval Gate — Bắt buộc trước Sprint 2–4)
Trước khi thay thế hàng loạt icon `bi-*` trên 103 template hoặc hợp nhất/đơn giản hoá cấu trúc điều hướng & trang tổng quan:
1. Chủ dự án xem xét trực tiếp trang `/dev/design-system/` ở cả **Light Mode** và **Dark Mode**: đối chiếu từng cặp icon (Bootstrap Icons cũ vs KMG Soft Icons 1.0 mới), bảng token, mẫu card tinh giản.
2. Chủ dự án quyết định phương án điều hướng kép (`/tong-quan/` vs `/workspace/`, `/` vs `/portal/`) và mức độ ẩn/gom chi tiết kỹ thuật (nhãn nội bộ như `D04 v1.1`, `Phase 5 · WF22`, `BE-07`, `PA-06`, `CM-03`, `INV-04`) ra khỏi giao diện người dùng cuối.

### Sprint 2 — Áp dụng KMG Soft Icons 1.0 & Component thư viện dùng chung *(Sau Gate)*
- Triển khai `{% kmg_icon %}` đồng bộ cho Navbar, Sidebar, Breadcrumb, Buttons, KPI Tiles, Empty States, AI Chat/Studio, Events & Music Hub.
- Chuẩn hoá component tái sử dụng trong `templates/components/`: `page_header`, `stat_card`, `surface_card`, `status_badge`, `empty_state`, `filter_bar`, `modal_confirm`.

### Sprint 3 — Tinh giản thị giác (Visual Decluttering) & Cấu trúc trang sạch *(Sau Gate)*
- Rút số lớp bọc thẻ (nested `.kmg-card > .border > .kmg-card`) xuống tối đa 1–2 cấp, thay viền thừa bằng khoảng thở hợp lý (`whitespace` theo lưới 8px).
- Phân rã `department_detail.html` (673 dòng) và `governance_center.html` (564 dòng) thành partial rõ ràng có tab/accordion theo ngữ cảnh vai trò.
- Chuẩn hoá `floating_chat.html` & `events/list.html` giảm inline CSS (`133` -> `< 15` chỉ dành cho biến động như chiều rộng phần trăm tiến độ).

### Sprint 4 — Thuần Việt hoá UX Microcopy toàn hệ thống *(Sau Gate)*
- Rà soát 100% template, `forms.py`, `models.py` choices/verbose_name (chỉ nhãn hiển thị, không đổi key/DB) và file `static/js/*.js` theo từ điển `docs/design/UI_TERMINOLOGY_VI.md`.
- Thay nhãn kỹ thuật thô (`Phase 5`, `D04 v1.1`, `WF22`, `INV-04`, `Guest`, `Stage Spec`, `Eval Suite`) bằng ngôn ngữ KMG tự nhiên, thân thiện cho sinh viên CLB Guitar.

### Sprint 5 — Khả năng tiếp cận (WCAG 2.2 AA), Mobile-first & Hiệu năng Frontend
- Audit bàn phím (`Tab`, `Shift+Tab`, `Esc`, `focus-visible`), `aria-live`, vùng chạm `>= 44x44px` trên di động, kiểm tra `360px` không tràn ngang.
- Giảm CSS trùng lặp giữa `app.css` / `site.css` / template `<style>`, đảm bảo không có request thừa hoặc render-blocking mới.

### Sprint 6 — Kiểm định hồi quy toàn diện & Bàn giao
- Chạy đầy đủ bộ test Django (`settings_test`), `evaluate_ai`, `check --deploy`, audit HTTP/DOM tất cả route theo 7 persona D04, chụp ảnh Light/Dark trên các breakpoint `360px`, `768px`, `1024px`, `1440px`, `1920px`.
- Hoàn thiện báo cáo `docs/audit/12_KMG_FRONTEND_REFINEMENT_REPORT.md` và cập nhật `docs/AI_DEVELOPMENT_STATE.md`.
