"""Cấu hình kiểm thử cách ly: không đọc .env hay ghi vào kho tệp đang sử dụng.

Mặc định dùng SQLite tạm. CI dùng KMG_TEST_DB_ENGINE=mysql và các biến
KMG_TEST_DB_* trỏ tới MySQL dành riêng cho kiểm thử.
"""
import os
import tempfile
from pathlib import Path

_test_storage = tempfile.TemporaryDirectory(prefix="kmg-tests-", ignore_cleanup_errors=True)
_test_root = Path(_test_storage.name)

# Đặt trước khi import settings để không đọc cấu hình hoặc tạo thư mục thật.
os.environ.update({
    "KMG_ENV_FILE": "",
    "DEBUG": "True",
    "SECRET_KEY": "test-only-secret-key-not-for-production-01234567890123456789",
    "CERT_SIGNING_KEY": "test-only-certificate-key",
    "CHAT_MASTER_KEK": "test-only-chat-key",
    "DATABASE_URL": "",
    "CACHE_URL": "",
    "DB_ENGINE": os.environ.get("KMG_TEST_DB_ENGINE", "sqlite"),
    "DB_NAME": os.environ.get("KMG_TEST_DB_NAME", "kmg_ci"),
    "DB_HOST": os.environ.get("KMG_TEST_DB_HOST", "127.0.0.1"),
    "DB_PORT": os.environ.get("KMG_TEST_DB_PORT", "3306"),
    "DB_USER": os.environ.get("KMG_TEST_DB_USER", "root"),
    "DB_PASSWORD": os.environ.get("KMG_TEST_DB_PASSWORD", ""),
    "MEDIA_ROOT": str(_test_root / "media"),
    "PRIVATE_VAULT_ROOT": str(_test_root / "private_vault"),
    "LOG_ROOT": str(_test_root / "logs"),
    "USE_HTTPS": "False",
    "TRUST_PROXY_HEADERS": "False",
    "TRUST_X_FORWARDED_FOR": "False",
})

from .settings import *  # noqa: E402,F401,F403

ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
MEDIA_ROOT = _test_root / "media"
PRIVATE_VAULT_ROOT = _test_root / "private_vault"
STATIC_ROOT = _test_root / "staticfiles"
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
SMS_PROVIDER = "console"
AI_PROVIDER = "mock"
AI_API_KEY = ""
SMS_API_KEY = ""
SMS_WEBHOOK_URL = ""
ALLOW_DEMO_SEED = True
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
if DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
    DATABASES["default"]["NAME"] = _test_root / "base.sqlite3"
    DATABASES["default"]["TEST"] = {"NAME": _test_root / "test.sqlite3"}
else:
    DATABASES["default"]["TEST"] = {
        "NAME": os.environ.get("KMG_TEST_DB_TEST_NAME", "test_kmg_ci"),
        "CHARSET": "utf8mb4",
    }
