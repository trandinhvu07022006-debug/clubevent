"""
Giao diện Web cho Vận hành Cốt lõi CLB KMG (`/workspace/cong-viec/`, `/workspace/su-kien/`, `/workspace/ky-luat/`).

Mọi view đều kiểm tra quyền thực tế tại Backend qua `PermissionEngine` và dịch vụ `operations.services`.
"""
from __future__ import annotations

import mimetypes
import os

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_POST

from accounts.models import User
from events.models import EventCategory
from organization.models import (
    ClubMembership,
    ClubMembershipStatus,
    Department,
    DepartmentMembership,
    DeptMembershipStatus,
    Skill,
)
from organization.permissions import PermissionEngine, club_member_required
from organization.services import GovernanceError

from .models import (
    Appeal,
    AppealStatus,
    AppealTargetType,
    CheckinStatus,
    ClubEventApprovalStatus,
    ClubEventProfile,
    ClubEventScope,
    ClubTask,
    DisciplineCase,
    DisciplineStatus,
    EventAttendance,
    EventDeptRoleType,
    ExtensionStatus,
    TaskExtensionRequest,
    TaskPriority,
    TaskReview,
    TaskReviewDecision,
    TaskSubmission,
    TaskSubmissionMode,
    TaskWorkflowStatus,
)
from .services import (
    adjudicate_appeal,
    can_access_task_submission_file,
    can_view_club_task,
    create_and_assign_task,
    create_club_event,
    finalize_task_review,
    freeze_event_rsvp,
    propose_manual_discipline_case,
    publish_club_event,
    reassign_club_task,
    recommend_assignees_for_task,
    record_member_event_checkin,
    request_task_extension,
    resolve_discipline_case,
    respond_event_rsvp,
    review_club_event,
    review_rsvp_exemption,
    review_task_extension,
    submit_appeal,
    submit_club_event_for_approval,
    submit_task_deliverable,
    update_task_progress,
)


def _parse_local_dt(raw: str):
    if not raw:
        return None
    dt = parse_datetime(raw.strip())
    if dt is None:
        return None
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


# ---------------------------------------------------------------------------
# 1. KHÔNG GIAN CÔNG VIỆC CLB (`/workspace/cong-viec/`)
# ---------------------------------------------------------------------------
@club_member_required
def task_list(request):
    """
    Bảng điều phối & theo dõi Công việc CLB Đa Ban:
    - Thành viên xem nhiệm vụ bản thân được giao.
    - Trưởng ban / Phó ban có gói `BUNDLE_TASK_OPS` / Phó CN `PORTFOLIO_OPS` / Chủ nhiệm xem & giao nhiệm vụ trong phạm vi quyền.
    - Cố vấn thuần tuý (`INV-04` / Ma trận dòng 2) không truy cập danh sách nhiệm vụ cá nhân mà dùng Cổng Giám sát tổng hợp.
    """
    actor = request.user
    ctx = PermissionEngine.summarize_actor_context(actor)
    if ctx["is_advisor"] and not ctx["departments"] and not ctx["can_access_club_governance"]:
        raise PermissionDenied(
            "Theo Ma trận Phân quyền D04, Cố vấn giám sát tiến độ tổng hợp tại Cổng Giám sát, không truy cập nhiệm vụ cá nhân."
        )

    all_depts = list(Department.objects.filter(is_active=True))
    assignable_depts = [
        d
        for d in all_depts
        if PermissionEngine.authorize(actor, "dept.task.assign", department=d)
        or PermissionEngine.authorize(actor, "club.dept.supervise_ops")
    ]
    view_all_dept_ids = [
        d.id
        for d in all_depts
        if PermissionEngine.authorize(actor, "dept.task.view_all", department=d)
        or PermissionEngine.authorize(actor, "club.dept.supervise_ops")
    ]

    if request.method == "POST" and request.POST.get("action") == "create_task":
        dept = get_object_or_404(Department, pk=request.POST.get("department_id"), is_active=True)
        deadline = _parse_local_dt(request.POST.get("deadline", ""))
        assignee_ids = request.POST.getlist("assignee_ids")
        assignees = list(User.objects.filter(pk__in=assignee_ids))
        skill_id = (request.POST.get("recommended_skill_id") or "").strip()
        rec_skill = Skill.objects.filter(pk=skill_id).first() if skill_id.isdigit() else None
        ce_id = (request.POST.get("club_event_id") or "").strip()
        ce_obj = (
            ClubEventProfile.objects.select_related("event").filter(pk=ce_id).first()
            if ce_id.isdigit()
            else None
        )
        try:
            if deadline is None:
                raise GovernanceError("Định dạng thời hạn hoàn thành (deadline) không hợp lệ.")
            task = create_and_assign_task(
                actor=actor,
                department=dept,
                title=request.POST.get("title", ""),
                description=request.POST.get("description", ""),
                deadline=deadline,
                assignees=assignees,
                priority=request.POST.get("priority", TaskPriority.MEDIUM),
                submission_mode=request.POST.get("submission_mode", TaskSubmissionMode.ANY_ONE),
                recommended_skill=rec_skill,
                event=ce_obj.event if ce_obj else None,
                category_tag=request.POST.get("category_tag", ""),
            )
            messages.success(
                request,
                f"Đã giao nhiệm vụ '{task.title}' cho {len(assignees)} thành viên tại {dept.name}!",
            )
            return redirect("operations:task_detail", pk=task.pk)
        except (GovernanceError, PermissionDenied) as exc:
            messages.error(request, str(exc))

    selected_dept_slug = (request.GET.get("ban") or "").strip()
    selected_skill_id = (request.GET.get("skill") or "").strip()
    filter_status = (request.GET.get("status") or "").strip()

    my_tasks_qs = (
        ClubTask.objects.select_related("department", "event", "recommended_skill", "created_by")
        .prefetch_related("assignees__user")
        .filter(assignees__user=actor, assignees__is_active=True)
        .distinct()
    )
    managed_tasks_qs = (
        ClubTask.objects.select_related("department", "event", "recommended_skill", "created_by")
        .prefetch_related("assignees__user")
        .filter(department_id__in=view_all_dept_ids)
        .distinct()
        if view_all_dept_ids
        else ClubTask.objects.none()
    )

    if selected_dept_slug:
        my_tasks_qs = my_tasks_qs.filter(department__slug=selected_dept_slug)
        managed_tasks_qs = managed_tasks_qs.filter(department__slug=selected_dept_slug)
    if filter_status in TaskWorkflowStatus.values:
        my_tasks_qs = my_tasks_qs.filter(workflow_status=filter_status)
        managed_tasks_qs = managed_tasks_qs.filter(workflow_status=filter_status)

    my_tasks = list(my_tasks_qs[:50])
    managed_tasks = list(managed_tasks_qs[:80])
    reassignment_tasks = [t for t in managed_tasks if t.reassignment_needed]

    # Gợi ý nhân sự theo Skill cho Ban đang chọn (INV-01)
    preview_dept = None
    if assignable_depts:
        preview_dept = next(
            (d for d in assignable_depts if d.slug == selected_dept_slug),
            assignable_depts[0],
        )
    preview_skill = (
        Skill.objects.filter(pk=selected_skill_id).first()
        if selected_skill_id.isdigit()
        else None
    )
    recommended_candidates = (
        recommend_assignees_for_task(preview_dept, skill=preview_skill)
        if preview_dept is not None
        else []
    )
    all_assignable_members = (
        list(
            DepartmentMembership.objects.select_related("user", "department")
            .filter(
                department__in=assignable_depts,
                status=DeptMembershipStatus.ACTIVE,
                user__club_membership__status=ClubMembershipStatus.ACTIVE,
            )
            .order_by("department__display_order", "user__full_name")
        )
        if assignable_depts
        else []
    )
    skills = list(Skill.objects.select_related("category").filter(is_active=True))
    active_club_events = list(
        ClubEventProfile.objects.select_related("event", "lead_department")
        .exclude(
            approval_status__in=[
                ClubEventApprovalStatus.CANCELLED,
                ClubEventApprovalStatus.ARCHIVED,
                ClubEventApprovalStatus.REJECTED,
            ]
        )[:30]
    )

    return render(
        request,
        "operations/task_list.html",
        {
            "my_tasks": my_tasks,
            "managed_tasks": managed_tasks,
            "reassignment_tasks": reassignment_tasks,
            "assignable_depts": assignable_depts,
            "preview_dept": preview_dept,
            "preview_skill": preview_skill,
            "recommended_candidates": recommended_candidates,
            "all_assignable_members": all_assignable_members,
            "skills": skills,
            "active_club_events": active_club_events,
            "priority_choices": TaskPriority.choices,
            "submission_modes": TaskSubmissionMode.choices,
            "status_choices": TaskWorkflowStatus.choices,
            "selected_dept_slug": selected_dept_slug,
            "filter_status": filter_status,
            "default_deadline": (timezone.localtime() + timezone.timedelta(days=3)).strftime(
                "%Y-%m-%dT%H:%M"
            ),
        },
    )


@club_member_required
def task_detail(request, pk: int):
    """Chi tiết 10 bước thực hiện, nộp tệp Private Vault, xin gia hạn & nghiệm thu bất biến (`WF13–WF15`)."""
    task = get_object_or_404(
        ClubTask.objects.select_related(
            "department", "event", "recommended_skill", "created_by"
        ),
        pk=pk,
    )
    actor = request.user
    if not can_view_club_task(actor, task):
        raise PermissionDenied("Bạn không có quyền truy cập nhiệm vụ nội bộ này.")

    assignee_ids = task.assignee_user_ids
    is_assignee = actor.id in assignee_ids
    has_approve_perm = PermissionEngine.authorize(
        actor, "dept.task.approve", department=task.department
    ) or PermissionEngine.authorize(actor, "club.dept.supervise_ops")
    # PA-04: Kể cả Trưởng ban/Chủ nhiệm nếu đang là người thực hiện cũng KHÔNG được tự nghiệm thu
    can_review_this_task = has_approve_perm and not is_assignee
    can_reassign = PermissionEngine.authorize(
        actor, "dept.task.assign", department=task.department
    ) or PermissionEngine.authorize(actor, "club.dept.supervise_ops")

    if request.method == "POST":
        action = request.POST.get("action", "")
        try:
            if action == "update_progress":
                pct_raw = (request.POST.get("progress_percent") or "").strip()
                pct = int(pct_raw) if pct_raw.isdigit() else None
                update_task_progress(
                    actor=actor,
                    task=task,
                    new_status=request.POST.get("new_status", TaskWorkflowStatus.IN_PROGRESS),
                    progress_percent=pct,
                )
                messages.success(request, "Đã cập nhật trạng thái tiến độ thực hiện nhiệm vụ.")

            elif action == "submit_deliverable":
                submit_task_deliverable(
                    actor=actor,
                    task=task,
                    submission_note=request.POST.get("submission_note", ""),
                    evidence_url=request.POST.get("evidence_url", ""),
                    attachment=request.FILES.get("attachment"),
                )
                messages.success(
                    request,
                    "Đã nộp kết quả nhiệm vụ thành công! Tệp đính kèm (nếu có) được lưu an toàn tại Private Vault.",
                )

            elif action == "request_extension":
                req_dt = _parse_local_dt(request.POST.get("requested_deadline", ""))
                if req_dt is None:
                    raise GovernanceError("Thời hạn đề xuất không hợp lệ.")
                request_task_extension(
                    actor=actor,
                    task=task,
                    requested_deadline=req_dt,
                    reason=request.POST.get("reason", ""),
                )
                messages.success(request, "Đã gửi yêu cầu xin gia hạn deadline tới cán bộ phụ trách.")

            elif action == "review_extension":
                ext = get_object_or_404(
                    TaskExtensionRequest, pk=request.POST.get("extension_id"), task=task
                )
                approved = request.POST.get("decision") == "approve"
                review_task_extension(
                    actor=actor,
                    extension_request=ext,
                    approved=approved,
                    review_note=request.POST.get("review_note", ""),
                )
                messages.success(
                    request,
                    "Đã đồng ý gia hạn deadline." if approved else "Đã từ chối yêu cầu gia hạn.",
                )

            elif action == "finalize_review":
                score_raw = (request.POST.get("quality_score") or "5").strip()
                score = int(score_raw) if score_raw.isdigit() else 5
                rev = finalize_task_review(
                    actor=actor,
                    task=task,
                    decision=request.POST.get("decision", ""),
                    quality_score=score,
                    feedback=request.POST.get("feedback", ""),
                )
                messages.success(
                    request,
                    f"Đã ghi biên bản nghiệm thu bất biến: {rev.get_decision_display()} ({rev.quality_score}/5).",
                )

            elif action == "reassign_task":
                new_ids = request.POST.getlist("assignee_ids")
                new_users = list(User.objects.filter(pk__in=new_ids))
                reassign_club_task(
                    actor=actor,
                    task=task,
                    new_assignees=new_users,
                    note=request.POST.get("note", ""),
                )
                messages.success(request, "Đã phân công lại nhân sự thực hiện nhiệm vụ.")

            elif action == "appeal_review":
                rev = get_object_or_404(TaskReview, pk=request.POST.get("review_id"), task=task)
                ap = submit_appeal(
                    appellant=actor,
                    target_type=AppealTargetType.TASK_REVIEW,
                    task_review=rev,
                    reason=request.POST.get("reason", ""),
                )
                messages.success(
                    request,
                    f"Đã gửi phản hồi/khiếu nại #{ap.pk} về kết quả nghiệm thu tới Ban Chủ nhiệm.",
                )

            return redirect("operations:task_detail", pk=task.pk)
        except (GovernanceError, PermissionDenied) as exc:
            messages.error(request, str(exc))

    assignees = list(task.assignees.select_related("user", "assigned_by"))
    submissions = list(task.submissions.select_related("submitted_by"))
    reviews = list(task.reviews.select_related("reviewer", "submission"))
    extensions = list(task.extension_requests.select_related("requested_by", "reviewed_by"))
    dept_candidates = (
        recommend_assignees_for_task(task.department, skill=task.recommended_skill)
        if can_reassign
        else []
    )

    return render(
        request,
        "operations/task_detail.html",
        {
            "task": task,
            "assignees": assignees,
            "submissions": submissions,
            "reviews": reviews,
            "extensions": extensions,
            "is_assignee": is_assignee,
            "has_approve_perm": has_approve_perm,
            "can_review_this_task": can_review_this_task,
            "can_reassign": can_reassign,
            "dept_candidates": dept_candidates,
            "review_decisions": TaskReviewDecision.choices,
        },
    )


@club_member_required
def download_task_submission_file(request, submission_id: int):
    """`SEC-01`: Tải tệp đính kèm bài nộp từ `PrivateVaultStorage` sau khi xác thực quyền Backend."""
    sub = get_object_or_404(
        TaskSubmission.objects.select_related("task__department", "submitted_by"),
        pk=submission_id,
    )
    if not can_access_task_submission_file(request.user, sub):
        raise PermissionDenied("Bạn không có quyền truy cập tệp đính kèm bảo mật của bài nộp này.")
    if not sub.attachment:
        raise Http404("Bài nộp này không có tệp đính kèm.")
    try:
        file_handle = sub.attachment.open("rb")
    except FileNotFoundError as exc:
        raise Http404("Không tìm thấy tệp trên kho lưu trữ.") from exc

    filename = os.path.basename(sub.attachment.name)
    content_type, _ = mimetypes.guess_type(filename)
    return FileResponse(
        file_handle,
        as_attachment=True,
        filename=filename,
        content_type=content_type or "application/octet-stream",
    )


# ---------------------------------------------------------------------------
# 2. TRUNG TÂM SỰ KIỆN KÉP, PHỐI HỢP LIÊN BAN & RSVP (`WF09–WF12`)
# ---------------------------------------------------------------------------
@club_member_required
def event_hub(request):
    """Không gian Sự kiện Nội bộ Ban, Sự kiện Toàn CLB (RSVP) & Đề xuất Show Công khai."""
    actor = request.user
    PermissionEngine.require(actor, "club.event.view_internal")

    all_depts = list(Department.objects.filter(is_active=True))
    can_approve_club_event = PermissionEngine.authorize(actor, "club.event.approve")
    proposable_depts = [
        d
        for d in all_depts
        if PermissionEngine.authorize(actor, "dept.event.manage_internal", department=d)
        or can_approve_club_event
    ]

    if request.method == "POST" and request.POST.get("action") == "create_club_event":
        lead_dept = get_object_or_404(
            Department, pk=request.POST.get("lead_department_id"), is_active=True
        )
        starts_at = _parse_local_dt(request.POST.get("starts_at", ""))
        rsvp_freeze_at = _parse_local_dt(request.POST.get("rsvp_freeze_at", ""))
        scope = request.POST.get("event_scope", ClubEventScope.DEPT_INTERNAL)
        support_ids = request.POST.getlist("support_department_ids")
        support_depts = [
            (d, EventDeptRoleType.CO_ORGANIZER, "Phối hợp chuyên môn / vận hành sự kiện")
            for d in Department.objects.filter(pk__in=support_ids, is_active=True)
            if d.id != lead_dept.id
        ]
        try:
            if starts_at is None:
                raise GovernanceError("Thời gian diễn ra sự kiện không hợp lệ.")
            profile = create_club_event(
                actor=actor,
                lead_department=lead_dept,
                name=request.POST.get("name", ""),
                location=request.POST.get("location", ""),
                starts_at=starts_at,
                rsvp_freeze_at=rsvp_freeze_at,
                event_scope=scope,
                category=request.POST.get("category", EventCategory.MUSIC),
                capacity=int(request.POST.get("capacity") or 100),
                budget=int(request.POST.get("budget") or 0),
                description=request.POST.get("description", ""),
                proposal_note=request.POST.get("proposal_note", ""),
                supporting_departments=support_depts,
            )
            if request.POST.get("submit_immediately") == "1":
                submit_club_event_for_approval(actor, profile)
            messages.success(
                request,
                f"Đã tạo kế hoạch sự kiện '{profile.event.name}' ({profile.get_event_scope_display()}).",
            )
            return redirect("operations:event_detail", pk=profile.pk)
        except (GovernanceError, PermissionDenied) as exc:
            messages.error(request, str(exc))

    active_dept_ids = PermissionEngine.get_active_department_ids(actor)
    can_supervise_all = (
        can_approve_club_event
        or PermissionEngine.authorize(actor, "club.overview.supervise")
    )
    qs = (
        ClubEventProfile.objects.select_related(
            "event", "lead_department", "proposed_by", "approved_by", "policy_version"
        )
        .prefetch_related("department_roles__department")
        .order_by("-event__starts_at")
    )
    if not can_supervise_all:
        qs = qs.filter(
            Q(approval_status__in=[ClubEventApprovalStatus.PUBLISHED, ClubEventApprovalStatus.ONGOING, ClubEventApprovalStatus.COMPLETED])
            | Q(lead_department_id__in=active_dept_ids)
            | Q(department_roles__department_id__in=active_dept_ids)
        ).distinct()

    club_events = list(qs[:60])
    my_rsvp_map = {
        att.club_event_id: att
        for att in EventAttendance.objects.filter(
            user=actor, club_event_id__in=[ce.id for ce in club_events]
        )
    }
    for ce in club_events:
        ce.my_attendance = my_rsvp_map.get(ce.id)

    pending_bcn_events = [
        ce
        for ce in club_events
        if ce.approval_status == ClubEventApprovalStatus.SUBMITTED
        and ce.event_scope in (ClubEventScope.CLUB_WIDE, ClubEventScope.PUBLIC_SHOW)
    ]

    return render(
        request,
        "operations/event_hub.html",
        {
            "club_events": club_events,
            "pending_bcn_events": pending_bcn_events,
            "departments": all_depts,
            "proposable_depts": proposable_depts,
            "can_approve_club_event": can_approve_club_event,
            "scope_choices": ClubEventScope.choices,
            "category_choices": EventCategory.choices,
            "default_starts": (timezone.localtime() + timezone.timedelta(days=7)).strftime(
                "%Y-%m-%dT19:00"
            ),
            "default_freeze": (timezone.localtime() + timezone.timedelta(days=5)).strftime(
                "%Y-%m-%dT23:59"
            ),
        },
    )


@club_member_required
def event_detail(request, pk: int):
    """Chi tiết sự kiện nội bộ/kép, phê duyệt BCN, phản hồi RSVP & điểm danh tách rời quota vé."""
    club_event = get_object_or_404(
        ClubEventProfile.objects.select_related(
            "event", "lead_department", "proposed_by", "approved_by", "policy_version"
        ),
        pk=pk,
    )
    actor = request.user
    PermissionEngine.require(actor, "club.event.view_internal")

    can_manage_lead = PermissionEngine.authorize(
        actor, "dept.event.manage_internal", department=club_event.lead_department
    )
    can_approve_bcn = PermissionEngine.authorize(actor, "club.event.approve")
    can_approve_this = (
        can_approve_bcn
        if club_event.event_scope in (ClubEventScope.CLUB_WIDE, ClubEventScope.PUBLIC_SHOW)
        else (can_manage_lead or can_approve_bcn)
    )
    can_manage_rsvp = (
        can_approve_bcn
        or PermissionEngine.authorize(actor, "club.event.configure_rsvp")
        or can_manage_lead
    )
    is_active_member = actor.club_status == ClubMembershipStatus.ACTIVE

    if request.method == "POST":
        action = request.POST.get("action", "")
        try:
            if action == "submit_proposal":
                submit_club_event_for_approval(actor, club_event)
                messages.success(request, "Đã gửi tờ trình sự kiện lên cấp phê duyệt.")

            elif action == "review_event":
                approved = request.POST.get("decision") == "approve"
                auto_pub = request.POST.get("auto_publish") == "1"
                review_club_event(
                    actor=actor,
                    club_event=club_event,
                    approved=approved,
                    review_note=request.POST.get("review_note", ""),
                    auto_publish=auto_pub,
                )
                messages.success(
                    request,
                    "Đã phê duyệt kế hoạch sự kiện!"
                    if approved
                    else "Đã từ chối đề xuất sự kiện.",
                )

            elif action == "publish_event":
                publish_club_event(actor=actor, club_event=club_event)
                messages.success(
                    request,
                    "Đã ban hành sự kiện và khởi tạo danh sách RSVP thành viên CLB!",
                )

            elif action == "respond_rsvp":
                attending = request.POST.get("rsvp_choice") == "attending"
                att = respond_event_rsvp(
                    actor=actor,
                    club_event=club_event,
                    attending=attending,
                    decline_reason=request.POST.get("decline_reason", ""),
                )
                messages.success(
                    request,
                    f"Đã ghi nhận phản hồi RSVP của bạn: {att.get_rsvp_status_display()}.",
                )

            elif action == "review_exemption":
                att = get_object_or_404(
                    EventAttendance,
                    pk=request.POST.get("attendance_id"),
                    club_event=club_event,
                )
                exempted = request.POST.get("decision") == "exempt"
                review_rsvp_exemption(
                    actor=actor,
                    attendance=att,
                    exempted=exempted,
                    note=request.POST.get("note", ""),
                )
                messages.success(
                    request,
                    f"Đã cập nhật đơn xin vắng của {att.user.public_name}: {att.get_rsvp_status_display()}.",
                )

            elif action == "freeze_rsvp":
                cnt = freeze_event_rsvp(club_event, actor=actor)
                messages.info(
                    request,
                    f"Đã khoá sổ RSVP sự kiện ({cnt} thành viên chưa phản hồi được chuyển sang Mặc định tham gia).",
                )

            elif action == "checkin_member":
                att = get_object_or_404(
                    EventAttendance,
                    pk=request.POST.get("attendance_id"),
                    club_event=club_event,
                )
                record_member_event_checkin(
                    actor=actor,
                    attendance=att,
                    checkin_status=request.POST.get("checkin_status", CheckinStatus.PRESENT),
                )
                messages.success(
                    request,
                    f"Đã điểm danh {att.user.public_name}: {att.get_checkin_status_display()}.",
                )

            return redirect("operations:event_detail", pk=club_event.pk)
        except (GovernanceError, PermissionDenied) as exc:
            messages.error(request, str(exc))

    dept_roles = list(club_event.department_roles.select_related("department"))
    attendances = list(
        club_event.attendances.select_related("user", "exemption_reviewed_by", "checked_in_by")
    )
    my_attendance = next((a for a in attendances if a.user_id == actor.id), None)
    event_tasks = [
        t
        for t in club_event.event.club_tasks.select_related("department").prefetch_related(
            "assignees__user"
        )
        if can_view_club_task(actor, t)
    ]

    rsvp_summary = {
        "total": len(attendances),
        "confirmed": sum(
            1
            for a in attendances
            if a.rsvp_status in ("CONFIRMED_ATTENDING", "AUTO_COMMITTED")
        ),
        "pending": sum(1 for a in attendances if a.rsvp_status == "PENDING_RESPONSE"),
        "declined_pending": sum(
            1 for a in attendances if a.rsvp_status == "DECLINED_PENDING"
        ),
        "exempted": sum(
            1
            for a in attendances
            if a.rsvp_status in ("DECLINED_EXEMPTED", "EXEMPT_SUSPENDED")
        ),
    }

    return render(
        request,
        "operations/event_detail.html",
        {
            "club_event": club_event,
            "dept_roles": dept_roles,
            "attendances": attendances,
            "my_attendance": my_attendance,
            "event_tasks": event_tasks,
            "rsvp_summary": rsvp_summary,
            "can_manage_lead": can_manage_lead,
            "can_approve_this": can_approve_this,
            "can_manage_rsvp": can_manage_rsvp,
            "is_active_member": is_active_member,
            "checkin_choices": CheckinStatus.choices,
        },
    )


# ---------------------------------------------------------------------------
# 3. TRUNG TÂM CẢNH BÁO CHUYÊN CẦN & KHIẾU NẠI ĐỘC LẬP (`/workspace/ky-luat/`)
# ---------------------------------------------------------------------------
@club_member_required
def discipline_center(request):
    """
    Trung tâm Cảnh báo Chuyên cần Minh bạch (`> 3` lần vi phạm — Cấm tự khoá `R04`) & Khiếu nại Độc lập (`WF23–WF24`):
    - Thành viên xem cảnh báo của chính mình và gửi giải trình/khiếu nại.
    - Trưởng ban đề xuất xem xét thành viên trong Ban.
    - Chủ nhiệm / Phó CN Nhân sự xem xét thủ công hồ sơ `FLAGGED` và thụ lý độc lập `Appeal`.
    - Cố vấn chỉ xem ở chế độ `READ_ONLY` (0 nút chỉnh sửa — `INV-04`).
    """
    actor = request.user
    can_adjudicate = PermissionEngine.authorize(actor, "club.member.suspend_temporary")
    can_supervise = PermissionEngine.authorize(actor, "club.overview.supervise")
    all_depts = list(Department.objects.filter(is_active=True))
    proposable_depts = [
        d
        for d in all_depts
        if PermissionEngine.authorize(actor, "dept.evaluation.propose", department=d)
        or can_adjudicate
    ]

    if request.method == "POST":
        action = request.POST.get("action", "")
        try:
            if action == "propose_case":
                target = get_object_or_404(User, pk=request.POST.get("target_user_id"))
                dept_id = (request.POST.get("department_id") or "").strip()
                dept = Department.objects.filter(pk=dept_id).first() if dept_id.isdigit() else None
                case = propose_manual_discipline_case(
                    actor=actor,
                    target_user=target,
                    department=dept,
                    summary=request.POST.get("summary", ""),
                    evidence_note=request.POST.get("evidence_note", ""),
                )
                messages.success(
                    request,
                    f"Đã lập hồ sơ đề xuất xem xét #{case.pk} trình Ban Chủ nhiệm.",
                )

            elif action == "resolve_case":
                case = get_object_or_404(DisciplineCase, pk=request.POST.get("case_id"))
                resolve_discipline_case(
                    actor=actor,
                    case=case,
                    new_status=request.POST.get("new_status", ""),
                    resolution_note=request.POST.get("resolution_note", ""),
                )
                messages.success(
                    request,
                    f"Đã cập nhật kết luận xem xét hồ sơ #{case.pk}: {case.get_status_display()}.",
                )

            elif action == "submit_appeal":
                case_id = (request.POST.get("discipline_case_id") or "").strip()
                d_case = (
                    get_object_or_404(DisciplineCase, pk=case_id)
                    if case_id.isdigit()
                    else None
                )
                ap = submit_appeal(
                    appellant=actor,
                    target_type=AppealTargetType.DISCIPLINE_CASE,
                    discipline_case=d_case,
                    reason=request.POST.get("reason", ""),
                    evidence_url=request.POST.get("evidence_url", ""),
                )
                messages.success(
                    request,
                    f"Đã gửi đơn giải trình / khiếu nại #{ap.pk} thành công.",
                )

            elif action == "adjudicate_appeal":
                ap = get_object_or_404(Appeal, pk=request.POST.get("appeal_id"))
                adjudicate_appeal(
                    actor=actor,
                    appeal=ap,
                    decision_status=request.POST.get("decision_status", ""),
                    decision_note=request.POST.get("decision_note", ""),
                )
                messages.success(
                    request,
                    f"Đã ban hành phán quyết độc lập cho đơn khiếu nại #{ap.pk}.",
                )

            return redirect("operations:discipline_center")
        except (GovernanceError, PermissionDenied) as exc:
            messages.error(request, str(exc))

    my_cases = list(
        DisciplineCase.objects.select_related("department", "reviewed_by", "policy_version")
        .filter(target_user=actor)
        .order_by("-created_at")
    )
    my_appeals = list(
        Appeal.objects.select_related("discipline_case", "task_review", "decided_by")
        .filter(appellant=actor)
        .order_by("-created_at")
    )

    if can_adjudicate or can_supervise:
        managed_cases = list(
            DisciplineCase.objects.select_related(
                "target_user", "department", "created_by", "reviewed_by", "policy_version"
            ).order_by("-created_at")[:60]
        )
        managed_appeals = list(
            Appeal.objects.select_related(
                "appellant", "discipline_case", "task_review__task", "original_actor", "decided_by"
            ).order_by("-created_at")[:60]
        )
    elif proposable_depts:
        managed_cases = list(
            DisciplineCase.objects.select_related(
                "target_user", "department", "created_by", "reviewed_by"
            )
            .filter(department__in=proposable_depts)
            .order_by("-created_at")[:40]
        )
        managed_appeals = []
    else:
        managed_cases = []
        managed_appeals = []

    eligible_targets = (
        list(
            ClubMembership.objects.select_related("user")
            .filter(status=ClubMembershipStatus.ACTIVE)
            .exclude(user=actor)
            .order_by("member_code")
        )
        if proposable_depts
        else []
    )

    return render(
        request,
        "operations/discipline_center.html",
        {
            "my_cases": my_cases,
            "my_appeals": my_appeals,
            "managed_cases": managed_cases,
            "managed_appeals": managed_appeals,
            "proposable_depts": proposable_depts,
            "eligible_targets": eligible_targets,
            "can_adjudicate": can_adjudicate,
            "can_supervise": can_supervise,
            "resolution_choices": [
                (DisciplineStatus.UNDER_REVIEW, "Đang xác minh & lắng nghe giải trình"),
                (DisciplineStatus.EXEMPTED_DISMISSED, "Miễn trừ / Đóng hồ sơ không kỷ luật"),
                (DisciplineStatus.WARNING_ISSUED, "Nhắc nhở / Cảnh cáo chính thức"),
                (DisciplineStatus.SUSPENSION_APPLIED, "Ra quyết định tạm khoá tư cách thành viên"),
            ],
            "appeal_decision_choices": [
                (AppealStatus.UNDER_REVIEW, "Tiếp nhận thụ lý độc lập"),
                (AppealStatus.UPHELD, "Giữ nguyên quyết định ban đầu"),
                (AppealStatus.OVERTURNED, "Chấp nhận khiếu nại — Khôi phục / Huỷ quyết định cũ"),
            ],
        },
    )
