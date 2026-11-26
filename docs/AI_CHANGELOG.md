# KMG AI — Changelog

## [2026-11-26] KMG AI — Intelligent Music Companion Upgrade

### Thêm mới
- `aiassist/router.py`: Chuẩn hóa tiếng Việt có dấu/không dấu/viết tắt/slang sinh viên, phát hiện jailbreak/role-spoofing/dò bí mật.
- `aiassist/music_tutor.py`: Hệ thống tri thức âm nhạc an toàn (Guitar, Thanh nhạc, Nhạc lý, Nhạc cụ khác, Tập band, Biểu diễn, Sáng tạo), AI Companion cho đời sống sinh viên, lộ trình học nhạc 7/30 ngày thích ứng và thống kê tiến độ thực tế.
- `aiassist/business_queries.py`: Truy vấn dữ liệu nghiệp vụ động có kiểm tra `PermissionEngine` (`PracticeSession`, `recruitment.Application`, `TrainingEnrollment`, `UserSkill`, `MemberEvaluation`, `ClubTask`, `FinancialTransaction`, `ClubMembership`).
- `aiassist/models.py` + `0008_clubknowledge_approval_status_and_more.py`: Bổ sung trường quản trị kho tri thức (`knowledge_id`, `approval_status`, `version`, `effective_date`, `source_urls`, `source_note`, `owner`, `is_admin_edited`, `revision_history`), mở rộng `KnowledgeCategory`, thêm `MusicLearningProfile` & `MusicPracticeLog`.
- `aiassist/management/commands/import_ai_dataset.py`: Importer JSONL cho Dataset v2 (`aiassist/datasets/v2/`) hỗ trợ `--dry-run`, kiểm tra schema/ID/nguồn/trùng lặp, bảo vệ bản ghi đã chỉnh sửa và quy trình chờ duyệt.
- `aiassist/test_kmg_companion.py`: 7 test cases chuyên sâu cho importer, tiếng Việt slang, an toàn âm nhạc/điện, chống giả mạo vai trò, và Music Profile API.

### Cập nhật
- `aiassist/chatbot.py`: Tích hợp router mới, chặn từ khóa rộng (`lịch`, `có gì`) đè lên câu hỏi âm nhạc/lịch tập/lịch thi; chuyển `_club_departments` sang `organization.Department` và `_my_tasks` sang `operations.ClubTask` (giữ fallback cho model cũ).
- `aiassist/services.py`, `adapters.py`, `export_finetune_dataset.py`: Lọc `ClubKnowledge` theo `approval_status=APPROVED` và `effective_date`, nới snippet RAG lên 650 ký tự, sửa lỗi khớp nhầm `'lịch thi học kỳ của trường'`, ưu tiên `organization.Department`.
- `aiassist/views.py`, `urls.py`, `templates/aiassist/studio.html`, `chat.html`: Gợi ý câu hỏi theo vai trò, API `/troly/ho-so-nhac/` quản lý cá nhân hóa, quy trình Duyệt/Lưu trữ tri thức và chỉ số latency trên AI Studio.
- `aiassist/management/commands/evaluate_ai.py`: Bổ sung kiểm thử Bảo mật & Music/Companion và đo `p50`/`p95` latency.
