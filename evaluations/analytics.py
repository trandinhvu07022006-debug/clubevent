"""
Phân tích Vận hành & Đánh giá Cấp Ban & Toàn CLB (`evaluations.analytics`).

Tuân thủ:
- Chỉ thị 3.3: Tuyệt đối KHÔNG xếp hạng điểm số (no numeric leaderboard) giữa các thành viên.
- Phân quyền theo phạm vi:
  - Toàn CLB: Ban Chủ nhiệm & Cố vấn (Cố vấn ở chế độ Hard Read-Only `INV-04`, che thông tin cá nhân `PA-07`).
  - Cấp Ban: Trưởng ban & Phó ban trong phạm vi Ban quản lý.
- `SEC-02`: Xuất CSV an toàn bằng `safe_csv_row` chống Formula Injection.
"""
from __future__ import annotations

import csv
import io
from typing import Any

from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.utils import timezone

from accounts.models import User
from core.security import safe_csv_row
from operations.models import (
    CheckinStatus,
    ClubEventProfile,
    ClubTask,
    DisciplineCase,
    DisciplineStatus,
    EventAttendance,
    TaskWorkflowStatus,
)
from operations.services import redact_pii_for_advisor
from organization.models import (
    ClubMembership,
    ClubMembershipStatus,
    Department,
    DepartmentMembership,
    DeptMembershipStatus,
    PositionCode,
    ScopeType,
    UserSkill,
)
from organization.permissions import PermissionEngine
from programs.models import (
    ConfidentialDocument,
    DepartmentProposal,
    PracticeParticipant,
    PracticeResponseStatus,
    PracticeSession,
    ProposalStatus,
    TrainingCourse,
    TrainingEnrollment,
    TrainingEnrollmentStatus,
)
from programs.services import _is_pure_advisor
from social.models import SocialPost

from .models import (
    EvaluationCycle,
    EvaluationCycleStatus,
    EvaluationStatus,
    MemberEvaluation,
    MemberRecognition,
    OverallRating,
    RecognitionStatus,
)


def can_view_club_analytics(actor: User) -> bool:
    if not actor or not getattr(actor, "is_authenticated", False):
        return False
    return any(
        PermissionEngine.authorize(actor, code)
        for code in (
            "club.overview.supervise",
            "club.report.export",
            "club.dept.supervise_ops",
            "club.evaluation.finalize",
        )
    )


def can_view_dept_analytics(actor: User, department: Department) -> bool:
    if not actor or not getattr(actor, "is_authenticated", False):
        return False
    if can_view_club_analytics(actor):
        return True
    return PermissionEngine.authorize(
        actor, "dept.progress.view_summary", department=department
    )


def accessible_departments_for_analytics(actor: User) -> list[Department]:
    all_depts = list(Department.objects.filter(is_active=True))
    if can_view_club_analytics(actor):
        return all_depts
    return [d for d in all_depts if can_view_dept_analytics(actor, d)]


def build_department_analytics(actor: User, department: Department) -> dict[str, Any]:
    """Tổng hợp chỉ số vận hành & đánh giá trong phạm vi 1 Ban."""
    if not can_view_dept_analytics(actor, department):
        raise PermissionDenied(f"Bạn không có quyền xem thống kê của {department.name}.")
    return _build_department_summaries([department])[0]


def _build_department_summaries(departments: list[Department]) -> list[dict[str, Any]]:
    """Chỉ gọi sau kiểm tra quyền; gom mỗi bảng một lần cho toàn bộ Ban được phép.

    Không JOIN nhiều quan hệ một-nhiều trong cùng phép đếm vì sẽ nhân số liệu.
    Không cache kết quả theo người dùng để tránh quyền vừa thu hồi còn hiệu lực.
    """
    if not departments:
        return []
    dept_ids = [department.pk for department in departments]
    now = timezone.now()

    def grouped(queryset, field="department_id", **aggregates):
        return {
            row[field]: row
            for row in queryset.filter(**{f"{field}__in": dept_ids})
            .order_by().values(field).annotate(**(aggregates or {"total": Count("pk")}))
        }

    members = grouped(DepartmentMembership.objects.filter(status=DeptMembershipStatus.ACTIVE))
    open_task = ~Q(workflow_status__in=[
        TaskWorkflowStatus.APPROVED, TaskWorkflowStatus.REJECTED, TaskWorkflowStatus.CANCELLED,
    ])
    tasks = grouped(
        ClubTask.objects.all(),
        total=Count("pk"),
        approved=Count("pk", filter=Q(workflow_status=TaskWorkflowStatus.APPROVED)),
        open=Count("pk", filter=open_task),
        overdue=Count("pk", filter=open_task & Q(deadline__lt=now)),
    )
    events = grouped(ClubEventProfile.objects.all(), "lead_department_id")
    attendance = grouped(
        EventAttendance.objects.all(), "club_event__lead_department_id",
        total=Count("pk"),
        present=Count("pk", filter=Q(checkin_status__in=[CheckinStatus.PRESENT, CheckinStatus.LATE])),
    )
    courses = grouped(TrainingCourse.objects.all())
    completions = grouped(
        TrainingEnrollment.objects.filter(status=TrainingEnrollmentStatus.COMPLETED),
        "course__department_id",
    )
    practices = grouped(PracticeSession.objects.all())
    practices_attended = grouped(
        PracticeParticipant.objects.filter(response_status=PracticeResponseStatus.ATTENDED),
        "session__department_id",
    )
    proposals = grouped(
        DepartmentProposal.objects.all(),
        total=Count("pk"),
        approved=Count("pk", filter=Q(status__in=[
            ProposalStatus.APPROVED, ProposalStatus.IN_PROGRESS, ProposalStatus.COMPLETED,
        ])),
    )
    documents = grouped(ConfidentialDocument.objects.filter(is_archived=False))
    latest_cycle = EvaluationCycle.objects.filter(status=EvaluationCycleStatus.OPEN).order_by("-starts_on").first()
    evaluations_qs = MemberEvaluation.objects.all()
    if latest_cycle:
        evaluations_qs = evaluations_qs.filter(cycle=latest_cycle)
    evaluations = grouped(
        evaluations_qs,
        total=Count("pk"),
        confirmed=Count("pk", filter=Q(status=EvaluationStatus.CONFIRMED)),
        draft=Count("pk", filter=Q(status=EvaluationStatus.DRAFT)),
        **{
            f"rating_{rating}": Count("pk", filter=Q(status=EvaluationStatus.CONFIRMED, overall_rating=rating))
            for rating in OverallRating.values
        },
    )
    recognitions = grouped(MemberRecognition.objects.filter(status=RecognitionStatus.VERIFIED))

    def count(data, dept_id, key="total"):
        return data.get(dept_id, {}).get(key, 0)

    summaries = []
    for department in departments:
        pk = department.pk
        task_counts = {key: count(tasks, pk, key) for key in ("total", "approved", "open", "overdue")}
        task_counts["rate"] = round(task_counts["approved"] / task_counts["total"] * 100, 1) if task_counts["total"] else 0.0
        total_attendances = count(attendance, pk)
        present_attendances = count(attendance, pk, "present")
        summaries.append({
            "department": department,
            "active_members_count": count(members, pk),
            "tasks": task_counts,
            "events": {
                "total": count(events, pk),
                "total_attendances": total_attendances,
                "present_attendances": present_attendances,
                "attendance_rate": round(present_attendances / total_attendances * 100, 1) if total_attendances else 0.0,
            },
            "training": {
                "courses_count": count(courses, pk),
                "training_completions": count(completions, pk),
                "practices_count": count(practices, pk),
                "practices_attended": count(practices_attended, pk),
            },
            "proposals": {"total": count(proposals, pk), "approved": count(proposals, pk, "approved")},
            "documents_count": count(documents, pk),
            "evaluations": {
                "cycle": latest_cycle,
                "total": count(evaluations, pk),
                "confirmed": count(evaluations, pk, "confirmed"),
                "draft": count(evaluations, pk, "draft"),
                "distribution": {rating: count(evaluations, pk, f"rating_{rating}") for rating in OverallRating.values},
            },
            "recognitions_count": count(recognitions, pk),
        })
    return summaries


def build_executive_analytics(actor: User) -> dict[str, Any]:
    """Tổng quan phân tích toàn CLB dành cho Ban Chủ nhiệm và Cố vấn (`INV-04`)."""
    if not can_view_club_analytics(actor):
        raise PermissionDenied("Bạn không có quyền xem phân tích cấp toàn CLB.")

    is_advisor = _is_pure_advisor(actor)
    departments = list(Department.objects.filter(is_active=True))

    dept_summaries = _build_department_summaries(departments)

    # Nhân sự CLB
    club_active_members = ClubMembership.objects.filter(
        status=ClubMembershipStatus.ACTIVE
    ).count()
    club_suspended_members = ClubMembership.objects.filter(
        status=ClubMembershipStatus.SUSPENDED
    ).count()
    verified_skills_count = UserSkill.objects.filter(verification_status="VERIFIED").count()

    # Kỷ luật
    flagged_discipline = DisciplineCase.objects.filter(
        status__in=[DisciplineStatus.FLAGGED, DisciplineStatus.UNDER_REVIEW]
    ).count()

    # Mạng xã hội & Tương tác
    total_posts = SocialPost.objects.filter(is_deleted=False).count()

    # Tài chính CLB (chỉ đọc)
    from finance.services import compute_club_fund_summary

    fund_summary = compute_club_fund_summary()

    # Vinh danh
    club_recognitions = list(
        MemberRecognition.objects.select_related("recipient", "department", "cycle")
        .filter(status=RecognitionStatus.VERIFIED)
        .order_by("-verified_at")[:10]
    )

    return {
        "is_advisor": is_advisor,
        "departments": departments,
        "dept_summaries": dept_summaries,
        "club_kpis": {
            "active_members": club_active_members,
            "suspended_members": club_suspended_members,
            "verified_skills": verified_skills_count,
            "flagged_discipline": flagged_discipline,
            "total_posts": total_posts,
            "net_fund_balance": fund_summary["net_club_balance"],
            "fund_confirmed_income": fund_summary["confirmed_income"],
            "fund_confirmed_expense": fund_summary["confirmed_expense"],
            "fund_pending_count": fund_summary["pending_count"],
        },
        "recent_recognitions": [
            {
                "id": r.id,
                "title": r.title,
                "recipient_name": (
                    redact_pii_for_advisor(r.recipient.public_name)
                    if is_advisor
                    else r.recipient.public_name
                ),
                "scope": r.get_scope_display(),
                "department_name": r.department.name if r.department else "Toàn CLB",
                "is_public": r.is_public,
                "verified_at": r.verified_at,
            }
            for r in club_recognitions
        ],
    }


def export_analytics_csv(actor: User) -> str:
    """Xuất báo cáo phân tích vận hành ra định dạng CSV an toàn (`SEC-02` + `PA-07`)."""
    if not (
        can_view_club_analytics(actor)
        or PermissionEngine.authorize(actor, "club.report.export")
    ):
        raise PermissionDenied("Bạn không có quyền xuất báo cáo tổng hợp.")

    is_advisor = _is_pure_advisor(actor)
    data = build_executive_analytics(actor)

    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.writer(buf)

    # 1. Chỉ số cấp CLB
    writer.writerow(["BÁO CÁO PHÂN TÍCH VẬN HÀNH & ĐÁNH GIÁ CLB KMG"])
    writer.writerow([f"Thời điểm xuất: {timezone.localtime().strftime('%d/%m/%Y %H:%M')}"])
    if is_advisor:
        writer.writerow(["Chế độ xuất: Giám sát Độc lập (INV-04 / PA-07 che PII)"])
    writer.writerow([])

    writer.writerow(["CHỈ SỐ TOÀN CLB"])
    writer.writerow(["Thành viên chính thức (ACTIVE)", data["club_kpis"]["active_members"]])
    writer.writerow(["Thành viên tạm khoá (SUSPENDED)", data["club_kpis"]["suspended_members"]])
    writer.writerow(["Kỹ năng chuyên môn đã xác minh", data["club_kpis"]["verified_skills"]])
    writer.writerow(["Hồ sơ chuyên cần/kỷ luật đang mở", data["club_kpis"]["flagged_discipline"]])
    writer.writerow(["Số dư quỹ CLB đã ghi sổ (VND)", data["club_kpis"]["net_fund_balance"]])
    writer.writerow(["Tổng thu đã ghi sổ (VND)", data["club_kpis"]["fund_confirmed_income"]])
    writer.writerow(["Tổng chi đã ghi sổ (VND)", data["club_kpis"]["fund_confirmed_expense"]])
    writer.writerow(["Phiếu quỹ chờ duyệt", data["club_kpis"]["fund_pending_count"]])
    writer.writerow([])

    # 2. Chi tiết theo từng Ban
    writer.writerow(
        [
            "Ban",
            "Nhân sự ACTIVE",
            "Nhiệm vụ (Hoàn thành / Tổng)",
            "Tỉ lệ xong việc (%)",
            "Nhiệm vụ quá hạn",
            "Tỉ lệ có mặt sự kiện (%)",
            "Buổi tập đã tham gia",
            "Khoá đào tạo hoàn thành",
            "Đề xuất (Đã duyệt / Tổng)",
            "Tài liệu mật Ban",
            "Phiếu đánh giá kỳ này (Đã chốt / Tổng)",
            "Số lượt vinh danh",
        ]
    )
    for ds in data["dept_summaries"]:
        dept = ds["department"]
        t = ds["tasks"]
        ev = ds["events"]
        tr = ds["training"]
        p = ds["proposals"]
        evals = ds["evaluations"]
        writer.writerow(
            safe_csv_row(
                [
                    dept.name,
                    ds["active_members_count"],
                    f"{t['approved']}/{t['total']}",
                    t["rate"],
                    t["overdue"],
                    ev["attendance_rate"],
                    tr["practices_attended"],
                    tr["training_completions"],
                    f"{p['approved']}/{p['total']}",
                    ds["documents_count"],
                    f"{evals['confirmed']}/{evals['total']}",
                    ds["recognitions_count"],
                ]
            )
        )

    return buf.getvalue()
