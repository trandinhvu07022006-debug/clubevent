# BÁO CÁO TỔNG THỂ DỰ ÁN NỀN TẢNG QUẢN TRỊ CLB ÂM NHẠC KMG
**KMG Club Management Platform — Technical Status, Progress & Strategic Plan**
*Baseline Phase 5: 14/11/2026 | Cập nhật chuẩn bị pilot: 18/11/2026*
*Kho mã nguồn Git:* [`dawn2819/kmg-bcbc`](https://github.com/dawn2819/kmg-bcbc)

---

## 1. TỔNG QUAN DỰ ÁN & BỐI CẢNH NGHIỆP VỤ

### Cập nhật Phase 6 ngày 18/11/2026

Đang chuẩn bị pilot, chưa nghiệm thu vận hành chính thức. Chủ dự án chọn giữ cơ cấu Chuyên môn / Truyền thông–Sự kiện / Kỹ thuật.

- Có Compose, health DB/cache, heartbeat scheduler; CI MySQL/Redis, container và backup/restore sang project mới. Hai lỗi CI về khóa ngắn và health URL đã sửa.
- Đã khóa đường Django Admin/ORM hàng loạt vượt quy trình sổ quỹ; thêm constraint người duyệt độc lập, bảo vệ khoản chi kết chuyển và các test hồi quy. Không tuyên bố chống mọi sửa đổi bằng SQL trực tiếp.
- OTP phản ánh lỗi gửi; reminder lưu email chờ gửi lại cùng thông báo app trong transaction. SMTP vẫn có cửa sổ gửi trùng sau tiếp nhận/trước commit.
- Rate limit Redis dùng Lua nguyên tử; cache lỗi thì chặn yêu cầu được bảo vệ. LocMem chỉ dành dev/test.
- Có bootstrap danh mục không có người dùng mẫu; chặn seed theo cấu hình pilot và không đặt lại mật khẩu có sẵn.
- Có [kế hoạch pilot](../PILOT_PLAN.md), [hướng dẫn người dùng](../USER_GUIDE.md), [sổ tay quản trị](../ADMIN_HANDBOOK.md) và [runbook](../deployment/DEPLOYMENT_AND_BACKUP.md).

**Xác minh:** MySQL 8.4.9 riêng: 385 test phát hiện, 383 đạt, 2 bỏ qua (Redis thực và symlink Windows); check 0 issues, không lệch migration, migration mới áp dụng thành công. Trong bộ trên có 17 test công cụ triển khai: 16 đạt, 1 bỏ qua. Bootstrap và seed KMG chạy hai lần thành công trên SQLite riêng. Chưa chạy Docker/GitHub Actions/HTTPS/SMTP thật, load test hoặc UAT; Docker/Redis server chưa có trên máy này. Không dùng kết quả unit test để đánh dấu các mục đó đã đạt.

Các phần còn lại mô tả baseline Phase 5 và kế hoạch ban đầu. Khi triển khai dùng tài liệu pilot mới; không chạy seed trên dữ liệu thật.

**Bàn giao local đã xác minh:** Theo lựa chọn của chủ dự án, chưa triển khai máy chủ. `chay-pilot-local.bat` / `python -m deployment.local_pilot --demo` chạy trên loopback cổng 8001 với DB/khóa/tệp riêng trong `.local-pilot/`, không đọc `.env`. Đã migrate, bootstrap, seed, collectstatic và check; HTTP smoke thực đạt cho trang chủ, health, CSS, đăng nhập 6 persona, Guest bị chặn workspace, media công khai tải được và vault không có URL trực tiếp. Xem [LOCAL_HANDOVER.md](../LOCAL_HANDOVER.md). Email/SMS console và AI mock; không tự chạy scheduler nền.

### 1.1. Mục tiêu & Tầm nhìn
**KMG Club Management Platform** là nền tảng quản trị và vận hành toàn diện dành cho Câu lạc bộ Âm nhạc Sinh viên KMG (K-Music Guild / KMG Club). Dự án được phát triển theo kiến trúc **Django 5.2 Enterprise Modular Monolith** kết hợp hệ thống **REST API v1 (`/api/v1/`)**, chạy trên hệ quản trị cơ sở dữ liệu **MySQL 8.4 Server (InnoDB, utf8mb4_0900_ai_ci)**.

Nền tảng giải quyết triệt để các bài toán thực tiễn của một tổ chức sinh viên quy mô lớn, bao gồm:
1. **Phân rã tổ chức & ma trận phân quyền đa chiều (RBAC + DBAC + ABAC + Delegation + Resource ACL):** Hỗ trợ mô hình 3 Ban chuyên trách (Ban Truyền thông sự kiện `MEDIA_EVENT`, Ban Chuyên môn âm nhạc `SPECIALTY`, Ban Kỹ thuật `TECHNICAL`), thành viên sinh hoạt đa Ban (M-N), cơ cấu cán bộ 4 tầng (Chủ nhiệm, Phó chủ nhiệm phụ trách 4 mảng, Trưởng ban, Phó ban theo 4 gói ủy quyền).
2. **Quy trình onboarding & phân cấp tài khoản chuẩn mực:** Khách đăng ký qua Email/SĐT -> Xác thực OTP 6 chữ số -> Mặc định ở trạng thái Khách (`GUEST`) -> Ban Chủ nhiệm sơ tuyển/phân Ban mới mở tính năng Thành viên -> Chỉ Admin Server ("tôi") mới có quyền nâng cấp các chức vụ cốt cán.
3. **Quản lý vận hành 10 bước (10-Stage Task Workflow):** Phân công công việc đơn lẻ/nhóm, nghiệm thu bất biến (Maker-Checker `INV-03`), gia hạn có kiểm soát.
4. **Hệ thống Sự kiện Kép (Dual Events) & RSVP chuyên cần:** Bảo toàn 100% luồng bán vé/check-in công khai cho khán giả (`registrations.Ticket`), tích hợp thêm sự kiện nội bộ/tập luyện với điểm danh nội bộ (`EventAttendance`), chống phạt kép (`CF-02`).
5. **Kho Tài liệu Bảo mật Cấp cao (Confidential Document Vault):** Phân loại 5 cấp độ bảo mật, lưu trữ vật lý ngoài web root (`PrivateVaultStorage` theo `SEC-01`), kiểm tra magic bytes, chống thực thi mã độc, ghi sổ nhật ký truy cập bất biến (`DocumentAccessLog`), quy trình Break-Glass có kiểm toán.
6. **Mạng xã hội Nội bộ & Nhắn tin mã hóa tại máy chủ:** Luồng tin phân phạm vi Ban/CLB (`PA-05`), mã hóa phong bì AES-256-GCM và quyền hội thoại (`INV-05`), playlist và tặng nhạc (`BE-05`). Không phải E2EE trước người nắm máy chủ/khóa.
7. **Quản lý Quỹ & Tài chính Bất biến (Immutable Club Finance):** Sổ cái thu/chi/điều chỉnh hai bước Maker-Checker (`WF22`), giao dịch đã ghi sổ (`CONFIRMED`) là bất biến tuyệt đối (chặn `.save()` và `.delete()`), kết chuyển tương thích ngược với ngân sách sự kiện cũ (`CM-03`), xuất CSV an toàn chống Formula Injection (`SEC-02`).
8. **Đánh giá 7 Tiêu chí & Vinh danh Tách biệt (Chỉ thị 3.3 Nhà tài trợ):** Đánh giá định kỳ mang tính phát triển, tự động snapshot dữ liệu vận hành Phase 2/3, bảo mật riêng tư, tuyệt đối không xếp hạng điểm số công khai (no leaderboard), phản hồi hai chiều nhẹ nhàng (`BE-06`), vinh danh định tính riêng biệt.

---

## 2. HIỆN TRẠNG KIẾN TRÚC & CÔNG NGHỆ (TECHNICAL ARCHITECTURE)

| Phân hệ / Lớp | Công nghệ / Tiêu chuẩn áp dụng | Trạng thái |
| :--- | :--- | :--- |
| **Backend Core** | Python 3.12, Django 5.2.18 Modular Monolith | Đang chuẩn bị pilot |
| **Database Engine** | MySQL 8.4 Server (`InnoDB`, `utf8mb4_0900_ai_ci`, `SELECT FOR UPDATE` pessimistic lock) | Hoạt động 100% |
| **REST API** | Kiến trúc `/api/v1/` chuẩn JSON Envelope: `{ "ok": true, "data": ..., "meta": ... }` | 53 API endpoints |
| **Bảo mật Kho tệp** | `PrivateVaultStorage` vật lý ngoài `MEDIA_ROOT` (`SEC-01`), xác thực magic bytes, băm SHA-256 | Đã kiểm chứng |
| **Mã hóa Tin nhắn** | Phong bì mã hóa chuẩn `AES-256-GCM` (`social.crypto`, `CHAT_MASTER_KEK`), Zero-Admin-Read (`INV-05`) | Đã kiểm chứng |
| **Bảo mật Báo cáo** | Bộ lọc `safe_csv_row` & `safe_csv_cell` chống CSV Formula Injection (`SEC-02`), xuất UTF-8 BOM | Đã kiểm chứng |
| **Frontend & UI** | Django Templates, Bootstrap 5.3, Bootstrap Icons, KMG Editorial Stage CSS, Theme Toggle (Light/Dark) | Hoàn thiện |
| **PWA & Notifications** | Manifest/service worker, thông báo trong app/email; Web Push mới có nền móng | Pilot dùng app/email; chưa hoàn thiện Web Push |

---

## 3. TIẾN ĐỘ THỰC HIỆN CHI TIẾT THEO CÁC PHASE

```
[Phase 1: Core Foundation]  -->  [Phase 2: Core Management]  -->  [Phase 3: Dept Management]
         (Hoàn thành)                     (Hoàn thành)                    (Hoàn thành)
               │                                │                               │
               ▼                                ▼                               ▼
[Phase 4: Social & Messaging] --> [Phase 5: Finance & Eval]  -->  [Phase 6: Hardening & Release]
         (Hoàn thành)                     (Hoàn thành)                     (Đang mở)
```

### Phase 1: Nền tảng Tổ chức Đa Ban & Phân quyền Cốt lõi (Commit `93b45c2`, `8ae06c7`)
- **Động cơ phân quyền `PermissionEngine` (D04 v1.2):** Kiểm tra quyền tập trung tại Backend, tích hợp RBAC, DBAC, ABAC, Delegation và Resource-level ACL.
- **Quy trình Onboarding chuẩn:**
  1. Đăng ký tài khoản qua Email hoặc Số điện thoại.
  2. Xác minh mã OTP 6 chữ số đa kênh (Email / SMS mô phỏng an toàn).
  3. Sau khi xác minh, tài khoản mặc định giữ vai trò Khách (`GUEST`), chưa có quyền vào không gian nội bộ CLB.
  4. Chủ nhiệm CLB (`CHAIRMAN`) hoặc Phó chủ nhiệm (`VICE_CHAIRMAN`) duyệt đơn ứng tuyển hoặc nâng role trực tiếp và phân vào ít nhất 1 Ban đang hoạt động mới mở tính năng Thành viên.
  5. Độc quyền Admin Server ("tôi"): Chỉ Admin Server mới có quyền nâng cấp / bổ nhiệm / miễn nhiệm Chủ nhiệm, Phó chủ nhiệm, Trưởng ban và Cố vấn (`server.leadership.manage`, `club.officer.appoint_head`).
- **Chế độ truy cập Ban (Department Access Mode):** Tự động chuyển đổi giữa `MANAGE` (quản trị), `MEMBER` (sinh hoạt), `READ_ONLY` (xem chéo Ban / Cố vấn), `DENIED` (khóa).
- **Hồ sơ Kỹ năng Nghệ thuật (`UserSkill`):** Tách biệt năng khiếu âm nhạc khỏi quyền bảo mật (`INV-01: Skill != Permission`).
- **Trang chủ Công khai (`public_portal`):** Giao diện thương hiệu KMG Editorial Stage, giới thiệu 3 Ban, lịch biểu diễn công khai, form liên hệ chống spam IP.

### Phase 2: Vận hành Công việc, Sự kiện Kép & Kỷ luật (Commit `a91262c`)
- **Quy trình công việc 10 bước (`CM-01`):** `DRAFT` -> `ASSIGNED` -> `ACCEPTED` -> `IN_PROGRESS` -> `SUBMITTED` -> `UNDER_REVIEW` -> `REVISION_REQUESTED` -> `APPROVED` / `REJECTED` / `CANCELLED`.
- **Sổ cái nghiệm thu bất biến (`TaskReview`):** Append-only, chống tự nghiệm thu (`INV-03` / `PA-04`).
- **Sự kiện kép & RSVP nội bộ (`CM-04`, `BE-03`):** Quản lý sự kiện nội bộ/tổng duyệt, nhắc phản hồi RSVP tự động, miễn trừ điểm danh tự động cho thành viên bị tạm khóa (`CF-02`).
- **Hồ sơ chuyên cần & Trung tâm Khiếu nại độc lập (`WF23`, `WF24`):** Quy trình xử lý vi phạm khách quan, người ra quyết định ban đầu không được tự bác đơn khiếu nại.
- **Nền tảng PWA & Nhắc lịch thông minh (`DB-06`, `CM-04`):** Nhắc việc tự động trước 48h / 12h với cơ chế chống gửi trùng (`ScheduledReminder`).

### Phase 3: Quản lý Ban Chuyên biệt, Kho Tài liệu Mật & Đào tạo (Commit `5fb5b55`)
- **Cổng chuyên biệt theo từng Ban:** Tab phân hệ Tổng quan & Nhân sự, Công việc & Sự kiện, Chuyên môn Ban (Showcase), Đào tạo & Lịch tập, Đề xuất, Kho Tài liệu.
- **Kho Tài liệu Bảo mật (Confidential Vault):** Phân loại 5 cấp bậc, cơ chế Resource-level ACL gắn vòng đời (`PA-02`), cơ chế phá kính khẩn cấp Break-Glass có kiểm toán.
- **Quy trình Đề xuất Hoạt động 6 trạng thái (`WF17`, `WF18`):** Sáng kiến từ thành viên -> Trưởng ban thẩm định -> Chuyển cấp Ban Chủ nhiệm -> Phê duyệt triển khai sự kiện.
- **Đào tạo & Lịch tập Band (`BE-04`):** Quản lý khóa học chuyên môn (Vocal, Guitar, Audio Sound), lịch tập band (Rehearsal) định danh nhạc cụ và nhịp độ (tempo).

### Phase 4: Mạng xã hội Nội bộ, Nhắn tin Bảo mật & Âm nhạc (Commit `375be95`)
- **Mạng xã hội Nội bộ (`social.SocialPost`):** Phân chia phạm vi hiển thị `PERSONAL`, `DEPARTMENT`, `CLUB`. Tuân thủ `PA-05` (chia sẻ bài viết nội bộ Ban ra toàn CLB thì thành viên Ban khác không thấy nội dung gốc).
- **Hệ thống Nhắn tin Bảo mật (`social.ChatMessage`):** Mã hóa phong bì AES-256-GCM đối xứng, kiểm soát truy cập nghiêm ngặt. Tuân thủ `INV-05` (Zero-Admin-Read: Chủ nhiệm, Cố vấn và Admin Server đều bị cấm đọc tin nhắn riêng của người khác).
- **Danh sách phát nhạc & Tặng bài hát (`social.MusicPlaylist`):** Playlist riêng tư / công khai, tính năng gửi tặng bài hát chống nhầm tên tài khoản qua tìm kiếm fuzzy an toàn (`BE-05`).

### Phase 5: Quỹ CLB Bất biến, Đánh giá 7 Tiêu chí & Phân tích Báo cáo (Commit hiện tại)
- **Quỹ CLB & Sổ cái Bất biến (`finance` app):**
  - Maker-Checker hai bước độc lập: người lập phiếu (`created_by`) không được tự duyệt (`approved_by`), tuân thủ `INV-03`.
  - Bất biến sổ cái: khi giao dịch đạt trạng thái `CONFIRMED`, hệ thống chặn hoàn toàn mọi sửa đổi tài chính và lệnh xoá (`.delete()`), bắt buộc xử lý sai sót bằng bút toán điều chỉnh bù trừ `ADJUSTMENT` (`CREDIT` / `DEBIT`) liên kết phiếu gốc `adjusted_from`.
  - Cầu nối `CM-03`: Tự động khoá sửa/xoá trên khoản chi sự kiện cũ `organizing.Expense` sau khi đã kết chuyển và được duyệt vào sổ cái quỹ.
  - Quản lý đóng góp quỹ định kỳ của thành viên: thành viên đang bị tạm khoá (`SUSPENDED`) vẫn xem được lịch sử đóng góp cá nhân tại Cổng thông tin trạng thái `/taikhoan/trang-thai/` và API `/api/v1/finance/my-contributions/`.
  - Kiểm tra chứng từ hoá đơn upload (`SEC-01`): chỉ chấp nhận PDF, PNG, JPG, JPEG, WEBP <= 10MB, kiểm tra magic bytes, lưu trữ tại `PrivateVaultStorage`.
  - Cô lập đề xuất chi cấp Ban (`PA-06`): Cán bộ Ban chỉ được đề xuất chi tiêu trong phạm vi Ban của mình.
- **Đánh giá Thành viên 7 Tiêu chí & Vinh danh (`evaluations` app):**
  - Thực thi chuẩn mực Chỉ thị 3.3 của Nhà tài trợ: Đánh giá mang tính phát triển, định tính, riêng tư; tuyệt đối không tạo bảng xếp hạng điểm số (no numeric leaderboard) công khai.
  - Tự động snapshot số liệu vận hành Phase 2/3 (tỉ lệ hoàn thành nhiệm vụ, số buổi tập band tham gia, chuyên cần sự kiện, kỹ năng chuyên môn xác minh) làm minh chứng khách quan cho 7 tiêu chí.
  - Thành viên sinh hoạt đa Ban nhận các phiếu đánh giá độc lập theo từng Ban (`UNIQUE(cycle, member, department)`), Trưởng ban Ban này không can thiệp hay đọc phiếu Ban khác.
  - Phó ban có thể soạn nháp nhưng bị chặn chốt đánh giá (Trần quyền hạn cứng `DEPUTY_HEAD_FORBIDDEN_PERMISSIONS`).
  - Phản hồi hai chiều nhẹ nhàng (`BE-06` — `EvaluationResponse`): cho phép thành viên và cán bộ trao đổi trực tiếp trên phiếu đánh giá trước khi khoá kỳ, tách biệt khỏi thủ tục Kỷ luật/Khiếu nại.
  - Vinh danh thành viên (`MemberRecognition`): luồng công nhận độc lập, định tính, vinh danh cấp Ban và Toàn CLB, xuất hiện trang trọng trên Trang chủ công khai.
- **Trung tâm Phân tích Vận hành & Xuất Báo cáo CSV An toàn:**
  - Tổng hợp chỉ số công việc, sự kiện, đào tạo, đề xuất và tài chính toàn CLB hoặc theo từng Ban.
  - Cố vấn (`ADVISOR`) ở chế độ Hard Read-Only (`INV-04`): xem được báo cáo tổng hợp và xuất CSV, tự động che thông tin liên hệ cá nhân (`PA-07` PII Redaction), bị chặn toàn bộ quyền chỉnh sửa.
  - Xuất file CSV chuẩn UTF-8 BOM, làm sạch dữ liệu bằng `safe_csv_row` (`SEC-02`) chống tấn công thực thi công thức (CSV Formula Injection).

---

## 4. MA TRẬN PHÂN QUYỀN & CÁC BẤT BIẾN BẢO MẬT HỆ THỐNG

| Mã Bất biến / Quy tắc | Nội dung Bất biến | Cơ chế Bảo vệ ở Backend |
| :--- | :--- | :--- |
| **`INV-01`** | `Skill != Permission` | Năng khiếu nghệ thuật (`UserSkill`) chỉ dùng để gợi ý phân công; tuyệt đối không dùng để bypass quyền tài liệu mật hay quyền hệ thống. |
| **`INV-02`** | Không vượt quyền người cấp | Người ủy quyền không thể cấp quyền mà chính bản thân mình không sở hữu. |
| **`INV-03`** | Chống tự phê duyệt (Segregation of Duties) | Chặn tự duyệt nhiệm vụ, tự nghiệm thu, tự chốt đánh giá, tự duyệt vinh danh, tự duyệt phiếu quỹ (`actor != created_by`). |
| **`INV-04`** | Cố vấn Hard Read-Only | Cố vấn có thể xem dashboard giám sát và báo cáo tổng hợp; cấm 100% mọi quyền ghi (`is_mutation=True`), không giao việc cá nhân, tự động che PII (`PA-07`). |
| **`INV-05`** | Bí mật riêng tư tuyệt đối | Không một ai (kể cả Chủ nhiệm, Cố vấn hay Admin Server) được quyền đọc trộm tin nhắn riêng hoặc playlist riêng tư của người khác (`UNIVERSAL_NEVER_GRANTED`). |
| **`INV-06`** | Thu hồi quyền tức thời | Chấm dứt chức vụ hoặc khoá tài khoản sẽ thu hồi phiên làm việc và cập nhật `authz_version` ngay lập tức. |
| **`SEC-01`** | Kho lưu trữ mật ngoài Web Root | Chứng từ tài chính và tài liệu mật lưu trong `PrivateVaultStorage`, cấm phục vụ trực tiếp qua URL tĩnh, phục vụ qua Stream View kiểm tra quyền. |
| **`SEC-02`** | Chống CSV Formula Injection | Mọi giá trị xuất CSV đều qua bộ lọc `safe_csv_row`, thêm tiền tố `'` nếu bắt đầu bằng `=`, `+`, `-`, `@`. |
| **`CM-03`** | Khóa dữ liệu cũ khi đã ghi sổ | Khoản chi sự kiện cũ `organizing.Expense` bị khoá sửa/xoá khi phiếu sổ cái liên kết đạt `CONFIRMED`. |
| **`BE-06`** | Trao đổi hai chiều phi kỷ luật | Phản hồi đánh giá là diễn đàn đối thoại xây dựng, không kích hoạt quy trình kỷ luật. |

---

## 5. KẾ HOẠCH TIẾP THEO (PHASE 6 ROADMAP)

| Hạng mục | Mục tiêu Kỹ thuật | Kế hoạch Thực hiện |
| :--- | :--- | :--- |
| **6.1. Tối ưu Hiệu năng & Chỉ mục DB** | Giảm thiểu N+1 query, rà soát composite index trên các bảng giao dịch lớn (`financialtransaction`, `memberevaluation`, `eventattendance`). | Kiểm thử tải (load testing) với 1.000 user ảo, đo latency các API chính. |
| **6.2. Containerization & Docker Compose** | Đóng gói môi trường hoàn chỉnh: Web App (Django + Gunicorn), MySQL 8.4, Nginx Reverse Proxy, Redis Cache. | Viết `Dockerfile`, `docker-compose.yml`, kiểm thử triển khai trên Linux/Ubuntu. |
| **6.3. CI/CD Pipeline Automation** | Tự động chạy toàn bộ bộ test suite và migration check khi tạo Pull Request trên GitHub. | Cấu hình `.github/workflows/ci.yml` kiểm thử tự động trên runner Ubuntu. |
| **6.4. Tài liệu Vận hành & Hướng dẫn Sử dụng** | Cung cấp cẩm nang chi tiết cho Ban Chủ nhiệm, Trưởng các Ban, Cố vấn và Thành viên mới. | Xuất bản `USER_GUIDE.md` và `ADMIN_HANDBOOK.md` trong thư mục `docs/`. |

---

## 6. HƯỚNG DẪN CÀI ĐẶT & TÀI KHOẢN MẪU (QUICK START)

### 6.1. Cài đặt & Khởi chạy Nhanh
```powershell
# 1. Kích hoạt môi trường ảo Python
.\venv\Scripts\Activate.ps1

# 2. Cài đặt thư viện phụ thuộc
pip install -r requirements.txt

# 3. Khởi chạy MySQL Server 8.4 (Port 3306, utf8mb4)
& "C:\Program Files\MySQL\MySQL Server 8.4\bin\mysqld.exe" --datadir="C:\Users\vud20\mysql84_data" --port=3306 --character-set-server=utf8mb4 --collation-server=utf8mb4_0900_ai_ci

# 4. Áp dụng toàn bộ migrations
python manage.py migrate

# 5. Khởi tạo dữ liệu mẫu toàn hệ thống (Idempotent Seed)
python manage.py seed_kmg

# 6. Khởi động Web Server phát triển
python manage.py runserver 127.0.0.1:8000
```

### 6.2. Tài khoản demo KMG (mật khẩu `Kmg@2026!`, chỉ dùng DB demo riêng)
- **Admin Server (Quyền tối cao nâng cấp lãnh đạo):** `admin` (hoặc `srv_admin`)
- **Chủ nhiệm CLB (Điều hành toàn CLB):** `chunhiem` (Nguyễn Hoàng Long)
- **Phó chủ nhiệm phụ trách Nhân sự & Tài chính:** `phocn_nhansu` (Trần Hà Linh)
- **Phó chủ nhiệm phụ trách Sự kiện:** `phocn_sukien` (Lê Hoàng Nam)
- **Cố vấn CLB (Hard Read-Only / Giám sát):** `covan` (ThS. Vũ Quốc Bảo)
- **Trưởng ban Chuyên môn Âm nhạc:** `truongban_cm` (Phạm Gia Huy)
- **Trưởng ban Truyền thông sự kiện:** `truongban_tt` (Đặng Khánh Vy)
- **Trưởng ban Kỹ thuật (Demo):** `truongban_kt` (Hoàng Đức Minh)
- **Phó ban Chuyên môn (được ủy quyền gói):** `phoban_cm_uyquyen` (Bùi Thảo Nguyên)
- **Thành viên sinh hoạt Đa Ban (Chuyên môn & Kỹ thuật):** `thanhvien_daban` (Đỗ Quang Anh)
- **Thành viên có tài khoản bị tạm khóa (xem quyền riêng tư & khiếu nại):** `thanhvien_tamkhoa` (Phan Minh Quân)
