"""
Giao diện Web Phase 3 (`programs.views`):
- Kho Tài liệu Mật & Phân quyền ACL (`/workspace/tai-lieu/`, `/workspace/tai-lieu/<pk>/`, tải tệp bảo mật `SEC-01`).
- Trung tâm Đề xuất Hoạt động & Thẩm định 2 cấp (`/workspace/de-xuat/`, `/workspace/de-xuat/<pk>/`).
- Trung tâm Đào tạo Chuyên môn & Lịch tập Band (`/workspace/dao-tao/`).
- Bổ sung mục Chuyên môn / Showcase vào Cổng Ban (`/workspace/ban/<slug>/showcase/them/`).
"""
from __future__ import annotations

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
from operations.models import ClubEventApprovalStatus, ClubEventProfile, ClubTask
from organization.models import (
    ClubMembershipStatus,
    Department,
    DeptMembershipStatus,
    Position,
    PositionCode,
    ScopeType,
    Skill,
    UserSkill,
)
from organization.permissions import PermissionEngine, club_member_required
from organization.services import GovernanceError

from .models import (
    AclPermissionLevel,
    AclSubjectType,
    ConfidentialDocument,
    DepartmentProposal,
    DocumentACLEntry,
    DocumentAccessAction,
    DocumentCategory,
    DocumentClassification,
    DocumentVersion,
    PracticeParticipant,
    PracticeResponseStatus,
    PracticeSession,
    ProposalReviewDecision,
    ProposalScope,
    ProposalStatus,
    ProposalType,
    ShowcaseItemType,
    TrainingCourse,
    TrainingEnrollment,
    TrainingEnrollmentStatus,
)
from .services import (
    _has_position_in_club,
    _is_pure_advisor,
    add_proposal_comment,
    break_glass_document_access,
    can_access_document,
    can_view_proposal,
    convert_proposal_to_course,
    convert_proposal_to_event,
    create_confidential_document,
    create_department_showcase_item,
    create_practice_session,
    create_proposal,
    create_training_course,
    enroll_in_training,
    filter_accessible_documents,
    grant_document_acl,
    record_document_access,
    review_proposal,
    revoke_document_acl,
    submit_proposal,
    update_practice_participant_status,
    update_training_enrollment_status,
    upload_document_version,
)


def _parse_dt_input(raw: str):
    if not raw:
        return None
    dt = parse_datetime(raw.strip())
    if dt is None:
        return None
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


# ---------------------------------------------------------------------------
# 1. KHO TÀI LIỆU MẬT & RESOURCE-LEVEL ACL (`/workspace/tai-lieu/`)
# ---------------------------------------------------------------------------
@club_member_required
def document_vault(request):
    actor = request.user
    is_advisor = _is_pure_advisor(actor)
    all_depts = list(Department.objects.filter(is_active=True))
    manageable_depts = [
        d
        for d in all_depts
        if not is_advisor
        and (
            PermissionEngine.authorize(actor, "dept.document.manage", department=d)
            or PermissionEngine.authorize(actor, "club.document.manage_confidential")
        )
    ]
    can_manage_club_docs = not is_advisor and PermissionEngine.authorize(
        actor, "club.document.manage_confidential"
    )

    if request.method == "POST":
        if is_advisor:
            raise PermissionDenied("Cố vấn ở chế độ Hard Read-Only (`INV-04`), không được tạo tài liệu.")
        action = request.POST.get("action", "")
        if action == "create_document":
            dept_id = (request.POST.get("department_id") or "").strip()
            dept = Department.objects.filter(pk=dept_id, is_active=True).first() if dept_id.isdigit() else None
            cat_id = (request.POST.get("category_id") or "").strip()
            cat = DocumentCategory.objects.filter(pk=cat_id, is_active=True).first() if cat_id.isdigit() else None
            skill_ids = [sid for sid in request.POST.getlist("recommended_skill_ids") if sid.isdigit()]
            skills = list(Skill.objects.filter(pk__in=skill_ids, is_active=True))
            try:
                doc, ver = create_confidential_document(
                    actor=actor,
                    title=request.POST.get("title", ""),
                    classification=request.POST.get("classification", DocumentClassification.DEPT_INTERNAL),
                    uploaded_file=request.FILES.get("file"),
                    department=dept,
                    category=cat,
                    custom_category_label=request.POST.get("custom_category_label", ""),
                    description=request.POST.get("description", ""),
                    recommended_skills=skills,
                    change_note=request.POST.get("change_note", "Phiên bản đầu tiên"),
                    request=request,
                )
                messages.success(request, f"Đã lưu tài liệu '{doc.title}' ({doc.code} v{ver.version_number}) vào Kho Mật.")
                return redirect("programs:document_detail", pk=doc.pk)
            except GovernanceError as exc:
                messages.error(request, str(exc))

    dept_slug = (request.GET.get("dept") or "").strip()
    selected_dept = Department.objects.filter(slug=dept_slug, is_active=True).first() if dept_slug else None
    cls_filter = (request.GET.get("classification") or "").strip()
    skill_id = (request.GET.get("skill") or "").strip()
    selected_skill = Skill.objects.filter(pk=skill_id, is_active=True).first() if skill_id.isdigit() else None
    q = (request.GET.get("q") or "").strip()

    # Hai Pha (PA-01): Lọc quyền bảo mật trước -> Lọc gợi ý kỹ năng sau
    doc_items = filter_accessible_documents(
        actor,
        department=selected_dept,
        classification=cls_filter,
        skill=selected_skill,
        query_text=q,
    )

    return render(
        request,
        "programs/document_vault.html",
        {
            "doc_items": doc_items,
            "departments": all_depts,
            "manageable_depts": manageable_depts,
            "can_manage_club_docs": can_manage_club_docs,
            "categories": list(DocumentCategory.objects.filter(is_active=True)),
            "skills": list(Skill.objects.select_related("category").filter(is_active=True)),
            "classifications": DocumentClassification.choices,
            "selected_dept": selected_dept,
            "selected_classification": cls_filter,
            "selected_skill": selected_skill,
            "q": q,
            "is_advisor": is_advisor,
        },
    )


@club_member_required
def document_detail(request, pk: int):
    actor = request.user
    doc = get_object_or_404(
        ConfidentialDocument.objects.select_related("department", "category", "owner").prefetch_related(
            "recommended_skills"
        ),
        pk=pk,
    )
    can_view = can_access_document(actor, doc, required_level=AclPermissionLevel.VIEW)
    is_chairman_candidate = _has_position_in_club(actor, PositionCode.CHAIRMAN) or getattr(
        actor, "is_server_admin", False
    )

    if request.method == "POST":
        if _is_pure_advisor(actor):
            raise PermissionDenied("Cố vấn ở chế độ Hard Read-Only (`INV-04`), không được thao tác.")
        action = request.POST.get("action", "")
        if action == "break_glass":
            try:
                break_glass_document_access(
                    actor=actor,
                    document=doc,
                    reason=request.POST.get("reason", ""),
                    duration_hours=int(request.POST.get("duration_hours") or 24),
                    request=request,
                )
                messages.warning(
                    request,
                    "Đã kích hoạt truy cập khẩn cấp Break-Glass có thời hạn. Nhật ký kiểm toán & cảnh báo bảo mật đã được ghi nhận.",
                )
                return redirect("programs:document_detail", pk=doc.pk)
            except (GovernanceError, ValueError) as exc:
                messages.error(request, str(exc))
        elif action == "upload_version":
            try:
                ver = upload_document_version(
                    actor=actor,
                    document=doc,
                    uploaded_file=request.FILES.get("file"),
                    change_note=request.POST.get("change_note", ""),
                    request=request,
                )
                messages.success(request, f"Đã cập nhật phiên bản mới v{ver.version_number}.")
                return redirect("programs:document_detail", pk=doc.pk)
            except GovernanceError as exc:
                messages.error(request, str(exc))
        elif action == "grant_acl":
            try:
                subj = request.POST.get("subject_type", "")
                lvl = request.POST.get("permission_level", AclPermissionLevel.DOWNLOAD)
                u_id = request.POST.get("user_id") or ""
                p_id = request.POST.get("position_id") or ""
                t_id = request.POST.get("task_id") or ""
                d_id = request.POST.get("acl_department_id") or ""
                target_u = User.objects.filter(pk=u_id).first() if u_id.isdigit() else None
                pos = Position.objects.filter(pk=p_id).first() if p_id.isdigit() else None
                task = ClubTask.objects.filter(pk=t_id).first() if t_id.isdigit() else None
                acl_dept = Department.objects.filter(pk=d_id).first() if d_id.isdigit() else None
                expires = _parse_dt_input(request.POST.get("expires_at", ""))
                grant_document_acl(
                    actor=actor,
                    document=doc,
                    subject_type=subj,
                    permission_level=lvl,
                    target_user=target_u,
                    position=pos,
                    position_department=doc.department,
                    task=task,
                    department=acl_dept,
                    reason=request.POST.get("reason", ""),
                    expires_at=expires,
                    request=request,
                )
                messages.success(request, "Đã cập nhật danh sách phân quyền ACL.")
                return redirect("programs:document_detail", pk=doc.pk)
            except GovernanceError as exc:
                messages.error(request, str(exc))
        elif action == "revoke_acl":
            entry = get_object_or_404(DocumentACLEntry, pk=request.POST.get("entry_id"), document=doc)
            try:
                revoke_document_acl(
                    actor=actor,
                    acl_entry=entry,
                    reason=request.POST.get("reason", "Thu hồi quyền từ trang chi tiết"),
                    request=request,
                )
                messages.success(request, "Đã thu hồi mục phân quyền ACL.")
                return redirect("programs:document_detail", pk=doc.pk)
            except GovernanceError as exc:
                messages.error(request, str(exc))

    if not can_view:
        # Ghi nhận vết truy cập trái phép TRƯỚC khi trả 403 (ngoài atomic block)
        record_document_access(
            document=doc,
            version=doc.latest_version,
            actor=actor,
            action=DocumentAccessAction.DENIED_ATTEMPT,
            request=request,
            reason="Từ chối xem chi tiết tài liệu mật",
        )
        if is_chairman_candidate:
            return render(
                request,
                "programs/document_detail.html",
                {
                    "doc": doc,
                    "access_denied_can_break_glass": True,
                    "can_download": False,
                    "can_manage": False,
                    "versions": [],
                    "acl_entries": [],
                    "access_logs": [],
                },
                status=403,
            )
        raise PermissionDenied("Bạn không có quyền truy cập tài liệu mật này (Skill không tự cấp quyền ACL).")

    record_document_access(
        document=doc,
        version=doc.latest_version,
        actor=actor,
        action=DocumentAccessAction.VIEW,
        request=request,
    )

    can_download = can_access_document(actor, doc, required_level=AclPermissionLevel.DOWNLOAD)
    can_manage = can_access_document(actor, doc, required_level=AclPermissionLevel.MANAGE)
    versions = list(doc.versions.select_related("uploaded_by"))
    acl_entries = (
        list(
            doc.acl_entries.select_related("user", "position", "department", "task", "granted_by")
        )
        if can_manage
        else []
    )
    access_logs = (
        list(doc.access_logs.select_related("actor", "version")[:30])
        if can_manage
        else []
    )

    active_members = (
        list(
            User.objects.filter(
                is_locked=False,
                club_membership__status=ClubMembershipStatus.ACTIVE,
            ).order_by("full_name", "username")
        )
        if can_manage
        else []
    )
    dept_tasks = (
        list(ClubTask.objects.filter(department=doc.department).order_by("-created_at")[:30])
        if (can_manage and doc.department_id)
        else []
    )

    return render(
        request,
        "programs/document_detail.html",
        {
            "doc": doc,
            "access_denied_can_break_glass": False,
            "can_download": can_download,
            "can_manage": can_manage,
            "versions": versions,
            "acl_entries": acl_entries,
            "access_logs": access_logs,
            "subject_types": AclSubjectType.choices,
            "permission_levels": AclPermissionLevel.choices,
            "active_members": active_members,
            "positions": list(Position.objects.all()) if can_manage else [],
            "departments": list(Department.objects.filter(is_active=True)) if can_manage else [],
            "dept_tasks": dept_tasks,
        },
    )


@club_member_required
def document_download(request, pk: int):
    """Tải tệp từ `PrivateVaultStorage` có kiểm tra quyền & ghi sổ cái `DocumentAccessLog` (`SEC-01`)."""
    actor = request.user
    doc = get_object_or_404(ConfidentialDocument, pk=pk)
    ver_id = request.GET.get("version")
    if ver_id and ver_id.isdigit():
        ver = get_object_or_404(DocumentVersion, pk=ver_id, document=doc)
    else:
        ver = doc.latest_version

    if not can_access_document(actor, doc, required_level=AclPermissionLevel.DOWNLOAD):
        record_document_access(
            document=doc,
            version=ver,
            actor=actor,
            action=DocumentAccessAction.DENIED_ATTEMPT,
            request=request,
            reason="Cố tình tải trực tiếp tài liệu mật khi không có ACL",
        )
        raise PermissionDenied("Bạn không có quyền tải tệp tài liệu mật này.")

    if ver is None or not ver.file:
        raise Http404("Tài liệu chưa có tệp đính kèm.")
    try:
        fh = ver.file.open("rb")
    except FileNotFoundError as exc:
        raise Http404("Không tìm thấy tệp vật lý trong Kho Lưu trữ.") from exc

    record_document_access(
        document=doc,
        version=ver,
        actor=actor,
        action=DocumentAccessAction.DOWNLOAD,
        request=request,
        reason=f"Tải v{ver.version_number}",
    )
    response = FileResponse(
        fh,
        as_attachment=True,
        filename=os.path.basename(ver.original_filename or f"{doc.code}.bin"),
        content_type=ver.content_type or "application/octet-stream",
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


# ---------------------------------------------------------------------------
# 2. QUY TRÌNH ĐỀ XUẤT HOẠT ĐỘNG (`/workspace/de-xuat/`)
# ---------------------------------------------------------------------------
@club_member_required
def proposal_hub(request):
    actor = request.user
    is_advisor = _is_pure_advisor(actor)
    all_depts = list(Department.objects.filter(is_active=True))
    creatable_depts = [
        d
        for d in all_depts
        if not is_advisor
        and (
            PermissionEngine.authorize(actor, "dept.proposal.create_member", department=d)
            or PermissionEngine.authorize(actor, "dept.proposal.submit_to_bcn", department=d)
            or PermissionEngine.authorize(actor, "club.dept.supervise_ops")
        )
    ]

    if request.method == "POST":
        if is_advisor:
            raise PermissionDenied("Cố vấn ở chế độ Hard Read-Only (`INV-04`), không được tạo đề xuất.")
        if request.POST.get("action") == "create_proposal":
            dept = get_object_or_404(Department, pk=request.POST.get("department_id"), is_active=True)
            try:
                prop = create_proposal(
                    actor=actor,
                    department=dept,
                    title=request.POST.get("title", ""),
                    proposal_type=request.POST.get("proposal_type", ProposalType.EVENT),
                    scope=request.POST.get("scope", ProposalScope.DEPARTMENT),
                    summary=request.POST.get("summary", ""),
                    objectives=request.POST.get("objectives", ""),
                    estimated_budget=request.POST.get("estimated_budget") or 0,
                    proposed_start_at=_parse_dt_input(request.POST.get("proposed_start_at", "")),
                    proposed_location=request.POST.get("proposed_location", ""),
                    attachment=request.FILES.get("attachment"),
                    submit_immediately=request.POST.get("submit_immediately") == "1",
                )
                messages.success(request, f"Đã tạo đề xuất '{prop.title}' ({prop.code}).")
                return redirect("programs:proposal_detail", pk=prop.pk)
            except GovernanceError as exc:
                messages.error(request, str(exc))

    all_props = DepartmentProposal.objects.select_related(
        "department", "proposer", "approved_by", "linked_event", "linked_course"
    )
    dept_slug = (request.GET.get("dept") or "").strip()
    if dept_slug:
        all_props = all_props.filter(department__slug=dept_slug)
    status_filter = (request.GET.get("status") or "").strip()
    if status_filter in ProposalStatus.values:
        all_props = all_props.filter(status=status_filter)

    visible_props = [p for p in all_props if can_view_proposal(actor, p)]

    return render(
        request,
        "programs/proposal_hub.html",
        {
            "proposals": visible_props,
            "departments": all_depts,
            "creatable_depts": creatable_depts,
            "proposal_types": ProposalType.choices,
            "proposal_scopes": ProposalScope.choices,
            "proposal_statuses": ProposalStatus.choices,
            "is_advisor": is_advisor,
            "selected_dept_slug": dept_slug,
            "selected_status": status_filter,
        },
    )


@club_member_required
def proposal_detail(request, pk: int):
    actor = request.user
    prop = get_object_or_404(
        DepartmentProposal.objects.select_related(
            "department", "proposer", "approved_by", "linked_event__event", "linked_course"
        ),
        pk=pk,
    )
    if not can_view_proposal(actor, prop):
        raise PermissionDenied("Bạn không có quyền xem đề xuất này.")

    is_advisor = _is_pure_advisor(actor)
    is_bcn_approver = not is_advisor and (
        PermissionEngine.authorize(actor, "club.event.approve")
        or PermissionEngine.authorize(actor, "club.dept.supervise_ops")
        or getattr(actor, "is_server_admin", False)
    )
    is_dept_reviewer = not is_advisor and PermissionEngine.authorize(
        actor, "dept.proposal.submit_to_bcn", department=prop.department
    )
    can_review = (is_bcn_approver or is_dept_reviewer) and prop.status in (
        ProposalStatus.SUBMITTED,
        ProposalStatus.UNDER_REVIEW,
        ProposalStatus.REJECTED,
    )
    can_submit = (
        not is_advisor
        and (prop.proposer_id == actor.id or is_dept_reviewer)
        and prop.status in (ProposalStatus.DRAFT, ProposalStatus.REJECTED)
    )
    can_convert_event = (
        not is_advisor
        and prop.status == ProposalStatus.APPROVED
        and not prop.linked_event_id
        and (
            is_bcn_approver
            or PermissionEngine.authorize(actor, "dept.event.manage_internal", department=prop.department)
        )
    )
    can_convert_course = (
        not is_advisor
        and prop.status == ProposalStatus.APPROVED
        and not prop.linked_course_id
        and (
            is_bcn_approver
            or PermissionEngine.authorize(actor, "dept.training.manage", department=prop.department)
        )
    )
    can_convert = can_convert_event or can_convert_course

    if request.method == "POST":
        if is_advisor:
            raise PermissionDenied("Cố vấn ở chế độ Hard Read-Only (`INV-04`), không được thao tác.")
        action = request.POST.get("action", "")
        try:
            if action == "submit":
                submit_proposal(actor=actor, proposal=prop)
                messages.success(request, f"Đã gửi đề xuất {prop.code} lên cấp xem xét.")
            elif action == "comment":
                add_proposal_comment(
                    actor=actor, proposal=prop, body=request.POST.get("body", "")
                )
                messages.success(request, "Đã ghi nhận góp ý thảo luận.")
            elif action == "review":
                rev = review_proposal(
                    actor=actor,
                    proposal=prop,
                    decision=request.POST.get("decision", ""),
                    feedback=request.POST.get("feedback", ""),
                )
                messages.success(request, f"Đã ghi nhận thẩm định: {rev.get_decision_display()}.")
            elif action == "convert_event":
                ce = convert_proposal_to_event(actor=actor, proposal=prop)
                messages.success(
                    request,
                    f"Đã chuyển đề xuất thành Dự thảo Sự kiện '{ce.event.name}'.",
                )
                return redirect("operations:event_detail", pk=ce.pk)
            elif action == "convert_course":
                course = convert_proposal_to_course(actor=actor, proposal=prop)
                messages.success(
                    request,
                    f"Đã chuyển đề xuất thành Khóa đào tạo '{course.title}'.",
                )
                return redirect("programs:training_practice_hub")
            return redirect("programs:proposal_detail", pk=prop.pk)
        except GovernanceError as exc:
            messages.error(request, str(exc))

    reviews = list(prop.reviews.select_related("reviewer"))
    comments = list(prop.comments.select_related("author"))
    return render(
        request,
        "programs/proposal_detail.html",
        {
            "proposal": prop,
            "reviews": reviews,
            "comments": comments,
            "is_advisor": is_advisor,
            "is_bcn_approver": is_bcn_approver,
            "is_dept_reviewer": is_dept_reviewer,
            "can_review": can_review,
            "can_submit": can_submit,
            "can_convert": can_convert,
            "can_convert_event": can_convert_event,
            "can_convert_course": can_convert_course,
            "decisions": ProposalReviewDecision.choices,
        },
    )


# ---------------------------------------------------------------------------
# 3. ĐÀO TẠO CHUYÊN MÔN & LỊCH TẬP BAND (`/workspace/dao-tao/`)
# ---------------------------------------------------------------------------
@club_member_required
def training_practice_hub(request):
    actor = request.user
    is_advisor = _is_pure_advisor(actor)
    all_depts = list(Department.objects.filter(is_active=True))
    manage_training_depts = [
        d
        for d in all_depts
        if not is_advisor
        and (
            PermissionEngine.authorize(actor, "dept.training.manage", department=d)
            or PermissionEngine.authorize(actor, "club.dept.supervise_ops")
        )
    ]

    if request.method == "POST":
        if is_advisor:
            raise PermissionDenied("Cố vấn ở chế độ Hard Read-Only (`INV-04`), không được thao tác.")
        action = request.POST.get("action", "")
        try:
            if action == "create_course":
                dept = get_object_or_404(Department, pk=request.POST.get("department_id"), is_active=True)
                st = _parse_dt_input(request.POST.get("starts_at", ""))
                en = _parse_dt_input(request.POST.get("ends_at", ""))
                if not st or not en:
                    raise GovernanceError("Vui lòng nhập đầy đủ thời gian bắt đầu và kết thúc.")
                sk_id = request.POST.get("target_skill_id") or ""
                target_sk = Skill.objects.filter(pk=sk_id).first() if sk_id.isdigit() else None
                inst_id = request.POST.get("instructor_id") or ""
                instructor = User.objects.filter(pk=inst_id).first() if inst_id.isdigit() else actor
                c = create_training_course(
                    actor=actor,
                    department=dept,
                    title=request.POST.get("title", ""),
                    description=request.POST.get("description", ""),
                    custom_category=request.POST.get("custom_category", ""),
                    target_skill=target_sk,
                    instructor=instructor,
                    location=request.POST.get("location", ""),
                    starts_at=st,
                    ends_at=en,
                    capacity=int(request.POST.get("capacity") or 25),
                )
                messages.success(request, f"Đã mở khóa đào tạo '{c.title}'.")
            elif action == "enroll_course":
                course = get_object_or_404(TrainingCourse, pk=request.POST.get("course_id"))
                enr = enroll_in_training(actor=actor, course=course)
                messages.success(
                    request,
                    f"Đã đăng ký '{course.title}' ({enr.get_status_display()}).",
                )
            elif action == "drop_course":
                enr = get_object_or_404(TrainingEnrollment, pk=request.POST.get("enrollment_id"))
                update_training_enrollment_status(
                    actor=actor, enrollment=enr, new_status=TrainingEnrollmentStatus.DROPPED
                )
                messages.info(request, "Đã huỷ ghi danh khóa đào tạo.")
            elif action == "complete_enrollment":
                enr = get_object_or_404(TrainingEnrollment, pk=request.POST.get("enrollment_id"))
                update_training_enrollment_status(
                    actor=actor,
                    enrollment=enr,
                    new_status=TrainingEnrollmentStatus.COMPLETED,
                    attendance_count=enr.attendance_count + 1,
                    completion_note=request.POST.get("completion_note", "Hoàn thành đạt yêu cầu"),
                )
                messages.success(request, f"Đã xác nhận hoàn thành đào tạo cho {enr.user.public_name}.")
            elif action == "create_practice":
                dept = get_object_or_404(Department, pk=request.POST.get("department_id"), is_active=True)
                st = _parse_dt_input(request.POST.get("starts_at", ""))
                en = _parse_dt_input(request.POST.get("ends_at", ""))
                if not st or not en:
                    raise GovernanceError("Vui lòng nhập đầy đủ thời gian buổi tập.")
                ce_id = request.POST.get("club_event_id") or ""
                ce = ClubEventProfile.objects.filter(pk=ce_id).first() if ce_id.isdigit() else None
                u_ids = [uid for uid in request.POST.getlist("participant_ids") if uid.isdigit()]
                default_role = request.POST.get("default_role", "Thành viên tập luyện")
                specs = [(u, default_role, None) for u in User.objects.filter(pk__in=u_ids)]
                ps = create_practice_session(
                    actor=actor,
                    department=dept,
                    title=request.POST.get("title", ""),
                    repertoire_note=request.POST.get("repertoire_note", ""),
                    location=request.POST.get("location", ""),
                    starts_at=st,
                    ends_at=en,
                    club_event=ce,
                    participants_specs=specs,
                )
                messages.success(request, f"Đã lên lịch tập luyện '{ps.title}'.")
            elif action == "practice_rsvp":
                part = get_object_or_404(PracticeParticipant, pk=request.POST.get("participant_id"))
                update_practice_participant_status(
                    actor=actor,
                    participant=part,
                    new_status=request.POST.get("response_status", PracticeResponseStatus.CONFIRMED),
                    note=request.POST.get("note", ""),
                )
                messages.success(request, "Đã cập nhật trạng thái tham gia buổi tập.")
            return redirect("programs:training_practice_hub")
        except (GovernanceError, ValueError) as exc:
            messages.error(request, str(exc))

    courses_qs = TrainingCourse.objects.select_related(
        "department", "instructor", "target_skill"
    ).prefetch_related("enrollments__user")
    sessions_qs = PracticeSession.objects.select_related(
        "department", "club_event__event", "lead_coordinator"
    ).prefetch_related("participants__user", "participants__skill")

    dept_slug = (request.GET.get("dept") or "").strip()
    if dept_slug:
        courses_qs = courses_qs.filter(department__slug=dept_slug)
        sessions_qs = sessions_qs.filter(department__slug=dept_slug)

    courses = []
    for c in courses_qs:
        my_enr = next((e for e in c.enrollments.all() if e.user_id == actor.id), None)
        can_manage = any(d.id == c.department_id for d in manage_training_depts)
        courses.append(
            {
                "course": c,
                "my_enrollment": my_enr,
                "active_count": sum(
                    1
                    for e in c.enrollments.all()
                    if e.status in (TrainingEnrollmentStatus.ENROLLED, TrainingEnrollmentStatus.COMPLETED)
                ),
                "can_manage": can_manage,
                "enrollments": list(c.enrollments.all()) if can_manage else [],
            }
        )

    sessions = []
    for s in sessions_qs:
        my_part = next((p for p in s.participants.all() if p.user_id == actor.id), None)
        can_manage = any(d.id == s.department_id for d in manage_training_depts)
        sessions.append(
            {
                "session": s,
                "my_participation": my_part,
                "can_manage": can_manage,
                "participants": list(s.participants.all()),
            }
        )

    return render(
        request,
        "programs/training_practice_hub.html",
        {
            "courses": courses,
            "sessions": sessions,
            "departments": all_depts,
            "manage_training_depts": manage_training_depts,
            "skills": list(Skill.objects.filter(is_active=True)),
            "active_members": list(
                User.objects.filter(
                    is_locked=False, club_membership__status=ClubMembershipStatus.ACTIVE
                ).order_by("full_name", "username")
            )
            if manage_training_depts
            else [],
            "club_events": list(
                ClubEventProfile.objects.select_related("event").exclude(
                    approval_status=ClubEventApprovalStatus.CANCELLED
                )
            )
            if manage_training_depts
            else [],
            "is_advisor": is_advisor,
            "selected_dept_slug": dept_slug,
        },
    )


# ---------------------------------------------------------------------------
# 4. THÊM MỤC CHUYÊN MÔN / SHOWCASE TRÊN CỔNG BAN
# ---------------------------------------------------------------------------
@require_POST
@club_member_required
def department_add_showcase(request, slug: str):
    dept = get_object_or_404(Department, slug=slug, is_active=True)
    doc_id = (request.POST.get("linked_document_id") or "").strip()
    doc = (
        ConfidentialDocument.objects.filter(pk=doc_id, department=dept).first()
        if doc_id.isdigit()
        else None
    )
    try:
        create_department_showcase_item(
            actor=request.user,
            department=dept,
            category_label=request.POST.get("category_label", ""),
            item_type=request.POST.get("item_type", ShowcaseItemType.SOP_GUIDE),
            title=request.POST.get("title", ""),
            summary=request.POST.get("summary", ""),
            external_url=request.POST.get("external_url", ""),
            linked_document=doc,
            is_pinned=request.POST.get("is_pinned") == "1",
        )
        messages.success(request, f"Đã bổ sung mục chuyên môn mới cho {dept.name}.")
    except GovernanceError as exc:
        messages.error(request, str(exc))
    return redirect("organization:department_detail", slug=dept.slug)
