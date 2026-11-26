# KMG AI — Các Hạn chế & Rủi ro Còn Tồn Tại (Known Issues)

1. **Chưa thực hiện benchmark LLM thực tế với Ollama / Gemini Live API trên máy dev:** Môi trường dev Windows chưa cài Ollama và `evaluate_ai` mặc định chạy offline/mock. Độ trễ `p50`/`p95` đã đo hiện tại phản ánh tầng Router cục bộ (`0.11ms` / `0.19ms`), chưa đo end-to-end latency qua mạng tới LLM.
2. **46 mục tri thức Dataset v2 đang ở trạng thái chờ duyệt (`PENDING`):** Cần Ban Chuyên môn kiểm duyệt 24 mục âm nhạc (`MUSIC-K01`..`MUSIC-K24`) và BCN kiểm duyệt 22 mục nghiệp vụ (`K01`..`K22`) trong AI Studio trước khi kích hoạt lên RAG chính thức.
3. **Fine-tuning chưa thực hiện trong đợt này:** Theo phạm vi kế hoạch, chưa gửi job fine-tuning; tập trung vào Hybrid RAG, Intent Router và Golden Eval Loop.
4. **Rollback:** Nếu cần quay lại trạng thái trước migration `0008`, chạy `python manage.py migrate aiassist 0007` trước khi revert code.
