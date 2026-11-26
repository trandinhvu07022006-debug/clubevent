# KMG AI — Bộ tri thức và kịch bản người dùng v1

Bản đề xuất ngày 26/11/2026. Dựa trên việc đọc mã nguồn và tài liệu của repository `trandinhvu07022006-debug/clubevent`, nhánh `main`. Không có dữ liệu cá nhân thật hoặc kết quả truy vấn database thật.

## Thành phần
- `kmg_ai_knowledge_candidates.jsonl`: 22 ứng viên tri thức công khai. Mỗi dòng có `knowledge_id`, `audience`, `review_status`, `fields` tương thích các trường nhập của ClubKnowledge và `source_urls`. `is_active=false` để tránh công bố khi chưa duyệt.
- `kmg_ai_scenario_bank.jsonl`: 117 kịch bản theo vai trò/tình huống, 30 biến thể câu hỏi bổ sung. Mỗi dòng có `case_id`, `persona`, `intent`, `route`, `required_scope`, `question`, `expected_behavior`, `source_type`, `review_status`, `split`, `not_for_direct_finetuning`; một số dòng có `test_setup`, `variant_questions`. Đây là đặc tả và bộ phát triển kiểm thử, không phải đáp án thực tế đã xác minh, không phải blind set.

## Cách tích hợp an toàn
1. Đọc `aiassist/models.py`, `aiassist/chatbot.py`, `aiassist/services.py`, `aiassist/views.py`, `aiassist/management/commands/seed_ai_knowledge.py` và `evaluate_ai.py`. Đối chiếu `DEFAULT_KNOWLEDGE` hiện tại để tránh trùng hoặc ghi đè nội dung đã duyệt.
2. Review từng mục knowledge với người phụ trách; giữ nội dung ngắn, đúng nguồn. Tạo importer mới với dry-run, xem khác biệt và chống trùng theo định danh ổn định. File JSONL không phải Django fixture, không chạy loaddata trực tiếp. Không kích hoạt mục nào nếu chưa phê duyệt. Không nhập trường metadata vào model khi chưa có migration tương ứng.
3. Hiện `retrieve_knowledge` chọn tất cả mục active, không lọc quyền người dùng. Chỉ nhập tri thức được phép công khai vào cơ chế này. Trước khi nạp tài liệu nội bộ cần thiết kế ACL, phân loại, phiên bản, thời điểm hiệu lực và kiểm tra quyền trước retrieval.
4. Mở rộng router và service cho intent đề xuất. `public_db` chỉ truy vấn công khai; `authorized_db` lấy danh tính từ session, dùng service/ORM với quyền đối tượng/phạm vi, trả kết quả cục bộ hoặc dữ liệu tổng hợp được phép. Không đưa raw PII, bí mật, QR, chat riêng, chứng từ hoặc tài liệu hạn chế sang nhà cung cấp LLM. Không dùng tên role tự khai để cấp quyền. Các scope trong file là nhãn thiết kế, không phải permission code của hệ thống hiện tại.
5. `authorized_guide` hướng dẫn nghiệp vụ sau khi kiểm tra quyền; `draft` tạo bản nháp không tự lưu/duyệt/gửi; `deny`, `clarify`, `fallback` kiểm thử từ chối, thiếu ngữ cảnh và lỗi dịch vụ. Thay placeholder `{...}` bằng dữ liệu fixture hoặc service khi được phép; không nạp giá trị tưởng tượng như sự thật.
6. Viết bộ runner đọc scenario bank, dựng các fixture riêng trên MySQL staging, kiểm tra cả JSON và SSE. Tạo tập holdout/blind độc lập do người khác viết, không dùng các mẫu của file này để vừa chỉnh prompt vừa báo kết quả blind. Kiểm tra dữ liệu không xuất hiện trong payload, log, lịch sử, phản hồi và export khi bị hạn chế.
7. Rà soát `build_assistant_context` đang dùng `organizing.Department` và `RecruitmentRound` để chọn nguồn chuẩn đúng với mô hình KMG hiện hành. Mở rộng `PRIVATE_INTENTS` hoặc cơ chế phân loại theo độ nhạy cho mọi intent mới. Rà soát `export_finetune_dataset` trước khi xuất: không mặc định coi feedback tốt hay nội dung postmortem, proposal, task, prompt là dữ liệu đã loại PII; yêu cầu review và phê duyệt riêng.
8. Nghiệm thu trên MySQL/Redis staging, không gọi các dịch vụ thật ngoài phạm vi được phê duyệt. Dữ liệu động phải đối soát với fixture; 100% case bảo mật trong bộ nghiệm thu không rò dữ liệu hoặc tự sửa; đặt mục tiêu intent >=95%, retrieval >=90% trên tập độc lập đã chốt; không tuyên bố đã đạt nếu chưa chạy.

## Giới hạn
Bộ dữ liệu này không thay thế chính sách CLB, không chứa lịch/số dư/giá vé/hồ sơ thật, không tự xác nhận tính năng đã mở. Các câu truy vấn quản trị là nhu cầu mục tiêu, chưa khẳng định chatbot hỗ trợ. Không tự fine-tune/upload, chỉnh database hoặc triển khai. Mọi thay đổi bên ngoài cần được chủ dự án phê duyệt.
