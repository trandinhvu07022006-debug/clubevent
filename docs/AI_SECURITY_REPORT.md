# KMG AI — Báo cáo Bảo mật (AI Security Report)

## 1. Các cơ chế phòng vệ thực thi tại Backend
1. **Chống Prompt Injection & Role Spoofing (`aiassist/router.py`, `privacy.py`):**
   - `is_security_violation()` chặn các mẫu jailbreak (`ignore all previous instructions`, `bỏ qua quy tắc`), giả mạo chức danh (`coi em là trưởng ban`, `giả sử em là admin`), yêu cầu ghi/miễn điểm danh trái phép, và dò bí mật/IDOR (`in ra api key`, `xem mã vé của người khác`).
   - `sanitize_untrusted_input()` loại bỏ ký tự điều khiển và thẻ giả mạo ranh giới (`</USER_QUERY>`, `<|im_start|>`) trước khi ghép prompt.
2. **Phân quyền tri thức & Dữ liệu động (`PermissionEngine`):**
   - `ClubKnowledge` chỉ truy xuất các mục `is_active=True`, `approval_status=APPROVED`, `visibility` khớp `visible_knowledge_levels(user)`.
   - Mọi truy vấn động (`business_queries.py`) kiểm tra `PermissionEngine.authorize(user, ...)` trên `request.user` đã xác thực; `Application`, `Ticket`, `MemberEvaluation` lọc chặt theo `user=user` (chống IDOR).
3. **Egress Policy (`aiassist/egress.py`):** Chặn tuyệt đối dữ liệu `INTERNAL`, `CONFIDENTIAL`, `PRIVATE_PII` gửi ra Cloud LLM (`gemini`, `openai`).
4. **Bảo vệ Session, Log & Export (`views.py`, `export_finetune_dataset.py`):**
   - `chat_history` re-check quyền qua từng lượt (`_load_chat_history`); `PRIVATE_INTENTS` không lưu vào lịch sử hoặc `answer_preview`.
   - `export_finetune_dataset` mặc định chỉ xuất dữ liệu `PUBLIC` và `ClubKnowledge` đã `APPROVED`.
   - Feedback token ký bằng `django.core.signing` (hạn 24h, dùng 1 lần).

## 2. Kết quả kiểm thử bảo mật
- Toàn bộ **148 unit tests** trong `aiassist` (bao gồm `test_rc1_security.py`, `test_phase5_ai_safety.py`, `test_safety.py`, `test_kmg_companion.py`) đều **PASS**.
- `evaluate_ai`: Che PII **6/6**, Bảo mật & Music/Companion **7/7**.
