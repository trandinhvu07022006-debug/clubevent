# Ma trận Kiểm thử Chấp nhận (UAT) cho Pilot 100 Sinh viên

Tài liệu rà soát kịch bản kiểm thử vận hành và phân quyền cho sự kiện thử nghiệm (~100 sinh viên) trên nền tảng **Clubevent & KMG AI**.

## 1. Phân nhóm vai trò cần kiểm thử

| Vai trò trên hệ thống / nghiệp vụ | Ánh xạ kỹ thuật hiện tại | Quyền hạn cốt lõi cần UAT |
|---|---|---|
| **1. Khách (`GUEST`)** | `Role.GUEST` / chưa đăng nhập | Xem sự kiện `PUBLIC`, đăng ký tài khoản/OTP, đặt vé (tối đa `MAX_TICKETS_PER_USER_PER_EVENT=4`), hỏi chatbot luồng công khai, **chặn** xem sự kiện `INTERNAL` và tác vụ BTC. |
| **2. Thành viên (`MEMBER`)** | `Role.MEMBER` + `ClubMembershipStatus.ACTIVE` | Xem sự kiện `PUBLIC` & `INTERNAL` (khi đủ điều kiện thành viên), xem/hủy/chuyển nhượng vé hợp lệ, gửi phản hồi sau sự kiện, truy cập không gian thành viên. |
| **3. Thành viên BTC (`STAFF`)** | `Role.STAFF` | Quét QR / nhập mã 12 ký tự check-in sự kiện được phân công, xem tiến độ check-in, nhận & cập nhật công việc được giao, **chặn** tự duyệt chi ngân sách hoặc thao tác `ADMIN`. |
| **4. Trưởng BTC (`LEAD`)** | `Role.LEAD` | Tạo/sửa/đổi trạng thái sự kiện & loại vé, xác nhận thanh toán vé, dùng AI gợi ý công việc/nội dung truyền thông/tóm tắt phản hồi (có rate-limit `kmg_ai_lead`), quản lý ngân sách sự kiện. |
| **5. Chủ nhiệm CLB** | `Role.LEAD` / `Appointment` Chủ nhiệm (`organization`) | Phê duyệt đề xuất hoạt động/đào tạo, cấp/thu hồi ủy quyền (`PermissionGrant`), duyệt chi bước 2 (Maker-Checker), kiểm tra báo cáo tổng hợp CLB. |
| **6. Cố vấn** | Vai trò Cố vấn / `Role.STAFF`/`LEAD` phạm vi giám sát (`organization`) | Xem báo cáo tài chính/hoạt động, rà soát quy trình & nội quy, **không** vượt quyền xóa dữ liệu sổ cái bất biến (`Ledger` / `AuditLog`). |
| **7. Admin Server (`ADMIN`)** | `Role.ADMIN` / `is_superuser` | Truy cập Django Admin, Studio AI (`ClubKnowledge`, `AIPromptProfile`), xuất dataset fine-tune đã che PII, giám sát health check & log hệ thống. |

## 2. Ma trận Kịch bản UAT trọng tâm (Pilot 100 sinh viên)

| Mã | Nhóm nghiệp vụ | Vai trò tham gia | Điều kiện kiểm thử & Kỳ vọng đạt |
|---|---|---|---|
| **UAT-01** | Đăng ký & giới hạn vé đồng thời | Khách, Thành viên | 100 lượt truy cập đặt vé cùng lúc không làm âm số chỗ (`quota` & `remaining >= 0`), không vượt giới hạn 4 vé/người/sự kiện (`select_for_update()`). |
| **UAT-02** | Thanh toán VietQR & Webhook SePay | Khách, BTC, Hệ thống | Chuyển khoản đúng `booking_ref` + `event_id` khớp `BANK_ACCOUNT` và số tiền >= tổng đơn xác nhận ngay; sai `BANK_ACCOUNT`, sai số tiền hoặc webhook rỗng bị bỏ qua an toàn. |
| **UAT-03** | Chuyển nhượng vé & Hủy vé hoàn suất | Thành viên, BTC | Không chuyển vé sau ngưỡng `TRANSFER_BEFORE_HOURS=3`; hủy vé trước 24h nhường chỗ cho danh sách chờ; vé đã check-in không thể hủy. |
| **UAT-04** | Check-in QR dưới tải sự kiện | TV BTC, Trưởng BTC | Quét đồng thời nhiều luồng cho cùng 1 mã vé chỉ có đúng 1 lần check-in thành công, các lần trùng báo lỗi rõ ràng, trạng thái giữ `CHECKED_IN`. |
| **UAT-05** | Cô lập quyền sự kiện `INTERNAL` | Khách, Thành viên | Khách không thấy sự kiện `INTERNAL` ở trang công khai, không đăng ký được qua URL ẩn (`EventVisibility.PUBLIC`), AI & log chat không lưu nội dung `INTERNAL`. |
| **UAT-06** | Bảo vệ luồng KMG AI & Fallback | Toàn bộ vai trò | Hỏi thông tin cá nhân không gửi PII ra LLM ngoài; hết lượt / lỗi API / circuit mở mạch vẫn trả về câu trả lời quy tắc hoặc fallback an toàn không lỗi 500. |
| **UAT-07** | Tài chính Maker-Checker & Kho chứng từ | Trưởng BTC, Chủ nhiệm, Cố vấn | Chứng từ lưu trong `PRIVATE_VAULT_ROOT`, URL `/private-vault/` chỉ người có quyền tải được; khoản chi không thể tự duyệt chính mình. |

## 3. Phân tách Trạng thái Kiểm chứng RC1 (AUD-010 / AUD-011)

| Hạng mục | Hình thức kiểm chứng | Trạng thái | Ghi chú & Bằng chứng |
|---|---|---|---|
| **Automated E2E (Django Client & Integration)** | Tự động trong bộ test (`core/test_uat_e2e.py`, `registrations/test_rc1_concurrency.py`, `finance/test_rc1_regressions.py`, `aiassist/test_rc1_security.py`) | **VERIFIED** | Xác minh đầy đủ 7 vai trò qua HTTP view/API thật, template chứa `viewport` + Bootstrap shell, zero HTTP 500 trên các trang trọng tâm. |
| **Headless Browser / Playwright Viewport (`360px–1920px`)** | Render trình duyệt thật & chụp màn hình responsive trên server test cô lập | **BLOCKED** | Môi trường dev/CI hiện chưa cài đặt `playwright` / binary Chromium (`pip list` không có `playwright`, `where.exe playwright` trả về rỗng); không giả lập kết quả. |
| **Developer Verification** | Chạy `check`, `check --deploy`, `makemigrations --check`, `evaluate_ai --with-migrate`, full test suite | **VERIFIED** | Xem chi tiết nhật ký trong `docs/AI_DEVELOPMENT_STATE.md` và `docs/audit/08_INDEPENDENT_REVIEW_REMEDIATION.md`. |
| **Human UAT (Pilot Operators — 7 vai trò)** | Diễn tập thực tế bởi BCN / BTC / Thành viên / Khách trước ngày mở sự kiện thật | **REVIEW_REQUIRED** | Đợi nghiệm thu thực tế trên staging cô lập sử dụng tài khoản UAT giả lập riêng bên dưới. |

## 4. Bộ Tài khoản UAT Giả lập Độc lập (Chỉ dùng trong môi trường Staging / Test cô lập)

> **Cảnh báo:** Tuyệt đối không dùng thông tin/mật khẩu thật hoặc dữ liệu production trong UAT. Tạo bằng script/fixture cô lập rồi thu hồi sau diễn tập.

| STT | Tài khoản giả lập (`username`) | Email giả lập | Vai trò & Scope kiểm thử | Kịch bản kiểm thử phụ trách |
|---|---|---|---|---|
| 1 | `uat_guest` | `uat_guest@example.com` | `GUEST` (đã xác minh OTP mẫu) | `UAT-01`, `UAT-05`, `UAT-06` |
| 2 | `uat_member` | `uat_member@example.com` | `MEMBER` (`ACTIVE` + `Ban Truyền thông`) | `UAT-03`, `UAT-05` |
| 3 | `uat_staff` | `uat_staff@example.com` | `STAFF` (BTC quét QR check-in) | `UAT-04` |
| 4 | `uat_lead` | `uat_lead@example.com` | `LEAD` (Trưởng BTC sự kiện) | `UAT-01`, `UAT-02`, `UAT-04` |
| 5 | `uat_chair` | `uat_chair@example.com` | `Appointment(CHAIRMAN)` | `UAT-07` & `AI Studio` |
| 6 | `uat_advisor` | `uat_advisor@example.com` | `Appointment(ADVISOR)` Read-Only `INV-04` | `UAT-07` (xác minh chặn mutation) |
| 7 | `uat_admin` | `uat_admin@example.com` | `ADMIN` (`is_superuser` kỹ thuật) | Healthcheck, Admin & Export tách biệt |

## 5. Điều kiện trước khi chốt Pilot thực tế trên Server

- Kiểm thử lại trên **MySQL 8.4** và **Redis** thật (`DATABASE_URL`, `CACHE_URL`) kết hợp CI `docker compose` (`AUD-001`).
- Khởi chạy thử bằng `gunicorn` + `Nginx` kiểm tra `X-Forwarded-For` (`TRUST_X_FORWARDED_FOR`), SSL (`USE_HTTPS=True`) và `/health/`.
- Chạy Playwright/Chromium kiểm tra responsive `360px`–`1920px` và hoàn tất diễn tập **Human UAT** theo bảng 7 vai trò trước khi mở bán vé sự kiện thật.
