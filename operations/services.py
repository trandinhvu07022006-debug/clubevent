"""
Tầng Nghiệp vụ Vận hành Cốt lõi CLB KMG (Phase 2 — Core Management).

Mọi hàm nghiệp vụ bắt buộc tuân thủ:
1. Kiểm tra `PermissionEngine` tại Backend (RBAC + DBAC + ABAC + Delegation).
2. Thực thi phân tách nhiệm vụ:
   - Cấm tự nghiệm thu nhiệm vụ bản thân được giao (`PA-04` / `INV-03`).
   - Cấm người ra quyết định ban đầu tự bác bỏ/phán quyết đơn khiếu nại về quyết định đó (`WF24`).
   - Cố vấn ở chế độ Hard Read-Only (`INV-04`), xem Audit Log đã tự động che PII (`PA-07`).
3. Tự động gắn cờ `reassignment_needed` cho công việc đang dở dang khi thành viên chuyển Ban,
   bị tạm khoá hoặc rời CLB (`BE-02`).
4. Vượt ngưỡng `> 3` lần vi phạm chỉ tạo `DisciplineCase(status=FLAGGED)` để BCN xem xét,
   TUYỆT ĐỐI KHÔNG tự khoá tài khoản hay tự tạm khoá thành viên (`R04`).
"""
from __future__ import annotations

from datetime import timedelta
import re

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import URLValidator
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import AccountStatus, AuditLog, User
from events.models import Event, EventCategory, EventStatus, EventVisibility
from notifications.models import (
    NotificationKind,
    ReminderStage,
    ReminderTargetType,
)
from notifications.services import (
    dispatch_idempotent_reminder,
    notify_many,
    send_operational_alert,
)
from organization.models import (
    Appointment,
    ClubMembership,
    ClubMembershipStatus,
    Department,
    DepartmentMembership,
    DeptMembershipStatus,
    LifecycleEventType,
    MemberLifecycleEvent,
    PolicyVersion,
    PositionCode,
    Skill,
    SkillVerificationStatus,
    UserSkill,
)
from organization.permissions import PermissionEngine
from organization.services import GovernanceError, restore_club_member, suspend_club_member

from .models import (
    Appeal,
    AppealStatus,
    AppealTargetType,
    AssigneeRole,
    CheckinStatus,
    ClubAnnouncement,
    ClubEventApprovalStatus,
    ClubEventProfile,
    ClubEventScope,
    ClubTask,
    ClubTaskAssignee,
    DisciplineCase,
    DisciplineStatus,
    DisciplineTriggerType,
    EventAttendance,
    EventAttendanceHistory,
    EventDepartmentRole,
    EventDeptRoleType,
    ExtensionStatus,
    RsvpStatus,
    TaskExtensionRequest,
    TaskPriority,
    TaskReview,
    TaskReviewDecision,
    TaskSubmission,
    TaskSubmissionMode,
    TaskWorkflowStatus,
)

_EMAIL_RE = re.compile(r"\b([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
_PHONE_RE = re.compile(r"(?<!\d)(\+?84|0)(\d{2})\d{4,6}(\d{2})(?!\d)")
_HTTP_URL_VALIDATOR = URLValidator(schemes=["http", "https"])


def clean_evidence_url(raw: str) -> str:
    """Chỉ chấp nhận liên kết minh chứng `http(s)://` (chặn `javascript:` / `data:` khi render vào `href`)."""
    value = (raw or "").strip()
    if not value:
        return ""
    try:
        _HTTP_URL_VALIDATOR(value)
    except ValidationError as exc:
        raise GovernanceError("Liên kết minh chứng phải là địa chỉ http(s) hợp lệ.") from exc
    return value[:200]


def redact_pii_for_advisor(text: str) -> str:
    """
    `PA-07` & Data Privacy Rule 10: Tự động che Email & SĐT cá nhân trong nhật ký hệ thống
    khi hiển thị ở Cổng Giám sát Cố vấn (`ADVISOR`).
    """
    if not text:
        return ""
    masked = _EMAIL_RE.sub(r"\1***@\2", str(text))
    masked = _PHONE_RE.sub(r"\1\2*****\3", masked)
    return masked


def _get_executive_reviewers() -> list[User]:
    """Lấy danh sách Chủ nhiệm và Phó CN phụ trách Nhân sự đang đương nhiệm để nhận cảnh báo."""
    now = timezone.now()
    appts = (
        Appointment.objects.select_related("user", "position")
        .filter(
            position__code__in=[PositionCode.CHAIRMAN, PositionCode.VICE_CHAIRMAN],
            is_active=True,
            ended_at__isnull=True,
        )
        .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=now))
    )
    users = []
    seen = set()
    for a in appts:
        if a.user_id not in seen and PermissionEngine.authorize(
            a.user, "club.member.suspend_temporary"
        ):
            seen.add(a.user_id)
            users.append(a.user)
    return users


# ---------------------------------------------------------------------------
# 1. GỢI Ý NHÂN SỰ THEO KỸ NĂNG & QUẢN LÝ CÔNG VIỆC 10 BƯỚC (`WF13–WF15`)
# ---------------------------------------------------------------------------
def recommend_assignees_for_task(
    department: Department,
    skill: Skill | None = None,
) -> list[dict]:
    """
    Gợi ý thành viên phù hợp trong Ban dựa trên `UserSkill` đã xác minh và tải công việc hiện tại.
    BẤT BIẾN `INV-01`: Chỉ phục vụ lọc & đề xuất giao việc, không cấp bất kỳ quyền truy cập nào!
    """
    memberships = list(
        DepartmentMembership.objects.select_related("user", "user__club_membership")
        .filter(
            department=department,
            status=DeptMembershipStatus.ACTIVE,
            user__is_locked=False,
            user__club_membership__status=ClubMembershipStatus.ACTIVE,
        )
    )
    user_ids = [m.user_id for m in memberships]
    verified_skill_map: dict[int, UserSkill] = {}
    if skill is not None and user_ids:
        for us in UserSkill.objects.filter(
            user_id__in=user_ids,
            skill=skill,
            verification_status=SkillVerificationStatus.VERIFIED,
        ):
            verified_skill_map[us.user_id] = us

    open_assignments = list(
        ClubTaskAssignee.objects.select_related("task")
        .filter(
            user_id__in=user_ids,
            is_active=True,
        )
        .exclude(
            task__workflow_status__in=[
                TaskWorkflowStatus.APPROVED,
                TaskWorkflowStatus.REJECTED,
                TaskWorkflowStatus.CANCELLED,
            ]
        )
    )
    active_counts: dict[int, int] = {uid: 0 for uid in user_ids}
    overdue_counts: dict[int, int] = {uid: 0 for uid in user_ids}
    now = timezone.now()
    for a in open_assignments:
        active_counts[a.user_id] = active_counts.get(a.user_id, 0) + 1
        if a.task.deadline < now:
            overdue_counts[a.user_id] = overdue_counts.get(a.user_id, 0) + 1

    candidates = []
    for dm in memberships:
        u = dm.user
        us = verified_skill_map.get(u.id)
        candidates.append(
            {
                "user": u,
                "has_verified_skill": us is not None,
                "proficiency_label": us.get_proficiency_display() if us else "",
                "active_task_count": active_counts.get(u.id, 0),
                "overdue_task_count": overdue_counts.get(u.id, 0),
            }
        )

    candidates.sort(
        key=lambda item: (
            not item["has_verified_skill"],
            item["overdue_task_count"],
            item["active_task_count"],
            item["user"].public_name,
        )
    )
    return candidates


def can_view_club_task(actor: User, task: ClubTask) -> bool:
    """
    Kiểm tra quyền xem chi tiết một nhiệm vụ cá nhân/nhóm trong Ban:
    - Cố vấn (`ADVISOR`) chỉ xem tiến độ tổng hợp của Ban, KHÔNG xem nhiệm vụ cá nhân (`D04` dòng 2).
    - Cán bộ/Thành viên Ban khác ghé sang ở chế độ `READ_ONLY` KHÔNG xem được nhiệm vụ nội bộ Ban.
    """
    if not actor or not getattr(actor, "is_authenticated", False):
        return False
    if PermissionEngine.authorize(actor, "dept.task.view_all", department=task.department):
        return True
    if PermissionEngine.authorize(actor, "club.dept.supervise_ops"):
        return True
    if (
        actor.id in task.assignee_user_ids
        and PermissionEngine.authorize(
            actor, "dept.task.view_personal_self", department=task.department
        )
    ):
        return True
    # Thành viên từ Ban phối hợp được giao nhiệm vụ trong sự kiện liên Ban
    if (
        task.event_id
        and actor.id in task.assignee_user_ids
        and getattr(actor, "club_status", "") == ClubMembershipStatus.ACTIVE
    ):
        return True
    return False


def can_access_task_submission_file(actor: User, submission: TaskSubmission) -> bool:
    """`SEC-01`: Kiểm tra phân quyền Backend trước khi mở tệp bài nộp từ `PrivateVaultStorage`."""
    if not actor or not getattr(actor, "is_authenticated", False):
        return False
    task = submission.task
    if PermissionEngine.authorize(actor, "dept.task.view_all", department=task.department):
        return True
    if PermissionEngine.authorize(actor, "dept.task.approve", department=task.department):
        return True
    if PermissionEngine.authorize(actor, "club.dept.supervise_ops"):
        return True
    if submission.submitted_by_id == actor.id and can_view_club_task(actor, task):
        return True
    if actor.id in task.assignee_user_ids and can_view_club_task(actor, task):
        return True
    return False


def _validate_assignee_eligible_for_task(
    user: User,
    department: Department,
    event: Event | None = None,
) -> None:
    cm = user.club_membership_record
    if not cm or cm.status != ClubMembershipStatus.ACTIVE:
        raise GovernanceError(
            f"Chỉ có thể giao nhiệm vụ cho thành viên CLB đang ACTIVE ({user.public_name} không đủ điều kiện)."
        )
    in_dept = DepartmentMembership.objects.filter(
        user=user,
        department=department,
        status=DeptMembershipStatus.ACTIVE,
    ).exists()
    if in_dept:
        return
    if event is not None and hasattr(event, "club_profile"):
        participating_dept_ids = set(
            event.club_profile.department_roles.values_list("department_id", flat=True)
        ) | {event.club_profile.lead_department_id}
        user_dept_ids = PermissionEngine.get_active_department_ids(user)
        if user_dept_ids & participating_dept_ids:
            return
    raise GovernanceError(
        f"{user.public_name} hiện không phải thành viên đang sinh hoạt tại {department.name}."
    )


@transaction.atomic
def create_and_assign_task(
    *,
    actor: User,
    department: Department,
    title: str,
    deadline,
    assignees: list[User],
    description: str = "",
    priority: str = TaskPriority.MEDIUM,
    submission_mode: str = TaskSubmissionMode.ANY_ONE,
    recommended_skill: Skill | None = None,
    event: Event | None = None,
    category_tag: str = "",
    lead_user: User | None = None,
) -> ClubTask:
    """Tạo và phân công nhiệm vụ cá nhân hoặc theo nhóm (`WF13`)."""
    if not (
        PermissionEngine.authorize(actor, "dept.task.assign", department=department)
        or PermissionEngine.authorize(actor, "club.dept.supervise_ops")
    ):
        PermissionEngine.require(actor, "dept.task.assign", department=department)

    clean_title = (title or "").strip()
    if not clean_title:
        raise GovernanceError("Tiêu đề nhiệm vụ không được để trống.")
    if not assignees:
        raise GovernanceError("Phải chọn ít nhất 01 thành viên nhận nhiệm vụ.")
    if deadline <= timezone.now():
        raise GovernanceError("Thời hạn hoàn thành (deadline) phải nằm ở tương lai.")

    unique_assignees: list[User] = []
    seen_ids = set()
    for u in assignees:
        if u.id not in seen_ids:
            _validate_assignee_eligible_for_task(u, department, event=event)
            seen_ids.add(u.id)
            unique_assignees.append(u)

    task = ClubTask.objects.create(
        title=clean_title[:200],
        description=(description or "").strip(),
        department=department,
        event=event,
        recommended_skill=recommended_skill,
        category_tag=(category_tag or "").strip()[:60],
        priority=priority if priority in TaskPriority.values else TaskPriority.MEDIUM,
        workflow_status=TaskWorkflowStatus.ASSIGNED,
        submission_mode=(
            submission_mode
            if submission_mode in TaskSubmissionMode.values
            else TaskSubmissionMode.ANY_ONE
        ),
        deadline=deadline,
        created_by=actor,
    )

    effective_lead_id = lead_user.id if (lead_user and lead_user.id in seen_ids) else unique_assignees[0].id
    for u in unique_assignees:
        ClubTaskAssignee.objects.create(
            task=task,
            user=u,
            role=AssigneeRole.LEAD if u.id == effective_lead_id else AssigneeRole.COLLABORATOR,
            personal_status=TaskWorkflowStatus.ASSIGNED,
            assigned_by=actor,
        )
        dispatch_idempotent_reminder(
            target_type=ReminderTargetType.CLUB_TASK,
            target_id=task.id,
            recipient=u,
            stage=ReminderStage.ASSIGNED,
            kind=NotificationKind.TASK_ASSIGNED,
            title=f"Nhiệm vụ mới tại {department.name}",
            message=f"{task.title} (Hạn: {timezone.localtime(task.deadline):%H:%M %d/%m/%Y})",
            url=f"/workspace/cong-viec/{task.id}/",
            email_category="task_deadline",
        )

    AuditLog.write(
        actor,
        "Giao nhiệm vụ CLB",
        f"{task.title} ({department.name})",
        note=", ".join(u.public_name for u in unique_assignees),
    )
    return task


@transaction.atomic
def reassign_club_task(
    *,
    actor: User,
    task: ClubTask,
    new_assignees: list[User],
    note: str = "",
) -> ClubTask:
    """Phân công lại nhân sự cho nhiệm vụ đang dở dang (`BE-02`)."""
    if not (
        PermissionEngine.authorize(actor, "dept.task.assign", department=task.department)
        or PermissionEngine.authorize(actor, "club.dept.supervise_ops")
    ):
        PermissionEngine.require(actor, "dept.task.assign", department=task.department)

    if task.is_finalized:
        raise GovernanceError("Không thể phân công lại nhiệm vụ đã kết thúc.")
    if not new_assignees:
        raise GovernanceError("Phải chọn ít nhất 01 thành viên tiếp nhận nhiệm vụ.")

    unique_users: list[User] = []
    seen = set()
    for u in new_assignees:
        if u.id not in seen:
            _validate_assignee_eligible_for_task(u, task.department, event=task.event)
            seen.add(u.id)
            unique_users.append(u)

    task.assignees.exclude(user_id__in=seen).update(is_active=False)
    for idx, u in enumerate(unique_users):
        assignee_row, created = ClubTaskAssignee.objects.get_or_create(
            task=task,
            user=u,
            defaults={
                "role": AssigneeRole.LEAD if idx == 0 else AssigneeRole.COLLABORATOR,
                "personal_status": TaskWorkflowStatus.ASSIGNED,
                "assigned_by": actor,
                "is_active": True,
            },
        )
        if not created and not assignee_row.is_active:
            assignee_row.is_active = True
            assignee_row.personal_status = TaskWorkflowStatus.ASSIGNED
            assignee_row.assigned_by = actor
            assignee_row.save(update_fields=["is_active", "personal_status", "assigned_by"])
        if created:
            send_operational_alert(
                user=u,
                kind=NotificationKind.TASK_ASSIGNED,
                title=f"Được phân công tiếp nhận: {task.title}",
                message=f"Ban: {task.department.name}. {note}".strip(),
                url=f"/workspace/cong-viec/{task.id}/",
                email_category="task_deadline",
            )

    task.reassignment_needed = False
    task.reassignment_reason = ""
    if task.workflow_status == TaskWorkflowStatus.DRAFT:
        task.workflow_status = TaskWorkflowStatus.ASSIGNED
    task.save(
        update_fields=[
            "reassignment_needed",
            "reassignment_reason",
            "workflow_status",
            "updated_at",
        ]
    )
    AuditLog.write(
        actor,
        "Phân công lại nhiệm vụ",
        task.title,
        note=", ".join(u.public_name for u in unique_users),
    )
    return task


@transaction.atomic
def update_task_progress(
    *,
    actor: User,
    task: ClubTask,
    new_status: str,
    progress_percent: int | None = None,
) -> ClubTask:
    """Thành viên tiếp nhận (`ACCEPTED`) hoặc cập nhật tiến độ thực hiện (`IN_PROGRESS`)."""
    if not can_view_club_task(actor, task) or actor.id not in task.assignee_user_ids:
        raise PermissionDenied("Chỉ thành viên đang được giao nhiệm vụ này mới có thể cập nhật tiến độ.")
    if task.is_finalized:
        raise GovernanceError("Nhiệm vụ này đã đóng, không thể cập nhật tiến độ.")
    if new_status not in (TaskWorkflowStatus.ACCEPTED, TaskWorkflowStatus.IN_PROGRESS):
        raise GovernanceError("Trạng thái cập nhật tiến độ không hợp lệ.")

    assignee = ClubTaskAssignee.objects.select_for_update().get(
        task=task, user=actor, is_active=True
    )
    now = timezone.now()
    if assignee.accepted_at is None:
        assignee.accepted_at = now
    assignee.personal_status = new_status
    if progress_percent is not None:
        assignee.progress_percent = max(0, min(100, int(progress_percent)))
    elif new_status == TaskWorkflowStatus.ACCEPTED and assignee.progress_percent == 0:
        assignee.progress_percent = 10
    elif new_status == TaskWorkflowStatus.IN_PROGRESS and assignee.progress_percent < 25:
        assignee.progress_percent = 50
    assignee.save(update_fields=["accepted_at", "personal_status", "progress_percent"])

    active_rows = list(task.assignees.filter(is_active=True))
    avg_progress = (
        round(sum(r.progress_percent for r in active_rows) / len(active_rows))
        if active_rows
        else 0
    )
    if task.workflow_status in (
        TaskWorkflowStatus.ASSIGNED,
        TaskWorkflowStatus.ACCEPTED,
        TaskWorkflowStatus.IN_PROGRESS,
        TaskWorkflowStatus.REVISION_REQUESTED,
    ):
        task.workflow_status = new_status
    task.progress_percent = min(95, avg_progress)
    task.save(update_fields=["workflow_status", "progress_percent", "updated_at"])
    return task


@transaction.atomic
def submit_task_deliverable(
    *,
    actor: User,
    task: ClubTask,
    submission_note: str,
    evidence_url: str = "",
    attachment=None,
) -> TaskSubmission:
    """
    Thành viên nộp kết quả công việc (`WF14`, `CM-01`, `CM-02`, `SEC-01`).
    - Cho phép nộp cả khi nhiệm vụ đã trễ hạn (`CM-01`), tự động đánh dấu `is_late=True`.
    - Tệp đính kèm tự động lưu vào `PrivateVaultStorage` (`SEC-01`).
    """
    if not can_view_club_task(actor, task) or actor.id not in task.assignee_user_ids:
        raise PermissionDenied("Chỉ người được giao nhiệm vụ này mới có quyền nộp kết quả.")
    if task.is_finalized:
        raise GovernanceError("Nhiệm vụ đã kết thúc, không thể nộp thêm bài.")
    clean_note = (submission_note or "").strip()
    if not clean_note:
        raise GovernanceError("Vui lòng nhập báo cáo / mô tả kết quả thực hiện.")

    is_late = task.is_overdue
    safe_url = clean_evidence_url(evidence_url)
    safe_attachment = None
    if attachment is not None:
        from programs.services import validate_and_prepare_vault_file
        safe_attachment = validate_and_prepare_vault_file(attachment)["content_file"]
    submission = TaskSubmission.objects.create(
        task=task,
        submitted_by=actor,
        submission_note=clean_note,
        evidence_url=safe_url,
        attachment=safe_attachment,
        is_late=is_late,
    )

    assignee = ClubTaskAssignee.objects.select_for_update().get(
        task=task, user=actor, is_active=True
    )
    if assignee.accepted_at is None:
        assignee.accepted_at = timezone.now()
    assignee.personal_status = TaskWorkflowStatus.SUBMITTED
    assignee.progress_percent = 100
    assignee.save(update_fields=["accepted_at", "personal_status", "progress_percent"])

    active_rows = list(task.assignees.filter(is_active=True))
    all_submitted = all(
        r.personal_status == TaskWorkflowStatus.SUBMITTED for r in active_rows
    )
    if task.submission_mode == TaskSubmissionMode.ANY_ONE or all_submitted:
        task.workflow_status = TaskWorkflowStatus.SUBMITTED
        task.progress_percent = 100
    else:
        task.workflow_status = TaskWorkflowStatus.IN_PROGRESS
        task.progress_percent = round(
            sum(r.progress_percent for r in active_rows) / max(len(active_rows), 1)
        )
    task.save(update_fields=["workflow_status", "progress_percent", "updated_at"])

    if task.created_by_id and task.created_by_id != actor.id:
        send_operational_alert(
            user=task.created_by,
            kind=NotificationKind.TASK_REVIEWED,
            title=f"Bài nộp mới chờ nghiệm thu: {task.title}",
            message=f"{actor.public_name} vừa nộp kết quả nhiệm vụ tại {task.department.name}.",
            url=f"/workspace/cong-viec/{task.id}/",
        )
    AuditLog.write(actor, "Nộp kết quả nhiệm vụ", task.title, note="Trễ hạn" if is_late else "Đúng hạn")
    return submission


@transaction.atomic
def request_task_extension(
    *,
    actor: User,
    task: ClubTask,
    requested_deadline,
    reason: str,
) -> TaskExtensionRequest:
    """Thành viên xin gia hạn deadline nhiệm vụ trước khi chốt nghiệm thu."""
    if not can_view_club_task(actor, task) or actor.id not in task.assignee_user_ids:
        raise PermissionDenied("Chỉ người được giao nhiệm vụ mới được gửi yêu cầu gia hạn.")
    if task.is_finalized:
        raise GovernanceError("Nhiệm vụ đã đóng, không thể xin gia hạn.")
    if requested_deadline <= task.deadline:
        raise GovernanceError("Thời hạn gia hạn mới phải sau deadline hiện tại.")
    if not (reason or "").strip():
        raise GovernanceError("Bắt buộc nêu rõ lý do xin gia hạn.")

    return TaskExtensionRequest.objects.create(
        task=task,
        requested_by=actor,
        requested_deadline=requested_deadline,
        reason=reason.strip()[:255],
    )


@transaction.atomic
def review_task_extension(
    *,
    actor: User,
    extension_request: TaskExtensionRequest,
    approved: bool,
    review_note: str = "",
) -> TaskExtensionRequest:
    """Cán bộ có thẩm quyền duyệt hoặc từ chối yêu cầu gia hạn (chặn tự duyệt `PA-04`)."""
    task = extension_request.task
    if not (
        PermissionEngine.authorize(actor, "dept.task.approve", department=task.department)
        or PermissionEngine.authorize(actor, "club.dept.supervise_ops")
    ):
        PermissionEngine.require(actor, "dept.task.approve", department=task.department)

    if actor.id == extension_request.requested_by_id or actor.id in task.assignee_user_ids:
        raise PermissionDenied(
            "Vi phạm nguyên tắc phân tách nhiệm vụ (PA-04 / INV-03): Không được tự duyệt gia hạn cho nhiệm vụ của chính mình."
        )
    if extension_request.status != ExtensionStatus.PENDING:
        raise GovernanceError("Yêu cầu gia hạn này đã được xử lý trước đó.")

    extension_request.status = ExtensionStatus.APPROVED if approved else ExtensionStatus.REJECTED
    extension_request.reviewed_by = actor
    extension_request.reviewed_at = timezone.now()
    extension_request.review_note = (review_note or "").strip()[:255]
    extension_request.save(
        update_fields=["status", "reviewed_by", "reviewed_at", "review_note"]
    )
    if approved:
        task.deadline = extension_request.requested_deadline
        task.save(update_fields=["deadline", "updated_at"])
    return extension_request


@transaction.atomic
def finalize_task_review(
    *,
    actor: User,
    task: ClubTask,
    decision: str,
    quality_score: int = 5,
    feedback: str = "",
    submission: TaskSubmission | None = None,
) -> TaskReview:
    """
    Nghiệm thu & chốt kết quả nhiệm vụ vào sổ cái bất biến `TaskReview` (`WF15`, `PA-04`, `INV-03`).

    CHẶN CỨNG `PA-04`: Nếu `actor` nằm trong danh sách người thực hiện nhiệm vụ (`task.assignee_user_ids`)
    hoặc là người nộp bài, Backend từ chối `403 PermissionDenied` ngay lập tức (kể cả Trưởng ban / Chủ nhiệm)!
    """
    if not (
        PermissionEngine.authorize(actor, "dept.task.approve", department=task.department)
        or PermissionEngine.authorize(actor, "club.dept.supervise_ops")
    ):
        PermissionEngine.require(actor, "dept.task.approve", department=task.department)

    if actor.id in task.assignee_user_ids or (
        submission is not None and submission.submitted_by_id == actor.id
    ):
        raise PermissionDenied(
            "Vi phạm nguyên tắc phân tách nhiệm vụ (PA-04 / INV-03): Người được giao việc không được tự nghiệm thu nhiệm vụ của chính mình."
        )

    if decision not in TaskReviewDecision.values:
        raise GovernanceError("Quyết định nghiệm thu không hợp lệ.")
    if task.is_finalized:
        raise GovernanceError("Nhiệm vụ này đã được chốt kết quả trước đó.")

    clean_feedback = (feedback or "").strip()
    if not clean_feedback:
        raise GovernanceError("Cán bộ nghiệm thu cần ghi nhận xét minh bạch cho thành viên.")

    latest_sub = submission or task.submissions.order_by("-submitted_at", "-id").first()
    if decision in (TaskReviewDecision.APPROVED, TaskReviewDecision.REVISION_REQUESTED):
        if latest_sub is None and task.workflow_status not in (
            TaskWorkflowStatus.SUBMITTED,
            TaskWorkflowStatus.UNDER_REVIEW,
        ):
            raise GovernanceError(
                "Chỉ có thể duyệt hoàn thành hoặc yêu cầu sửa khi thành viên đã nộp kết quả."
            )
    elif decision == TaskReviewDecision.REJECTED:
        if (
            latest_sub is None
            and not task.is_overdue
            and task.workflow_status
            not in (TaskWorkflowStatus.SUBMITTED, TaskWorkflowStatus.UNDER_REVIEW)
        ):
            raise GovernanceError(
                "Chỉ có thể đánh giá Không đạt khi bài nộp không đạt yêu cầu hoặc nhiệm vụ đã quá hạn không nộp."
            )

    score = max(1, min(5, int(quality_score)))
    review = TaskReview.objects.create(
        task=task,
        submission=latest_sub,
        reviewer=actor,
        decision=decision,
        quality_score=score,
        feedback=clean_feedback,
    )

    now = timezone.now()
    if decision == TaskReviewDecision.APPROVED:
        task.workflow_status = TaskWorkflowStatus.APPROVED
        task.progress_percent = 100
        task.completed_at = now
        task.assignees.filter(is_active=True).update(
            personal_status=TaskWorkflowStatus.APPROVED,
            progress_percent=100,
        )
    elif decision == TaskReviewDecision.REVISION_REQUESTED:
        task.workflow_status = TaskWorkflowStatus.REVISION_REQUESTED
        task.assignees.filter(is_active=True).update(
            personal_status=TaskWorkflowStatus.REVISION_REQUESTED
        )
    else:
        task.workflow_status = TaskWorkflowStatus.REJECTED
        task.completed_at = now
        task.assignees.filter(is_active=True).update(
            personal_status=TaskWorkflowStatus.REJECTED
        )

    task.save(
        update_fields=["workflow_status", "progress_percent", "completed_at", "updated_at"]
    )

    active_assignee_users = [
        a.user for a in task.assignees.select_related("user").filter(is_active=True)
    ]
    for u in active_assignee_users:
        send_operational_alert(
            user=u,
            kind=NotificationKind.TASK_REVIEWED,
            title=f"Kết quả nghiệm thu: {review.get_decision_display()}",
            message=f"{task.title} — Điểm chất lượng: {score}/5. Nhận xét: {clean_feedback[:120]}",
            url=f"/workspace/cong-viec/{task.id}/",
            email_category="important" if decision == TaskReviewDecision.REJECTED else None,
        )
        if decision == TaskReviewDecision.REJECTED and task.event_id is not None:
            evaluate_member_discipline_thresholds(u)

    AuditLog.write(
        actor,
        "Nghiệm thu nhiệm vụ CLB",
        f"{task.title} -> {review.get_decision_display()}",
        note=f"Điểm {score}/5",
    )
    return review


@transaction.atomic
def flag_tasks_needing_reassignment(
    target_user: User,
    department: Department | None = None,
    reason: str = "",
) -> int:
    """
    `BE-02`: Tự động gắn cờ `reassignment_needed=True` cho các nhiệm vụ chưa hoàn thành
    khi nhân sự chuyển Ban, bị tạm khoá (`SUSPENDED`) hoặc rời CLB.
    """
    qs = ClubTaskAssignee.objects.select_related("task", "task__department", "task__created_by").filter(
        user=target_user,
        is_active=True,
    ).exclude(
        task__workflow_status__in=[
            TaskWorkflowStatus.APPROVED,
            TaskWorkflowStatus.REJECTED,
            TaskWorkflowStatus.CANCELLED,
        ]
    )
    if department is not None:
        qs = qs.filter(task__department=department)

    affected_tasks: dict[int, ClubTask] = {}
    for row in list(qs):
        row.is_active = False
        row.save(update_fields=["is_active"])
        affected_tasks[row.task_id] = row.task

    flagged_count = 0
    for task in affected_tasks.values():
        remaining_leads = task.assignees.filter(
            is_active=True, role=AssigneeRole.LEAD
        ).exists()
        remaining_any = task.assignees.filter(is_active=True).exists()
        if not remaining_any or not remaining_leads:
            task.reassignment_needed = True
            task.reassignment_reason = (
                reason or f"{target_user.public_name} không còn phụ trách tại {task.department.name}"
            )[:255]
            task.save(update_fields=["reassignment_needed", "reassignment_reason", "updated_at"])
            flagged_count += 1
            if task.created_by_id and task.created_by_id != target_user.id:
                send_operational_alert(
                    user=task.created_by,
                    kind=NotificationKind.TASK_DEADLINE,
                    title=f"Cần phân công lại: {task.title}",
                    message=task.reassignment_reason,
                    url=f"/workspace/cong-viec/{task.id}/",
                )
    return flagged_count


# ---------------------------------------------------------------------------
# 2. QUẢN LÝ SỰ KIỆN KÉP, PHỐI HỢP LIÊN BAN & ĐIỂM DANH RSVP (`WF09–WF12`)
# ---------------------------------------------------------------------------
@transaction.atomic
def create_club_event(
    *,
    actor: User,
    lead_department: Department,
    name: str,
    location: str,
    starts_at,
    ends_at=None,
    register_deadline=None,
    rsvp_freeze_at=None,
    event_scope: str = ClubEventScope.DEPT_INTERNAL,
    category: str = EventCategory.MUSIC,
    capacity: int = 100,
    budget: int = 0,
    description: str = "",
    proposal_note: str = "",
    require_club_rsvp: bool | None = None,
    default_opt_out_rsvp: bool = True,
    supporting_departments: list[tuple[Department, str, str]] | None = None,
) -> ClubEventProfile:
    """
    Khởi tạo sự kiện nội bộ Ban / đề xuất sự kiện toàn CLB / đề xuất Show công khai (`WF09`, `INT-01`, `CF-05`).
    - Luôn tạo `events.Event` ở `visibility=INTERNAL` và `status=DRAFT` trước khi được duyệt & ban hành
      để đề xuất chưa duyệt không bao giờ rò rỉ ra trang chủ công khai (`INT-01`).
    """
    if not (
        PermissionEngine.authorize(
            actor, "dept.event.manage_internal", department=lead_department
        )
        or PermissionEngine.authorize(actor, "club.event.approve")
    ):
        PermissionEngine.require(
            actor, "dept.event.manage_internal", department=lead_department
        )

    clean_name = (name or "").strip()
    clean_location = (location or "").strip()
    if not clean_name or not clean_location:
        raise GovernanceError("Tên sự kiện và địa điểm không được để trống.")
    if event_scope not in ClubEventScope.values:
        raise GovernanceError("Phạm vi sự kiện không hợp lệ.")

    reg_deadline = register_deadline or (starts_at - timedelta(hours=12))
    freeze_at = rsvp_freeze_at or reg_deadline
    need_rsvp = (
        bool(require_club_rsvp)
        if require_club_rsvp is not None
        else (event_scope == ClubEventScope.CLUB_WIDE)
    )

    base_event = Event.objects.create(
        name=clean_name[:200],
        description=(description or "").strip(),
        location=clean_location[:200],
        category=category if category in EventCategory.values else EventCategory.MUSIC,
        starts_at=starts_at,
        ends_at=ends_at,
        register_deadline=reg_deadline,
        capacity=max(1, int(capacity)),
        budget=max(0, int(budget)),
        status=EventStatus.DRAFT,
        visibility=EventVisibility.INTERNAL,
        created_by=actor,
    )

    profile = ClubEventProfile.objects.create(
        event=base_event,
        event_scope=event_scope,
        approval_status=ClubEventApprovalStatus.DRAFT,
        lead_department=lead_department,
        require_club_rsvp=need_rsvp,
        default_opt_out_rsvp=default_opt_out_rsvp,
        rsvp_freeze_at=freeze_at if need_rsvp else None,
        proposal_note=(proposal_note or "").strip(),
        proposed_by=actor,
    )

    EventDepartmentRole.objects.create(
        club_event=profile,
        department=lead_department,
        role_type=EventDeptRoleType.LEAD,
        responsibility_note="Ban Chủ trì kế hoạch & điều phối tổng thể",
    )
    for supp_dept, role_type, resp_note in supporting_departments or []:
        if supp_dept.id == lead_department.id:
            continue
        EventDepartmentRole.objects.update_or_create(
            club_event=profile,
            department=supp_dept,
            defaults={
                "role_type": (
                    role_type
                    if role_type in EventDeptRoleType.values
                    and role_type != EventDeptRoleType.LEAD
                    else EventDeptRoleType.SUPPORT
                ),
                "responsibility_note": (resp_note or "")[:255],
            },
        )

    AuditLog.write(
        actor,
        "Khởi tạo kế hoạch sự kiện CLB",
        f"{base_event.name} ({profile.get_event_scope_display()})",
        note=lead_department.name,
    )
    return profile


@transaction.atomic
def submit_club_event_for_approval(
    actor: User,
    club_event: ClubEventProfile,
) -> ClubEventProfile:
    """Trưởng ban / Phó ban được ủy quyền trình đề xuất sự kiện lên cấp phê duyệt (`WF09`)."""
    if not (
        PermissionEngine.authorize(
            actor, "dept.event.manage_internal", department=club_event.lead_department
        )
        or PermissionEngine.authorize(actor, "club.event.approve")
    ):
        PermissionEngine.require(
            actor, "dept.event.manage_internal", department=club_event.lead_department
        )
    if club_event.approval_status not in (
        ClubEventApprovalStatus.DRAFT,
        ClubEventApprovalStatus.REJECTED,
    ):
        raise GovernanceError("Chỉ có thể gửi duyệt sự kiện đang ở trạng thái Nháp hoặc Từ chối.")

    club_event.approval_status = ClubEventApprovalStatus.SUBMITTED
    club_event.proposed_by = actor
    club_event.save(update_fields=["approval_status", "proposed_by", "updated_at"])
    AuditLog.write(actor, "Trình duyệt sự kiện CLB", club_event.event.name)
    return club_event


@transaction.atomic
def review_club_event(
    *,
    actor: User,
    club_event: ClubEventProfile,
    approved: bool,
    review_note: str = "",
    auto_publish: bool = False,
) -> ClubEventProfile:
    """
    Phê duyệt hoặc từ chối sự kiện (`WF10`, Ma trận phân quyền dòng 7):
    - `CLUB_WIDE` và `PUBLIC_SHOW`: BẮT BUỘC có quyền `club.event.approve` (Chủ nhiệm hoặc Phó CN mảng Sự kiện).
      Trưởng ban chỉ có quyền Đề xuất, gọi hàm này sẽ bị chặn `403`!
    - `DEPT_INTERNAL`: Trưởng ban chủ trì (`dept.event.manage_internal`) hoặc BCN (`club.event.approve`) duyệt.
    """
    if club_event.event_scope in (ClubEventScope.CLUB_WIDE, ClubEventScope.PUBLIC_SHOW):
        PermissionEngine.require(actor, "club.event.approve")
    else:
        if not (
            PermissionEngine.authorize(
                actor, "dept.event.manage_internal", department=club_event.lead_department
            )
            or PermissionEngine.authorize(actor, "club.event.approve")
        ):
            PermissionEngine.require(
                actor, "dept.event.manage_internal", department=club_event.lead_department
            )

    if club_event.approval_status not in (
        ClubEventApprovalStatus.DRAFT,
        ClubEventApprovalStatus.SUBMITTED,
        ClubEventApprovalStatus.UNDER_REVIEW,
    ):
        raise GovernanceError("Sự kiện không ở trạng thái chờ phê duyệt.")

    club_event.approval_status = (
        ClubEventApprovalStatus.APPROVED if approved else ClubEventApprovalStatus.REJECTED
    )
    club_event.approved_by = actor
    club_event.approved_at = timezone.now()
    club_event.review_note = (review_note or "").strip()[:255]
    club_event.save(
        update_fields=[
            "approval_status",
            "approved_by",
            "approved_at",
            "review_note",
            "updated_at",
        ]
    )

    AuditLog.write(
        actor,
        "Phê duyệt sự kiện CLB" if approved else "Từ chối đề xuất sự kiện CLB",
        club_event.event.name,
        note=club_event.review_note,
    )
    if approved and auto_publish:
        return publish_club_event(actor=actor, club_event=club_event)
    return club_event


@transaction.atomic
def publish_club_event(
    *,
    actor: User,
    club_event: ClubEventProfile,
) -> ClubEventProfile:
    """
    Ban hành chính thức sự kiện (`WF11`, `INT-01`, `BE-08`, `CF-02`, `CM-04`):
    - Gắn phiên bản chính sách RSVP hiện hành (`PolicyVersion`).
    - Chỉ `PUBLIC_SHOW` đã được duyệt mới mở `Event.visibility = PUBLIC`;
      `DEPT_INTERNAL` và `CLUB_WIDE` luôn giữ `Event.visibility = INTERNAL` (`INT-01`).
    - Nếu sự kiện có RSVP cấp CLB: khởi tạo `PENDING_RESPONSE` cho thành viên `ACTIVE`,
      và tự động gắn `EXEMPT_SUSPENDED` cho thành viên đang `SUSPENDED` để không bao giờ phạt kép (`CF-02`).
    """
    if club_event.event_scope in (ClubEventScope.CLUB_WIDE, ClubEventScope.PUBLIC_SHOW):
        PermissionEngine.require(actor, "club.event.approve")
    else:
        if not (
            PermissionEngine.authorize(
                actor, "dept.event.manage_internal", department=club_event.lead_department
            )
            or PermissionEngine.authorize(actor, "club.event.approve")
        ):
            PermissionEngine.require(
                actor, "dept.event.manage_internal", department=club_event.lead_department
            )

    if club_event.approval_status != ClubEventApprovalStatus.APPROVED:
        raise GovernanceError("Sự kiện bắt buộc phải được phê duyệt (APPROVED) trước khi ban hành.")

    rsvp_policy = PolicyVersion.objects.filter(
        policy_key="CLUB_EVENT_DEFAULT_RSVP", is_current=True
    ).first()
    now = timezone.now()

    club_event.approval_status = ClubEventApprovalStatus.PUBLISHED
    club_event.published_at = now
    club_event.policy_version = rsvp_policy
    club_event.save(
        update_fields=["approval_status", "published_at", "policy_version", "updated_at"]
    )

    base_event = club_event.event
    base_event.status = EventStatus.OPEN
    if club_event.event_scope == ClubEventScope.PUBLIC_SHOW:
        base_event.visibility = EventVisibility.PUBLIC
    else:
        base_event.visibility = EventVisibility.INTERNAL
    base_event.save(update_fields=["status", "visibility"])

    if club_event.event_scope == ClubEventScope.CLUB_WIDE or club_event.require_club_rsvp:
        memberships = list(
            ClubMembership.objects.select_related("user").filter(
                status__in=[ClubMembershipStatus.ACTIVE, ClubMembershipStatus.SUSPENDED],
                user__is_locked=False,
            )
        )
        for cm in memberships:
            initial_status = (
                RsvpStatus.EXEMPT_SUSPENDED
                if cm.status == ClubMembershipStatus.SUSPENDED
                else RsvpStatus.PENDING_RESPONSE
            )
            att, created = EventAttendance.objects.get_or_create(
                club_event=club_event,
                user=cm.user,
                defaults={"rsvp_status": initial_status},
            )
            if created and initial_status == RsvpStatus.PENDING_RESPONSE:
                freeze_txt = (
                    f"Hạn phản hồi: {timezone.localtime(club_event.rsvp_freeze_at):%H:%M %d/%m/%Y}"
                    if club_event.rsvp_freeze_at
                    else "Vui lòng xác nhận tham gia"
                )
                dispatch_idempotent_reminder(
                    target_type=ReminderTargetType.EVENT_RSVP,
                    target_id=club_event.id,
                    recipient=cm.user,
                    stage=ReminderStage.ASSIGNED,
                    kind=NotificationKind.EVENT_RSVP,
                    title=f"Sự kiện CLB mới: {base_event.name}",
                    message=f"{freeze_txt} tại {base_event.location}.",
                    url=f"/workspace/su-kien/{club_event.id}/",
                    email_category="event_rsvp",
                )
    elif club_event.event_scope == ClubEventScope.DEPT_INTERNAL:
        dept_ids = set(
            club_event.department_roles.values_list("department_id", flat=True)
        ) | {club_event.lead_department_id}
        dept_members = list(
            DepartmentMembership.objects.select_related("user", "user__club_membership")
            .filter(
                department_id__in=dept_ids,
                status=DeptMembershipStatus.ACTIVE,
                user__is_locked=False,
                user__club_membership__status=ClubMembershipStatus.ACTIVE,
            )
        )
        seen_users = set()
        for dm in dept_members:
            if dm.user_id in seen_users:
                continue
            seen_users.add(dm.user_id)
            EventAttendance.objects.get_or_create(
                club_event=club_event,
                user=dm.user,
                defaults={"rsvp_status": RsvpStatus.PENDING_RESPONSE},
            )

    AuditLog.write(
        actor,
        "Ban hành sự kiện CLB",
        base_event.name,
        note=f"Visibility={base_event.visibility}",
    )
    return club_event


@transaction.atomic
def respond_event_rsvp(
    *,
    actor: User,
    club_event: ClubEventProfile,
    attending: bool,
    decline_reason: str = "",
) -> EventAttendance:
    """Thành viên phản hồi Tham gia hoặc Xin vắng có lý do trước hạn chốt (`WF12`)."""
    cm = actor.club_membership_record if getattr(actor, "is_authenticated", False) else None
    if not cm or cm.status != ClubMembershipStatus.ACTIVE:
        raise PermissionDenied("Chỉ thành viên CLB đang ACTIVE mới có thể phản hồi RSVP sự kiện nội bộ.")

    if club_event.approval_status not in (
        ClubEventApprovalStatus.PUBLISHED,
        ClubEventApprovalStatus.ONGOING,
    ):
        raise GovernanceError("Sự kiện này hiện chưa mở nhận phản hồi RSVP.")

    if club_event.is_rsvp_frozen:
        raise GovernanceError(
            "Đã quá thời hạn chốt danh sách RSVP của sự kiện này, không thể tự thay đổi phản hồi.",
            code="RSVP_FROZEN",
        )

    clean_reason = (decline_reason or "").strip()
    if not attending and not clean_reason:
        raise GovernanceError("Khi báo vắng sự kiện cấp CLB, bạn bắt buộc phải ghi rõ lý do xin phép.")

    att, _ = EventAttendance.objects.select_for_update().get_or_create(
        club_event=club_event,
        user=actor,
        defaults={"rsvp_status": RsvpStatus.PENDING_RESPONSE},
    )
    prev_status = att.rsvp_status
    new_status = (
        RsvpStatus.CONFIRMED_ATTENDING if attending else RsvpStatus.DECLINED_PENDING
    )
    att.rsvp_status = new_status
    att.decline_reason = "" if attending else clean_reason[:255]
    att.responded_at = timezone.now()
    att.save(update_fields=["rsvp_status", "decline_reason", "responded_at", "updated_at"])

    EventAttendanceHistory.objects.create(
        attendance=att,
        previous_rsvp_status=prev_status,
        new_rsvp_status=new_status,
        actor=actor,
        note=att.decline_reason or "Thành viên xác nhận tham gia",
    )
    return att


@transaction.atomic
def review_rsvp_exemption(
    *,
    actor: User,
    attendance: EventAttendance,
    exempted: bool,
    note: str = "",
) -> EventAttendance:
    """Cán bộ xét duyệt đơn xin vắng sự kiện cấp CLB (`DECLINED_EXEMPTED` vs `DECLINED_UNEXCUSED` — `BE-03`)."""
    club_event = attendance.club_event
    if not (
        PermissionEngine.authorize(actor, "club.event.configure_rsvp")
        or PermissionEngine.authorize(actor, "club.event.approve")
        or PermissionEngine.authorize(
            actor, "dept.event.manage_internal", department=club_event.lead_department
        )
    ):
        PermissionEngine.require(actor, "club.event.configure_rsvp")

    if actor.id == attendance.user_id:
        raise PermissionDenied("Không được tự phê duyệt đơn xin vắng sự kiện của chính mình (INV-03).")

    prev = attendance.rsvp_status
    attendance.rsvp_status = (
        RsvpStatus.DECLINED_EXEMPTED if exempted else RsvpStatus.DECLINED_UNEXCUSED
    )
    attendance.exemption_reviewed_by = actor
    attendance.exemption_reviewed_at = timezone.now()
    attendance.exemption_note = (note or "").strip()[:255]
    attendance.save(
        update_fields=[
            "rsvp_status",
            "exemption_reviewed_by",
            "exemption_reviewed_at",
            "exemption_note",
            "updated_at",
        ]
    )
    EventAttendanceHistory.objects.create(
        attendance=attendance,
        previous_rsvp_status=prev,
        new_rsvp_status=attendance.rsvp_status,
        actor=actor,
        note=attendance.exemption_note,
    )

    if not exempted and club_event.event_scope == ClubEventScope.CLUB_WIDE:
        evaluate_member_discipline_thresholds(attendance.user)
    return attendance


@transaction.atomic
def freeze_event_rsvp(
    club_event: ClubEventProfile,
    actor: User | None = None,
) -> int:
    """
    Khoá sổ RSVP tại thời điểm `rsvp_freeze_at` (Quyết định `A3` & `CF-02`):
    - Thành viên đang bị `SUSPENDED` tự động chuyển sang `EXEMPT_SUSPENDED` (không bao giờ phạt kép `CF-02`).
    - Thành viên `ACTIVE` còn `PENDING_RESPONSE` chuyển sang `AUTO_COMMITTED` nếu `default_opt_out_rsvp=True`.
    """
    if actor is not None:
        if not (
            PermissionEngine.authorize(actor, "club.event.configure_rsvp")
            or PermissionEngine.authorize(actor, "club.event.approve")
            or PermissionEngine.authorize(
                actor, "dept.event.manage_internal", department=club_event.lead_department
            )
        ):
            PermissionEngine.require(actor, "club.event.configure_rsvp")

    pending_rows = list(
        EventAttendance.objects.select_for_update()
        .select_related("user", "user__club_membership")
        .filter(club_event=club_event, rsvp_status=RsvpStatus.PENDING_RESPONSE)
    )
    auto_committed_count = 0
    for att in pending_rows:
        cm = att.user.club_membership_record
        if not cm or cm.status != ClubMembershipStatus.ACTIVE:
            att.rsvp_status = RsvpStatus.EXEMPT_SUSPENDED
            att.save(update_fields=["rsvp_status", "updated_at"])
            EventAttendanceHistory.objects.create(
                attendance=att,
                previous_rsvp_status=RsvpStatus.PENDING_RESPONSE,
                new_rsvp_status=RsvpStatus.EXEMPT_SUSPENDED,
                actor=actor,
                note="Tự động miễn trừ do thành viên đang tạm khoá / không ACTIVE tại thời điểm chốt (CF-02)",
            )
            continue

        if club_event.default_opt_out_rsvp:
            att.rsvp_status = RsvpStatus.AUTO_COMMITTED
            att.save(update_fields=["rsvp_status", "updated_at"])
            auto_committed_count += 1
            EventAttendanceHistory.objects.create(
                attendance=att,
                previous_rsvp_status=RsvpStatus.PENDING_RESPONSE,
                new_rsvp_status=RsvpStatus.AUTO_COMMITTED,
                actor=actor,
                note="Chốt danh sách tự động theo Chính sách RSVP Sự kiện cấp CLB (Quyết định A3)",
            )

    if club_event.rsvp_frozen_at is None:
        club_event.rsvp_frozen_at = timezone.now()
        club_event.save(update_fields=["rsvp_frozen_at", "updated_at"])
    return auto_committed_count


@transaction.atomic
def record_member_event_checkin(
    *,
    actor: User,
    attendance: EventAttendance,
    checkin_status: str,
) -> EventAttendance:
    """Điểm danh thực tế thành viên tại sự kiện nội bộ (`PRESENT` / `LATE` / `NO_SHOW`)."""
    club_event = attendance.club_event
    if not (
        PermissionEngine.authorize(actor, "club.event.approve")
        or PermissionEngine.authorize(actor, "club.event.configure_rsvp")
        or PermissionEngine.authorize(
            actor, "dept.event.manage_internal", department=club_event.lead_department
        )
    ):
        PermissionEngine.require(
            actor, "dept.event.manage_internal", department=club_event.lead_department
        )
    if checkin_status not in CheckinStatus.values:
        raise GovernanceError("Trạng thái điểm danh không hợp lệ.")

    # CF-02: Thành viên đang tạm khoá được bảo vệ miễn trừ tuyệt đối, không ghi NO_SHOW
    if (
        attendance.rsvp_status == RsvpStatus.EXEMPT_SUSPENDED
        or attendance.user.club_status == ClubMembershipStatus.SUSPENDED
    ):
        attendance.rsvp_status = RsvpStatus.EXEMPT_SUSPENDED
        attendance.checkin_status = CheckinStatus.NOT_YET
        attendance.save(update_fields=["rsvp_status", "checkin_status", "updated_at"])
        return attendance

    attendance.checkin_status = checkin_status
    attendance.checked_in_by = actor
    attendance.checked_in_at = timezone.now()
    attendance.save(
        update_fields=["checkin_status", "checked_in_by", "checked_in_at", "updated_at"]
    )

    if (
        checkin_status == CheckinStatus.NO_SHOW
        and club_event.event_scope == ClubEventScope.CLUB_WIDE
    ):
        evaluate_member_discipline_thresholds(attendance.user)
    return attendance


# ---------------------------------------------------------------------------
# 3. CẢNH BÁO KỶ LUẬT MINH BẠCH (`> 3` VI PHẠM — CẤM TỰ KHOÁ `R04`) & KHIẾU NẠI (`WF23–WF24`)
# ---------------------------------------------------------------------------
@transaction.atomic
def evaluate_member_discipline_thresholds(target_user: User) -> list[DisciplineCase]:
    """
    Quét minh bạch số lần vi phạm của `target_user` trong kỳ theo `PolicyVersion` hiện hành (`BE-08`):
    1. Số sự kiện cấp CLB vắng không phép / No-show sau cam kết `> threshold` (mặc định `> 3`, tức từ lần thứ 4).
    2. Số nhiệm vụ sự kiện bị đánh giá Không đạt (`REJECTED`) hoặc quá hạn `> threshold` (mặc định `> 3`).

    QUY TẮC BẤT BIẾN `R04`: Chỉ tạo/cập nhật `DisciplineCase(status=FLAGGED)` kèm bằng chứng JSON,
    TUYỆT ĐỐI KHÔNG tự động khoá tài khoản hay tự động chuyển `ClubMembership` sang `SUSPENDED`!
    """
    cm = target_user.club_membership_record
    if not cm or cm.status != ClubMembershipStatus.ACTIVE:
        return []

    policy = PolicyVersion.objects.filter(
        policy_key="VIOLATION_THRESHOLD_SEMESTER", is_current=True
    ).first()
    cfg = policy.config if policy else {}
    threshold = int(cfg.get("warning_threshold_exceeded_after", 3))
    window_months = int(cfg.get("window_months", 6))
    window_start = timezone.now() - timedelta(days=30 * window_months)

    flagged_cases: list[DisciplineCase] = []

    # 1. Quét vi phạm chuyên cần Sự kiện cấp CLB
    club_attendances = list(
        EventAttendance.objects.select_related("club_event__event")
        .filter(
            user=target_user,
            club_event__event_scope=ClubEventScope.CLUB_WIDE,
            updated_at__gte=window_start,
        )
    )
    unexcused_atts = [a for a in club_attendances if a.counts_as_unexcused_violation]
    if len(unexcused_atts) > threshold:
        evidence = {
            "window_months": window_months,
            "threshold_exceeded_after": threshold,
            "events": [
                {
                    "club_event_id": a.club_event_id,
                    "event_name": a.club_event.event.name,
                    "rsvp_status": a.rsvp_status,
                    "checkin_status": a.checkin_status,
                }
                for a in unexcused_atts
            ],
        }
        case = (
            DisciplineCase.objects.filter(
                target_user=target_user,
                trigger_type=DisciplineTriggerType.EVENT_ATTENDANCE_THRESHOLD,
                status__in=[DisciplineStatus.FLAGGED, DisciplineStatus.UNDER_REVIEW],
            )
            .order_by("-created_at")
            .first()
        )
        created_new = False
        if case is None:
            case = DisciplineCase.objects.create(
                target_user=target_user,
                trigger_type=DisciplineTriggerType.EVENT_ATTENDANCE_THRESHOLD,
                violation_count=len(unexcused_atts),
                threshold_applied=threshold,
                policy_version=policy,
                summary=(
                    f"Cảnh báo chuyên cần: {len(unexcused_atts)} lần vắng sự kiện cấp CLB không phép "
                    f"(vượt ngưỡng > {threshold} lần/kỳ). Chờ Ban Chủ nhiệm xem xét thủ công."
                ),
                evidence_snapshot=evidence,
                status=DisciplineStatus.FLAGGED,
            )
            created_new = True
        else:
            case.violation_count = len(unexcused_atts)
            case.evidence_snapshot = evidence
            case.summary = (
                f"Cảnh báo chuyên cần: {len(unexcused_atts)} lần vắng sự kiện cấp CLB không phép "
                f"(vượt ngưỡng > {threshold} lần/kỳ). Chờ Ban Chủ nhiệm xem xét thủ công."
            )
            case.save(update_fields=["violation_count", "evidence_snapshot", "summary", "updated_at"])

        if created_new:
            send_operational_alert(
                user=target_user,
                kind=NotificationKind.DISCIPLINE_ALERT,
                title="Cảnh báo ngưỡng chuyên cần sự kiện CLB",
                message=case.summary,
                url="/workspace/ky-luat/",
                email_category="important",
            )
            for reviewer in _get_executive_reviewers():
                if reviewer.id != target_user.id:
                    send_operational_alert(
                        user=reviewer,
                        kind=NotificationKind.DISCIPLINE_ALERT,
                        title=f"Hồ sơ cần BCN xem xét: {target_user.public_name}",
                        message=case.summary,
                        url="/workspace/ky-luat/",
                    )
        flagged_cases.append(case)

    # 2. Quét vi phạm nhiệm vụ gắn với Sự kiện
    event_tasks = list(
        ClubTask.objects.filter(
            assignees__user=target_user,
            event__isnull=False,
            created_at__gte=window_start,
        ).distinct()
    )
    violating_tasks = [
        t
        for t in event_tasks
        if t.workflow_status == TaskWorkflowStatus.REJECTED or t.is_overdue
    ]
    if len(violating_tasks) > threshold:
        task_evidence = {
            "window_months": window_months,
            "threshold_exceeded_after": threshold,
            "tasks": [
                {
                    "task_id": t.id,
                    "title": t.title,
                    "workflow_status": t.workflow_status,
                    "is_overdue": t.is_overdue,
                }
                for t in violating_tasks
            ],
        }
        t_case = (
            DisciplineCase.objects.filter(
                target_user=target_user,
                trigger_type=DisciplineTriggerType.EVENT_TASK_THRESHOLD,
                status__in=[DisciplineStatus.FLAGGED, DisciplineStatus.UNDER_REVIEW],
            )
            .order_by("-created_at")
            .first()
        )
        created_task_case = False
        if t_case is None:
            t_case = DisciplineCase.objects.create(
                target_user=target_user,
                trigger_type=DisciplineTriggerType.EVENT_TASK_THRESHOLD,
                violation_count=len(violating_tasks),
                threshold_applied=threshold,
                policy_version=policy,
                summary=(
                    f"Cảnh báo trách nhiệm sự kiện: {len(violating_tasks)} nhiệm vụ sự kiện không đạt/quá hạn "
                    f"(vượt ngưỡng > {threshold} lần/kỳ). Chờ Ban Chủ nhiệm xem xét."
                ),
                evidence_snapshot=task_evidence,
                status=DisciplineStatus.FLAGGED,
            )
            created_task_case = True
        else:
            t_case.violation_count = len(violating_tasks)
            t_case.evidence_snapshot = task_evidence
            t_case.save(update_fields=["violation_count", "evidence_snapshot", "updated_at"])

        if created_task_case:
            send_operational_alert(
                user=target_user,
                kind=NotificationKind.DISCIPLINE_ALERT,
                title="Cảnh báo tiến độ nhiệm vụ sự kiện CLB",
                message=t_case.summary,
                url="/workspace/ky-luat/",
                email_category="important",
            )
        flagged_cases.append(t_case)

    return flagged_cases


@transaction.atomic
def propose_manual_discipline_case(
    *,
    actor: User,
    target_user: User,
    department: Department | None,
    summary: str,
    evidence_note: str = "",
) -> DisciplineCase:
    """Trưởng ban / Phó ban HR hoặc BCN lập hồ sơ đề xuất xem xét kỷ luật minh bạch."""
    if actor.id == target_user.id:
        raise PermissionDenied("Không thể tự lập hồ sơ kỷ luật đối với chính mình.")
    authorized = PermissionEngine.authorize(
        actor, "club.member.suspend_temporary", target_user=target_user
    )
    if not authorized and department is not None:
        authorized = PermissionEngine.authorize(
            actor,
            "dept.evaluation.propose",
            department=department,
            target_user=target_user,
        )
    if not authorized:
        if department is not None:
            PermissionEngine.require(
                actor,
                "dept.evaluation.propose",
                department=department,
                target_user=target_user,
            )
        PermissionEngine.require(
            actor, "club.member.suspend_temporary", target_user=target_user
        )

    clean_summary = (summary or "").strip()
    if not clean_summary:
        raise GovernanceError("Tóm tắt hồ sơ đề xuất không được để trống.")

    policy = PolicyVersion.objects.filter(
        policy_key="VIOLATION_THRESHOLD_SEMESTER", is_current=True
    ).first()
    case = DisciplineCase.objects.create(
        target_user=target_user,
        department=department,
        trigger_type=DisciplineTriggerType.MANUAL_PROPOSAL,
        violation_count=1,
        policy_version=policy,
        summary=clean_summary[:255],
        evidence_snapshot={"note": (evidence_note or "").strip()},
        status=DisciplineStatus.FLAGGED,
        created_by=actor,
    )
    send_operational_alert(
        user=target_user,
        kind=NotificationKind.DISCIPLINE_ALERT,
        title="Hồ sơ xem xét tư cách thành viên mới",
        message=case.summary,
        url="/workspace/ky-luat/",
        email_category="important",
    )
    AuditLog.write(actor, "Đề xuất xem xét kỷ luật", target_user.public_name, note=case.summary)
    return case


@transaction.atomic
def resolve_discipline_case(
    *,
    actor: User,
    case: DisciplineCase,
    new_status: str,
    resolution_note: str,
    suspended_until=None,
) -> DisciplineCase:
    """
    Chủ nhiệm (hoặc Phó CN mảng Nhân sự) xem xét thủ công hồ sơ `DisciplineCase` (`WF23`, `R04`).
    Chỉ khi lãnh đạo chọn rõ `SUSPENSION_APPLIED` kèm lý do, hệ thống mới gọi `suspend_club_member`.
    """
    PermissionEngine.require(
        actor, "club.member.suspend_temporary", target_user=case.target_user
    )
    if new_status not in (
        DisciplineStatus.UNDER_REVIEW,
        DisciplineStatus.EXEMPTED_DISMISSED,
        DisciplineStatus.WARNING_ISSUED,
        DisciplineStatus.SUSPENSION_APPLIED,
    ):
        raise GovernanceError("Quyết định xử lý hồ sơ không hợp lệ.")
    clean_note = (resolution_note or "").strip()
    if not clean_note:
        raise GovernanceError("Bắt buộc phải ghi rõ kết luận xem xét minh bạch.")

    case.status = new_status
    case.reviewed_by = actor
    case.reviewed_at = timezone.now()
    case.resolution_note = clean_note
    case.save(
        update_fields=["status", "reviewed_by", "reviewed_at", "resolution_note", "updated_at"]
    )

    if new_status == DisciplineStatus.SUSPENSION_APPLIED:
        suspend_club_member(
            actor=actor,
            target_user=case.target_user,
            reason=clean_note[:255],
            suspended_until=suspended_until,
        )

    send_operational_alert(
        user=case.target_user,
        kind=NotificationKind.DISCIPLINE_ALERT,
        title=f"Kết luận hồ sơ #{case.pk}: {case.get_status_display()}",
        message=clean_note[:220],
        url=(
            "/taikhoan/trang-thai/"
            if new_status == DisciplineStatus.SUSPENSION_APPLIED
            else "/workspace/ky-luat/"
        ),
        email_category="important",
    )
    AuditLog.write(
        actor,
        "Xử lý hồ sơ cảnh báo kỷ luật",
        f"{case.target_user.public_name} -> {case.get_status_display()}",
        note=clean_note[:180],
    )
    return case


@transaction.atomic
def submit_appeal(
    *,
    appellant: User,
    target_type: str,
    reason: str,
    discipline_case: DisciplineCase | None = None,
    task_review: TaskReview | None = None,
    evidence_url: str = "",
) -> Appeal:
    """
    Thành viên (kể cả đang bị tạm khoá `SUSPENDED`!) gửi đơn khiếu nại / giải trình độc lập (`WF24`, Chỉ thị 3.3).
    """
    if not appellant or not getattr(appellant, "is_authenticated", False):
        raise PermissionDenied("Bạn cần đăng nhập để gửi khiếu nại.")
    if appellant.is_locked or appellant.account_status == AccountStatus.LOCKED:
        raise PermissionDenied("Tài khoản đã bị khoá cấp hệ thống.")

    cm = appellant.club_membership_record
    if cm is None:
        raise PermissionDenied("Chức năng khiếu nại nội bộ chỉ dành cho thành viên CLB.")

    clean_reason = (reason or "").strip()
    if not clean_reason:
        raise GovernanceError("Nội dung giải trình / khiếu nại không được để trống.")
    if target_type not in AppealTargetType.values:
        raise GovernanceError("Loại khiếu nại không hợp lệ.")

    original_actor = None
    if target_type == AppealTargetType.TASK_REVIEW:
        if task_review is None:
            raise GovernanceError("Vui lòng chỉ định biên bản nghiệm thu cần phản hồi.")
        if not task_review.task.assignees.filter(user=appellant).exists():
            raise PermissionDenied("Bạn chỉ được phản hồi biên bản nghiệm thu nhiệm vụ của chính mình.")
        original_actor = task_review.reviewer
        dup_qs = Appeal.objects.filter(
            appellant=appellant,
            target_type=target_type,
            task_review=task_review,
            status__in=[AppealStatus.SUBMITTED, AppealStatus.UNDER_REVIEW],
        )
    elif target_type == AppealTargetType.DISCIPLINE_CASE:
        if discipline_case is None or discipline_case.target_user_id != appellant.id:
            raise PermissionDenied("Hồ sơ cảnh báo/kỷ luật không thuộc về bạn.")
        original_actor = discipline_case.reviewed_by or discipline_case.created_by
        dup_qs = Appeal.objects.filter(
            appellant=appellant,
            target_type=target_type,
            discipline_case=discipline_case,
            status__in=[AppealStatus.SUBMITTED, AppealStatus.UNDER_REVIEW],
        )
    else:
        if cm.status != ClubMembershipStatus.SUSPENDED and discipline_case is None:
            raise GovernanceError("Tư cách thành viên của bạn hiện không bị tạm khoá.")
        latest_susp = (
            MemberLifecycleEvent.objects.filter(
                user=appellant, event_type=LifecycleEventType.SUSPENDED
            )
            .order_by("-created_at", "-id")
            .first()
        )
        original_actor = (
            (discipline_case.reviewed_by if discipline_case else None)
            or (latest_susp.actor if latest_susp else None)
        )
        dup_qs = Appeal.objects.filter(
            appellant=appellant,
            target_type=AppealTargetType.MEMBERSHIP_SUSPENSION,
            status__in=[AppealStatus.SUBMITTED, AppealStatus.UNDER_REVIEW],
        )

    if dup_qs.exists():
        raise GovernanceError("Bạn đang có một đơn khiếu nại cùng nội dung chờ thụ lý.")

    safe_url = clean_evidence_url(evidence_url)
    appeal = Appeal.objects.create(
        appellant=appellant,
        target_type=target_type,
        discipline_case=discipline_case,
        task_review=task_review,
        original_actor=original_actor,
        reason=clean_reason,
        evidence_url=safe_url,
    )

    for reviewer in _get_executive_reviewers():
        if reviewer.id != appellant.id:
            send_operational_alert(
                user=reviewer,
                kind=NotificationKind.APPEAL_UPDATE,
                title=f"Đơn khiếu nại mới từ {appellant.public_name}",
                message=f"[{appeal.get_target_type_display()}] {clean_reason[:140]}",
                url="/workspace/ky-luat/",
            )

    AuditLog.write(
        appellant,
        "Gửi đơn khiếu nại / giải trình",
        appeal.get_target_type_display(),
        note=clean_reason[:160],
    )
    return appeal


@transaction.atomic
def adjudicate_appeal(
    *,
    actor: User,
    appeal: Appeal,
    decision_status: str,
    decision_note: str,
) -> Appeal:
    """
    Thụ lý & phán quyết độc lập đơn khiếu nại (`WF24`, `INV-03`):
    - Cấm người gửi tự giải quyết đơn của mình.
    - Cấm người ra quyết định ban đầu (`original_actor`) tự phán quyết đơn khiếu nại về quyết định đó
      (trừ trường hợp Admin Server can thiệp kỹ thuật tối cao).
    - Nếu `OVERTURNED` đối với quyết định tạm khoá: tự động khôi phục `ClubMembership` về `ACTIVE`!
    """
    if appeal.target_type == AppealTargetType.TASK_REVIEW:
        if not (
            PermissionEngine.authorize(
                actor, "club.dept.supervise_ops", target_user=appeal.appellant
            )
            or PermissionEngine.authorize(
                actor, "club.member.suspend_temporary", target_user=appeal.appellant
            )
        ):
            PermissionEngine.require(
                actor, "club.dept.supervise_ops", target_user=appeal.appellant
            )
    else:
        PermissionEngine.require(
            actor, "club.member.suspend_temporary", target_user=appeal.appellant
        )

    if actor.id == appeal.appellant_id:
        raise PermissionDenied("Không thể tự giải quyết đơn khiếu nại của chính mình.")

    if (
        appeal.original_actor_id is not None
        and actor.id == appeal.original_actor_id
        and not getattr(actor, "is_server_admin", False)
    ):
        raise PermissionDenied(
            "Vi phạm nguyên tắc khách quan độc lập (WF24): Người ra quyết định ban đầu không được tự phán quyết đơn khiếu nại về chính quyết định đó."
        )

    if decision_status not in (
        AppealStatus.UNDER_REVIEW,
        AppealStatus.UPHELD,
        AppealStatus.OVERTURNED,
    ):
        raise GovernanceError("Trạng thái giải quyết khiếu nại không hợp lệ.")
    if appeal.status in (AppealStatus.UPHELD, AppealStatus.OVERTURNED):
        raise GovernanceError("Đơn khiếu nại này đã có phán quyết cuối cùng.")

    clean_note = (decision_note or "").strip()
    if not clean_note:
        raise GovernanceError("Bắt buộc ghi rõ lý do và căn cứ giải quyết khiếu nại.")

    appeal.status = decision_status
    appeal.decided_by = actor
    appeal.decided_at = timezone.now()
    appeal.decision_note = clean_note
    appeal.save(
        update_fields=["status", "decided_by", "decided_at", "decision_note", "updated_at"]
    )

    if decision_status == AppealStatus.OVERTURNED:
        if (
            appeal.target_type == AppealTargetType.MEMBERSHIP_SUSPENSION
            or (
                appeal.discipline_case
                and appeal.discipline_case.status == DisciplineStatus.SUSPENSION_APPLIED
            )
        ) and appeal.appellant.club_status == ClubMembershipStatus.SUSPENDED:
            restore_club_member(
                actor=actor,
                target_user=appeal.appellant,
                reason=f"Chấp nhận khiếu nại #{appeal.pk}: {clean_note[:180]}",
            )
        if appeal.discipline_case is not None:
            appeal.discipline_case.status = DisciplineStatus.EXEMPTED_DISMISSED
            appeal.discipline_case.resolution_note = (
                f"Được huỷ/miễn trừ qua đơn khiếu nại #{appeal.pk}: {clean_note}"
            )
            appeal.discipline_case.save(
                update_fields=["status", "resolution_note", "updated_at"]
            )
        if (
            appeal.target_type == AppealTargetType.TASK_REVIEW
            and appeal.task_review is not None
        ):
            # Giữ nguyên biên bản cũ trong sổ cái bất biến, mở lại trạng thái task để chấm lại độc lập
            task = appeal.task_review.task
            task.workflow_status = TaskWorkflowStatus.UNDER_REVIEW
            task.completed_at = None
            task.save(update_fields=["workflow_status", "completed_at", "updated_at"])

    send_operational_alert(
        user=appeal.appellant,
        kind=NotificationKind.APPEAL_UPDATE,
        title=f"Kết quả khiếu nại #{appeal.pk}: {appeal.get_status_display()}",
        message=clean_note[:220],
        url=(
            "/workspace/"
            if appeal.appellant.club_status == ClubMembershipStatus.ACTIVE
            else "/taikhoan/trang-thai/"
        ),
        email_category="important",
    )
    AuditLog.write(
        actor,
        "Phán quyết đơn khiếu nại",
        f"Đơn #{appeal.pk} ({appeal.appellant.public_name}) -> {appeal.get_status_display()}",
        note=clean_note[:160],
    )
    return appeal


# ---------------------------------------------------------------------------
# 4. THÔNG BÁO CHÍNH THỨC CLB & TIẾN TRÌNH NHẮC VIỆC CHỦ ĐỘNG (MỤC 3.5)
# ---------------------------------------------------------------------------
@transaction.atomic
def broadcast_announcement(
    *,
    actor: User,
    title: str,
    content: str,
    department: Department | None = None,
    is_pinned: bool = False,
    send_email: bool = False,
) -> ClubAnnouncement:
    """Phát bản tin thông báo điều hành chính thức toàn CLB hoặc trong phạm vi một Ban."""
    if department is None:
        PermissionEngine.require(actor, "club.announcement.publish")
        recipients = [
            cm.user
            for cm in ClubMembership.objects.select_related("user").filter(
                status=ClubMembershipStatus.ACTIVE,
                user__is_locked=False,
            )
        ]
    else:
        if not (
            PermissionEngine.authorize(
                actor, "dept.event.manage_internal", department=department
            )
            or PermissionEngine.authorize(actor, "club.announcement.publish")
        ):
            PermissionEngine.require(
                actor, "dept.event.manage_internal", department=department
            )
        recipients = [
            dm.user
            for dm in DepartmentMembership.objects.select_related("user", "user__club_membership").filter(
                department=department,
                status=DeptMembershipStatus.ACTIVE,
                user__is_locked=False,
                user__club_membership__status=ClubMembershipStatus.ACTIVE,
            )
        ]

    clean_title = (title or "").strip()
    clean_content = (content or "").strip()
    if not clean_title or not clean_content:
        raise GovernanceError("Tiêu đề và nội dung thông báo không được để trống.")

    ann = ClubAnnouncement.objects.create(
        title=clean_title[:160],
        content=clean_content,
        department=department,
        is_pinned=is_pinned,
        send_email=send_email,
        published_by=actor,
        recipient_count=len(recipients),
    )

    target_url = (
        f"/workspace/ban/{department.slug}/" if department is not None else "/workspace/"
    )
    if send_email:
        for u in recipients:
            send_operational_alert(
                user=u,
                kind=NotificationKind.ANNOUNCEMENT,
                title=ann.title,
                message=clean_content[:220],
                url=target_url,
                email_category="important",
            )
    else:
        notify_many(
            recipients,
            kind=NotificationKind.ANNOUNCEMENT,
            title=ann.title,
            message=clean_content[:220],
            url=target_url,
        )

    scope_label = department.name if department is not None else "Toàn CLB"
    AuditLog.write(actor, "Phát thông báo chính thức", f"[{scope_label}] {ann.title}")
    return ann


def run_proactive_operations_cycle(now=None) -> dict:
    """
    Chu trình tự động định kỳ (Chỉ thị 3.5 & `DB-06` Idempotent Reminders):
    1. Khoá sổ RSVP các sự kiện cấp CLB đã tới `rsvp_freeze_at` (`freeze_event_rsvp`).
    2. Gửi nhắc hạn `T_48H`, `T_12H`, `OVERDUE` cho các `ClubTask` đang thực hiện (chống gửi trùng 100%).
    3. Gửi nhắc phản hồi `T_48H`, `T_12H` cho thành viên chưa trả lời RSVP sự kiện CLB.
    4. Quét cảnh báo vượt ngưỡng `> 3` vi phạm (`evaluate_member_discipline_thresholds`).
    """
    ref_now = now or timezone.now()
    frozen_events = 0
    auto_committed_members = 0
    task_reminders_sent = 0
    rsvp_reminders_sent = 0
    flagged_cases_count = 0

    due_events = list(
        ClubEventProfile.objects.select_related("event").filter(
            approval_status__in=[
                ClubEventApprovalStatus.PUBLISHED,
                ClubEventApprovalStatus.ONGOING,
            ],
            rsvp_freeze_at__isnull=False,
            rsvp_freeze_at__lte=ref_now,
            rsvp_frozen_at__isnull=True,
        )
    )
    for ce in due_events:
        auto_committed_members += freeze_event_rsvp(ce, actor=None)
        frozen_events += 1

    # Nhắc deadline công việc CLB
    open_tasks = list(
        ClubTask.objects.select_related("department")
        .prefetch_related("assignees__user")
        .exclude(
            workflow_status__in=[
                TaskWorkflowStatus.SUBMITTED,
                TaskWorkflowStatus.UNDER_REVIEW,
                TaskWorkflowStatus.APPROVED,
                TaskWorkflowStatus.REJECTED,
                TaskWorkflowStatus.CANCELLED,
            ]
        )
    )
    for task in open_tasks:
        delta = task.deadline - ref_now
        stage = None
        stage_label = ""
        if delta.total_seconds() < 0:
            stage = ReminderStage.OVERDUE
            stage_label = "đã quá hạn hoàn thành"
        elif delta <= timedelta(hours=12):
            stage = ReminderStage.T_12H
            stage_label = "còn dưới 12 giờ nữa đến hạn"
        elif delta <= timedelta(hours=48):
            stage = ReminderStage.T_48H
            stage_label = "còn dưới 48 giờ nữa đến hạn"

        if stage is not None:
            for a in task.assignees.all():
                if not a.is_active:
                    continue
                if dispatch_idempotent_reminder(
                    target_type=ReminderTargetType.CLUB_TASK,
                    target_id=task.id,
                    recipient=a.user,
                    stage=stage,
                    kind=NotificationKind.TASK_DEADLINE,
                    title=f"Nhắc hạn nhiệm vụ: {task.title}",
                    message=f"Nhiệm vụ tại {task.department.name} {stage_label}.",
                    url=f"/workspace/cong-viec/{task.id}/",
                    email_category="task_deadline",
                ):
                    task_reminders_sent += 1

    # Nhắc phản hồi RSVP sự kiện cấp CLB trước hạn chốt
    upcoming_rsvp_events = list(
        ClubEventProfile.objects.select_related("event").filter(
            approval_status=ClubEventApprovalStatus.PUBLISHED,
            rsvp_freeze_at__gt=ref_now,
            rsvp_frozen_at__isnull=True,
        )
    )
    for ce in upcoming_rsvp_events:
        delta = ce.rsvp_freeze_at - ref_now
        stage = None
        if delta <= timedelta(hours=12):
            stage = ReminderStage.T_12H
        elif delta <= timedelta(hours=48):
            stage = ReminderStage.T_48H
        if stage is not None:
            pending_atts = list(
                ce.attendances.select_related("user").filter(
                    rsvp_status=RsvpStatus.PENDING_RESPONSE
                )
            )
            for att in pending_atts:
                if dispatch_idempotent_reminder(
                    target_type=ReminderTargetType.EVENT_RSVP,
                    target_id=ce.id,
                    recipient=att.user,
                    stage=stage,
                    kind=NotificationKind.EVENT_RSVP,
                    title=f"Nhắc phản hồi RSVP: {ce.event.name}",
                    message=(
                        f"Vui lòng xác nhận Tham gia hoặc Xin phép trước "
                        f"{timezone.localtime(ce.rsvp_freeze_at):%H:%M %d/%m/%Y}."
                    ),
                    url=f"/workspace/su-kien/{ce.id}/",
                    email_category="event_rsvp",
                ):
                    rsvp_reminders_sent += 1

    # Quét ngưỡng cảnh báo chuyên cần (> 3 lần/kỳ)
    for cm in ClubMembership.objects.select_related("user").filter(
        status=ClubMembershipStatus.ACTIVE
    ):
        cases = evaluate_member_discipline_thresholds(cm.user)
        flagged_cases_count += len(cases)

    # Phase 3: Nhắc lịch đào tạo & lịch tập Band (`T_48H`, `T_12H`)
    training_reminders_sent = 0
    practice_reminders_sent = 0
    try:
        from programs.services import dispatch_training_and_practice_reminders

        prog_stats = dispatch_training_and_practice_reminders(ref_now=ref_now)
        training_reminders_sent = prog_stats["training_reminders_sent"]
        practice_reminders_sent = prog_stats["practice_reminders_sent"]
    except Exception:
        pass

    return {
        "frozen_events": frozen_events,
        "auto_committed_members": auto_committed_members,
        "task_reminders_sent": task_reminders_sent,
        "rsvp_reminders_sent": rsvp_reminders_sent,
        "training_reminders_sent": training_reminders_sent,
        "practice_reminders_sent": practice_reminders_sent,
        "flagged_cases_checked": flagged_cases_count,
    }
