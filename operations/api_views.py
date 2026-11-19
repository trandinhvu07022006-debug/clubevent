"""
REST API `/api/v1/` — Phase 2 Core Management (Công việc, Sự kiện CLB & RSVP, Kỷ luật, Khiếu nại, Thông báo).

Dùng chung JSON Envelope `{ok, data, meta}` / `{ok:false, error:{code,message,details}}` với Phase 1.
Mọi endpoint ủy quyền cho `operations.services`, nơi `PermissionEngine` kiểm tra quyền tại Backend.
"""
from __future__ import annotations

from functools import wraps

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.models import User
from notifications.models import PushSubscription
from notifications.services import get_or_create_notification_preference
from organization.api_views import _parse_json_body, api_error, api_ok
from organization.models import ClubMembershipStatus, Department
from organization.permissions import PermissionEngine, api_login_required
from organization.services import GovernanceError

from .models import (
    Appeal,
    AppealTargetType,
    ClubEventApprovalStatus,
    ClubEventProfile,
    ClubTask,
    DisciplineCase,
    TaskReview,
)
from .services import (
    adjudicate_appeal,
    broadcast_announcement,
    can_view_club_task,
    create_and_assign_task,
    finalize_task_review,
    resolve_discipline_case,
    respond_event_rsvp,
    review_club_event,
    submit_appeal,
    submit_task_deliverable,
    update_task_progress,
)


def _api_guard(view_func):
    """Chuyển lỗi nghiệp vụ / phân quyền thành JSON Envelope chuẩn."""

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
            status_code = 409 if exc.code in ("RSVP_FROZEN", "CONFLICT_SINGLETON") else 400
            return api_error(exc.code, str(exc), status=status_code)

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


def _serialize_task(task: ClubTask) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "department": {"id": task.department_id, "name": task.department.name},
        "event_id": task.event_id,
        "priority": task.priority,
        "workflow_status": task.workflow_status,
        "is_overdue": task.is_overdue,
        "submission_mode": task.submission_mode,
        "progress_percent": task.progress_percent,
        "deadline": task.deadline.isoformat(),
        "reassignment_needed": task.reassignment_needed,
        "recommended_skill": task.recommended_skill.code if task.recommended_skill_id else None,
        "assignees": [
            {
                "user_id": a.user_id,
                "display_name": a.user.public_name,
                "role": a.role,
                "personal_status": a.personal_status,
                "progress_percent": a.progress_percent,
            }
            for a in task.assignees.select_related("user").filter(is_active=True)
        ],
    }


def _serialize_club_event(ce: ClubEventProfile, viewer: User) -> dict:
    my_att = ce.attendances.filter(user=viewer).first()
    return {
        "id": ce.id,
        "event_id": ce.event_id,
        "name": ce.event.name,
        "location": ce.event.location,
        "starts_at": ce.event.starts_at.isoformat(),
        "event_scope": ce.event_scope,
        "approval_status": ce.approval_status,
        "visibility": ce.event.visibility,
        "lead_department_id": ce.lead_department_id,
        "rsvp_freeze_at": ce.rsvp_freeze_at.isoformat() if ce.rsvp_freeze_at else None,
        "is_rsvp_frozen": ce.is_rsvp_frozen,
        "policy_version": ce.policy_version.version_number if ce.policy_version_id else None,
        "my_rsvp_status": my_att.rsvp_status if my_att else None,
    }


def _serialize_appeal(ap: Appeal) -> dict:
    return {
        "id": ap.id,
        "target_type": ap.target_type,
        "status": ap.status,
        "reason": ap.reason,
        "discipline_case_id": ap.discipline_case_id,
        "task_review_id": ap.task_review_id,
        "decision_note": ap.decision_note,
        "decided_at": ap.decided_at.isoformat() if ap.decided_at else None,
        "created_at": ap.created_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Công việc
# ---------------------------------------------------------------------------
@require_http_methods(["GET", "POST"])
@api_login_required
@_api_guard
def api_tasks(request):
    """`GET /api/v1/tasks/` — nhiệm vụ của tôi. `POST` — giao nhiệm vụ mới (`dept.task.assign`)."""
    if request.method == "GET":
        tasks = (
            ClubTask.objects.select_related("department", "recommended_skill")
            .filter(assignees__user=request.user, assignees__is_active=True)
            .distinct()[:100]
        )
        return api_ok([_serialize_task(t) for t in tasks])

    payload = _parse_json_body(request)
    dept = get_object_or_404(Department, pk=payload.get("department_id"), is_active=True)
    ids = payload.get("assignee_ids") or []
    if not isinstance(ids, list):
        raise GovernanceError("assignee_ids phải là mảng.")
    assignees = list(User.objects.filter(pk__in=ids))
    deadline = _parse_dt(payload.get("deadline"))
    if deadline is None:
        raise GovernanceError("Thiếu deadline.")
    task = create_and_assign_task(
        actor=request.user,
        department=dept,
        title=str(payload.get("title", "")),
        description=str(payload.get("description", "")),
        deadline=deadline,
        assignees=assignees,
        priority=str(payload.get("priority", "MEDIUM")),
        submission_mode=str(payload.get("submission_mode", "ANY_ONE")),
    )
    return api_ok(_serialize_task(task), status=201)


@require_GET
@api_login_required
@_api_guard
def api_task_detail(request, pk: int):
    task = get_object_or_404(ClubTask.objects.select_related("department"), pk=pk)
    if not can_view_club_task(request.user, task):
        raise PermissionDenied("Bạn không có quyền xem nhiệm vụ này.")
    data = _serialize_task(task)
    data["reviews"] = [
        {
            "id": r.id,
            "decision": r.decision,
            "quality_score": r.quality_score,
            "feedback": r.feedback,
            "reviewer": r.reviewer.public_name,
            "created_at": r.created_at.isoformat(),
        }
        for r in task.reviews.select_related("reviewer")
    ]
    return api_ok(data)


@require_POST
@api_login_required
@_api_guard
def api_task_progress(request, pk: int):
    task = get_object_or_404(ClubTask, pk=pk)
    payload = _parse_json_body(request)
    pct = payload.get("progress_percent")
    task = update_task_progress(
        actor=request.user,
        task=task,
        new_status=str(payload.get("status", "IN_PROGRESS")),
        progress_percent=int(pct) if pct is not None else None,
    )
    return api_ok(_serialize_task(task))


@require_POST
@api_login_required
@_api_guard
def api_task_submit(request, pk: int):
    """Nộp kết quả qua API (JSON — tệp đính kèm dùng giao diện Web multipart)."""
    task = get_object_or_404(ClubTask, pk=pk)
    payload = _parse_json_body(request)
    sub = submit_task_deliverable(
        actor=request.user,
        task=task,
        submission_note=str(payload.get("submission_note", "")),
        evidence_url=str(payload.get("evidence_url", "")),
    )
    return api_ok({"submission_id": sub.id, "is_late": sub.is_late, "task": _serialize_task(task)}, status=201)


@require_POST
@api_login_required
@_api_guard
def api_task_review(request, pk: int):
    task = get_object_or_404(ClubTask, pk=pk)
    payload = _parse_json_body(request)
    review = finalize_task_review(
        actor=request.user,
        task=task,
        decision=str(payload.get("decision", "")),
        quality_score=int(payload.get("quality_score", 5)),
        feedback=str(payload.get("feedback", "")),
    )
    return api_ok({"review_id": review.id, "decision": review.decision, "task": _serialize_task(task)}, status=201)


# ---------------------------------------------------------------------------
# Sự kiện CLB & RSVP
# ---------------------------------------------------------------------------
@require_GET
@api_login_required
@_api_guard
def api_club_events(request):
    PermissionEngine.require(request.user, "club.event.view_internal")
    qs = ClubEventProfile.objects.select_related("event", "policy_version")
    if not (
        PermissionEngine.authorize(request.user, "club.event.approve")
        or PermissionEngine.authorize(request.user, "club.overview.supervise")
    ):
        qs = qs.filter(
            approval_status__in=[
                ClubEventApprovalStatus.PUBLISHED,
                ClubEventApprovalStatus.ONGOING,
                ClubEventApprovalStatus.COMPLETED,
            ]
        )
    return api_ok([_serialize_club_event(ce, request.user) for ce in qs[:100]])


@require_POST
@api_login_required
@_api_guard
def api_club_event_rsvp(request, pk: int):
    ce = get_object_or_404(ClubEventProfile.objects.select_related("event"), pk=pk)
    payload = _parse_json_body(request)
    att = respond_event_rsvp(
        actor=request.user,
        club_event=ce,
        attending=bool(payload.get("attending", True)),
        decline_reason=str(payload.get("decline_reason", "")),
    )
    return api_ok({"club_event_id": ce.id, "rsvp_status": att.rsvp_status})


@require_POST
@api_login_required
@_api_guard
def api_club_event_review(request, pk: int):
    ce = get_object_or_404(ClubEventProfile.objects.select_related("event"), pk=pk)
    payload = _parse_json_body(request)
    ce = review_club_event(
        actor=request.user,
        club_event=ce,
        approved=bool(payload.get("approved", False)),
        review_note=str(payload.get("review_note", "")),
        auto_publish=bool(payload.get("auto_publish", False)),
    )
    return api_ok(_serialize_club_event(ce, request.user))


# ---------------------------------------------------------------------------
# Kỷ luật & Khiếu nại
# ---------------------------------------------------------------------------
@require_GET
@api_login_required
@_api_guard
def api_discipline_cases(request):
    if PermissionEngine.authorize(request.user, "club.member.suspend_temporary") or PermissionEngine.authorize(
        request.user, "club.overview.supervise"
    ):
        qs = DisciplineCase.objects.select_related("target_user")[:100]
    else:
        qs = DisciplineCase.objects.select_related("target_user").filter(target_user=request.user)
    return api_ok(
        [
            {
                "id": c.id,
                "target_user_id": c.target_user_id,
                "trigger_type": c.trigger_type,
                "status": c.status,
                "violation_count": c.violation_count,
                "threshold_applied": c.threshold_applied,
                "summary": c.summary,
                "evidence_snapshot": c.evidence_snapshot,
            }
            for c in qs
        ]
    )


@require_POST
@api_login_required
@_api_guard
def api_discipline_case_resolve(request, pk: int):
    case = get_object_or_404(DisciplineCase, pk=pk)
    payload = _parse_json_body(request)
    case = resolve_discipline_case(
        actor=request.user,
        case=case,
        new_status=str(payload.get("status", "")),
        resolution_note=str(payload.get("resolution_note", "")),
    )
    return api_ok({"id": case.id, "status": case.status})


@require_http_methods(["GET", "POST"])
@api_login_required
@_api_guard
def api_appeals(request):
    """`GET/POST /api/v1/appeals/` — mở cho cả thành viên đang SUSPENDED (whitelist trong LockedUserMiddleware)."""
    if request.method == "GET":
        return api_ok(
            [_serialize_appeal(a) for a in Appeal.objects.filter(appellant=request.user)[:50]]
        )
    payload = _parse_json_body(request)
    target_type = str(payload.get("target_type", AppealTargetType.MEMBERSHIP_SUSPENSION))
    d_case = None
    t_review = None
    if payload.get("discipline_case_id"):
        d_case = get_object_or_404(DisciplineCase, pk=payload["discipline_case_id"])
    if payload.get("task_review_id"):
        t_review = get_object_or_404(TaskReview, pk=payload["task_review_id"])
    appeal = submit_appeal(
        appellant=request.user,
        target_type=target_type,
        reason=str(payload.get("reason", "")),
        discipline_case=d_case,
        task_review=t_review,
        evidence_url=str(payload.get("evidence_url", "")),
    )
    return api_ok(_serialize_appeal(appeal), status=201)


@require_POST
@api_login_required
@_api_guard
def api_appeal_adjudicate(request, pk: int):
    if request.user.club_status == ClubMembershipStatus.SUSPENDED:
        raise PermissionDenied("Thành viên đang tạm khoá không thể thụ lý khiếu nại.")
    appeal = get_object_or_404(Appeal, pk=pk)
    payload = _parse_json_body(request)
    appeal = adjudicate_appeal(
        actor=request.user,
        appeal=appeal,
        decision_status=str(payload.get("status", "")),
        decision_note=str(payload.get("decision_note", "")),
    )
    return api_ok(_serialize_appeal(appeal))


# ---------------------------------------------------------------------------
# Thông báo chính thức & Tuỳ chọn nhận thông báo / Push PWA
# ---------------------------------------------------------------------------
@require_POST
@api_login_required
@_api_guard
def api_announcements(request):
    payload = _parse_json_body(request)
    dept = None
    if payload.get("department_id"):
        dept = get_object_or_404(Department, pk=payload["department_id"], is_active=True)
    ann = broadcast_announcement(
        actor=request.user,
        title=str(payload.get("title", "")),
        content=str(payload.get("content", "")),
        department=dept,
        is_pinned=bool(payload.get("is_pinned", False)),
        send_email=bool(payload.get("send_email", False)),
    )
    return api_ok({"id": ann.id, "recipient_count": ann.recipient_count}, status=201)


_PREF_FIELDS = ("email_important", "email_task_deadline", "email_event_rsvp", "web_push_enabled")


@require_http_methods(["GET", "POST"])
@api_login_required
@_api_guard
def api_notification_preferences(request):
    pref = get_or_create_notification_preference(request.user)
    if request.method == "POST":
        payload = _parse_json_body(request)
        for field in _PREF_FIELDS:
            if field in payload:
                setattr(pref, field, bool(payload[field]))
        pref.save()
    return api_ok({f: getattr(pref, f) for f in _PREF_FIELDS})


@require_POST
@api_login_required
@_api_guard
def api_push_subscribe(request):
    """Lưu Web Push Subscription chuẩn W3C (`{endpoint, keys:{p256dh, auth}}`)."""
    payload = _parse_json_body(request)
    endpoint = str(payload.get("endpoint", "")).strip()
    keys = payload.get("keys") or {}
    if not endpoint.startswith("https://") or not isinstance(keys, dict):
        raise GovernanceError("Push subscription không hợp lệ (endpoint phải là https).")
    p256dh = str(keys.get("p256dh", "")).strip()
    auth = str(keys.get("auth", "")).strip()
    if not p256dh or not auth:
        raise GovernanceError("Thiếu khoá p256dh / auth.")
    sub, created = PushSubscription.objects.update_or_create(
        user=request.user,
        endpoint=endpoint[:500],
        defaults={
            "p256dh": p256dh[:255],
            "auth": auth[:128],
            "user_agent": request.META.get("HTTP_USER_AGENT", "")[:255],
            "is_active": True,
        },
    )
    pref = get_or_create_notification_preference(request.user)
    if not pref.web_push_enabled:
        pref.web_push_enabled = True
        pref.save(update_fields=["web_push_enabled", "updated_at"])
    return api_ok({"id": sub.id, "created": created}, status=201 if created else 200)
