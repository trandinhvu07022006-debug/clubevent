"""
Chống GỬI TRÙNG form (bấm đúp, mạng chậm bấm lại, F5 gửi lại POST).

Lỗi thật đã gặp: mạng chậm, bấm đúp nút "Đăng ký" -> 2 request -> đặt 2 vé,
trong khi màn hình chỉ báo "Đăng ký thành công 1 vé". Tương tự giao việc,
thêm khoản chi... tạo bản ghi trùng.

Cách làm: mỗi lần hiển thị form sinh một mã ngẫu nhiên (thẻ {% once_token %}).
Server chỉ chấp nhận mỗi mã MỘT lần: cache.add() là thao tác "thêm nếu chưa
có" nguyên tử, nên 2 request cùng mã đến cùng lúc thì chỉ 1 cái qua.

Lưu ý triển khai: cache mặc định (LocMemCache) chỉ dùng chung trong MỘT tiến
trình. Chạy nhiều worker (gunicorn -w 4) thì cấu hình CACHES dùng chung
(DatabaseCache / Redis) để chặn được cả khi 2 request rơi vào 2 worker.
Phía trình duyệt còn một lớp chặn nữa (base.html) cho mọi form POST.
"""
import uuid

from django.core.cache import cache

FIELD = "_once"
TTL_SECONDS = 30 * 60


def new_token() -> str:
    return uuid.uuid4().hex


def consume(request) -> bool:
    """
    True nếu đây là lần gửi ĐẦU TIÊN của form (hoặc form cũ không có mã),
    False nếu mã đã dùng rồi -> view bỏ qua, không tạo dữ liệu lần nữa.
    """
    token = request.POST.get(FIELD, "")
    if not token:
        return True
    owner = request.user.pk if request.user.is_authenticated else "anon"
    return cache.add(f"once:{owner}:{token[:64]}", 1, TTL_SECONDS)
