"""
Chống dò mật khẩu, dùng chung cho trang đăng nhập của web và /admin/login/.

Hai lớp giới hạn:
- Theo IP: chặn một máy thử liên tục.
- Theo tài khoản (gộp mọi IP): chặn việc đổi IP để dò cùng một tài khoản.

Đánh đổi: người khác cố tình nhập sai có thể làm tài khoản bị khoá tạm. Khoá tự
mở khi các lượt thử cũ trôi ra khỏi cửa sổ thời gian.
"""
import unicodedata
from functools import wraps

from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from django.http import HttpResponse

from core.security import is_rate_limited, reset_global_rate_limit

from .models import User
from .services import find_user_by_login_identifier

IP_SCOPE = "auth_login"
IP_LIMIT = 20
IP_WINDOW = 300          # giây
ACCOUNT_SCOPE = "auth_account"
ACCOUNT_LIMIT = 10
ACCOUNT_WINDOW = 900     # giây


def _bucket_for_user(user):
    return f"user:{user.pk}"


def _bucket_for_name(raw):
    """Gộp username, email, SĐT của cùng một người vào một bộ đếm."""
    name = (raw or "").replace("\x00", "").strip()
    # Chuẩn hoá như form đăng nhập của Django, nếu không ký tự "na ná" sẽ lách được
    if len(name) <= 254:
        name = unicodedata.normalize("NFKC", name).strip()
    if not name:
        return ""
    # Thử đúng phép so khớp mà bước xác thực dùng (theo collation của DB) trước,
    # sau đó mới tới email / SĐT
    user = (User.objects.filter(username=name).first()
            or find_user_by_login_identifier(name))
    return _bucket_for_user(user) if user else f"name:{name.casefold()}"


def login_blocked(request):
    """Ghi nhận một lượt thử đăng nhập; True nghĩa là phải từ chối lượt này."""
    # Kiểm tra IP trước: IP đã bị chặn thì không tiêu thêm hạn mức của tài khoản
    if is_rate_limited(request, IP_SCOPE, IP_LIMIT, IP_WINDOW):
        return True
    bucket = _bucket_for_name(request.POST.get("username", ""))
    return bool(bucket) and is_rate_limited(
        request, ACCOUNT_SCOPE, ACCOUNT_LIMIT, ACCOUNT_WINDOW,
        identifier=bucket, per_ip=False)


def blocked_response():
    return HttpResponse(
        "Quá nhiều yêu cầu đăng nhập. Vui lòng thử lại sau.", status=429)


def throttle_login(view):
    """Bọc một view đăng nhập có sẵn (ví dụ của Django Admin)."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.method == "POST" and login_blocked(request):
            return blocked_response()
        return view(request, *args, **kwargs)
    return wrapper


@receiver(user_logged_in)
def _reset_after_success(sender, request, user, **kwargs):
    # Đăng nhập đúng thì xoá bộ đếm, người gõ nhầm vài lần không bị phạt dồn
    reset_global_rate_limit(ACCOUNT_SCOPE, _bucket_for_user(user))
