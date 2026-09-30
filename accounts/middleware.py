"""Middleware cho M1 - Tài khoản."""
from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect


class LockedUserMiddleware:
    """
    Đăng xuất ngay tài khoản bị khoá ở request kế tiếp.

    LoginForm chỉ chặn lúc ĐĂNG NHẬP và decorator phân quyền chỉ chặn trang
    BTC. Không có lớp này thì người đang đăng nhập sẵn khi bị Admin khoá vẫn
    đặt vé, gửi đánh giá... bình thường cho tới khi phiên hết hạn.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and user.is_locked:
            logout(request)
            messages.error(request, "Tài khoản của bạn đã bị khoá. "
                                    "Liên hệ Admin để được mở.")
            return redirect("accounts:login")
        return self.get_response(request)
