# Tổng hợp chức năng, điểm mạnh và chuẩn bị demo — KMG Club

Tài liệu dùng cho 2 việc: **viết báo cáo** (phần 1, 2 đưa vào chương 3 và
chương 8) và **chuẩn bị buổi demo** (phần 3). Mọi con số ở đây đều đo được
trên dự án hiện tại, kèm cách kiểm lại.

---

## Phần 1. Danh sách chức năng

5 vai trò: **Khách** (chưa đăng nhập) · **Thành viên** · **Thành viên BTC** ·
**Trưởng BTC** · **Admin (Ban chủ nhiệm)**. Vai trò cao hơn có mọi quyền của
vai trò thấp hơn.

### M1. Tài khoản và phân quyền

| Mã | Chức năng | Ai dùng |
|---|---|---|
| F1.1 | Đăng ký (MSSV, email không trùng), đăng nhập, đăng xuất | Khách |
| F1.3 | Hồ sơ cá nhân, ảnh đại diện (tự thu nhỏ), đổi mật khẩu | Mọi người |
| F1.4 | Quên mật khẩu qua email (link sống 2 giờ, tối đa 5 lần/giờ) | Mọi người |
| F1.5 | Quản lý tài khoản: tìm kiếm, gán vai trò, khoá / mở khoá | Admin |
| F0.1 | Phân quyền kiểm tra ở server — gõ thẳng URL vượt quyền bị chặn 403 | Hệ thống |
| F0.2 | Nhật ký thao tác (gán vai trò, xác nhận thanh toán, check-in, huỷ sự kiện…) | Admin |

### M2. Sự kiện

| Mã | Chức năng | Ai dùng |
|---|---|---|
| F2.1 | Tạo / sửa sự kiện: danh mục, giờ bắt đầu – kết thúc, địa điểm, sức chứa, ảnh bìa, ngân sách dự kiến | Trưởng BTC |
| F2.2 | Nhiều loại vé cho một sự kiện (miễn phí / có phí, số lượng riêng) | Trưởng BTC |
| F2.4 | Máy trạng thái: Đang chuẩn bị → Mở đăng ký → Đóng đăng ký → Đã diễn ra / Đã huỷ | Trưởng BTC |
| F2.3 | Huỷ sự kiện: huỷ mọi vé và lượt chờ, báo mỗi người một lần, nhắc hoàn tiền | Trưởng BTC |
| F2.5 | Danh sách sự kiện: lọc danh mục + trạng thái + sắp tới/đã qua + tìm kiếm (kết hợp được) | Mọi người |
| F2.6 | Lịch sự kiện theo tháng | Mọi người |
| F7.4 | Thêm vào lịch điện thoại / Google Calendar (file `.ics`) | Mọi người |
| — | Chia sẻ link sự kiện; khối "Sự kiện sắp tới của bạn" ở trang chủ | Mọi người |

### M3. Công việc Ban tổ chức

| Mã | Chức năng | Ai dùng |
|---|---|---|
| F3.1 | Bảng công việc Kanban theo sự kiện, % tiến độ, việc quá hạn tô đỏ | Trưởng BTC |
| F3.6 | **Giao việc**: cho sự kiện hoặc **việc chung của CLB**, giao cho bất kỳ ai trong BTC **kể cả Ban chủ nhiệm**, có mức ưu tiên (Thấp → Gấp) | Trưởng BTC, Admin |
| F3.3 | Việc của tôi: lọc trạng thái có số đếm, việc gấp lên đầu, cập nhật tiến độ | Thành viên BTC trở lên |
| F3.7 | "Tôi đã giao": theo dõi tiến độ việc mình giao, sửa / giao lại / xoá | Trưởng BTC, Admin |
| AI | AI gợi ý danh sách công việc cho sự kiện (có danh sách mặc định khi AI lỗi) | Trưởng BTC |
| NS | Ngân sách: ghi khoản chi theo hạng mục + ảnh hoá đơn, tự tính thu – chi – lãi/lỗ, xuất CSV | Trưởng BTC |

### M4. Đăng ký vé và thanh toán

| Mã | Chức năng | Ai dùng |
|---|---|---|
| F4.1 | Đặt vé, tối đa 4 vé/người/sự kiện, **chống bán vượt chỗ khi nhiều người đặt cùng lúc** | Thành viên |
| F4.2 | Vé của tôi: mã QR, tab Sắp tới / Đã qua, in vé – lưu PDF | Thành viên |
| F4.3 | Huỷ vé trước giờ diễn ra 24h, chỗ trả lại | Thành viên |
| F4.7 | **Mã giao dịch nhóm + VietQR**: đặt nhiều vé chỉ chuyển khoản 1 lần, quét QR bằng app ngân hàng là tự điền số tiền và nội dung | Thành viên |
| F4.4 | Xác nhận thanh toán **theo nhóm**, tìm bằng cách dán nội dung chuyển khoản | Thành viên BTC |
| F4.5 | Vé quá hạn thanh toán tự huỷ (hạn = min(24h, giờ diễn ra)) | Hệ thống |
| F4.8 | **Danh sách chờ**: hết vé thì xếp hàng; có người huỷ → **tự động cấp vé** cho người đầu hàng | Thành viên |
| F4.6 | Danh sách người tham gia + danh sách chờ, xuất CSV (Excel mở được) | Trưởng BTC |

### M5. Check-in

| Mã | Chức năng | Ai dùng |
|---|---|---|
| F5.1 | Check-in bằng mã vé: 3 kết quả Hợp lệ (xanh) / Đã sử dụng (vàng) / Không hợp lệ (đỏ) | Thành viên BTC |
| F5.3 | Quét QR bằng camera điện thoại, bíp + rung, chống quét trùng | Thành viên BTC |
| F5.4 | Bảng điểm danh cập nhật mỗi 5 giây: tổng, theo loại vé, người vừa vào cổng | Thành viên BTC |

### M6. Phản hồi và thống kê

| Mã | Chức năng | Ai dùng |
|---|---|---|
| F6.1 | Gửi đánh giá 1–5 sao — chỉ người đã check-in, trong 7 ngày, mỗi người 1 lần | Thành viên |
| F6.2 | AI tóm tắt phản hồi: điểm khen, điểm chê, đề xuất (không gửi tên/MSSV cho AI) | Trưởng BTC |
| F6.3 | Thống kê từng sự kiện + biểu đồ (vé theo loại, phân bố số sao) | Trưởng BTC |
| F6.4 | Thống kê tổng hợp nhiều sự kiện: tỉ lệ check-in, doanh thu, điểm đánh giá | Trưởng BTC |

### M7. Thông báo

| Mã | Chức năng | Ai dùng |
|---|---|---|
| F7.3 | Chuông thông báo trong app (số chưa đọc, 5 tin mới nhất, đọc hết) | Mọi người |
| F7.1 | Thông báo + email khi: đặt vé, được xác nhận, vé hết hạn, sự kiện bị huỷ, được cấp vé từ danh sách chờ, được giao việc | Hệ thống |
| F7.2 | Nhắc lịch 24h trước sự kiện | Hệ thống |

### M8. Ghi nhận tham gia

| Mã | Chức năng | Ai dùng |
|---|---|---|
| F8.1 | Lịch sử tham gia trên hồ sơ (số sự kiện đã dự, số vé, số tiền đã chi) | Thành viên |
| F8.2 | **Giấy chứng nhận tham gia** in A4 có QR; **trang xác thực công khai** (ai quét cũng kiểm được thật/giả, MSSV được che) | Thành viên, Khách |

### Tiện ích chung

- **Trợ lý tra cứu** (chat): trả lời bằng cách tra thẳng dữ liệu (còn vé không,
  vé của tôi, việc của tôi…) nên không bịa; câu hỏi lạ mới hỏi AI, có giới hạn lượt.
- Giao diện **sáng / tối**, dùng tốt trên **điện thoại**, chạy được **khi mất
  mạng ngoài** (thư viện giao diện để sẵn trong dự án, không dùng CDN).
- Lệnh quản trị: `seed_demo` (dữ liệu demo), `run_periodic` (tác vụ định kỳ
  15 phút), `release_expired`, `send_reminders`.

---

## Phần 2. Điểm mạnh — kèm bằng chứng

Khi trình bày hoặc viết báo cáo, **mỗi điểm mạnh đi kèm một bằng chứng**.

| # | Điểm mạnh | Bằng chứng / cách chứng minh |
|---|---|---|
| 1 | **Giải quyết đúng vấn đề thật của CLB**: trọn vòng đời sự kiện từ chuẩn bị (giao việc) → bán vé → check-in → phản hồi → thống kê → chứng nhận, thay cho Google Form + Excel + Zalo rời rạc | Phần 1; kịch bản demo đi hết vòng đời trong 10 phút |
| 2 | **Không bán vượt chỗ khi nhiều người đặt cùng lúc** (race condition) | Demo 2 trình duyệt cùng đặt chỗ cuối; đo 10/10 lần đúng; `RaceConditionTests` |
| 3 | **Kiểm thử bài bản, có số liệu** | **233 test tự động** (100% pass), **độ phủ code 87%**, kiểm thử theo vai người dùng **69/69 bước**, mã test khớp bảng test case / RTM |
| 4 | **Bảo mật được kiểm chứng**, không chỉ ẩn nút | Test: vượt quyền → 403, xem dữ liệu người khác → 404, thao tác qua link giả → 405, chống XSS, chống chuyển hướng sang trang lạ, tài khoản bị khoá bị đăng xuất ngay |
| 5 | **Kiến trúc rõ ràng** 3 tầng View – Service – Model, 4 máy trạng thái (sự kiện, vé, lượt chờ, công việc) | `*/services.py`; `ALLOWED_TRANSITIONS` trong `events/models.py` |
| 6 | **Tự động hoá giảm việc tay cho BTC**: tự huỷ vé quá hạn, tự cấp vé từ danh sách chờ, tự nhắc lịch, xác nhận thanh toán theo nhóm | `run_periodic`; demo danh sách chờ |
| 7 | **Thanh toán thực tế cho sinh viên Việt Nam**: VietQR chuẩn EMVCo sinh offline, nội dung chuyển khoản ngắn gọn để đối chiếu sao kê | `registrations/vietqr.py`; test CRC chuẩn `29B1` |
| 8 | **Dùng AI có kiểm soát**: AI chỉ gợi ý, con người quyết định; AI lỗi thì hệ thống vẫn chạy; không gửi dữ liệu cá nhân cho AI | Test `SuggestTasksFallbackTests`; demo tắt mạng vẫn chạy |
| 9 | **Chạy được ở điều kiện khó**: mất mạng ngoài vẫn đủ giao diện; chỉ cần SQLite; cài đặt 1 cú nhấp đúp | `static/vendor/`; `chay-thu.bat` |
| 10 | **Hiệu năng**: không trang nào bị N+1 query (5–21 truy vấn cố định mỗi trang); ảnh tải lên tự thu nhỏ | Đo bằng `CaptureQueriesContext`; `core/images.py` |
| 11 | **Minh bạch**: có khai báo dùng AI, bảng lỗi đã tìm và sửa, tài liệu giải thích code | `docs/khai-bao-su-dung-ai.md`, `docs/giai-thich-code.md` |

**Nói thật về giới hạn** (giảng viên đánh giá cao điều này):
- Hệ thống **không tự biết** người dùng đã chuyển khoản — BTC vẫn đối chiếu sao kê.
- Camera quét QR cần HTTPS; khi không có thì dùng ô nhập mã.
- Chưa kiểm thử tải lớn; quy mô thiết kế cho một CLB (vài trăm người).
- Thông báo cập nhật khi tải lại trang (không đẩy tức thời).

---

## Phần 3. Khi demo cần làm gì

### 3.1. Trước buổi demo (làm theo thứ tự, đánh dấu từng ô)

- [ ] `git pull` bản mới nhất trên máy demo, chạy `chay-thu.bat` một lần cho chắc.
- [ ] `python manage.py test` → phải thấy **233 test OK**. Chụp màn hình để chiếu.
- [ ] **Nạp lại dữ liệu sạch ngay trước giờ demo**: `python manage.py seed_demo --reset`.
- [ ] Mở sẵn 2 cửa sổ trình duyệt: thường + ẩn danh (để đăng nhập 2 người cùng lúc).
- [ ] Tắt thông báo máy tính, đóng tab riêng tư (Facebook, Instagram…), phóng to chữ trình duyệt 110–125% cho người ngồi xa dễ đọc.
- [ ] Nếu demo camera: chạy `ngrok http 8000`, thêm tên miền ngrok vào `ALLOWED_HOSTS` và `CSRF_TRUSTED_ORIGINS` trong `.env`, mở link trên điện thoại. Không có ngrok thì dùng ô nhập mã.
- [ ] Nếu demo VietQR: điền `BANK_*` trong `.env`, **quét thử bằng app ngân hàng thật** trước.
- [ ] **Dự phòng**: một máy thứ 2 đã cài sẵn + **video quay đủ luồng demo**. Hỏng máy vẫn trình bày được.
- [ ] Mỗi người đọc phần mình phụ trách trong `docs/giai-thich-code.md` và tự trả lời câu hỏi ở cuối mỗi mục.

### 3.2. Trình tự demo

Làm đúng theo `docs/kich-ban-demo.md` (14 bước chính, khoảng 10 phút + 6 bước
mở rộng). Nguyên tắc:

1. **Đi theo vòng đời sự kiện**, không đi theo từng menu: tạo sự kiện → giao
   việc → bán vé → thanh toán → check-in → đánh giá → thống kê.
2. **3 khoảnh khắc "wow" phải làm thật chậm, nói rõ**:
   - **2 người cùng bấm đặt chỗ cuối** → chỉ 1 người được (bước 8).
   - **Check-in 3 màu**: hợp lệ → quét lại báo đã dùng → mã sai (bước 10).
   - **Có người huỷ → người đang chờ tự có vé + có thông báo** (bước E1).
3. **Mỗi bước nói 1 câu "vì sao"**, không chỉ "bấm vào đây". Câu gợi ý có sẵn ở
   cột "Nói gì" trong kịch bản.
4. **Chủ động cho thấy bảo mật**: gõ thẳng URL trang quản trị bằng tài khoản
   thường → 403.
5. **Kết thúc bằng số liệu**: màn hình 233 test pass, độ phủ 87%, bảng test
   case / RTM, Git log có nhánh + Pull Request.
6. **Mỗi thành viên thao tác ít nhất 1 lần** để ai cũng trả lời được câu hỏi.

### 3.3. Nếu sự cố giữa lúc demo

| Sự cố | Xử lý tại chỗ |
|---|---|
| Mất mạng | Vẫn chạy bình thường (không dùng CDN); chỉ AI tóm tắt / gợi ý chuyển sang danh sách mặc định — **nói ra đây là thiết kế có chủ đích** |
| Camera không bật | Dùng ô nhập mã vé — cùng kết quả 3 màu |
| Dữ liệu bị rối sau vài lần thử | `python manage.py seed_demo --reset` (khoảng 5 giây) |
| Web không lên | Chuyển máy dự phòng hoặc chiếu video |
| Quên mật khẩu tài khoản demo | Tất cả đều là `demo1234` |

### 3.4. Câu hỏi giảng viên hay hỏi — trả lời ngắn

| Câu hỏi | Ý chính trả lời |
|---|---|
| Làm sao không bán vượt chỗ? | Khoá dòng loại vé (`SELECT … FOR UPDATE`) trong một transaction; người sau chờ người trước xong mới đọc số chỗ |
| Người đang chờ được cấp vé thế nào? 2 người huỷ cùng lúc có cấp trùng không? | Cấp ngay trong transaction huỷ vé, dưới cùng khoá dòng → không cấp trùng |
| Vì sao thông báo gửi "sau khi commit"? | Nếu gửi trước mà giao dịch lỗi thì email "đặt vé thành công" đã đi mà vé không tồn tại |
| Chứng nhận có làm giả được không? | Mã xác thực là chữ ký HMAC theo khoá bí mật của server; sửa 1 ký tự là trang xác thực báo không hợp lệ |
| AI lỗi thì sao? Có gửi dữ liệu cá nhân cho AI không? | Có danh sách mặc định; chỉ gửi nội dung đánh giá, không gửi tên/MSSV |
| Nhóm dùng AI thế nào? | Trả lời theo `docs/khai-bao-su-dung-ai.md`: công cụ gì, phần nào, nhóm kiểm tra và hiểu code ra sao |
| Test được bao nhiêu? | 233 test tự động, độ phủ 87%, kiểm thử theo vai 69/69 bước, mã test khớp RTM |

Chi tiết từng câu và câu hỏi theo module: `docs/giai-thich-code.md`.
