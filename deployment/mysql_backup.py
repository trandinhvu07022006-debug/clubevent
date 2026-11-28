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
    dest.mkdir(mode=0o700, parents=False, exist_ok=False)
    try:
        dest.chmod(0o700)
    except OSError:
        pass
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
    with sql_path.open("xb") as sql_out:
        try:
            sql_path.chmod(0o600)
        except OSError:
            pass
        subprocess.run(dump_cmd, env=_mysql_env(db_password), stdout=sql_out, check=True)

    m_root = Path(media_root)
    m_root.mkdir(parents=True, exist_ok=True)
    with media_arc.open("xb") as out:
        try:
            media_arc.chmod(0o600)
        except OSError:
            pass
        volume_archive.export_archive(m_root, out, public=True)

    v_root = Path(vault_root)
    v_root.mkdir(parents=True, exist_ok=True)
    with vault_arc.open("xb") as out:
        try:
            vault_arc.chmod(0o600)
        except OSError:
            pass
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
    pending_manifest = dest / "manifest.pending.json"
    with pending_manifest.open("x", encoding="utf-8") as mf:
        try:
            pending_manifest.chmod(0o600)
        except OSError:
            pass
        json.dump(manifest, mf, indent=2)
    pending_manifest.replace(dest / "manifest.json")
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
    key_env: dict[str, str] | None = None,
) -> dict:
    src_raw = Path(source_dir)
    if src_raw.is_symlink():
        raise ValueError("Từ chối khôi phục: source_dir không được là symlink.")
    src = src_raw.resolve(strict=True)
    manifest = compose_backups.validate_backup(src)

    # Kiểm tra dấu vân tay khóa mã hóa TRƯỚC KHI ghi bất kỳ dữ liệu nào
    expected_fp = manifest.get("key_fingerprints") or {}
    if any(expected_fp.values()):
        if not key_env:
            raise ValueError("Bản sao lưu có dấu vân tay khóa mã hóa; bắt buộc cung cấp key_env để đối chiếu.")
        if compose_backups.key_fingerprints(key_env) != expected_fp:
            raise ValueError("Dấu vân tay khóa mã hóa (SECRET_KEY/CERT_SIGNING_KEY/CHAT_MASTER_KEK) không khớp bản backup.")

    # Kiểm tra media và private_vault đích không phải symlink, không trùng/lồng nhau và phải trống TRƯỚC KHI import DB
    m_dst = Path(target_media)
    v_dst = Path(target_vault)
    for label, p in (("target_media", m_dst), ("target_vault", v_dst)):
        if p.is_symlink():
            raise ValueError(f"Từ chối khôi phục: {label} không được là symlink.")
    m_res = m_dst.resolve()
    v_res = v_dst.resolve()
    if m_res == v_res or m_res.is_relative_to(v_res) or v_res.is_relative_to(m_res):
        raise ValueError("Từ chối khôi phục: target_media và target_vault không được trùng hoặc lồng nhau.")
    if m_res == src or m_res.is_relative_to(src) or v_res == src or v_res.is_relative_to(src):
        raise ValueError("Từ chối khôi phục: thư mục đích không được trùng hoặc nằm trong thư mục backup.")
    if m_dst.exists() and any(m_dst.iterdir()):
        raise ValueError(f"Từ chối khôi phục: thư mục media đích `{m_dst}` không trống.")
    if v_dst.exists() and any(v_dst.iterdir()):
        raise ValueError(f"Từ chối khôi phục: thư mục private_vault đích `{v_dst}` không trống.")

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

    m_dst.mkdir(parents=True, exist_ok=True)
    volume_archive.restore_archive(src / "media.tar.gz", m_dst, public=True)

    v_dst.mkdir(parents=True, exist_ok=True)
    volume_archive.restore_archive(src / "private_vault.tar.gz", v_dst, public=False)
    return manifest
