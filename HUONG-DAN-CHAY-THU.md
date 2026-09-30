# Hướng dẫn chạy thử và test KMG Club

Cảm ơn bạn đã giúp test! Làm theo 3 bước dưới đây, **không cần biết lập trình**
và **không cần cài MySQL**.

## Bước 1. Cài Python (chỉ làm một lần)

- Tải **Python 3.10 trở lên** tại <https://www.python.org/downloads/>.
- **Windows:** khi cài, nhớ tick ô **"Add python.exe to PATH"** ở màn hình đầu tiên.
- Máy đã có Python rồi thì bỏ qua bước này.

## Bước 2. Tải dự án về

**Cách dễ nhất (không cần Git):**
1. Mở <https://github.com/trandinhvu07022006-debug/clubevent>
2. Bấm nút xanh **Code** → **Download ZIP**.
3. Giải nén ra một thư mục, ví dụ `D:\clubevent`.

**Nếu đã có Git:**
```
git clone https://github.com/trandinhvu07022006-debug/clubevent.git
```

## Bước 3. Chạy

- **Windows:** vào thư mục vừa giải nén, **nhấp đúp `chay-thu.bat`**.
- **macOS / Linux:** mở Terminal tại thư mục đó, gõ `bash chay-thu.sh`.

Lần đầu mất vài phút để cài thư viện (cần có mạng). Xong trình duyệt tự mở
<http://127.0.0.1:8000>. Các lần sau chạy gần như ngay lập tức.

**Giữ nguyên cửa sổ đen** trong lúc dùng web; đóng nó là tắt web.

> Cổng 8000 đang bị chiếm? Mở cmd tại thư mục dự án, gõ `set PORT=8001`
> rồi `chay-thu.bat` (macOS/Linux: `PORT=8001 bash chay-thu.sh`).

## Tài khoản để thử

Mật khẩu chung: **`demo1234`**

| Tài khoản | Vai trò | Nên thử gì |
|---|---|---|
| `thanhvien` | Thành viên | Đặt vé, vào danh sách chờ, xem vé + mã QR, thông báo, giấy chứng nhận |
| `thanhvien2` | Thành viên | Đang chờ vé ở sự kiện "Giao lưu Guitar liên CLB" |
| `btc1`, `btc2` | Thành viên BTC | Xác nhận thanh toán, check-in bằng mã vé, cập nhật việc được giao |
| `truongbtc` | Trưởng BTC | Tạo sự kiện, loại vé, giao việc, ngân sách, thống kê, huỷ sự kiện |
| `admin` | Admin (Ban chủ nhiệm) | Quản lý tài khoản, gán vai trò, khoá tài khoản, nhật ký thao tác |

Hoặc tự **đăng ký tài khoản mới** để thử như một người dùng lạ.

## Gợi ý kịch bản test (khoảng 15 phút)

1. `thanhvien`: vào sự kiện **Acoustic Night**, đặt 2 **vé khách mời** (có phí)
   → vào **Vé của tôi** xem khối "Cần thanh toán" và nội dung chuyển khoản `KMG …`.
2. Thử đặt thêm cho vượt 4 vé → phải bị chặn với thông báo rõ ràng.
3. Vào sự kiện **Giao lưu Guitar liên CLB (đã hết vé)** → **Vào danh sách chờ**.
4. Đăng xuất, đăng nhập `btc1` → **Xác nhận TT** → dán nội dung `KMG …` vào ô
   tìm kiếm → **Đã nhận tiền**.
5. `btc1` mở **Check-in** của Acoustic Night → nhập mã vé của `thanhvien`
   (xem ở "Vé của tôi") → xanh "HỢP LỆ"; nhập lại lần nữa → vàng "ĐÃ SỬ DỤNG".
6. `truongbtc` → **Giao việc** cho `admin` một việc "Gấp" → đăng nhập `admin`,
   bấm **chuông** góc trên phải xem thông báo.
7. `thanhvien` → **Hồ sơ** → lịch sử tham gia → **Chứng nhận** sự kiện Minishow.
8. Thử trên **điện thoại** (xem mục dưới) và thử nút đổi **giao diện sáng/tối**.

Muốn đưa dữ liệu về như ban đầu: tắt cửa sổ đen, xoá file `db.sqlite3` rồi chạy lại.

## Thử trên điện thoại (cùng mạng Wi-Fi với máy tính)

1. Trên máy tính, mở cmd tại thư mục dự án, chạy:
   `venv\Scripts\python.exe manage.py runserver 0.0.0.0:8000`
2. Xem IP máy tính: gõ `ipconfig`, lấy dòng **IPv4 Address** (vd `192.168.1.5`).
3. Trên điện thoại mở `http://192.168.1.5:8000`.

Lưu ý: **quét QR bằng camera** cần HTTPS nên sẽ không bật được theo cách này —
dùng ô nhập mã vé thay thế. Đây là giới hạn của trình duyệt, không phải lỗi.

## Báo lỗi

Gặp lỗi hay chỗ khó dùng, hãy tạo **Issue** tại
<https://github.com/trandinhvu07022006-debug/clubevent/issues> (cần tài khoản
GitHub), hoặc nhắn trực tiếp cho nhóm. Ghi giúp:

- **Tài khoản** đang dùng và **trang** (link trên thanh địa chỉ).
- **Các bước** đã làm.
- **Mong đợi** điều gì — **thực tế** xảy ra gì.
- **Ảnh chụp màn hình**; nếu cửa sổ đen có chữ đỏ báo lỗi, chụp cả phần đó.
- Máy và trình duyệt (vd Windows 10 + Chrome, iPhone + Safari).

## Gặp sự cố khi cài

| Hiện tượng | Cách xử lý |
|---|---|
| `Chua cai Python` | Cài Python (bước 1), nhớ tick "Add python.exe to PATH", mở lại cửa sổ |
| `Cai thu vien that bai` | Kiểm tra mạng rồi chạy lại; mạng trường chặn thì dùng 4G |
| Trình duyệt báo không kết nối được | Chờ cửa sổ đen hiện dòng `Starting development server` rồi tải lại trang |
| `Error: That port is already in use` | Chạy với cổng khác (xem ghi chú ở bước 3) |
| Windows chặn file `.bat` (SmartScreen) | Bấm **More info** → **Run anyway** |
