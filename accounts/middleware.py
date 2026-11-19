"""
Middleware bảo vệ phiên đăng nhập & trạng thái tài khoản (M1 / INV-06).

1. Tài khoản bị khoá (`is_locked` / `AccountStatus.LOCKED`) -> đăng xuất ngay ở request kế tiếp.
2. Phiên thiết bị bị thu hồi từ xa (`UserSession.revoked_at IS NOT NULL`) -> đăng xuất ngay.
3. Thành viên CLB bị tạm khoá (`ClubMembership.status == SUSPENDED`) -> chặn truy cập
   Không gian nội bộ `/workspace/` và API nội bộ, điều hướng về Cổng hạn chế.
"""
from django.contrib import messages
from django.contrib.auth import logout
from django.http import JsonResponse
from django.shortcuts import redirect

from .models import AccountStatus, UserSession


class LockedUserMiddleware:
    """Kiểm tra trạng thái khoá, thu hồi phiên thiết bị và phạm vi tạm khoá CLB."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            is_api = request.path.startswith("/api/v1/")

            # 1. Khoá tài khoản cấp hệ thống
            if user.is_locked or user.account_status == AccountStatus.LOCKED:
                logout(request)
                if is_api:
                    return JsonResponse(
                        {
                            "ok": False,
                            "error": {
                                "code": "ACCOUNT_LOCKED",
                                "message": "Tài khoản của bạn đã bị khoá.",
                                "details": {},
                            },
                        },
                        status=403,
                    )
                messages.error(
                    request,
                    "Tài khoản của bạn đã bị khoá. Liên hệ Admin để được mở.",
                )
                return redirect("accounts:login")

            # 2. Phiên thiết bị đã bị thu hồi từ xa
            session_key = getattr(request.session, "session_key", None)
            if session_key and UserSession.objects.filter(
                user=user,
                session_key=session_key,
                revoked_at__isnull=False,
            ).exists():
                logout(request)
                if is_api:
                    return JsonResponse(
                        {
                            "ok": False,
                            "error": {
                                "code": "SESSION_REVOKED",
                                "message": "Phiên đăng nhập trên thiết bị này đã bị thu hồi.",
                                "details": {},
                            },
                        },
                        status=401,
                    )
                messages.warning(
                    request,
                    "Phiên đăng nhập trên thiết bị này đã được đăng xuất từ xa.",
                )
                return redirect("accounts:login")

            # 3. Thành viên CLB đang bị tạm khoá (SUSPENDED): chặn vào không gian làm việc nội bộ
            if user.club_status == "SUSPENDED":
                if request.path.startswith("/workspace/"):
                    messages.warning(
                        request,
                        "Tư cách thành viên CLB của bạn đang bị tạm khoá. "
                        "Bạn chỉ có thể xem thông báo trạng thái và gửi phản hồi.",
                    )
                    return redirect("accounts:membership_status")
                if is_api and not request.path.startswith(
                    (
                        "/api/v1/auth/me/",
                        "/api/v1/auth/sessions/",
                        "/api/v1/auth/otp/",
                        "/api/v1/appeals/",
                        "/api/v1/finance/my-contributions/",
                        "/api/v1/evaluations/my/",
                    )
                ):
                    return JsonResponse(
                        {
                            "ok": False,
                            "error": {
                                "code": "MEMBERSHIP_SUSPENDED",
                                "message": "Tư cách thành viên CLB đang tạm khoá.",
                                "details": {},
                            },
                        },
                        status=403,
                    )

        return self.get_response(request)
