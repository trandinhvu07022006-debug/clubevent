"""
Công cụ nhập dữ liệu tri thức AI chuẩn JSONL (Dataset v2) vào ClubKnowledge.

Tính năng:
  - Hỗ trợ JSONL UTF-8 (mặc định: aiassist/datasets/v2/kmg_ai_knowledge_candidates.jsonl).
  - --dry-run: kiểm tra schema, mã định danh, trùng lặp, nguồn tham chiếu mà không ghi DB.
  - Chống trùng lặp (theo knowledge_id và tiêu đề chuẩn hoá), chạy lại không tạo bản ghi trùng.
  - Bảo vệ dữ liệu đã chỉnh sửa bởi quản trị (is_admin_edited=True): mặc định bỏ qua, không ghi đè.
  - Phê duyệt trước khi kích hoạt: mặc định nhập ở trạng thái PENDING và is_active=False.
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from aiassist.models import (ApprovalStatus, ClubKnowledge, KnowledgeCategory,
                             KnowledgeVisibility)

DEFAULT_CANDIDATES_PATH = (
    Path(__file__).resolve().parents[2]
    / "datasets"
    / "v2"
    / "kmg_ai_knowledge_candidates.jsonl"
)

_AUDIENCE_TO_VISIBILITY = {
    "public": KnowledgeVisibility.PUBLIC,
    "internal": KnowledgeVisibility.INTERNAL,
    "member": KnowledgeVisibility.INTERNAL,
    "confidential": KnowledgeVisibility.CONFIDENTIAL,
    "board": KnowledgeVisibility.CONFIDENTIAL,
    "admin": KnowledgeVisibility.CONFIDENTIAL,
}

_TOPIC_TO_CATEGORY = {
    "guitar": KnowledgeCategory.MUSIC,
    "vocal": KnowledgeCategory.MUSIC,
    "theory": KnowledgeCategory.MUSIC,
    "instruments": KnowledgeCategory.MUSIC,
    "band": KnowledgeCategory.MUSIC,
    "creative": KnowledgeCategory.MUSIC,
    "stage": KnowledgeCategory.TECH,
    "equipment": KnowledgeCategory.TECH,
    "student": KnowledgeCategory.STUDENT_LIFE,
    "community": KnowledgeCategory.STUDENT_LIFE,
    "join": KnowledgeCategory.RECRUITMENT,
    "daily": KnowledgeCategory.GENERAL,
}


def _norm_title(text: str) -> str:
    s = unicodedata.normalize("NFD", (text or "").lower().strip()).replace("đ", "d")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.split())


def _is_valid_url(url: str) -> bool:
    parsed = urlparse(str(url or "").strip())
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def validate_knowledge_row(raw: dict, line_no: int) -> tuple[dict | None, list[str]]:
    """Kiểm tra schema, mã định danh, danh mục, nguồn của một dòng JSONL."""
    errors: list[str] = []
    if not isinstance(raw, dict):
        return None, [f"Dòng {line_no}: không phải JSON object."]

    kid = str(raw.get("knowledge_id") or "").strip()
    if not kid or len(kid) > 64:
        errors.append(f"Dòng {line_no}: thiếu hoặc sai độ dài 'knowledge_id'.")

    fields = raw.get("fields")
    if not isinstance(fields, dict):
        errors.append(f"Dòng {line_no} ({kid or '?'}): thiếu object 'fields'.")
        return None, errors

    title = str(fields.get("title") or "").strip()
    content = str(fields.get("content") or "").strip()
    if not title or len(title) > 160:
        errors.append(f"Dòng {line_no} ({kid}): 'fields.title' rỗng hoặc > 160 ký tự.")
    if not content:
        errors.append(f"Dòng {line_no} ({kid}): 'fields.content' không được rỗng.")

    audience = str(raw.get("audience") or "public").strip().lower()
    if audience not in _AUDIENCE_TO_VISIBILITY:
        errors.append(f"Dòng {line_no} ({kid}): 'audience' không hợp lệ ({audience}).")

    topic = str(raw.get("topic") or "").strip().lower()
    raw_cat = str(fields.get("category") or KnowledgeCategory.GENERAL).strip().upper()
    if raw_cat == KnowledgeCategory.GENERAL and topic in _TOPIC_TO_CATEGORY:
        category = _TOPIC_TO_CATEGORY[topic]
    elif raw_cat in KnowledgeCategory.values:
        category = raw_cat
    else:
        errors.append(f"Dòng {line_no} ({kid}): 'category' không hợp lệ ({raw_cat}).")
        category = KnowledgeCategory.GENERAL

    source_urls = raw.get("source_urls") or []
    if not isinstance(source_urls, list) or any(not _is_valid_url(u) for u in source_urls):
        errors.append(f"Dòng {line_no} ({kid}): 'source_urls' phải là danh sách URL http(s) hợp lệ.")

    if errors:
        return None, errors

    try:
        priority = max(1, min(int(fields.get("priority", 10)), 999))
    except (TypeError, ValueError):
        priority = 10

    return {
        "knowledge_id": kid,
        "title": title,
        "category": category,
        "visibility": _AUDIENCE_TO_VISIBILITY[audience],
        "keywords": str(fields.get("keywords") or "").strip()[:255],
        "content": content,
        "priority": priority,
        "source_urls": [str(u).strip() for u in source_urls],
        "source_note": str(raw.get("source_note") or "").strip()[:255],
        "review_status": str(raw.get("review_status") or "").strip(),
    }, []


def import_knowledge_jsonl(
    path: Path,
    *,
    dry_run: bool = False,
    approve: bool = False,
    force_overwrite: bool = False,
) -> dict:
    """Nhập tệp JSONL ứng viên tri thức vào ClubKnowledge kèm báo cáo chi tiết."""
    if not path.exists():
        raise CommandError(f"Không tìm thấy tệp JSONL: {path}")

    raw_lines = path.read_text(encoding="utf-8").splitlines()
    seen_ids: set[str] = set()
    seen_titles: set[str] = set()
    parsed_rows: list[dict] = []
    errors: list[str] = []
    duplicates_in_file = 0

    for idx, line in enumerate(raw_lines, 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"Dòng {idx}: lỗi JSON ({exc}).")
            continue
        row, row_errors = validate_knowledge_row(obj, idx)
        if row_errors:
            errors.extend(row_errors)
            continue
        kid = row["knowledge_id"]
        ntitle = _norm_title(row["title"])
        if kid in seen_ids or ntitle in seen_titles:
            duplicates_in_file += 1
            errors.append(f"Dòng {idx} ({kid}): trùng mã định danh hoặc tiêu đề trong tệp.")
            continue
        seen_ids.add(kid)
        seen_titles.add(ntitle)
        parsed_rows.append(row)

    stats = {
        "total_lines": len([l for l in raw_lines if l.strip()]),
        "valid_rows": len(parsed_rows),
        "created": 0,
        "updated": 0,
        "skipped_admin_conflict": 0,
        "skipped_existing_title": 0,
        "duplicates_in_file": duplicates_in_file,
        "errors": errors,
        "dry_run": dry_run,
    }

    existing_by_kid = {
        k.knowledge_id: k
        for k in ClubKnowledge.objects.exclude(knowledge_id__isnull=True).exclude(knowledge_id="")
    }
    existing_by_title = {_norm_title(k.title): k for k in ClubKnowledge.objects.all()}

    target_approval = ApprovalStatus.APPROVED if approve else ApprovalStatus.PENDING
    target_active = bool(approve)

    with transaction.atomic():
        for row in parsed_rows:
            kid = row["knowledge_id"]
            ntitle = _norm_title(row["title"])
            existing = existing_by_kid.get(kid)
            if existing is None:
                title_match = existing_by_title.get(ntitle)
                if title_match is not None and title_match.knowledge_id and title_match.knowledge_id != kid:
                    stats["skipped_existing_title"] += 1
                    continue
                existing = title_match

            if existing is None:
                stats["created"] += 1
                if not dry_run:
                    ClubKnowledge.objects.create(
                        knowledge_id=kid,
                        title=row["title"],
                        category=row["category"],
                        visibility=row["visibility"],
                        approval_status=target_approval,
                        keywords=row["keywords"],
                        content=row["content"],
                        source_urls=row["source_urls"],
                        source_note=row["source_note"],
                        priority=row["priority"],
                        is_active=target_active,
                        version="2.0" if kid.startswith("MUSIC-") else "1.0",
                    )
            else:
                if existing.is_admin_edited and not force_overwrite:
                    stats["skipped_admin_conflict"] += 1
                    continue
                stats["updated"] += 1
                if not dry_run:
                    existing.knowledge_id = kid
                    existing.title = row["title"]
                    existing.category = row["category"]
                    existing.visibility = row["visibility"]
                    existing.keywords = row["keywords"]
                    existing.content = row["content"]
                    existing.source_urls = row["source_urls"]
                    existing.source_note = row["source_note"]
                    existing.priority = row["priority"]
                    if approve:
                        existing.approval_status = ApprovalStatus.APPROVED
                        existing.is_active = True
                    existing.save()

    return stats


class Command(BaseCommand):
    help = "Nhập dữ liệu tri thức AI chuẩn JSONL vào ClubKnowledge (hỗ trợ dry-run & chống trùng)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            default=str(DEFAULT_CANDIDATES_PATH),
            help="Đường dẫn tới tệp JSONL ứng viên tri thức (mặc định dùng bộ v2 đầy đủ).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Chỉ kiểm tra schema, trùng lặp, xung đột và báo cáo, không ghi DB.",
        )
        parser.add_argument(
            "--approve",
            action="store_true",
            help="Phê duyệt và kích hoạt ngay các mục được nhập (mặc định là PENDING & inactive).",
        )
        parser.add_argument(
            "--force-overwrite",
            action="store_true",
            help="Cho phép ghi đè cả các mục đã được quản trị chỉnh sửa.",
        )

    def handle(self, *args, **options):
        path = Path(options["path"])
        stats = import_knowledge_jsonl(
            path,
            dry_run=options["dry_run"],
            approve=options["approve"],
            force_overwrite=options["force_overwrite"],
        )
        mode = "DRY-RUN" if stats["dry_run"] else "IMPORT"
        self.stdout.write(
            f"[{mode}] Tệp: {path.name} | Hợp lệ: {stats['valid_rows']}/{stats['total_lines']} | "
            f"Tạo mới: {stats['created']} | Cập nhật: {stats['updated']} | "
            f"Bỏ qua (admin sửa): {stats['skipped_admin_conflict']} | "
            f"Trùng tiêu đề: {stats['skipped_existing_title']} | Lỗi: {len(stats['errors'])}"
        )
        for err in stats["errors"][:20]:
            self.stdout.write(self.style.WARNING(f"  - {err}"))
        if stats["errors"]:
            raise CommandError(f"Phát hiện {len(stats['errors'])} lỗi khi kiểm tra dữ liệu.")
        self.stdout.write(self.style.SUCCESS("Hoàn tất kiểm tra/nhập dữ liệu tri thức AI."))
