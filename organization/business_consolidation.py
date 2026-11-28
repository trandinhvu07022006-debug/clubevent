"""
Công cụ kiểm kê, ánh xạ và diễn tập chuyển đổi Hợp nhất Hệ thống Nghiệp vụ (`BUS-01`, `BUS-03`).

Chuyển đổi an toàn, idempotent từ 3 mô hình legacy sang Canonical Models:
  1. `organizing.Department` -> `organization.Department` (+ `DepartmentMembership`, `DEPT_HEAD`)
  2. `organizing.Task` -> `operations.ClubTask` (+ `TaskAssignee`)
  3. `recruitment.Application` -> `organization.MembershipApplication`

Nguyên tắc an toàn:
  - Không xóa hoặc sửa bản ghi ở các bảng cũ.
  - Mặc định `dry_run=True` (rollback giao dịch sau khi đối soát).
  - Hỗ trợ chạy lại idempotent: dùng natural key / `category_tag` marker để tránh nhân bản.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone


@dataclass
class ConsolidationReport:
    dry_run: bool
    source_counts: dict[str, int] = field(default_factory=dict)
    created: dict[str, int] = field(default_factory=dict)
    skipped_duplicate: dict[str, int] = field(default_factory=dict)
    unmapped_notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    target_counts_after: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "ok": self.ok,
            "source_counts": self.source_counts,
            "created": self.created,
            "skipped_duplicate": self.skipped_duplicate,
            "target_counts_after": self.target_counts_after,
            "unmapped_notes": self.unmapped_notes,
            "errors": self.errors,
        }


_TASK_PRIORITY_MAP = {
    "LOW": "LOW",
    "NORMAL": "MEDIUM",
    "HIGH": "HIGH",
    "URGENT": "URGENT",
}

_TASK_STATUS_MAP = {
    "TODO": "ASSIGNED",
    "DOING": "IN_PROGRESS",
    "DONE": "APPROVED",
}

_APP_STATUS_MAP = {
    "PENDING": "SUBMITTED",
    "INTERVIEW": "DEPT_SCREENED",
    "APPROVED": "APPROVED",
    "REJECTED": "REJECTED",
}


def _gen_dept_code(slug: str) -> str:
    raw = (slug or "DEPT").upper().replace("-", "_")
    cleaned = "".join(ch for ch in raw if ch.isalnum() or ch == "_")
    return (cleaned or "DEPT")[:32]


def run_unified_business_rehearsal(*, dry_run: bool = True) -> ConsolidationReport:
    """Chạy kiểm kê, ánh xạ và đối soát 3 cặp mô hình song song (`dry_run=True` mặc định)."""
    from operations.models import AssigneeRole, ClubTask, ClubTaskAssignee
    from organization.models import (
        Appointment,
        Department as OrgDepartment,
        DepartmentMembership,
        DeptMembershipStatus,
        MembershipApplication,
        Position,
        PositionCode,
        ScopeType,
    )
    from organizing.models import Department as LegacyDepartment, Task as LegacyTask
    from recruitment.models import Application as LegacyApplication

    report = ConsolidationReport(
        dry_run=dry_run,
        source_counts={
            "organizing.Department": LegacyDepartment.objects.count(),
            "organizing.Task": LegacyTask.objects.count(),
            "recruitment.Application": LegacyApplication.objects.count(),
        },
        created={"Department": 0, "DepartmentMembership": 0, "ClubTask": 0, "MembershipApplication": 0},
        skipped_duplicate={"Department": 0, "DepartmentMembership": 0, "ClubTask": 0, "MembershipApplication": 0},
    )

    with transaction.atomic():
        # 1. organizing.Department -> organization.Department
        dept_map: dict[int, OrgDepartment] = {}
        for l_dept in LegacyDepartment.objects.prefetch_related("members").select_related("lead").order_by("id"):
            canon = OrgDepartment.objects.filter(slug=l_dept.slug).first()
            if canon is None:
                code = _gen_dept_code(l_dept.slug)
                if OrgDepartment.objects.filter(code=code).exists():
                    code = f"{code[:26]}_{l_dept.id}"[:32]
                canon = OrgDepartment.objects.create(
                    code=code,
                    name=l_dept.name[:120],
                    slug=l_dept.slug[:80],
                    short_description=(l_dept.description or "")[:255],
                    description=l_dept.description or "",
                    icon=(l_dept.icon or "bi-music-note-list")[:60],
                    display_order=l_dept.order,
                    is_active=True,
                )
                report.created["Department"] += 1
            else:
                report.skipped_duplicate["Department"] += 1
            dept_map[l_dept.id] = canon

            # Đồng bộ thành viên M2M sang DepartmentMembership
            for member in l_dept.members.all():
                _, m_created = DepartmentMembership.objects.get_or_create(
                    user=member,
                    department=canon,
                    defaults={"status": DeptMembershipStatus.ACTIVE},
                )
                if m_created:
                    report.created["DepartmentMembership"] += 1
                else:
                    report.skipped_duplicate["DepartmentMembership"] += 1

            # Đồng bộ Trưởng ban nếu Ban đích chưa có Trưởng ban đương nhiệm
            if l_dept.lead_id:
                pos_head = Position.objects.filter(code=PositionCode.DEPT_HEAD).first()
                if pos_head and not Appointment.objects.filter(
                    department=canon, position=pos_head, is_active=True
                ).exists():
                    Appointment.objects.create(
                        user=l_dept.lead,
                        position=pos_head,
                        scope_type=ScopeType.DEPARTMENT,
                        department=canon,
                        title_note="Đồng bộ từ mô hình Ban cũ",
                    )

        # Ban dự phòng cho các Task chung không gắn Department
        fallback_dept = OrgDepartment.objects.filter(is_active=True).order_by("display_order", "id").first()

        # 2. organizing.Task -> operations.ClubTask
        for l_task in LegacyTask.objects.select_related("department", "event", "assignee", "created_by").order_by("id"):
            marker = f"legacy_task:{l_task.id}"
            if ClubTask.objects.filter(category_tag=marker).exists():
                report.skipped_duplicate["ClubTask"] += 1
                continue
            target_dept = dept_map.get(l_task.department_id) if l_task.department_id else fallback_dept
            if target_dept is None:
                report.errors.append(f"organizing.Task#{l_task.id}: không có Ban đích hợp lệ.")
                continue
            if l_task.department_id is None:
                report.unmapped_notes.append(
                    f"organizing.Task#{l_task.id} ('{l_task.title}') không gắn Ban -> ánh xạ về Ban '{target_dept.name}'."
                )

            desc = l_task.description or ""
            if l_task.note:
                desc = f"{desc}\n[Ghi chú cũ]: {l_task.note}".strip()
            deadline = l_task.deadline or (l_task.created_at + timedelta(days=7))
            c_task = ClubTask.objects.create(
                title=l_task.title[:200],
                description=desc,
                department=target_dept,
                event=l_task.event,
                category_tag=marker,
                priority=_TASK_PRIORITY_MAP.get(l_task.priority, "MEDIUM"),
                workflow_status=_TASK_STATUS_MAP.get(l_task.status, "ASSIGNED"),
                progress_percent=100 if l_task.status == "DONE" else (50 if l_task.status == "DOING" else 0),
                deadline=deadline,
                created_by=l_task.created_by,
                completed_at=l_task.done_at if l_task.status == "DONE" else None,
            )
            if l_task.assignee_id:
                ClubTaskAssignee.objects.get_or_create(
                    task=c_task,
                    user=l_task.assignee,
                    defaults={"role": AssigneeRole.LEAD},
                )
            report.created["ClubTask"] += 1

        # 3. recruitment.Application -> organization.MembershipApplication
        for l_app in LegacyApplication.objects.select_related("user", "department", "reviewer").order_by("id"):
            target_dept = dept_map.get(l_app.department_id) if l_app.department_id else fallback_dept
            if target_dept is None:
                report.errors.append(f"recruitment.Application#{l_app.id}: không có Ban đích hợp lệ.")
                continue
            target_status = _APP_STATUS_MAP.get(l_app.status, "SUBMITTED")
            exists = MembershipApplication.objects.filter(
                user=l_app.user,
                primary_department=target_dept,
                motivation=l_app.motivation[:1500],
            ).exists()
            if exists:
                report.skipped_duplicate["MembershipApplication"] += 1
                continue

            screening_parts = []
            if l_app.interview_at:
                screening_parts.append(f"Lịch casting/PV: {timezone.localtime(l_app.interview_at):%H:%M %d/%m/%Y}")
            if l_app.review_note:
                screening_parts.append(l_app.review_note)

            MembershipApplication.objects.create(
                user=l_app.user,
                primary_department=target_dept,
                declared_skills_text=f"{l_app.strengths} ({l_app.get_level_display()})"[:255],
                motivation=(l_app.motivation or "Đăng ký gia nhập KMG")[:1500],
                portfolio_url=l_app.portfolio_url or "",
                status=target_status,
                screening_note=" · ".join(screening_parts)[:255],
                reviewed_by=l_app.reviewer,
                reviewed_at=l_app.reviewed_at,
                decision_note=(l_app.review_note or "")[:255] if target_status in ("APPROVED", "REJECTED") else "",
            )
            report.created["MembershipApplication"] += 1

        # Đối soát số lượng sau ánh xạ
        report.target_counts_after = {
            "organization.Department": OrgDepartment.objects.count(),
            "operations.ClubTask": ClubTask.objects.count(),
            "organization.MembershipApplication": MembershipApplication.objects.count(),
        }

        if dry_run:
            transaction.set_rollback(True)

    return report
