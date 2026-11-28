"""
Giao diện Web cho Không gian Nội bộ Nền tảng (`/workspace/`) — Phase 1 Core Foundation.

Bao gồm:
1. Không gian thành viên/cán bộ đa ban (`/workspace/`) — hiển thị thẻ chọn Ban (không tự ép vào 1 Ban),
   hồ sơ kỹ năng cá nhân, lịch sử vòng đời cá nhân.
2. Cổng ứng tuyển từ Guest lên Thành viên CLB (`/workspace/ung-tuyen/`).
3. Trang Ban chuyên trách (`/workspace/ban/<slug>/`) — tự động chuyển giữa `MANAGE`, `MEMBER`
   và `READ_ONLY` (khi xem chéo ban hoặc Cố vấn ghé xem).
4. Trung tâm Quản trị Tổ chức & Phân quyền (`/workspace/quan-tri/`).
5. Cổng Giám sát Độc lập cho Cố vấn (`/workspace/giam-sat/`).
6. Sổ cái Lịch sử Thành viên Bất biến (`/workspace/thanh-vien/<id>/lich-su/`).
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import User
from accounts.services import resolve_post_login_url

from .forms import MembershipApplicationForm, UserSkillDeclareForm
from .models import (
    ApplicationStatus,
    Appointment,
    ClubMembership,
    ClubMembershipStatus,
    Department,
    DepartmentMembership,
    DeptMembershipStatus,
    GrantBundleCode,
    MemberLifecycleEvent,
    MembershipApplication,
    PermissionGrant,
    PolicyVersion,
    Position,
    PositionCode,
    ResourceAccessRule,
    UserSkill,
    serialize_member_contact_for_viewer,
)
from .permissions import (
    DEPUTY_HEAD_BUNDLE_PERMISSIONS,
    PermissionEngine,
    VICE_CHAIRMAN_PORTFOLIO_PERMISSIONS,
    club_member_required,
)
from .services import (
    GovernanceError,
    add_member_to_department,
    appoint_officer,
    approve_club_member,
    declare_user_skill,
    end_appointment,
    grant_delegated_permissions,
    restore_club_member,
    revoke_permission_grant,
    screen_membership_application,
    submit_membership_application,
    suspend_club_member,
    transfer_member_department,
    verify_user_skill,
)


@club_member_required
def workspace_home(request):
    """
    Không gian làm việc trung tâm của Thành viên & Cán bộ KMG.
    - Nếu là Cố vấn thuần túy (không có thẻ thành viên ACTIVE và không giữ chức điều hành),
      chuyển thẳng sang Cổng Giám sát `/workspace/giam-sat/`.
    - Nếu thuộc >= 2 Ban: hiển thị toàn bộ danh sách Ban để thành viên tự chọn ngữ cảnh làm việc.
    """
    actor = request.user
    ctx = PermissionEngine.summarize_actor_context(actor)
    if ctx["is_advisor"] and not ctx["departments"] and not ctx["can_access_club_governance"]:
        return redirect("organization:advisor_overview")

    all_depts = list(
        Department.objects.filter(is_active=True).annotate(
            active_member_count=Count(
                "memberships",
                filter=Q(memberships__status=DeptMembershipStatus.ACTIVE),
            )
        )
    )
    my_dept_mode_map = {d["id"]: d["access_mode"] for d in ctx["departments"]}
    my_dept_ids = set(my_dept_mode_map.keys())
    dept_appt_ids = {
        a["department_id"]
        for a in ctx["appointments"]
        if a["scope_type"] == "DEPARTMENT" and a["department_id"]
    }
    my_depts = []
    other_depts = []
    for dept in all_depts:
        if dept.id in my_dept_mode_map:
            mode = my_dept_mode_map[dept.id]
        elif ctx["club_status"] == ClubMembershipStatus.SUSPENDED:
            mode = "DENIED"
        elif ctx["is_server_admin"] or ctx["is_chairman"]:
            mode = "MANAGE"
        elif ctx["is_vice_chairman"] or dept.id in dept_appt_ids:
            mode = PermissionEngine.get_department_access_mode(actor, dept)
        elif (
            ctx["club_status"] == ClubMembershipStatus.ACTIVE and my_dept_ids
        ) or ctx["appointments"]:
            mode = "READ_ONLY"
        else:
            mode = "DENIED"
        item = {
            "dept": dept,
            "access_mode": mode,
            "member_count": dept.active_member_count,
        }
        if dept.id in my_dept_ids or mode == "MANAGE":
            my_depts.append(item)
        else:
            other_depts.append(item)

    skill_form = UserSkillDeclareForm(request.POST or None)
    if request.method == "POST" and request.POST.get("action") == "declare_skill":
        if not ctx["departments"] and not ctx["is_chairman"]:
            raise PermissionDenied("Chức năng khai báo kỹ năng dành cho thành viên CLB.")
        if skill_form.is_valid():
            us = declare_user_skill(
                user=actor,
                skill=skill_form.cleaned_data["skill"],
                proficiency=skill_form.cleaned_data["proficiency"],
                experience_note=skill_form.cleaned_data["experience_note"],
                evidence_url=skill_form.cleaned_data["evidence_url"],
            )
            messages.success(
                request,
                f"Đã lưu kỹ năng '{us.skill.name}' (trạng thái: Chờ Ban xác minh).",
            )
            return redirect("organization:workspace_home")

    my_skills = list(actor.user_skills.select_related("skill__category", "verified_by"))
    my_lifecycle = list(actor.lifecycle_events.select_related("department", "actor")[:8])

    # Phase 2 — Bảng điều khiển vận hành cá nhân: KPI công việc, RSVP chờ phản hồi, thông báo chính thức
    from operations.models import (
        ClubAnnouncement,
        ClubEventApprovalStatus,
        ClubTask,
        DisciplineCase,
        DisciplineStatus,
        EventAttendance,
        RsvpStatus,
        TaskWorkflowStatus,
    )

    open_my_tasks = list(
        ClubTask.objects.select_related("department")
        .filter(assignees__user=actor, assignees__is_active=True)
        .exclude(
            workflow_status__in=[
                TaskWorkflowStatus.APPROVED,
                TaskWorkflowStatus.REJECTED,
                TaskWorkflowStatus.CANCELLED,
            ]
        )
        .distinct()
        .order_by("deadline")[:8]
    )
    task_kpis = {
        "open": len(open_my_tasks),
        "overdue": sum(1 for t in open_my_tasks if t.is_overdue),
        "revision": sum(
            1 for t in open_my_tasks if t.workflow_status == TaskWorkflowStatus.REVISION_REQUESTED
        ),
        "approved_total": ClubTask.objects.filter(
            assignees__user=actor, workflow_status=TaskWorkflowStatus.APPROVED
        )
        .distinct()
        .count(),
    }
    pending_rsvps = list(
        EventAttendance.objects.select_related("club_event__event")
        .filter(
            user=actor,
            rsvp_status=RsvpStatus.PENDING_RESPONSE,
            club_event__approval_status=ClubEventApprovalStatus.PUBLISHED,
        )
        .order_by("club_event__event__starts_at")[:5]
    )
    my_dept_id_list = list(my_dept_ids)
    announcements = list(
        ClubAnnouncement.objects.select_related("department", "published_by")
        .filter(Q(department__isnull=True) | Q(department_id__in=my_dept_id_list))
        .order_by("-is_pinned", "-created_at")[:5]
    )
    open_discipline_cases = DisciplineCase.objects.filter(
        target_user=actor,
        status__in=[DisciplineStatus.FLAGGED, DisciplineStatus.UNDER_REVIEW],
    ).count()

    # Phase 3 — Đào tạo, Lịch tập Band, Đề xuất & Kho Tài liệu Mật
    from datetime import timedelta
    from programs.models import (
        PracticeParticipant,
        PracticeSessionStatus,
        TrainingEnrollment,
        TrainingEnrollmentStatus,
    )
    from programs.services import filter_accessible_documents

    upcoming_window = timezone.now() - timedelta(hours=2)
    my_enrollments = list(
        TrainingEnrollment.objects.select_related("course__department")
        .filter(
            user=actor,
            status__in=[TrainingEnrollmentStatus.ENROLLED, TrainingEnrollmentStatus.WAITLIST],
            course__starts_at__gte=upcoming_window,
        )
        .order_by("course__starts_at")[:4]
    )
    my_practices = list(
        PracticeParticipant.objects.select_related("session__department")
        .filter(
            user=actor,
            session__status=PracticeSessionStatus.SCHEDULED,
            session__starts_at__gte=upcoming_window,
        )
        .order_by("session__starts_at")[:4]
    )
    accessible_docs_count = len(filter_accessible_documents(actor))

    # Phase 4 — Mạng xã hội Nội bộ, Nhắn tin Bảo mật & Playlist Âm nhạc
    from social.models import ConversationMember, MusicPlaylist, MusicShare
    from social.services import list_visible_posts

    recent_social_posts = list_visible_posts(actor, scope="ALL", limit=3)
    active_chat_count = ConversationMember.objects.filter(
        user=actor, left_at__isnull=True
    ).count()
    my_playlist_count = MusicPlaylist.objects.filter(owner=actor).count()
    received_music_gifts_count = MusicShare.objects.filter(
        recipient=actor, is_saved_to_playlist=False
    ).count()

    # Phase 5 — Quỹ & Đánh giá cá nhân
    from evaluations.models import MemberEvaluation
    from finance.models import MemberContribution

    my_contributions_count = MemberContribution.objects.filter(member=actor).count()
    my_evaluations_count = MemberEvaluation.objects.filter(member=actor, status="CONFIRMED").count()

    return render(
        request,
        "organization/workspace_home.html",
        {
            "actor_ctx": ctx,
            "my_depts": my_depts,
            "other_depts": other_depts,
            "my_skills": my_skills,
            "skill_form": skill_form,
            "my_lifecycle": my_lifecycle,
            "open_my_tasks": open_my_tasks,
            "task_kpis": task_kpis,
            "pending_rsvps": pending_rsvps,
            "announcements": announcements,
            "open_discipline_cases": open_discipline_cases,
            "my_enrollments": my_enrollments,
            "my_practices": my_practices,
            "accessible_docs_count": accessible_docs_count,
            "recent_social_posts": recent_social_posts,
            "active_chat_count": active_chat_count,
            "my_playlist_count": my_playlist_count,
            "received_music_gifts_count": received_music_gifts_count,
            "my_contributions_count": my_contributions_count,
            "my_evaluations_count": my_evaluations_count,
        },
    )


@login_required
def apply_membership(request):
    """Trang dành cho tài khoản Guest nộp đơn xin gia nhập CLB KMG (`WF01`)."""
    if request.user.club_status == ClubMembershipStatus.ACTIVE:
        messages.info(request, "Bạn đã là thành viên chính thức của CLB KMG.")
        return redirect("organization:workspace_home")

    existing_apps = list(
        request.user.membership_applications.select_related(
            "primary_department", "secondary_department", "screened_by", "reviewed_by"
        )
    )
    has_pending = any(
        a.status in (ApplicationStatus.SUBMITTED, ApplicationStatus.DEPT_SCREENED)
        for a in existing_apps
    )
    form = MembershipApplicationForm(request.POST or None)
    if request.method == "POST" and not has_pending and form.is_valid():
        try:
            submit_membership_application(
                user=request.user,
                primary_department=form.cleaned_data["primary_department"],
                secondary_department=form.cleaned_data["secondary_department"],
                declared_skills_text=form.cleaned_data["declared_skills_text"],
                portfolio_url=form.cleaned_data["portfolio_url"],
                motivation=form.cleaned_data["motivation"],
            )
            messages.success(
                request,
                "Đã gửi đơn ứng tuyển gia nhập CLB KMG! Ban chuyên môn sẽ sơ duyệt hồ sơ của bạn.",
            )
            return redirect("organization:apply_membership")
        except GovernanceError as exc:
            messages.error(request, str(exc))

    return render(
        request,
        "organization/apply_membership.html",
        {
            "form": form,
            "existing_apps": existing_apps,
            "has_pending": has_pending,
        },
    )


@club_member_required
def department_detail(request, slug: str):
    """
    Trang không gian của từng Ban (`/workspace/ban/<slug>/`).
    - Tự động hiển thị và khóa quyền theo `access_mode` (`MANAGE` | `MEMBER` | `READ_ONLY`).
    - Khi ở chế độ `READ_ONLY` chéo ban: chỉ xem thông tin chung, nhân sự (ẩn PII riêng tư),
      tiến độ tổng hợp; ẩn toàn bộ thao tác quản trị & tài liệu mật.
    """
    dept = get_object_or_404(Department, slug=slug, is_active=True)
    PermissionEngine.require(request.user, "dept.page.view", department=dept)
    access_mode = PermissionEngine.get_department_access_mode(request.user, dept)

    can_manage_members = PermissionEngine.authorize(
        request.user, "dept.member.manage", department=dept
    )
    can_screen_apps = PermissionEngine.authorize(
        request.user, "dept.member.screen", department=dept
    )
    can_verify_skills = PermissionEngine.authorize(
        request.user, "dept.skill.verify", department=dept
    )
    can_appoint_deputy = PermissionEngine.authorize(
        request.user, "dept.deputy.appoint", department=dept
    )
    can_delegate = PermissionEngine.authorize(
        request.user, "dept.permission.delegate", department=dept
    )
    can_assign_tasks = PermissionEngine.authorize(
        request.user, "dept.task.assign", department=dept
    )

    now = timezone.now()
    officers = list(
        Appointment.objects.select_related("user", "position")
        .prefetch_related("permission_grants")
        .filter(department=dept, is_active=True, ended_at__isnull=True)
        .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=now))
        .order_by("position__rank_order", "started_at")
    )

    raw_memberships = list(
        DepartmentMembership.objects.select_related(
            "user", "user__profile", "user__club_membership"
        )
        .prefetch_related("user__user_skills__skill")
        .filter(department=dept, status=DeptMembershipStatus.ACTIVE)
        .order_by("user__full_name", "user__username")
    )
    roster = []
    for dm in raw_memberships:
        contact = serialize_member_contact_for_viewer(
            request.user, dm.user, can_manage_target=can_manage_members
        )
        roster.append(
            {
                "membership": dm,
                "user": dm.user,
                "contact": contact,
                "verified_skills": [
                    us
                    for us in dm.user.user_skills.all()
                    if us.verification_status == "VERIFIED"
                ],
            }
        )

    pending_skills = []
    if can_verify_skills:
        member_ids = [dm.user_id for dm in raw_memberships]
        pending_skills = list(
            UserSkill.objects.select_related("user", "skill__category")
            .filter(user_id__in=member_ids, verification_status="SELF_DECLARED")
            .order_by("-created_at")
        )

    pending_applications = []
    if can_screen_apps:
        pending_applications = list(
            MembershipApplication.objects.select_related("user")
            .filter(primary_department=dept, status=ApplicationStatus.SUBMITTED)
            .order_by("created_at")
        )

    # Danh sách tài nguyên / tài liệu mẫu của Ban để minh họa Resource ACL (`Skill != Permission`)
    resources = []
    for rule in dept.resource_rules.select_related("recommended_skill").all():
        resources.append(
            {
                "rule": rule,
                "can_access": PermissionEngine.can_access_resource(request.user, rule),
            }
        )

    deputy_bundle_choices = [
        (code, GrantBundleCode(code).label)
        for code in DEPUTY_HEAD_BUNDLE_PERMISSIONS.keys()
    ]
    active_deputies = [a for a in officers if a.position.code == PositionCode.DEPUTY_HEAD]

    # Phase 2 — Tiến độ công việc & sự kiện của Ban (khoá cứng READ_ONLY chéo Ban)
    from operations.models import (
        ClubEventApprovalStatus,
        ClubEventProfile,
        ClubTask,
        TaskWorkflowStatus,
    )

    finalized_statuses = [
        TaskWorkflowStatus.APPROVED,
        TaskWorkflowStatus.REJECTED,
        TaskWorkflowStatus.CANCELLED,
    ]
    dept_tasks_qs = ClubTask.objects.filter(department=dept)
    total_tasks = dept_tasks_qs.count()
    approved_tasks = dept_tasks_qs.filter(workflow_status=TaskWorkflowStatus.APPROVED).count()
    open_tasks = dept_tasks_qs.exclude(workflow_status__in=finalized_statuses).count()
    overdue_tasks = (
        dept_tasks_qs.exclude(workflow_status__in=finalized_statuses)
        .filter(deadline__lt=now)
        .count()
    )
    reassignment_tasks = dept_tasks_qs.filter(reassignment_needed=True).count()
    dept_task_stats = {
        "total": total_tasks,
        "approved": approved_tasks,
        "open": open_tasks,
        "overdue": overdue_tasks,
        "reassignment": reassignment_tasks,
        "completion_rate": round((approved_tasks / total_tasks) * 100) if total_tasks else 0,
    }

    can_view_all_tasks = PermissionEngine.authorize(
        request.user, "dept.task.view_all", department=dept
    ) or PermissionEngine.authorize(request.user, "club.dept.supervise_ops")
    can_view_personal_tasks = PermissionEngine.authorize(
        request.user, "dept.task.view_personal_self", department=dept
    )
    if can_view_all_tasks:
        task_scope_mode = "DEPT_ALL"
        dept_tasks = list(
            dept_tasks_qs.select_related("recommended_skill")
            .prefetch_related("assignees__user")
            .exclude(workflow_status=TaskWorkflowStatus.CANCELLED)
            .order_by("deadline")[:8]
        )
    elif can_view_personal_tasks:
        task_scope_mode = "PERSONAL_SELF"
        dept_tasks = list(
            dept_tasks_qs.select_related("recommended_skill")
            .prefetch_related("assignees__user")
            .filter(assignees__user=request.user, assignees__is_active=True)
            .exclude(workflow_status=TaskWorkflowStatus.CANCELLED)
            .distinct()
            .order_by("deadline")[:8]
        )
    else:
        task_scope_mode = "AGGREGATE_ONLY"
        dept_tasks = []

    dept_events_qs = (
        ClubEventProfile.objects.select_related("event", "lead_department")
        .filter(Q(lead_department=dept) | Q(department_roles__department=dept))
        .distinct()
    )
    can_manage_dept_events = PermissionEngine.authorize(
        request.user, "dept.event.manage_internal", department=dept
    ) or PermissionEngine.authorize(request.user, "club.event.approve")
    if not (access_mode == "MANAGE" or can_manage_dept_events):
        dept_events_qs = dept_events_qs.filter(
            approval_status__in=[
                ClubEventApprovalStatus.PUBLISHED,
                ClubEventApprovalStatus.ONGOING,
                ClubEventApprovalStatus.COMPLETED,
            ]
        )
    dept_events = list(dept_events_qs.order_by("-event__starts_at")[:6])

    # Phase 3 — Cổng Ban Chuyên biệt (Showcase, Đào tạo, Lịch tập, Đề xuất & Kho Tài liệu Mật)
    from programs.models import (
        DepartmentProposal,
        DepartmentShowcaseItem,
        PracticeSession,
        ShowcaseItemType,
        TrainingCourse,
    )
    from programs.services import (
        _is_pure_advisor,
        can_access_document,
        can_view_proposal,
        filter_accessible_documents,
    )

    is_advisor_actor = _is_pure_advisor(request.user)
    showcase_raw = list(
        DepartmentShowcaseItem.objects.select_related("linked_document", "created_by").filter(
            department=dept
        )
    )
    showcase_entries = [
        {
            "item": sc,
            "can_access_doc": (
                sc.linked_document_id is not None
                and can_access_document(request.user, sc.linked_document)
            ),
        }
        for sc in showcase_raw
    ]
    can_add_showcase = (not is_advisor_actor) and (
        PermissionEngine.authorize(request.user, "dept.event.manage_internal", department=dept)
        or PermissionEngine.authorize(request.user, "dept.training.manage", department=dept)
        or PermissionEngine.authorize(request.user, "dept.document.manage", department=dept)
        or PermissionEngine.authorize(request.user, "club.dept.supervise_ops")
    )
    dept_courses = list(
        TrainingCourse.objects.select_related("instructor", "target_skill")
        .prefetch_related("enrollments")
        .filter(department=dept)[:8]
    )
    dept_practices_qs = PracticeSession.objects.select_related(
        "lead_coordinator", "club_event__event"
    ).prefetch_related("participants__user").filter(department=dept)
    dept_practices_count = dept_practices_qs.count()
    dept_practices = [] if access_mode == "READ_ONLY" else list(dept_practices_qs[:8])
    dept_proposals = [
        p
        for p in DepartmentProposal.objects.select_related("proposer", "department").filter(
            department=dept
        )
        if can_view_proposal(request.user, p)
    ][:8]
    dept_vault_docs = filter_accessible_documents(request.user, department=dept)[:10]
    active_tab = (request.GET.get("tab") or "overview").strip()
    if active_tab not in ("overview", "ops", "specialty", "training", "proposals", "vault"):
        active_tab = "overview"

    return render(
        request,
        "organization/department_detail.html",
        {
            "dept": dept,
            "access_mode": access_mode,
            "active_tab": active_tab,
            "officers": officers,
            "active_deputies": active_deputies,
            "roster": roster,
            "pending_skills": pending_skills,
            "pending_applications": pending_applications,
            "resources": resources,
            "deputy_bundle_choices": deputy_bundle_choices,
            "dept_task_stats": dept_task_stats,
            "dept_tasks": dept_tasks,
            "task_scope_mode": task_scope_mode,
            "dept_events": dept_events,
            "showcase_entries": showcase_entries,
            "showcase_types": ShowcaseItemType.choices,
            "can_add_showcase": can_add_showcase,
            "dept_courses": dept_courses,
            "dept_practices": dept_practices,
            "dept_practices_count": dept_practices_count,
            "dept_proposals": dept_proposals,
            "dept_vault_docs": dept_vault_docs,
            "perms": {
                "can_manage_members": can_manage_members,
                "can_screen_apps": can_screen_apps,
                "can_verify_skills": can_verify_skills,
                "can_appoint_deputy": can_appoint_deputy,
                "can_delegate": can_delegate,
                "can_assign_tasks": can_assign_tasks,
                "can_manage_dept_events": can_manage_dept_events,
            },
        },
    )


@require_POST
@club_member_required
def department_verify_skill_view(request, slug: str, pk: int):
    dept = get_object_or_404(Department, slug=slug, is_active=True)
    us = get_object_or_404(UserSkill.objects.select_related("user", "skill"), pk=pk)
    approved = request.POST.get("decision") != "reject"
    note = request.POST.get("review_note", "")
    try:
        verify_user_skill(
            actor=request.user,
            user_skill=us,
            department=dept,
            approved=approved,
            review_note=note,
        )
        messages.success(
            request,
            f"Đã {'xác minh' if approved else 'từ chối'} kỹ năng {us.skill.name} của {us.user.public_name}.",
        )
    except GovernanceError as exc:
        messages.error(request, str(exc))
    return redirect("organization:department_detail", slug=dept.slug)


@require_POST
@club_member_required
def department_screen_application_view(request, slug: str, pk: int):
    dept = get_object_or_404(Department, slug=slug, is_active=True)
    app = get_object_or_404(
        MembershipApplication.objects.select_related("user", "primary_department"),
        pk=pk,
        primary_department=dept,
    )
    try:
        screen_membership_application(
            actor=request.user,
            application=app,
            note=request.POST.get("screening_note", "Đạt sơ duyệt chuyên môn Ban"),
        )
        messages.success(
            request,
            f"Đã sơ duyệt hồ sơ của {app.user.public_name} và chuyển lên Ban Chủ nhiệm.",
        )
    except GovernanceError as exc:
        messages.error(request, str(exc))
    return redirect("organization:department_detail", slug=dept.slug)


@require_POST
@club_member_required
def department_appoint_deputy_view(request, slug: str):
    dept = get_object_or_404(Department, slug=slug, is_active=True)
    target = get_object_or_404(User, pk=request.POST.get("user_id"))
    pos = get_object_or_404(Position, code=PositionCode.DEPUTY_HEAD)
    try:
        appoint_officer(
            actor=request.user,
            target_user=target,
            position=pos,
            department=dept,
            term_label=request.POST.get("term_label", "2026-2027"),
            title_note=request.POST.get("title_note", ""),
        )
        messages.success(
            request, f"Đã bổ nhiệm {target.public_name} giữ chức Phó ban {dept.name}."
        )
    except GovernanceError as exc:
        messages.error(request, str(exc))
    return redirect("organization:department_detail", slug=dept.slug)


@require_POST
@club_member_required
def department_grant_bundle_view(request, slug: str):
    dept = get_object_or_404(Department, slug=slug, is_active=True)
    appt = get_object_or_404(
        Appointment.objects.select_related("position", "department", "user"),
        pk=request.POST.get("appointment_id"),
        department=dept,
    )
    bundle_code = request.POST.get("bundle_code", "")
    reason = request.POST.get("reason", "Ủy quyền điều hành trong Ban")
    try:
        grant = grant_delegated_permissions(
            actor=request.user,
            bound_appointment=appt,
            bundle_code=bundle_code,
            department=dept,
            reason=reason,
        )
        messages.success(
            request,
            f"Đã cấp '{grant.get_bundle_code_display()}' cho {appt.user.public_name}.",
        )
    except GovernanceError as exc:
        messages.error(request, str(exc))
    return redirect("organization:department_detail", slug=dept.slug)


@club_member_required
def governance_center(request):
    """
    Trung tâm Quản trị Tổ chức & Phân quyền cấp CLB (`/workspace/quan-tri/`).
    Chỉ Chủ nhiệm và Phó chủ nhiệm có mảng phụ trách phù hợp mới truy cập được;
    mọi thao tác POST đều kiểm tra lại từng mã quyền nguyên tử ở Backend!
    """
    actor = request.user
    ctx = PermissionEngine.summarize_actor_context(actor)
    if not ctx["can_access_club_governance"]:
        raise PermissionDenied("Bạn không có quyền truy cập Trung tâm Quản trị cấp CLB.")

    if request.method == "POST":
        action = request.POST.get("action", "")
        try:
            if action == "approve_application":
                app = get_object_or_404(
                    MembershipApplication.objects.select_related(
                        "user", "primary_department", "secondary_department"
                    ),
                    pk=request.POST.get("application_id"),
                )
                depts = [app.primary_department]
                if app.secondary_department and request.POST.get("include_secondary") == "1":
                    depts.append(app.secondary_department)
                cm = approve_club_member(
                    actor=actor,
                    target_user=app.user,
                    departments=depts,
                    application=app,
                    note=request.POST.get("decision_note", "Chào mừng gia nhập KMG!"),
                )
                messages.success(
                    request,
                    f"Đã duyệt {app.user.public_name} vào CLB với mã {cm.member_code}!",
                )

            elif action == "promote_guest_member":
                target = get_object_or_404(User, pk=request.POST.get("user_id"))
                dept_ids = request.POST.getlist("department_ids")
                if not dept_ids and request.POST.get("department_id"):
                    dept_ids = [request.POST.get("department_id")]
                selected_depts = list(
                    Department.objects.filter(pk__in=dept_ids, is_active=True)
                )
                cm = approve_club_member(
                    actor=actor,
                    target_user=target,
                    departments=selected_depts,
                    note=request.POST.get(
                        "note", "Ban Chủ nhiệm nâng role từ Khách lên Thành viên & phân Ban"
                    ),
                )
                messages.success(
                    request,
                    f"Đã nâng tài khoản {target.public_name} từ Khách lên Thành viên chính thức ({cm.member_code}) "
                    f"và phân vào {', '.join(d.name for d in selected_depts)}!",
                )

            elif action == "add_dept_member":
                target = get_object_or_404(User, pk=request.POST.get("user_id"))
                dept = get_object_or_404(Department, pk=request.POST.get("department_id"))
                add_member_to_department(
                    actor=actor,
                    target_user=target,
                    department=dept,
                    note=request.POST.get("note", "Bổ sung sinh hoạt đa ban"),
                )
                messages.success(
                    request, f"Đã thêm {target.public_name} vào {dept.name}."
                )

            elif action == "transfer_dept":
                target = get_object_or_404(User, pk=request.POST.get("user_id"))
                from_dept = get_object_or_404(Department, pk=request.POST.get("from_department_id"))
                to_dept = get_object_or_404(Department, pk=request.POST.get("to_department_id"))
                transfer_member_department(
                    actor=actor,
                    target_user=target,
                    from_department=from_dept,
                    to_department=to_dept,
                    note=request.POST.get("note", ""),
                )
                messages.success(
                    request,
                    f"Đã chuyển {target.public_name} từ {from_dept.name} sang {to_dept.name}.",
                )

            elif action == "appoint_officer":
                target = get_object_or_404(User, pk=request.POST.get("user_id"))
                pos = get_object_or_404(Position, code=request.POST.get("position_code"))
                dept_id = request.POST.get("department_id")
                dept = Department.objects.filter(pk=dept_id).first() if dept_id else None
                appoint_officer(
                    actor=actor,
                    target_user=target,
                    position=pos,
                    department=dept,
                    term_label=request.POST.get("term_label", "2026-2027"),
                    title_note=request.POST.get("title_note", ""),
                )
                messages.success(
                    request, f"Đã bổ nhiệm {target.public_name} giữ chức {pos.name}."
                )

            elif action == "end_appointment":
                appt = get_object_or_404(
                    Appointment.objects.select_related("user", "position", "department"),
                    pk=request.POST.get("appointment_id"),
                )
                end_appointment(
                    actor=actor,
                    appointment=appt,
                    reason=request.POST.get("reason", "Kết thúc nhiệm kỳ"),
                )
                messages.success(
                    request,
                    f"Đã kết thúc nhiệm kỳ {appt.position.name} của {appt.user.public_name} và thu hồi quyền tức thời.",
                )

            elif action == "grant_portfolio":
                appt = get_object_or_404(
                    Appointment.objects.select_related("user", "position", "department"),
                    pk=request.POST.get("appointment_id"),
                )
                grant = grant_delegated_permissions(
                    actor=actor,
                    bound_appointment=appt,
                    bundle_code=request.POST.get("bundle_code", ""),
                    department=appt.department,
                    reason=request.POST.get("reason", "Phân công mảng phụ trách BCN"),
                )
                messages.success(
                    request,
                    f"Đã cấp '{grant.get_bundle_code_display()}' cho {appt.user.public_name}.",
                )

            elif action == "revoke_grant":
                grant = get_object_or_404(
                    PermissionGrant.objects.select_related(
                        "grantee", "bound_appointment__position", "department"
                    ),
                    pk=request.POST.get("grant_id"),
                )
                revoke_permission_grant(
                    actor=actor,
                    grant=grant,
                    reason=request.POST.get("reason", "Thu hồi phân công"),
                )
                messages.success(
                    request,
                    f"Đã thu hồi '{grant.get_bundle_code_display()}' của {grant.grantee.public_name}.",
                )

            elif action == "suspend_member":
                target = get_object_or_404(User, pk=request.POST.get("user_id"))
                suspend_club_member(
                    actor=actor,
                    target_user=target,
                    reason=request.POST.get("reason", ""),
                )
                messages.warning(
                    request, f"Đã tạm khoá tư cách thành viên CLB của {target.public_name}."
                )

            elif action == "restore_member":
                target = get_object_or_404(User, pk=request.POST.get("user_id"))
                restore_club_member(
                    actor=actor,
                    target_user=target,
                    reason=request.POST.get("reason", "Khôi phục hoạt động"),
                )
                messages.success(
                    request, f"Đã khôi phục tư cách thành viên CLB cho {target.public_name}."
                )

            elif action == "broadcast_announcement":
                from operations.services import broadcast_announcement

                dept_id = (request.POST.get("department_id") or "").strip()
                dept = (
                    Department.objects.filter(pk=dept_id, is_active=True).first()
                    if dept_id.isdigit()
                    else None
                )
                ann = broadcast_announcement(
                    actor=actor,
                    title=request.POST.get("title", ""),
                    content=request.POST.get("content", ""),
                    department=dept,
                    is_pinned=request.POST.get("is_pinned") == "1",
                    send_email=request.POST.get("send_email") == "1",
                )
                messages.success(
                    request,
                    f"Đã phát thông báo '{ann.title}' tới {ann.recipient_count} thành viên.",
                )

            return redirect("organization:governance_center")
        except (GovernanceError, PermissionDenied) as exc:
            messages.error(request, str(exc))

    departments = list(Department.objects.filter(is_active=True))
    positions = list(Position.objects.all())
    deputy_positions = [
        p
        for p in positions
        if p.code in (PositionCode.DEPUTY_HEAD, PositionCode.CORE_MEMBER)
    ]
    pending_apps = list(
        MembershipApplication.objects.select_related(
            "user", "primary_department", "secondary_department", "screened_by"
        )
        .filter(status__in=[ApplicationStatus.SUBMITTED, ApplicationStatus.DEPT_SCREENED])
        .order_by("-status", "created_at")
    )
    guest_users = list(
        User.objects.filter(is_locked=False, is_superuser=False)
        .exclude(role="ADMIN")
        .exclude(
            club_membership__status__in=[
                ClubMembershipStatus.ACTIVE,
                ClubMembershipStatus.SUSPENDED,
            ]
        )
        .exclude(
            appointments__is_active=True,
            appointments__ended_at__isnull=True,
        )
        .distinct()
        .order_by("-created_at")[:100]
    )
    club_members = list(
        ClubMembership.objects.select_related("user")
        .prefetch_related("user__department_memberships__department")
        .order_by("member_code")
    )
    active_appointments = list(
        Appointment.objects.select_related("user", "position", "department")
        .filter(is_active=True, ended_at__isnull=True)
        .order_by("position__rank_order", "department__display_order")
    )
    historical_appointments = list(
        Appointment.objects.select_related("user", "position", "department")
        .filter(Q(is_active=False) | Q(ended_at__isnull=False))
        .order_by("-ended_at")[:15]
    )
    active_grants = list(
        PermissionGrant.objects.select_related(
            "grantee", "bound_appointment__position", "department", "granted_by"
        ).filter(is_active=True, revoked_at__isnull=True)
    )
    delegable_appointments = [
        a
        for a in active_appointments
        if a.position.code in (PositionCode.VICE_CHAIRMAN, PositionCode.DEPUTY_HEAD)
    ]
    bundle_choices = [
        (code, GrantBundleCode(code).label)
        for code in (
            list(VICE_CHAIRMAN_PORTFOLIO_PERMISSIONS.keys())
            + list(DEPUTY_HEAD_BUNDLE_PERMISSIONS.keys())
        )
    ]
    policies = list(PolicyVersion.objects.filter(is_current=True))

    from operations.models import (
        Appeal,
        AppealStatus,
        ClubAnnouncement,
        ClubEventApprovalStatus,
        ClubEventProfile,
        ClubTask,
        DisciplineCase,
        DisciplineStatus,
    )

    ops_summary = {
        "pending_events": ClubEventProfile.objects.filter(
            approval_status=ClubEventApprovalStatus.SUBMITTED
        ).count(),
        "flagged_cases": DisciplineCase.objects.filter(
            status__in=[DisciplineStatus.FLAGGED, DisciplineStatus.UNDER_REVIEW]
        ).count(),
        "open_appeals": Appeal.objects.filter(
            status__in=[AppealStatus.SUBMITTED, AppealStatus.UNDER_REVIEW]
        ).count(),
        "reassignment_tasks": ClubTask.objects.filter(reassignment_needed=True).count(),
    }
    recent_announcements = list(
        ClubAnnouncement.objects.select_related("department", "published_by")[:5]
    )
    can_publish_club_announcement = PermissionEngine.authorize(actor, "club.announcement.publish")
    announce_depts = [
        d
        for d in departments
        if can_publish_club_announcement
        or PermissionEngine.authorize(actor, "dept.event.manage_internal", department=d)
    ]

    return render(
        request,
        "organization/governance_center.html",
        {
            "actor_ctx": ctx,
            "ops_summary": ops_summary,
            "recent_announcements": recent_announcements,
            "can_publish_club_announcement": can_publish_club_announcement,
            "announce_depts": announce_depts,
            "departments": departments,
            "positions": positions,
            "deputy_positions": deputy_positions,
            "pending_apps": pending_apps,
            "guest_users": guest_users,
            "club_members": club_members,
            "active_appointments": active_appointments,
            "historical_appointments": historical_appointments,
            "active_grants": active_grants,
            "delegable_appointments": delegable_appointments,
            "bundle_choices": bundle_choices,
            "policies": policies,
            "can_appoint_head": PermissionEngine.authorize(actor, "server.leadership.manage"),
            "can_appoint_deputy_club": PermissionEngine.authorize(actor, "club.officer.appoint_deputy"),
            "can_approve_member": PermissionEngine.authorize(actor, "club.member.approve"),
            "can_delegate_club": PermissionEngine.authorize(actor, "club.permission.delegate"),
            "can_suspend_member": PermissionEngine.authorize(actor, "club.member.suspend_temporary"),
        },
    )


@club_member_required
def advisor_overview(request):
    """
    Cổng Giám sát Tổng quan Độc lập (Hard Read-Only — `INV-04`) dành cho Cố vấn & Ban Chủ nhiệm.
    Tuyệt đối không chứa bất kỳ form chỉnh sửa/phê duyệt nào.
    """
    PermissionEngine.require(request.user, "club.overview.supervise")

    departments = list(
        Department.objects.filter(is_active=True).annotate(
            active_members_count=Count(
                "memberships",
                filter=Q(memberships__status=DeptMembershipStatus.ACTIVE),
            )
        )
    )
    active_appointments = list(
        Appointment.objects.select_related("user", "position", "department")
        .filter(is_active=True, ended_at__isnull=True)
        .order_by("position__rank_order", "department__display_order")
    )
    recent_lifecycle = list(
        MemberLifecycleEvent.objects.select_related("user", "department", "actor")[:25]
    )
    policies = list(PolicyVersion.objects.filter(is_current=True))
    stats = {
        "active_members": ClubMembership.objects.filter(
            status=ClubMembershipStatus.ACTIVE
        ).count(),
        "suspended_members": ClubMembership.objects.filter(
            status=ClubMembershipStatus.SUSPENDED
        ).count(),
        "verified_skills": UserSkill.objects.filter(verification_status="VERIFIED").count(),
    }

    # Phase 2 — KPI vận hành theo Ban & Nhật ký điều hành đã che PII (PA-07). Không có nút thao tác (INV-04).
    from accounts.models import AuditLog
    from operations.models import ClubTask, DisciplineCase, DisciplineStatus, TaskWorkflowStatus
    from operations.services import redact_pii_for_advisor

    finalized = [
        TaskWorkflowStatus.APPROVED,
        TaskWorkflowStatus.REJECTED,
        TaskWorkflowStatus.CANCELLED,
    ]
    now = timezone.now()
    dept_ops = []
    for d in departments:
        dept_tasks = ClubTask.objects.filter(department=d)
        dept_ops.append(
            {
                "dept": d,
                "open": dept_tasks.exclude(workflow_status__in=finalized).count(),
                "overdue": dept_tasks.exclude(workflow_status__in=finalized)
                .filter(deadline__lt=now)
                .count(),
                "approved": dept_tasks.filter(workflow_status=TaskWorkflowStatus.APPROVED).count(),
            }
        )
    stats["flagged_cases"] = DisciplineCase.objects.filter(
        status__in=[DisciplineStatus.FLAGGED, DisciplineStatus.UNDER_REVIEW]
    ).count()
    audit_entries = [
        {
            "created_at": log.created_at,
            "actor": log.user.public_name if log.user_id else "Hệ thống",
            "action": log.action,
            "target": redact_pii_for_advisor(log.target),
            "note": redact_pii_for_advisor(log.note),
        }
        for log in AuditLog.objects.select_related("user")[:30]
    ]

    # Phase 3 — Giám sát chỉ đọc Đề xuất cấp CLB, Đào tạo & Kho Tài liệu Mật (`INV-04`)
    from programs.models import (
        ConfidentialDocument,
        DepartmentProposal,
        DocumentAccessAction,
        DocumentAccessLog,
        ProposalScope,
        ProposalStatus,
        TrainingCourse,
    )

    escalated_proposals = list(
        DepartmentProposal.objects.select_related("department", "proposer")
        .filter(
            Q(scope=ProposalScope.CLUB)
            | Q(is_escalated_to_bcn=True)
            | Q(status__in=[ProposalStatus.APPROVED, ProposalStatus.IN_PROGRESS, ProposalStatus.COMPLETED])
        )[:10]
    )
    programs_stats = {
        "training_courses": TrainingCourse.objects.count(),
        "vault_docs": ConfidentialDocument.objects.filter(is_archived=False).count(),
        "security_alerts": DocumentAccessLog.objects.filter(
            action__in=[DocumentAccessAction.BREAK_GLASS, DocumentAccessAction.DENIED_ATTEMPT]
        ).count(),
    }

    # Phase 5 — Quỹ CLB tổng quan & Vinh danh (Hard Read-Only — INV-04)
    from evaluations.services import public_recognitions
    from finance.services import compute_club_fund_summary

    fund_summary = compute_club_fund_summary()
    advisor_recognitions = public_recognitions(limit=6)

    return render(
        request,
        "organization/advisor_overview.html",
        {
            "departments": departments,
            "active_appointments": active_appointments,
            "recent_lifecycle": recent_lifecycle,
            "policies": policies,
            "stats": stats,
            "dept_ops": dept_ops,
            "audit_entries": audit_entries,
            "escalated_proposals": escalated_proposals,
            "programs_stats": programs_stats,
            "fund_summary": fund_summary,
            "advisor_recognitions": advisor_recognitions,
        },
    )


@club_member_required
def member_lifecycle_view(request, user_id: int):
    """
    Xem dòng thời gian Lịch sử Vòng đời Bất biến của một thành viên (Chỉ thị 3.2).
    Được phép: Chính chủ, Trưởng ban cùng Ban với thành viên đó, Phó CN, Chủ nhiệm, Cố vấn.
    """
    target = get_object_or_404(User, pk=user_id)
    actor = request.user

    allowed = actor.pk == target.pk or PermissionEngine.authorize(
        actor, "club.member.view_lifecycle"
    )
    if not allowed:
        target_dept_ids = PermissionEngine.get_active_department_ids(target)
        for dept in Department.objects.filter(id__in=target_dept_ids):
            if PermissionEngine.authorize(actor, "dept.member.manage", department=dept):
                allowed = True
                break
    if not allowed:
        raise PermissionDenied("Bạn không có quyền xem sổ cái lịch sử của thành viên này.")

    events = list(
        target.lifecycle_events.select_related("department", "actor").order_by(
            "-created_at", "-id"
        )
    )
    appointments = list(
        target.appointments.select_related("position", "department").order_by(
            "-started_at"
        )
    )
    return render(
        request,
        "organization/member_lifecycle.html",
        {
            "target": target,
            "club_membership": target.club_membership_record,
            "events": events,
            "appointments": appointments,
        },
    )
