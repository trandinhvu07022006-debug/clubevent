"""
Tầng Service cho M1 - Xác thực Đa Định danh (Email / SĐT / Username),
Xác minh OTP 6 số qua SMS hoặc Email, Quản lý Phiên Thiết bị &
Bộ định tuyến Thông minh sau Đăng nhập (Smart Post-Login Router).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets

from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from core.security import get_client_ip

from .models import (
    AccountStatus,
    AccountStatusHistory,
    AuditLog,
    EmailVerificationToken,
    OTPVerificationChallenge,
    OtpChannel,
    Role,
    User,
    UserProfile,
    UserSession,
    is_valid_phone_number,
    normalize_phone_number,
)
from .sms import send_sms_otp

EMAIL_VERIFY_TTL_HOURS = 24
logger = logging.getLogger(__name__)


class OtpVerificationError(ValueError):
    """Lỗi nghiệp vụ khi phát hành hoặc xác minh mã OTP 6 chữ số."""

    def __init__(self, message: str, code: str = "OTP_INVALID"):
        super().__init__(message)
        self.code = code

    @property
    def status_code(self) -> int:
        return 503 if self.code == "OTP_DELIVERY_FAILED" else 400


def ensure_user_profile(user: User) -> UserProfile:
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile


def find_user_by_login_identifier(identifier: str) -> User | None:
    """
    Cho phép người dùng đăng nhập bằng:
    1. Tên đăng nhập (`username`), HOẶC
    2. Địa chỉ Email (`normalized_email`, không phân biệt hoa/thường), HOẶC
    3. Số điện thoại (`normalized_phone`, tự chuẩn hoá `+84...` / `09...`).
    """
    raw = (identifier or "").strip()
    if not raw:
        return None

    by_username = User.objects.filter(username__iexact=raw).first()
    if by_username is not None:
        return by_username

    if "@" in raw:
        return User.objects.filter(normalized_email=raw.lower()).first()

    norm_phone = normalize_phone_number(raw)
    if norm_phone and is_valid_phone_number(raw):
        return User.objects.filter(normalized_phone=norm_phone).first()

    return None


def mask_destination(channel: str, destination: str) -> str:
    """Che bớt Email hoặc SĐT khi hiển thị trên màn hình xác minh OTP."""
    dest = (destination or "").strip()
    if not dest:
        return "—"
    if channel == OtpChannel.EMAIL and "@" in dest:
        local, domain = dest.split("@", 1)
        head = local[:2] if len(local) >= 2 else local[:1]
        return f"{head}***@{domain}"
    if len(dest) >= 7:
        return f"{dest[:3]}***{dest[-4:]}"
    return "***"


def _hash_otp_code(
    user_id: int,
    channel: str,
    destination: str,
    raw_code: str,
) -> str:
    """Băm mã OTP 6 chữ số bằng HMAC-SHA256 gắn chặt với user_id, kênh và đích nhận."""
    secret = settings.SECRET_KEY.encode("utf-8")
    msg = f"kmg-otp-v1:{user_id}:{channel}:{destination}:{raw_code}".encode("utf-8")
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()


def select_default_otp_channel(
    user: User,
    preferred_channel: str | None = None,
) -> str:
    """Chọn kênh gửi OTP phù hợp với thông tin liên hệ của tài khoản."""
    pref = (preferred_channel or "").strip().upper()
    if pref == OtpChannel.SMS and user.normalized_phone:
        return OtpChannel.SMS
    if pref == OtpChannel.EMAIL and user.normalized_email:
        return OtpChannel.EMAIL

    if user.normalized_email and not user.is_email_verified:
        return OtpChannel.EMAIL
    if user.normalized_phone and not user.is_phone_verified:
        return OtpChannel.SMS
    if user.normalized_email:
        return OtpChannel.EMAIL
    if user.normalized_phone:
        return OtpChannel.SMS
    raise OtpVerificationError(
        "Tài khoản chưa có Email hoặc Số điện thoại để nhận mã xác minh OTP.",
        code="OTP_MISSING_CONTACT",
    )


@transaction.atomic
def issue_otp_challenge(
    user: User,
    channel: str | None = None,
    request=None,
) -> tuple[OTPVerificationChallenge, str]:
    """
    Phát hành mã OTP 6 chữ số qua Email hoặc SMS:
    - Chỉ thay thế mã cũ khi provider xác nhận nhận mã mới.
    - Sinh mã 6 chữ số từ CSPRNG (`secrets.randbelow`), chỉ lưu HMAC-SHA256 vào DB.
    - Gửi qua Email (`send_mail`) hoặc SMS Gateway (`send_sms_otp`).
    """
    # Tuần tự hóa các lần gửi lại trên cùng tài khoản (kể cả khi chưa có mã cũ).
    User.objects.select_for_update().get(pk=user.pk)
    chosen_channel = select_default_otp_channel(user, channel)
    destination = (
        user.normalized_email
        if chosen_channel == OtpChannel.EMAIL
        else user.normalized_phone
    )
    if not destination:
        raise OtpVerificationError(
            "Tài khoản chưa khai báo thông tin cho kênh nhận OTP đã chọn.",
            code="OTP_MISSING_CONTACT",
        )

    now = timezone.now()
    OTPVerificationChallenge.objects.filter(
        user=user,
        channel=chosen_channel,
        used_at__isnull=True,
        invalidated_at__isnull=True,
    ).update(invalidated_at=now)

    raw_code = f"{secrets.randbelow(1_000_000):06d}"
    ttl_minutes = int(getattr(settings, "OTP_EXPIRY_MINUTES", 10))
    max_attempts = int(getattr(settings, "OTP_MAX_ATTEMPTS", 5))
    code_hash = _hash_otp_code(user.pk, chosen_channel, destination, raw_code)

    challenge = OTPVerificationChallenge.objects.create(
        user=user,
        channel=chosen_channel,
        destination=destination,
        code_hash=code_hash,
        max_attempts=max_attempts,
        expires_at=now + timezone.timedelta(minutes=ttl_minutes),
    )

    try:
        if chosen_channel == OtpChannel.EMAIL:
            delivered = send_mail(
                subject=f"[KMG Club] Mã xác minh OTP của bạn: {raw_code}",
                message=(
                    f"Xin chào {user.public_name},\n\n"
                    f"Mã xác minh OTP tài khoản KMG Club của bạn là: {raw_code}\n"
                    f"Mã có hiệu lực trong {ttl_minutes} phút. Tuyệt đối không chia sẻ mã này.\n\n"
                    "Lưu ý: Sau khi xác minh OTP, tài khoản mặc định ở chế độ Khách (Guest). "
                    "Các chức năng Thành viên nội bộ sẽ mở khi được Chủ nhiệm / Phó chủ nhiệm nâng role và phân Ban."
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email or destination],
                fail_silently=False,
            ) == 1
        else:
            delivered = send_sms_otp(user.phone or destination, raw_code, user=user)
    except Exception as exc:
        # Không ghi payload/OTP hoặc nội dung lỗi provider có thể chứa bí mật.
        logger.warning("OTP delivery failed: channel=%s user=%s error=%s",
                       chosen_channel, user.pk, type(exc).__name__)
        delivered = False
    if not delivered:
        # atomic rollback giữ nguyên mã cũ và loại bỏ mã mới chưa gửi được.
        raise OtpVerificationError(
            "Hiện chưa gửi được mã xác minh. Vui lòng thử Gửi lại mã sau ít phút. "
            "Nếu bạn đã nhận mã trước đó, mã đó vẫn có hiệu lực đến khi hết hạn.",
            code="OTP_DELIVERY_FAILED",
        )

    ip = get_client_ip(request) if request is not None else ""
    AuditLog.write(
        user,
        f"Phát hành OTP ({chosen_channel})",
        mask_destination(chosen_channel, destination),
        ip_address=ip,
    )
    return challenge, raw_code


def verify_otp_challenge(
    user: User,
    raw_code: str,
    channel: str | None = None,
) -> OTPVerificationChallenge:
    """
    Xác thực mã OTP 6 chữ số (an toàn chống race-condition & chống dò mã brute-force):
    - Lưu ý: Số lần thử sai (`attempts += 1`) được commit bền vững vào CSDL trước khi
      ném `OtpVerificationError` để kẻ tấn công không lợi dụng rollback né khoá 5 lần thử.
    - Xác minh thành công kích hoạt `AccountStatus.ACTIVE` và cập nhật `email_verified_at` /
      `phone_verified_at`, NHƯNG giữ nguyên `user.club_status == 'GUEST'` (mặc định là Khách).
    """
    cleaned_code = "".join(ch for ch in (raw_code or "") if ch.isdigit())
    if len(cleaned_code) != 6:
        raise OtpVerificationError(
            "Mã OTP phải gồm đúng 6 chữ số.",
            code="OTP_FORMAT_INVALID",
        )

    pref_channel = (channel or "").strip().upper()
    error_to_raise: OtpVerificationError | None = None
    verified_challenge: OTPVerificationChallenge | None = None

    with transaction.atomic():
        qs = OTPVerificationChallenge.objects.select_for_update().filter(
            user=user,
            used_at__isnull=True,
            invalidated_at__isnull=True,
        )
        if pref_channel in (OtpChannel.EMAIL, OtpChannel.SMS):
            qs = qs.filter(channel=pref_channel)
        challenge = qs.order_by("-created_at", "-id").first()

        if challenge is None:
            error_to_raise = OtpVerificationError(
                "Không có mã OTP nào đang chờ xác minh. Vui lòng bấm Gửi lại mã OTP.",
                code="OTP_NOT_FOUND",
            )
        else:
            now = timezone.now()
            if challenge.expires_at < now:
                challenge.invalidated_at = now
                challenge.save(update_fields=["invalidated_at"])
                error_to_raise = OtpVerificationError(
                    "Mã OTP đã hết hạn. Vui lòng yêu cầu gửi lại mã mới.",
                    code="OTP_EXPIRED",
                )
            elif challenge.attempts >= challenge.max_attempts:
                challenge.invalidated_at = now
                challenge.save(update_fields=["invalidated_at"])
                error_to_raise = OtpVerificationError(
                    "Mã OTP này đã bị vô hiệu hoá do nhập sai quá số lần cho phép.",
                    code="OTP_LOCKED",
                )
            else:
                expected_hash = _hash_otp_code(
                    user.pk,
                    challenge.channel,
                    challenge.destination,
                    cleaned_code,
                )
                if not hmac.compare_digest(challenge.code_hash, expected_hash):
                    challenge.attempts += 1
                    update_cols = ["attempts"]
                    if challenge.attempts >= challenge.max_attempts:
                        challenge.invalidated_at = now
                        update_cols.append("invalidated_at")
                        challenge.save(update_fields=update_cols)
                        error_to_raise = OtpVerificationError(
                            f"Mã OTP không chính xác ({challenge.attempts}/{challenge.max_attempts}). "
                            f"Mã đã bị huỷ để bảo vệ tài khoản, vui lòng yêu cầu gửi mã mới.",
                            code="OTP_LOCKED",
                        )
                    else:
                        remaining = challenge.max_attempts - challenge.attempts
                        challenge.save(update_fields=update_cols)
                        error_to_raise = OtpVerificationError(
                            f"Mã OTP không chính xác. Bạn còn {remaining} lần thử.",
                            code="OTP_INVALID",
                        )
                else:
                    # Khớp mã OTP -> đánh dấu đã sử dụng & kích hoạt trạng thái tài khoản kỹ thuật
                    challenge.used_at = now
                    challenge.save(update_fields=["used_at"])

                    old_status = user.account_status
                    user_updates = []
                    if challenge.channel == OtpChannel.EMAIL:
                        user.email_verified_at = now
                        user_updates.append("email_verified_at")
                    else:
                        user.phone_verified_at = now
                        user_updates.append("phone_verified_at")

                    if not user.is_locked and user.account_status != AccountStatus.ACTIVE:
                        user.account_status = AccountStatus.ACTIVE
                        user_updates.append("account_status")

                    user.save(update_fields=user_updates)

                    if old_status != user.account_status:
                        AccountStatusHistory.objects.create(
                            user=user,
                            old_status=old_status,
                            new_status=user.account_status,
                            changed_by=user,
                            reason=f"Xác minh OTP qua {challenge.get_channel_display()} thành công",
                        )
                    AuditLog.write(
                        user,
                        f"Xác minh OTP ({challenge.channel})",
                        mask_destination(challenge.channel, challenge.destination),
                        note=f"Tư cách hiện tại: {user.club_status}",
                    )
                    verified_challenge = challenge

    if error_to_raise is not None:
        raise error_to_raise
    assert verified_challenge is not None
    return verified_challenge


def _describe_device(user_agent: str) -> str:
    ua = (user_agent or "").lower()
    if not ua:
        return "Trình duyệt Web"
    os_name = "Thiết bị"
    if "windows" in ua:
        os_name = "Windows"
    elif "android" in ua:
        os_name = "Android"
    elif "iphone" in ua or "ipad" in ua:
        os_name = "iOS"
    elif "mac os" in ua or "macintosh" in ua:
        os_name = "macOS"
    elif "linux" in ua:
        os_name = "Linux"

    browser = "Browser"
    if "edg/" in ua:
        browser = "Edge"
    elif "chrome/" in ua and "edg/" not in ua:
        browser = "Chrome"
    elif "firefox/" in ua:
        browser = "Firefox"
    elif "safari/" in ua and "chrome/" not in ua:
        browser = "Safari"
    return f"{browser} trên {os_name}"


def record_login_session(request, user: User) -> UserSession | None:
    """Ghi nhận hoặc cập nhật phiên đăng nhập theo thiết bị sau khi login."""
    if not request.session.session_key:
        request.session.save()
    session_key = request.session.session_key
    if not session_key:
        return None
    ua = (request.META.get("HTTP_USER_AGENT") or "")[:255]
    ip = get_client_ip(request)[:64]
    device_label = _describe_device(ua)
    session_obj, created = UserSession.objects.update_or_create(
        user=user,
        session_key=session_key,
        defaults={
            "device_label": device_label,
            "ip_address": ip,
            "user_agent": ua,
            "last_seen_at": timezone.now(),
            "revoked_at": None,
            "revoked_reason": "",
        },
    )
    return session_obj


@transaction.atomic
def revoke_user_session(
    actor: User,
    session_obj: UserSession,
    reason: str = "Người dùng đăng xuất từ xa",
) -> None:
    """Thu hồi một phiên thiết bị cụ thể và xóa luôn bản ghi Django Session nếu có."""
    if session_obj.revoked_at is None:
        session_obj.revoked_at = timezone.now()
        session_obj.revoked_reason = reason[:160]
        session_obj.save(update_fields=["revoked_at", "revoked_reason"])
    Session.objects.filter(session_key=session_obj.session_key).delete()
    AuditLog.write(
        actor,
        "Thu hồi phiên thiết bị",
        session_obj.user.username,
        note=f"{session_obj.device_label} ({reason})",
    )


@transaction.atomic
def revoke_all_other_sessions(actor: User, current_session_key: str) -> int:
    """Đăng xuất mọi thiết bị khác trừ thiết bị hiện tại."""
    qs = UserSession.objects.filter(user=actor, revoked_at__isnull=True).exclude(
        session_key=current_session_key or ""
    )
    keys = list(qs.values_list("session_key", flat=True))
    count = qs.update(
        revoked_at=timezone.now(),
        revoked_reason="Đăng xuất các thiết bị khác",
    )
    if keys:
        Session.objects.filter(session_key__in=keys).delete()
    if count:
        AuditLog.write(actor, "Thu hồi mọi phiên khác", actor.username, f"{count} thiết bị")
    return count


@transaction.atomic
def issue_email_verification(user: User, request=None) -> str | None:
    """Phát hành mã xác minh email 1 lần qua liên kết (hiệu lực 24h) và gửi email."""
    if not user.email:
        return None
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    EmailVerificationToken.objects.create(
        user=user,
        email=user.email.strip().lower(),
        token_hash=token_hash,
        expires_at=timezone.now() + timezone.timedelta(hours=EMAIL_VERIFY_TTL_HOURS),
    )
    path = reverse("accounts:verify_email", args=[raw_token])
    verify_url = (
        request.build_absolute_uri(path)
        if request is not None
        else f"{settings.SITE_URL}{path}"
    )
    send_mail(
        subject="[KMG Club] Xác minh địa chỉ email tài khoản",
        message=(
            f"Xin chào {user.public_name},\n\n"
            f"Vui lòng nhấn vào liên kết sau để xác minh email tài khoản KMG của bạn "
            f"(hiệu lực trong {EMAIL_VERIFY_TTL_HOURS} giờ):\n{verify_url}\n\n"
            f"Nếu bạn không thực hiện đăng ký này, vui lòng bỏ qua email."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=True,
    )
    return raw_token


@transaction.atomic
def confirm_email_verification(raw_token: str) -> User | None:
    """Xác thực token email; nếu hợp lệ thì kích hoạt `AccountStatus.ACTIVE`."""
    if not raw_token:
        return None
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    token_obj = (
        EmailVerificationToken.objects.select_for_update()
        .select_related("user")
        .filter(token_hash=token_hash)
        .first()
    )
    if token_obj is None or not token_obj.is_usable:
        return None
    now = timezone.now()
    token_obj.used_at = now
    token_obj.save(update_fields=["used_at"])

    user = token_obj.user
    old_status = user.account_status
    user.email_verified_at = now
    if not user.is_locked:
        user.account_status = AccountStatus.ACTIVE
    user.save(update_fields=["email_verified_at", "account_status"])

    AccountStatusHistory.objects.create(
        user=user,
        old_status=old_status,
        new_status=user.account_status,
        changed_by=user,
        reason="Xác minh email thành công",
    )
    AuditLog.write(user, "Xác minh email", user.email)
    return user


@transaction.atomic
def set_account_lock_state(
    actor: User,
    target: User,
    locked: bool,
    reason: str = "",
) -> User:
    """Khóa hoặc mở khóa tài khoản kỹ thuật, thu hồi phiên và ghi lịch sử bất biến."""
    if actor.pk == target.pk:
        raise ValueError("Không thể tự khoá hoặc mở khoá tài khoản của chính mình.")
    old_status = target.account_status
    target.is_locked = locked
    target.save(update_fields=["is_locked"])
    AccountStatusHistory.objects.create(
        user=target,
        old_status=old_status,
        new_status=target.account_status,
        changed_by=actor,
        reason=reason or ("Khoá tài khoản" if locked else "Mở khoá tài khoản"),
    )
    if locked:
        active_sessions = UserSession.objects.filter(user=target, revoked_at__isnull=True)
        keys = list(active_sessions.values_list("session_key", flat=True))
        active_sessions.update(
            revoked_at=timezone.now(),
            revoked_reason=reason or "Tài khoản bị khoá",
        )
        if keys:
            Session.objects.filter(session_key__in=keys).delete()
    AuditLog.write(
        actor,
        "Khoá tài khoản" if locked else "Mở khoá tài khoản",
        target,
        note=reason,
    )
    return target


def resolve_post_login_url(user: User) -> str:
    """
    Bộ điều hướng thông minh sau đăng nhập (Smart Post-Login Router — Master Prompt 3.1 & 6.1):

    1. Thành viên CLB bị tạm khóa (`SUSPENDED`) -> Cổng thông tin hạn chế `/taikhoan/trang-thai/`.
    2. Cố vấn (`ADVISOR` thuần túy, không giữ chức điều hành) -> Dashboard Giám sát `/workspace/giam-sat/`.
    3. Thành viên CLB đã được nâng role VÀ phân Ban (`has_active_club_access`) hoặc Cán bộ đương nhiệm
       (`CHAIRMAN`, `VICE_CHAIRMAN`, `DEPT_HEAD`, `DEPUTY_HEAD`) -> Không gian nội bộ `/workspace/`.
    4. Admin Server thuần túy (`is_server_admin`) -> Bảng Quản trị Tài khoản & Lãnh đạo `/taikhoan/quanly/`.
    5. Khách (`GUEST`) mới đăng ký (kể cả đã xác minh OTP) -> Hệ thống Sự kiện & Đặt vé `/sukien/`.
    """
    if not user or not user.is_authenticated:
        return reverse("events:list")

    cm = user.club_membership_record
    if cm and cm.status == "SUSPENDED":
        return reverse("accounts:membership_status")

    now = timezone.now()
    active_position_codes: set[str] = set()
    if hasattr(user, "appointments"):
        active_position_codes = set(
            user.appointments.filter(is_active=True, ended_at__isnull=True)
            .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=now))
            .values_list("position__code", flat=True)
        )

    executive_or_dept_roles = {
        "CHAIRMAN",
        "VICE_CHAIRMAN",
        "DEPT_HEAD",
        "DEPUTY_HEAD",
        "CORE_MEMBER",
    }
    if "ADVISOR" in active_position_codes and not (
        active_position_codes & executive_or_dept_roles
    ):
        return reverse("organization:advisor_overview")

    if (active_position_codes & executive_or_dept_roles) or (
        cm and cm.status == "ACTIVE" and not user.is_server_admin and user.has_active_club_access
    ) or (
        cm and cm.status == "ACTIVE" and user.is_server_admin
    ):
        return reverse("organization:workspace_home")

    if user.is_server_admin:
        return reverse("accounts:user_list")

    try:
        from django.shortcuts import resolve_url
        return resolve_url(settings.LOGIN_REDIRECT_URL)
    except Exception:
        return reverse("events:list")


# ---------------------------------------------------------------------------
# Tương thích ngược: OTP xác minh Email tài khoản Khách (Sprint 7)
# ---------------------------------------------------------------------------
class OTPError(Exception):
    """Lỗi nghiệp vụ khi gửi / kiểm tra mã. View hiện nguyên văn cho user."""


def _otp_hash(user_id: int, code: str) -> str:
    from django.utils.crypto import salted_hmac
    return salted_hmac("accounts.otp", f"{user_id}:{code}").hexdigest()


def resend_wait_seconds(user: User) -> int:
    from .models import EmailOTP
    last = EmailOTP.objects.filter(user=user).only("created_at").first()
    if last is None:
        return 0
    passed = (timezone.now() - last.created_at).total_seconds()
    resend_sec = getattr(settings, "OTP_RESEND_SECONDS", 60)
    return max(int(resend_sec - passed), 0)


def send_email_otp(user: User):
    from notifications.services import send_templated_email
    from .models import EmailOTP
    if not user.email:
        raise OTPError("Tài khoản chưa có email để nhận mã.")
    if user.email_verified_at:
        raise OTPError("Email của bạn đã được xác minh.")
    wait = resend_wait_seconds(user)
    if wait:
        raise OTPError(f"Vui lòng chờ {wait} giây rồi gửi lại mã.")
    hour_ago = timezone.now() - timezone.timedelta(hours=1)
    max_per_hour = getattr(settings, "OTP_MAX_PER_HOUR", 5)
    if EmailOTP.objects.filter(user=user, created_at__gte=hour_ago).count() >= max_per_hour:
        raise OTPError("Bạn đã yêu cầu quá nhiều mã. Vui lòng thử lại sau 1 giờ.")

    code = f"{secrets.randbelow(10 ** 6):06d}"
    with transaction.atomic():
        EmailOTP.objects.filter(user=user, used_at__isnull=True).update(used_at=timezone.now())
        otp = EmailOTP.objects.create(user=user, code_hash=_otp_hash(user.pk, code))

    ttl = getattr(settings, "OTP_TTL_MINUTES", 10)
    title = "Mã xác minh email"
    try:
        send_templated_email("notice", {
            "user": user, "site_url": settings.SITE_URL, "title": title,
            "message": f"Mã xác minh của bạn là {code}. Mã có hiệu lực trong {ttl} phút.",
            "details": [("Mã xác minh", code)],
            "note": "Không chia sẻ mã này cho bất kỳ ai, kể cả người xưng là BTC. "
                    "Nếu bạn không tạo tài khoản KMG Club, hãy bỏ qua email này.",
        }, [user.email])
    except Exception:
        logger.exception("Gửi mã OTP cho user %s thất bại", user.pk)
        otp.delete()
        raise OTPError("Không gửi được email lúc này. Vui lòng thử lại sau ít phút.")
    return otp


def verify_email_otp(user: User, code: str) -> None:
    code = (code or "").strip().replace(" ", "")
    if not code:
        raise OTPError("Vui lòng nhập mã xác minh 6 số.")
    if len(code) != 6 or not code.isdigit():
        raise OTPError("Mã xác minh phải gồm đúng 6 chữ số.")
    error = _check_legacy_email_otp(user, code)
    if error:
        raise OTPError(error)


@transaction.atomic
def _check_legacy_email_otp(user: User, code: str) -> str:
    from .models import EmailOTP
    otp = (EmailOTP.objects.select_for_update()
           .filter(user=user, used_at__isnull=True).first())
    if otp is None or otp.is_expired:
        return "Mã đã hết hạn hoặc chưa được gửi. Bấm \"Gửi mã\" để nhận mã mới."
    if not (len(code) == 6 and code.isdigit()
            and hmac.compare_digest(otp.code_hash, _otp_hash(user.pk, code))):
        otp.attempts += 1
        max_att = getattr(settings, "OTP_MAX_ATTEMPTS", 5)
        left = max_att - otp.attempts
        if left <= 0:
            otp.used_at = timezone.now()
        otp.save(update_fields=["attempts", "used_at"])
        if left <= 0:
            return "Nhập sai quá nhiều lần. Mã đã bị huỷ, vui lòng gửi mã mới."
        return f"Mã không đúng. Bạn còn {left} lần thử."

    now = timezone.now()
    otp.used_at = now
    otp.save(update_fields=["used_at"])
    user.email_verified_at = now
    user.save(update_fields=["email_verified_at"])
    AuditLog.write(user, "Xác minh email", user.username, user.email)
    return ""
