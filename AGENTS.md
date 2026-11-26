# AGENTS.md — Quy chuẩn phối hợp Antigravity & OpenAI Codex (`clubevent`)

Tài liệu này được đọc tự động bởi **cả Antigravity và OpenAI Codex CLI** tại `D:\clubevent\clubevent`.

## 1. Bắt buộc khi bắt đầu mỗi phiên làm việc
Trước khi lập kế hoạch, phân tích sâu hoặc chỉnh sửa bất kỳ file nào, **cả Antigravity và Codex BẮT BUỘC phải đọc**:
1. `AGENTS.md` (file này)
2. `docs/AI_DEVELOPMENT_STATE.md` (trạng thái dự án, bảng khóa file đang sửa, hàng đợi bàn giao và nhật ký review chéo)

Khi kết thúc công việc hoặc bàn giao sang Agent kia, Agent vừa thực thi phải cập nhật lại `docs/AI_DEVELOPMENT_STATE.md`.

## 2. Phân công vai trò
- **Antigravity (Môi trường phát triển chính):**
  - Thực thi phát triển tính năng Django (`accounts`, `events`, `organizing`, `registrations`, `feedback`, `aiassist`, `organization`, `social`, `programs`, `evaluations`, `operations`, `recruitment`).
  - Chỉnh sửa template/static UI, tạo migration, chạy kiểm thử toàn cục, kiểm tra trình duyệt, quản lý nhánh Git và tích hợp bản cuối.
- **OpenAI Codex CLI (Chuyên gia phối hợp):**
  - Phản biện kiến trúc, rà soát bảo mật/race-condition/bất biến (`INV-*`), review chéo thay đổi qua `codex exec review`.
  - Phân tích hoặc đề xuất sửa lỗi ở chế độ chỉ đọc (`codex exec -s read-only`), hoặc xử lý module độc lập trên Git worktree tách biệt (`--worktree`).

## 3. Quy tắc chống xung đột — Single-Writer (Cấm sửa trùng file)
1. **Không bao giờ để hai Agent đồng thời chỉnh sửa cùng một file.**
2. Trước khi chỉnh sửa bất kỳ file nào, Agent cầm quyền ghi **phải ghi tên file, tên Agent (`antigravity` hoặc `codex`) và nhánh làm việc** vào mục **Bảng Khoá File Đang Hoạt Động** trong `docs/AI_DEVELOPMENT_STATE.md`.
3. Khi Antigravity gọi Codex CLI trên cùng thư mục `D:\clubevent\clubevent`:
   - Dùng `-s read-only` cho phân tích/tư vấn và `codex exec review` cho review chéo.
   - Nếu cần Codex trực tiếp sửa mã nguồn song song, bắt buộc chạy trên **Git worktree riêng (`codex exec --worktree`)** với phạm vi file tách biệt hoàn toàn khỏi danh sách Antigravity đang khóa; sau đó Antigravity review diff rồi mới gộp.
4. Sau khi hoàn tất và kiểm thử xong, Agent phải xóa khóa của mình khỏi `docs/AI_DEVELOPMENT_STATE.md`.

## 4. Quy trình Bàn giao — Review Chéo — Kiểm thử (4 bước)
1. **Bàn giao (Handoff):** Kiểm tra `docs/AI_DEVELOPMENT_STATE.md` không có xung đột file, ghi nhận nhiệm vụ vào bảng bàn giao với phạm vi file rõ ràng và tiêu chí hoàn thành.
2. **Thực thi trên nhánh riêng:**
   - Làm việc trên nhánh feature/fix riêng hoặc worktree riêng. **Tuyệt đối không push trực tiếp lên `main`.**
   - Không đọc, in, hay sửa giá trị bí mật trong `.env`, `.env.production*`.
   - Codex chỉ xác thực bằng tài khoản ChatGPT chính thức (`forced_login_method = "chatgpt"` trong `~/.codex/config.toml`), **không dùng `OPENAI_API_KEY` trả phí**, không dùng token phiên nội bộ hoặc cách xác thực không chính thức.
3. **Review chéo (Cross-Review):**
   - Sau khi Agent chính (thường là Antigravity) hoàn tất thay đổi chưa commit hoặc trên nhánh feature, gọi Codex chạy review chéo:
     - `codex exec review --uncommitted` (review thay đổi đang làm)
     - hoặc `codex exec review --base main` (review toàn bộ nhánh so với `main`)
   - Nếu Codex đề xuất sửa đổi trên worktree/patch, Antigravity phải đọc diff, xác minh không phá vỡ bất biến hệ thống rồi mới áp dụng.
4. **Kiểm thử bắt buộc trước khi kết luận:**
   - Kiểm tra cấu hình: `.\venv\Scripts\python.exe manage.py check`
   - Chạy test liên quan và/hoặc toàn bộ suite: `.\venv\Scripts\python.exe manage.py test --keepdb`
   - Nếu sửa `aiassist`, chạy thêm: `.\venv\Scripts\python.exe manage.py evaluate_ai`
   - Lưu ý: `config/settings.py` tự động xóa `AI_API_KEY` khi chạy `test`; mọi test AI phải chạy offline/mock an toàn.

## 5. Bất biến kỹ thuật của Clubevent & KMG AI cần bảo toàn
- **Môi trường Python:** Luôn dùng `.\venv\Scripts\python.exe` tại `D:\clubevent\clubevent`.
- **Bảo mật & Secrets:** Giữ nguyên cơ chế fail-closed khi `DEBUG=False` cho `SECRET_KEY`, `CERT_SIGNING_KEY`, `CHAT_MASTER_KEK`, cùng lớp throttle đăng nhập web + `/admin/login/`.
- **Quyền riêng tư (PII):** Dữ liệu gửi ra AI ngoài phải đi qua bộ che PII (`aiassist/privacy.py`); không gửi thông tin cá nhân nhạy cảm (MSSV, email, SĐT, mã vé riêng) qua tầng AI hoặc vào log.
- **Tôn trọng dữ liệu & mã nguồn hiện có:** Không tự ý reset DB local/demo hoặc ghi đè file chưa được bàn giao.

## 6. Quy chuẩn kỹ thuật & an toàn bổ sung (hợp nhất từ `AGENTS_PROPOSED.md`)
- **Kiến trúc & phạm vi:** Duy trì Django modular monolith, MySQL, SOLID/DRY/KISS và tương thích ngược. Không đổi app label, schema bảng hoặc URL contract khi chưa có phân tích và kế hoạch migration được duyệt.
- **Ranh giới tin cậy AI:** Mọi thông tin quyền (`user_id`, `club_id`, `permissions`) lấy từ backend đã xác thực; đầu ra của model là dữ liệu không đáng tin cậy. Tool ghi dữ liệu chỉ được mở khi có kiểm tra quyền theo đối tượng, xác nhận người dùng, validation, idempotency và audit log.
- **Môi trường kiểm thử & ngôn ngữ:** Chỉ kiểm thử trên `config.settings_test`, DB/cache cách ly và provider mock; không tạo dữ liệu demo trên DB thật; báo cáo đầy đủ kết quả thực (gồm fail/skip/blocker). Mã nguồn và định danh dùng tiếng Anh; tài liệu, báo cáo dùng tiếng Việt. Không coi kế hoạch hoặc mục tiêu là kết quả đã đạt.
