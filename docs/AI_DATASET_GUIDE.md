# KMG AI — Hướng dẫn Tích hợp Dataset & Mở rộng Dữ liệu

## 1. Dataset v2 (`aiassist/datasets/v2/`)
Nguồn gốc: `KMG_AI_Dataset_v2_Music.zip` (đã bao gồm toàn bộ v1, không nhập riêng v1):
- `kmg_ai_scenario_bank.jsonl`: **317** kịch bản (117 v1 + 200 v2) và **94** biến thể câu hỏi (30 v1 + 64 v2).
- `kmg_ai_knowledge_candidates.jsonl`: **46** mục tri thức ứng viên (22 từ v1 `pending_owner_review`, 24 từ v2 `pending_music_mentor_review`), toàn bộ `is_active=false`.

## 2. Công cụ nhập dữ liệu (`import_ai_dataset`)
Lệnh:
```bash
python manage.py import_ai_dataset --dry-run
python manage.py import_ai_dataset
```
Cơ chế kiểm soát:
- **Schema & ID:** Kiểm tra `knowledge_id` duy nhất, độ dài `title <= 160`, `content` không rỗng, `audience` hợp lệ, `source_urls` là URL `http(s)` hợp lệ.
- **Chống trùng lặp:** Kiểm tra trùng `knowledge_id` và tiêu đề chuẩn hóa trong file và trong DB; chạy lại không tạo bản ghi trùng.
- **Bảo vệ bản ghi đã chỉnh sửa:** Không ghi đè các mục có `is_admin_edited=True` trừ khi truyền `--force-overwrite`.
- **Phê duyệt trước khi kích hoạt:** Mặc định nhập ở trạng thái `approval_status=PENDING`, `is_active=False`. Quản trị viên duyệt tại AI Studio hoặc truyền `--approve` khi đã kiểm duyệt xong.
- **Tách biệt tập đánh giá:** Không đưa toàn bộ câu hỏi trong `kmg_ai_scenario_bank.jsonl` trực tiếp vào RAG hay fine-tuning; giữ tập kiểm thử độc lập cho `evaluate_ai`.

## 3. Lộ trình mở rộng 2.000 kịch bản (Phase 11)
Phân bổ mục tiêu dài hạn: 600 âm nhạc, 400 nghiệp vụ CLB, 300 đời sống sinh viên, 300 tập luyện/biểu diễn, 200 hội thoại nhiều lượt, 200 bảo mật/ngoại lệ. Mọi kiến thức âm nhạc mới cần Ban Chuyên môn kiểm duyệt trước khi chuyển sang `APPROVED`.
