# KMG AI — Báo cáo Kiểm duyệt Hệ thống Hiện tại (Phase 1 Audit)

**Ngày kiểm duyệt:** 2026-11-26  
**Phạm vi:** Phân hệ `aiassist/` và các module liên quan trực tiếp (`organization`, `operations`, `programs`, `events`, `registrations`, `recruitment`, `finance`, `evaluations`, `templates/aiassist/`, `static/js/chatbot.js`).

---

## 1. Kết quả đo Baseline trước nâng cấp

| Hạng mục kiểm tra | Lệnh thực thi | Kết quả thực tế |
|---|---|---|
| Unit tests `aiassist` | `.\venv\Scripts\python.exe manage.py test aiassist --settings=config.settings_test` | **141/141 PASS** (9.263s) |
| Intent [dev] (`golden_intents.json`) | `evaluate_ai --with-migrate --settings=config.settings_test` | **38/38 (100%)** |
| Intent [holdout] | `evaluate_ai` | **22/22 (100%)** |
| Intent [blind] | `evaluate_ai` | **50/50 (100%)** |
| Retrieval [dev] (`golden_retrieval.json`) | `evaluate_ai` | **13/13 (100%)** |
| Retrieval [holdout] | `evaluate_ai` | **7/8 (88%)** — Lỗi: `'lịch thi học kỳ của trường'` khớp nhầm `[Thông tin chung CLB] Đề xuất hoạt động, đào tạo và lịch tập band` |
| Che PII (`REDACTION_CASES`) | `evaluate_ai` | **6/6 PASS** |
| Fallback khi AI lỗi | `evaluate_ai` | **PASS** |

---

## 2. Điểm mạnh đã có (Giữ nguyên & Kế thừa)

1. **Chính sách Egress Fail-Closed (`aiassist/egress.py`):** Phân loại `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `PRIVATE_PII`. Chặn tuyệt đối dữ liệu non-public gửi ra Cloud LLM (`gemini`, `openai`), chỉ cho phép Local LLM tin cậy.
2. **Bảo vệ PII & Chống Prompt Injection (`aiassist/privacy.py`):** Che email, SĐT, MSSV, mã vé 12 ký tự hex, CCCD, họ tên đã biết; làm sạch ký tự điều khiển và thẻ giả mạo ranh giới prompt (`sanitize_untrusted_input`, `<USER_QUERY>`).
3. **Phân quyền tri thức bước đầu (`aiassist/models.py`, `services.py`):** `ClubKnowledge.visibility` (`PUBLIC` / `INTERNAL` / `CONFIDENTIAL`) lọc qua `PermissionEngine` (`visible_knowledge_levels`), có re-check phân quyền lịch sử chat mỗi lượt (`_load_chat_history`).
4. **Structured Output (`aiassist/schemas.py`):** JSON Schema cho 9 tác vụ AI kèm fallback an toàn.
5. **Signed Feedback Token (`aiassist/views.py`):** Chống IDOR khi đánh giá 👍/👎 bằng `django.core.signing` (hạn 24h, dùng 1 lần).

---

## 3. Hạn chế & Khoảng trống cần khắc phục

| # | Hạn chế xác minh được | Vị trí trong code | Mức độ |
|---|---|---|---|
| 1 | **Nhận diện ý định chỉ có 10 intent cứng bằng tổng độ dài từ khóa**, thiếu toàn bộ intent âm nhạc, đời sống sinh viên, lịch tập, đào tạo, đánh giá, tài chính, lãnh đạo. | `aiassist/chatbot.py::INTENTS` | P0 |
| 2 | **Từ khóa rộng gây hiểu sai câu hỏi:** `"lich"`, `"co gi"`, `"hoat dong"` trong `upcoming_events` có thể nuốt câu hỏi `"tối nay có lịch tập không"`, `"lịch thi học kỳ"`. | `aiassist/chatbot.py::INTENTS` | P0 |
| 3 | **Tham chiếu model nghiệp vụ cũ:** `_club_departments`, `build_assistant_context`, `_tool_get_club_overview`, `export_finetune_dataset` dùng `organizing.models.Department`; `_my_tasks` dùng `organizing.models.Task` và `user.is_staff_btc` thay vì `organization.Department`, `operations.ClubTask` và `PermissionEngine`. | `chatbot.py`, `services.py`, `adapters.py`, `export_finetune_dataset.py` | P0 |
| 4 | **RAG giới hạn `limit=4` và `350` ký tự/mục**, chưa có metadata quản trị tri thức (`knowledge_id`, `approval_status`, `version`, `effective_date`, `source_urls`, `owner`, `revision_history`), chưa hỗ trợ danh mục Âm nhạc & Đời sống sinh viên. | `aiassist/models.py`, `aiassist/services.py` | P0 |
| 5 | **Thiếu truy vấn dữ liệu nghiệp vụ động theo phân quyền:** Chưa tra được hồ sơ tuyển thành viên cá nhân, lịch tập (`PracticeSession`), khóa đào tạo (`TrainingCourse`), điểm danh (`EventAttendance`), kỹ năng (`UserSkill`), đánh giá (`MemberEvaluation`), thu chi (`FinancialTransaction`), thống kê Ban/CLB. | `aiassist/chatbot.py`, `aiassist/services.py` | P0 |
| 6 | **Chưa tích hợp Dataset v2** (`KMG_AI_Dataset_v2_Music.zip`: 317 kịch bản, 94 biến thể, 46 ứng viên tri thức) và chưa có JSONL importer an toàn (dry-run, chống trùng, không ghi đè mục đã sửa, quy trình duyệt). | `aiassist/management/commands/` | P0 |
| 7 | **Chưa có Gia sư Âm nhạc cá nhân hóa & AI Companion:** Chưa có hồ sơ học nhạc, lộ trình 7/30 ngày, bài tập theo trình độ, hỗ trợ tâm lý sinh viên. | `aiassist/` | P1 |
| 8 | **AI Studio & Giao diện Chatbot chưa hỗ trợ quy trình mới:** Studio chưa có hàng đợi duyệt tri thức, cảnh báo mâu thuẫn/lỗi thời, thống kê latency/cost; Chat UI chưa hiển thị nguồn trích dẫn rõ ràng, gợi ý theo vai trò và Music Tutor. | `aiassist/views.py`, `templates/aiassist/` | P1 |
| 9 | **Pipeline xuất dữ liệu & đánh giá:** `evaluate_ai` mới đo 10 intent cũ và 8 câu retrieval; chưa có bộ test bảo mật/phân quyền/dữ liệu động/tiếng Việt không dấu toàn diện trong `evaluate_ai`. | `evaluate_ai.py`, `export_finetune_dataset.py` | P0 |
