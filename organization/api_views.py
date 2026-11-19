"""
REST API `/api/v1/` — Chuẩn JSON Envelope thống nhất cho KMG Club Management Platform.

Mọi endpoint đều kiểm tra xác thực và phân quyền đa chiều qua `PermissionEngine` tại Backend.
"""
from __future__ import annotations

import json

from django.contrib.auth import login
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.forms import RegisterForm
from accounts.models import User, UserSession
from accounts.services import (
    OtpVerificationError,
    ensure_user_profile,
    issue_otp_challenge,
    mask_destination,
    record_login_session,
    resolve_post_login_url,
    revoke_user_session,
    verify_otp_challenge,
)
from core.security import is_rate_limited

from .models import (
    Appointment,
    Department,
    DepartmentMembership,
    DeptMembershipStatus,
    LifecycleEventType,
    PermissionGrant,
    Position,
    ResourceAccessRule,
    Skill,
    SkillProficiency,
    UserSkill,
    serialize_member_contact_for_viewer,
)
from .permissions import PermissionEngine, api_login_required
from .services import (
    GovernanceError,
    appoint_officer,
    approve_club_member,
    declare_user_skill,
    end_appointment,
    grant_delegated_permissions,
    record_lifecycle_event,
    revoke_permission_grant,
    server_admin_assign_leadership,
    verify_user_skill,
)


def api_ok(data, status: int = 200) -> JsonResponse:
    return JsonResponse(
        {
            "ok": True,
            "data": data,
            "meta": {"timestamp": timezone.localtime().isoformat()},
        },
        status=status,
    )


def api_error(
    code: str,
    message: str,
    status: int = 400,
    details: dict | None = None,
) -> JsonResponse:
    return JsonResponse(
        {
            "ok": False,
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
            },
        },
        status=status,
    )


def _parse_json_body(request) -> dict:
    if not request.body:
        return {}
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise GovernanceError("Dữ liệu JSON gửi lên không hợp lệ.") from exc
    if not isinstance(payload, dict):
        raise GovernanceError("Body JSON phải là một object.")
    return payload


@require_GET
@api_login_required
def api_auth_me(request):
    """`GET /api/v1/auth/me/` — Hồ sơ, trạng thái kép, OTP, danh sách Ban, chức vụ và route điều hướng."""
    user = request.user
    ctx = PermissionEngine.summarize_actor_context(user)
    return api_ok(
        {
            "id": user.id,
            "username": user.username,
            "display_name": user.public_name,
            "full_name": user.full_name,
            "mssv": user.mssv,
            "email": user.email,
            "phone": user.phone,
            "email_verified": user.is_email_verified,
            "phone_verified": user.is_phone_verified,
            "otp_verified": user.is_otp_verified,
            "account_status": user.account_status,
            "has_active_club_access": user.has_active_club_access,
            "authz_version": user.authz_version,
            "post_login_url": resolve_post_login_url(user),
            **ctx,
        }
    )


@require_POST
def api_auth_register(request):
    """
    `POST /api/v1/auth/register/` — Đăng ký tài khoản qua Email hoặc SĐT:
    - Mặc định tài khoản ở chế độ Khách (`club_status == 'GUEST'`, `has_active_club_access == False`).
    - Tự động phát hành mã OTP 6 chữ số qua Email hoặc SMS.
    """
    if is_rate_limited(request, scope="api_auth_register", limit=10, window_seconds=600):
        return api_error(
            "RATE_LIMITED",
            "Bạn gửi yêu cầu đăng ký quá nhanh. Vui lòng thử lại sau.",
            status=429,
        )
    try:
        payload = _parse_json_body(request)
    except GovernanceError as exc:
        return api_error(exc.code, str(exc), status=400)

    pw = str(payload.get("password") or payload.get("password1") or "")
    pw2 = str(payload.get("password2") or pw)
    form_data = {
        "full_name": str(payload.get("full_name") or ""),
        "email": str(payload.get("email") or ""),
        "phone": str(payload.get("phone") or ""),
        "otp_channel": str(payload.get("otp_channel") or "AUTO"),
        "username": str(payload.get("username") or ""),
        "mssv": str(payload.get("mssv") or ""),
        "password1": pw,
        "password2": pw2,
    }
    form = RegisterForm(data=form_data)
    if not form.is_valid():
        flat_errors = {k: [str(msg) for msg in v] for k, v in form.errors.items()}
        first_msg = next(iter(flat_errors.values()))[0] if flat_errors else "Dữ liệu không hợp lệ."
        return api_error("VALIDATION_ERROR", first_msg, status=400, details=flat_errors)

    user = form.save()
    ensure_user_profile(user)
    record_lifecycle_event(
        user=user,
        event_type=LifecycleEventType.REGISTERED,
        actor=user,
        title="Đăng ký tài khoản qua API (Mặc định: Khách)",
        note=f"Username: {user.username}",
    )
    login(request, user)
    record_login_session(request, user)
    try:
        challenge, _ = issue_otp_challenge(
            user=user,
            channel=form.cleaned_data.get("resolved_otp_channel"),
            request=request,
        )
    except OtpVerificationError as exc:
        # Tài khoản đã được tạo. HTTP 5xx sẽ ngăn SessionMiddleware lưu phiên
        # đăng nhập mới, khiến người dùng không gọi được endpoint gửi lại OTP.
        return api_ok(
            {
                "user_id": user.id,
                "username": user.username,
                "account_status": user.account_status,
                "club_status": user.club_status,
                "has_active_club_access": user.has_active_club_access,
                "otp_sent": False,
                "delivery_error": {"code": exc.code, "message": str(exc)},
                "retry_url": "/api/v1/auth/otp/send/",
            },
            status=201,
        )
    return api_ok(
        {
            "user_id": user.id,
            "username": user.username,
            "account_status": user.account_status,
            "club_status": user.club_status,
            "has_active_club_access": user.has_active_club_access,
            "otp_sent": True,
            "otp_channel": challenge.channel,
            "masked_destination": mask_destination(challenge.channel, challenge.destination),
            "expires_at": challenge.expires_at.isoformat(),
        },
        status=201,
    )


@require_POST
@api_login_required
def api_auth_otp_send(request):
    """`POST /api/v1/auth/otp/send/` — Yêu cầu phát hành / gửi lại mã OTP 6 chữ số qua Email hoặc SMS."""
    if is_rate_limited(
        request,
        scope="api_auth_otp_send",
        limit=5,
        window_seconds=600,
        identifier=str(request.user.pk),
    ):
        return api_error(
            "RATE_LIMITED",
            "Bạn đã yêu cầu gửi mã OTP quá nhiều lần liên tiếp. Vui lòng thử lại sau ít phút.",
            status=429,
        )
    try:
        payload = _parse_json_body(request)
        channel = str(payload.get("channel") or "").strip().upper() or None
        challenge, _ = issue_otp_challenge(
            user=request.user,
            channel=channel,
            request=request,
        )
        return api_ok(
            {
                "otp_channel": challenge.channel,
                "masked_destination": mask_destination(
                    challenge.channel, challenge.destination
                ),
                "expires_at": challenge.expires_at.isoformat(),
            }
        )
    except OtpVerificationError as exc:
        return api_error(exc.code, str(exc), status=exc.status_code)
    except GovernanceError as exc:
        return api_error(exc.code, str(exc), status=400)


@require_POST
@api_login_required
def api_auth_otp_verify(request):
    """
    `POST /api/v1/auth/otp/verify/` — Xác minh mã OTP 6 chữ số qua SMS hoặc Email.
    Lưu ý: Sau khi xác minh OTP thành công, tài khoản kỹ thuật lên `ACTIVE`,
    nhưng tư cách CLB vẫn giữ mặc định là Khách (`club_status == 'GUEST'`) cho tới khi
    được Chủ nhiệm / Phó chủ nhiệm nâng role & phân Ban!
    """
    try:
        payload = _parse_json_body(request)
        raw_code = str(payload.get("code") or "")
        channel = str(payload.get("channel") or "").strip().upper() or None
        verified = verify_otp_challenge(
            user=request.user,
            raw_code=raw_code,
            channel=channel,
        )
        request.user.refresh_from_db()
        return api_ok(
            {
                "verified_channel": verified.channel,
                "account_status": request.user.account_status,
                "email_verified": request.user.is_email_verified,
                "phone_verified": request.user.is_phone_verified,
                "club_status": request.user.club_status,
                "has_active_club_access": request.user.has_active_club_access,
                "post_login_url": resolve_post_login_url(request.user),
            }
        )
    except OtpVerificationError as exc:
        status_code = 429 if exc.code == "OTP_LOCKED" else 400
        return api_error(exc.code, str(exc), status=status_code)
    except GovernanceError as exc:
        return api_error(exc.code, str(exc), status=400)


@require_GET
@api_login_required
def api_auth_sessions(request):
    """`GET /api/v1/auth/sessions/` — Danh sách phiên thiết bị của chính người dùng."""
    cur_key = request.session.session_key
    sessions = [
        {
            "id": s.id,
            "device_label": s.device_label,
            "ip_address": s.ip_address,
            "last_seen_at": s.last_seen_at.isoformat(),
            "is_current": s.session_key == cur_key,
            "is_active": s.is_active_session,
            "revoked_at": s.revoked_at.isoformat() if s.revoked_at else None,
        }
        for s in request.user.device_sessions.all()[:20]
    ]
    return api_ok({"sessions": sessions})


@require_POST
@api_login_required
def api_auth_session_revoke(request, pk: int):
    """`POST /api/v1/auth/sessions/<pk>/revoke/` — Thu hồi từ xa 1 thiết bị của chính mình."""
    session_obj = UserSession.objects.filter(pk=pk, user=request.user).first()
    if session_obj is None:
        return api_error("NOT_FOUND", "Không tìm thấy phiên thiết bị.", status=404)
    if session_obj.session_key == request.session.session_key:
        return api_error(
            "VALIDATION_ERROR",
            "Không thể thu hồi phiên hiện tại qua API này; hãy gọi đăng xuất.",
            status=400,
        )
    revoke_user_session(request.user, session_obj)
    return api_ok({"revoked_session_id": session_obj.id})


@require_GET
@api_login_required
def api_departments_list(request):
    """`GET /api/v1/departments/` — Danh sách các Ban KMG kèm `access_mode` theo người gọi."""
    if not request.user.has_active_club_access:
        return api_error(
            "PERMISSION_DENIED",
            "Chỉ thành viên chính thức, cán bộ hoặc cố vấn CLB mới truy cập được danh sách nội bộ.",
            status=403,
        )
    items = []
    for d in Department.objects.filter(is_active=True):
        items.append(
            {
                "id": d.id,
                "code": d.code,
                "name": d.name,
                "slug": d.slug,
                "short_description": d.short_description,
                "is_demo": d.is_demo,
                "custom_categories": d.custom_categories,
                "access_mode": PermissionEngine.get_department_access_mode(
                    request.user, d
                ),
                "active_member_count": d.memberships.filter(
                    status=DeptMembershipStatus.ACTIVE
                ).count(),
            }
        )
    return api_ok({"departments": items})


@require_GET
@api_login_required
def api_department_detail(request, slug: str):
    """`GET /api/v1/departments/<slug>/` — Thông tin chi tiết Ban & quyền hạn trong ngữ cảnh Ban."""
    dept = Department.objects.filter(slug=slug, is_active=True).first()
    if dept is None:
        return api_error("NOT_FOUND", "Không tìm thấy Ban.", status=404)
    if not PermissionEngine.authorize(request.user, "dept.page.view", department=dept):
        return api_error(
            "PERMISSION_DENIED",
            f"Bạn không có quyền xem trang {dept.name}.",
            status=403,
        )
    mode = PermissionEngine.get_department_access_mode(request.user, dept)
    officers = [
        {
            "user_id": a.user_id,
            "display_name": a.user.public_name,
            "position_code": a.position.code,
            "position_name": a.position.name,
            "term_label": a.term_label,
        }
        for a in Appointment.objects.select_related("user", "position").filter(
            department=dept, is_active=True, ended_at__isnull=True
        )
    ]
    return api_ok(
        {
            "id": dept.id,
            "code": dept.code,
            "name": dept.name,
            "slug": dept.slug,
            "description": dept.description,
            "is_demo": dept.is_demo,
            "custom_categories": dept.custom_categories,
            "access_mode": mode,
            "officers": officers,
            "capabilities": {
                "can_assign_tasks": PermissionEngine.authorize(
                    request.user, "dept.task.assign", department=dept
                ),
                "can_approve_tasks": PermissionEngine.authorize(
                    request.user, "dept.task.approve", department=dept
                ),
                "can_manage_members": PermissionEngine.authorize(
                    request.user, "dept.member.manage", department=dept
                ),
                "can_appoint_deputy": PermissionEngine.authorize(
                    request.user, "dept.deputy.appoint", department=dept
                ),
                "can_verify_skills": PermissionEngine.authorize(
                    request.user, "dept.skill.verify", department=dept
                ),
            },
        }
    )


@require_GET
@api_login_required
def api_department_members(request, slug: str):
    """`GET /api/v1/departments/<slug>/members/` — Nhân sự Ban có che PII theo cài đặt riêng tư."""
    dept = Department.objects.filter(slug=slug, is_active=True).first()
    if dept is None:
        return api_error("NOT_FOUND", "Không tìm thấy Ban.", status=404)
    if not PermissionEngine.authorize(request.user, "dept.roster.view", department=dept):
        return api_error(
            "PERMISSION_DENIED",
            f"Bạn không có quyền xem nhân sự {dept.name}.",
            status=403,
        )
    can_manage = PermissionEngine.authorize(
        request.user, "dept.member.manage", department=dept
    )
    members = []
    for dm in (
        DepartmentMembership.objects.select_related(
            "user", "user__profile", "user__club_membership"
        )
        .filter(department=dept, status=DeptMembershipStatus.ACTIVE)
        .order_by("user__full_name")
    ):
        contact = serialize_member_contact_for_viewer(
            request.user, dm.user, can_manage_target=can_manage
        )
        cm = dm.user.club_membership_record
        members.append(
            {
                "user_id": dm.user_id,
                "member_code": cm.member_code if cm else None,
                "display_name": dm.user.public_name,
                "joined_at": dm.joined_at.isoformat(),
                **contact,
            }
        )
    return api_ok(
        {
            "department": dept.slug,
            "access_mode": PermissionEngine.get_department_access_mode(
                request.user, dept
            ),
            "members": members,
        }
    )


@require_POST
@api_login_required
def api_appointments_create(request):
    """`POST /api/v1/appointments/` — Bổ nhiệm chức vụ mới (kiểm tra singleton & phân quyền)."""
    try:
        payload = _parse_json_body(request)
        target = get_object_or_404(User, pk=payload.get("user_id"))
        position = Position.objects.filter(code=payload.get("position_code")).first()
        if position is None:
            return api_error("VALIDATION_ERROR", "Mã chức vụ không hợp lệ.", status=400)
        dept = None
        if payload.get("department_id"):
            dept = get_object_or_404(Department, pk=payload["department_id"])

        appt = appoint_officer(
            actor=request.user,
            target_user=target,
            position=position,
            department=dept,
            term_label=str(payload.get("term_label", "2026-2027")),
            title_note=str(payload.get("title_note", "")),
        )
        return api_ok(
            {
                "id": appt.id,
                "user_id": appt.user_id,
                "position_code": appt.position.code,
                "department_id": appt.department_id,
                "singleton_active_key": appt.singleton_active_key,
            },
            status=201,
        )
    except PermissionDenied as exc:
        return api_error("PERMISSION_DENIED", str(exc), status=403)
    except ValidationError as exc:
        return api_error("VALIDATION_ERROR", "; ".join(exc.messages), status=400)
    except GovernanceError as exc:
        status_code = 409 if exc.code == "CONFLICT_SINGLETON" else 400
        return api_error(exc.code, str(exc), status=status_code)


@require_POST
@api_login_required
def api_appointment_end(request, pk: int):
    """`POST /api/v1/appointments/<pk>/end/` — Kết thúc nhiệm kỳ & thu hồi quyền tức thời."""
    appt = Appointment.objects.select_related("user", "position", "department").filter(pk=pk).first()
    if appt is None:
        return api_error("NOT_FOUND", "Không tìm thấy quyết định bổ nhiệm.", status=404)
    try:
        payload = _parse_json_body(request)
        end_appointment(
            actor=request.user,
            appointment=appt,
            reason=str(payload.get("reason", "Kết thúc nhiệm kỳ")),
        )
        return api_ok(
            {
                "id": appt.id,
                "is_active": appt.is_active,
                "ended_at": appt.ended_at.isoformat() if appt.ended_at else None,
            }
        )
    except PermissionDenied as exc:
        return api_error("PERMISSION_DENIED", str(exc), status=403)
    except GovernanceError as exc:
        return api_error(exc.code, str(exc), status=400)


@require_http_methods(["GET", "POST"])
@api_login_required
def api_permission_grants(request):
    """`GET / POST /api/v1/permission-grants/` — Danh sách hoặc tạo gói quyền ủy quyền."""
    if request.method == "GET":
        grants = PermissionEngine.get_active_grants(request.user)
        return api_ok(
            {
                "grants": [
                    {
                        "id": g.id,
                        "bundle_code": g.bundle_code,
                        "bundle_label": g.get_bundle_code_display(),
                        "department_id": g.department_id,
                        "expires_at": g.expires_at.isoformat() if g.expires_at else None,
                    }
                    for g in grants
                ]
            }
        )
    try:
        payload = _parse_json_body(request)
        appt = Appointment.objects.select_related(
            "user", "position", "department"
        ).filter(pk=payload.get("appointment_id")).first()
        if appt is None:
            return api_error("NOT_FOUND", "Không tìm thấy quyết định bổ nhiệm.", status=404)
        dept = appt.department
        if payload.get("department_id") and dept is None:
            dept = Department.objects.filter(pk=payload["department_id"]).first()
        grant = grant_delegated_permissions(
            actor=request.user,
            bound_appointment=appt,
            bundle_code=str(payload.get("bundle_code", "")),
            department=dept,
            reason=str(payload.get("reason", "Ủy quyền qua API")),
            custom_permission_codes=payload.get("custom_permissions") or None,
        )
        return api_ok(
            {
                "id": grant.id,
                "grantee_id": grant.grantee_id,
                "bundle_code": grant.bundle_code,
            },
            status=201,
        )
    except PermissionDenied as exc:
        return api_error("PERMISSION_DENIED", str(exc), status=403)
    except GovernanceError as exc:
        return api_error(exc.code, str(exc), status=400)


@require_POST
@api_login_required
def api_permission_grant_revoke(request, pk: int):
    """`POST /api/v1/permission-grants/<pk>/revoke/` — Thu hồi gói quyền ủy quyền ngay lập tức."""
    grant = PermissionGrant.objects.select_related(
        "grantee", "bound_appointment__position", "department"
    ).filter(pk=pk).first()
    if grant is None:
        return api_error("NOT_FOUND", "Không tìm thấy bản ghi ủy quyền.", status=404)
    try:
        payload = _parse_json_body(request)
        revoke_permission_grant(
            actor=request.user,
            grant=grant,
            reason=str(payload.get("reason", "Thu hồi ủy quyền")),
        )
        return api_ok({"id": grant.id, "is_active": grant.is_active})
    except PermissionDenied as exc:
        return api_error("PERMISSION_DENIED", str(exc), status=403)
    except GovernanceError as exc:
        return api_error(exc.code, str(exc), status=400)


@require_http_methods(["GET", "POST"])
@api_login_required
def api_my_skills(request):
    """`GET / POST /api/v1/skills/me/` — Xem hoặc khai báo kỹ năng cá nhân."""
    if not request.user.has_active_club_access:
        return api_error(
            "PERMISSION_DENIED",
            "Chức năng hồ sơ kỹ năng dành cho thành viên CLB KMG.",
            status=403,
        )
    if request.method == "GET":
        skills = [
            {
                "id": us.id,
                "skill_code": us.skill.code,
                "skill_name": us.skill.name,
                "category": us.skill.category.name,
                "proficiency": us.proficiency,
                "verification_status": us.verification_status,
                "verified_by": us.verified_by.public_name if us.verified_by else None,
            }
            for us in request.user.user_skills.select_related(
                "skill__category", "verified_by"
            )
        ]
        return api_ok({"skills": skills})

    try:
        payload = _parse_json_body(request)
        skill = Skill.objects.filter(code=payload.get("skill_code"), is_active=True).first()
        if skill is None:
            return api_error("VALIDATION_ERROR", "Mã kỹ năng không tồn tại.", status=400)
        proficiency = str(payload.get("proficiency", SkillProficiency.BEGINNER))
        if proficiency not in SkillProficiency.values:
            return api_error("VALIDATION_ERROR", "Mức độ thành thạo không hợp lệ.", status=400)
        us = declare_user_skill(
            user=request.user,
            skill=skill,
            proficiency=proficiency,
            experience_note=str(payload.get("experience_note", "")),
            evidence_url=str(payload.get("evidence_url", "")),
        )
        return api_ok(
            {
                "id": us.id,
                "skill_code": skill.code,
                "verification_status": us.verification_status,
            },
            status=201,
        )
    except GovernanceError as exc:
        return api_error(exc.code, str(exc), status=400)


@require_POST
@api_login_required
def api_verify_user_skill(request, pk: int):
    """`POST /api/v1/skills/user-skills/<pk>/verify/` — Xác minh kỹ năng thành viên."""
    us = UserSkill.objects.select_related("user", "skill").filter(pk=pk).first()
    if us is None:
        return api_error("NOT_FOUND", "Không tìm thấy hồ sơ kỹ năng.", status=404)
    try:
        payload = _parse_json_body(request)
        dept = Department.objects.filter(pk=payload.get("department_id")).first()
        if dept is None:
            return api_error("VALIDATION_ERROR", "Phải chỉ định department_id.", status=400)
        verify_user_skill(
            actor=request.user,
            user_skill=us,
            department=dept,
            approved=bool(payload.get("approved", True)),
            review_note=str(payload.get("review_note", "")),
        )
        return api_ok(
            {
                "id": us.id,
                "verification_status": us.verification_status,
            }
        )
    except PermissionDenied as exc:
        return api_error("PERMISSION_DENIED", str(exc), status=403)
    except GovernanceError as exc:
        return api_error(exc.code, str(exc), status=400)


@require_GET
@api_login_required
def api_member_lifecycle(request, user_id: int):
    """`GET /api/v1/members/<user_id>/lifecycle/` — Dòng thời gian lịch sử bất biến."""
    target = User.objects.filter(pk=user_id).first()
    if target is None:
        return api_error("NOT_FOUND", "Không tìm thấy thành viên.", status=404)

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
        return api_error(
            "PERMISSION_DENIED",
            "Bạn không có quyền truy cập lịch sử thành viên này.",
            status=403,
        )

    events = [
        {
            "id": ev.id,
            "event_type": ev.event_type,
            "event_type_label": ev.get_event_type_display(),
            "title": ev.title,
            "department": ev.department.name if ev.department_id else None,
            "actor": ev.actor.public_name if ev.actor_id else None,
            "note": ev.note,
            "created_at": ev.created_at.isoformat(),
        }
        for ev in target.lifecycle_events.select_related("department", "actor")
    ]
    return api_ok({"user_id": target.id, "display_name": target.public_name, "events": events})


@require_GET
@api_login_required
def api_resource_access_check(request, resource_code: str):
    """`GET /api/v1/resources/<resource_code>/access-check/` — Kiểm tra quyền truy cập tài liệu ACL."""
    rule = ResourceAccessRule.objects.select_related("department", "recommended_skill").filter(
        resource_code=resource_code
    ).first()
    if rule is None:
        return api_error("NOT_FOUND", "Không tìm thấy tài nguyên.", status=404)
    if not PermissionEngine.can_access_resource(request.user, rule):
        return api_error(
            "PERMISSION_DENIED",
            f"Bạn không được cấp quyền ACL cho tài liệu mật '{rule.title}'. "
            f"(Lưu ý: Có kỹ năng chuyên môn không tự động mở khoá tài liệu mật).",
            status=403,
        )
    return api_ok(
        {
            "resource_code": rule.resource_code,
            "title": rule.title,
            "classification": rule.classification,
            "access_granted": True,
        }
    )


@require_POST
@api_login_required
def api_members_promote(request):
    """
    `POST /api/v1/members/promote/` — Chủ nhiệm hoặc Phó chủ nhiệm nâng role tài khoản Khách (`Guest`)
    lên Thành viên chính thức (`ACTIVE`) VÀ phân vào >= 1 Ban (`department_ids`) để mở chức năng Thành viên.
    """
    try:
        payload = _parse_json_body(request)
        target = User.objects.filter(pk=payload.get("user_id")).first()
        if target is None:
            return api_error("NOT_FOUND", "Không tìm thấy tài khoản người dùng.", status=404)
        dept_ids = payload.get("department_ids") or []
        if isinstance(dept_ids, int):
            dept_ids = [dept_ids]
        if not dept_ids and payload.get("department_id"):
            dept_ids = [payload["department_id"]]
        departments = list(Department.objects.filter(pk__in=dept_ids, is_active=True))
        cm = approve_club_member(
            actor=request.user,
            target_user=target,
            departments=departments,
            note=str(payload.get("note") or "Nâng role Thành viên & phân Ban"),
        )
        return api_ok(
            {
                "user_id": target.id,
                "member_code": cm.member_code,
                "club_status": cm.status,
                "has_active_club_access": target.has_active_club_access,
                "departments": [
                    {"id": d.id, "code": d.code, "name": d.name, "slug": d.slug}
                    for d in departments
                ],
            },
            status=201,
        )
    except PermissionDenied as exc:
        return api_error("PERMISSION_DENIED", str(exc), status=403)
    except GovernanceError as exc:
        return api_error(exc.code, str(exc), status=400)


@require_POST
@api_login_required
def api_admin_assign_leadership(request):
    """
    `POST /api/v1/admin/leadership/` — ĐỘC QUYỀN Admin Server ("admin server là tôi"):
    Nâng cấp một tài khoản đã đăng ký lên `CHAIRMAN` (Chủ nhiệm), `VICE_CHAIRMAN` (Phó CN),
    `DEPT_HEAD` (Trưởng ban + `department_id`), hoặc `ADVISOR` (Cố vấn).
    Mọi vai trò khác (kể cả Chủ nhiệm CLB!) gọi endpoint này đều bị chặn `403 PERMISSION_DENIED`.
    """
    try:
        payload = _parse_json_body(request)
        target = User.objects.filter(pk=payload.get("user_id")).first()
        if target is None:
            return api_error("NOT_FOUND", "Không tìm thấy tài khoản người dùng.", status=404)
        dept = None
        if payload.get("department_id"):
            dept = Department.objects.filter(
                pk=payload["department_id"], is_active=True
            ).first()
            if dept is None:
                return api_error("NOT_FOUND", "Không tìm thấy Ban đã chọn.", status=404)
        appt = server_admin_assign_leadership(
            actor=request.user,
            target_user=target,
            position_code=str(payload.get("position_code") or "").strip(),
            department=dept,
            portfolios=payload.get("portfolios") or None,
            term_label=str(payload.get("term_label") or "2026-2027"),
            title_note=str(payload.get("title_note") or ""),
            replace_existing=bool(payload.get("replace_existing", False)),
        )
        return api_ok(
            {
                "appointment_id": appt.id,
                "user_id": target.id,
                "position_code": appt.position.code,
                "position_name": appt.position.name,
                "department_id": appt.department_id,
                "club_status": target.club_status,
                "has_active_club_access": target.has_active_club_access,
            },
            status=201,
        )
    except PermissionDenied as exc:
        return api_error("PERMISSION_DENIED", str(exc), status=403)
    except ValidationError as exc:
        return api_error("VALIDATION_ERROR", "; ".join(exc.messages), status=400)
    except GovernanceError as exc:
        status_code = 409 if exc.code == "CONFLICT_SINGLETON" else 400
        return api_error(exc.code, str(exc), status=status_code)
