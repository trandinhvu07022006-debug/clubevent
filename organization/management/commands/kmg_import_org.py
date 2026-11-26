"""Lệnh nhập dữ liệu tổ chức, thành viên, chức vụ, kỹ năng và lịch sử từ CSV hoặc Excel."""
from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from organization.importers import SUPPORTED_KINDS, run_org_import


class Command(BaseCommand):
    help = "Nhập danh mục/hồ sơ thành viên KMG từ CSV hoặc Excel (.xlsx) hỗ trợ dry-run và chống trùng."

    def add_arguments(self, parser):
        parser.add_argument("--kind", required=True, choices=SUPPORTED_KINDS)
        parser.add_argument("--file", required=True, help="Đường dẫn tới tệp .csv hoặc .xlsx")
        parser.add_argument("--dry-run", action="store_true", help="Kiểm tra toàn bộ và rollback sau khi xác thực")
        parser.add_argument("--update-existing", action="store_true", help="Cập nhật bản ghi an toàn nếu đã tồn tại")
        parser.add_argument("--approve-by", default="", help="Username Admin/Chủ nhiệm phê duyệt (bắt buộc cho appointments)")
        parser.add_argument("--report-json", default="", help="Ghi báo cáo chi tiết ra JSON")

    def handle(self, *args, **options):
        report = run_org_import(
            kind=options["kind"],
            file_path=options["file"],
            dry_run=options["dry_run"],
            update_existing=options["update_existing"],
            approve_by_username=options["approve_by"],
        )
        payload = report.as_dict()
        if options["report_json"]:
            out_path = Path(options["report_json"])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        mode = "DRY-RUN" if report.dry_run else "COMMIT"
        self.stdout.write(
            f"[{mode}] kind={report.kind} total={report.total_rows} "
            f"created={report.created} updated={report.updated} "
            f"skipped={report.skipped} errors={len(report.errors)}"
        )
        for err in report.errors[:20]:
            self.stderr.write(f"  - Dòng {err['row']}: {err['error']}")
