# KMG AI — Kiến trúc Hệ thống (AI Architecture)

## 1. Luồng xử lý Hybrid (`aiassist/chatbot.py` + `router.py` + `services.py`)

```
User Query
  │
  ▼
[1. Security Pre-Check] (router.py::is_security_violation)
  ├─ Phát hiện jailbreak / role-spoofing / dò OTP, API key, vé người khác → Trả lời từ chối an toàn (`security_deny`)
  │
  ▼
[2. Context & Normalization] (router.py::prepare_query)
  ├─ Tách "bạn" (_nguoi_) khỏi "ban", bỏ dấu, mở rộng viết tắt/slang sinh viên (ko, dc, ck, hnay, t7...)
  │
  ▼
[3. Intent Router & Disambiguation] (chatbot.py::detect_intent)
  ├─ Chặn từ khóa rộng ("lịch", "có gì") đè lên ý định âm nhạc/lịch tập/lịch thi
  ├─ Khớp intent nghiệp vụ → Kiểm tra đăng nhập & `PermissionEngine` → `business_queries.py` / `HANDLERS`
  │
  ▼
[4. Music Tutor & Student Companion] (music_tutor.py::answer_music_or_companion)
  ├─ Lộ trình 7/30 ngày thích ứng (`MusicLearningProfile` + `UserSkill`)
  ├─ Tiến độ luyện tập thực tế (`MusicPracticeLog`)
  ├─ Tư vấn sinh viên (tâm lý, chưa có nhạc cụ, bận thi) & Tri thức âm nhạc an toàn
  │
  ▼
[5. Hybrid RAG + LLM Grounding] (services.py::ask_assistant / stream_assistant_reply)
  ├─ `ClubKnowledge` (chỉ `is_active=True`, `approval_status=APPROVED`, đúng `visibility` và `effective_date`)
  ├─ BM25 + Lexical Scoring + Metadata
  ├─ Egress Policy (`egress.py`): chặn tuyệt đối dữ liệu non-public ra Cloud LLM
  └─ Fallback an toàn về `UNKNOWN_TEXT` khi LLM không khả dụng
```

---

## 2. Định hướng Tương lai — Phase 14 (Voice & Audio AI Roadmap)
*Chỉ lập kiến trúc và lộ trình, chưa triển khai trong đợt này:*
1. **Guitar Tuner & Pitch Detection:** Web Audio API (trình duyệt) thu tín hiệu micro cục bộ, chạy thuật toán YIN / autocorrelation client-side để hiển thị tần số & độ lệch cent theo thời gian thực (không gửi audio thô lên server nếu không cần thiết).
2. **Metronome & Rhythm Analysis:** Bộ đếm nhịp Web Audio API (AudioWorklet chính xác mức mili-giây) kết hợp phát hiện onset (năng lượng phổ) để đo độ đều nhịp khi tập quạt chả / Cajon.
3. **Luyện cảm âm & Đánh giá bài luyện:** Chỉ triển khai sau khi hoàn thiện bộ đánh giá văn bản và có sự tham gia kiểm duyệt của Ban Chuyên môn.
