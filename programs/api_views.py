"""
REST API `/api/v1/` — Phase 3 Department Management:
- Kho Tài liệu Mật & ACL (`/api/v1/documents/`, `download`, `acl`, `break-glass`).
- Quy trình Đề xuất (`/api/v1/proposals/`, `review`, `convert`).
- Đào tạo & Lịch tập Band (`/api/v1/training-courses/`, `/api/v1/practice-sessions/`).
"""
from __future__ import annotations

from functools import wraps
import os

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.models import User
from operations.models import ClubTask
from organization.api_views import _parse_json_body, api_error, api_ok
from organization.models import Department, Position, Skill
from organization.permissions import PermissionEngine, api_login_required
from organization.services import GovernanceError

from .models import (
    AclPermissionLevel,
    ConfidentialDocument,
    DepartmentProposal,
    DocumentACLEntry,
    DocumentAccessAction,
    DocumentClassification,
    DocumentVersion,
    PracticeParticipant,
    PracticeSession,
    ProposalScope,
    ProposalType,
    TrainingCourse,
)
from .services import (
    _is_pure_advisor,
    break_glass_document_access,
    can_access_document,
    can_view_proposal,
    convert_proposal_to_course,
    convert_proposal_to_event,
    create_confidential_document,
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
)


def _api_guard(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        try:
            return view_func(request, *args, **kwargs)
        except PermissionDenied as exc:
            return api_error("PERMISSION_DENIED", str(exc) or "Không đủ quyền.", status=403)
        except Http404:
            return api_error("NOT_FOUND", "Không tìm thấy tài nguyên.", status=404)
        except ValidationError as exc:
            return api_error("VALIDATION_ERROR", "; ".join(exc.messages), status=400)
        except GovernanceError as exc:
            return api_error(exc.code, str(exc), status=400)

    return wrapper


def _parse_dt(raw):
    if not raw:
        return None
    dt = parse_datetime(str(raw))
    if dt is None:
        raise GovernanceError("Định dạng thời gian ISO-8601 không hợp lệ.")
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def _serialize_document(doc: ConfidentialDocument, viewer: User, matched_skills=None) -> dict:
    latest = doc.latest_version
    return {
        "id": doc.id,
        "code": doc.code,
        "title": doc.title,
        "classification": doc.classification,
        "department": {"id": doc.department_id, "name": doc.department.name}
        if doc.department_id
        else None,
        "custom_category_label": doc.custom_category_label,
        "recommended_skills": [s.code for s in doc.recommended_skills.all()],
        "is_skill_recommended": bool(matched_skills),
        "can_download": can_access_document(viewer, doc, AclPermissionLevel.DOWNLOAD),
        "can_manage": can_access_document(viewer, doc, AclPermissionLevel.MANAGE),
        "latest_version": {
            "id": latest.id,
            "version_number": latest.version_number,
            "original_filename": latest.original_filename,
            "file_size": latest.file_size,
            "checksum_sha256": latest.checksum_sha256,
        }
        if latest
        else None,
    }


def _serialize_proposal(p: DepartmentProposal) -> dict:
    return {
        "id": p.id,
        "code": p.code,
        "title": p.title,
        "proposal_type": p.proposal_type,
        "scope": p.scope,
        "status": p.status,
        "is_escalated_to_bcn": p.is_escalated_to_bcn,
        "department": {"id": p.department_id, "name": p.department.name},
        "proposer_id": p.proposer_id,
        "proposer_name": p.proposer.public_name,
        "estimated_budget": str(p.estimated_budget),
        "linked_event_id": p.linked_event_id,
        "linked_course_id": p.linked_course_id,
        "created_at": p.created_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# 1. DOCUMENTS & ACL API
# ---------------------------------------------------------------------------
@require_http_methods(["GET", "POST"])
@api_login_required
@_api_guard
def api_documents(request):
    if request.method == "GET":
        dept_slug = (request.GET.get("dept") or "").strip()
        dept = Department.objects.filter(slug=dept_slug, is_active=True).first() if dept_slug else None
        cls = (request.GET.get("classification") or "").strip()
        sk_id = (request.GET.get("skill_id") or "").strip()
        sk = Skill.objects.filter(pk=sk_id).first() if sk_id.isdigit() else None
        q = (request.GET.get("q") or "").strip()
        items = filter_accessible_documents(
            request.user,
            department=dept,
            classification=cls,
            skill=sk,
            query_text=q,
        )
        return api_ok(
            [
                _serialize_document(it["document"], request.user, it["matched_user_skills"])
                for it in items
            ]
        )

    dept_id = request.POST.get("department_id") or ""
    dept = Department.objects.filter(pk=dept_id, is_active=True).first() if dept_id.isdigit() else None
    skill_codes = [s for s in request.POST.getlist("recommended_skills") if s]
    skills = list(Skill.objects.filter(code__in=skill_codes)) if skill_codes else []
    doc, _ = create_confidential_document(
        actor=request.user,
        title=request.POST.get("title", ""),
        classification=request.POST.get("classification", DocumentClassification.DEPT_INTERNAL),
        uploaded_file=request.FILES.get("file"),
        department=dept,
        description=request.POST.get("description", ""),
        custom_category_label=request.POST.get("custom_category_label", ""),
        recommended_skills=skills,
        request=request,
    )
    return api_ok(_serialize_document(doc, request.user), status=201)


@require_GET
@api_login_required
@_api_guard
def api_document_detail(request, pk: int):
    doc = get_object_or_404(ConfidentialDocument, pk=pk)
    if not can_access_document(request.user, doc, AclPermissionLevel.VIEW):
        record_document_access(
            document=doc,
            version=doc.latest_version,
            actor=request.user,
            action=DocumentAccessAction.DENIED_ATTEMPT,
            request=request,
            reason="API detail permission denied",
        )
        raise PermissionDenied("Bạn không có quyền xem tài liệu mật này.")
    record_document_access(
        document=doc,
        version=doc.latest_version,
        actor=request.user,
        action=DocumentAccessAction.VIEW,
        request=request,
    )
    return api_ok(_serialize_document(doc, request.user))


@require_GET
@api_login_required
@_api_guard
def api_document_download(request, pk: int):
    doc = get_object_or_404(ConfidentialDocument, pk=pk)
    ver = doc.latest_version
    if not can_access_document(request.user, doc, AclPermissionLevel.DOWNLOAD):
        record_document_access(
            document=doc,
            version=ver,
            actor=request.user,
            action=DocumentAccessAction.DENIED_ATTEMPT,
            request=request,
            reason="API download permission denied",
        )
        raise PermissionDenied("Bạn không có quyền tải tệp tài liệu mật này.")
    if ver is None or not ver.file:
        raise Http404("Tệp không tồn tại.")
    record_document_access(
        document=doc,
        version=ver,
        actor=request.user,
        action=DocumentAccessAction.DOWNLOAD,
        request=request,
        reason="API download",
    )
    resp = FileResponse(
        ver.file.open("rb"),
        as_attachment=True,
        filename=os.path.basename(ver.original_filename or f"{doc.code}.bin"),
        content_type=ver.content_type or "application/octet-stream",
    )
    resp["X-Content-Type-Options"] = "nosniff"
    resp["Cache-Control"] = "private, no-store"
    return resp


@require_http_methods(["GET", "POST"])
@api_login_required
@_api_guard
def api_document_acl(request, pk: int):
    doc = get_object_or_404(ConfidentialDocument, pk=pk)
    if not can_access_document(request.user, doc, AclPermissionLevel.MANAGE):
        raise PermissionDenied("Bạn không có quyền quản trị ACL của tài liệu này.")

    if request.method == "GET":
        entries = doc.acl_entries.select_related("user", "position", "department", "task")
        return api_ok(
            [
                {
                    "id": e.id,
                    "subject_type": e.subject_type,
                    "user_id": e.user_id,
                    "position_id": e.position_id,
                    "department_id": e.department_id,
                    "task_id": e.task_id,
                    "permission_level": e.permission_level,
                    "is_active": e.is_active,
                    "is_currently_effective": e.is_currently_effective,
                    "reason": e.reason,
                }
                for e in entries
            ]
        )

    payload = _parse_json_body(request)
    if payload.get("action") == "revoke":
        entry = get_object_or_404(DocumentACLEntry, pk=payload.get("entry_id"), document=doc)
        revoked = revoke_document_acl(
            actor=request.user,
            acl_entry=entry,
            reason=payload.get("reason", "Thu hồi qua API"),
            request=request,
        )
        return api_ok({"id": revoked.id, "is_active": revoked.is_active})

    entry = grant_document_acl(
        actor=request.user,
        document=doc,
        subject_type=payload.get("subject_type", ""),
        permission_level=payload.get("permission_level", AclPermissionLevel.DOWNLOAD),
        target_user=User.objects.filter(pk=payload.get("user_id")).first()
        if payload.get("user_id")
        else None,
        position=Position.objects.filter(code=payload.get("position_code")).first()
        if payload.get("position_code")
        else None,
        position_department=doc.department,
        task=ClubTask.objects.filter(pk=payload.get("task_id")).first()
        if payload.get("task_id")
        else None,
        department=Department.objects.filter(pk=payload.get("department_id")).first()
        if payload.get("department_id")
        else None,
        reason=payload.get("reason", ""),
        expires_at=_parse_dt(payload.get("expires_at")),
        request=request,
    )
    return api_ok({"id": entry.id, "subject_type": entry.subject_type, "is_active": entry.is_active}, status=201)


@require_POST
@api_login_required
@_api_guard
def api_document_break_glass(request, pk: int):
    doc = get_object_or_404(ConfidentialDocument, pk=pk)
    payload = _parse_json_body(request)
    entry = break_glass_document_access(
        actor=request.user,
        document=doc,
        reason=payload.get("reason", ""),
        duration_hours=int(payload.get("duration_hours", 24)),
        request=request,
    )
    return api_ok(
        {
            "acl_entry_id": entry.id,
            "expires_at": entry.expires_at.isoformat() if entry.expires_at else None,
            "is_break_glass": True,
        },
        status=201,
    )


# ---------------------------------------------------------------------------
# 2. PROPOSALS API
# ---------------------------------------------------------------------------
@require_http_methods(["GET", "POST"])
@api_login_required
@_api_guard
def api_proposals(request):
    if request.method == "GET":
        props = [
            _serialize_proposal(p)
            for p in DepartmentProposal.objects.select_related("department", "proposer")
            if can_view_proposal(request.user, p)
        ]
        return api_ok(props)

    payload = _parse_json_body(request)
    dept = get_object_or_404(Department, pk=payload.get("department_id"), is_active=True)
    prop = create_proposal(
        actor=request.user,
        department=dept,
        title=payload.get("title", ""),
        proposal_type=payload.get("proposal_type", ProposalType.EVENT),
        scope=payload.get("scope", ProposalScope.DEPARTMENT),
        summary=payload.get("summary", ""),
        objectives=payload.get("objectives", ""),
        estimated_budget=payload.get("estimated_budget", 0),
        proposed_start_at=_parse_dt(payload.get("proposed_start_at")),
        proposed_location=payload.get("proposed_location", ""),
        submit_immediately=bool(payload.get("submit_immediately", False)),
    )
    return api_ok(_serialize_proposal(prop), status=201)


@require_GET
@api_login_required
@_api_guard
def api_proposal_detail(request, pk: int):
    prop = get_object_or_404(DepartmentProposal.objects.select_related("department", "proposer"), pk=pk)
    if not can_view_proposal(request.user, prop):
        raise PermissionDenied("Bạn không có quyền xem đề xuất này.")
    return api_ok(_serialize_proposal(prop))


@require_POST
@api_login_required
@_api_guard
def api_proposal_review(request, pk: int):
    prop = get_object_or_404(DepartmentProposal, pk=pk)
    payload = _parse_json_body(request)
    if payload.get("action") == "submit":
        submit_proposal(actor=request.user, proposal=prop)
        return api_ok(_serialize_proposal(prop))
    rev = review_proposal(
        actor=request.user,
        proposal=prop,
        decision=payload.get("decision", ""),
        feedback=payload.get("feedback", ""),
    )
    return api_ok(
        {
            "review_id": rev.id,
            "decision": rev.decision,
            "proposal_status": prop.status,
            "is_escalated_to_bcn": prop.is_escalated_to_bcn,
        }
    )


@require_POST
@api_login_required
@_api_guard
def api_proposal_convert(request, pk: int):
    prop = get_object_or_404(DepartmentProposal, pk=pk)
    payload = _parse_json_body(request)
    target = payload.get("target", "event")
    if target == "course":
        course = convert_proposal_to_course(actor=request.user, proposal=prop)
        return api_ok({"course_id": course.id, "proposal_status": prop.status}, status=201)
    ce = convert_proposal_to_event(actor=request.user, proposal=prop)
    return api_ok({"club_event_id": ce.id, "proposal_status": prop.status}, status=201)


# ---------------------------------------------------------------------------
# 3. TRAINING & PRACTICE SESSIONS API
# ---------------------------------------------------------------------------
@require_http_methods(["GET", "POST"])
@api_login_required
@_api_guard
def api_training_courses(request):
    if request.method == "GET":
        courses = TrainingCourse.objects.select_related("department", "instructor")
        return api_ok(
            [
                {
                    "id": c.id,
                    "title": c.title,
                    "department": {"id": c.department_id, "name": c.department.name},
                    "location": c.location,
                    "starts_at": c.starts_at.isoformat(),
                    "capacity": c.capacity,
                    "active_enrollments": c.active_enrollments_count,
                    "status": c.status,
                }
                for c in courses
            ]
        )

    payload = _parse_json_body(request)
    dept = get_object_or_404(Department, pk=payload.get("department_id"), is_active=True)
    course = create_training_course(
        actor=request.user,
        department=dept,
        title=payload.get("title", ""),
        description=payload.get("description", ""),
        location=payload.get("location", "Phòng Tập KMG"),
        starts_at=_parse_dt(payload.get("starts_at")),
        ends_at=_parse_dt(payload.get("ends_at")),
        capacity=int(payload.get("capacity", 25)),
    )
    return api_ok({"id": course.id, "title": course.title, "status": course.status}, status=201)


@require_POST
@api_login_required
@_api_guard
def api_training_enroll(request, pk: int):
    course = get_object_or_404(TrainingCourse, pk=pk)
    enr = enroll_in_training(actor=request.user, course=course)
    return api_ok({"enrollment_id": enr.id, "status": enr.status}, status=201)


@require_http_methods(["GET", "POST"])
@api_login_required
@_api_guard
def api_practice_sessions(request):
    if request.method == "GET":
        if _is_pure_advisor(request.user) or not PermissionEngine.get_active_department_ids(request.user):
            # Cố vấn hoặc thành viên chỉ xem tổng quan hoặc của Ban mình
            qs = PracticeSession.objects.select_related("department")
        else:
            qs = PracticeSession.objects.select_related("department")
        return api_ok(
            [
                {
                    "id": s.id,
                    "title": s.title,
                    "department": {"id": s.department_id, "name": s.department.name},
                    "location": s.location,
                    "starts_at": s.starts_at.isoformat(),
                    "status": s.status,
                }
                for s in qs
            ]
        )

    payload = _parse_json_body(request)
    dept = get_object_or_404(Department, pk=payload.get("department_id"), is_active=True)
    specs = []
    for item in payload.get("participants") or []:
        u = User.objects.filter(pk=item.get("user_id")).first()
        if u:
            specs.append((u, item.get("assigned_role", "Thành viên tập luyện"), None))
    ps = create_practice_session(
        actor=request.user,
        department=dept,
        title=payload.get("title", ""),
        location=payload.get("location", "Phòng Studio B204"),
        starts_at=_parse_dt(payload.get("starts_at")),
        ends_at=_parse_dt(payload.get("ends_at")),
        repertoire_note=payload.get("repertoire_note", ""),
        participants_specs=specs,
    )
    return api_ok({"id": ps.id, "title": ps.title, "status": ps.status}, status=201)


@require_POST
@api_login_required
@_api_guard
def api_practice_attendance(request, pk: int):
    ps = get_object_or_404(PracticeSession, pk=pk)
    payload = _parse_json_body(request)
    uid = payload.get("user_id") or request.user.id
    part = get_object_or_404(PracticeParticipant, session=ps, user_id=uid)
    updated = update_practice_participant_status(
        actor=request.user,
        participant=part,
        new_status=payload.get("response_status", ""),
        note=payload.get("note", ""),
    )
    return api_ok({"participant_id": updated.id, "response_status": updated.response_status})
