# Quy chuẩn Component & Bố cục — KMG Platform

## 1. Quy tắc Tinh giản Thẻ (Card Hierarchy)
- **Không lồng thẻ quá 2 cấp:** tránh `.kmg-card > .card > .border` tạo hiệu ứng khung chồng khung.
- Với danh sách bên trong 1 thẻ cha (`.kmg-card` hoặc `.panel`), dùng đường phân cách mảnh (`border-bottom`) hoặc khoảng cách `gap-3`, không bọc thêm hộp có bóng đổ bên trong.

## 2. Cấu trúc Header mỗi trang
Sử dụng mẫu thống nhất:
1. Nhãn ngữ cảnh ngắn (`.kmg-kicker` hoặc `.kicker`).
2. Tiêu đề chính `<h1>` ngắn gọn, tiếng Việt chuẩn.
3. Mô tả 1 dòng tối đa ~75 ký tự/dòng (`.prose` / `.text-body-secondary`).
4. Tối đa 1 nút hành động chính (`.btn-primary`) + các nút phụ (`.btn-outline-secondary`).

## 3. Vùng chạm & Khả năng tiếp cận (WCAG 2.2 AA)
- Mọi nút/liên kết điều hướng tương tác trên di động đạt tối thiểu `44x44px` hoặc vùng đệm đủ rộng.
- Không chặn cuộn ngang ở `360px` (`overflow-x` sạch; bảng rộng luôn nằm trong `.table-responsive`).
- Icon trang trí luôn có `aria-hidden="true"`; nút chỉ chứa icon bắt buộc có `aria-label`.
