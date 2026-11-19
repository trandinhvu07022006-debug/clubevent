"""Môi trường thử local riêng; không đọc .env hoặc dùng DB/kho tệp mặc định."""
import json
import os
from pathlib import Path
import secrets

from django.core.exceptions import ImproperlyConfigured

_local_root = Path(__file__).resolve().parent.parent / ".local-pilot"
_local_root.mkdir(exist_ok=True)
_keys_path = _local_root / "keys.json"
_key_names = ("SECRET_KEY", "CERT_SIGNING_KEY", "CHAT_MASTER_KEK")
if not _keys_path.exists():
    if (_local_root / "db.sqlite3").exists():
        raise ImproperlyConfigured("Thiếu .local-pilot/keys.json của CSDL cũ. Khôi phục khóa gốc trước khi chạy.")
    with _keys_path.open("x", encoding="utf-8") as _key_file:
        _keys_path.chmod(0o600)
        json.dump({name: secrets.token_urlsafe(48) for name in _key_names}, _key_file)
_local_keys = json.loads(_keys_path.read_text(encoding="utf-8"))
if any(not isinstance(_local_keys.get(name), str) or len(_local_keys[name]) < 32 for name in _key_names):
    raise ImproperlyConfigured("Khóa local không hợp lệ; khôi phục keys.json gốc.")

os.environ.update({
    **{name: _local_keys[name] for name in _key_names},
    "KMG_ENV_FILE": "", "DEBUG": "True",
    "ALLOW_DEMO_SEED": str(not (_local_root / "roster-customized.lock").exists()),
    "DB_ENGINE": "sqlite", "DATABASE_URL": "", "CACHE_URL": "",
    "ALLOWED_HOSTS": "localhost,127.0.0.1", "USE_HTTPS": "False",
    "TRUST_PROXY_HEADERS": "False", "TRUST_X_FORWARDED_FOR": "False",
    "CSRF_TRUSTED_ORIGINS": "", "LOG_ROOT": str(_local_root / "logs"),
    "MEDIA_ROOT": str(_local_root / "media"),
    "PRIVATE_VAULT_ROOT": str(_local_root / "private_vault"),
    "STATIC_ROOT": str(_local_root / "staticfiles"),
    "EMAIL_BACKEND": "django.core.mail.backends.console.EmailBackend",
    "SMS_PROVIDER": "console", "SMS_API_KEY": "", "SMS_WEBHOOK_URL": "",
    "AI_PROVIDER": "mock", "AI_API_KEY": "",
    "SITE_URL": os.environ.get("KMG_LOCAL_SITE_URL", "http://127.0.0.1:8001"),
})

from .settings import *  # noqa: E402,F401,F403

DATABASES["default"]["NAME"] = _local_root / "db.sqlite3"
DATABASES["default"]["TEST"] = {"NAME": _local_root / "test.sqlite3"}
EMAIL_HOST_USER = EMAIL_HOST_PASSWORD = ""
LOG_TO_CONSOLE = True
