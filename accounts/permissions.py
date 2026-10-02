"""
F0.1 - Phân quyền kiểm tra ở SERVER, không chỉ ẩn nút trên giao diện.

Người dùng gõ thẳng URL không thuộc quyền mình sẽ nhận lỗi 403.
Đây là câu giảng viên rất hay hỏi khi bảo vệ.
"""
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied


def _guard(test_func):
    """Sinh ra decorator từ một hàm kiểm tra quyền trên user."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                # Chưa đăng nhập thì đưa về trang login, giữ lại URL đang muốn vào
                return redirect_to_login(request.get_full_path())
            if user.is_locked:
                raise PermissionDenied("Tài khoản đã bị khoá.")
            if not test_func(user):
                raise PermissionDenied("Bạn không có quyền truy cập chức năng này.")
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


# Thành viên chính thức trở lên (không phải Khách): xem các Ban
member_required = _guard(lambda u: u.is_club_member)

# Thành viên BTC trở lên: check-in, xác nhận thanh toán
staff_required = _guard(lambda u: u.is_staff_btc)

# Trưởng BTC trở lên: tạo sự kiện, phân công công việc, xem thống kê
lead_required = _guard(lambda u: u.is_lead)

# Chỉ Admin: quản lý tài khoản, gán role
admin_required = _guard(lambda u: u.is_admin_role)
