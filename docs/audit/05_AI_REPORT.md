# PHASE 5 — BÁO CÁO NÂNG CẤP & AN TOÀN KMG AI (AI REPORT)

**Ngày thực hiện:** 2026-11-26  
**Nhánh làm việc:** `feature/kmg-system-stabilization`  

---

## 1. Kiến trúc KMG AI hiện tại (Hybrid Agent + RAG + Multi-Provider)

1. **Tầng 1 — Luật & Ý định tiếng Việt (`aiassist/chatbot.py`):**
   - `prepare_query()` chuẩn hóa dấu NFD/NFC, tách `"bạn"` vs `"ban"`, bỏ ký tự lặp, chuẩn hóa `"check-in"`, lọc lời chào đầu câu `_is_pure_greeting()`.
   - Dữ liệu nhạy cảm/cá nhân (`my_tickets`, `my_tasks`) và `PRIVATE_INTENTS` (`upcoming_events`, `seats_left`, `greeting`, `my_tickets`, `my_tasks`) chạy cục bộ 100%, không đẩy vào `chat_history` hoặc `AIInteractionLog.answer_preview`.
2. **Tầng 2 — Hybrid RAG BM25 + Lexical có phân quyền (`aiassist/services.py`, `aiassist/adapters.py`, `aiassist/models.py`):**
   - **Phân loại dữ liệu fail-closed (`ClubKnowledge.visibility`, migration `0006`):**
     - `PUBLIC` (Công khai) / `INTERNAL` (Nội bộ CLB — **mặc định cho mục mới**) / `CONFIDENTIAL` (Mật / Quản trị).
     - `visible_knowledge_levels(user)` và `retrieve_knowledge_bm25()` lọc quyền chặt theo `can_view_internal_events(user)` (chặn Khách và thành viên `SUSPENDED` khỏi dữ liệu `INTERNAL`; chỉ `LEAD`/`ADMIN` thấy `CONFIDENTIAL`).
     - `export_finetune_dataset` chỉ xuất mục `PUBLIC`.
   - Trả nguồn trích dẫn (`sources`) ra JSON/SSE và hiển thị qua `textContent` tại giao diện chat.
3. **Phòng vệ Prompt Injection & PII (`aiassist/privacy.py`, `aiassist/services.py`):**
   - `redact()` che email, SĐT, MSSV, mã vé, số dài, họ tên trước khi lưu log hoặc gọi LLM.
   - `sanitize_untrusted_input()` loại ký tự điều khiển và thẻ giả ranh giới (`<|im_start|>`, `<system>`, `</USER_QUERY>`, `### SYSTEM:`); câu hỏi được bọc riêng trong `<USER_QUERY>...</USER_QUERY>`.
4. **Multi-Provider Gateway, Local LLM & Streaming (`aiassist/providers.py`):**
   - Hỗ trợ `gemini`, `openai`, `local`/`ollama` (chuẩn OpenAI API `/v1/chat/completions`, không yêu cầu `AI_API_KEY`), và `mock`.
   - Bảo vệ bởi `CircuitBreaker` (`AI_CIRCUIT_BREAKER_THRESHOLD=5`, cooldown `60s`), `DailyBudgetTracker` (`AI_DAILY_CHAR_BUDGET=500000`, `AI_MAX_PROMPT_CHARS=32000`), fallback `AI_FALLBACK_PROVIDER`, và streaming SSE trực tiếp từ provider.

---

## 2. Đánh giá phần cứng Local LLM (`P5.4`)

Kiểm tra phần cứng máy dev thực tế (`Get-CimInstance`):
- **CPU:** Intel Core i5-12500H (12 nhân / 16 luồng).
- **RAM:** 16 GB DDR4-3200 (`16,869,548,032` bytes).
- **GPU:** NVIDIA GeForce RTX 3050 Laptop GPU — **VRAM 4 GB** (`4,293,918,720` bytes) + Intel Iris Xe Graphics.
- **Kết luận & Blocker:** VRAM 4 GB phù hợp chạy mô hình nhỏ quantized `Q4_K_M` cỡ 1.5B–3B (`qwen2.5:3b` / `qwen2.5:1.5b`) qua Ollama. Máy hiện chưa cài Ollama và chưa tải mô hình về nên **benchmark tốc độ TTFT / tokens/s thực tế** được đánh dấu `BLOCKED` (mã nguồn adapter & SSE local đã test bằng mock trong `aiassist/test_providers.py`).

---

## 3. Bằng chứng kiểm thử Phase 5

- `python manage.py test aiassist.test_phase5_ai_safety aiassist.test_llmops --settings=config.settings_test`: kiểm chứng phân quyền `PUBLIC` / `INTERNAL` / `CONFIDENTIAL` / `SUSPENDED`, fail-closed default `INTERNAL`, lọc xuất dataset fine-tune, chống prompt injection và pipeline LLMOps.
- `python manage.py evaluate_ai --with-migrate --settings=config.settings_test` (chạy ở kiểm thử cuối suite): đo Golden Intent (`dev` 38/38, `holdout` 22/22, `blind` 50/50), Retrieval (`dev` 13/13, `holdout` 7/8), PII `6/6`, Fallback OK.
