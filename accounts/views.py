"""View cho M1 - Đăng ký Email/SĐT, Xác minh OTP 6 số, Quản trị Admin Server & Phiên Thiết bị."""
from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.views import (
    LoginView,
    LogoutView,
    PasswordChangeView,
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
)
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from urllib.parse import urlencode

from core.pagination import paginate
from core.security import is_rate_limited
from registrations.services import attended_events, user_stats

from .forms import (
    AppPasswordResetForm,
    ExtendedProfileForm,
    LoginForm,
    OTPVerifyForm,
    ProfileForm,
    RegisterForm,
    RoleForm,
)
from .models import AuditLog, OTPVerificationChallenge, OtpChannel, User, UserSession
from .permissions import admin_required
from .services import (
    OtpVerificationError,
    confirm_email_verification,
    ensure_user_profile,
    issue_email_verification,
    issue_otp_challenge,
    mask_destination,
    record_login_session,
    resolve_post_login_url,
    revoke_all_other_sessions,
    revoke_user_session,
    select_default_otp_channel,
    set_account_lock_state,
    verify_otp_challenge,
)
from .throttle import blocked_response, login_blocked


def _store_dev_otp_hint(request, challenge: OTPVerificationChallenge, raw_code: str) -> None:
    """
    Chỉ khi chạy local DEBUG với console provider mới lưu gợi ý mã OTP vào session
    của chính người dùng để Admin/Dev test giao diện SMS không cần cổng trả phí.
    Tuyệt đối không bao giờ kích hoạt khi DEBUG=False.
    """
    request.session["last_otp_channel"] = challenge.channel
    if settings.DEBUG and getattr(settings, "SMS_PROVIDER", "console") == "console":
        request.session["dev_otp_hint"] = raw_code
    else:
        request.session.pop("dev_otp_hint", None)


def _safe_next(request, default="pages:dashboard"):
    """Chỉ cho quay về URL trong site, chặn open redirect qua tham số next."""
    url = request.POST.get("next") or request.GET.get("next") or ""
    if url and url_has_allowed_host_and_scheme(url, {request.get_host()},
                                               request.is_secure()):
        return url
    return reverse(default)


class AppLoginView(LoginView):
    """F1.2 - Đăng nhập bằng Email / SĐT / Username có chống brute-force + Smart Post-Login Router."""

    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        if login_blocked(request):
            messages.error(
                request,
                "Bạn thử đăng nhập quá nhiều lần liên tiếp. Vui lòng chờ vài phút.",
            )
            return blocked_response()
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        record_login_session(self.request, self.request.user)
        return response

    def get_default_redirect_url(self):
        return resolve_post_login_url(self.request.user)


class AppLogoutView(LogoutView):
    def post(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.session.session_key:
            UserSession.objects.filter(
                user=request.user,
                session_key=request.session.session_key,
                revoked_at__isnull=True,
            ).update(revoked_reason="Người dùng chủ động đăng xuất")
        return super().post(request, *args, **kwargs)


def register(request):
    """
    F1.1 - Đăng ký tài khoản qua Email hoặc SĐT:
    - Tạo tài khoản mặc định ở chế độ Khách (`club_status == 'GUEST'`).
    - Tự động phát hành mã OTP 6 chữ số qua SMS hoặc Email.
    - Chuyển hướng sang màn hình xác minh OTP `/taikhoan/xacminh-otp/`.
    """
    if request.user.is_authenticated:
        return redirect(resolve_post_login_url(request.user))
    if request.method == "POST" and is_rate_limited(
        request,
        scope="auth_register",
        limit=10,
        window_seconds=600,
    ):
        return HttpResponse(
            "Bạn gửi yêu cầu đăng ký quá nhanh. Vui lòng thử lại sau.",
            status=429,
        )
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        ensure_user_profile(user)
        chosen_channel = form.cleaned_data.get("resolved_otp_channel")
        try:
            from organization.models import LifecycleEventType
            from organization.services import record_lifecycle_event

            contact_summary = ", ".join(
                part
                for part in (
                    f"Email: {user.email}" if user.email else "",
                    f"SĐT: {user.phone}" if user.phone else "",
                )
                if part
            )
            record_lifecycle_event(
                user=user,
                event_type=LifecycleEventType.REGISTERED,
                actor=user,
                title="Đăng ký tài khoản trên hệ thống KMG (Mặc định: Khách)",
                note=f"Username: {user.username} ({contact_summary})",
            )
        except Exception:
            pass

        login(request, user)
        record_login_session(request, user)
        if user.email and getattr(settings, "REQUIRE_EMAIL_OTP", True) and user.needs_email_verification:
            try:
                from .services import OTPError, send_email_otp
                send_email_otp(user)
                messages.info(
                    request,
                    f"Đã gửi mã xác minh tới {user.email}. Nhập mã để hoàn tất đăng ký."
                )
            except OTPError as e:
                messages.warning(request, str(e))
            return redirect("accounts:verify_email")

        try:
            challenge, raw_code = issue_otp_challenge(
                user=user, channel=chosen_channel, request=request,
            )
        except OtpVerificationError as exc:
            request.session["last_otp_channel"] = chosen_channel
            messages.warning(request, f"Tài khoản Khách đã được tạo. {exc}")
            return redirect("accounts:verify_otp")
        _store_dev_otp_hint(request, challenge, raw_code)
        masked = mask_destination(challenge.channel, challenge.destination)
        messages.success(
            request,
            f"Đăng ký tài khoản thành công (chế độ mặc định: Khách)! "
            f"Mã OTP 6 chữ số đã được gửi qua {challenge.get_channel_display()} tới {masked}.",
        )
        return redirect("accounts:verify_otp")
    return render(request, "accounts/register.html", {"form": form})


@login_required
def verify_otp_view(request):
    """
    Trang nhập mã xác minh OTP 6 chữ số qua SMS hoặc Email (`/taikhoan/xacminh-otp/`).
    Sau khi xác minh OTP thành công, tài khoản vẫn giữ mặc định là Khách (`GUEST`) cho đến khi
    được Chủ nhiệm / Phó chủ nhiệm nâng role & phân Ban (hoặc Admin Server nâng cấp lãnh đạo).
    """
    user = request.user
    requested_channel = (
        request.POST.get("channel")
        or request.GET.get("channel")
        or request.session.get("last_otp_channel")
        or ""
    ).upper()

    active_challenge = (
        OTPVerificationChallenge.objects.filter(
            user=user,
            used_at__isnull=True,
            invalidated_at__isnull=True,
        )
        .order_by("-created_at", "-id")
        .first()
    )

    try:
        effective_channel = (
            requested_channel
            if requested_channel in (OtpChannel.EMAIL, OtpChannel.SMS)
            else (
                active_challenge.channel
                if active_challenge is not None
                else select_default_otp_channel(user)
            )
        )
    except OtpVerificationError:
        effective_channel = ""

    form = OTPVerifyForm(
        request.POST if request.method == "POST" else None,
        initial={"channel": effective_channel},
    )
    if request.method == "POST" and form.is_valid():
        try:
            verified = verify_otp_challenge(
                user=user,
                raw_code=form.cleaned_data["code"],
                channel=form.cleaned_data.get("channel") or None,
            )
            request.session.pop("dev_otp_hint", None)
            user.refresh_from_db()
            if user.club_status == "GUEST" and not user.is_server_admin:
                messages.success(
                    request,
                    f"Xác minh OTP qua {verified.get_channel_display()} thành công! "
                    f"Tài khoản của bạn hiện ở chế độ Khách (Guest). Các chức năng Thành viên nội bộ CLB "
                    f"sẽ mở sau khi được Chủ nhiệm hoặc Phó chủ nhiệm nâng role và phân Ban.",
                )
            else:
                messages.success(
                    request,
                    f"Đã xác minh thành công mã OTP qua {verified.get_channel_display()}!",
                )
            return redirect(resolve_post_login_url(user))
        except OtpVerificationError as exc:
            form.add_error("code", str(exc))

    destination = (
        user.normalized_email
        if effective_channel == OtpChannel.EMAIL
        else user.normalized_phone
    )
    dev_otp_hint = (
        request.session.get("dev_otp_hint")
        if (settings.DEBUG and getattr(settings, "SMS_PROVIDER", "console") == "console")
        else None
    )
    return render(
        request,
        "accounts/verify_otp.html",
        {
            "form": form,
            "effective_channel": effective_channel,
            "channel_label": dict(OtpChannel.choices).get(effective_channel, "OTP"),
            "masked_destination": mask_destination(effective_channel, destination or ""),
            "active_challenge": active_challenge,
            "can_use_email": bool(user.normalized_email),
            "can_use_sms": bool(user.normalized_phone),
            "dev_otp_hint": dev_otp_hint,
            "otp_expiry_minutes": getattr(settings, "OTP_EXPIRY_MINUTES", 10),
        },
    )


@require_POST
@login_required
def resend_otp_view(request):
    """Gửi mới / gửi lại mã OTP 6 chữ số qua Email hoặc SMS (có Rate-Limit chống spam)."""
    if is_rate_limited(
        request,
        scope="auth_resend_otp",
        limit=5,
        window_seconds=600,
        identifier=str(request.user.pk),
    ):
        messages.warning(
            request,
            "Bạn đã yêu cầu gửi mã OTP quá nhiều lần liên tiếp. Vui lòng chờ vài phút.",
        )
        return redirect("accounts:verify_otp")

    preferred_channel = (request.POST.get("channel") or "").strip().upper() or None
    try:
        challenge, raw_code = issue_otp_challenge(
            user=request.user,
            channel=preferred_channel,
            request=request,
        )
        _store_dev_otp_hint(request, challenge, raw_code)
        masked = mask_destination(challenge.channel, challenge.destination)
        messages.success(
            request,
            f"Đã gửi mã OTP 6 chữ số mới qua {challenge.get_channel_display()} tới {masked}.",
        )
    except OtpVerificationError as exc:
        messages.error(request, str(exc))
    return redirect("accounts:verify_otp")


def verify_email(request, token: str = ""):
    """Xác minh địa chỉ email qua mã OTP (khi token rỗng) hoặc liên kết token 1 lần."""
    if not token:
        return verify_email_view(request)
    verified_user = confirm_email_verification(token)
    if verified_user is None:
        messages.error(
            request,
            "Liên kết xác minh email không hợp lệ hoặc đã hết hạn.",
        )
    else:
        messages.success(
            request,
            f"Đã xác minh thành công địa chỉ email {verified_user.email}!",
        )
    if request.user.is_authenticated:
        return redirect("accounts:profile")
    return redirect("accounts:login")


@require_POST
@login_required
def resend_verification_email(request):
    """Gửi lại email xác minh (có giới hạn tần suất chống spam)."""
    if request.user.is_email_verified:
        messages.info(request, "Email của bạn đã được xác minh trước đó.")
        return redirect("accounts:profile")
    if is_rate_limited(
        request,
        scope="auth_resend_verify",
        limit=3,
        window_seconds=600,
        identifier=str(request.user.pk),
    ):
        messages.warning(
            request,
            "Bạn vừa yêu cầu gửi mã xác minh. Vui lòng chờ ít phút trước khi gửi lại.",
        )
        return redirect("accounts:profile")
    issue_email_verification(request.user, request=request)
    messages.success(request, "Đã gửi lại liên kết xác minh tới hộp thư của bạn.")
    return redirect("accounts:profile")


@login_required
def profile(request):
    """F1.3 - Cập nhật hồ sơ, xác minh OTP, cài đặt quyền riêng tư PII và xem lịch sử tham gia."""
    ext_profile = ensure_user_profile(request.user)
    action = request.POST.get("form_type", "basic")
    form = ProfileForm(
        request.POST if (request.method == "POST" and action == "basic") else None,
        request.FILES if (request.method == "POST" and action == "basic") else None,
        instance=request.user,
    )
    ext_form = ExtendedProfileForm(
        request.POST if (request.method == "POST" and action == "extended") else None,
        instance=ext_profile,
    )
    if request.method == "POST":
        if action == "extended" and ext_form.is_valid():
            ext_form.save()
            messages.success(request, "Đã cập nhật hồ sơ mở rộng & cài đặt quyền riêng tư.")
            return redirect("accounts:profile")
        if action == "basic" and form.is_valid():
            form.save()
            messages.success(request, "Đã cập nhật hồ sơ.")
            return redirect("accounts:profile")

    attended = list(attended_events(request.user))
    active_sessions = list(
        request.user.device_sessions.filter(revoked_at__isnull=True)[:10]
    )
    my_playlists = []
    if request.user.has_active_club_access:
        from social.models import MusicPlaylist

        my_playlists = list(MusicPlaylist.objects.filter(owner=request.user).prefetch_related("items")[:4])
    return render(
        request,
        "accounts/profile.html",
        {
            "form": form,
            "ext_form": ext_form,
            "attended": attended,
            "stats": user_stats(request.user),
            "active_sessions": active_sessions,
            "current_session_key": request.session.session_key,
            "my_playlists": my_playlists,
        },
    )


@login_required
def session_list(request):
    """Trang quản lý các thiết bị đã đăng nhập."""
    sessions = request.user.device_sessions.all()[:30]
    return render(
        request,
        "accounts/sessions.html",
        {
            "sessions": sessions,
            "current_session_key": request.session.session_key,
        },
    )


@require_POST
@login_required
def session_revoke(request, pk):
    """Đăng xuất từ xa một phiên thiết bị của chính người dùng."""
    session_obj = get_object_or_404(UserSession, pk=pk, user=request.user)
    if session_obj.session_key == request.session.session_key:
        messages.warning(
            request,
            "Đây là thiết bị hiện tại. Hãy dùng nút Đăng xuất nếu muốn thoát phiên này.",
        )
        return redirect("accounts:sessions")
    revoke_user_session(request.user, session_obj)
    messages.success(request, f"Đã thu hồi phiên trên {session_obj.device_label}.")
    return redirect("accounts:sessions")


@require_POST
@login_required
def session_revoke_others(request):
    """Đăng xuất toàn bộ thiết bị khác trừ thiết bị hiện tại."""
    count = revoke_all_other_sessions(request.user, request.session.session_key or "")
    messages.success(request, f"Đã đăng xuất {count} thiết bị khác.")
    return redirect("accounts:sessions")


@login_required
def membership_status_portal(request):
    """
    Cổng thông tin hạn chế (Restricted Portal) dành cho thành viên đang bị tạm khoá
    (`ClubMembership.status == SUSPENDED`) hoặc ứng viên theo dõi trạng thái hồ sơ.
    Cho phép thành viên đang `SUSPENDED` gửi đơn khiếu nại / giải trình độc lập (`WF24`).
    """
    from operations.models import Appeal, AppealTargetType, DisciplineCase
    from operations.services import submit_appeal
    from organization.services import GovernanceError

    cm = request.user.club_membership_record
    if request.method == "POST" and request.POST.get("action") == "submit_appeal":
        case_id = (request.POST.get("discipline_case_id") or "").strip()
        d_case = (
            DisciplineCase.objects.filter(pk=case_id, target_user=request.user).first()
            if case_id.isdigit()
            else None
        )
        try:
            appeal = submit_appeal(
                appellant=request.user,
                target_type=AppealTargetType.MEMBERSHIP_SUSPENSION,
                reason=request.POST.get("reason", ""),
                discipline_case=d_case,
                evidence_url=request.POST.get("evidence_url", ""),
            )
            messages.success(
                request,
                f"Đã gửi đơn khiếu nại / giải trình #{appeal.pk} tới Ban Chủ nhiệm xem xét độc lập.",
            )
            return redirect("accounts:membership_status")
        except (GovernanceError, PermissionDenied) as exc:
            messages.error(request, str(exc))

    lifecycle = []
    applications = []
    if hasattr(request.user, "lifecycle_events"):
        lifecycle = list(request.user.lifecycle_events.select_related("department", "actor")[:20])
    if hasattr(request.user, "membership_applications"):
        applications = list(
            request.user.membership_applications.select_related(
                "primary_department", "secondary_department"
            )
        )
    my_cases = list(
        DisciplineCase.objects.select_related("reviewed_by")
        .filter(target_user=request.user)
        .order_by("-created_at")[:10]
    )
    my_appeals = list(
        Appeal.objects.select_related("decided_by", "original_actor")
        .filter(appellant=request.user)
        .order_by("-created_at")[:10]
    )
    my_contributions = []
    my_evaluations = []
    if hasattr(request.user, "member_contributions"):
        my_contributions = list(
            request.user.member_contributions.select_related("ledger_transaction", "department")[:10]
        )
    if hasattr(request.user, "evaluations_received"):
        my_evaluations = list(
            request.user.evaluations_received.select_related("cycle", "department")
            .filter(status="CONFIRMED")[:10]
        )
    return render(
        request,
        "accounts/membership_status.html",
        {
            "club_membership": cm,
            "lifecycle": lifecycle,
            "applications": applications,
            "my_cases": my_cases,
            "my_appeals": my_appeals,
            "my_contributions": my_contributions,
            "my_evaluations": my_evaluations,
        },
    )


class AppPasswordChangeView(PasswordChangeView):
    """F1.3 - Đổi mật khẩu, thu hồi các thiết bị khác để bảo vệ tài khoản."""

    template_name = "accounts/password_change.html"
    form_class = PasswordChangeForm
    success_url = reverse_lazy("accounts:profile")

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        for field in form.fields.values():
            field.widget.attrs.update({"class": "form-control"})
        return form

    def form_valid(self, form):
        response = super().form_valid(form)
        self.request.user.bump_authz_version()
        revoke_all_other_sessions(
            self.request.user, self.request.session.session_key or ""
        )
        messages.success(self.request, "Đã đổi mật khẩu thành công.")
        AuditLog.write(self.request.user, "Đổi mật khẩu", self.request.user)
        return response


class AppPasswordResetView(PasswordResetView):
    """SEC-06 - Đặt lại mật khẩu giới hạn 5 yêu cầu/giờ theo IP trong Cache."""

    template_name = "accounts/password_reset_form.html"
    email_template_name = "emails/password_reset.txt"
    html_email_template_name = "emails/password_reset.html"
    subject_template_name = "emails/password_reset_subject.txt"
    form_class = AppPasswordResetForm
    success_url = reverse_lazy("accounts:password_reset_done")

    def dispatch(self, request, *args, **kwargs):
        if request.method == "POST" and is_rate_limited(
            request,
            scope="auth_password_reset",
            limit=5,
            window_seconds=3600,
        ):
            return redirect(self.success_url)
        return super().dispatch(request, *args, **kwargs)


class AppPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")

    def form_valid(self, form):
        response = super().form_valid(form)
        self.user.bump_authz_version()
        AuditLog.write(self.user, "Đặt lại mật khẩu", self.user.username)
        return response


@admin_required
def user_list(request):
    """
    F1.4 - Bảng Điều khiển Admin Server (`/taikhoan/quanly/`):
    Xem danh sách tài khoản mới đăng ký (Khách / Thành viên / Lãnh đạo), trạng thái OTP,
    và nâng cấp trực tiếp các chức vụ Chủ nhiệm, Phó chủ nhiệm, Trưởng ban, Cố vấn.
    """
    keyword = request.GET.get("q", "").strip()
    tier = request.GET.get("tier", "all").strip()
    users = (
        User.objects.select_related("club_membership")
        .prefetch_related(
            "appointments__position",
            "appointments__department",
            "department_memberships__department",
        )
        .order_by("-created_at")
    )
    if keyword:
        users = users.filter(
            Q(full_name__icontains=keyword)
            | Q(display_name__icontains=keyword)
            | Q(mssv__icontains=keyword)
            | Q(username__icontains=keyword)
            | Q(email__icontains=keyword)
            | Q(phone__icontains=keyword)
            | Q(normalized_phone__icontains=keyword)
        )
    if tier == "guest":
        users = users.filter(club_membership__isnull=True)
    elif tier == "member":
        users = users.filter(club_membership__status="ACTIVE")
    elif tier == "leadership":
        users = users.filter(
            appointments__is_active=True,
            appointments__ended_at__isnull=True,
        ).distinct()

    page_obj, querystring = paginate(request, users, per_page=20)
    return render(
        request,
        "accounts/user_list.html",
        {
            "users": page_obj,
            "page_obj": page_obj,
            "querystring": querystring,
            "keyword": keyword,
            "tier": tier,
        },
    )


@admin_required
def user_set_role(request, pk):
    """
    F1.4 - Trang Quản trị Tài khoản & Nâng cấp Chức vụ Lãnh đạo CLB dành riêng cho Admin Server:
    1. Đổi vai trò BTC sự kiện / Admin Server (`RoleForm`).
    2. Nâng cấp tài khoản đã đăng ký lên `Chủ nhiệm`, `Phó chủ nhiệm`, `Trưởng ban` (chọn Ban), `Cố vấn`.
    3. Kết thúc nhiệm kỳ lãnh đạo hiện có.
    """
    from organization.models import Appointment, Department, GrantBundleCode, Position
    from organization.permissions import VICE_CHAIRMAN_PORTFOLIO_PERMISSIONS
    from organization.services import bootstrap_organization_catalog

    bootstrap_organization_catalog()
    target = get_object_or_404(User, pk=pk)
    if request.method == "POST" and target == request.user:
        messages.error(request, "Không thể tự đổi vai trò hệ thống của chính mình.")
        return redirect("accounts:user_list")

    form = RoleForm(request.POST or None, instance=target)
    if request.method == "POST" and form.is_valid():
        old_role = target.get_role_display()
        form.save()
        target.bump_authz_version()
        AuditLog.write(
            request.user,
            "Gán role",
            target,
            f"{old_role} -> {target.get_role_display()}",
        )
        messages.success(request, f"Đã đổi vai trò hệ thống của {target.public_name}.")
        return redirect("accounts:user_list")

    active_appointments = list(
        Appointment.objects.select_related("position", "department")
        .prefetch_related("permission_grants")
        .filter(user=target, is_active=True, ended_at__isnull=True)
        .order_by("position__rank_order")
    )
    departments = list(Department.objects.filter(is_active=True))
    positions = list(Position.objects.all().order_by("rank_order"))
    vc_portfolios = [
        (code, GrantBundleCode(code).label)
        for code in VICE_CHAIRMAN_PORTFOLIO_PERMISSIONS.keys()
    ]
    return render(
        request,
        "accounts/user_role.html",
        {
            "form": form,
            "target": target,
            "departments": departments,
            "positions": positions,
            "vc_portfolios": vc_portfolios,
            "active_appointments": active_appointments,
        },
    )


@require_POST
@admin_required
def user_assign_leadership(request, pk):
    """Admin Server nâng cấp trực tiếp tài khoản đã đăng ký lên Chủ nhiệm, Phó CN, Trưởng ban, Cố vấn."""
    from organization.models import Department
    from organization.services import GovernanceError, server_admin_assign_leadership

    target = get_object_or_404(User, pk=pk)
    position_code = (request.POST.get("position_code") or "").strip()
    dept_id = (request.POST.get("department_id") or "").strip()
    department = Department.objects.filter(pk=dept_id, is_active=True).first() if dept_id else None
    portfolios = request.POST.getlist("portfolios")
    term_label = (request.POST.get("term_label") or "2026-2027").strip()
    title_note = (request.POST.get("title_note") or "").strip()
    replace_existing = request.POST.get("replace_existing") == "1"

    try:
        appt = server_admin_assign_leadership(
            actor=request.user,
            target_user=target,
            position_code=position_code,
            department=department,
            portfolios=portfolios,
            term_label=term_label,
            title_note=title_note,
            replace_existing=replace_existing,
        )
        scope_txt = f" ({appt.department.name})" if appt.department_id else " (Toàn CLB)"
        messages.success(
            request,
            f"Admin Server đã nâng cấp {target.public_name} lên chức vụ {appt.position.name}{scope_txt}!",
        )
    except (GovernanceError, PermissionDenied) as exc:
        messages.error(request, str(exc))
    return redirect("accounts:user_role", pk=target.pk)


@require_POST
@admin_required
def user_end_leadership(request, pk, appt_pk):
    """Admin Server kết thúc nhiệm kỳ / thu hồi chức vụ lãnh đạo CLB."""
    from organization.models import Appointment
    from organization.services import GovernanceError, end_appointment

    target = get_object_or_404(User, pk=pk)
    appt = get_object_or_404(
        Appointment.objects.select_related("user", "position", "department"),
        pk=appt_pk,
        user=target,
    )
    reason = (request.POST.get("reason") or "Admin Server thu hồi / kết thúc nhiệm kỳ").strip()
    try:
        end_appointment(actor=request.user, appointment=appt, reason=reason)
        messages.success(
            request,
            f"Đã kết thúc chức vụ {appt.position.name} của {target.public_name} và thu hồi quyền tức thời.",
        )
    except (GovernanceError, PermissionDenied) as exc:
        messages.error(request, str(exc))
    return redirect("accounts:user_role", pk=target.pk)


@require_POST
@admin_required
def user_toggle_lock(request, pk):
    """F1.4 - Khoá hoặc mở khoá tài khoản, thu hồi phiên và ghi lịch sử."""
    target = get_object_or_404(User, pk=pk)
    if target == request.user:
        messages.error(request, "Không thể tự khoá tài khoản của mình.")
        return redirect("accounts:user_list")
    reason = request.POST.get("reason", "").strip()
    set_account_lock_state(
        actor=request.user,
        target=target,
        locked=not target.is_locked,
        reason=reason,
    )
    messages.success(request, "Đã cập nhật trạng thái tài khoản.")
    return redirect("accounts:user_list")


@admin_required
def audit_log(request):
    """F0.2 - Xem nhật ký thao tác, 200 dòng gần nhất."""
    return render(
        request,
        "accounts/audit_log.html",
        {"logs": AuditLog.objects.select_related("user")[:200]},
    )


@login_required
def verify_email_view(request):
    """
    F1.7 - Nhập mã OTP xác minh email cho tài khoản Khách đặt vé.
    """
    user = request.user
    next_url = _safe_next(request)
    if not user.needs_email_verification:
        if user.email_verified_at:
            messages.info(request, "Email của bạn đã được xác minh, không cần nhập mã nữa.")
        return redirect(next_url)

    if request.method == "POST":
        try:
            from .services import OTPError, send_email_otp, verify_email_otp
            if request.POST.get("action") == "send":
                send_email_otp(user)
                messages.success(request, f"Đã gửi mã xác minh tới {user.email}.")
            else:
                verify_email_otp(user, request.POST.get("code", ""))
                messages.success(request, "Xác minh email thành công. Bạn đã có thể đặt vé.")
                return redirect(next_url)
        except OTPError as e:
            messages.error(request, str(e))
        # PRG: tránh F5 gửi lại POST
        url = request.path
        if request.POST.get("next"):
            url += "?" + urlencode({"next": request.POST["next"]})
        return redirect(url)

    from .services import resend_wait_seconds
    return render(request, "accounts/verify_email.html", {
        "user": user,
        "next": request.GET.get("next", ""),
        "has_code": user.email_otps.filter(used_at__isnull=True).exists(),
        "ttl": getattr(settings, "OTP_TTL_MINUTES", 10),
        "wait": resend_wait_seconds(user),
    })
