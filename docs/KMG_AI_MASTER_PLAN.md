# KMG AI — Master Plan (Intelligent Music Companion)

**Mục tiêu:** Nâng cấp toàn diện phân hệ `aiassist` thành trợ lý thông minh chuyên biệt cho CLB Âm nhạc KMG và sinh viên — hữu ích ngay cả khi CLB không tổ chức sự kiện — trên nền tảng kiến trúc bảo mật, phân quyền và đo lường được.

---

## 1. Phạm vi & Nguyên tắc bất biến
- **Chỉ tập trung vào `aiassist` và các tích hợp đọc/hỏi đáp liên quan trực tiếp.** Không migration lại toàn bộ DB, không redesign toàn bộ website.
- **Bảo mật thực thi tại backend:** Mọi kiểm tra quyền dùng `organization.permissions.PermissionEngine`; không tin role tự khai trong câu hỏi; không gửi dữ liệu `INTERNAL`/`CONFIDENTIAL`/`PRIVATE_PII` ra Cloud LLM (`egress.py`); không để AI tự sinh SQL hay thực thi thao tác ghi nghiệp vụ (duyệt đơn, chuyển tiền, sửa quyền).
- **An toàn âm nhạc & sinh viên:** Không khuyến khích luyện thanh khi đau/khàn giọng; không chẩn đoán y tế/tâm lý; không hướng dẫn sửa chữa điện nguy hiểm; không sao chép lời bài hát/giáo trình có bản quyền.

---

## 2. Lộ trình triển khai theo mức ưu tiên

### P0 — Nền tảng Cốt lõi, Dữ liệu, Định tuyến & Bảo mật
1. **Kiểm duyệt & Baseline** (`docs/AI_AUDIT_REPORT.md`).
2. **Nâng cấp `ClubKnowledge` & Importer Dataset v2:**
   - Bổ sung `knowledge_id`, `approval_status` (`DRAFT`, `PENDING`, `APPROVED`, `ARCHIVED`), `version`, `effective_date`, `source_note`, `source_urls`, `owner`, `revision_history`, danh mục `MUSIC`, `STUDENT_LIFE`, `TRAINING`, `TECH`.
   - Command `import_ai_dataset` hỗ trợ JSONL, `--dry-run`, kiểm tra schema/ID/nguồn/trùng lặp, bảo vệ bản ghi đã chỉnh sửa (`--force-overwrite` tắt mặc định), mặc định nhập ở trạng thái chờ duyệt (`PENDING`, `is_active=False`).
3. **AI Intent Router & Tiếng Việt tự nhiên (`aiassist/router.py` + `chatbot.py`):**
   - Chuẩn hóa tiếng Việt có dấu / không dấu / viết tắt (`ko`, `dc`, `ck`, `e`, `m`, `bh`, `ib`...) / tiếng lóng sinh viên / đa ý định.
   - Tách rõ nhóm intent: `public_kb`, `music_tutor`, `student_companion`, `public_db`, `authorized_db`, `clarify`, `deny`, `fallback`.
   - Chặn từ khóa rộng (`lịch`, `có gì`, `ban`) ghi đè ý định âm nhạc (`lịch tập`, `bấm F`, `lịch thi`).
4. **Hybrid RAG nâng cấp (`aiassist/services.py`):**
   - Kết hợp BM25 + Lexical + Metadata (`category`, `tags/topic`, `audience`, `version`, `priority`, `approval_status=APPROVED`) + ngưỡng từ chối rõ ràng cho câu hỏi ngoài phạm vi.
   - Hỗ trợ trích xuất đoạn dài hơn (600–800 ký tự) kèm nguồn (`title`, `category`, `knowledge_id`, `version`).
5. **Truy vấn dữ liệu nghiệp vụ động (Read-only, Authorized):**
   - Chuyển hoàn toàn sang model hiện hành: `organization.Department` (3 Ban: Chuyên môn, Truyền thông – Sự kiện, Kỹ thuật), `operations.ClubTask`, `programs.TrainingCourse` / `PracticeSession`, `recruitment.Application`, `evaluations.MemberEvaluation`, `finance.FinancialTransaction`, `registrations.Ticket`, `events.Event`.
   - Phân tầng quyền 6 nhóm đối tượng: Khách tham quan, Ứng viên, Thành viên, Trưởng/Phó ban & BTC, BCN & Tài chính, Cố vấn & Admin.
6. **Kiểm thử độc lập & Bảo mật (`evaluate_ai` + unit tests):**
   - Mở rộng `evaluate_ai` với split `dev`, `holdout`, `blind` độc lập (không lấy từ tập development/RAG), kiểm thử phân quyền, dữ liệu động, tiếng Việt không dấu, prompt injection, rò rỉ dữ liệu, fallback, p50/p95 latency.

### P1 — Music Tutor, Student Companion, AI Studio & UI
7. **Music Knowledge System & Music Tutor:**
   - Kho tri thức âm nhạc có cấu trúc (Guitar, Thanh nhạc, Nhạc lý, Piano/Keyboard/Bass/Trống/Ukulele/Cajon, Tập band, Biểu diễn, Sáng tạo âm nhạc).
   - Hồ sơ học nhạc cá nhân hóa (`MusicLearningProfile` liên kết `User`, tái sử dụng `Skill`/`UserSkill`/`TrainingCourse`), cho phép bật/tắt/sửa/xóa dữ liệu cá nhân hóa.
   - Sinh lộ trình 7 ngày / 30 ngày thích ứng theo thời gian rảnh, trình độ, mục tiêu; đánh giá tiến độ dựa trên bài tập & nhật ký thực tế.
8. **AI Companion (Đời sống sinh viên):**
   - Lắng nghe, phản hồi gần gũi, thực tế, không phán xét với các tình huống tâm lý/hòa nhập/bận thi/chưa có nhạc cụ.
9. **AI Studio & Chat UI:**
   - Studio: hàng đợi phê duyệt tri thức, phát hiện trùng/lỗi thời, thống kê latency & unresolved queries.
   - Chat UI: gợi ý câu hỏi theo vai trò, hiển thị nguồn tri thức, nút thao tác nhanh Music Tutor, giữ nguyên theme Light/Dark của hệ thống.

### P2 — Định hướng Tương lai (Kiến trúc & Roadmap)
10. **Mở rộng Dataset 2.000 kịch bản & Voice/Audio AI Roadmap:** Tài liệu hóa kiến trúc Voice AI, Tuner, Metronome, Pitch/Rhythm analysis trong `AI_ARCHITECTURE.md`.
