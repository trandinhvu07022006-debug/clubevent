"""
Cổng gửi tin nhắn SMS OTP đa chế độ (`console` / `webhook`) cho KMG Club Platform.

- Ở môi trường phát triển & kiểm thử tự động (`SMS_PROVIDER=console`):
  Ghi nội dung SMS ra log console và lưu vào `SMS_OUTBOX` (tương tự `django.core.mail.outbox`,
  tự động xoá sạch trước mỗi test method qua `KMGTestRunner`).
- Ở môi trường triển khai thật (`SMS_PROVIDER=webhook`):
  Gửi HTTP POST JSON có xác thực `Bearer <SMS_API_KEY>` và `timeout` chặt chẽ tới
  SMS Gateway (SpeedSMS / eSMS / Twilio / Webhook nội bộ).
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from django.conf import settings
from django.utils import timezone

from .models import normalize_phone_number

logger = logging.getLogger(__name__)

# Hộp thư SMS phục vụ kiểm thử tự động & chẩn đoán ở chế độ console
SMS_OUTBOX: list[dict] = []


def clear_sms_outbox() -> None:
    """Làm sạch bộ nhớ SMS Outbox trước mỗi ca kiểm thử độc lập."""
    SMS_OUTBOX.clear()


def send_sms_otp(phone: str, code: str, user=None) -> bool:
    """
    Gửi mã OTP 6 chữ số tới số điện thoại của người dùng.
    Trả về `True` nếu đã chuyển giao thành công cho provider cấu hình.
    """
    norm_phone = normalize_phone_number(phone) or (phone or "").strip()
    if not norm_phone:
        return False

    ttl_min = getattr(settings, "OTP_EXPIRY_MINUTES", 10)
    sender_id = getattr(settings, "SMS_SENDER_ID", "KMG-CLUB")
    provider = getattr(settings, "SMS_PROVIDER", "console").lower()
    message = (
        f"[{sender_id}] Ma xac minh OTP tai khoan KMG cua ban la {code} "
        f"(hieu luc {ttl_min} phut). Tuyet doi khong chia se ma nay cho bat ky ai."
    )

    record = {
        "to": norm_phone,
        "raw_phone": phone,
        "sender": sender_id,
        "code": code,
        "message": message,
        "provider": provider,
        "user_id": getattr(user, "pk", None),
        "sent_at": timezone.now().isoformat(),
    }

    if provider == "webhook":
        webhook_url = getattr(settings, "SMS_WEBHOOK_URL", "").strip()
        api_key = getattr(settings, "SMS_API_KEY", "").strip()
        timeout_sec = int(getattr(settings, "SMS_TIMEOUT_SECONDS", 8))
        if not webhook_url:
            logger.warning("SMS_PROVIDER=webhook nhưng chưa cấu hình SMS_WEBHOOK_URL.")
            return False
        payload = json.dumps(
            {
                "to": norm_phone,
                "sender": sender_id,
                "message": message,
                "otp": code,
            }
        ).encode("utf-8")
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        req = urllib.request.Request(
            webhook_url, data=payload, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                return 200 <= getattr(resp, "status", 200) < 300
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            logger.warning("Gửi SMS OTP qua webhook thất bại: %s", type(exc).__name__)
            return False

    if provider != "console":
        logger.warning("SMS provider không được hỗ trợ; từ chối gửi OTP.")
        return False

    # Chế độ console / sandbox chỉ được chọn tường minh.
    SMS_OUTBOX.append(record)
    if len(SMS_OUTBOX) > 200:
        del SMS_OUTBOX[:-200]
    logger.info("[KMG SMS OTP -> %s] %s", norm_phone, message)
    return True
