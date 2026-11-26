# Kế hoạch sẵn sàng Local LLM cho Clubevent & KMG AI

Tài liệu đánh giá khả năng triển khai **Local LLM** trên phần cứng hiện có của nhóm phát triển và cấu hình cổng kết nối chuẩn OpenAI API đã tích hợp sẵn trong `aiassist/providers.py`.

## 1. Cấu hình phần cứng máy phát triển (đã kiểm tra thực tế)

- **CPU:** Intel Core i5-12500H (12th Gen, 12 nhân / 16 luồng)
- **RAM:** 16 GB DDR4-3200 (2 x 8 GB = 16,869,548,032 bytes khả dụng)
- **GPU:** NVIDIA GeForce RTX 3050 Laptop GPU + Intel Iris Xe Graphics

## 2. Đánh giá mức độ phù hợp mô hình

Với cấu hình laptop i5-12500H + RTX 3050 (VRAM 4 GB tiêu chuẩn) + 16 GB RAM:

| Nhóm mô hình | Quantization khuyến nghị | Mức phù hợp | Vai trò dự kiến |
|---|---|---|---|
| **Qwen2.5-3B-Instruct** / **Llama-3.2-3B-Instruct** | `Q4_K_M` (~2.0 GB VRAM) | Phù hợp trực tiếp | Trợ lý hỏi đáp tiếng Việt nhanh, fallback ngoại tuyến |
| **Qwen2.5-1.5B-Instruct** / **Gemma-2-2B-it** | `Q4_K_M` (~1.2–1.6 GB VRAM) | Rất nhẹ, độ trễ thấp | Streaming SSE câu hỏi ngắn trên máy yếu/CPU fallback |
| Mô hình 7B–8B | `Q4_K_M` (~4.7–5.5 GB) | Không khuyến nghị chạy 24/7 trên VRAM 4 GB | Phải offload nhiều lớp sang RAM, độ trễ cao |

## 3. Tích hợp kiến trúc đã hoàn thành trong mã nguồn

Hệ thống không phụ thuộc SDK riêng của Ollama mà sử dụng **OpenAI-compatible REST & SSE Adapter** trong [aiassist/providers.py](../aiassist/providers.py) và [aiassist/services.py](../aiassist/services.py):

- Biến môi trường trong [config/settings.py](../config/settings.py):
  - `AI_PROVIDER=local` (hoặc `ollama`)
  - `AI_LOCAL_BASE_URL=http://127.0.0.1:11434/v1` (mặc định chuẩn Ollama; tương thích vLLM / LM Studio)
  - `AI_LOCAL_MODEL=qwen2.5:3b`
  - `AI_FALLBACK_PROVIDER=local` (tự động chuyển sang Local LLM nếu Gemini/OpenAI quá tải hoặc Circuit Breaker mở mạch)
- Cơ chế bảo vệ đi kèm:
  - **Không bắt buộc `AI_API_KEY`** khi `AI_PROVIDER` là `local` hoặc `ollama`.
  - **Circuit Breaker:** tự mở mạch khi provider lỗi liên tiếp vượt `AI_CIRCUIT_BREAKER_THRESHOLD` (mặc định `5`), tránh nghẽn worker web trong thời gian `AI_CIRCUIT_BREAKER_COOLDOWN` (`60` giây).
  - **Daily Budget & Prompt Cap:** kiểm soát theo `AI_MAX_PROMPT_CHARS` (`32000`) và `AI_DAILY_CHAR_BUDGET` (`500000`).
  - **Streaming SSE thật:** `stream_openai_tokens()` đọc luồng `data: {...}` / `data: [DONE]` trực tiếp từ local server mà vẫn giữ kiểm soát URL & nguồn trích dẫn từ máy chủ.

## 4. Quy trình benchmark khi cài đặt Ollama trên máy thật

> **Lưu ý hiện trạng:** Môi trường kiểm thử hiện tại chưa cài sẵn dịch vụ Ollama/Docker nên toàn bộ luồng Local LLM mới được kiểm chứng qua mock HTTP/SSE adapter trong [aiassist/test_providers.py](../aiassist/test_providers.py). Khi triển khai thử nghiệm Local LLM thật cần thực hiện các bước sau:

1. Cài Ollama và tải mô hình: `ollama pull qwen2.5:3b`
2. Khởi động với `.env`:
   - `AI_PROVIDER=local`
   - `AI_LOCAL_BASE_URL=http://127.0.0.1:11434/v1`
   - `AI_LOCAL_MODEL=qwen2.5:3b`
3. Chạy kiểm định chất lượng có LLM Judge:
   - `python manage.py evaluate_ai --min-intent 0.95 --llm-judge`
4. Đo độ trễ TTFT (Time To First Token), throughput (tokens/s) và tỷ lệ tuân thủ JSON schema trên tập 50 câu hỏi `blind`.
