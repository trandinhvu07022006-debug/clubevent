"""
F1.7 - Xác minh email bằng mã OTP.

Vì sao cần: tài khoản Khách ai cũng tạo được online, mỗi tài khoản đặt tối
đa 4 vé. Không xác minh gì thì một người tạo 10 tài khoản bằng email bịa là
gom được 40 vé rồi bán lại giá cao. Bắt nhận mã qua email thật làm việc tạo
tài khoản ảo tốn công hơn nhiều, và mỗi tài khoản gắn với một hộp thư thật
để BTC truy vết khi có tranh chấp.

Các lớp chống dò mã / spam:
  - Mã 6 số ngẫu nhiên (secrets), chỉ lưu bản băm HMAC.
  - Hết hạn sau OTP_TTL_MINUTES phút, dùng xong là bỏ.
  - Nhập sai OTP_MAX_ATTEMPTS lần thì mã bị huỷ, phải xin mã mới.
  - Gửi lại cách nhau OTP_RESEND_SECONDS giây, tối đa OTP_MAX_PER_HOUR mã/giờ.
    Dò hết 10^6 mã với 5 lần thử x 5 mã mỗi giờ là không khả thi.
"""
from __future__ import annotations

import hmac
import logging
import secrets
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac

from notifications.services import send_templated_email

from .models import AuditLog, EmailOTP

if TYPE_CHECKING:
    from .models import User

logger = logging.getLogger(__name__)


class OTPError(Exception):
    """Lỗi nghiệp vụ khi gửi / kiểm tra mã. View hiện nguyên văn cho user."""


def _hash(user_id: int, code: str) -> str:
    # Gắn user_id vào để cùng một mã 6 số ở 2 user cho ra 2 bản băm khác nhau
    return salted_hmac("accounts.otp", f"{user_id}:{code}").hexdigest()


def resend_wait_seconds(user: User) -> int:
    """Còn bao nhiêu giây nữa mới được gửi mã mới (0 = gửi được ngay)."""
    last = EmailOTP.objects.filter(user=user).only("created_at").first()
    if last is None:
        return 0
    passed = (timezone.now() - last.created_at).total_seconds()
    return max(int(settings.OTP_RESEND_SECONDS - passed), 0)


def send_email_otp(user: User) -> EmailOTP:
    """
    Sinh mã mới, vô hiệu mã cũ và gửi qua email. Gửi mail ĐỒNG BỘ vì người
    dùng đang đứng chờ mã; SMTP lỗi thì báo lỗi luôn chứ không nuốt.
    """
    if not user.email:
        raise OTPError("Tài khoản chưa có email để nhận mã.")
    if user.email_verified_at:
        raise OTPError("Email của bạn đã được xác minh.")
    wait = resend_wait_seconds(user)
    if wait:
        raise OTPError(f"Vui lòng chờ {wait} giây rồi gửi lại mã.")
    hour_ago = timezone.now() - timezone.timedelta(hours=1)
    if EmailOTP.objects.filter(user=user, created_at__gte=hour_ago).count() \
            >= settings.OTP_MAX_PER_HOUR:
        raise OTPError("Bạn đã yêu cầu quá nhiều mã. Vui lòng thử lại sau 1 giờ.")

    code = f"{secrets.randbelow(10 ** 6):06d}"
    with transaction.atomic():
        EmailOTP.objects.filter(user=user, used_at__isnull=True).update(
            used_at=timezone.now())
        otp = EmailOTP.objects.create(user=user, code_hash=_hash(user.pk, code))

    title = "Mã xác minh email"
    try:
        send_templated_email("notice", {
            "user": user, "site_url": settings.SITE_URL, "title": title,
            "message": f"Mã xác minh của bạn là {code}. "
                       f"Mã có hiệu lực trong {settings.OTP_TTL_MINUTES} phút.",
            "details": [("Mã xác minh", code)],
            "note": "Không chia sẻ mã này cho bất kỳ ai, kể cả người xưng là BTC. "
                    "Nếu bạn không tạo tài khoản KMG Club, hãy bỏ qua email này.",
        }, [user.email])
    except Exception:
        logger.exception("Gửi mã OTP cho user %s thất bại", user.pk)
        # Xoá để lần bấm "Gửi lại" không bị tính chờ / tính vào hạn mức
        otp.delete()
        raise OTPError("Không gửi được email lúc này. Vui lòng thử lại sau ít phút.")
    return otp


def verify_email_otp(user: User, code: str) -> None:
    """Kiểm tra mã. Đúng thì đánh dấu email đã xác minh; sai thì ném OTPError."""
    # Ném lỗi SAU khi transaction đã commit: ném bên trong atomic thì lần
    # đếm sai bị rollback theo, kẻ dò mã sẽ được thử vô hạn.
    error = _check_otp(user, (code or "").strip().replace(" ", ""))
    if error:
        raise OTPError(error)


@transaction.atomic
def _check_otp(user: User, code: str) -> str:
    """Trả "" nếu mã đúng (và đã ghi nhận xác minh), ngược lại trả lý do."""
    # Khoá dòng mã: 2 request nhập mã song song không được cộng dồn sai lệch
    otp = (EmailOTP.objects.select_for_update()
           .filter(user=user, used_at__isnull=True).first())
    if otp is None or otp.is_expired:
        return "Mã đã hết hạn hoặc chưa được gửi. Bấm \"Gửi mã\" để nhận mã mới."
    if not (len(code) == 6 and code.isdigit()
            and hmac.compare_digest(otp.code_hash, _hash(user.pk, code))):
        otp.attempts += 1
        left = settings.OTP_MAX_ATTEMPTS - otp.attempts
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
