"""Công cụ nhập danh sách thành viên, cơ cấu, chức vụ, kỹ năng và lịch sử từ CSV / Excel (.xlsx)."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from accounts.models import (
    AccountStatus,
    Affiliation,
    Role,
    User,
    normalize_phone_number,
)
from organization.models import (
    ClubMembership,
    ClubMembershipStatus,
    Department,
    DepartmentMembership,
    DeptMembershipStatus,
    LifecycleEventType,
    MemberLifecycleEvent,
    Position,
    PositionCode,
    ScopeType,
    Skill,
    SkillCategory,
    SkillProficiency,
    SkillVerificationStatus,
    UserSkill,
)
from organization.services import (
    GovernanceError,
    _generate_next_member_code,
    appoint_officer,
    record_lifecycle_event,
)

SUPPORTED_KINDS = ("members", "structure", "appointments", "skills", "history")


@dataclass
class ImportReport:
    kind: str
    file_path: str
    dry_run: bool
    total_rows: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[dict] = field(default_factory=list)

    def add_error(self, row_num: int, message: str) -> None:
        self.errors.append({"row": row_num, "error": message})

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "file_path": self.file_path,
            "dry_run": self.dry_run,
            "total_rows": self.total_rows,
            "created": self.created,
            "updated": self.updated,
            "skipped": self.skipped,
            "error_count": len(self.errors),
            "errors": self.errors,
        }


def _col_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha()).upper()
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return max(idx - 1, 0)


def _read_xlsx_stdlib(path: Path) -> list[dict[str, str]]:
    """Đọc tệp Excel .xlsx không cần phụ thuộc ngoài khi openpyxl chưa được cài."""
    ns_main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    with zipfile.ZipFile(path, "r") as zf:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall(f"{{{ns_main}}}si"):
                texts = [t.text or "" for t in si.iter(f"{{{ns_main}}}t")]
                shared_strings.append("".join(texts))

        sheet_names = sorted(
            n for n in zf.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")
        )
        if not sheet_names:
            return []
        sheet_root = ET.fromstring(zf.read(sheet_names[0]))
        rows_raw: list[list[str]] = []
        for row_el in sheet_root.iter(f"{{{ns_main}}}row"):
            row_map: dict[int, str] = {}
            max_col = 0
            for c_el in row_el.findall(f"{{{ns_main}}}c"):
                col_i = _col_index(c_el.attrib.get("r", "A1"))
                max_col = max(max_col, col_i)
                ctype = c_el.attrib.get("t", "")
                val = ""
                if ctype == "inlineStr":
                    is_el = c_el.find(f"{{{ns_main}}}is")
                    if is_el is not None:
                        val = "".join(t.text or "" for t in is_el.iter(f"{{{ns_main}}}t"))
                else:
                    v_el = c_el.find(f"{{{ns_main}}}v")
                    if v_el is not None and v_el.text is not None:
                        if ctype == "s":
                            idx = int(v_el.text)
                            val = shared_strings[idx] if 0 <= idx < len(shared_strings) else ""
                        else:
                            val = v_el.text
                row_map[col_i] = val.strip()
            if row_map:
                rows_raw.append([row_map.get(i, "") for i in range(max_col + 1)])

    if not rows_raw:
        return []
    headers = [h.strip() for h in rows_raw[0]]
    results: list[dict[str, str]] = []
    for values in rows_raw[1:]:
        if not any(v.strip() for v in values):
            continue
        item = {
            headers[i]: (values[i].strip() if i < len(values) else "")
            for i in range(len(headers))
            if headers[i]
        }
        results.append(item)
    return results


def read_tabular_file(file_path: str | Path) -> list[dict[str, str]]:
    """Đọc bảng dữ liệu từ CSV (UTF-8/BOM) hoặc Excel (.xlsx)."""
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        raise CommandError(f"Không tìm thấy tệp dữ liệu: {path}")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            if not reader.fieldnames:
                return []
            rows = []
            for row in reader:
                cleaned = {str(k).strip(): (str(v).strip() if v is not None else "") for k, v in row.items() if k}
                if any(cleaned.values()):
                    rows.append(cleaned)
            return rows
    if suffix == ".xlsx":
        try:
            import openpyxl  # type: ignore

            wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
            ws = wb.active
            iter_rows = list(ws.iter_rows(values_only=True))
            if not iter_rows:
                return []
            headers = [str(h or "").strip() for h in iter_rows[0]]
            rows = []
            for values in iter_rows[1:]:
                if not any(v is not None and str(v).strip() for v in values):
                    continue
                rows.append({
                    headers[i]: (str(values[i]).strip() if i < len(values) and values[i] is not None else "")
                    for i in range(len(headers))
                    if headers[i]
                })
            return rows
        except ImportError:
            return _read_xlsx_stdlib(path)
    raise CommandError(f"Định dạng không hỗ trợ ({suffix}); chỉ nhận .csv hoặc .xlsx.")


def _parse_dt(raw: str, *, default_now: bool = False):
    if not raw:
        return timezone.now() if default_now else None
    dt = parse_datetime(raw)
    if dt is None:
        d = parse_date(raw)
        if d is not None:
            dt = datetime(d.year, d.month, d.day, 9, 0, 0)
    if dt is not None and timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def _resolve_user(identifier: str) -> User | None:
    ident = (identifier or "").strip()
    if not ident:
        return None
    user = User.objects.filter(username__iexact=ident).first()
    if user:
        return user
    return User.objects.filter(normalized_email=ident.lower()).first()


def _import_structure(rows: list[dict[str, str]], report: ImportReport, update_existing: bool) -> None:
    for idx, row in enumerate(rows, start=2):
        code = row.get("department_code", "").strip().upper()
        name = row.get("department_name", "").strip()
        slug = row.get("slug", "").strip().lower()
        if not code or not name or not slug:
            report.add_error(idx, "Thiếu department_code, department_name hoặc slug.")
            continue
        dept = Department.objects.filter(code=code).first()
        if dept is None:
            if Department.objects.filter(slug=slug).exists():
                report.add_error(idx, f"Slug `{slug}` đã thuộc về Ban khác.")
                continue
            dept = Department.objects.create(
                code=code,
                name=name,
                slug=slug,
                short_description=row.get("short_description", "")[:255],
                is_demo=row.get("is_demo", "").lower() in ("1", "true", "yes"),
                display_order=int(row.get("display_order") or 10),
            )
            report.created += 1
        elif update_existing:
            dept.name = name
            dept.short_description = row.get("short_description", dept.short_description)[:255]
            dept.save(update_fields=["name", "short_description"])
            report.updated += 1
        else:
            report.skipped += 1

        cat_code = row.get("skill_category_code", "").strip().upper()
        cat_name = row.get("skill_category_name", "").strip()
        skill_code = row.get("skill_code", "").strip().upper()
        skill_name = row.get("skill_name", "").strip()
        if cat_code and cat_name:
            cat, _ = SkillCategory.objects.get_or_create(
                code=cat_code,
                defaults={"name": cat_name, "department": dept},
            )
            if skill_code and skill_name:
                Skill.objects.get_or_create(
                    code=skill_code,
                    defaults={"category": cat, "name": skill_name},
                )


def _import_members(rows: list[dict[str, str]], report: ImportReport, update_existing: bool) -> None:
    seen_usernames: set[str] = set()
    seen_emails: set[str] = set()
    seen_mssvs: set[str] = set()

    for idx, row in enumerate(rows, start=2):
        username = row.get("username", "").strip()
        full_name = row.get("full_name", "").strip()
        email = row.get("email", "").strip().lower()
        mssv = row.get("mssv", "").strip()
        phone = row.get("phone", "").strip()
        dept_code = row.get("department_code", "").strip().upper()

        if not username or not full_name:
            report.add_error(idx, "Thiếu `username` hoặc `full_name`.")
            continue
        if username.lower() in seen_usernames:
            report.add_error(idx, f"Trùng `username` trong tệp: {username}.")
            continue
        seen_usernames.add(username.lower())

        if email:
            if email in seen_emails:
                report.add_error(idx, f"Trùng `email` trong tệp: {email}.")
                continue
            seen_emails.add(email)
        if mssv:
            if mssv in seen_mssvs:
                report.add_error(idx, f"Trùng `mssv` trong tệp: {mssv}.")
                continue
            seen_mssvs.add(mssv)

        dept = None
        if dept_code:
            dept = Department.objects.filter(code=dept_code).first()
            if dept is None:
                report.add_error(idx, f"Mã Ban `{dept_code}` chưa tồn tại.")
                continue

        requested_role = row.get("role", "").strip().upper()
        if requested_role in (Role.ADMIN, "SUPERUSER"):
            report.add_error(idx, "Từ chối gán quyền Admin/Superuser qua tệp import hàng loạt.")
            continue

        norm_phone = normalize_phone_number(phone) if phone else None
        if phone and not norm_phone:
            report.add_error(idx, f"Số điện thoại không hợp lệ: {phone}.")
            continue

        affiliation = row.get("affiliation", Affiliation.KMA).strip().upper()
        if affiliation not in Affiliation.values:
            report.add_error(idx, f"Affiliation không hợp lệ: {affiliation}.")
            continue

        joined_at = parse_date(row.get("joined_at", "")) or timezone.localdate()
        status = row.get("membership_status", ClubMembershipStatus.ACTIVE).strip().upper()
        if status not in ClubMembershipStatus.values:
            report.add_error(idx, f"Trạng thái thành viên không hợp lệ: {status}.")
            continue

        user = User.objects.filter(username__iexact=username).first()
        if user is None:
            if email and User.objects.filter(normalized_email=email).exists():
                report.add_error(idx, f"Email `{email}` đã gắn với tài khoản khác.")
                continue
            if mssv and User.objects.filter(mssv=mssv).exists():
                report.add_error(idx, f"MSSV `{mssv}` đã tồn tại.")
                continue
            if norm_phone and User.objects.filter(normalized_phone=norm_phone).exists():
                report.add_error(idx, f"SĐT `{phone}` đã tồn tại.")
                continue

            user = User(
                username=username,
                full_name=full_name,
                display_name=row.get("display_name", "") or full_name,
                email=email,
                phone=phone,
                mssv=mssv or None,
                affiliation=affiliation,
                school=row.get("school", ""),
                role=Role.MEMBER,
                account_status=AccountStatus.ACTIVE,
            )
            user.set_unusable_password()
            user.save()
            member_code = row.get("member_code", "").strip() or _generate_next_member_code(joined_at.year)
            ClubMembership.objects.create(
                user=user,
                member_code=member_code,
                status=status,
                joined_at=joined_at,
            )
            if dept is not None:
                DepartmentMembership.objects.get_or_create(
                    user=user,
                    department=dept,
                    defaults={"status": DeptMembershipStatus.ACTIVE, "joined_at": joined_at},
                )
            record_lifecycle_event(
                user=user,
                event_type=LifecycleEventType.APPROVED_CLUB,
                department=dept,
                title="Nhập hồ sơ thành viên chính thức KMG",
                note=row.get("note", "Nhập từ tệp tổ chức"),
            )
            report.created += 1
        elif update_existing:
            user.full_name = full_name
            if row.get("display_name"):
                user.display_name = row["display_name"]
            if row.get("school"):
                user.school = row["school"]
            user.save()
            if dept is not None:
                DepartmentMembership.objects.get_or_create(
                    user=user,
                    department=dept,
                    defaults={"status": DeptMembershipStatus.ACTIVE, "joined_at": joined_at},
                )
            report.updated += 1
        else:
            if dept is not None and not DepartmentMembership.objects.filter(user=user, department=dept).exists():
                DepartmentMembership.objects.create(
                    user=user,
                    department=dept,
                    status=DeptMembershipStatus.ACTIVE,
                    joined_at=joined_at,
                )
                report.updated += 1
            else:
                report.skipped += 1


def _import_skills(rows: list[dict[str, str]], report: ImportReport, update_existing: bool) -> None:
    for idx, row in enumerate(rows, start=2):
        user = _resolve_user(row.get("username_or_email", "") or row.get("username", ""))
        skill_code = row.get("skill_code", "").strip().upper()
        prof = row.get("proficiency", SkillProficiency.INTERMEDIATE).strip().upper()
        if user is None:
            report.add_error(idx, "Không tìm thấy thành viên tương ứng.")
            continue
        skill = Skill.objects.filter(code=skill_code).first()
        if skill is None:
            report.add_error(idx, f"Mã kỹ năng `{skill_code}` không tồn tại.")
            continue
        if prof not in SkillProficiency.values:
            report.add_error(idx, f"Mức thành thạo `{prof}` không hợp lệ.")
            continue
        verifier = _resolve_user(row.get("verified_by", ""))
        existing = UserSkill.objects.filter(user=user, skill=skill).first()
        if existing is None:
            UserSkill.objects.create(
                user=user,
                skill=skill,
                proficiency=prof,
                verification_status=(
                    SkillVerificationStatus.VERIFIED if verifier else SkillVerificationStatus.SELF_DECLARED
                ),
                verified_by=verifier,
                verified_at=timezone.now() if verifier else None,
                experience_note=row.get("experience_note", row.get("evidence_note", ""))[:255],
            )
            report.created += 1
        elif update_existing:
            existing.proficiency = prof
            existing.experience_note = row.get("experience_note", row.get("evidence_note", existing.experience_note))[:255]
            existing.save(update_fields=["proficiency", "experience_note"])
            report.updated += 1
        else:
            report.skipped += 1


def _import_appointments(
    rows: list[dict[str, str]],
    report: ImportReport,
    approver: User | None,
) -> None:
    if approver is None or not (approver.is_admin_role or approver.is_superuser):
        raise CommandError(
            "Nhập chức vụ/nhiệm kỳ bắt buộc chỉ định `--approve-by <admin_username>` đã được phê duyệt."
        )
    for idx, row in enumerate(rows, start=2):
        user = _resolve_user(row.get("username_or_email", "") or row.get("username", ""))
        pos_code = row.get("position_code", "").strip().upper()
        dept_code = row.get("department_code", "").strip().upper()
        term_label = row.get("term_label", "2026-2027").strip() or "2026-2027"
        if user is None:
            report.add_error(idx, "Không tìm thấy người được bổ nhiệm.")
            continue
        pos = Position.objects.filter(code=pos_code).first() if pos_code in PositionCode.values else None
        if pos is None:
            report.add_error(idx, f"Mã chức vụ `{pos_code}` không tồn tại trong danh mục.")
            continue
        dept = Department.objects.filter(code=dept_code).first() if dept_code else None
        if dept_code and dept is None:
            report.add_error(idx, f"Mã Ban `{dept_code}` không tồn tại.")
            continue
        ends_at = _parse_dt(row.get("ends_at", ""), default_now=False)
        try:
            appoint_officer(
                actor=approver,
                target_user=user,
                position=pos,
                department=dept,
                term_label=term_label,
                title_note=row.get("title_note", ""),
                ends_at=ends_at,
            )
            report.created += 1
        except GovernanceError as exc:
            report.add_error(idx, str(exc))


def _import_history(rows: list[dict[str, str]], report: ImportReport) -> None:
    for idx, row in enumerate(rows, start=2):
        user = _resolve_user(row.get("username_or_email", "") or row.get("username", ""))
        event_type = row.get("event_type", "").strip().upper()
        title = row.get("title", "").strip()
        if user is None or not title:
            report.add_error(idx, "Thiếu người dùng hợp lệ hoặc tiêu đề mốc lịch sử.")
            continue
        if event_type not in LifecycleEventType.values:
            report.add_error(idx, f"Loại sự kiện lịch sử `{event_type}` không hợp lệ.")
            continue
        dept_code = row.get("department_code", "").strip().upper()
        dept = Department.objects.filter(code=dept_code).first() if dept_code else None
        if dept_code and dept is None:
            report.add_error(idx, f"Mã Ban `{dept_code}` không tồn tại.")
            continue
        note = row.get("note", "")[:255]
        if MemberLifecycleEvent.objects.filter(user=user, event_type=event_type, title=title[:200]).exists():
            report.skipped += 1
            continue
        record_lifecycle_event(
            user=user,
            event_type=event_type,
            department=dept,
            title=title,
            note=note,
            metadata={"imported": True},
        )
        report.created += 1


def run_org_import(
    *,
    kind: str,
    file_path: str | Path,
    dry_run: bool = False,
    update_existing: bool = False,
    approve_by_username: str = "",
) -> ImportReport:
    if kind not in SUPPORTED_KINDS:
        raise CommandError(f"Loại import `{kind}` không hợp lệ; chọn một trong {SUPPORTED_KINDS}.")
    rows = read_tabular_file(file_path)
    report = ImportReport(kind=kind, file_path=str(file_path), dry_run=dry_run, total_rows=len(rows))
    approver = _resolve_user(approve_by_username) if approve_by_username else None

    with transaction.atomic():
        if kind == "structure":
            _import_structure(rows, report, update_existing)
        elif kind == "members":
            _import_members(rows, report, update_existing)
        elif kind == "skills":
            _import_skills(rows, report, update_existing)
        elif kind == "appointments":
            _import_appointments(rows, report, approver)
        elif kind == "history":
            _import_history(rows, report)
        if dry_run:
            transaction.set_rollback(True)
    return report
