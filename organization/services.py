"""
Tầng Nghiệp vụ Tổ chức, Nhân sự Đa Ban, Bổ nhiệm, Ủy quyền & Lịch sử Thành viên.

Mọi thao tác thay đổi trạng thái tổ chức đều:
1. Kiểm tra `PermissionEngine` tại Backend.
2. Thực thi trong `transaction.atomic()` với khóa dòng chống race condition.
3. Ghi Sổ cái bất biến `MemberLifecycleEvent` (Chỉ thị 3.2) và `AuditLog`.
4. Tăng `User.authz_version` để thu hồi/cập nhật quyền tức thời (`INV-06`).
"""
from __future__ import annotations

from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import AuditLog, Role, User

from .models import (
    ApplicationStatus,
    Appointment,
    ClubMembership,
    ClubMembershipStatus,
    Department,
    DepartmentMembership,
    DeptMembershipStatus,
    GrantBundleCode,
    LifecycleEventType,
    MemberLifecycleEvent,
    MembershipApplication,
    Permission,
    PermissionGrant,
    PolicyVersion,
    Position,
    PositionCode,
    PositionPermission,
    ScopeType,
    Skill,
    SkillCategory,
    SkillVerificationStatus,
    UserSkill,
)
from .permissions import (
    DEPUTY_HEAD_BASELINE_PERMISSIONS,
    DEPUTY_HEAD_BUNDLE_PERMISSIONS,
    DEPT_HEAD_OWN_DEPT_PERMISSIONS,
    MEMBER_IN_OWN_DEPT_PERMISSIONS,
    PERMISSIONS_CATALOG,
    PermissionEngine,
    SERVER_ADMIN_EXCLUSIVE_PERMISSIONS,
    VICE_CHAIRMAN_BASELINE_PERMISSIONS,
    VICE_CHAIRMAN_PORTFOLIO_PERMISSIONS,
)


class GovernanceError(Exception):
    """Lỗi vi phạm quy tắc nghiệp vụ tổ chức / phân quyền CLB."""

    def __init__(self, message: str, code: str = "VALIDATION_ERROR"):
        super().__init__(message)
        self.code = code


def record_lifecycle_event(
    user: User,
    event_type: str,
    title: str,
    actor: User | None = None,
    department: Department | None = None,
    note: str = "",
    metadata: dict | None = None,
) -> MemberLifecycleEvent:
    """Ghi một mốc bất biến vào lịch sử vòng đời thành viên (Chỉ thị 3.2)."""
    return MemberLifecycleEvent.objects.create(
        user=user,
        event_type=event_type,
        department=department,
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        title=title[:200],
        note=(note or "")[:255],
        metadata=metadata or {},
    )


def _generate_next_member_code(year: int | None = None) -> str:
    """Sinh mã thành viên tuần tự `KMG-YYYY-NNNN` an toàn trong transaction."""
    yr = year or timezone.localdate().year
    prefix = f"KMG-{yr}-"
    last = (
        ClubMembership.objects.select_for_update()
        .filter(member_code__startswith=prefix)
        .order_by("-member_code")
        .first()
    )
    seq = 1
    if last:
        tail = last.member_code[len(prefix):]
        if tail.isdigit():
            seq = int(tail) + 1
    return f"{prefix}{seq:04d}"


@transaction.atomic
def bootstrap_organization_catalog() -> dict:
    """
    Khởi tạo (idempotent) toàn bộ danh mục chuẩn của KMG Platform:
    - 3 Ban dự kiến (Truyền thông sự kiện, Chuyên môn, Kỹ thuật [Demo]).
    - 6 Chức vụ chuẩn & toàn bộ mã quyền nguyên tử `D04 v1.1`.
    - Danh mục Kỹ năng nghệ thuật/kỹ thuật.
    - Chính sách vận hành v1 (bao gồm Quyết định A3 cho RSVP Sự kiện cấp CLB).
    """
    dept_specs = [
        (
            "MEDIA_EVENT",
            "Ban Truyền thông sự kiện",
            "truyen-thong-su-kien",
            "Phụ trách hình ảnh thương hiệu, truyền thông đa kênh, kịch bản và điều phối sự kiện âm nhạc.",
            "bi-megaphone",
            False,
            ["Ấn phẩm Poster", "Quay dựng Recap", "Kịch bản Sân khấu", "Đối ngoại & Tài trợ"],
            1,
        ),
        (
            "SPECIALTY",
            "Ban Chuyên môn",
            "chuyen-mon",
            "Trái tim nghệ thuật của KMG: đào tạo thanh nhạc, nhạc cụ, hòa âm phối khí và dàn dựng tiết mục.",
            "bi-music-note-beamed",
            False,
            ["Vocal", "Guitar & Bass", "Keyboard", "Drums & Percussion", "Hòa âm Band"],
            2,
        ),
        (
            "TECHNICAL",
            "Ban Kỹ thuật",
            "ky-thuat",
            "Phụ trách âm thanh live (FOH/Monitor), ánh sáng sân khấu, thu âm và hạ tầng thiết bị biểu diễn.",
            "bi-sliders",
            True,
            ["Sound Mixing", "Ánh sáng Sân khấu", "Livestream & Thu âm", "Bảo trì Thiết bị"],
            3,
        ),
    ]
    departments = {}
    for code, name, slug, desc, icon, is_demo, cats, order in dept_specs:
        # Không ghi đè tên, cấu hình hoặc trạng thái Ban đã được quản trị viên sửa.
        dept, _ = Department.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "slug": slug,
                "short_description": desc,
                "description": desc,
                "icon": icon,
                "is_demo": is_demo,
                "custom_categories": cats,
                "display_order": order,
            },
        )
        departments[code] = dept

    pos_specs = [
        (PositionCode.CHAIRMAN, "Chủ nhiệm CLB", ScopeType.CLUB, True, True, False, 1),
        (PositionCode.VICE_CHAIRMAN, "Phó chủ nhiệm CLB", ScopeType.CLUB, True, False, False, 2),
        (PositionCode.ADVISOR, "Cố vấn CLB", ScopeType.CLUB, False, False, True, 3),
        (PositionCode.DEPT_HEAD, "Trưởng ban", ScopeType.DEPARTMENT, True, True, False, 4),
        (PositionCode.DEPUTY_HEAD, "Phó ban", ScopeType.DEPARTMENT, True, False, False, 5),
        (PositionCode.CORE_MEMBER, "Thành viên nòng cốt", ScopeType.DEPARTMENT, False, False, False, 6),
    ]
    positions = {}
    for code, name, scope, is_officer, is_singleton, is_ro, rank in pos_specs:
        pos, _ = Position.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "scope_type": scope,
                "is_officer": is_officer,
                "is_singleton": is_singleton,
                "is_read_only": is_ro,
                "rank_order": rank,
            },
        )
        positions[code] = pos

    perm_objs = {}
    for code, name, module, scope, is_mut in PERMISSIONS_CATALOG:
        perm, _ = Permission.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "module": module,
                "scope_type": scope,
                "is_mutation": is_mut,
            },
        )
        perm_objs[code] = perm

    # Gắn quyền mặc định vào bảng PositionPermission để tra cứu minh bạch trên DB
    # Lưu ý: SERVER_ADMIN_EXCLUSIVE_PERMISSIONS chỉ thuộc về Admin Server, không gán cho Chủ nhiệm!
    baseline_map = {
        PositionCode.CHAIRMAN: set(perm_objs.keys()) - set(SERVER_ADMIN_EXCLUSIVE_PERMISSIONS),
        PositionCode.VICE_CHAIRMAN: set(VICE_CHAIRMAN_BASELINE_PERMISSIONS),
        PositionCode.DEPT_HEAD: set(DEPT_HEAD_OWN_DEPT_PERMISSIONS),
        PositionCode.DEPUTY_HEAD: set(DEPUTY_HEAD_BASELINE_PERMISSIONS),
        PositionCode.CORE_MEMBER: set(MEMBER_IN_OWN_DEPT_PERMISSIONS),
    }
    PositionPermission.objects.filter(
        position=positions[PositionCode.CHAIRMAN],
        permission__code__in=SERVER_ADMIN_EXCLUSIVE_PERMISSIONS,
    ).delete()
    for pos_code, codes in baseline_map.items():
        pos = positions[pos_code]
        for p_code in codes:
            if p_code in perm_objs:
                PositionPermission.objects.get_or_create(
                    position=pos,
                    permission=perm_objs[p_code],
                )

    # Danh mục Kỹ năng KMG
    skill_tree = [
        (
            "VOCAL",
            "Thanh nhạc (Vocal)",
            departments["SPECIALTY"],
            1,
            [
                ("VOCAL_LEAD", "Lead Vocal"),
                ("VOCAL_HARMONY", "Bè / Harmony"),
                ("RAP", "Rap / Spoken Word"),
            ],
        ),
        (
            "INSTRUMENT",
            "Nhạc cụ biểu diễn",
            departments["SPECIALTY"],
            2,
            [
                ("GUITAR_ACOUSTIC", "Guitar Acoustic"),
                ("GUITAR_ELECTRIC", "Guitar Electric"),
                ("BASS", "Guitar Bass"),
                ("PIANO_KEYBOARD", "Piano / Keyboard"),
                ("DRUMS_CAJON", "Trống (Drums / Cajon)"),
                ("VIOLIN", "Violin"),
            ],
        ),
        (
            "MEDIA_PROD",
            "Truyền thông & Sản xuất sự kiện",
            departments["MEDIA_EVENT"],
            3,
            [
                ("GRAPHIC_DESIGN", "Thiết kế Đồ hoạ / Poster"),
                ("PHOTO_VIDEO", "Chụp ảnh & Quay dựng"),
                ("CONTENT_COPY", "Sáng tạo Nội dung / Kịch bản"),
                ("STAGE_MC", "MC & Điều phối sân khấu"),
            ],
        ),
        (
            "AUDIO_STAGE",
            "Kỹ thuật Âm thanh & Ánh sáng",
            departments["TECHNICAL"],
            4,
            [
                ("LIVE_SOUND", "Live Sound Mixing (FOH)"),
                ("STAGE_LIGHTING", "Ánh sáng sân khấu"),
                ("AUDIO_RECORDING", "Thu âm & Hậu kỳ Audio"),
            ],
        ),
    ]
    for cat_code, cat_name, dept, order, skills in skill_tree:
        cat, _ = SkillCategory.objects.update_or_create(
            code=cat_code,
            defaults={"name": cat_name, "department": dept, "display_order": order},
        )
        for s_code, s_name in skills:
            Skill.objects.update_or_create(
                code=s_code,
                defaults={"category": cat, "name": s_name},
            )

    # Chính sách vận hành CLB (Quyết định A3 & Ngưỡng kỷ luật)
    PolicyVersion.objects.get_or_create(
        policy_key="CLUB_EVENT_DEFAULT_RSVP",
        version_number=1,
        defaults={
            "title": "Chính sách phản hồi mặc định cho Sự kiện cấp CLB",
            "config": {
                "before_deadline_status": "PENDING_RESPONSE",
                "reminders_hours_before_deadline": [48, 12],
                "at_deadline_transition_to": "AUTO_COMMITTED",
                "allow_excused_opt_out_before_deadline": True,
            },
            "is_current": True,
        },
    )
    PolicyVersion.objects.get_or_create(
        policy_key="VIOLATION_THRESHOLD_SEMESTER",
        version_number=1,
        defaults={
            "title": "Ngưỡng cảnh báo vi phạm chuyên cần trong kỳ hoạt động",
            "config": {
                "window_months": 6,
                "warning_threshold_exceeded_after": 3,
                "exclude_exempted": True,
                "count_auto_committed_no_show": True,
                "auto_lock_forbidden": True,
            },
            "is_current": True,
        },
    )
    return {"departments": departments, "positions": positions}


# ---------------------------------------------------------------------------
# QUY TRÌNH GIA NHẬP & ĐA BAN (`WF01`, `WF02`, `WF05`)
# ---------------------------------------------------------------------------
@transaction.atomic
def submit_membership_application(
    user: User,
    primary_department: Department,
    motivation: str,
    secondary_department: Department | None = None,
    declared_skills_text: str = "",
    portfolio_url: str = "",
) -> MembershipApplication:
    """Guest nộp đơn xin gia nhập CLB KMG (`WF01`)."""
    cm = user.club_membership_record
    if cm and cm.status == ClubMembershipStatus.ACTIVE:
        raise GovernanceError("Bạn đã là thành viên chính thức của CLB KMG.")
    if MembershipApplication.objects.filter(
        user=user,
        status__in=[ApplicationStatus.SUBMITTED, ApplicationStatus.DEPT_SCREENED],
    ).exists():
        raise GovernanceError("Bạn đang có một hồ sơ ứng tuyển chờ xét duyệt.")
    if secondary_department and secondary_department.id == primary_department.id:
        secondary_department = None

    app = MembershipApplication.objects.create(
        user=user,
        primary_department=primary_department,
        secondary_department=secondary_department,
        declared_skills_text=declared_skills_text.strip()[:255],
        motivation=motivation.strip()[:1500],
        portfolio_url=portfolio_url.strip(),
    )
    AuditLog.write(user, "Nộp đơn ứng tuyển CLB", primary_department.name)
    return app


@transaction.atomic
def screen_membership_application(
    actor: User,
    application: MembershipApplication,
    note: str = "",
) -> MembershipApplication:
    """Trưởng ban (hoặc Phó ban có gói HR Screening) sơ duyệt hồ sơ ứng viên của Ban mình."""
    PermissionEngine.require(
        actor,
        "dept.member.screen",
        department=application.primary_department,
        target_user=application.user,
    )
    if application.status != ApplicationStatus.SUBMITTED:
        raise GovernanceError("Chỉ có thể sơ duyệt đơn ở trạng thái Mới nộp.")
    application.status = ApplicationStatus.DEPT_SCREENED
    application.screening_note = note.strip()[:255]
    application.screened_by = actor
    application.screened_at = timezone.now()
    application.save(
        update_fields=["status", "screening_note", "screened_by", "screened_at"]
    )
    AuditLog.write(
        actor,
        "Sơ duyệt ứng viên Ban",
        application.user.public_name,
        note=f"{application.primary_department.name}: {application.screening_note}",
    )
    return application


@transaction.atomic
def approve_club_member(
    actor: User,
    target_user: User,
    departments: list[Department],
    application: MembershipApplication | None = None,
    note: str = "",
) -> ClubMembership:
    """
    Chủ nhiệm (hoặc Phó CN mảng Nhân sự) phê duyệt thành viên chính thức CLB,
    cấp `member_code` (`KMG-YYYY-NNNN`) và kích hoạt `DepartmentMembership` đa ban.
    """
    PermissionEngine.require(actor, "club.member.approve", target_user=target_user)
    if not departments:
        raise GovernanceError("Thành viên chính thức phải thuộc ít nhất 01 Ban.")

    cm = ClubMembership.objects.select_for_update().filter(user=target_user).first()
    if cm is None:
        cm = ClubMembership.objects.create(
            user=target_user,
            member_code=_generate_next_member_code(),
            status=ClubMembershipStatus.ACTIVE,
            approved_by=actor,
        )
    else:
        cm.status = ClubMembershipStatus.ACTIVE
        cm.suspended_until = None
        cm.suspended_reason = ""
        cm.left_at = None
        cm.approved_by = actor
        cm.save(
            update_fields=[
                "status",
                "suspended_until",
                "suspended_reason",
                "left_at",
                "approved_by",
                "updated_at",
            ]
        )

    record_lifecycle_event(
        user=target_user,
        event_type=LifecycleEventType.APPROVED_CLUB,
        actor=actor,
        title=f"Được phê duyệt là Thành viên chính thức KMG ({cm.member_code})",
        note=note,
        metadata={"member_code": cm.member_code},
    )

    for dept in departments:
        dm, created = DepartmentMembership.objects.update_or_create(
            user=target_user,
            department=dept,
            defaults={
                "status": DeptMembershipStatus.ACTIVE,
                "left_at": None,
                "note": note[:255],
            },
        )
        record_lifecycle_event(
            user=target_user,
            event_type=LifecycleEventType.JOINED_DEPT,
            actor=actor,
            department=dept,
            title=f"Gia nhập {dept.name}",
            note=note,
        )

    if application is not None:
        application.status = ApplicationStatus.APPROVED
        application.reviewed_by = actor
        application.reviewed_at = timezone.now()
        application.decision_note = note[:255]
        application.save(
            update_fields=["status", "reviewed_by", "reviewed_at", "decision_note"]
        )
    else:
        # Nếu nâng cấp trực tiếp từ danh sách Khách, tự động đóng các đơn ứng tuyển đang chờ (nếu có)
        MembershipApplication.objects.filter(
            user=target_user,
            status__in=[ApplicationStatus.SUBMITTED, ApplicationStatus.DEPT_SCREENED],
        ).update(
            status=ApplicationStatus.APPROVED,
            reviewed_by=actor,
            reviewed_at=timezone.now(),
            decision_note=(note or "Được Ban Chủ nhiệm nâng role & phân Ban trực tiếp")[:255],
        )

    target_user._state.fields_cache.pop("club_membership", None)
    target_user.bump_authz_version()
    try:
        from social.services import (
            sync_user_club_wide_membership,
            sync_user_department_chat_membership,
        )

        sync_user_club_wide_membership(target_user, active=True)
        for dept in departments:
            sync_user_department_chat_membership(target_user, dept, joined=True)
    except Exception:
        pass
    AuditLog.write(
        actor,
        "Phê duyệt thành viên CLB",
        f"{target_user.public_name} ({cm.member_code})",
        note=", ".join(d.name for d in departments),
    )
    return cm


@transaction.atomic
def add_member_to_department(
    actor: User,
    target_user: User,
    department: Department,
    note: str = "",
) -> DepartmentMembership:
    """Gán thêm một thành viên CLB vào một Ban mới (hỗ trợ Đa Ban M-N)."""
    if not (
        PermissionEngine.authorize(actor, "club.member.transfer_dept", target_user=target_user)
        or PermissionEngine.authorize(
            actor, "dept.member.manage", department=department, target_user=target_user
        )
    ):
        PermissionEngine.require(
            actor, "dept.member.manage", department=department, target_user=target_user
        )
    cm = target_user.club_membership_record
    if not cm or cm.status != ClubMembershipStatus.ACTIVE:
        raise GovernanceError("Chỉ có thể thêm thành viên CLB đang ACTIVE vào Ban.")

    dm, _ = DepartmentMembership.objects.update_or_create(
        user=target_user,
        department=department,
        defaults={
            "status": DeptMembershipStatus.ACTIVE,
            "left_at": None,
            "note": note[:255],
        },
    )
    record_lifecycle_event(
        user=target_user,
        event_type=LifecycleEventType.JOINED_DEPT,
        actor=actor,
        department=department,
        title=f"Tham gia thêm {department.name}",
        note=note,
    )
    target_user.bump_authz_version()
    try:
        from social.services import sync_user_department_chat_membership

        sync_user_department_chat_membership(target_user, department, joined=True)
    except Exception:
        pass
    AuditLog.write(actor, "Thêm thành viên vào Ban", target_user.public_name, department.name)
    return dm


@transaction.atomic
def transfer_member_department(
    actor: User,
    target_user: User,
    from_department: Department,
    to_department: Department,
    note: str = "",
) -> DepartmentMembership:
    """Chuyển Ban cho thành viên (`WF05` & Chỉ thị 3.2: giữ nguyên lịch sử tại Ban cũ)."""
    PermissionEngine.require(actor, "club.member.transfer_dept", target_user=target_user)
    if from_department.id == to_department.id:
        raise GovernanceError("Ban chuyển đến phải khác Ban hiện tại.")

    old_dm = DepartmentMembership.objects.filter(
        user=target_user,
        department=from_department,
        status=DeptMembershipStatus.ACTIVE,
    ).first()
    if old_dm is None:
        raise GovernanceError(f"Thành viên hiện không sinh hoạt tại {from_department.name}.")

    # Tự động kết thúc mọi chức vụ đang giữ tại Ban cũ khi chuyển Ban!
    active_dept_appts = Appointment.objects.select_for_update().filter(
        user=target_user,
        department=from_department,
        is_active=True,
        ended_at__isnull=True,
    )
    for appt in active_dept_appts:
        end_appointment(
            actor=actor,
            appointment=appt,
            reason=f"Tự động kết thúc chức vụ do chuyển sang {to_department.name}",
        )

    old_dm.status = DeptMembershipStatus.TRANSFERRED
    old_dm.left_at = timezone.localdate()
    old_dm.note = f"Chuyển sang {to_department.name}. {note}"[:255]
    old_dm.save(update_fields=["status", "left_at", "note", "updated_at"])

    new_dm, _ = DepartmentMembership.objects.update_or_create(
        user=target_user,
        department=to_department,
        defaults={
            "status": DeptMembershipStatus.ACTIVE,
            "left_at": None,
            "note": f"Chuyển từ {from_department.name}. {note}"[:255],
        },
    )
    record_lifecycle_event(
        user=target_user,
        event_type=LifecycleEventType.TRANSFERRED_DEPT,
        actor=actor,
        department=to_department,
        title=f"Chuyển Ban: {from_department.name} -> {to_department.name}",
        note=note,
        metadata={"from_dept": from_department.code, "to_dept": to_department.code},
    )
    target_user.bump_authz_version()
    try:
        from operations.services import flag_tasks_needing_reassignment

        flag_tasks_needing_reassignment(
            target_user=target_user,
            department=from_department,
            reason=f"Thành viên chuyển từ {from_department.name} sang {to_department.name}",
        )
    except Exception:
        pass
    try:
        from programs.services import revoke_bound_document_acls

        revoke_bound_document_acls(
            target_user=target_user,
            department=from_department,
            actor=actor,
            reason=f"Tự động thu hồi ACL do chuyển từ {from_department.name} sang {to_department.name}",
        )
    except Exception:
        pass
    try:
        from social.services import sync_user_department_chat_membership

        sync_user_department_chat_membership(target_user, from_department, joined=False)
        sync_user_department_chat_membership(target_user, to_department, joined=True)
    except Exception:
        pass
    AuditLog.write(
        actor,
        "Chuyển Ban thành viên",
        target_user.public_name,
        f"{from_department.name} -> {to_department.name}",
    )
    return new_dm


# ---------------------------------------------------------------------------
# BỔ NHIỆM, MIỄN NHIỆM & ỦY QUYỀN ĐỘNG (`WF03`, `WF04`, Chỉ thị 3.1 & 3.2)
# ---------------------------------------------------------------------------
def _ensure_member_and_dept_for_leadership(
    actor: User,
    target_user: User,
    department: Department | None = None,
    note: str = "",
) -> ClubMembership:
    """
    Khi Admin Server nâng cấp một tài khoản vừa mới đăng ký (đang là Khách `GUEST`)
    lên Chủ nhiệm, Phó chủ nhiệm hoặc Trưởng ban: tự động kích hoạt hồ sơ Thành viên CLB
    (`KMG-YYYY-NNNN`) và phân vào Ban tương ứng trong cùng một giao dịch nguyên tử.
    """
    cm = ClubMembership.objects.select_for_update().filter(user=target_user).first()
    if cm is None:
        cm = ClubMembership.objects.create(
            user=target_user,
            member_code=_generate_next_member_code(),
            status=ClubMembershipStatus.ACTIVE,
            approved_by=actor,
        )
        record_lifecycle_event(
            user=target_user,
            event_type=LifecycleEventType.APPROVED_CLUB,
            actor=actor,
            title=f"Được kích hoạt Thành viên CLB khi nâng cấp lãnh đạo ({cm.member_code})",
            note=note,
            metadata={"member_code": cm.member_code},
        )
    elif cm.status != ClubMembershipStatus.ACTIVE:
        cm.status = ClubMembershipStatus.ACTIVE
        cm.suspended_until = None
        cm.suspended_reason = ""
        cm.left_at = None
        cm.approved_by = actor
        cm.save(
            update_fields=[
                "status",
                "suspended_until",
                "suspended_reason",
                "left_at",
                "approved_by",
                "updated_at",
            ]
        )

    if department is not None:
        existing_dm = DepartmentMembership.objects.filter(
            user=target_user,
            department=department,
            status=DeptMembershipStatus.ACTIVE,
        ).exists()
        DepartmentMembership.objects.update_or_create(
            user=target_user,
            department=department,
            defaults={
                "status": DeptMembershipStatus.ACTIVE,
                "left_at": None,
                "note": (note or "Phân Ban khi nâng cấp chức vụ")[:255],
            },
        )
        if not existing_dm:
            record_lifecycle_event(
                user=target_user,
                event_type=LifecycleEventType.JOINED_DEPT,
                actor=actor,
                department=department,
                title=f"Gia nhập {department.name}",
                note=note,
            )

    MembershipApplication.objects.filter(
        user=target_user,
        status__in=[ApplicationStatus.SUBMITTED, ApplicationStatus.DEPT_SCREENED],
    ).update(
        status=ApplicationStatus.APPROVED,
        reviewed_by=actor,
        reviewed_at=timezone.now(),
        decision_note=(note or "Được Admin Server nâng cấp chức vụ lãnh đạo")[:255],
    )
    target_user._state.fields_cache.pop("club_membership", None)
    try:
        from social.services import (
            sync_user_club_wide_membership,
            sync_user_department_chat_membership,
        )

        sync_user_club_wide_membership(target_user, active=True)
        if department is not None:
            sync_user_department_chat_membership(target_user, department, joined=True)
    except Exception:
        pass
    return cm


@transaction.atomic
def appoint_officer(
    actor: User,
    target_user: User,
    position: Position,
    department: Department | None = None,
    term_label: str = "2026-2027",
    title_note: str = "",
    ends_at=None,
) -> Appointment:
    """
    Bổ nhiệm cán bộ/cố vấn có kiểm tra phân quyền 2 tầng nghiêm ngặt & khóa đơn nhiệm `singleton_active_key`:
    - Các chức vụ lãnh đạo chủ chốt (`CHAIRMAN`, `VICE_CHAIRMAN`, `DEPT_HEAD`, `ADVISOR`):
      ĐỘC QUYỀN của Admin Server (`server.leadership.manage`). Kể cả Chủ nhiệm CLB cũng bị chặn 403!
      Khi Admin Server nâng cấp tài khoản mới đăng ký (`Guest`), hệ thống tự động kích hoạt
      `ClubMembership` + `DepartmentMembership` cho họ.
    - Chức vụ `DEPUTY_HEAD` (`Phó ban`) / `CORE_MEMBER`:
      Do Trưởng ban (tại chính Ban đó), Chủ nhiệm, Phó CN (có mảng Nhân sự) hoặc Admin Server bổ nhiệm.
    """
    scope_type = position.scope_type
    is_srv_admin = bool(getattr(actor, "is_server_admin", False))

    if scope_type == ScopeType.DEPARTMENT:
        if department is None:
            raise GovernanceError("Bổ nhiệm chức vụ cấp Ban bắt buộc phải chọn Ban.")
        if position.code in (PositionCode.DEPUTY_HEAD, PositionCode.CORE_MEMBER):
            if not (
                PermissionEngine.authorize(
                    actor, "dept.deputy.appoint", department=department, target_user=target_user
                )
                or PermissionEngine.authorize(
                    actor, "club.officer.appoint_deputy", target_user=target_user
                )
            ):
                PermissionEngine.require(
                    actor, "dept.deputy.appoint", department=department, target_user=target_user
                )
            if is_srv_admin:
                _ensure_member_and_dept_for_leadership(
                    actor, target_user, department=department, note=title_note
                )
        else:
            # Bổ nhiệm Trưởng ban (DEPT_HEAD) là ĐỘC QUYỀN của Admin Server!
            PermissionEngine.require(actor, "server.leadership.manage", target_user=target_user)
            _ensure_member_and_dept_for_leadership(
                actor, target_user, department=department, note=title_note
            )

        if not DepartmentMembership.objects.filter(
            user=target_user,
            department=department,
            status=DeptMembershipStatus.ACTIVE,
        ).exists():
            raise GovernanceError(
                f"{target_user.public_name} phải là thành viên đang sinh hoạt tại {department.name} "
                f"trước khi được bổ nhiệm chức vụ của Ban."
            )
    else:
        # Cấp CLB (Chủ nhiệm, Phó chủ nhiệm, Cố vấn): ĐỘC QUYỀN của Admin Server!
        PermissionEngine.require(actor, "server.leadership.manage", target_user=target_user)
        if position.code != PositionCode.ADVISOR:
            _ensure_member_and_dept_for_leadership(
                actor, target_user, department=department, note=title_note
            )

    # Đồng bộ vai trò BTC sự kiện legacy (LEAD) cho Chủ nhiệm / Phó CN / Trưởng ban (không cấp ADMIN!)
    if (
        position.code in (PositionCode.CHAIRMAN, PositionCode.VICE_CHAIRMAN, PositionCode.DEPT_HEAD)
        and target_user.role == Role.MEMBER
    ):
        target_user.role = Role.LEAD
        target_user.save(update_fields=["role"])

    appt = Appointment(
        user=target_user,
        position=position,
        scope_type=scope_type,
        department=department if scope_type == ScopeType.DEPARTMENT else None,
        title_note=title_note.strip()[:120],
        term_label=term_label.strip()[:40] or "2026-2027",
        ends_at=ends_at,
        appointed_by=actor,
    )
    appt.clean()
    try:
        with transaction.atomic():
            appt.save()
    except IntegrityError as exc:
        scope_label = department.name if (scope_type == ScopeType.DEPARTMENT and department) else "CLB KMG"
        raise GovernanceError(
            f"{scope_label} hiện đã có {position.name} đang đương nhiệm. "
            f"Vui lòng kết thúc nhiệm kỳ hiện tại trước khi bổ nhiệm người mới.",
            code="CONFLICT_SINGLETON",
        ) from exc

    scope_label = (
        department.name
        if (scope_type == ScopeType.DEPARTMENT and department)
        else "Toàn CLB"
    )
    record_lifecycle_event(
        user=target_user,
        event_type=LifecycleEventType.APPOINTED,
        actor=actor,
        department=department if scope_type == ScopeType.DEPARTMENT else None,
        title=f"Được bổ nhiệm {position.name} ({scope_label})",
        note=f"Nhiệm kỳ {appt.term_label}. {appt.title_note}".strip(),
        metadata={"appointment_id": appt.id, "position_code": position.code},
    )
    target_user.bump_authz_version()
    AuditLog.write(
        actor,
        "Bổ nhiệm chức vụ",
        f"{target_user.public_name} -> {position.name}",
        note=scope_label,
    )
    return appt


@transaction.atomic
def end_appointment(
    actor: User,
    appointment: Appointment,
    reason: str = "Kết thúc nhiệm kỳ",
) -> Appointment:
    """
    Kết thúc nhiệm kỳ / miễn nhiệm chức vụ (Chỉ thị 3.2):
    - Lưu nguyên vẹn lịch sử nhiệm kỳ.
    - Giải phóng `singleton_active_key = NULL`.
    - Thu hồi tức thời mọi `PermissionGrant` gắn với nhiệm kỳ này (`INV-02` & `INV-06`).
    - Miễn nhiệm `CHAIRMAN`, `VICE_CHAIRMAN`, `DEPT_HEAD`, `ADVISOR` là độc quyền của Admin Server!
    """
    if appointment.scope_type == ScopeType.DEPARTMENT and appointment.position.code in (
        PositionCode.DEPUTY_HEAD,
        PositionCode.CORE_MEMBER,
    ):
        if not (
            PermissionEngine.authorize(
                actor,
                "dept.deputy.appoint",
                department=appointment.department,
                target_user=appointment.user,
            )
            or PermissionEngine.authorize(
                actor, "club.officer.appoint_deputy", target_user=appointment.user
            )
        ):
            PermissionEngine.require(
                actor,
                "dept.deputy.appoint",
                department=appointment.department,
                target_user=appointment.user,
            )
    else:
        PermissionEngine.require(
            actor, "server.leadership.manage", target_user=appointment.user
        )

    now = timezone.now()
    appointment.ended_at = now
    appointment.is_active = False
    appointment.ended_reason = (reason or "Kết thúc nhiệm kỳ")[:255]
    appointment.revoked_by = actor
    appointment.save(
        update_fields=["ended_at", "is_active", "ended_reason", "revoked_by"]
    )

    # Thu hồi dây chuyền mọi gói quyền ủy quyền đang bám vào quyết định bổ nhiệm này
    appointment.permission_grants.filter(is_active=True, revoked_at__isnull=True).update(
        is_active=False,
        revoked_at=now,
        revoked_by=actor,
    )
    try:
        from programs.services import revoke_bound_document_acls

        revoke_bound_document_acls(
            target_user=appointment.user,
            appointment=appointment,
            actor=actor,
            reason=f"Thu hồi ACL gắn với nhiệm kỳ {appointment.position.name}: {appointment.ended_reason}",
        )
    except Exception:
        pass

    scope_label = appointment.department.name if appointment.department_id else "Toàn CLB"
    record_lifecycle_event(
        user=appointment.user,
        event_type=LifecycleEventType.ROLE_ENDED,
        actor=actor,
        department=appointment.department,
        title=f"Kết thúc chức vụ {appointment.position.name} ({scope_label})",
        note=appointment.ended_reason,
        metadata={"appointment_id": appointment.id, "position_code": appointment.position.code},
    )
    appointment.user.bump_authz_version()
    AuditLog.write(
        actor,
        "Kết thúc nhiệm kỳ / Miễn nhiệm",
        f"{appointment.user.public_name} ({appointment.position.name})",
        note=f"{scope_label}: {appointment.ended_reason}",
    )
    return appointment


@transaction.atomic
def server_admin_assign_leadership(
    actor: User,
    target_user: User,
    position_code: str,
    department: Department | None = None,
    portfolios: list[str] | None = None,
    term_label: str = "2026-2027",
    title_note: str = "",
    replace_existing: bool = False,
) -> Appointment:
    """
    Dành riêng cho Admin Server ("admin server là tôi"):
    Nâng cấp trực tiếp một tài khoản đã đăng ký lên `Chủ nhiệm`, `Phó chủ nhiệm`, `Trưởng ban`
    (hoặc `Cố vấn` / `Phó ban`), tự động kích hoạt tư cách Thành viên CLB, phân Ban,
    và tuỳ chọn gắn sẵn Mảng phụ trách cho Phó chủ nhiệm trong 1 bước duy nhất.
    """
    PermissionEngine.require(actor, "server.leadership.manage", target_user=target_user)
    position = Position.objects.filter(code=position_code).first()
    if position is None:
        raise GovernanceError("Mã chức vụ nâng cấp không hợp lệ.")

    dept_for_scope = department if position.scope_type == ScopeType.DEPARTMENT else None
    if position.scope_type == ScopeType.DEPARTMENT and dept_for_scope is None:
        raise GovernanceError(f"Chức vụ {position.name} bắt buộc phải chọn một Ban cụ thể.")

    # Nếu cùng người dùng đã đang giữ đúng chức vụ này thì tái sử dụng để gán thêm mảng/ban
    existing_same_user = Appointment.objects.filter(
        user=target_user,
        position=position,
        department=dept_for_scope,
        is_active=True,
        ended_at__isnull=True,
    ).first()

    if existing_same_user is not None:
        if position.code != PositionCode.ADVISOR:
            _ensure_member_and_dept_for_leadership(
                actor, target_user, department=department, note=title_note
            )
        appt = existing_same_user
    else:
        if replace_existing and position.is_singleton:
            incumbent = Appointment.objects.select_for_update().filter(
                position=position,
                department=dept_for_scope,
                is_active=True,
                ended_at__isnull=True,
            ).exclude(user=target_user).first()
            if incumbent is not None:
                end_appointment(
                    actor=actor,
                    appointment=incumbent,
                    reason=f"Admin Server chuyển giao chức vụ {position.name} cho {target_user.public_name}",
                )
        appt = appoint_officer(
            actor=actor,
            target_user=target_user,
            position=position,
            department=department,
            term_label=term_label,
            title_note=title_note,
        )

    if position.code == PositionCode.VICE_CHAIRMAN and portfolios:
        existing_bundles = set(
            appt.permission_grants.filter(is_active=True, revoked_at__isnull=True)
            .values_list("bundle_code", flat=True)
        )
        for bundle_code in portfolios:
            if (
                bundle_code in VICE_CHAIRMAN_PORTFOLIO_PERMISSIONS
                and bundle_code not in existing_bundles
            ):
                grant_delegated_permissions(
                    actor=actor,
                    bound_appointment=appt,
                    bundle_code=bundle_code,
                    reason=title_note or "Admin Server phân công mảng phụ trách khi nâng cấp Phó CN",
                )

    return appt


@transaction.atomic
def grant_delegated_permissions(
    actor: User,
    bound_appointment: Appointment,
    bundle_code: str,
    reason: str,
    department: Department | None = None,
    expires_at=None,
    custom_permission_codes: list[str] | None = None,
) -> PermissionGrant:
    """
    Cấp Gói ủy quyền cho Phó ban (`BUNDLE_*`) hoặc Mảng phụ trách cho Phó CN (`PORTFOLIO_*`).
    Thực thi nghiêm ngặt Hard Ceiling & `INV-02` (Sub-delegation Containment).
    """
    if not bound_appointment.is_currently_effective:
        raise GovernanceError("Không thể ủy quyền cho một quyết định bổ nhiệm đã hết hiệu lực.")

    grantee = bound_appointment.user
    pos_code = bound_appointment.position.code

    if pos_code == PositionCode.DEPUTY_HEAD:
        target_dept = bound_appointment.department
        PermissionEngine.require(
            actor,
            "dept.permission.delegate",
            department=target_dept,
            target_user=grantee,
        )
        valid_bundles = set(DEPUTY_HEAD_BUNDLE_PERMISSIONS.keys()) | {GrantBundleCode.CUSTOM}
        if bundle_code not in valid_bundles:
            raise GovernanceError("Gói quyền này không dành cho chức vụ Phó ban.")
        scope_type = ScopeType.DEPARTMENT
        department = target_dept

        # INV-02: Nếu người cấp là Trưởng ban có thời hạn kết thúc nhiệm kỳ, thời hạn ủy quyền <= nhiệm kỳ Trưởng ban
        grantor_head_appt = (
            Appointment.objects.filter(
                user=actor,
                position__code=PositionCode.DEPT_HEAD,
                department=target_dept,
                is_active=True,
                ended_at__isnull=True,
            ).first()
        )
        if grantor_head_appt and grantor_head_appt.ends_at:
            if expires_at is None or expires_at > grantor_head_appt.ends_at:
                expires_at = grantor_head_appt.ends_at

    elif pos_code == PositionCode.VICE_CHAIRMAN:
        PermissionEngine.require(
            actor, "club.permission.delegate", target_user=grantee
        )
        valid_portfolios = set(VICE_CHAIRMAN_PORTFOLIO_PERMISSIONS.keys()) | {
            GrantBundleCode.CUSTOM
        }
        if bundle_code not in valid_portfolios:
            raise GovernanceError("Mảng phụ trách này không dành cho Phó chủ nhiệm.")
        scope_type = ScopeType.DEPARTMENT if department is not None else ScopeType.CLUB
    else:
        raise GovernanceError(
            "Chỉ áp dụng cơ chế gói ủy quyền đối với Phó ban hoặc Phó chủ nhiệm."
        )

    if bound_appointment.ends_at and (
        expires_at is None or expires_at > bound_appointment.ends_at
    ):
        expires_at = bound_appointment.ends_at

    if expires_at is not None and expires_at <= timezone.now():
        raise GovernanceError("Thời hạn ủy quyền phải nằm ở tương lai.")

    grant = PermissionGrant.objects.create(
        grantee=grantee,
        bound_appointment=bound_appointment,
        bundle_code=bundle_code,
        scope_type=scope_type,
        department=department,
        reason=reason.strip()[:255] or "Phân công nhiệm vụ",
        expires_at=expires_at,
        granted_by=actor,
    )
    if custom_permission_codes:
        perms = Permission.objects.filter(code__in=custom_permission_codes)
        grant.custom_permissions.set(perms)

    record_lifecycle_event(
        user=grantee,
        event_type=LifecycleEventType.DELEGATION_GRANTED,
        actor=actor,
        department=department,
        title=f"Được cấp {grant.get_bundle_code_display()}",
        note=grant.reason,
        metadata={"grant_id": grant.id, "bundle_code": bundle_code},
    )
    grantee.bump_authz_version()
    AuditLog.write(
        actor,
        "Cấp quyền ủy quyền",
        f"{grantee.public_name} <- {grant.get_bundle_code_display()}",
        note=grant.reason,
    )
    return grant


@transaction.atomic
def revoke_permission_grant(
    actor: User,
    grant: PermissionGrant,
    reason: str = "Thu hồi ủy quyền",
) -> PermissionGrant:
    """Thu hồi gói quyền ủy quyền ngay lập tức (`INV-06`)."""
    if grant.bound_appointment.position.code == PositionCode.DEPUTY_HEAD:
        PermissionEngine.require(
            actor,
            "dept.permission.delegate",
            department=grant.department,
            target_user=grant.grantee,
        )
    else:
        PermissionEngine.require(
            actor, "club.permission.delegate", target_user=grant.grantee
        )

    grant.is_active = False
    grant.revoked_at = timezone.now()
    grant.revoked_by = actor
    grant.save(update_fields=["is_active", "revoked_at", "revoked_by"])

    record_lifecycle_event(
        user=grant.grantee,
        event_type=LifecycleEventType.DELEGATION_REVOKED,
        actor=actor,
        department=grant.department,
        title=f"Thu hồi {grant.get_bundle_code_display()}",
        note=reason[:255],
        metadata={"grant_id": grant.id},
    )
    grant.grantee.bump_authz_version()
    AuditLog.write(
        actor,
        "Thu hồi ủy quyền",
        f"{grant.grantee.public_name} ({grant.get_bundle_code_display()})",
        note=reason,
    )
    return grant


# ---------------------------------------------------------------------------
# TẠM KHOÁ, KHÔI PHỤC, RỜI CLB & XÁC MINH KỸ NĂNG (`WF23`, Chỉ thị 3.2 & 3.4)
# ---------------------------------------------------------------------------
@transaction.atomic
def suspend_club_member(
    actor: User,
    target_user: User,
    reason: str,
    suspended_until=None,
) -> ClubMembership:
    """Tạm khoá tư cách thành viên CLB (thủ công, có lý do minh bạch, thu hồi quyền tức thời)."""
    PermissionEngine.require(
        actor, "club.member.suspend_temporary", target_user=target_user
    )
    cm = ClubMembership.objects.select_for_update().filter(user=target_user).first()
    if cm is None:
        raise GovernanceError("Người dùng chưa có hồ sơ thành viên CLB.")
    if not reason.strip():
        raise GovernanceError("Bắt buộc phải nêu rõ lý do tạm khoá tư cách thành viên.")

    cm.status = ClubMembershipStatus.SUSPENDED
    cm.suspended_reason = reason.strip()[:255]
    cm.suspended_until = suspended_until
    cm.save(update_fields=["status", "suspended_reason", "suspended_until", "updated_at"])

    record_lifecycle_event(
        user=target_user,
        event_type=LifecycleEventType.SUSPENDED,
        actor=actor,
        title="Bị tạm khoá tư cách thành viên CLB",
        note=cm.suspended_reason,
    )
    target_user._state.fields_cache.pop("club_membership", None)
    target_user.bump_authz_version()
    try:
        from operations.models import EventAttendance, RsvpStatus
        from operations.services import flag_tasks_needing_reassignment

        flag_tasks_needing_reassignment(
            target_user=target_user,
            reason=f"Thành viên bị tạm khoá CLB: {cm.suspended_reason}",
        )
        # CF-02: Tự động miễn trừ RSVP cho các sự kiện sắp tới khi đang tạm khoá để không bị phạt kép
        EventAttendance.objects.filter(
            user=target_user,
            rsvp_status__in=[RsvpStatus.PENDING_RESPONSE, RsvpStatus.AUTO_COMMITTED],
            checkin_status="NOT_YET",
        ).update(rsvp_status=RsvpStatus.EXEMPT_SUSPENDED)
    except Exception:
        pass
    try:
        from programs.services import revoke_bound_document_acls

        revoke_bound_document_acls(
            target_user=target_user,
            actor=actor,
            reason=f"Thu hồi quyền tài liệu mật do bị tạm khoá CLB: {cm.suspended_reason}",
        )
    except Exception:
        pass
    try:
        from social.services import leave_all_club_chats

        leave_all_club_chats(target_user, include_direct=False)
    except Exception:
        pass
    AuditLog.write(actor, "Tạm khoá thành viên CLB", target_user.public_name, cm.suspended_reason)
    return cm


@transaction.atomic
def restore_club_member(
    actor: User,
    target_user: User,
    reason: str = "Khôi phục tư cách hoạt động",
) -> ClubMembership:
    """Khôi phục tư cách thành viên sau tạm khoá (chống tự mở khoá `INV-03`)."""
    PermissionEngine.require(
        actor, "club.member.suspend_temporary", target_user=target_user
    )
    if actor.pk == target_user.pk:
        raise GovernanceError("Không được tự khôi phục tư cách của chính mình.")
    cm = ClubMembership.objects.select_for_update().filter(user=target_user).first()
    if cm is None:
        raise GovernanceError("Người dùng chưa có hồ sơ thành viên CLB.")

    cm.status = ClubMembershipStatus.ACTIVE
    cm.suspended_reason = ""
    cm.suspended_until = None
    cm.save(update_fields=["status", "suspended_reason", "suspended_until", "updated_at"])

    record_lifecycle_event(
        user=target_user,
        event_type=LifecycleEventType.RESTORED,
        actor=actor,
        title="Được khôi phục tư cách thành viên CLB",
        note=reason[:255],
    )
    target_user._state.fields_cache.pop("club_membership", None)
    target_user.bump_authz_version()
    try:
        from social.services import (
            sync_user_club_wide_membership,
            sync_user_department_chat_membership,
        )

        sync_user_club_wide_membership(target_user, active=True)
        for dm in DepartmentMembership.objects.select_related("department").filter(
            user=target_user,
            status=DeptMembershipStatus.ACTIVE,
            department__is_active=True,
        ):
            sync_user_department_chat_membership(target_user, dm.department, joined=True)
    except Exception:
        pass
    AuditLog.write(actor, "Khôi phục thành viên CLB", target_user.public_name, reason)
    return cm


@transaction.atomic
def mark_member_left_club(
    actor: User,
    target_user: User,
    as_alumni: bool = True,
    reason: str = "Tốt nghiệp / Kết thúc sinh hoạt",
) -> ClubMembership:
    """Chuyển thành viên sang Cựu thành viên (`ALUMNI`) hoặc Rời CLB (`LEFT`), bảo toàn 100% lịch sử."""
    PermissionEngine.require(actor, "club.member.expel_permanent", target_user=target_user)
    cm = ClubMembership.objects.select_for_update().filter(user=target_user).first()
    if cm is None:
        raise GovernanceError("Người dùng chưa có hồ sơ thành viên CLB.")

    now = timezone.now()
    # Thu hồi mọi chức vụ đang đương nhiệm
    for appt in Appointment.objects.select_for_update().filter(
        user=target_user, is_active=True, ended_at__isnull=True
    ):
        end_appointment(actor=actor, appointment=appt, reason=reason)

    DepartmentMembership.objects.filter(
        user=target_user, status=DeptMembershipStatus.ACTIVE
    ).update(status=DeptMembershipStatus.LEFT, left_at=timezone.localdate())

    cm.status = ClubMembershipStatus.ALUMNI if as_alumni else ClubMembershipStatus.LEFT
    cm.left_at = timezone.localdate()
    cm.save(update_fields=["status", "left_at", "updated_at"])

    record_lifecycle_event(
        user=target_user,
        event_type=LifecycleEventType.LEFT_CLUB,
        actor=actor,
        title="Chuyển trạng thái Cựu thành viên" if as_alumni else "Rời CLB KMG",
        note=reason[:255],
    )
    target_user._state.fields_cache.pop("club_membership", None)
    target_user.bump_authz_version()
    try:
        from operations.services import flag_tasks_needing_reassignment

        flag_tasks_needing_reassignment(
            target_user=target_user,
            reason=f"Thành viên rời CLB / chuyển Cựu thành viên: {reason}",
        )
    except Exception:
        pass
    try:
        from programs.services import revoke_bound_document_acls

        revoke_bound_document_acls(
            target_user=target_user,
            actor=actor,
            reason=f"Thu hồi toàn bộ ACL tài liệu mật do rời CLB: {reason}",
        )
    except Exception:
        pass
    try:
        from social.services import leave_all_club_chats

        leave_all_club_chats(target_user, include_direct=True)
    except Exception:
        pass
    AuditLog.write(actor, "Ghi nhận rời CLB", target_user.public_name, reason)
    return cm


@transaction.atomic
def declare_user_skill(
    user: User,
    skill: Skill,
    proficiency: str,
    experience_note: str = "",
    evidence_url: str = "",
) -> UserSkill:
    """Thành viên tự khai báo / cập nhật kỹ năng (về trạng thái `SELF_DECLARED` chờ xác minh)."""
    us, _ = UserSkill.objects.update_or_create(
        user=user,
        skill=skill,
        defaults={
            "proficiency": proficiency,
            "verification_status": SkillVerificationStatus.SELF_DECLARED,
            "experience_note": experience_note.strip()[:255],
            "evidence_url": evidence_url.strip(),
            "verified_by": None,
            "verified_at": None,
        },
    )
    return us


@transaction.atomic
def verify_user_skill(
    actor: User,
    user_skill: UserSkill,
    department: Department,
    approved: bool = True,
    review_note: str = "",
) -> UserSkill:
    """Trưởng ban (hoặc Phó ban được ủy quyền Đào tạo) xác minh kỹ năng thành viên."""
    PermissionEngine.require(
        actor,
        "dept.skill.verify",
        department=department,
        target_user=user_skill.user,
    )
    user_skill.verification_status = (
        SkillVerificationStatus.VERIFIED
        if approved
        else SkillVerificationStatus.REJECTED
    )
    user_skill.verified_by = actor
    user_skill.verified_at = timezone.now()
    user_skill.review_note = review_note.strip()[:255]
    user_skill.save(
        update_fields=[
            "verification_status",
            "verified_by",
            "verified_at",
            "review_note",
        ]
    )
    AuditLog.write(
        actor,
        "Xác minh kỹ năng" if approved else "Từ chối xác minh kỹ năng",
        f"{user_skill.user.public_name} - {user_skill.skill.name}",
        note=user_skill.review_note,
    )
    return user_skill
