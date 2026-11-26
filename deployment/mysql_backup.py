"""
Công cụ sao lưu & khôi phục chuẩn cho MySQL 8.4 độc lập (ngoài Docker Compose).

- Sử dụng `mysqldump --single-transaction --routines --triggers --hex-blob --set-gtid-purged=OFF`
  với `MYSQL_PWD` truyền qua biến môi trường (không lộ mật khẩu trong args/logs).
- Tự động phát hiện `mysqldump` / `mysql` trong PATH hoặc thư mục MySQL Server 8.4 trên Windows.
- Đóng gói kèm `media/` và `private_vault/` qua `deployment.volume_archive`, ghi `manifest.json`
  chứa mã băm SHA-256 + dấu vân tay khóa (không bao giờ lưu `.env` hoặc khóa thô).
- Chỉ cho phép khôi phục vào CSDL đích trống / mới tạo (không ghi đè DB đang chạy).
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from deployment import backup_restore as compose_backups
from deployment import volume_archive

WIN_MYSQL_BIN = Path(r"C:\Program Files\MySQL\MySQL Server 8.4\bin")


def resolve_mysql_tool(binary_name: str) -> str:
    found = shutil.which(binary_name)
    if found:
        return found
    for suffix in (".exe", ""):
        cand = WIN_MYSQL_BIN / f"{binary_name}{suffix}"
        if cand.exists():
            return str(cand)
    raise FileNotFoundError(f"Không tìm thấy công cụ MySQL `{binary_name}` trong PATH hoặc `{WIN_MYSQL_BIN}`.")


def _mysql_env(password: str) -> dict[str, str]:
    env = dict(os.environ)
    env["MYSQL_PWD"] = password or ""
    return env


def create_mysql_backup(
    *,
    destination: str | Path,
    db_name: str,
    db_user: str,
    db_password: str,
    db_host: str = "127.0.0.1",
    db_port: str = "3306",
    media_root: str | Path,
    vault_root: str | Path,
    key_env: dict[str, str] | None = None,
) -> Path:
    dest = Path(destination).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    mysqldump_bin = resolve_mysql_tool("mysqldump")
    sql_path = dest / "database.sql"
    media_arc = dest / "media.tar.gz"
    vault_arc = dest / "private_vault.tar.gz"

    dump_cmd = [
        mysqldump_bin,
        "--protocol=TCP",
        f"--host={db_host}",
        f"--port={db_port}",
        f"--user={db_user}",
        "--single-transaction",
        "--quick",
        "--routines",
        "--triggers",
        "--hex-blob",
        "--no-tablespaces",
        "--set-gtid-purged=OFF",
        db_name,
    ]
    with sql_path.open("wb") as sql_out:
        subprocess.run(dump_cmd, env=_mysql_env(db_password), stdout=sql_out, check=True)

    m_root = Path(media_root)
    m_root.mkdir(parents=True, exist_ok=True)
    with media_arc.open("wb") as out:
        volume_archive.export_archive(m_root, out, public=True)

    v_root = Path(vault_root)
    v_root.mkdir(parents=True, exist_ok=True)
    with vault_arc.open("wb") as out:
        volume_archive.export_archive(v_root, out, public=False)

    fingerprints = (
        compose_backups.key_fingerprints(key_env)
        if key_env
        else {k: "" for k in compose_backups.KEYS}
    )
    manifest = {
        "format_version": 1,
        "mode": "standalone_mysql",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "database_name": db_name,
        "key_fingerprints": fingerprints,
        "artifacts": {
            name: {
                "bytes": (dest / name).stat().st_size,
                "sha256": compose_backups.digest(dest / name),
            }
            for name in compose_backups.ARTIFACTS
        },
    }
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    compose_backups.validate_backup(dest)
    return dest


def restore_mysql_backup(
    *,
    source_dir: str | Path,
    target_db: str,
    db_user: str,
    db_password: str,
    db_host: str = "127.0.0.1",
    db_port: str = "3306",
    target_media: str | Path,
    target_vault: str | Path,
) -> dict:
    src = Path(source_dir).resolve(strict=True)
    manifest = compose_backups.validate_backup(src)
    mysql_bin = resolve_mysql_tool("mysql")
    env = _mysql_env(db_password)

    # Từ chối ghi đè nếu DB đích đã có bảng tồn tại
    check_cmd = [
        mysql_bin,
        "--protocol=TCP",
        f"--host={db_host}",
        f"--port={db_port}",
        f"--user={db_user}",
        "--batch",
        "--skip-column-names",
        target_db,
        "-e",
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE()",
    ]
    res = subprocess.run(check_cmd, env=env, stdout=subprocess.PIPE, text=True, check=True)
    if int((res.stdout or "0").strip()) > 0:
        raise ValueError(f"Từ chối khôi phục: CSDL đích `{target_db}` không trống.")

    import_cmd = [
        mysql_bin,
        "--protocol=TCP",
        f"--host={db_host}",
        f"--port={db_port}",
        f"--user={db_user}",
        target_db,
    ]
    with (src / "database.sql").open("rb") as sql_in:
        subprocess.run(import_cmd, env=env, stdin=sql_in, check=True)

    m_dst = Path(target_media)
    m_dst.mkdir(parents=True, exist_ok=True)
    volume_archive.restore_archive(src / "media.tar.gz", m_dst, public=True)

    v_dst = Path(target_vault)
    v_dst.mkdir(parents=True, exist_ok=True)
    volume_archive.restore_archive(src / "private_vault.tar.gz", v_dst, public=False)
    return manifest
