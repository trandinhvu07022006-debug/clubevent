"""Lệnh quản trị chuyển đổi dữ liệu an toàn từ SQLite sang MySQL 8.4."""
from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from deployment.sqlite_to_mysql import run_sqlite_to_mysql_migration


class Command(BaseCommand):
    help = "Kiểm kê, dry-run, chuyển đổi và đối soát dữ liệu SQLite sang MySQL 8.4."

    def add_arguments(self, parser):
        parser.add_argument("--source", required=True, help="Đường dẫn tới file SQLite nguồn")
        parser.add_argument("--target-alias", default="default", help="Alias DB đích trong settings.DATABASES")
        parser.add_argument("--execute", action="store_true", help="Thực thi chuyển đổi thật sang MySQL (mặc định là dry-run)")
        parser.add_argument("--backup-dir", default="", help="Thư mục ngoài repo để sao lưu SQLite trước khi chạy")
        parser.add_argument("--allow-nonempty", action="store_true", help="Cho phép ghi lên DB đích đã có bảng dữ liệu")
        parser.add_argument("--report-json", default="", help="Xuất báo cáo đối soát ra JSON")

    def handle(self, *args, **options):
        report = run_sqlite_to_mysql_migration(
            source_sqlite=options["source"],
            target_alias=options["target_alias"],
            dry_run=not options["execute"],
            backup_dir=options["backup_dir"] or None,
            allow_nonempty=options["allow_nonempty"],
        )
        payload = report.as_dict()
        if options["report_json"]:
            out = Path(options["report_json"])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        self.stdout.write(json.dumps({
            "mode": report.mode,
            "ok": report.ok,
            "total_source_rows": payload["total_source_rows"],
            "total_target_rows": payload["total_target_rows"],
            "dirty_values_fixed": report.dirty_values_fixed,
            "fk_orphans": report.fk_orphans,
            "finance_reconciliation": report.finance_reconciliation,
            "errors": report.errors,
        }, ensure_ascii=False, indent=2))
        if not report.ok:
            raise CommandError("Chuyển đổi SQLite -> MySQL phát hiện lỗi hoặc lệch đối soát.")
