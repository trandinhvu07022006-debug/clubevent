# Cải tiến: từ "giao diện admin" thành website CLB hoàn chỉnh

Tài liệu ghi lại đợt cải tiến tháng 10/2026, xuất phát từ góp ý của các anh
khoá trên:

| Góp ý | Đã xử lý bằng |
|---|---|
| "Có trang nhất không? Vào link là ra ngay cái giống giao diện admin" | Trang chủ giới thiệu `/` + 3 trang theo đối tượng + menu/chân trang công khai |
| "Làm nền tảng giao task cho các ban CLB, gán task theo sự kiện, check tiến độ" | Mô hình **Ban** (Department), giao việc cho cả Ban, tự nhận việc, tiến độ theo Ban |
| "Tích hợp lên lịch nhắc cho đỡ quên" | Lệnh định kỳ tự **nhắc việc sắp đến hạn** (24h) và **báo việc quá hạn** |

---

## 1. Học hỏi từ các trang lớn

| Sản phẩm | Học được gì | Áp dụng ở đâu |
|---|---|---|
| **Luma, Eventbrite** | Trang chủ dẫn bằng sự kiện THẬT, không bằng chữ | Hero hiện sự kiện sắp tới thật; mục "Sự kiện sắp tới" lấy từ CSDL |
| **Slack, Notion** | Chia lối đi theo đối tượng: cá nhân / nhóm | Khối "Bạn là ai?" + trang *Dành cho thành viên* / *Dành cho Ban tổ chức* |
| **Notion, Slack** | Đã đăng nhập thì vào thẳng ứng dụng | `/` chuyển người đã đăng nhập sang `/tong-quan/` |
| **GitHub, Linear** | Trang "Home" cá nhân hoá: việc cần xử lý lên đầu | Trang **Tổng quan** với 2 không gian Cá nhân / Tổ chức |
| **Notion, Linear** | Danh sách "Bắt đầu" cho người mới | Khối *Bắt đầu*: hồ sơ, ảnh, email, vé đầu tiên, vào Ban |
| **Jira, Linear** | "Assign to me", tránh 2 người nhận trùng | Nút *Nhận việc* có khoá dòng (`select_for_update`) |
| **Linear, Stripe** | Menu dính, đổ bóng khi cuộn; chân trang nhiều cột | `partials/public_nav.html`, `partials/public_footer.html` |
| **Linear, Notion** | Trang đăng nhập 2 cột, nói rõ sau khi vào sẽ thấy gì | `accounts/login.html`, `accounts/register.html` |

Nguyên tắc giữ nguyên từ trước: **không CDN**, **không bịa số liệu** (dải con
số tự ẩn khi CSDL trống), **quyền kiểm ở server**, đúng cả theme sáng và tối.

## 2. Điều hướng theo cá nhân và tổ chức

```
Khách ──► /  (trang giới thiệu)
          ├─ Giới thiệu            /gioi-thieu/   (Ban Quản trị, thành tích, 2 Ban)
          ├─ Tuyển thành viên      /tuyen-thanh-vien/   (nhãn "Đang mở" khi có đợt)
          ├─ Hướng dẫn ▾  Tham gia sự kiện /danh-cho-thanh-vien/
          │               Dành cho Ban tổ chức /danh-cho-ban-to-chuc/
          └─ Sự kiện /sukien/, Lịch /lich/, Đăng nhập, Tạo tài khoản (= Khách)

Đăng nhập ──► /tong-quan/
          ├─ Không gian CÁ NHÂN (?space=me) - mọi người
          │    vé sắp tới · đơn chờ thanh toán · sự kiện chờ đánh giá
          │    gợi ý sự kiện · danh sách Bắt đầu
          └─ Không gian TỔ CHỨC (?space=org) - BTC trở lên (mặc định cho họ)
               việc của tôi · quá hạn · sắp đến hạn · việc Ban chờ nhận
               Ban của tôi · nút mở check-in nếu hôm nay có sự kiện
               + Trưởng BTC: sự kiện đang chạy, tiến độ mọi Ban
               + Admin: tài khoản theo vai trò, nhật ký gần đây
```

Sidebar chia nhóm **Khám phá / Cá nhân / Tổ chức / Quản trị**; mỗi vai trò chỉ
thấy nhóm của mình. Thành viên tự gõ `?space=org` vẫn chỉ nhận không gian cá
nhân (có test).

## 3. Các Ban (đơn vị tổ chức)

- Model `organizing.Department`: tên, đường dẫn, icon, mô tả, **Trưởng ban**,
  thành viên (chỉ BTC trở lên).
- `Task.department`: việc có thể giao cho **một người**, **cả Ban** (để trống
  người nhận) hoặc cả hai.
- **Trưởng ban** (một Thành viên BTC được chọn làm trưởng) được giao việc
  trong Ban mình, cho người trong Ban mình; không cần là Trưởng BTC.
- Trang Ban: tiến độ %, việc chờ nhận, việc quá hạn, **mỗi người đang giữ bao
  nhiêu việc** (để chia đều tay).
- Xoá Ban không mất việc (chỉ bỏ gắn Ban).

## 4. Nhắc hạn công việc

`organizing.services.send_task_reminders()`, chạy trong `run_periodic` mỗi 15 phút:

- Việc đến hạn trong 24h → nhắc người phụ trách (việc chưa ai nhận → nhắc cả Ban).
- Việc quá hạn → báo người phụ trách **và người giao việc**.
- Mỗi loại nhắc tối đa 1 lần (đánh dấu `due_reminded_at` / `overdue_reminded_at`
  trong transaction có khoá dòng). **Đổi deadline thì được nhắc lại** theo hạn mới.
- Bỏ qua việc đã xong và việc của sự kiện đã huỷ / đã diễn ra.

## 5. Tuyển thành viên theo đợt (thay cho "đăng ký là thành viên")

Góp ý: cho đăng ký online là thành viên thì danh sách bị loãng. Cách làm mới:

| Vai trò | Có được bằng cách | Làm được |
|---|---|---|
| **Khách** | Tự tạo tài khoản online | Đặt vé, check-in, đánh giá, **nộp đơn ứng tuyển** |
| **Thành viên** | Đơn ứng tuyển **được nhận** | Thuộc một Ban, xem hoạt động của Ban |
| TV BTC trở lên | Ban Quản trị nâng vai trò | Như cũ |

- Ban Quản trị (Trưởng BTC/Admin) **mở đợt tuyển** (thời gian, Ban nhận đơn, thông tin casting).
- Khách nộp đơn: chọn **Ban Chuyên môn** hoặc **Ban Truyền thông & Sự kiện**, nhạc cụ / thế mạnh,
  trình độ, link video/sản phẩm, lý do. Mỗi đợt 1 đơn, rút đơn được khi chưa có kết quả.
- Duyệt: *Chờ duyệt → Hẹn casting/phỏng vấn → Đã nhận / Chưa phù hợp*. Trưởng ban chỉ duyệt đơn
  vào Ban mình. Mỗi bước gửi thông báo + email cho ứng viên.
- **Đã nhận** ⇒ Khách tự lên Thành viên và vào Ban đã chọn (không hạ vai trò người đã cao hơn).

## 6. Nội dung giới thiệu KMG

- Văn bản, tiêu chí, thành tích: `pages/club_content.py` (chắt lọc từ bài giới thiệu chính thức,
  không thêm số liệu ngoài nguồn).
- Ban Quản trị nhiệm kỳ 2026 - 2027: bảng `pages.ClubOfficer`, nạp sẵn bằng migration;
  **tải ảnh** trong trang quản trị Django (`/admin/` → Ban Quản trị). Chưa có ảnh thì hiện chữ cái đầu.
- 2 Ban: **Truyền thông & Sự kiện** (Trưởng ban Phan Tiến Đạt) và **Chuyên môn** (Trưởng ban Lưu Nhật Linh).

## 7. Cấu hình thông tin CLB

Sửa trong `.env` (hoặc `config/settings.py` → `CLUB_INFO`):

```
CLUB_NAME=KMG Club
CLUB_TAGLINE=...
CLUB_INTRO=...
CLUB_EMAIL=...
CLUB_FACEBOOK=https://facebook.com/...
CLUB_ADDRESS=...
```

Để trống mục nào thì mục đó tự ẩn trên trang.

## 8. Kiểm thử

- `pages/tests.py` (23 test): khách thấy website, người đăng nhập vào Tổng quan,
  đúng không gian theo vai trò, sidebar đúng nhóm, chuyển trang sau đăng nhập/đăng xuất.
- `organizing/test_departments.py` (29 test): quyền với Ban, tự nhận việc (kể
  cả 2 người nhận cùng lúc), Trưởng ban giao việc đúng phạm vi, chặn chèn mã qua
  ô icon, số liệu tiến độ, nhắc hạn / quá hạn / không nhắc trùng / nhắc lại khi đổi hạn.

- `recruitment/tests.py` (23 test): đăng ký online chỉ là Khách, nộp/rút đơn, đợt đóng,
  Ban không nhận đơn, duyệt → lên Thành viên + vào Ban, Trưởng ban chỉ duyệt Ban mình, menu.

Tổng: **314 test (239 cũ + 75 mới), tất cả đạt.**

## 9. Kịch bản demo gợi ý (7 phút)

1. Mở `/` khi chưa đăng nhập → trang giới thiệu, bấm *Dành cho Ban tổ chức* → bảng vai trò.
2. Đăng nhập `thanhvien` → vào thẳng **Tổng quan / Cá nhân**: đơn chờ thanh toán, bước Bắt đầu.
3. Đăng nhập `btc2` → **Tổng quan / Tổ chức**: badge *Các Ban* có việc chờ nhận
   → vào Ban Truyền thông → bấm **Nhận việc**.
4. Đăng nhập `btc1` (Trưởng Ban Hậu cần) → *Giao việc* chỉ chọn được Ban Hậu cần.
5. Chạy `python manage.py run_periodic` → `btc1`/`btc2` nhận thông báo "Sắp đến hạn: Mượn thêm 2 micro".
6. Đăng nhập `admin` → Tổng quan có tiến độ mọi Ban, tài khoản theo vai trò, nhật ký.
7. Đăng nhập `khach` → Tổng quan hiện "Trở thành thành viên: Chờ duyệt". Đăng nhập `btc1`
   (Trưởng ban Chuyên môn) → *Tuyển thành viên* → duyệt đơn của Phan Gia Huy → **Đã nhận**
   → đăng nhập lại `khach`: vai trò đã là Thành viên, có mục *Ban của tôi*.
