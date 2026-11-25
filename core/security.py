"""
Các tiện ích bảo mật dùng chung toàn hệ thống:
- SEC-02: Chống CSV Formula Injection (Excel / LibreOffice Calc / Google Sheets).
- SEC-06: Giới hạn tần suất (Rate Limiting) dựa trên Cache + IP + Định danh,
  chống vượt rào bằng cách bỏ cookie `sessionid`.
"""
from __future__ import annotations

from decimal import Decimal
import hashlib
import logging
import threading
import time
import uuid
from typing import Iterable

from django.conf import settings
from django.core.cache import cache, caches
from django.core.cache.backends.locmem import LocMemCache
from django.core.cache.backends.redis import RedisCache

logger = logging.getLogger(__name__)
_rate_locks = [threading.RLock() for _ in range(64)]
# Lua thực hiện trọn cửa sổ trượt trong một thao tác Redis nguyên tử, dùng
# đồng hồ Redis để không lệch thời gian giữa các Gunicorn worker/máy chủ.
_RATE_SCRIPT = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
local window = tonumber(ARGV[1])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
local count = redis.call('ZCARD', KEYS[1])
local limit = tonumber(ARGV[2])
if limit >= 0 and count >= limit then return 1 end
if ARGV[3] == '1' then
    redis.call('ZADD', KEYS[1], now, ARGV[4])
    redis.call('EXPIRE', KEYS[1], window)
end
return 0
"""

# Các ký tự mở đầu công thức nguy hiểm trên phần mềm bảng tính
_DANGEROUS_CSV_PREFIXES = ("=", "+", "-", "@")
_DANGEROUS_CSV_CONTROL = ("\t", "\r", "\n")


def safe_csv_cell(value):
    """
    Làm sạch một ô trước khi ghi ra file CSV (SEC-02).

    - Giữ nguyên kiểu số (`int`, `float`, `Decimal`) để Excel vẫn cộng/trừ được
      (kể cả số âm như chênh lệch ngân sách `-100000`).
    - Với chuỗi ký tự do người dùng nhập: nếu bắt đầu bằng `=`, `+`, `-`, `@`
      (kể cả có khoảng trắng dẫn đầu) hoặc ký tự điều khiển tab/CR/LF thì thêm
      dấu nháy đơn `'` ở đầu để vô hiệu hóa thực thi công thức.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Có" if value else "Không"
    if isinstance(value, (int, float, Decimal)):
        return value
    text = str(value)
    if not text:
        return ""
    stripped = text.lstrip(" ")
    if text[0] in _DANGEROUS_CSV_CONTROL or (
        stripped and stripped[0] in _DANGEROUS_CSV_PREFIXES
    ):
        return f"'{text}"
    return text


def safe_csv_row(values: Iterable) -> list:
    """Làm sạch toàn bộ một dòng dữ liệu trước khi truyền vào `csv.writer.writerow`."""
    return [safe_csv_cell(v) for v in values]


def get_client_ip(request) -> str:
    """
    Trích xuất địa chỉ IP máy khách một cách an toàn.

    Chỉ tin header `X-Forwarded-For` khi đứng sau Reverse Proxy tin cậy
    (`TRUST_X_FORWARDED_FOR=True`), tránh kẻ tấn công tự giả mạo header để né
    rate-limit.
    """
    if getattr(settings, "TRUST_X_FORWARDED_FOR", False):
        xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if xff:
            return xff.split(",")[0].strip()
    return (request.META.get("REMOTE_ADDR") or "unknown").strip()


def _rate_cache_key(scope: str, ip: str, identifier: str = "") -> str:
    raw = f"{scope}|{ip}|{(identifier or '').strip().lower()}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return f"kmg_rl:{scope}:{digest}"


def _active_timestamps(key: str, window_seconds: int, now: float | None = None) -> list[float]:
    now = time.time() if now is None else now
    stamps = cache.get(key) or []
    return [t for t in stamps if now - t < window_seconds]


def _rate_event(key: str, window_seconds: int, limit: int, record: bool) -> bool:
    if window_seconds <= 0:
        raise ValueError("window_seconds phải lớn hơn 0")
    backend = caches["default"]
    if isinstance(backend, RedisCache):
        # Adapter dành cho backend Redis tích hợp Django 5.2; tách namespace
        # khỏi danh sách timestamp cũ để nâng cấp không gây WRONGTYPE.
        redis_key = backend.make_and_validate_key(f"rl-v2:{key}")
        client = backend._cache.get_client(redis_key, write=True)
        return bool(client.eval(
            _RATE_SCRIPT, 1, redis_key, window_seconds, limit,
            "1" if record else "0", uuid.uuid4().hex,
        ))
    if not isinstance(backend, LocMemCache):
        raise RuntimeError("Rate limit yêu cầu Redis hoặc LocMemCache dành cho dev/test")
    # LocMem chỉ dùng dev/test; khóa bao cả đọc–sửa–ghi giữa các thread.
    lock = _rate_locks[int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % len(_rate_locks)]
    with lock:
        now = time.time()
        stamps = _active_timestamps(key, window_seconds, now=now)
        if limit >= 0 and len(stamps) >= limit:
            return True
        if record:
            stamps.append(now)
            cache.set(key, stamps, timeout=window_seconds)
        return False


def is_rate_limited(
    request,
    scope: str,
    limit: int,
    window_seconds: int,
    identifier: str = "",
    record: bool = True,
    per_ip: bool = True,
) -> bool:
    """
    Kiểm tra (và ghi nhận nếu chưa vượt ngưỡng) giới hạn tần suất theo IP + scope (SEC-06).

    Trả về `True` nếu đã chạm/vượt ngưỡng `limit` trong `window_seconds`.
    `per_ip=False` thì đếm chung cho mọi IP (ví dụ theo tài khoản).
    """
    ip = get_client_ip(request) if per_ip else "*"
    key = _rate_cache_key(scope, ip, identifier)
    try:
        return _rate_event(key, window_seconds, limit, record)
    except Exception as exc:
        # Không mở cửa bỏ qua chống spam khi Redis mất kết nối, không log URL/secret.
        logger.warning("Rate limit unavailable: %s", type(exc).__name__)
        return True


def reset_global_rate_limit(scope: str, identifier: str) -> None:
    """Xoá bộ đếm đã tạo bằng `is_rate_limited(..., per_ip=False)`."""
    key = _rate_cache_key(scope, "*", identifier)
    try:
        backend = caches["default"]
        if isinstance(backend, RedisCache):
            redis_key = backend.make_and_validate_key(f"rl-v2:{key}")
            backend._cache.get_client(redis_key, write=True).delete(redis_key)
        else:
            cache.delete(key)
    except Exception as exc:
        # Không xoá được thì bộ đếm tự hết hạn, không làm hỏng việc đăng nhập
        logger.warning("Rate reset unavailable: %s", type(exc).__name__)


def record_rate_event(
    request,
    scope: str,
    window_seconds: int,
    identifier: str = "",
) -> None:
    """Chỉ ghi nhận 1 lượt tiêu thụ hạn mức (dùng cho ngân sách AI sau khi gọi thành công)."""
    ip = get_client_ip(request)
    key = _rate_cache_key(scope, ip, identifier)
    try:
        _rate_event(key, window_seconds, limit=-1, record=True)
    except Exception as exc:
        logger.warning("Rate event unavailable: %s", type(exc).__name__)
