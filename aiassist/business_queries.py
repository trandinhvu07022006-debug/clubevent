"""
Authorized, read-only Django ORM queries for KMG AI (Phase 7).

All authorization checks use `organization.permissions.PermissionEngine` on the
authenticated server-side `user`. Never trust self-declared roles in user text.
"""
from __future__ import annotations

from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from organization.permissions import PermissionEngine


def _check_active_user(user) -> dict | None:
    """Trả về thông báo từ chối nếu chưa đăng nhập hoặc tài khoản đang bị khóa."""
    if not user or not getattr(user, "is_authenticated", False) or not getattr(user, "pk", None):
        return {
            "text": "Bạn cần đăng nhập thì mình mới tra được thông tin cá nhân.",
            "links": [{"label": "Đăng nhập", "url": reverse("accounts:login")}],
        }
    from accounts.models import AccountStatus

    if getattr(user, "is_locked", False) or getattr(user, "account_status", None) == AccountStatus.LOCKED:
        return {
            "text": "Tài khoản của bạn hiện đang bị khóa nên không thể tra cứu thông tin cá nhân.",
            "links": [],
        }
    return None


def query_my_practice(user) -> dict:
    """Lịch tập (PracticeSession) sắp tới của thành viên."""
    denied = _check_active_user(user)
    if denied is not None:
        return denied

    from programs.models import PracticeParticipant, PracticeSession, PracticeSessionStatus

    now = timezone.now()
    my_parts = list(
        PracticeParticipant.objects.filter(
            user=user,
            session__starts_at__gte=now,
        )
        .exclude(session__status=PracticeSessionStatus.CANCELLED)
        .select_related("session", "session__department")
        .order_by("session__starts_at")[:5]
    )
    if my_parts:
        lines = ["Lịch tập sắp tới của bạn:"]
        for p in my_parts:
            s = p.session
            when = timezone.localtime(s.starts_at).strftime("%H:%M %d/%m")
            dept = f" ({s.department.name})" if s.department else ""
            lines.append(f"• {s.title}{dept} — {when} tại {s.location or 'CLB'} [{p.get_response_status_display()}]")
        return {
            "text": "\n".join(lines),
            "links": [{"label": "Mở Không gian Đào tạo & Tập luyện", "url": reverse("programs:training_practice_hub")}],
        }

    # If user is a club member, show general upcoming club practice sessions
    if PermissionEngine.authorize(user, "club.event.view_internal"):
        sessions = list(
            PracticeSession.objects.filter(starts_at__gte=now)
            .exclude(status=PracticeSessionStatus.CANCELLED)
            .order_by("starts_at")[:5]
        )
        if sessions:
            lines = ["Bạn chưa có lịch tập riêng, nhưng CLB có các buổi tập sắp tới:"]
            for s in sessions:
                when = timezone.localtime(s.starts_at).strftime("%H:%M %d/%m")
                lines.append(f"• {s.title} — {when} tại {s.location or 'CLB'}")
            return {
                "text": "\n".join(lines),
                "links": [{"label": "Xem lịch tập CLB", "url": reverse("programs:training_practice_hub")}],
            }

    return {
        "text": "Hiện bạn chưa có lịch tập nào sắp tới được xếp trên hệ thống.",
        "links": [{"label": "Xem Không gian Đào tạo & Tập luyện", "url": reverse("programs:training_practice_hub")}],
    }


def query_my_recruitment_status(user) -> dict:
    """Trạng thái hồ sơ tuyển thành viên cá nhân (hợp nhất canonical MembershipApplication & legacy Application, strictly user=user)."""
    denied = _check_active_user(user)
    if denied is not None:
        return denied

    from organization.models import MembershipApplication
    from recruitment.models import Application

    canon_apps = list(
        MembershipApplication.objects.filter(user=user)
        .select_related("primary_department", "secondary_department")
        .order_by("-created_at")[:3]
    )
    legacy_apps = list(
        Application.objects.filter(user=user)
        .select_related("round", "department")
        .order_by("-created_at")[:3]
    )

    if not canon_apps and not legacy_apps:
        return {
            "text": "Bạn chưa nộp đơn ứng tuyển thành viên nào trên hệ thống.",
            "links": [{"label": "Xem trang Tuyển thành viên", "url": reverse("recruitment:home")}],
        }

    lines = ["Trạng thái hồ sơ ứng tuyển của bạn:"]
    links = []
    if canon_apps:
        for app in canon_apps:
            dept = app.primary_department.name if app.primary_department else "Chưa chọn ban"
            note = f" — {app.decision_note}" if app.decision_note else ""
            lines.append(f"• Hồ sơ gia nhập KMG ({dept}): {app.get_status_display()}{note}")
        links.append({"label": "Đăng ký / Theo dõi hồ sơ CLB", "url": reverse("organization:apply_membership")})
    for app in legacy_apps:
        dept = app.department.name if app.department else "Chưa chọn ban"
        extra = ""
        if app.interview_at:
            extra = f" — Lịch phỏng vấn/casting: {timezone.localtime(app.interview_at):%H:%M %d/%m/%Y}"
        lines.append(f"• Đợt '{app.round.name}' ({dept}): {app.get_status_display()}{extra}")
    if legacy_apps or not links:
        links.append({"label": "Xem hồ sơ tuyển thành viên", "url": reverse("recruitment:home")})
    return {
        "text": "\n".join(lines),
        "links": links,
    }


def query_my_training(user) -> dict:
    """Khóa đào tạo và kỹ năng cá nhân."""
    denied = _check_active_user(user)
    if denied is not None:
        return denied

    from organization.models import UserSkill
    from programs.models import TrainingCourse, TrainingCourseStatus, TrainingEnrollment

    enrollments = list(
        TrainingEnrollment.objects.filter(user=user)
        .select_related("course")
        .order_by("-enrolled_at")[:5]
    )
    skills = list(
        UserSkill.objects.filter(user=user)
        .select_related("skill")[:6]
    )
    lines = []
    if enrollments:
        lines.append("Khóa đào tạo bạn đã đăng ký:")
        for e in enrollments:
            lines.append(f"• {e.course.title} — {e.get_status_display()}")
    else:
        open_courses = list(
            TrainingCourse.objects.filter(status=TrainingCourseStatus.OPEN).order_by("starts_at")[:4]
        )
        if open_courses:
            lines.append("Các khóa đào tạo đang mở:")
            for c in open_courses:
                lines.append(f"• {c.title} ({timezone.localtime(c.starts_at):%d/%m/%Y})")
        else:
            lines.append("Bạn chưa tham gia khóa đào tạo nào và hiện chưa có khóa mới đang mở.")

    if skills:
        lines.append("Kỹ năng đã ghi nhận: " + ", ".join(f"{s.skill.name} ({s.get_proficiency_display()})" for s in skills))

    return {
        "text": "\n".join(lines),
        "links": [{"label": "Mở Không gian Đào tạo", "url": reverse("programs:training_practice_hub")}],
    }


def query_my_evaluations(user) -> dict:
    """Kết quả đánh giá định kỳ cá nhân (strictly member=user)."""
    denied = _check_active_user(user)
    if denied is not None:
        return denied

    from evaluations.models import EvaluationStatus, MemberEvaluation

    evals = list(
        MemberEvaluation.objects.filter(
            member=user,
            status=EvaluationStatus.CONFIRMED,
        )
        .select_related("cycle", "department")
        .order_by("-created_at")[:3]
    )
    eval_links = (
        [{"label": "Xem mục Đánh giá", "url": reverse("evaluations:hub")}]
        if PermissionEngine.authorize(user, "club.event.view_internal")
        else []
    )
    if not evals:
        return {
            "text": "Hiện chưa có kỳ đánh giá định kỳ nào đã công bố cho bạn.",
            "links": eval_links,
        }

    lines = ["Kết quả đánh giá gần đây của bạn:"]
    for ev in evals:
        dept = ev.department.name if ev.department else "CLB"
        lines.append(f"• {ev.cycle.name} ({dept}): {ev.get_overall_rating_display()}")
    return {
        "text": "\n".join(lines),
        "links": (
            [{"label": "Xem chi tiết đánh giá", "url": reverse("evaluations:hub")}]
            if eval_links
            else []
        ),
    }


def query_department_ops(user) -> dict:
    """Tổng hợp tiến độ công việc Ban/CLB theo đúng phạm vi Ban hoặc toàn CLB."""
    from operations.models import ClubTask, TaskWorkflowStatus
    from organization.models import Department

    is_club_wide = PermissionEngine.authorize(user, "club.event.approve") or PermissionEngine.authorize(
        user, "club.dept.supervise_ops"
    )
    authorized_depts = []
    if not is_club_wide:
        authorized_depts = [
            d
            for d in Department.objects.filter(is_active=True).order_by("display_order", "id")
            if PermissionEngine.authorize(user, "dept.task.assign", department=d)
            or PermissionEngine.authorize(user, "dept.task.view_all", department=d)
        ]
        if not authorized_depts:
            return {
                "text": "Bạn không có quyền xem tổng hợp công việc điều phối Ban/CLB. Bạn có thể hỏi 'Việc của tôi có gì?' để xem đầu việc cá nhân.",
                "links": [],
            }

    now = timezone.now()
    active_qs = ClubTask.objects.exclude(
        workflow_status__in=(TaskWorkflowStatus.APPROVED, TaskWorkflowStatus.CANCELLED)
    )
    if not is_club_wide:
        active_qs = active_qs.filter(department__in=authorized_depts)
        scope_label = "Ban " + ", ".join(d.name for d in authorized_depts)
    else:
        scope_label = "toàn CLB"

    total_open = active_qs.count()
    overdue = active_qs.filter(deadline__lt=now).count()
    in_review = active_qs.filter(workflow_status=TaskWorkflowStatus.SUBMITTED).count()
    return {
        "text": (
            f"Tổng quan công việc vận hành ({scope_label}) hiện tại: {total_open} đầu việc đang mở "
            f"({in_review} chờ duyệt nộp, {overdue} quá hạn). "
            "Bạn vào Không gian Điều phối để xem chi tiết và phân công nhân sự."
        ),
        "links": [{"label": "Mở Không gian Công việc", "url": reverse("operations:task_list")}],
    }


def query_finance_summary(user) -> dict:
    """Tra cứu tổng hợp thu chi CLB (đồng bộ quyền với finance_hub & compute_club_fund_summary)."""
    from finance.services import can_view_club_finance, compute_club_fund_summary

    if not can_view_club_finance(user):
        return {
            "text": "Bạn không có quyền truy cập số liệu tài chính và sổ quỹ của CLB.",
            "links": [],
        }

    summary = compute_club_fund_summary()
    income = summary["confirmed_income"]
    expense = summary["confirmed_expense"]
    balance = summary["net_club_balance"]
    pending_count = summary["pending_count"]
    fmt = lambda v: f"{v:,}".replace(",", ".") + "đ"
    return {
        "text": (
            f"Tổng hợp sổ quỹ đã duyệt: Thu {fmt(income)} | Chi {fmt(expense)} | "
            f"Chênh lệch {fmt(balance)}. Hiện có {pending_count} khoản đang chờ duyệt."
        ),
        "links": [{"label": "Mở Sổ quỹ Tài chính", "url": reverse("finance:hub")}],
    }


def query_club_analytics(user) -> dict:
    """Thống kê nhân sự & vận hành CLB (chỉ dành cho BCN, Cố vấn, Admin có quyền)."""
    if not (
        PermissionEngine.authorize(user, "club.event.approve")
        or PermissionEngine.authorize(user, "club.document.manage_confidential")
        or PermissionEngine.authorize(user, "club.overview.supervise")
    ):
        return {
            "text": "Bạn không có quyền xem báo cáo thống kê tổng hợp của Ban Chủ nhiệm.",
            "links": [],
        }

    from events.models import Event, EventStatus
    from operations.models import ClubTask, TaskWorkflowStatus
    from organization.models import ClubMembership, ClubMembershipStatus

    active_members = ClubMembership.objects.filter(status=ClubMembershipStatus.ACTIVE).count()
    open_events = Event.objects.filter(status=EventStatus.OPEN).count()
    open_tasks = ClubTask.objects.exclude(
        workflow_status__in=(TaskWorkflowStatus.APPROVED, TaskWorkflowStatus.CANCELLED)
    ).count()
    ctx = PermissionEngine.summarize_actor_context(user)
    if ctx.get("can_access_club_governance"):
        target_url = reverse("organization:governance_center")
        target_label = "Mở Trung tâm Quản trị CLB"
    elif PermissionEngine.authorize(user, "club.overview.supervise"):
        target_url = reverse("organization:advisor_overview")
        target_label = "Mở Cổng Giám sát Tổng quan"
    else:
        target_url = reverse("organization:workspace_home")
        target_label = "Xem Không gian Tổ chức CLB"

    return {
        "text": (
            f"Chỉ số vận hành KMG hiện tại: {active_members} thành viên chính thức, "
            f"{open_events} sự kiện đang mở đăng ký, {open_tasks} công việc đang triển khai."
        ),
        "links": [{"label": target_label, "url": target_url}],
    }
