# Từ điển Thuật ngữ Giao diện Tiếng Việt — KMG Platform

Tài liệu chuẩn hoá ngôn ngữ hiển thị nhằm đảm bảo **100% trải nghiệm thuần Việt, tự nhiên cho sinh viên**, không pha tạp thuật ngữ kỹ thuật hay mã kiểm thử nội bộ.

## 1. Thuật ngữ tiếng Anh ĐƯỢC PHÉP giữ nguyên
- Viết tắt phổ biến toàn dân / kỹ thuật không thể thay: `AI`, `QR`, `OTP`, `PDF`, `Excel`, `email`, `CSV` *(kèm nhãn Việt hóa "Bảng tính Excel / Tệp CSV")*.
- Thuật ngữ âm nhạc & hoạt động CLB đặc trưng: `Guitar`, `Acoustic`, `Jam Session`, `Workshop`.
- Tên riêng / Tên thương hiệu: `KMG`, `KMA`, `VietQR`.

## 2. Bảng quy đổi bắt buộc cho UI (Sprint 1 -> Sprint 4)

| Thuật ngữ cũ / Sai chính tả | Thay thế chuẩn Tiếng Việt tự nhiên | Ghi chú |
|---|---|---|
| `modun AI`, `8 Modun` | `mô-đun AI`, `8 mô-đun trợ lý` | Sửa chính tả tiếng Việt |
| `KMG Internal Workspace` | `Không gian Nội bộ KMG` | Bỏ tiếng Anh tiêu đề |
| `LLMOps & AI Training Studio` | `Trung tâm Huấn luyện Trợ lý AI` | Dễ hiểu với BCN & BTC |
| `Eval Suite` / `Eval JSONL` | `Bộ kiểm định chất lượng` / `Tệp đánh giá JSONL` | Tự nhiên, rõ nghĩa |
| `RAG` *(trên UI thành viên)* | `Kho tri thức CLB` | Chỉ giữ `(RAG)` ở khu kỹ thuật nếu cần |
| `Stage Spec`, `FOH` | `Thông số sân khấu`, `Âm thanh hội trường (FOH)` | Hoặc giải thích rõ |
| `Cross-Department Read-Only` | `Chế độ Xem liên Ban (chỉ đọc)` | Thuần Việt hoàn toàn |
| `Guest` / `Role` *(trong tiêu đề)* | `Khách` / `Vai trò` | Không để `Nâng Role Khách` |
| `Dashboard` / `Analytics` | `Tổng quan` / `Thống kê & Phân tích` | Thống nhất toàn app |
| `D04 v1.1`, `Phase 5 · WF22`, `INV-03`, `INV-04`, `BE-07`, `PA-06`, `CM-03` | Ẩn mã spec khỏi tiêu đề/nút người dùng; diễn giải bằng quy tắc nghiệp vụ rõ ràng (vd: *"Cố vấn chỉ xem báo cáo"*) | Chỉ giữ mã quy tắc trong tài liệu `docs/` |
| `MANAGE`, `MEMBER`, `READ_ONLY` *(hiển thị thô)* | `Quản lý Ban`, `Thành viên`, `Chỉ xem` | Dùng `get_*_display` hoặc map nhãn |
