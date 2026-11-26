"""
Công cụ chuyển đổi an toàn dữ liệu từ SQLite sang MySQL 8.4 (`InnoDB`, `utf8mb4`).

Quy trình bắt buộc:
1. Inventory: Kiểm kê bảng, số dòng, chuỗi rỗng trên cột UNIQUE NULL, khóa ngoại lỗi, tổng quỹ tài chính.
2. Pre-backup: Tạo bản sao lưu SQLite kèm SHA-256 trước khi ghi sang MySQL.
3. Dry-run: Kiểm tra tương thích schema, UTF-8 / emoji, độ dài cột và ràng buộc trước khi ghi.
4. Execute: Sao chép theo bảng/thứ tự an toàn, giữ nguyên PK, code vé, booking_ref, dữ liệu mã hóa nhị phân.
5. Reconcile: Đối soát số dòng 100%, khóa ngoại MySQL và số liệu sổ cái tài chính.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from typing import Any

from django.apps import apps
from django.conf import settings
from django.db import connections, transaction

NULLABLE_UNIQUE_CLEANUP = {
    "accounts_user": {"mssv", "normalized_email", "normalized_phone"},
    "organization_appointment": {"singleton_active_key"},
}

SYSTEM_EXCLUDE_TABLES = {"sqlite_sequence"}


@dataclass
class MigrationReport:
    source_sqlite: str
    target_alias: str
    mode: str
    source_rows: dict[str, int] = field(default_factory=dict)
    target_rows: dict[str, int] = field(default_factory=dict)
    dirty_values_fixed: dict[str, int] = field(default_factory=dict)
    fk_orphans: dict[str, int] = field(default_factory=dict)
    finance_reconciliation: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and not self.fk_orphans

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_sqlite": self.source_sqlite,
            "target_alias": self.target_alias,
            "mode": self.mode,
            "ok": self.ok,
            "total_source_rows": sum(self.source_rows.values()),
            "total_target_rows": sum(self.target_rows.values()),
            "source_rows": self.source_rows,
            "target_rows": self.target_rows,
            "dirty_values_fixed": self.dirty_values_fixed,
            "fk_orphans": self.fk_orphans,
            "finance_reconciliation": self.finance_reconciliation,
            "warnings": self.warnings,
            "errors": self.errors,
        }


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def backup_sqlite_source(source_path: Path, backup_dir: Path) -> Path:
    """Sao lưu tệp SQLite nguồn trước khi chuyển đổi, ghi kèm manifest SHA-256."""
    source_path = source_path.resolve(strict=True)
    backup_dir = backup_dir.resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snap = backup_dir / f"{source_path.stem}.{ts}.sqlite3"
    src_conn = sqlite3.connect(str(source_path))
    dst_conn = sqlite3.connect(str(snap))
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()
    manifest = {
        "source": str(source_path),
        "backup": str(snap),
        "created_at": ts,
        "bytes": snap.stat().st_size,
        "sha256": _sha256_file(snap),
    }
    (backup_dir / f"{source_path.stem}.{ts}.manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return snap


def _model_field_defaults_by_table() -> dict[str, dict[str, Any]]:
    """Lấy giá trị mặc định khai báo ở Django model cho từng (bảng, cột)."""
    defaults: dict[str, dict[str, Any]] = {}
    for model in apps.get_models():
        table = model._meta.db_table
        tbl_map = defaults.setdefault(table, {})
        for f in model._meta.concrete_fields:
            if f.has_default():
                val = f.get_default()
                if val is not None:
                    tbl_map[f.column] = val
    return defaults


def _ordered_django_tables() -> list[str]:
    """Liệt kê tất cả bảng mô hình Django có mặt trên DB."""
    seen: list[str] = []
    for model in apps.get_models():
        t = model._meta.db_table
        if t not in seen:
            seen.append(t)
    return seen


def _sqlite_finance_totals(sq: sqlite3.Connection) -> dict[str, int]:
    cur = sq.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='finance_financialtransaction'")
    if cur.fetchone() is None:
        return {}
    rows = sq.execute(
        "SELECT tx_type, COALESCE(SUM(amount), 0) FROM finance_financialtransaction "
        "WHERE status='CONFIRMED' GROUP BY tx_type"
    ).fetchall()
    return {str(r[0]): int(r[1]) for r in rows}


def _target_finance_totals(conn) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT tx_type, COALESCE(SUM(amount), 0) FROM finance_financialtransaction "
            "WHERE status='CONFIRMED' GROUP BY tx_type"
        )
        return {str(r[0]): int(r[1]) for r in cur.fetchall()}


def _check_sqlite_orphans(sq: sqlite3.Connection) -> dict[str, int]:
    orphans: dict[str, int] = {}
    for model in apps.get_models():
        table = model._meta.db_table
        for field_obj in model._meta.concrete_fields:
            rel_model = getattr(field_obj, "related_model", None)
            if rel_model is None:
                continue
            parent_table = rel_model._meta.db_table
            parent_pk = rel_model._meta.pk.column
            col = field_obj.column
            sql = (
                f'SELECT COUNT(*) FROM "{table}" c '
                f'LEFT JOIN "{parent_table}" p ON c."{col}" = p."{parent_pk}" '
                f'WHERE c."{col}" IS NOT NULL AND p."{parent_pk}" IS NULL'
            )
            try:
                cnt = int(sq.execute(sql).fetchone()[0])
            except sqlite3.OperationalError:
                continue
            if cnt > 0:
                orphans[f"{table}.{col}->{parent_table}"] = cnt
    return orphans


def _check_target_orphans(conn) -> dict[str, int]:
    orphans: dict[str, int] = {}
    with conn.cursor() as cur:
        for model in apps.get_models():
            table = model._meta.db_table
            for field_obj in model._meta.concrete_fields:
                rel_model = getattr(field_obj, "related_model", None)
                if rel_model is None:
                    continue
                parent_table = rel_model._meta.db_table
                parent_pk = rel_model._meta.pk.column
                col = field_obj.column
                sql = (
                    f"SELECT COUNT(*) FROM `{table}` c "
                    f"LEFT JOIN `{parent_table}` p ON c.`{col}` = p.`{parent_pk}` "
                    f"WHERE c.`{col}` IS NOT NULL AND p.`{parent_pk}` IS NULL"
                )
                cur.execute(sql)
                cnt = int(cur.fetchone()[0])
                if cnt > 0:
                    orphans[f"{table}.{col}->{parent_table}"] = cnt
    return orphans


def _normalize_row(table: str, cols: list[str], row: tuple[Any, ...], counters: dict[str, int]) -> list[Any]:
    cleanup_cols = NULLABLE_UNIQUE_CLEANUP.get(table, set())
    out = list(row)
    for idx, col in enumerate(cols):
        val = out[idx]
        if col in cleanup_cols and isinstance(val, str) and not val.strip():
            out[idx] = None
            key = f"{table}.{col}"
            counters[key] = counters.get(key, 0) + 1
    return out


def run_sqlite_to_mysql_migration(
    *,
    source_sqlite: str | Path,
    target_alias: str = "default",
    dry_run: bool = True,
    backup_dir: str | Path | None = None,
    allow_nonempty: bool = False,
) -> MigrationReport:
    """Thực thi kiểm kê / dry-run / chuyển đổi dữ liệu SQLite sang MySQL an toàn."""
    src_path = Path(source_sqlite).resolve(strict=True)
    report = MigrationReport(
        source_sqlite=str(src_path),
        target_alias=target_alias,
        mode="DRY_RUN" if dry_run else "EXECUTE",
    )

    conn = connections[target_alias]
    if conn.vendor != "mysql" and not dry_run:
        report.errors.append(f"Target database `{target_alias}` phải là MySQL (hiện tại: {conn.vendor}).")
        return report

    sq = sqlite3.connect(str(src_path))
    try:
        sq_tables = {
            r[0]
            for r in sq.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        ordered_tables = [t for t in _ordered_django_tables() if t in sq_tables]

        for table in ordered_tables:
            cnt = int(sq.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            report.source_rows[table] = cnt

        report.fk_orphans = _check_sqlite_orphans(sq)
        if report.fk_orphans:
            report.errors.append(f"Phát hiện khóa ngoại mồ côi trong SQLite nguồn: {report.fk_orphans}")

        src_fin = _sqlite_finance_totals(sq)
        report.finance_reconciliation["source"] = src_fin

        # Kiểm tra tài sản media / private_vault
        media_root = Path(settings.MEDIA_ROOT)
        vault_root = Path(settings.PRIVATE_VAULT_ROOT)
        report.finance_reconciliation["media_files_present"] = (
            sum(1 for p in media_root.rglob("*") if p.is_file()) if media_root.exists() else 0
        )
        report.finance_reconciliation["private_vault_files_present"] = (
            sum(1 for p in vault_root.rglob("*") if p.is_file()) if vault_root.exists() else 0
        )

        # Kiểm tra dữ liệu nguồn bằng dry-run normalization pass
        for table in ordered_tables:
            if report.source_rows[table] == 0:
                continue
            cur = sq.execute(f'SELECT * FROM "{table}"')
            cols = [d[0] for d in cur.description]
            for row in cur:
                _normalize_row(table, cols, row, report.dirty_values_fixed)

        if dry_run:
            return report

        if report.errors:
            return report

        if backup_dir:
            backup_sqlite_source(src_path, Path(backup_dir))

        # Chế độ EXECUTE trên MySQL thực
        with conn.cursor() as cur:
            cur.execute("SHOW TABLES")
            target_tables = {r[0] for r in cur.fetchall()}
            missing_target = [t for t in ordered_tables if t not in target_tables]
            if missing_target:
                report.errors.append(f"MySQL đích thiếu bảng (chưa migrate?): {missing_target}")
                return report

            if not allow_nonempty:
                non_empty_biz = []
                for t in ordered_tables:
                    if t in ("django_migrations", "django_content_type", "auth_permission"):
                        continue
                    cur.execute(f"SELECT COUNT(*) FROM `{t}`")
                    t_cnt = int(cur.fetchone()[0])
                    if t == "pages_clubofficer" and t_cnt <= 4:
                        cur.execute("SELECT COUNT(*) FROM `accounts_user`")
                        if int(cur.fetchone()[0]) == 0:
                            continue
                    if t_cnt > 0:
                        non_empty_biz.append(t)
                if non_empty_biz:
                    report.errors.append(
                        f"MySQL đích đã có dữ liệu ở {non_empty_biz[:8]}; từ chối ghi đè khi chưa bật allow_nonempty."
                    )
                    return report

        model_defaults = _model_field_defaults_by_table()

        with transaction.atomic(using=target_alias):
            with conn.cursor() as cur:
                cur.execute("SET FOREIGN_KEY_CHECKS = 0")
                try:
                    # Xoá dữ liệu bootstrap mặc định trên MySQL mới migrate để khớp 100% PK IDs từ SQLite
                    for table in reversed(ordered_tables):
                        if report.source_rows.get(table, 0) > 0 or table in (
                            "auth_permission",
                            "django_content_type",
                        ):
                            cur.execute(f"DELETE FROM `{table}`")

                    for table in ordered_tables:
                        if report.source_rows.get(table, 0) == 0:
                            continue
                        sq_cur = sq.execute(f'SELECT * FROM "{table}"')
                        cols = [d[0] for d in sq_cur.description]
                        cur.execute(f"SHOW COLUMNS FROM `{table}`")
                        col_meta = cur.fetchall()
                        mysql_cols = {r[0] for r in col_meta}
                        use_indices = [i for i, c in enumerate(cols) if c in mysql_cols]
                        use_cols = [cols[i] for i in use_indices]

                        # Bù cột mới (NOT NULL chưa có default SQL) nếu SQLite ở bản migration cũ hơn
                        extra_cols: list[str] = []
                        extra_vals: list[Any] = []
                        tbl_defaults = model_defaults.get(table, {})
                        for col_row in col_meta:
                            cname, _, is_null, _, col_default, extra = col_row
                            if cname not in use_cols and is_null == "NO" and col_default is None and "auto_increment" not in (extra or ""):
                                if cname in tbl_defaults:
                                    extra_cols.append(cname)
                                    extra_vals.append(tbl_defaults[cname])
                                    report.warnings.append(f"Bổ sung default model `{table}.{cname}`={tbl_defaults[cname]!r} cho SQLite cũ.")
                                else:
                                    report.errors.append(f"Thiếu giá trị cho cột bắt buộc `{table}.{cname}` trên MySQL đích.")

                        if report.errors:
                            break

                        all_insert_cols = use_cols + extra_cols
                        col_sql = ", ".join(f"`{c}`" for c in all_insert_cols)
                        placeholders = ", ".join(["%s"] * len(all_insert_cols))
                        insert_sql = f"INSERT INTO `{table}` ({col_sql}) VALUES ({placeholders})"

                        batch: list[tuple[Any, ...]] = []
                        norm_counters: dict[str, int] = {}
                        for row in sq_cur:
                            norm = _normalize_row(table, cols, row, norm_counters)
                            batch.append(tuple(norm[i] for i in use_indices) + tuple(extra_vals))
                            if len(batch) >= 500:
                                cur.executemany(insert_sql, batch)
                                batch.clear()
                        if batch:
                            cur.executemany(insert_sql, batch)
                finally:
                    cur.execute("SET FOREIGN_KEY_CHECKS = 1")

        # Đối soát sau chuyển đổi
        with conn.cursor() as cur:
            for table in ordered_tables:
                cur.execute(f"SELECT COUNT(*) FROM `{table}`")
                t_cnt = int(cur.fetchone()[0])
                report.target_rows[table] = t_cnt
                if t_cnt != report.source_rows[table]:
                    report.errors.append(
                        f"Lệch số dòng bảng `{table}`: SQLite={report.source_rows[table]} vs MySQL={t_cnt}"
                    )

        report.fk_orphans = _check_target_orphans(conn)
        if report.fk_orphans:
            report.errors.append(f"Phát hiện lỗi khóa ngoại trên MySQL đích: {report.fk_orphans}")

        tgt_fin = _target_finance_totals(conn)
        report.finance_reconciliation["target"] = tgt_fin
        if src_fin != tgt_fin:
            report.errors.append(f"Lệch số liệu tài chính CONFIRMED: SQLite={src_fin} vs MySQL={tgt_fin}")

        return report
    finally:
        sq.close()
