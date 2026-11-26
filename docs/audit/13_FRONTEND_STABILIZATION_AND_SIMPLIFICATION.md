# Báo cáo 13 — Frontend Stabilization & Simplification (KMG UI/UX Refinement 3.0)

**Ngày thực hiện:** 2026-11-26  
**Nhánh làm việc:** `feature/mysql-production-readiness` (không merge `main`)  
**Baseline đối chiếu:** `5162738` / `eba9848`

---

## A. Các lỗi đã phát hiện & Bản vá an toàn đã áp dụng

| Hạng mục | Thực trạng trước vá | Bản vá đã áp dụng | File |
|---|---|---|---|
| **A1. `test_ticket_codes_are_unique_and_unguessable`** | Dùng `assertFalse(any(c.isdigit() for c in codes))` — gây lỗi ngẫu nhiên khi UUID hex 12 ký tự toàn chữ số (`0-9`). | Kiểm tra chuẩn regex `^[0-9A-F]{12}$`, tính duy nhất, khác ID tăng dần, và bổ sung test mock `uuid.uuid4` cho trường hợp prefix toàn chữ số. | `registrations/tests.py` |
| **A2. `static/css/kmg_editorial.css`** | Đã được khôi phục từ commit `6f2b5c1` (`3,338` bytes), đồng bộ token sáng/tối. | Xác minh tồn tại và được nạp trong `templates/base.html`. | `static/css/kmg_editorial.css` |
| **A3. Kiểm tra static assets trong `templates/`** | Quét toàn bộ **47** thẻ `{% static ... %}` trong `templates/`. | **0 file bị thiếu** (`missing: 0`). | `templates/**/*.html` |
| **A4. Docker smoke test trong CI** | Chỉ kiểm tra `/health/`, `/taikhoan/dangnhap/` và 1 file CSS đầu tiên. | Mở rộng kiểm tra `/portal/`, `/`, `/taikhoan/dangnhap/`, `/troly/`, toàn bộ CSS/JS static assets trên trang (HTTP 200, non-empty) và kiểm tra redirect/auth trên `/tong-quan/`, `/workspace/`, `/congviec/viec-cua-toi/`, `/ve/cua-toi/`. | `.github/workflows/ci.yml` |
| **A5. Service Worker precache (`notifications/views.py`)** | `cache.addAll(PRECACHE_URLS).catch(() => null)` nuốt im lặng mọi lỗi precache. | Dùng `Promise.allSettled` kiểm tra từng URL (`response.ok`), ghi `console.warn` cho URL lỗi và reject nếu toàn bộ precache thất bại; Việt hóa thông báo đẩy. | `notifications/views.py` |
| **E1. Active menu trùng lặp (AI Assistant & AI Studio)** | `templates/base.html` dùng `rm.namespace == 'aiassist'` cho mục "Hỗ trợ", làm cả **Hỗ trợ** và **Huấn luyện AI** cùng sáng khi mở `/troly/huan-luyen/`. | Sửa điều kiện thành `rm.namespace == 'aiassist' and rm.url_name == 'chat'`. | `templates/base.html` |
| **E2. Thuật ngữ kỹ thuật & Mã nội bộ trên UI** | Xuất hiện `KMG Platform`, `KMG Internal Workspace`, `INV-05`, `WF22`, `BE-06`, `SEC-02`, `READ_ONLY`, `MANAGE`, `MEMBER` trên giao diện người dùng. | Việt hóa tự nhiên, bỏ mã nội bộ trên giao diện mà vẫn giữ nguyên thông điệp bảo mật/nghiệp vụ. | `base.html`, `workspace_home.html`, `evaluations/*.html`, `finance/hub.html`, `social/*.html`, `notifications/views.py` |
| **F1. KMG Soft Icons 1.0** | Sidebar và `workspace_home.html` dùng Bootstrap Icons rời rạc. | Triển khai `{% kmg_icon %}` & `.kmg-icon-badge` (stroke `currentColor`, tương thích Sáng/Tối) cho sidebar `base.html` và các lối tắt `workspace_home.html`. | `templates/base.html`, `templates/organization/workspace_home.html` |

---

## B. Kết quả Kiểm thử Route theo Vai trò (SQLite cách ly `config.settings_test`)

Kiểm thử **25 route chính** (`pages`, `events`, `public_portal`, `aiassist`, `registrations`, `recruitment`, `organization`, `operations`, `programs`, `social`, `finance`, `evaluations`):
- **Guest:** `200: 7`, `302: 18` — **0 lỗi 500/404**.
- **Member (chưa kích hoạt quyền workspace):** `200: 8`, `302: 1`, `403: 16` — **0 lỗi 500/404**.
- **Admin:** `200: 24`, `302: 1` — **0 lỗi 500/404**.

---

## C–D. Bản thử nghiệm Cải tiến Bố cục `workspace_home.html` (Chờ Chủ dự án Nghiệm thu)

1. **Đưa nội dung ưu tiên lên trước:** Cảnh báo chuyên cần (`open_discipline_cases`), KPI công việc cá nhân, **Việc sắp đến hạn + RSVP**, **Thông báo chính thức**, và **Lịch Đào tạo & Tập Band** được đưa lên ngay đầu trang.
2. **Tinh giản 9 lối tắt dạng card (Progressive Disclosure):** Giữ 4 lối tắt dùng hằng ngày (`Đào tạo & Tập Band`, `Playlist & Tặng nhạc`, `Bảng tin Nội bộ`, `Nhắn tin Bảo mật`) ở hàng chính; gom 5 chức năng ít dùng hơn (`Đề xuất`, `Kho Tài liệu`, `Quỹ & Tài chính`, `Đánh giá`, `Phân tích`) và khối `Chức vụ & quyền hạn` vào `<details>` có thể mở rộng.
3. **Bảo toàn 100% URL & chức năng:** Không xóa bất kỳ liên kết hay biểu mẫu nào; chưa thay bộ icon toàn hệ thống (chờ nghiệm thu).

---

## G. Blocker môi trường & Hạng mục chờ xác nhận

- **Playwright / Browser Visual Testing (`320px–1920px`, Light/Dark, chụp ảnh trước/sau):** Máy dev Windows chưa cài `playwright` (`find_spec('playwright') == None`) và chưa có Docker Desktop / Redis Server cục bộ. Cần chạy trên runner Linux CI hoặc cài đặt Playwright để chụp ảnh đối chiếu và đo Core Web Vitals trước khi merge `main`.
- **MySQL + Redis + Docker CI:** Đã cập nhật `.github/workflows/ci.yml`, chờ push lên nhánh feature để runner GitHub Actions thực thi.
