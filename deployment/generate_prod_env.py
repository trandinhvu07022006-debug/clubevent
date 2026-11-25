"""
Sinh tệp .env.production với các khóa mật mã độc lập an toàn (SEC-07) từ .env.production.example.
Tệp .env.production được loại trừ trong .gitignore, tuyệt đối không commit lên Git.

Chạy:
  python deployment/generate_prod_env.py
"""
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
EXAMPLE_PATH = BASE_DIR / ".env.production.example"
TARGET_PATH = BASE_DIR / ".env.production"

SECRET_KEYS = {
    "SECRET_KEY",
    "CERT_SIGNING_KEY",
    "CHAT_MASTER_KEK",
    "DB_PASSWORD",
    "MYSQL_ROOT_PASSWORD",
}


def generate_production_env(overwrite: bool = False) -> Path:
    if TARGET_PATH.exists() and not overwrite:
        return TARGET_PATH

    lines = EXAMPLE_PATH.read_text(encoding="utf-8").splitlines()
    out_lines = []
    for line in lines:
        stripped = line.strip()
        if "=" in line and not stripped.startswith("#"):
            key, _, val = line.partition("=")
            key_name = key.strip()
            if key_name in SECRET_KEYS and not val.strip():
                token = secrets.token_urlsafe(48) if "KEY" in key_name or "KEK" in key_name else secrets.token_urlsafe(24)
                out_lines.append(f"{key_name}={token}")
                continue
        out_lines.append(line)

    TARGET_PATH.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return TARGET_PATH


if __name__ == "__main__":
    path = generate_production_env(overwrite=False)
    print(f"Đã sẵn sàng cấu hình Production bảo mật tại: {path.name} (đã chặn commit bởi .gitignore).")
