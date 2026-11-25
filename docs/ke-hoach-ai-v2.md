# Kế hoạch AI v2: an toàn trước, đo được sau

Tài liệu đối chiếu các nâng cấp an toàn dữ liệu và đánh giá chất lượng cho trợ lý AI (`aiassist`), tích hợp trên mốc `ce9fc9c`.

## 1. Hạng mục đã hoàn thiện

### P0 — An toàn dữ liệu & Sửa lỗi tiếng Việt
| Vấn đề | Cách sửa | File | Test nghiệm thu |
|---|---|---|---|
| Mã vé lọt sang AI qua lịch sử chat | Bỏ hẳn lượt hỏi đáp cá nhân (`PRIVATE_INTENTS`) khỏi lịch sử; che PII trước khi ghép prompt | `views.py`, `chatbot.py`, `services.py` | `test_ticket_code_never_reaches_ai` |
| Log lưu PII và mã vé | Che theo mẫu (`privacy.py`); không lưu câu trả lời cá nhân | `privacy.py`, `views.py` | `test_log_keeps_no_personal_answer_and_masks_question` |
| Dữ liệu cũ đã lỡ lưu | Migration `0003` che lại các bản ghi cũ | `migrations/0003_scrub_existing_logs.py` | `test_migration_scrubs_old_rows` |
| Góp ý, đơn tuyển, đề xuất, bài viết gửi nguyên văn cho AI | Che PII trước khi gửi sang LLM | `services.py`, `social/views.py` | `test_feedback_content_is_masked`, `PlatformAIPrivacyTests` |
| Ai cũng đánh giá được log bất kỳ (IDOR) | Token ký bằng `django.core.signing`, hạn 24h, dùng 1 lần | `views.py`, `chatbot.js`, `floating_chat.html` | `FeedbackSecurityTests` |
| "Các bạn" bị hiểu nhầm là "các Ban" | Phân biệt "bạn" (`_nguoi_`) trước khi bỏ dấu; thu hẹp từ khóa `club_departments` | `chatbot.py` | `MatchingTests` |

### P1 & P2 — Chất lượng đo được, Structured Schema & Telemetry
- **RAG lọc lạc đề:** Dùng `_knowledge_score()` khớp nguyên từ, bỏ `RETRIEVAL_STOPWORDS` và ngưỡng `RETRIEVAL_MIN_SCORE = 3` để câu hỏi ngoài lề trả rỗng.
- **Golden Sets (`aiassist/evals/`):** Đo riêng 3 tập `dev`, `holdout`, `blind` trong `evaluate_ai.py`, tự thoát mã lỗi (`CommandError`) nếu dưới ngưỡng.
- **Structured Output (`schemas.py`):** Dùng `generationConfig.responseFormat` kèm fallback HTTP 400 cho toàn bộ **9 tác vụ AI** (đã kiểm thử gọi thực tế thành công **HTTP 200 OK** với Gemini `gemini-3.6-flash`).
- **Telemetry & Validation:** Lưu `latency_ms`, `model_name`, `prompt_version` (mã băm SHA-256) trên `AIInteractionLog`; kiểm tra định dạng Few-Shot (`AIPromptProfile.clean()`, tối đa 3 ví dụ); bổ sung xuất Eval JSONL (`export_eval_dataset` & Web Studio).

## 2. Giới hạn minh bạch
- Bộ che PII hoạt động **theo mẫu và danh sách tên đã biết** (`aiassist/privacy.py`), không khẳng định là "Zero PII tuyệt đối".
- Endpoint Gemini `v1beta/tunedModels` đã kiểm thử thực tế và trả về `HTTP 501 Not Implemented` với API key thông thường; việc cải tiến liên tục trong dự án tập trung vào **RAG + Prompt Registry + Eval Loop trên Golden Set**.
