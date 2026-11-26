# KMG AI Dataset v2 — Âm nhạc và đời sống sinh viên

Bản mở rộng của KMG AI Dataset v1. Giữ nguyên 117 kịch bản và 22 mục tri thức v1, bổ sung **200 câu hỏi mới**, 64 biến thể (48 biến thể bỏ dấu tự động; phần còn lại viết tay) và **24 ứng viên tri thức phổ thông**. Tổng 317 kịch bản, 94 biến thể, 46 ứng viên tri thức. Đây là tập phát triển và kịch bản kiểm thử, chưa phải dữ liệu đã được nghiệm thu hay fine-tuning.

## Tệp bàn giao

- `kmg_ai_scenario_bank.jsonl`: toàn bộ 317 kịch bản (v1 + v2).
- `kmg_ai_knowledge_candidates.jsonl`: toàn bộ 46 mục tri thức ứng viên.
- `kmg_ai_music_scenarios_delta.jsonl`: chỉ 200 kịch bản mới.
- `kmg_ai_music_knowledge_delta.jsonl`: chỉ 24 mục tri thức mới, tất cả `is_active=false`.
- `V1_README.md`: hướng dẫn v1 giữ nguyên.
- `README.md`: hướng dẫn này.
- `manifest.json`: thống kê và SHA-256 của các tệp JSONL.

**Chỉ chọn bộ đầy đủ hoặc bộ delta khi import; không import cả hai.** JSONL UTF-8, mỗi dòng là một object. Không phải Django fixture. Không nạp thẳng bằng `loaddata`. `knowledge_id`, `case_id`, `intent`, `required_scope`, `persona`, `topic` là nhãn dữ liệu/đề xuất, không phải quyền hoặc mã intent đã tồn tại. Mã intent theo câu hỏi chỉ là định danh ứng viên; cần gom thành nhóm intent thực tế và ánh xạ trước khi viết router, không tạo 200 handler riêng.

## Phân nhóm câu hỏi mới

| Nhóm | Số câu |
|---|---:|
| Gia nhập, định hướng và casting | 16 |
| Đời sống sinh viên và học hỏi | 16 |
| Guitar từ cơ bản tới đệm hát | 16 |
| Thanh nhạc và luyện giọng | 16 |
| Piano, keyboard, bass, trống và ukulele | 16 |
| Nhạc lý, nhịp, nghe và hòa âm | 16 |
| Tập band, phối hợp và hòa tấu | 16 |
| Biểu diễn, sân khấu và sự cố thường gặp | 16 |
| Nhạc cụ, âm thanh và kỹ thuật | 16 |
| Cover, sáng tác, thu âm và chia sẻ âm nhạc | 16 |
| Hòa nhập, văn hóa và giao tiếp CLB | 16 |
| Sinh hoạt, lịch, tài nguyên và hoạt động thật của KMG | 16 |
| Câu hỏi dễ nhầm, nhiều ý và thiếu dữ liệu | 8 |

## Hướng dẫn triển khai

1. Đọc `V1_README.md` và đối chiếu mã nguồn hiện hành. Tạo importer dry-run, khóa định danh, validate kiểu và độ dài, so sánh trước khi ghi. Không ghi đè mục đã duyệt. Bản v2 không tạo model/migration hoặc tự triển khai.
2. Các mục tri thức mới là kiến thức âm nhạc phổ thông/đề xuất hướng dẫn, chưa dẫn tài liệu chuyên môn đã duyệt. Người phụ trách Ban Chuyên môn hoặc kỹ thuật cần rà soát trước khi kích hoạt; rút gọn và đặt từ khóa theo cách hỏi tự nhiên. Không lấy giả định về học phí, phòng tập, giờ tập, nhạc cụ mượn hay lịch casting làm sự thật KMG. Với câu liên quan sức khỏe, tránh chẩn đoán hoặc ép người dùng luyện tiếp khi đau.
3. `general_coaching` là route đề xuất mới dành cho tư vấn học nhạc không cần truy vấn dữ liệu riêng. `public_kb` đọc tri thức công khai đã duyệt; `public_db` tra dữ liệu công khai. `authorized_db` chỉ truy vấn sau khi xác thực, kiểm tra quyền, và xử lý cục bộ; nếu chức năng/field chưa tồn tại thì nói rõ chưa hỗ trợ. `clarify`, `deny`, `fallback` phải được test riêng. Không đưa dữ liệu nội bộ vào `ClubKnowledge` đang truy xuất toàn bộ active; bổ sung ACL trước khi hỗ trợ RAG nội bộ.
4. Câu hỏi trong `expected_behavior` mô tả hành vi/đáp án mong đợi, không phải câu trả lời của AI đã chạy. Không sử dụng file kịch bản làm knowledge base trực tiếp. Câu hỏi chung về nhạc cần trả lời được bằng kiến thức đã review, hoặc hỏi thêm ngữ cảnh khi không đủ dữ liệu. Câu hỏi KMG phải dựa trên tài liệu được công bố hoặc MySQL. Không để AI tự thực hiện thay đổi nghiệp vụ; chỉ dẫn đúng kênh. Tôn trọng quyền tác giả và đồng ý khi chia sẻ bản ghi.
5. Dùng cả câu hỏi chuẩn và biến thể có dấu/không dấu/viết tắt trong dev. Tách holdout/blind độc lập do người khác viết, theo nhóm câu cùng ý nghĩa để tránh rò tập kiểm thử. Các biến thể sinh bằng bỏ dấu không phải câu hỏi độc lập.
6. Kiểm thử JSON/SSE, câu hỏi nhiều ý, thiếu ngữ cảnh, hỏi sai Ban, khách chưa đăng nhập, dữ liệu thay đổi và lỗi dịch vụ. Mở rộng phân loại độ nhạy; không ghi câu trả lời riêng hoặc gửi thông tin cá nhân lên LLM, không xuất dữ liệu nhạy cảm qua fine-tune. Không cho LLM chạy SQL tự do.
7. Nghiệm thu trên MySQL/Redis staging và có người chuyên môn xác nhận nội dung giáo dục; đo độ đúng ý định, grounding, quyền, độ hữu ích cho người mới và độ trễ. Tất cả các ca kiểm thử vượt quyền phải không rò rỉ thông tin. Không dùng dữ liệu này để tự đánh giá blind, không báo test pass nếu chưa chạy.

## Giới hạn

Không có dữ liệu người dùng thật, lịch tập thật, giá phí, chính sách mới hoặc thông tin thiết bị thực tế. Quy mô và câu hỏi dựa trên nhu cầu giả lập CLB âm nhạc sinh viên. Kiến thức mới cần review chuyên môn; bộ dữ liệu chưa được nhập vào KMG, chưa chạy với chatbot, chưa test truy vấn MySQL hoặc gọi LLM. Không gửi hoặc fine-tune tự động.
