"""Lệnh kiểm kê & diễn tập hợp nhất hệ thống nghiệp vụ (`BUS-01`, `BUS-03`, mặc định dry-run)."""
from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from organization.business_consolidation import run_unified_business_rehearsal


class Command(BaseCommand):
    help = "Kiểm kê và diễn tập ánh xạ dữ liệu cũ -> Canonical (mặc định dry-run an toàn)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Thực thi ghi trên DB hiện hành (chỉ dùng trên môi trường staging/test được duyệt).",
        )
        parser.add_argument(
            "--report-json",
            default="",
            help="Đường dẫn xuất báo cáo đối soát JSON.",
        )

    def handle(self, *args, **options):
        dry_run = not options["execute"]
        report = run_unified_business_rehearsal(dry_run=dry_run)
        payload = report.as_dict()
        if options["report_json"]:
            out_path = Path(options["report_json"])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        self.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False))
