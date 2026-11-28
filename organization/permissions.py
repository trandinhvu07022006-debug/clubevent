"""
Động cơ Phân quyền Đa chiều (Canonical Multi-Dimensional Permission Engine — `D04 v1.1`).

Thực thi chính xác Ma trận Phân quyền Chuẩn `docs/business-analysis/PERMISSION_MATRIX.md`:
1. `RBAC + DBAC + ABAC + Delegation + Resource ACL`.
2. Phân rã 3 tầng cho Phó ban (Baseline / 4 Gói ủy quyền / Hard Ceiling).
3. Phân rã 3 tầng cho Phó chủ nhiệm (Baseline / 4 Mảng phụ trách / Hard Ceiling).
4. Chế độ truy cập Ban (`MANAGE` | `MEMBER` | `READ_ONLY` | `DENIED`) — Cán bộ Ban A sang Ban B
   chỉ ở chế độ `READ_ONLY` (hoặc `MEMBER` nếu cũng là thành viên thường của Ban B).
5. 6 Bất biến Bảo mật (`INV-01` `Skill != Permission`, `INV-02` Không vượt quyền người cấp,
   `INV-03` Chống tự phê duyệt, `INV-04` Cố vấn Hard Read-Only, `INV-05` Bí mật tin nhắn riêng,
   `INV-06` Thu hồi quyền tức thời).
"""
from __future__ import annotations

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone

from accounts.models import AccountStatus

from .models import (
    Appointment,
    ClubMembershipStatus,
    Department,
    DepartmentMembership,
    DeptMembershipStatus,
    GrantBundleCode,
    PermissionGrant,
    PositionCode,
    ResourceAccessRule,
    ResourceClassification,
    ScopeType,
)

# ---------------------------------------------------------------------------
# 1. DANH MỤC MÃ QUYỀN CHUẨN TOÀN HỆ THỐNG (PERMISSIONS CATALOG)
# ---------------------------------------------------------------------------
PERMISSIONS_CATALOG: list[tuple[str, str, str, str, bool]] = [
    # (code, name, module, scope_type, is_mutation)
    # --- Cấp Ban (Department Scope) ---
    ("dept.page.view", "Xem trang thông tin chung của Ban", "department", ScopeType.DEPARTMENT, False),
    ("dept.roster.view", "Xem danh sách nhân sự Ban", "department", ScopeType.DEPARTMENT, False),
    ("dept.progress.view_summary", "Xem tiến độ tổng hợp của Ban", "department", ScopeType.DEPARTMENT, False),
    ("dept.assist.coordinate_view", "Xem bảng điều phối hỗ trợ của Phó ban", "department", ScopeType.DEPARTMENT, False),
    ("dept.task.view_personal_self", "Xem & nộp nhiệm vụ cá nhân của bản thân trong Ban", "task", ScopeType.DEPARTMENT, False),
    ("dept.task.view_all", "Xem toàn bộ nhiệm vụ cá nhân của thành viên trong Ban", "task", ScopeType.DEPARTMENT, False),
    ("dept.task.assign", "Tạo & giao nhiệm vụ trong Ban", "task", ScopeType.DEPARTMENT, True),
    ("dept.task.approve", "Nghiệm thu & duyệt hoàn thành nhiệm vụ trong Ban", "task", ScopeType.DEPARTMENT, True),
    ("dept.member.screen", "Sơ duyệt hồ sơ ứng viên xin vào Ban", "hr", ScopeType.DEPARTMENT, True),
    ("dept.member.manage", "Quản lý thành viên trong Ban (tiếp nhận, điều chuyển nội bộ)", "hr", ScopeType.DEPARTMENT, True),
    ("dept.deputy.appoint", "Bổ nhiệm / miễn nhiệm Phó ban", "hr", ScopeType.DEPARTMENT, True),
    ("dept.permission.delegate", "Ủy quyền gói chức năng cho Phó ban", "governance", ScopeType.DEPARTMENT, True),
    ("dept.skill.verify", "Xác minh kỹ năng chuyên môn thành viên trong Ban", "specialty", ScopeType.DEPARTMENT, True),
    ("dept.training.manage", "Quản lý lịch đào tạo & buổi tập của Ban", "specialty", ScopeType.DEPARTMENT, True),
    ("dept.post.moderate", "Kiểm duyệt bài đăng nội bộ trong Ban", "social", ScopeType.DEPARTMENT, True),
    ("dept.document.manage", "Tải lên & phân quyền ACL tài liệu của Ban", "document", ScopeType.DEPARTMENT, True),
    ("dept.event.manage_internal", "Tạo sự kiện nội bộ cấp Ban & gửi đề xuất sự kiện CLB", "event", ScopeType.DEPARTMENT, True),
    ("dept.proposal.create_member", "Gửi đề xuất hoạt động/ý tưởng lên Ban", "proposal", ScopeType.DEPARTMENT, True),
    ("dept.proposal.submit_to_bcn", "Trình đề xuất chính thức từ Ban lên Ban Chủ nhiệm", "proposal", ScopeType.DEPARTMENT, True),
    ("dept.evaluation.propose", "Lập phiếu đề xuất đánh giá thành viên trong Ban", "evaluation", ScopeType.DEPARTMENT, True),
    ("dept.evaluation.finalize", "Chốt đánh giá định kỳ thành viên trong phạm vi Ban mình", "evaluation", ScopeType.DEPARTMENT, True),

    # --- Cấp Toàn CLB (Club Scope) ---
    ("club.overview.supervise", "Giám sát tổng quan hoạt động toàn CLB", "governance", ScopeType.CLUB, False),
    ("club.dept.supervise_ops", "Điều phối vận hành liên Ban", "governance", ScopeType.CLUB, True),
    ("club.member.view_lifecycle", "Xem sổ cái lịch sử thành viên toàn CLB", "hr", ScopeType.CLUB, False),
    ("club.member.approve", "Phê duyệt chính thức thành viên mới & cấp Member ID", "hr", ScopeType.CLUB, True),
    ("club.member.transfer_dept", "Phê duyệt chuyển Ban liên phòng ban", "hr", ScopeType.CLUB, True),
    ("club.member.suspend_temporary", "Tạm khoá / khôi phục tư cách thành viên có thời hạn", "hr", ScopeType.CLUB, True),
    ("club.member.expel_permanent", "Quyết định buộc rời CLB / thu hồi tư cách vĩnh viễn", "hr", ScopeType.CLUB, True),
    ("club.officer.appoint_deputy", "Phê duyệt bổ nhiệm Phó ban cấp CLB", "governance", ScopeType.CLUB, True),
    ("club.officer.appoint_head", "Bổ nhiệm / miễn nhiệm Trưởng ban, Phó CN, Cố vấn (Độc quyền Admin Server)", "governance", ScopeType.CLUB, True),
    ("server.leadership.manage", "Nâng cấp / thu hồi chức vụ Chủ nhiệm, Phó CN, Trưởng ban, Cố vấn (Độc quyền Admin Server)", "governance", ScopeType.CLUB, True),
    ("club.permission.delegate", "Phân công mảng phụ trách cho Phó chủ nhiệm", "governance", ScopeType.CLUB, True),
    ("club.governance.manage_departments", "Thành lập, cấu hình hoặc giải thể Ban trực thuộc", "governance", ScopeType.CLUB, True),
    ("club.governance.update_policy", "Ban hành phiên bản chính sách vận hành CLB", "governance", ScopeType.CLUB, True),
    ("club.event.view_internal", "Xem lịch sự kiện nội bộ toàn CLB", "event", ScopeType.CLUB, False),
    ("club.event.approve", "Phê duyệt sự kiện cấp CLB & công bố ra trang chủ", "event", ScopeType.CLUB, True),
    ("club.event.configure_rsvp", "Cấu hình hạn phản hồi & chính sách tham gia sự kiện CLB", "event", ScopeType.CLUB, True),
    ("club.media.approve_public", "Duyệt nội dung truyền thông xuất bản ra Public Website", "media", ScopeType.CLUB, True),
    ("club.social.moderate", "Kiểm duyệt bài viết MXH nội bộ toàn CLB", "social", ScopeType.CLUB, True),
    ("club.announcement.publish", "Phát thông báo chính thức toàn CLB", "notification", ScopeType.CLUB, True),
    ("club.proposal.review_comment", "Xem & ghi nhận xét thẩm định đề xuất cấp CLB", "proposal", ScopeType.CLUB, False),
    ("club.finance.view_summary", "Xem báo cáo tổng hợp thu chi & quỹ CLB", "finance", ScopeType.CLUB, False),
    ("club.finance.create_transaction", "Lập phiếu thu / chi / ghi nhận đóng góp quỹ CLB (Maker)", "finance", ScopeType.CLUB, True),
    ("club.finance.approve_transaction", "Phê duyệt độc lập phiếu thu / chi quỹ CLB (Maker-Checker)", "finance", ScopeType.CLUB, True),
    ("club.document.manage_confidential", "Quản lý kho tài liệu điều hành Ban Chủ nhiệm", "document", ScopeType.CLUB, True),
    ("club.evaluation.finalize", "Chốt kết quả đánh giá & danh hiệu vinh danh cấp CLB", "evaluation", ScopeType.CLUB, True),
    ("club.report.export", "Xuất báo cáo tổng hợp cấp CLB", "governance", ScopeType.CLUB, False),
]

PERMISSION_META: dict[str, dict] = {
    code: {
        "name": name,
        "module": module,
        "scope_type": scope_type,
        "is_mutation": is_mutation,
    }
    for code, name, module, scope_type, is_mutation in PERMISSIONS_CATALOG
}

# ---------------------------------------------------------------------------
# 2. CÁC BẤT BIẾN & TRẦN QUYỀN HẠN CỨNG (HARD CEILINGS & INVARIANTS)
# ---------------------------------------------------------------------------
# INV-05: Không một ai (kể cả Chủ nhiệm, Cố vấn, Admin Server) được cấp các quyền này
UNIVERSAL_NEVER_GRANTED: frozenset[str] = frozenset({
    "messaging.private.read_others",
    "social.playlist.view_private_others",
})

# Quyền độc quyền tuyệt đối của Admin Server ("admin server là tôi"):
# Kể cả Chủ nhiệm CLB hay Phó chủ nhiệm cũng KHÔNG có quyền nâng cấp / miễn nhiệm
# các chức vụ lãnh đạo chủ chốt (Chủ nhiệm, Phó chủ nhiệm, Trưởng ban, Cố vấn).
SERVER_ADMIN_EXCLUSIVE_PERMISSIONS: frozenset[str] = frozenset({
    "server.leadership.manage",
    "club.officer.appoint_head",
})

# INV-03: Các thao tác bắt buộc người thực hiện khác đối tượng đích (actor != target_user)
SELF_FORBIDDEN_ACTIONS: frozenset[str] = frozenset({
    "dept.task.approve",
    "dept.skill.verify",
    "dept.deputy.appoint",
    "dept.permission.delegate",
    "club.officer.appoint_deputy",
    "club.officer.appoint_head",
    "club.permission.delegate",
    "club.member.restore",
    "club.member.suspend_temporary",
    "club.member.expel_permanent",
    "club.finance.approve_transaction",
    "dept.evaluation.finalize",
    "club.evaluation.finalize",
})

# INV-04: Danh sách trắng tuyệt đối của Cố vấn (Hard Read-Only — cấm mọi mutation & task cá nhân)
ADVISOR_ALLOWED_READ_PERMISSIONS: frozenset[str] = frozenset({
    "club.overview.supervise",
    "dept.page.view",
    "dept.roster.view",
    "dept.progress.view_summary",
    "club.event.view_internal",
    "club.member.view_lifecycle",
    "club.proposal.review_comment",
    "club.finance.view_summary",
    "club.report.export",
})

# Quyền xem ở chế độ READ_ONLY chéo ban (khi thành viên/cán bộ Ban A sang xem Ban B)
CROSS_DEPT_READ_ONLY_PERMISSIONS: frozenset[str] = frozenset({
    "dept.page.view",
    "dept.roster.view",
    "dept.progress.view_summary",
})

# Quyền mặc định của một Thành viên chính thức trong Ban mình đang ACTIVE
MEMBER_IN_OWN_DEPT_PERMISSIONS: frozenset[str] = CROSS_DEPT_READ_ONLY_PERMISSIONS | frozenset({
    "dept.task.view_personal_self",
    "dept.proposal.create_member",
})

# Quyền mặc định của Phó ban (khi CHƯA được ủy quyền thêm gói nào)
DEPUTY_HEAD_BASELINE_PERMISSIONS: frozenset[str] = MEMBER_IN_OWN_DEPT_PERMISSIONS | frozenset({
    "dept.assist.coordinate_view",
})

# 4 Gói ủy quyền chuẩn của Phó ban (Chỉ thị 3.1)
DEPUTY_HEAD_BUNDLE_PERMISSIONS: dict[str, frozenset[str]] = {
    GrantBundleCode.BUNDLE_TASK_OPS: frozenset({
        "dept.task.view_all",
        "dept.task.assign",
        "dept.task.approve",
    }),
    GrantBundleCode.BUNDLE_TRAINING_CONTENT: frozenset({
        "dept.training.manage",
        "dept.skill.verify",
        "dept.post.moderate",
    }),
    GrantBundleCode.BUNDLE_HR_SCREENING: frozenset({
        "dept.member.screen",
        "dept.member.manage",
        "dept.evaluation.propose",
    }),
    GrantBundleCode.BUNDLE_RESOURCE_PROPOSAL: frozenset({
        "dept.document.manage",
        "dept.event.manage_internal",
        "dept.proposal.submit_to_bcn",
    }),
}

# Trần cứng của Phó ban (kể cả có tạo grant CUSTOM cũng bị chặn tuyệt đối)
DEPUTY_HEAD_FORBIDDEN_PERMISSIONS: frozenset[str] = frozenset({
    "dept.deputy.appoint",
    "dept.permission.delegate",
    "dept.evaluation.finalize",
}) | frozenset(code for code, _, _, scope, _ in PERMISSIONS_CATALOG if scope == ScopeType.CLUB)

# Quyền đầy đủ của Trưởng ban tại chính Ban mình quản lý
DEPT_HEAD_OWN_DEPT_PERMISSIONS: frozenset[str] = (
    DEPUTY_HEAD_BASELINE_PERMISSIONS
    | DEPUTY_HEAD_BUNDLE_PERMISSIONS[GrantBundleCode.BUNDLE_TASK_OPS]
    | DEPUTY_HEAD_BUNDLE_PERMISSIONS[GrantBundleCode.BUNDLE_TRAINING_CONTENT]
    | DEPUTY_HEAD_BUNDLE_PERMISSIONS[GrantBundleCode.BUNDLE_HR_SCREENING]
    | DEPUTY_HEAD_BUNDLE_PERMISSIONS[GrantBundleCode.BUNDLE_RESOURCE_PROPOSAL]
    | frozenset({
        "dept.deputy.appoint",
        "dept.permission.delegate",
        "dept.evaluation.finalize",
    })
)

# Quyền mặc định của Phó chủ nhiệm ngay sau khi được Admin Server nâng cấp:
# Cả Chủ nhiệm VÀ Phó chủ nhiệm đều có quyền nâng role Khách -> Thành viên & Phân Ban!
VICE_CHAIRMAN_BASELINE_PERMISSIONS: frozenset[str] = frozenset({
    "club.overview.supervise",
    "dept.page.view",
    "dept.roster.view",
    "dept.progress.view_summary",
    "club.event.view_internal",
    "club.member.view_lifecycle",
    "club.proposal.review_comment",
    "club.member.approve",
    "club.member.transfer_dept",
    "dept.member.screen",
    "dept.member.manage",
})

# 4 Mảng phụ trách chuyên sâu của Phó chủ nhiệm (Chỉ thị 3.1)
VICE_CHAIRMAN_PORTFOLIO_PERMISSIONS: dict[str, frozenset[str]] = {
    GrantBundleCode.PORTFOLIO_OPS: frozenset({
        "club.dept.supervise_ops",
        "dept.task.view_all",
        "dept.task.assign",
        "dept.task.approve",
        "club.announcement.publish",
    }),
    GrantBundleCode.PORTFOLIO_HR: frozenset({
        "club.member.approve",
        "club.member.transfer_dept",
        "club.officer.appoint_deputy",
        "dept.deputy.appoint",
        "dept.member.screen",
        "dept.member.manage",
        "club.member.suspend_temporary",
        "club.evaluation.finalize",
    }),
    GrantBundleCode.PORTFOLIO_EVENT: frozenset({
        "club.event.approve",
        "club.event.configure_rsvp",
        "club.media.approve_public",
        "club.social.moderate",
        "dept.event.manage_internal",
    }),
    GrantBundleCode.PORTFOLIO_FINANCE_DOC: frozenset({
        "club.finance.view_summary",
        "club.finance.create_transaction",
        "club.finance.approve_transaction",
        "club.document.manage_confidential",
        "club.report.export",
    }),
}

# Trần cứng của Phó chủ nhiệm (độc quyền của Chủ nhiệm CLB hoặc Admin Server)
VICE_CHAIRMAN_FORBIDDEN_PERMISSIONS: frozenset[str] = SERVER_ADMIN_EXCLUSIVE_PERMISSIONS | frozenset({
    "club.permission.delegate",
    "club.governance.manage_departments",
    "club.governance.update_policy",
    "club.member.expel_permanent",
})

BUNDLE_PERMISSION_MAP: dict[str, frozenset[str]] = {
    **DEPUTY_HEAD_BUNDLE_PERMISSIONS,
    **VICE_CHAIRMAN_PORTFOLIO_PERMISSIONS,
}


class PermissionEngine:
    """
    Điểm kiểm tra phân quyền duy nhất tại Backend cho cả Giao diện Web và `/api/v1/`.

    Không bao giờ tin cờ UI; không bao giờ cấp quyền dựa trên `UserSkill` (`INV-01`).
    """

    @staticmethod
    def get_active_appointments(user) -> list[Appointment]:
        if not user or not getattr(user, "is_authenticated", False) or not user.pk:
            return []
        now = timezone.now()
        return list(
            Appointment.objects.select_related("position", "department")
            .filter(user=user, is_active=True, ended_at__isnull=True)
            .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=now))
        )

    @staticmethod
    def get_active_grants(user) -> list[PermissionGrant]:
        if not user or not getattr(user, "is_authenticated", False) or not user.pk:
            return []
        now = timezone.now()
        grants = (
            PermissionGrant.objects.select_related(
                "bound_appointment__position", "department"
            )
            .prefetch_related("custom_permissions")
            .filter(
                grantee=user,
                is_active=True,
                revoked_at__isnull=True,
                starts_at__lte=now,
                bound_appointment__is_active=True,
                bound_appointment__ended_at__isnull=True,
            )
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
            .filter(
                Q(bound_appointment__ends_at__isnull=True)
                | Q(bound_appointment__ends_at__gt=now)
            )
        )
        return list(grants)

    @staticmethod
    def get_active_department_ids(user) -> set[int]:
        if not user or not getattr(user, "is_authenticated", False) or not user.pk:
            return set()
        return set(
            DepartmentMembership.objects.filter(
                user=user,
                status=DeptMembershipStatus.ACTIVE,
                department__is_active=True,
            ).values_list("department_id", flat=True)
        )

    @classmethod
    def _grants_permissions_for_grant(cls, grant: PermissionGrant) -> set[str]:
        pos_code = grant.bound_appointment.position.code
        perms = set(BUNDLE_PERMISSION_MAP.get(grant.bundle_code, frozenset()))
        if grant.bundle_code == GrantBundleCode.CUSTOM:
            perms |= {p.code for p in grant.custom_permissions.all()}

        # Áp trần cứng theo chức vụ người nhận ủy quyền
        if pos_code == PositionCode.DEPUTY_HEAD:
            perms -= DEPUTY_HEAD_FORBIDDEN_PERMISSIONS
        elif pos_code == PositionCode.VICE_CHAIRMAN:
            perms -= VICE_CHAIRMAN_FORBIDDEN_PERMISSIONS
        else:
            return set()
        return perms - UNIVERSAL_NEVER_GRANTED

    @classmethod
    def get_department_access_mode(
        cls, user, department: Department, *, _preloaded: dict | None = None
    ) -> str:
        """
        Xác định chế độ truy cập của `user` đối với một `department` cụ thể:
        - `DENIED`: Khách, chưa đăng nhập, tài khoản bị khoá hoặc thành viên bị `SUSPENDED`.
        - `MANAGE`: Chủ nhiệm, Trưởng ban của chính Ban này, Phó ban của Ban này đã có gói ủy quyền,
                    hoặc Phó chủ nhiệm có mảng Vận hành / Nhân sự áp dụng cho Ban này.
        - `MEMBER`: Thành viên đang `ACTIVE` của Ban này (kể cả khi người đó là Trưởng ban của Ban khác!),
                    hoặc Phó ban của Ban này khi chưa có gói ủy quyền quản trị.
        - `READ_ONLY`: Thành viên/cán bộ của Ban khác sang xem chéo ban, hoặc Cố vấn (`ADVISOR`).
        """
        if not user or not getattr(user, "is_authenticated", False) or not user.pk:
            return "DENIED"
        if user.is_locked or user.account_status == AccountStatus.LOCKED:
            return "DENIED"
        if getattr(user, "is_server_admin", False):
            return "MANAGE"
        cm = _preloaded["cm"] if _preloaded is not None else user.club_membership_record
        if cm and cm.status == ClubMembershipStatus.SUSPENDED:
            return "DENIED"

        appointments = (
            _preloaded["appointments"]
            if _preloaded is not None
            else cls.get_active_appointments(user)
        )
        pos_codes_club = {
            a.position.code for a in appointments if a.scope_type == ScopeType.CLUB
        }
        pos_codes_this_dept = {
            a.position.code
            for a in appointments
            if a.scope_type == ScopeType.DEPARTMENT and a.department_id == department.id
        }

        if PositionCode.CHAIRMAN in pos_codes_club:
            return "MANAGE"
        if PositionCode.DEPT_HEAD in pos_codes_this_dept:
            return "MANAGE"

        grants = (
            _preloaded["grants"]
            if _preloaded is not None
            else cls.get_active_grants(user)
        )
        if PositionCode.VICE_CHAIRMAN in pos_codes_club:
            for g in grants:
                if g.bound_appointment.position.code == PositionCode.VICE_CHAIRMAN and (
                    g.department_id is None or g.department_id == department.id
                ):
                    if g.bundle_code in (
                        GrantBundleCode.PORTFOLIO_OPS,
                        GrantBundleCode.PORTFOLIO_HR,
                    ) or cls._grants_permissions_for_grant(g):
                        return "MANAGE"

        if PositionCode.DEPUTY_HEAD in pos_codes_this_dept:
            for g in grants:
                if (
                    g.bound_appointment.position.code == PositionCode.DEPUTY_HEAD
                    and g.department_id == department.id
                    and cls._grants_permissions_for_grant(g)
                ):
                    return "MANAGE"
            return "MEMBER"

        active_dept_ids = (
            _preloaded["active_dept_ids"]
            if _preloaded is not None
            else cls.get_active_department_ids(user)
        )
        if department.id in active_dept_ids and cm and cm.status == ClubMembershipStatus.ACTIVE:
            return "MEMBER"

        if (cm and cm.status == ClubMembershipStatus.ACTIVE and active_dept_ids) or appointments:
            return "READ_ONLY"

        return "DENIED"

    @classmethod
    def authorize(
        cls,
        actor,
        permission_code: str,
        department: Department | None = None,
        target_user=None,
        resource: ResourceAccessRule | None = None,
        *,
        _preloaded: dict | None = None,
    ) -> bool:
        """
        Kiểm tra quyền đa chiều thực tế ở Backend.
        Trả về `True` nếu được phép, `False` nếu bị từ chối.
        """
        # INV-05: Ranh giới bí mật tuyệt đối (kể cả Chủ nhiệm & Admin Server đều bị cấm)
        if permission_code in UNIVERSAL_NEVER_GRANTED:
            return False

        # Kiểm tra tài khoản & trạng thái khoá
        if not actor or not getattr(actor, "is_authenticated", False) or not actor.pk:
            return False
        if actor.is_locked or actor.account_status == AccountStatus.LOCKED:
            return False

        is_srv_admin = bool(getattr(actor, "is_server_admin", False))

        # Độc quyền tuyệt đối của Admin Server ("admin server là tôi"):
        # Nâng cấp / miễn nhiệm Chủ nhiệm, Phó chủ nhiệm, Trưởng ban, Cố vấn
        if permission_code in SERVER_ADMIN_EXCLUSIVE_PERMISSIONS:
            return is_srv_admin

        # INV-03: Phân tách nhiệm vụ (không tự duyệt / tự bổ nhiệm / tự xác minh skill bản thân)
        if (
            target_user is not None
            and getattr(target_user, "pk", None) == actor.pk
            and permission_code in SELF_FORBIDDEN_ACTIONS
        ):
            return False

        # Kiểm tra ACL cấp tài nguyên nếu truyền kèm resource (Chỉ thị 3.4)
        if resource is not None and not cls.can_access_resource(actor, resource):
            return False

        if is_srv_admin:
            return permission_code in PERMISSION_META

        # Thành viên đang bị tạm khoá tư cách CLB không có quyền nghiệp vụ nội bộ
        cm = _preloaded["cm"] if _preloaded is not None else actor.club_membership_record
        if cm and cm.status == ClubMembershipStatus.SUSPENDED:
            return False

        appointments = (
            _preloaded["appointments"]
            if _preloaded is not None
            else cls.get_active_appointments(actor)
        )
        club_positions = {
            a.position.code for a in appointments if a.scope_type == ScopeType.CLUB
        }
        active_dept_ids = (
            _preloaded["active_dept_ids"]
            if _preloaded is not None
            else cls.get_active_department_ids(actor)
        )
        # Chỉ mở chức năng Thành viên sau khi đã được nâng role VÀ phân vào ít nhất 1 Ban đang hoạt động
        is_active_club_member = bool(
            cm and cm.status == ClubMembershipStatus.ACTIVE and bool(active_dept_ids)
        )

        # Nếu là Guest / Ứng viên chưa được nâng role + phân Ban và không giữ chức vụ nào -> Từ chối
        if not is_active_club_member and not appointments:
            return False

        # INV-04: Cố vấn thuần tuý (không kiêm nhiệm chức điều hành và không phải TV thường đang thao tác cá nhân)
        executive_positions = {
            PositionCode.CHAIRMAN,
            PositionCode.VICE_CHAIRMAN,
            PositionCode.DEPT_HEAD,
            PositionCode.DEPUTY_HEAD,
            PositionCode.CORE_MEMBER,
        }
        has_any_exec_or_member = is_active_club_member or any(
            a.position.code in executive_positions for a in appointments
        )
        if PositionCode.ADVISOR in club_positions and not has_any_exec_or_member:
            return permission_code in ADVISOR_ALLOWED_READ_PERMISSIONS

        # 1. Chủ nhiệm CLB (`CHAIRMAN`) — có toàn quyền điều hành CLB,
        #    TRỪ các quyền độc quyền Admin Server (nâng cấp Chủ nhiệm / Phó CN / Trưởng ban), INV-03 & INV-05
        if PositionCode.CHAIRMAN in club_positions:
            return (
                permission_code in PERMISSION_META
                and permission_code not in SERVER_ADMIN_EXCLUSIVE_PERMISSIONS
            )

        grants = (
            _preloaded["grants"]
            if _preloaded is not None
            else cls.get_active_grants(actor)
        )

        # 2. Phó chủ nhiệm CLB (`VICE_CHAIRMAN`) — Baseline + Mảng phụ trách được Chủ nhiệm giao - Trần cứng
        if PositionCode.VICE_CHAIRMAN in club_positions:
            if permission_code in VICE_CHAIRMAN_BASELINE_PERMISSIONS:
                return True
            if permission_code not in VICE_CHAIRMAN_FORBIDDEN_PERMISSIONS:
                for g in grants:
                    if g.bound_appointment.position.code == PositionCode.VICE_CHAIRMAN:
                        if department is not None and g.department_id not in (
                            None,
                            department.id,
                        ):
                            continue
                        if permission_code in cls._grants_permissions_for_grant(g):
                            return True

        # 3. Cố vấn kiêm nhiệm (nếu vừa là Cố vấn vừa có thẻ thành viên): vẫn hưởng quyền đọc giám sát
        if PositionCode.ADVISOR in club_positions and permission_code in ADVISOR_ALLOWED_READ_PERMISSIONS:
            return True

        # 4. Các quyền cấp Ban (`ScopeType.DEPARTMENT`) bắt buộc đối chiếu đúng `department`!
        meta = PERMISSION_META.get(permission_code)
        if meta and meta["scope_type"] == ScopeType.DEPARTMENT:
            if department is None:
                return False

            dept_positions = {
                a.position.code
                for a in appointments
                if a.scope_type == ScopeType.DEPARTMENT and a.department_id == department.id
            }

            # 4a. Trưởng ban tại CHÍNH Ban này (sang Ban khác dept_positions sẽ rỗng!)
            if PositionCode.DEPT_HEAD in dept_positions:
                if permission_code in DEPT_HEAD_OWN_DEPT_PERMISSIONS:
                    return True

            # 4b. Phó ban tại CHÍNH Ban này: Baseline + Gói ủy quyền còn hạn tại Ban này
            if PositionCode.DEPUTY_HEAD in dept_positions:
                if permission_code in DEPUTY_HEAD_BASELINE_PERMISSIONS:
                    return True
                if permission_code not in DEPUTY_HEAD_FORBIDDEN_PERMISSIONS:
                    for g in grants:
                        if (
                            g.bound_appointment.position.code == PositionCode.DEPUTY_HEAD
                            and g.department_id == department.id
                            and permission_code in cls._grants_permissions_for_grant(g)
                        ):
                            return True

            # 4c. Thành viên đang ACTIVE tại Ban này (bao gồm cả Trưởng ban A đang làm TV thường ở Ban B)
            if department.id in active_dept_ids:
                if permission_code in MEMBER_IN_OWN_DEPT_PERMISSIONS:
                    return True

            # 4d. Thành viên / Cán bộ của Ban khác ghé sang Ban này -> CHỈ READ_ONLY!
            if is_active_club_member or appointments:
                if permission_code in CROSS_DEPT_READ_ONLY_PERMISSIONS:
                    return True

            return False

        # 5. Một số quyền xem cấp CLB chung cho mọi thành viên chính thức đang ACTIVE
        if is_active_club_member and permission_code in {"club.event.view_internal"}:
            return True

        return False

    @classmethod
    def can_access_resource(cls, actor, rule: ResourceAccessRule) -> bool:
        """
        Kiểm tra quyền truy cập tài nguyên/tài liệu theo từng mức phân loại (Chỉ thị 3.4).

        TUYỆT ĐỐI KHÔNG kiểm tra `UserSkill` (`Skill != Permission` — `INV-01`)!
        """
        if not actor or not getattr(actor, "is_authenticated", False) or not actor.pk:
            return False
        if actor.is_locked or actor.account_status == AccountStatus.LOCKED:
            return False
        if getattr(actor, "is_server_admin", False):
            return True
        cm = actor.club_membership_record
        if cm and cm.status == ClubMembershipStatus.SUSPENDED:
            return False

        appointments = cls.get_active_appointments(actor)
        club_positions = {
            a.position.code for a in appointments if a.scope_type == ScopeType.CLUB
        }
        active_dept_ids = cls.get_active_department_ids(actor)
        is_active_club_member = bool(
            cm and cm.status == ClubMembershipStatus.ACTIVE and bool(active_dept_ids)
        )

        if not is_active_club_member and not appointments:
            return False

        # Chủ nhiệm hoặc người tạo tài nguyên
        if PositionCode.CHAIRMAN in club_positions:
            return True
        if rule.created_by_id and rule.created_by_id == actor.pk:
            return True

        # Mức 1: Tài nguyên chung toàn CLB
        if rule.classification == ResourceClassification.PUBLIC_CLUB:
            return True

        # Mức 4: Tài liệu mật Ban Chủ nhiệm
        if rule.classification == ResourceClassification.EXECUTIVE_CONFIDENTIAL:
            if PositionCode.ADVISOR in club_positions:
                return True
            if PositionCode.VICE_CHAIRMAN in club_positions and cls.authorize(
                actor, "club.document.manage_confidential"
            ):
                return True
            return rule.allowed_users.filter(pk=actor.pk).exists()

        # Trưởng ban (hoặc Phó ban được ủy quyền quản lý tài liệu) của chính Ban sở hữu tài nguyên
        if rule.department_id:
            if cls.authorize(actor, "dept.document.manage", department=rule.department):
                return True

        # Mức 2: Nội bộ Ban -> thành viên đang ACTIVE thuộc Ban đó (xem chéo ban READ_ONLY bị chặn)
        if rule.classification == ResourceClassification.DEPARTMENT_INTERNAL:
            if rule.department_id and rule.department_id in cls.get_active_department_ids(actor):
                return True
            return rule.allowed_users.filter(pk=actor.pk).exists()

        # Mức 3: Tài liệu mật theo ACL (`RESTRICTED_ACL`) -> CHỈ người/chức vụ được cấp quyền tường minh!
        if rule.classification == ResourceClassification.RESTRICTED_ACL:
            if rule.allowed_users.filter(pk=actor.pk).exists():
                return True
            active_pos_ids = [
                a.position_id
                for a in appointments
                if a.scope_type == ScopeType.CLUB
                or (rule.department_id and a.department_id == rule.department_id)
            ]
            if active_pos_ids and rule.allowed_positions.filter(pk__in=active_pos_ids).exists():
                return True
            return False

        return False

    @classmethod
    def require(
        cls,
        actor,
        permission_code: str,
        department: Department | None = None,
        target_user=None,
        resource: ResourceAccessRule | None = None,
    ) -> None:
        """Ném `PermissionDenied` (HTTP 403) với thông điệp rõ ràng nếu không đủ quyền."""
        if not cls.authorize(
            actor,
            permission_code,
            department=department,
            target_user=target_user,
            resource=resource,
        ):
            if permission_code in SERVER_ADMIN_EXCLUSIVE_PERMISSIONS:
                raise PermissionDenied(
                    "Chỉ Admin Server mới có quyền nâng cấp hoặc miễn nhiệm chức vụ "
                    "Chủ nhiệm, Phó chủ nhiệm, Trưởng ban và Cố vấn."
                )
            scope_txt = f" trong phạm vi {department.name}" if department else ""
            raise PermissionDenied(
                f"Bạn không có quyền '{permission_code}'{scope_txt}."
            )

    @classmethod
    def summarize_actor_context(cls, user) -> dict:
        """Tổng hợp toàn bộ tư cách, chức vụ, ban và quyền hiệu lực để hiển thị UI & `/api/v1/auth/me/`."""
        appointments = cls.get_active_appointments(user)
        grants = cls.get_active_grants(user)
        cm = user.club_membership_record if getattr(user, "is_authenticated", False) else None
        dept_memberships = (
            list(
                DepartmentMembership.objects.select_related("department").filter(
                    user=user,
                    status=DeptMembershipStatus.ACTIVE,
                    department__is_active=True,
                )
            )
            if getattr(user, "is_authenticated", False) and user.pk
            else []
        )
        preloaded = {
            "cm": cm,
            "appointments": appointments,
            "grants": grants,
            "active_dept_ids": {dm.department_id for dm in dept_memberships},
        }
        return {
            "club_status": cm.status if cm else "GUEST",
            "member_code": cm.member_code if cm else None,
            "is_server_admin": bool(getattr(user, "is_server_admin", False)),
            "appointments": [
                {
                    "id": a.id,
                    "position_code": a.position.code,
                    "position_name": a.position.name,
                    "scope_type": a.scope_type,
                    "department_id": a.department_id,
                    "department_name": a.department.name if a.department_id else None,
                    "department_slug": a.department.slug if a.department_id else None,
                    "term_label": a.term_label,
                    "title_note": a.title_note,
                    "ends_at": a.ends_at.isoformat() if a.ends_at else None,
                }
                for a in appointments
            ],
            "departments": [
                {
                    "id": dm.department.id,
                    "code": dm.department.code,
                    "name": dm.department.name,
                    "slug": dm.department.slug,
                    "is_demo": dm.department.is_demo,
                    "access_mode": cls.get_department_access_mode(
                        user, dm.department, _preloaded=preloaded
                    ),
                }
                for dm in dept_memberships
            ],
            "grants": [
                {
                    "id": g.id,
                    "bundle_code": g.bundle_code,
                    "bundle_label": g.get_bundle_code_display(),
                    "scope_type": g.scope_type,
                    "department_name": g.department.name if g.department_id else "Toàn CLB",
                    "expires_at": g.expires_at.isoformat() if g.expires_at else None,
                    "effective_permissions": sorted(cls._grants_permissions_for_grant(g)),
                }
                for g in grants
            ],
            "can_access_club_governance": any(
                cls.authorize(user, code, _preloaded=preloaded)
                for code in (
                    "server.leadership.manage",
                    "club.member.approve",
                    "club.dept.supervise_ops",
                    "club.event.approve",
                    "club.finance.approve_transaction",
                    "club.evaluation.finalize",
                )
            ),
            "can_access_club_finance": any(
                cls.authorize(user, code, _preloaded=preloaded)
                for code in (
                    "club.finance.view_summary",
                    "club.finance.create_transaction",
                    "club.finance.approve_transaction",
                )
            ),
            "can_export_club_reports": cls.authorize(
                user, "club.report.export", _preloaded=preloaded
            ),
            "can_manage_server_leadership": cls.authorize(
                user, "server.leadership.manage", _preloaded=preloaded
            ),
            "is_advisor": any(a.position.code == PositionCode.ADVISOR for a in appointments),
            "is_chairman": any(a.position.code == PositionCode.CHAIRMAN for a in appointments),
            "is_vice_chairman": any(
                a.position.code == PositionCode.VICE_CHAIRMAN for a in appointments
            ),
        }


def club_member_required(view_func):
    """Decorator bắt buộc người dùng có quyền truy cập Không gian Nội bộ CLB."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not request.user.has_active_club_access:
            raise PermissionDenied(
                "Khu vực này chỉ dành cho thành viên chính thức và ban điều hành CLB KMG."
            )
        return view_func(request, *args, **kwargs)

    return wrapper


def api_login_required(view_func):
    """Decorator chuẩn cho `/api/v1/` trả JSON Envelope `401` khi chưa đăng nhập."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse(
                {
                    "ok": False,
                    "error": {
                        "code": "AUTHENTICATION_REQUIRED",
                        "message": "Bạn cần đăng nhập để gọi API này.",
                        "details": {},
                    },
                },
                status=401,
            )
        return view_func(request, *args, **kwargs)

    return wrapper
