"""
Tầng Nghiệp vụ Phase 5: Đánh giá 7 Tiêu chí, Phản hồi (`BE-06`) & Vinh danh.

Ranh giới quyền:
- Lập nháp: `dept.evaluation.propose` (Trưởng ban, Phó ban có gói HR) trong ĐÚNG Ban; hoặc `club.evaluation.finalize`.
- Chốt: `dept.evaluation.finalize` (chỉ Trưởng ban — Phó ban bị Hard Ceiling) hoặc `club.evaluation.finalize`.
- `INV-03`: không tự đánh giá / tự chốt / tự xác nhận vinh danh cho chính mình.
- `INV-04`: Cố vấn không có bất kỳ quyền ghi nào, không xem điểm cá nhân.
- Ban A không bao giờ thấy phiếu đánh giá Ban B của thành viên đa Ban.
"""
from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from accounts.models import AuditLog, User
from notifications.models import NotificationKind
from notifications.services import notify_on_commit
from organization.models import (
    Department,
    DepartmentMembership,
    DeptMembershipStatus,
    SkillVerificationStatus,
    UserSkill,
)
from organization.permissions import PermissionEngine
from organization.services import GovernanceError
from programs.services import _is_pure_advisor

from .models import (
    EvaluationCriterion,
    EvaluationCriterionScore,
    EvaluationCycle,
    EvaluationCycleStatus,
    EvaluationResponse,
    EvaluationStatus,
    MemberEvaluation,
    MemberRecognition,
    OverallRating,
    RecognitionScope,
    RecognitionStatus,
)


# ---------------------------------------------------------------------------
# Quyền hạn
# ---------------------------------------------------------------------------
def can_draft_in_department(actor: User, department: Department) -> bool:
    if _is_pure_advisor(actor):
        return False
    return PermissionEngine.authorize(
        actor, "dept.evaluation.propose", department=department
    ) or PermissionEngine.authorize(actor, "club.evaluation.finalize")


def can_finalize_in_department(actor: User, department: Department, target_user=None) -> bool:
    if _is_pure_advisor(actor):
        return False
    return PermissionEngine.authorize(
        actor, "dept.evaluation.finalize", department=department, target_user=target_user
    ) or PermissionEngine.authorize(actor, "club.evaluation.finalize", target_user=target_user)


def can_view_evaluation(actor: User, ev: MemberEvaluation) -> bool:
    if not actor or not getattr(actor, "is_authenticated", False):
        return False
    if ev.member_id == actor.pk:
        return ev.status == EvaluationStatus.CONFIRMED
    return can_draft_in_department(actor, ev.department)


def reviewable_departments(actor: User) -> list[Department]:
    return [d for d in Department.objects.filter(is_active=True) if can_draft_in_department(actor, d)]


def visible_evaluations_qs(actor: User):
    depts = reviewable_departments(actor)
    return MemberEvaluation.objects.select_related(
        "cycle", "member", "department", "drafted_by", "finalized_by"
    ).filter(department__in=depts)


# ---------------------------------------------------------------------------
# Kỳ đánh giá & Số liệu tự động
# ---------------------------------------------------------------------------
def get_current_cycle() -> EvaluationCycle | None:
    return EvaluationCycle.objects.filter(status=EvaluationCycleStatus.OPEN).order_by("-starts_on").first()


def ensure_cycle(actor: User | None, *, code: str, name: str, starts_on, ends_on, response_deadline=None) -> EvaluationCycle:
    cycle, _ = EvaluationCycle.objects.get_or_create(
        code=code,
        defaults={
            "name": name,
            "starts_on": starts_on,
            "ends_on": ends_on,
            "response_deadline": response_deadline,
            "created_by": actor,
        },
    )
    return cycle


def create_cycle(actor: User, *, code: str, name: str, starts_on, ends_on, response_deadline=None) -> EvaluationCycle:
    PermissionEngine.require(actor, "club.evaluation.finalize")
    if not code or not name or not starts_on or not ends_on:
        raise GovernanceError("Vui lòng nhập đủ mã kỳ, tên kỳ và khoảng thời gian.")
    if ends_on < starts_on:
        raise GovernanceError("Ngày kết thúc phải sau ngày bắt đầu.")
    if EvaluationCycle.objects.filter(code=code).exists():
        raise GovernanceError(f"Mã kỳ '{code}' đã tồn tại.")
    cycle = EvaluationCycle.objects.create(
        code=code.strip()[:32],
        name=name.strip()[:160],
        starts_on=starts_on,
        ends_on=ends_on,
        response_deadline=response_deadline,
        created_by=actor,
    )
    AuditLog.write(actor, "Mở kỳ đánh giá", cycle.code, cycle.name)
    return cycle


def close_cycle(actor: User, cycle: EvaluationCycle) -> EvaluationCycle:
    PermissionEngine.require(actor, "club.evaluation.finalize")
    cycle.status = EvaluationCycleStatus.CLOSED
    cycle.save(update_fields=["status"])
    AuditLog.write(actor, "Khoá kỳ đánh giá", cycle.code, "")
    return cycle


def compute_member_dept_telemetry(member: User, department: Department, cycle: EvaluationCycle) -> dict:
    """Thu thập số liệu hoạt động Phase 2/3 của thành viên trong phạm vi ĐÚNG một Ban."""
    from operations.models import CheckinStatus, ClubTaskAssignee, EventAttendance, TaskWorkflowStatus
    from programs.models import (
        PracticeParticipant,
        PracticeResponseStatus,
        TrainingEnrollment,
        TrainingEnrollmentStatus,
    )

    start, end = cycle.starts_on, cycle.ends_on
    assigns = ClubTaskAssignee.objects.filter(user=member, task__department=department).filter(
        Q(task__deadline__isnull=True) | Q(task__deadline__date__range=(start, end))
    )
    tasks_total = assigns.count()
    tasks_approved = assigns.filter(task__workflow_status=TaskWorkflowStatus.APPROVED).count()
    now = timezone.now()
    tasks_overdue = (
        assigns.exclude(
            task__workflow_status__in=[
                TaskWorkflowStatus.APPROVED,
                TaskWorkflowStatus.REJECTED,
                TaskWorkflowStatus.CANCELLED,
            ]
        )
        .filter(task__deadline__lt=now)
        .count()
    )

    atts = EventAttendance.objects.filter(
        user=member,
        club_event__lead_department=department,
        club_event__event__starts_at__date__range=(start, end),
    )
    events_total = atts.count()
    events_present = atts.filter(checkin_status__in=[CheckinStatus.PRESENT, CheckinStatus.LATE]).count()
    events_no_show = atts.filter(checkin_status=CheckinStatus.NO_SHOW).count()

    parts = PracticeParticipant.objects.filter(
        user=member, session__department=department, session__starts_at__date__range=(start, end)
    )
    practice_total = parts.count()
    practice_attended = parts.filter(response_status=PracticeResponseStatus.ATTENDED).count()

    enrolls = TrainingEnrollment.objects.filter(user=member, course__department=department)
    training_enrolled = enrolls.exclude(status=TrainingEnrollmentStatus.DROPPED).count()
    training_completed = enrolls.filter(status=TrainingEnrollmentStatus.COMPLETED).count()

    verified_skills = UserSkill.objects.filter(
        user=member, verification_status=SkillVerificationStatus.VERIFIED
    ).count()

    return {
        "tasks_total": tasks_total,
        "tasks_approved": tasks_approved,
        "tasks_overdue": tasks_overdue,
        "events_total": events_total,
        "events_present": events_present,
        "events_no_show": events_no_show,
        "practice_total": practice_total,
        "practice_attended": practice_attended,
        "training_enrolled": training_enrolled,
        "training_completed": training_completed,
        "verified_skills": verified_skills,
        "computed_at": timezone.now().isoformat(),
    }


def _auto_evidence(criterion: str, t: dict) -> str:
    if criterion == EvaluationCriterion.TASK_COMPLETION:
        return f"{t['tasks_approved']}/{t['tasks_total']} nhiệm vụ được duyệt hoàn thành · {t['tasks_overdue']} đang quá hạn"
    if criterion == EvaluationCriterion.ATTENDANCE:
        return f"Có mặt {t['events_present']}/{t['events_total']} sự kiện Ban · {t['events_no_show']} vắng không phép"
    if criterion == EvaluationCriterion.PROFESSIONAL_SKILL:
        return f"{t['verified_skills']} kỹ năng chuyên môn đã được xác minh"
    if criterion == EvaluationCriterion.TRAINING_GROWTH:
        return (
            f"Tập luyện {t['practice_attended']}/{t['practice_total']} buổi · "
            f"hoàn thành {t['training_completed']}/{t['training_enrolled']} khoá đào tạo"
        )
    return "Nhận định định tính của cán bộ Ban"


# ---------------------------------------------------------------------------
# Lập nháp & Chốt đánh giá
# ---------------------------------------------------------------------------
def _clean_rating(value) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError) as exc:
        raise GovernanceError("Mức đánh giá tiêu chí phải là số từ 1 đến 5.") from exc
    if v < 1 or v > 5:
        raise GovernanceError("Mức đánh giá tiêu chí phải trong khoảng 1 đến 5.")
    return v


@transaction.atomic
def create_or_update_evaluation_draft(
    actor: User,
    *,
    cycle: EvaluationCycle,
    member: User,
    department: Department,
    criteria: dict | None = None,
    comments: dict | None = None,
    overall_rating: str = "",
    strengths: str = "",
    growth_areas: str = "",
    development_plan: str = "",
) -> MemberEvaluation:
    if _is_pure_advisor(actor):
        raise PermissionDenied("Cố vấn ở chế độ chỉ đọc (INV-04).")
    if member.pk == actor.pk:
        raise PermissionDenied("Không được tự lập phiếu đánh giá cho chính mình (INV-03).")
    if not can_draft_in_department(actor, department):
        raise PermissionDenied(f"Bạn không có quyền lập đánh giá trong {department.name}.")
    if not cycle.is_open:
        raise GovernanceError("Kỳ đánh giá đã khoá, không thể chỉnh sửa.")
    if not DepartmentMembership.objects.filter(
        user=member, department=department, status=DeptMembershipStatus.ACTIVE
    ).exists():
        raise GovernanceError(f"{member.public_name} không phải thành viên đang sinh hoạt tại {department.name}.")
    if overall_rating and overall_rating not in OverallRating.values:
        raise GovernanceError("Nhận định tổng quát không hợp lệ.")

    ev = (
        MemberEvaluation.objects.select_for_update()
        .filter(cycle=cycle, member=member, department=department)
        .first()
    )
    if ev is not None and ev.status != EvaluationStatus.DRAFT:
        raise GovernanceError("Phiếu đánh giá đã được chốt, không thể chỉnh sửa.")

    telemetry = compute_member_dept_telemetry(member, department, cycle)
    if ev is None:
        ev = MemberEvaluation(cycle=cycle, member=member, department=department, drafted_by=actor)
    ev.telemetry_snapshot = telemetry
    ev.overall_rating = overall_rating or ev.overall_rating
    ev.strengths = (strengths or ev.strengths or "").strip()
    ev.growth_areas = (growth_areas or ev.growth_areas or "").strip()
    ev.development_plan = (development_plan or ev.development_plan or "").strip()
    ev.drafted_by = actor
    ev.save()

    criteria = criteria or {}
    comments = comments or {}
    for code in EvaluationCriterion.values:
        score, _ = EvaluationCriterionScore.objects.get_or_create(evaluation=ev, criterion=code)
        if code in criteria and criteria[code] not in (None, ""):
            score.rating_level = _clean_rating(criteria[code])
        if code in comments:
            score.comment = (comments.get(code) or "").strip()[:500]
        score.auto_evidence = _auto_evidence(code, telemetry)[:255]
        score.save()

    AuditLog.write(actor, "Lập/cập nhật nháp đánh giá", member, f"{cycle.code} · {department.name}")
    return ev


@transaction.atomic
def finalize_evaluation(actor: User, ev: MemberEvaluation) -> MemberEvaluation:
    ev = MemberEvaluation.objects.select_for_update().select_related("cycle", "member", "department").get(pk=ev.pk)
    if _is_pure_advisor(actor):
        raise PermissionDenied("Cố vấn ở chế độ chỉ đọc (INV-04).")
    if ev.member_id == actor.pk:
        raise PermissionDenied("Không được tự chốt đánh giá của chính mình (INV-03).")
    if not can_finalize_in_department(actor, ev.department, target_user=ev.member):
        raise PermissionDenied(
            f"Chỉ Trưởng ban {ev.department.name} hoặc Ban Chủ nhiệm phụ trách nhân sự mới được chốt đánh giá."
        )
    if ev.status != EvaluationStatus.DRAFT:
        raise GovernanceError("Phiếu đánh giá này đã được chốt trước đó.")
    if not ev.cycle.is_open:
        raise GovernanceError("Kỳ đánh giá đã khoá.")
    if not ev.overall_rating:
        raise GovernanceError("Vui lòng chọn nhận định tổng quát trước khi chốt.")
    if ev.criterion_scores.count() < len(EvaluationCriterion.values):
        raise GovernanceError("Phiếu chưa có đủ 7 tiêu chí đánh giá.")

    ev.status = EvaluationStatus.CONFIRMED
    ev.finalized_by = actor
    ev.finalized_at = timezone.now()
    ev.save(update_fields=["status", "finalized_by", "finalized_at", "updated_at"])
    AuditLog.write(actor, "Chốt đánh giá thành viên", ev.member, f"{ev.cycle.code} · {ev.department.name}")
    notify_on_commit(
        ev.member,
        NotificationKind.EVALUATION,
        f"Phiếu đánh giá {ev.cycle.code} — {ev.department.name}",
        "Ban đã gửi nhận xét phát triển cá nhân cho bạn. Bạn có thể phản hồi trực tiếp trên phiếu.",
        url=reverse("evaluations:detail", kwargs={"pk": ev.pk}),
    )
    return ev


@transaction.atomic
def submit_evaluation_response(actor: User, ev: MemberEvaluation, message: str) -> EvaluationResponse:
    """`BE-06`: Phản hồi nhẹ nhàng hai chiều (không phải Khiếu nại)."""
    if _is_pure_advisor(actor):
        raise PermissionDenied("Cố vấn ở chế độ chỉ đọc (INV-04).")
    if ev.status != EvaluationStatus.CONFIRMED:
        raise GovernanceError("Chỉ phản hồi trên phiếu đánh giá đã chốt.")
    if not ev.cycle.is_open:
        raise GovernanceError("Kỳ đánh giá đã khoá — không thể gửi thêm phản hồi.")
    deadline = ev.cycle.response_deadline
    is_member = ev.member_id == actor.pk
    if is_member:
        if deadline and timezone.localdate() > deadline:
            raise GovernanceError("Đã quá hạn gửi phản hồi cho kỳ đánh giá này.")
    elif not can_draft_in_department(actor, ev.department):
        raise PermissionDenied("Bạn không có quyền phản hồi trên phiếu đánh giá này.")
    text = (message or "").strip()
    if not text:
        raise GovernanceError("Nội dung phản hồi không được để trống.")
    resp = EvaluationResponse.objects.create(
        evaluation=ev, author=actor, is_member_response=is_member, message=text[:3000]
    )
    if is_member:
        AuditLog.write(actor, "Phản hồi phiếu đánh giá", ev.department.name, ev.cycle.code)
        if ev.finalized_by_id and ev.finalized_by_id != actor.pk:
            notify_on_commit(
                ev.finalized_by,
                NotificationKind.EVALUATION,
                f"{actor.public_name} phản hồi phiếu đánh giá",
                text[:200],
                url=reverse("evaluations:detail", kwargs={"pk": ev.pk}),
            )
    else:
        notify_on_commit(
            ev.member,
            NotificationKind.EVALUATION,
            f"Cán bộ {ev.department.name} trả lời phản hồi của bạn",
            text[:200],
            url=reverse("evaluations:detail", kwargs={"pk": ev.pk}),
        )
    return resp


# ---------------------------------------------------------------------------
# Vinh danh (tách biệt khỏi điểm số)
# ---------------------------------------------------------------------------
@transaction.atomic
def nominate_recognition(
    actor: User,
    *,
    recipient: User,
    title: str,
    citation: str,
    scope: str = RecognitionScope.DEPARTMENT,
    department: Department | None = None,
    cycle: EvaluationCycle | None = None,
    is_public: bool = False,
) -> MemberRecognition:
    if _is_pure_advisor(actor):
        raise PermissionDenied("Cố vấn ở chế độ chỉ đọc (INV-04).")
    if recipient.pk == actor.pk:
        raise PermissionDenied("Không được tự đề cử vinh danh cho chính mình (INV-03).")
    if scope not in RecognitionScope.values:
        raise GovernanceError("Phạm vi vinh danh không hợp lệ.")
    if scope == RecognitionScope.DEPARTMENT:
        if department is None or not can_draft_in_department(actor, department):
            raise PermissionDenied("Bạn không có quyền đề cử vinh danh trong Ban này.")
    elif not (
        PermissionEngine.authorize(actor, "club.evaluation.finalize")
        or any(can_draft_in_department(actor, d) for d in Department.objects.filter(is_active=True))
    ):
        raise PermissionDenied("Bạn không có quyền đề cử vinh danh cấp CLB.")
    if not (title or "").strip() or not (citation or "").strip():
        raise GovernanceError("Vui lòng nhập danh hiệu và lời vinh danh.")
    rec = MemberRecognition.objects.create(
        recipient=recipient,
        scope=scope,
        department=department,
        cycle=cycle,
        title=title.strip()[:160],
        citation=citation.strip(),
        is_public=bool(is_public),
        proposed_by=actor,
    )
    AuditLog.write(actor, "Đề cử vinh danh", recipient, rec.title)
    return rec


@transaction.atomic
def verify_recognition(actor: User, rec: MemberRecognition, *, approve: bool, is_public: bool | None = None) -> MemberRecognition:
    rec = MemberRecognition.objects.select_for_update().select_related("recipient", "department").get(pk=rec.pk)
    if _is_pure_advisor(actor):
        raise PermissionDenied("Cố vấn ở chế độ chỉ đọc (INV-04).")
    if rec.recipient_id == actor.pk:
        raise PermissionDenied("Không được tự xác nhận vinh danh của chính mình (INV-03).")
    allowed = PermissionEngine.authorize(actor, "club.evaluation.finalize", target_user=rec.recipient)
    if not allowed and rec.scope == RecognitionScope.DEPARTMENT and rec.department_id:
        allowed = PermissionEngine.authorize(
            actor, "dept.evaluation.finalize", department=rec.department, target_user=rec.recipient
        )
    if not allowed:
        raise PermissionDenied("Bạn không có quyền xác nhận vinh danh này.")
    if rec.status != RecognitionStatus.PROPOSED:
        raise GovernanceError("Đề cử này đã được xử lý.")
    rec.status = RecognitionStatus.VERIFIED if approve else RecognitionStatus.REJECTED
    rec.verified_by = actor
    rec.verified_at = timezone.now()
    if is_public is not None:
        rec.is_public = bool(is_public)
    rec.save()
    AuditLog.write(actor, "Xác nhận vinh danh" if approve else "Từ chối đề cử vinh danh", rec.recipient, rec.title)
    if approve:
        notify_on_commit(
            rec.recipient,
            NotificationKind.RECOGNITION,
            f"Chúc mừng! Bạn được vinh danh: {rec.title}",
            rec.citation[:200],
            url=reverse("evaluations:hub"),
        )
    return rec


def public_recognitions(limit: int = 6):
    return list(
        MemberRecognition.objects.select_related("recipient", "department")
        .filter(status=RecognitionStatus.VERIFIED, is_public=True)
        .order_by("-verified_at")[:limit]
    )
