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

## 3. Điều kiện trước khi chốt Pilot thực tế trên Server

- Kiểm thử lại trên **MySQL 8.4** và **Redis** thật (`DATABASE_URL`, `CACHE_URL`) vì bộ test hiện tại chạy trên `SQLite` + `LocMemCache`.
- Khởi chạy thử bằng `gunicorn` + `Nginx` kiểm tra `X-Forwarded-For` (`TRUST_X_FORWARDED_FOR`), SSL (`USE_HTTPS=True`) và `/health/`.
- Thực hiện diễn tập UAT tối thiểu 1 vòng với 5–10 tài khoản đại diện đầy đủ các vai trò trên trước giờ mở bán vé sự kiện thật.
