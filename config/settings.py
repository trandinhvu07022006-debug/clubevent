"""
Cấu hình Django cho hệ thống hỗ trợ tổ chức sự kiện CLB sinh viên.

Mọi thông tin bí mật (SECRET_KEY, mật khẩu DB, API key AI) đọc từ biến
môi trường trong file .env — KHÔNG hard-code, KHÔNG commit lên Git.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env(key, default=None):
    """Đọc biến môi trường, có giá trị mặc định cho môi trường dev."""
    return os.environ.get(key, default)


def env_bool(key, default=False):
    """Đọc biến môi trường dạng boolean."""
    return str(env(key, str(default))).lower() in ("1", "true", "yes", "on")


# --- Đọc file .env thủ công (không cần thư viện ngoài) ---
_env_file = BASE_DIR / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())

SECRET_KEY = env("SECRET_KEY", "dev-only-doi-key-nay-truoc-khi-deploy")
DEBUG = env_bool("DEBUG", True)
ALLOWED_HOSTS = [h for h in env("ALLOWED_HOSTS", "*").split(",") if h]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # App nghiệp vụ, mỗi app ứng với 1 module trong SRS
    "accounts",       # M1 - Tài khoản & phân quyền
    "events",         # M2 - Quản lý sự kiện
    "organizing",     # M3 - Phân công công việc BTC
    "registrations",  # M4 + M5 - Đăng ký vé & Check-in
    "feedback",       # M6 - Phản hồi & thống kê
    "aiassist",       # Tích hợp AI
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise cho phép Django tự phục vụ file static khi DEBUG=False.
    # Không có nó thì lên host thật là mất sạch CSS/JS.
    # Bắt buộc đặt NGAY SAU SecurityMiddleware.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Cơ sở dữ liệu ---
# Chọn loại DB bằng biến DB_ENGINE trong .env:
#   mysql    - môi trường phát triển và demo (mặc định)
#   postgres - môi trường triển khai, vì host free thường chỉ có Postgres
#   sqlite   - chạy nhanh không cần cài gì, dùng cho frontend và unit test
#
# Nhờ dùng Django ORM nên đổi DB KHÔNG phải sửa một dòng code nghiệp vụ nào.
# Cả MySQL và PostgreSQL đều hỗ trợ SELECT ... FOR UPDATE nên phần chống
# race condition khi đặt vé hoạt động như nhau.
#
# CẢNH BÁO: đừng dùng SQLite khi demo. SQLite khoá toàn bộ file DB chứ không
# khoá theo dòng, nên không thể hiện đúng cơ chế chống race condition.
DB_ENGINE = env("DB_ENGINE", "mysql")

if DB_ENGINE == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
elif DB_ENGINE == "postgres":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("DB_NAME", "clubevent"),
            "USER": env("DB_USER", "postgres"),
            "PASSWORD": env("DB_PASSWORD", ""),
            "HOST": env("DB_HOST", "127.0.0.1"),
            "PORT": env("DB_PORT", "5432"),
        }
    }
else:
    import pymysql

    pymysql.install_as_MySQLdb()
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": env("DB_NAME", "clubevent"),
            "USER": env("DB_USER", "root"),
            "PASSWORD": env("DB_PASSWORD", ""),
            "HOST": env("DB_HOST", "127.0.0.1"),
            "PORT": env("DB_PORT", "3306"),
            "OPTIONS": {
                "charset": "utf8mb4",
                "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }
    }

# Nhiều host free cấp sẵn biến DATABASE_URL thay vì từng biến rời.
# Đọc luôn cho tiện, đỡ phải điền tay 5 biến trên dashboard.
_db_url = env("DATABASE_URL", "")
if _db_url:
    from urllib.parse import unquote, urlparse

    _u = urlparse(_db_url)
    _engines = {
        "postgres": "django.db.backends.postgresql",
        "postgresql": "django.db.backends.postgresql",
        "mysql": "django.db.backends.mysql",
    }
    if _u.scheme in _engines:
        DATABASES["default"] = {
            "ENGINE": _engines[_u.scheme],
            "NAME": (_u.path or "/").lstrip("/"),
            "USER": unquote(_u.username or ""),
            "PASSWORD": unquote(_u.password or ""),
            "HOST": _u.hostname or "",
            "PORT": str(_u.port or ""),
        }

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Mật khẩu băm bằng bcrypt. Cả bcrypt và PBKDF2 đều là hàm băm CHẬM và có
# SALT — đúng yêu cầu cho mật khẩu. Tuyệt đối không dùng MD5/SHA1 vì chúng
# nhanh, nên dò mật khẩu bằng brute-force rất dễ.
#
# Dò xem máy đã cài thư viện bcrypt chưa. Nếu chưa thì dùng PBKDF2 có sẵn
# trong Django để dự án vẫn chạy được — tránh cảnh bạn nào quên
# `pip install -r requirements.txt` là không chạy nổi.
try:
    import bcrypt  # noqa: F401

    PASSWORD_HASHERS = [
        "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
        "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    ]
except ImportError:
    PASSWORD_HASHERS = [
        "django.contrib.auth.hashers.PBKDF2PasswordHasher",
        "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    ]

LANGUAGE_CODE = "vi"
TIME_ZONE = "Asia/Ho_Chi_Minh"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
# Nơi `python manage.py collectstatic` gom toàn bộ file static về, để
# WhiteNoise phục vụ khi deploy. Không commit thư mục này (đã có trong
# .gitignore), nó được sinh lại mỗi lần deploy.
STATIC_ROOT = BASE_DIR / "staticfiles"

# WhiteNoise nén file và thêm mã băm vào tên file (manifest) để browser
# cache lâu mà vẫn nhận được bản mới khi ta sửa CSS.
# Chỉ bật khi deploy, vì ở chế độ dev nó bắt buộc phải collectstatic trước
# mới chạy được, rất bất tiện khi đang sửa giao diện.
if not DEBUG:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "events:list"
LOGOUT_REDIRECT_URL = "events:list"

# --- Quy tắc nghiệp vụ (đưa ra đây để dễ sửa và dễ test) ---
MAX_TICKETS_PER_USER_PER_EVENT = 4   # F4.1 - tối đa 4 vé/người/sự kiện
PAYMENT_DEADLINE_HOURS = 24          # F4.5 - vé chờ thanh toán quá 24h thì huỷ
CANCEL_BEFORE_HOURS = 24             # F4.3 - huỷ vé trước giờ diễn ra 24h
FEEDBACK_WINDOW_DAYS = 7             # F6.1 - gửi đánh giá trong 7 ngày

# --- Tích hợp AI ---
AI_PROVIDER = env("AI_PROVIDER", "gemini")   # gemini | openai | mock
AI_API_KEY = env("AI_API_KEY", "")           # để trong .env, không commit
AI_MODEL = env("AI_MODEL", "gemini-2.0-flash")
AI_TIMEOUT_SECONDS = int(env("AI_TIMEOUT_SECONDS", "20"))

# --- Bảo mật khi deploy thật (DEBUG=False) ---
if not DEBUG:
    SECURE_CONTENT_TYPE_NOSNIFF = True   # chặn browser tự đoán kiểu file
    SESSION_COOKIE_HTTPONLY = True       # JavaScript không đọc được cookie session
    CSRF_COOKIE_HTTPONLY = True
    X_FRAME_OPTIONS = "DENY"             # chống clickjacking (nhúng site vào iframe)

    # Các thiết lập dưới đây CHỈ bật khi site đã có HTTPS thật.
    # Bật khi chưa có SSL sẽ làm site không truy cập được, nên để qua .env.
    # Khi deploy có HTTPS thì thêm vào .env: USE_HTTPS=True
    if env_bool("USE_HTTPS", False):
        SECURE_SSL_REDIRECT = True       # tự chuyển http -> https
        SESSION_COOKIE_SECURE = True     # cookie chỉ gửi qua https
        CSRF_COOKIE_SECURE = True
        SECURE_HSTS_SECONDS = 31536000   # 1 năm, buộc browser luôn dùng https
        SECURE_HSTS_INCLUDE_SUBDOMAINS = True
        SECURE_HSTS_PRELOAD = True
