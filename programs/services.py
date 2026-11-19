"""
Tầng Nghiệp vụ Phase 3 (`programs.services`):
1. Kho Tài liệu Mật & Resource-level ACL (`WF20`, `INV-01`, `PA-01`, `PA-02`, `SEC-01`):
   - Kiểm tra tệp tải lên an toàn (chống `.html`/`.svg`/`.exe`, kiểm tra magic bytes & dung lượng 20MB).
   - Lưu vật lý trong `PrivateVaultStorage` ngoài `/media/`, băm SHA-256, phát hiện xâm nhập qua `DocumentAccessLog` bất biến.
   - Đánh giá 5 tầng phân loại (`PUBLIC`, `CLUB_INTERNAL`, `DEPT_INTERNAL`, `RESTRICTED`, `HIGHLY_RESTRICTED`).
   - Bảo đảm Two-Phase Query (`PA-01`): lọc bảo mật trước, chỉ gắn cờ gợi ý `UserSkill` lên danh sách đã được phép.
   - Tự động thu hồi ACL gắn vòng đời (`PA-02`) khi chuyển Ban, hết nhiệm kỳ hoặc tạm khoá/rời CLB.
   - Cơ chế Break-Glass có kiểm soát cho Chủ nhiệm CLB (`BREAK_GLASS` + lý do bắt buộc + `AuditLog` + cảnh báo).
2. Quy trình Đề xuất Hoạt động 6 trạng thái (`WF17`, `WF18`, `INV-03`, `DB-07`).
3. Đào tạo Chuyên môn, Lịch tập luyện Band (`BE-04`) & Nhắc lịch tự động `T-48h`/`T-12h` (`DB-06`).
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
import hashlib
import mimetypes
import os
import uuid

from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import AccountStatus, AuditLog, User
from core.security import get_client_ip
from notifications.models import (
    NotificationKind,
    ReminderStage,
    ReminderTargetType,
)
from notifications.services import (
    dispatch_idempotent_reminder,
    send_operational_alert,
)
from operations.models import (
    ClubEventScope,
    ClubTask,
    ClubTaskAssignee,
)
from operations.services import clean_evidence_url, create_club_event
from organization.models import (
    Appointment,
    ClubMembershipStatus,
    Department,
    DepartmentMembership,
    DeptMembershipStatus,
    Position,
    PositionCode,
    ScopeType,
    Skill,
    SkillVerificationStatus,
    UserSkill,
)
from organization.permissions import PermissionEngine
from organization.services import GovernanceError

from .models import (
    AclPermissionLevel,
    AclSubjectType,
    ConfidentialDocument,
    DepartmentProposal,
    DepartmentShowcaseItem,
    DocumentACLEntry,
    DocumentAccessAction,
    DocumentAccessLog,
    DocumentCategory,
    DocumentClassification,
    DocumentVersion,
    PracticeParticipant,
    PracticeResponseStatus,
    PracticeSession,
    PracticeSessionStatus,
    ProposalComment,
    ProposalReview,
    ProposalReviewDecision,
    ProposalScope,
    ProposalStatus,
    ProposalType,
    ShowcaseItemType,
    TrainingCourse,
    TrainingCourseStatus,
    TrainingEnrollment,
    TrainingEnrollmentStatus,
)

MAX_VAULT_FILE_BYTES = 20 * 1024 * 1024  # 20 MB

FORBIDDEN_EXTENSIONS = frozenset(
    {
        ".html",
        ".htm",
        ".xhtml",
        ".svg",
        ".js",
        ".mjs",
        ".php",
        ".phtml",
        ".asp",
        ".aspx",
        ".jsp",
        ".exe",
        ".dll",
        ".bat",
        ".cmd",
        ".ps1",
        ".sh",
        ".vbs",
        ".jar",
        ".msi",
        ".scr",
        ".com",
    }
)

ALLOWED_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".docx",
        ".doc",
        ".xlsx",
        ".xls",
        ".pptx",
        ".ppt",
        ".txt",
        ".md",
        ".csv",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".zip",
        ".mp3",
        ".wav",
        ".ogg",
        ".flac",
        ".mid",
        ".midi",
        ".musicxml",
        ".mxl",
    }
)

_LEVEL_RANK = {
    AclPermissionLevel.VIEW: 1,
    AclPermissionLevel.DOWNLOAD: 2,
    AclPermissionLevel.MANAGE: 3,
}


def _is_pure_advisor(actor: User) -> bool:
    if not actor or not getattr(actor, "is_authenticated", False) or not actor.pk:
        return False
    if getattr(actor, "is_server_admin", False):
        return False
    cm = actor.club_membership_record
    active_dept_ids = PermissionEngine.get_active_department_ids(actor)
    is_active_member = bool(
        cm and cm.status == ClubMembershipStatus.ACTIVE and bool(active_dept_ids)
    )
    appts = PermissionEngine.get_active_appointments(actor)
    club_pos = {a.position.code for a in appts if a.scope_type == ScopeType.CLUB}
    exec_pos = {
        PositionCode.CHAIRMAN,
        PositionCode.VICE_CHAIRMAN,
        PositionCode.DEPT_HEAD,
        PositionCode.DEPUTY_HEAD,
        PositionCode.CORE_MEMBER,
    }
    has_exec = is_active_member or any(a.position.code in exec_pos for a in appts)
    return PositionCode.ADVISOR in club_pos and not has_exec


def _is_active_club_actor(actor: User) -> bool:
    if not actor or not getattr(actor, "is_authenticated", False) or not actor.pk:
        return False
    if actor.is_locked or actor.account_status == AccountStatus.LOCKED:
        return False
    if getattr(actor, "is_server_admin", False):
        return True
    cm = actor.club_membership_record
    if cm and cm.status == ClubMembershipStatus.SUSPENDED:
        return False
    if cm and cm.status in (ClubMembershipStatus.ALUMNI, ClubMembershipStatus.LEFT):
        appts = PermissionEngine.get_active_appointments(actor)
        return bool(appts)
    active_depts = PermissionEngine.get_active_department_ids(actor)
    if cm and cm.status == ClubMembershipStatus.ACTIVE and active_depts:
        return True
    return bool(PermissionEngine.get_active_appointments(actor))


def _has_position_in_club(actor: User, pos_code: str, department: Department | None = None) -> bool:
    appts = PermissionEngine.get_active_appointments(actor)
    for a in appts:
        if a.position.code != pos_code:
            continue
        if department is None and a.scope_type == ScopeType.CLUB:
            return True
        if department is not None and a.scope_type == ScopeType.DEPARTMENT and a.department_id == department.id:
            return True
    return False


# ---------------------------------------------------------------------------
# 1. KHO TÀI LIỆU MẬT & BẢO MẬT TẢI TỆP (`SEC-01`, `WF20`, `INV-01`, `PA-01`, `PA-02`)
# ---------------------------------------------------------------------------
def validate_and_prepare_vault_file(uploaded_file) -> dict:
    """
    Kiểm tra an toàn tệp trước khi lưu vào Kho Mật (`WF20`, `SEC-01`):
    - Chặn tuyệt đối tệp thực thi, HTML, SVG, PHP, JS.
    - Chỉ chấp nhận định dạng cho phép và giới hạn tối đa 20MB.
    - Kiểm tra magic bytes chống giả mạo tệp thực thi hoặc script ẩn.
    - Trả về tuple/dict chứa tên lưu trữ UUID an toàn, ContentFile, SHA-256 và metadata.
    """
    if uploaded_file is None:
        raise GovernanceError("Vui lòng chọn tệp tài liệu để tải lên.")

    raw_name = os.path.basename(getattr(uploaded_file, "name", "") or "").strip()
    if not raw_name:
        raise GovernanceError("Tên tệp tài liệu không hợp lệ.")

    _, ext = os.path.splitext(raw_name)
    ext = ext.lower()
    if ext in FORBIDDEN_EXTENSIONS:
        raise GovernanceError(
            f"Định dạng tệp '{ext}' bị chặn vì lý do bảo mật (chống XSS/mã độc thực thi)."
        )
    if ext not in ALLOWED_EXTENSIONS:
        raise GovernanceError(
            f"Định dạng tệp '{ext}' chưa được hỗ trợ trong Kho Tài liệu KMG."
        )

    size = getattr(uploaded_file, "size", None)
    if size is not None and size > MAX_VAULT_FILE_BYTES:
        raise GovernanceError("Dung lượng tệp vượt quá giới hạn tối đa 20 MB.")

    try:
        uploaded_file.seek(0)
    except Exception:
        pass
    data = uploaded_file.read()
    try:
        uploaded_file.seek(0)
    except Exception:
        pass

    if not data:
        raise GovernanceError("Tệp tài liệu rỗng (0 bytes), không thể lưu trữ.")
    if len(data) > MAX_VAULT_FILE_BYTES:
        raise GovernanceError("Dung lượng tệp vượt quá giới hạn tối đa 20 MB.")

    head = data[:512]
    head_l = head.lstrip().lower()
    if head.startswith(b"MZ") or head.startswith(b"\x7fELF") or head[:4] in (
        b"\xfe\xed\xfa\xce",
        b"\xfe\xed\xfa\xcf",
        b"\xca\xfe\xba\xbe",
    ):
        raise GovernanceError("Phát hiện tệp nhị phân thực thi giả mạo đuôi mở rộng, đã chặn tải lên.")
    if head_l.startswith(b"#!"):
        raise GovernanceError("Phát hiện script shell thực thi, đã chặn tải lên.")
    if ext not in (".txt", ".md", ".csv") and any(
        sig in head_l for sig in (b"<script", b"<html", b"<!doctype html", b"<svg", b"<?php")
    ):
        raise GovernanceError("Phát hiện mã HTML/SVG/Script nhúng trái phép bên trong tệp tài liệu.")

    checksum = hashlib.sha256(data).hexdigest()
    guessed_ct, _ = mimetypes.guess_type(raw_name)
    content_type = (
        getattr(uploaded_file, "content_type", "") or guessed_ct or "application/octet-stream"
    )[:120]
    safe_storage_name = f"{uuid.uuid4().hex}{ext}"
    return {
        "original_filename": raw_name[:255],
        "storage_name": safe_storage_name,
        "content_file": ContentFile(data, name=safe_storage_name),
        "content_type": content_type,
        "file_size": len(data),
        "checksum_sha256": checksum,
    }


def _matching_acl_rank(
    actor: User,
    document: ConfidentialDocument,
    *,
    only_user_entries: bool = False,
) -> int:
    """
    Đánh giá mức quyền cao nhất từ các bản ghi `DocumentACLEntry` đang hiệu lực.
    KHÔNG BAO GIỜ đọc `UserSkill` (`INV-01`).
    """
    now = timezone.now()
    entries = list(
        document.acl_entries.select_related(
            "bound_dept_membership",
            "bound_appointment__position",
        )
        .filter(is_active=True, revoked_at__isnull=True)
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
    )
    if not entries:
        return 0

    active_depts = None
    active_appts = None
    max_rank = 0

    for entry in entries:
        # PA-02: Kiểm tra ràng buộc vòng đời trực tiếp ngay lúc đánh giá
        if entry.bound_dept_membership_id is not None:
            if entry.bound_dept_membership.status != DeptMembershipStatus.ACTIVE:
                continue
        if entry.bound_appointment_id is not None:
            if not entry.bound_appointment.is_currently_effective:
                continue

        if only_user_entries and entry.subject_type != AclSubjectType.USER:
            continue

        matched = False
        if entry.subject_type == AclSubjectType.USER:
            matched = entry.user_id == actor.id
        elif entry.subject_type == AclSubjectType.POSITION:
            if active_appts is None:
                active_appts = PermissionEngine.get_active_appointments(actor)
            for appt in active_appts:
                if appt.position_id != entry.position_id:
                    continue
                if entry.position_department_id is None or appt.department_id == entry.position_department_id:
                    matched = True
                    break
        elif entry.subject_type == AclSubjectType.TASK and entry.task_id:
            matched = ClubTaskAssignee.objects.filter(
                task_id=entry.task_id, user_id=actor.id, is_active=True
            ).exists()
        elif entry.subject_type == AclSubjectType.DEPARTMENT and entry.department_id:
            if active_depts is None:
                active_depts = PermissionEngine.get_active_department_ids(actor)
            matched = entry.department_id in active_depts

        if matched:
            rank = _LEVEL_RANK.get(entry.permission_level, 0)
            if rank > max_rank:
                max_rank = rank
    return max_rank


def can_access_document(
    actor: User,
    document: ConfidentialDocument,
    required_level: str = AclPermissionLevel.DOWNLOAD,
) -> bool:
    """
    Kiểm tra quyền truy cập tài liệu theo 5 phân loại & Bất biến `INV-01` / `INV-04`:
    - `PUBLIC` / `CLUB_INTERNAL`: Thành viên CLB ACTIVE & Cố vấn (chỉ đọc).
    - `DEPT_INTERNAL`: Thành viên ACTIVE trong Ban sở hữu, Quản trị tài liệu Ban, BCN hoặc ACL.
    - `RESTRICTED`: Chủ sở hữu, Trưởng ban sở hữu, Phó ban sở hữu có `dept.document.manage`,
      hoặc người khớp `DocumentACLEntry` (`USER`/`POSITION`/`TASK`/`DEPARTMENT`).
      Chủ nhiệm CLB nếu không nằm trong ACL riêng cần dùng `break_glass_document_access`.
    - `HIGHLY_RESTRICTED`: CHỈ Chủ sở hữu, Trưởng ban sở hữu (hoặc Chủ nhiệm với tài liệu cấp CLB),
      hoặc thành viên đích danh trong `USER` ACL (bao gồm Break-Glass còn hiệu lực).
      Phó ban & Phó CN dù có gói quản lý tài liệu vẫn bị CHẶN nếu không có tên trong `USER` ACL!
    """
    if not _is_active_club_actor(actor):
        return False

    req_rank = _LEVEL_RANK.get(required_level, 2)
    if getattr(actor, "is_server_admin", False):
        return True

    # Cố vấn thuần túy (`INV-04`): Hard Read-Only, không bao giờ có quyền MANAGE; chỉ xem PUBLIC/CLUB_INTERNAL hoặc USER ACL.
    if _is_pure_advisor(actor):
        if req_rank >= _LEVEL_RANK[AclPermissionLevel.MANAGE]:
            return False
        if document.classification in (
            DocumentClassification.PUBLIC,
            DocumentClassification.CLUB_INTERNAL,
        ):
            return True
        acl_rank = _matching_acl_rank(actor, document, only_user_entries=True)
        return acl_rank >= req_rank

    cls = document.classification
    is_owner = bool(document.owner_id and document.owner_id == actor.id)
    is_dept_head_here = bool(
        document.department_id
        and _has_position_in_club(actor, PositionCode.DEPT_HEAD, document.department)
    )
    is_club_chair = _has_position_in_club(actor, PositionCode.CHAIRMAN)

    # Mức 5: Tuyệt mật (`HIGHLY_RESTRICTED`) — trần cứng nghiêm ngặt nhất
    if cls == DocumentClassification.HIGHLY_RESTRICTED:
        if is_owner or is_dept_head_here or (document.department_id is None and is_club_chair):
            return True
        user_acl_rank = _matching_acl_rank(actor, document, only_user_entries=True)
        return user_acl_rank >= req_rank

    # Mức 4: Tài liệu mật theo ACL (`RESTRICTED`)
    if cls == DocumentClassification.RESTRICTED:
        if is_owner or is_dept_head_here:
            return True
        if document.department_id is None and (
            is_club_chair or PermissionEngine.authorize(actor, "club.document.manage_confidential")
        ):
            return True
        if document.department_id and _has_position_in_club(
            actor, PositionCode.DEPUTY_HEAD, document.department
        ):
            if PermissionEngine.authorize(
                actor, "dept.document.manage", department=document.department
            ):
                return True
        acl_rank = _matching_acl_rank(actor, document, only_user_entries=False)
        return acl_rank >= req_rank

    # Mức 3: Nội bộ Ban (`DEPT_INTERNAL`)
    if cls == DocumentClassification.DEPT_INTERNAL:
        if is_owner or is_dept_head_here or is_club_chair:
            return True
        if PermissionEngine.authorize(actor, "club.document.manage_confidential"):
            return True
        if document.department_id:
            if PermissionEngine.authorize(
                actor, "dept.document.manage", department=document.department
            ):
                return True
            if (
                req_rank <= _LEVEL_RANK[AclPermissionLevel.DOWNLOAD]
                and document.department_id in PermissionEngine.get_active_department_ids(actor)
            ):
                return True
        return _matching_acl_rank(actor, document, only_user_entries=False) >= req_rank

    # Mức 1 & 2: `PUBLIC` / `CLUB_INTERNAL`
    if is_owner or is_dept_head_here or is_club_chair:
        return True
    if PermissionEngine.authorize(actor, "club.document.manage_confidential"):
        return True
    if document.department_id and PermissionEngine.authorize(
        actor, "dept.document.manage", department=document.department
    ):
        return True
    if req_rank <= _LEVEL_RANK[AclPermissionLevel.DOWNLOAD]:
        return True
    return _matching_acl_rank(actor, document, only_user_entries=False) >= req_rank


def filter_accessible_documents(
    actor: User,
    *,
    department: Department | None = None,
    classification: str = "",
    skill: Skill | None = None,
    query_text: str = "",
    include_archived: bool = False,
) -> list[dict]:
    """
    Truy vấn Hai Pha (`PA-01` & `INV-01`):
    - Pha 1 (Bảo mật): Chỉ giữ lại các tài liệu mà `can_access_document(actor, doc, VIEW)` trả True;
      tuyệt đối không rò rỉ tiêu đề tài liệu `RESTRICTED`/`HIGHLY_RESTRICTED` cho người không có quyền.
    - Pha 2 (Trải nghiệm UX): Gắn nhãn gợi ý nếu khớp `UserSkill(VERIFIED)` của người dùng
      hoặc lọc theo `?skill=`. Không bao giờ nới rộng danh sách từ Pha 1!
    """
    qs = ConfidentialDocument.objects.select_related(
        "department", "category", "owner"
    ).prefetch_related("recommended_skills", "versions")
    if not include_archived:
        qs = qs.filter(is_archived=False)
    if department is not None:
        qs = qs.filter(department=department)
    if classification and classification in DocumentClassification.values:
        qs = qs.filter(classification=classification)
    if query_text:
        q_clean = query_text.strip()
        qs = qs.filter(
            Q(title__icontains=q_clean)
            | Q(code__icontains=q_clean)
            | Q(description__icontains=q_clean)
            | Q(custom_category_label__icontains=q_clean)
        )

    # Pha 1: Lọc bảo mật tuyệt đối ở tầng Service
    authorized_docs = [
        doc
        for doc in qs
        if can_access_document(actor, doc, required_level=AclPermissionLevel.VIEW)
    ]

    # Pha 2: Áp dụng gợi ý / lọc theo Kỹ năng (UX only — KHÔNG thể làm tăng số bản ghi vượt quá Pha 1)
    verified_skill_ids = set(
        UserSkill.objects.filter(
            user=actor, verification_status=SkillVerificationStatus.VERIFIED
        ).values_list("skill_id", flat=True)
    )
    results = []
    for doc in authorized_docs:
        doc_skills = list(doc.recommended_skills.all())
        if skill is not None and not any(s.id == skill.id for s in doc_skills):
            continue
        matched_skills = [s for s in doc_skills if s.id in verified_skill_ids]
        results.append(
            {
                "document": doc,
                "latest_version": doc.latest_version,
                "can_download": can_access_document(actor, doc, required_level=AclPermissionLevel.DOWNLOAD),
                "can_manage": can_access_document(actor, doc, required_level=AclPermissionLevel.MANAGE),
                "recommended_skills": doc_skills,
                "matched_user_skills": matched_skills,
                "is_skill_recommended": bool(matched_skills),
            }
        )
    return results


def record_document_access(
    *,
    document: ConfidentialDocument,
    actor: User | None,
    action: str,
    version: DocumentVersion | None = None,
    request=None,
    reason: str = "",
) -> DocumentAccessLog:
    """Ghi sổ cái kiểm toán bất biến `DocumentAccessLog`. Gọi ngoài khối atomic bị rollback nếu ghi `DENIED_ATTEMPT`."""
    ip_addr = get_client_ip(request) if request is not None else None
    if ip_addr == "unknown":
        ip_addr = None
    ua = ""
    if request is not None:
        ua = (request.META.get("HTTP_USER_AGENT", "") or "")[:255]
    return DocumentAccessLog.objects.create(
        document=document,
        version=version,
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        action=action,
        ip_address=ip_addr,
        user_agent=ua,
        reason=(reason or "")[:255],
    )


def _generate_document_code(department: Department | None = None) -> str:
    prefix_dept = department.code[:4] if department else "CLUB"
    yr = timezone.localdate().year
    base = f"DOC-{prefix_dept}-{yr}"
    for seq in range(ConfidentialDocument.objects.filter(code__startswith=base).count() + 1, 9999):
        candidate = f"{base}-{seq:03d}"
        if not ConfidentialDocument.objects.filter(code=candidate).exists():
            return candidate
    return f"{base}-{uuid.uuid4().hex[:6].upper()}"


@transaction.atomic
def create_confidential_document(
    *,
    actor: User,
    title: str,
    classification: str,
    uploaded_file,
    department: Department | None = None,
    category: DocumentCategory | None = None,
    custom_category_label: str = "",
    description: str = "",
    recommended_skills: list[Skill] | None = None,
    change_note: str = "Tải lên phiên bản đầu tiên",
    request=None,
) -> tuple[ConfidentialDocument, DocumentVersion]:
    """Khởi tạo tài liệu mật mới kèm phiên bản v1 trong `PrivateVaultStorage`."""
    if _is_pure_advisor(actor):
        raise PermissionDenied("Cố vấn ở chế độ Hard Read-Only, không được tạo tài liệu.")
    if department is not None:
        if not (
            PermissionEngine.authorize(actor, "dept.document.manage", department=department)
            or PermissionEngine.authorize(actor, "club.document.manage_confidential")
        ):
            PermissionEngine.require(actor, "dept.document.manage", department=department)
    else:
        PermissionEngine.require(actor, "club.document.manage_confidential")

    clean_title = (title or "").strip()
    if not clean_title:
        raise GovernanceError("Tiêu đề tài liệu không được để trống.")
    if classification not in DocumentClassification.values:
        raise GovernanceError("Mức phân loại bảo mật tài liệu không hợp lệ.")
    if (
        classification == DocumentClassification.HIGHLY_RESTRICTED
        and department is not None
        and _has_position_in_club(actor, PositionCode.DEPUTY_HEAD, department)
        and not _has_position_in_club(actor, PositionCode.DEPT_HEAD, department)
        and not getattr(actor, "is_server_admin", False)
    ):
        raise PermissionDenied("Chỉ Trưởng ban hoặc Ban Chủ nhiệm mới được tạo tài liệu Tuyệt mật của Ban.")

    prepared = validate_and_prepare_vault_file(uploaded_file)
    doc = ConfidentialDocument.objects.create(
        code=_generate_document_code(department),
        title=clean_title[:200],
        description=(description or "").strip(),
        department=department,
        category=category,
        custom_category_label=(custom_category_label or "").strip()[:80],
        classification=classification,
        owner=actor,
    )
    if recommended_skills:
        doc.recommended_skills.set(recommended_skills)

    ver = DocumentVersion.objects.create(
        document=doc,
        version_number=1,
        file=prepared["content_file"],
        original_filename=prepared["original_filename"],
        content_type=prepared["content_type"],
        file_size=prepared["file_size"],
        checksum_sha256=prepared["checksum_sha256"],
        change_note=(change_note or "Phiên bản đầu tiên")[:255],
        uploaded_by=actor,
        is_current=True,
    )
    record_document_access(
        document=doc,
        version=ver,
        actor=actor,
        action=DocumentAccessAction.VERSION_UPLOAD,
        request=request,
        reason="Khởi tạo tài liệu v1",
    )
    AuditLog.write(
        actor,
        "Tải lên tài liệu mật",
        f"[{doc.code}] {doc.title}",
        note=f"{doc.get_classification_display()} · {prepared['original_filename']}",
    )
    return doc, ver


@transaction.atomic
def upload_document_version(
    *,
    actor: User,
    document: ConfidentialDocument,
    uploaded_file,
    change_note: str = "",
    request=None,
) -> DocumentVersion:
    """Tải lên phiên bản mới (v2, v3...) cho tài liệu hiện có (`WF20`)."""
    if not can_access_document(actor, document, required_level=AclPermissionLevel.MANAGE):
        raise PermissionDenied("Bạn không có quyền cập nhật phiên bản cho tài liệu này.")

    prepared = validate_and_prepare_vault_file(uploaded_file)
    DocumentVersion.objects.select_for_update().filter(
        document=document, is_current=True
    ).update(is_current=False)
    latest = document.versions.order_by("-version_number").first()
    next_num = (latest.version_number + 1) if latest else 1

    ver = DocumentVersion.objects.create(
        document=document,
        version_number=next_num,
        file=prepared["content_file"],
        original_filename=prepared["original_filename"],
        content_type=prepared["content_type"],
        file_size=prepared["file_size"],
        checksum_sha256=prepared["checksum_sha256"],
        change_note=(change_note or f"Cập nhật phiên bản v{next_num}")[:255],
        uploaded_by=actor,
        is_current=True,
    )
    document.save(update_fields=["updated_at"])
    record_document_access(
        document=document,
        version=ver,
        actor=actor,
        action=DocumentAccessAction.VERSION_UPLOAD,
        request=request,
        reason=f"Tải lên v{next_num}",
    )
    AuditLog.write(actor, "Cập nhật phiên bản tài liệu", f"{document.code} v{next_num}", note=ver.change_note)
    return ver


@transaction.atomic
def grant_document_acl(
    *,
    actor: User,
    document: ConfidentialDocument,
    subject_type: str,
    permission_level: str = AclPermissionLevel.DOWNLOAD,
    target_user: User | None = None,
    position: Position | None = None,
    position_department: Department | None = None,
    task: ClubTask | None = None,
    department: Department | None = None,
    reason: str = "",
    expires_at=None,
    request=None,
) -> DocumentACLEntry:
    """
    Cấp quyền ACL theo từng tài liệu (`Resource-level ACL`, Chỉ thị 3.4 & `PA-01` / `PA-02`):
    - Chỉ hỗ trợ `USER` / `POSITION` / `TASK` / `DEPARTMENT` — CẤM TUYỆT ĐỐI `SKILL`.
    - Trên `HIGHLY_RESTRICTED`: chỉ chấp nhận cấp đích danh `USER`.
    - Gắn chặt `bound_dept_membership` / `bound_appointment` để tự động thu hồi khi chuyển Ban / hết nhiệm kỳ (`PA-02`).
    """
    if not can_access_document(actor, document, required_level=AclPermissionLevel.MANAGE):
        raise PermissionDenied("Bạn không có quyền phân quyền ACL cho tài liệu này.")
    if subject_type not in AclSubjectType.values:
        raise GovernanceError(
            "Loại đối tượng ACL không hợp lệ (Hệ thống cấm cấp quyền theo Kỹ năng theo bất biến INV-01 / PA-01)."
        )
    if permission_level not in AclPermissionLevel.values:
        raise GovernanceError("Mức quyền ACL không hợp lệ.")
    if document.classification == DocumentClassification.HIGHLY_RESTRICTED and subject_type != AclSubjectType.USER:
        raise GovernanceError("Tài liệu Tuyệt mật chỉ cho phép cấp quyền đích danh theo từng Thành viên (USER).")
    if expires_at is not None and expires_at <= timezone.now():
        raise GovernanceError("Thời hạn hiệu lực ACL phải nằm ở tương lai.")

    bound_dm = None
    bound_appt = None

    if subject_type == AclSubjectType.USER:
        if target_user is None:
            raise GovernanceError("Vui lòng chọn thành viên nhận quyền.")
        if target_user.is_locked or target_user.account_status == AccountStatus.LOCKED:
            raise GovernanceError("Không thể cấp quyền cho tài khoản đang bị khoá.")
        cm = target_user.club_membership_record
        if cm and cm.status == ClubMembershipStatus.SUSPENDED:
            raise GovernanceError("Không thể cấp quyền cho thành viên đang bị tạm khoá tư cách CLB.")
        if document.department_id:
            bound_dm = DepartmentMembership.objects.filter(
                user=target_user,
                department=document.department,
                status=DeptMembershipStatus.ACTIVE,
            ).first()
            if bound_dm is None:
                # Nếu người nhận đang thuộc Ban khác, gắn với tư cách Ban hiện hữu gần nhất để đảm bảo vòng đời
                bound_dm = DepartmentMembership.objects.filter(
                    user=target_user, status=DeptMembershipStatus.ACTIVE
                ).first()
            bound_appt = Appointment.objects.filter(
                user=target_user,
                department=document.department,
                is_active=True,
                ended_at__isnull=True,
            ).first()
    elif subject_type == AclSubjectType.POSITION:
        if position is None:
            raise GovernanceError("Vui lòng chọn chức vụ nhận quyền.")
        if position.scope_type == ScopeType.DEPARTMENT and position_department is None:
            position_department = document.department
            if position_department is None:
                raise GovernanceError("Chức vụ cấp Ban bắt buộc phải chỉ định Ban cụ thể.")
    elif subject_type == AclSubjectType.TASK:
        if task is None:
            raise GovernanceError("Vui lòng chọn nhiệm vụ liên kết.")
    elif subject_type == AclSubjectType.DEPARTMENT:
        if department is None:
            raise GovernanceError("Vui lòng chọn Ban nhận quyền.")

    entry = DocumentACLEntry.objects.create(
        document=document,
        subject_type=subject_type,
        user=target_user if subject_type == AclSubjectType.USER else None,
        position=position if subject_type == AclSubjectType.POSITION else None,
        position_department=position_department if subject_type == AclSubjectType.POSITION else None,
        task=task if subject_type == AclSubjectType.TASK else None,
        department=department if subject_type == AclSubjectType.DEPARTMENT else None,
        permission_level=permission_level,
        bound_dept_membership=bound_dm,
        bound_appointment=bound_appt,
        reason=(reason or "Cấp quyền truy cập tài liệu theo nhu cầu công việc")[:255],
        expires_at=expires_at,
        granted_by=actor,
    )

    if target_user is not None and target_user.id != actor.id:
        send_operational_alert(
            user=target_user,
            kind=NotificationKind.DOCUMENT_SECURITY,
            title=f"Được cấp quyền tài liệu: {document.title}",
            message=f"Mức quyền: {entry.get_permission_level_display()}. Lý do: {entry.reason}",
            url=f"/workspace/tai-lieu/{document.pk}/",
        )
    record_document_access(
        document=document,
        actor=actor,
        action=DocumentAccessAction.ACL_GRANT,
        request=request,
        reason=f"{subject_type} -> {permission_level}",
    )
    AuditLog.write(actor, "Cấp ACL tài liệu mật", document.code, note=f"{subject_type}: {entry.reason}")
    return entry


@transaction.atomic
def revoke_document_acl(
    *,
    actor: User,
    acl_entry: DocumentACLEntry,
    reason: str = "Thu hồi quyền truy cập tài liệu",
    request=None,
) -> DocumentACLEntry:
    doc = acl_entry.document
    if not can_access_document(actor, doc, required_level=AclPermissionLevel.MANAGE):
        raise PermissionDenied("Bạn không có quyền thu hồi ACL của tài liệu này.")
    if not acl_entry.is_active:
        return acl_entry

    now = timezone.now()
    acl_entry.is_active = False
    acl_entry.revoked_at = now
    acl_entry.revoked_by = actor
    acl_entry.revoked_reason = (reason or "Thu hồi ACL")[:255]
    acl_entry.save(update_fields=["is_active", "revoked_at", "revoked_by", "revoked_reason"])

    record_document_access(
        document=doc,
        actor=actor,
        action=DocumentAccessAction.ACL_REVOKE,
        request=request,
        reason=acl_entry.revoked_reason,
    )
    AuditLog.write(actor, "Thu hồi ACL tài liệu", doc.code, note=acl_entry.revoked_reason)
    return acl_entry


@transaction.atomic
def revoke_bound_document_acls(
    target_user: User,
    *,
    department: Department | None = None,
    appointment: Appointment | None = None,
    actor: User | None = None,
    reason: str = "Tự động thu hồi ACL do biến động nhân sự / nhiệm kỳ (PA-02)",
) -> int:
    """
    Hook tự động thu hồi quyền tài liệu mật (`PA-02`):
    - Khi chuyển Ban (`department` khác None): thu hồi mọi ACL `USER` gắn `bound_dept_membership__department=department`
      hoặc gắn với tài liệu thuộc `department`.
    - Khi kết thúc nhiệm kỳ (`appointment` khác None): thu hồi mọi ACL gắn `bound_appointment=appointment`
      hoặc cấp theo chức vụ cũ tại Ban của quyết định đó.
    - Khi tạm khoá / rời CLB (cả `department` và `appointment` đều None): thu hồi TOÀN BỘ ACL `USER` của thành viên.
    """
    now = timezone.now()
    qs = DocumentACLEntry.objects.select_related("document").filter(
        is_active=True, revoked_at__isnull=True
    )
    if appointment is not None:
        qs = qs.filter(Q(bound_appointment=appointment) | Q(user=target_user, document__department=appointment.department))
    elif department is not None:
        qs = qs.filter(user=target_user).filter(
            Q(bound_dept_membership__department=department) | Q(document__department=department)
        )
    else:
        qs = qs.filter(user=target_user)

    entries = list(qs)
    for entry in entries:
        entry.is_active = False
        entry.revoked_at = now
        entry.revoked_by = actor
        entry.revoked_reason = reason[:255]
        entry.save(update_fields=["is_active", "revoked_at", "revoked_by", "revoked_reason"])
        record_document_access(
            document=entry.document,
            actor=actor,
            action=DocumentAccessAction.ACL_REVOKE,
            reason=f"PA-02 Auto-Revoke ({target_user.public_name}): {reason[:160]}",
        )
    return len(entries)


@transaction.atomic
def break_glass_document_access(
    *,
    actor: User,
    document: ConfidentialDocument,
    reason: str,
    duration_hours: int = 24,
    request=None,
) -> DocumentACLEntry:
    """
    Cơ chế Break-Glass có kiểm soát dành cho **Chủ nhiệm CLB** (hoặc Admin Server):
    - Yêu cầu lý do khẩn cấp rõ ràng (>= 8 ký tự).
    - Cấp tạm ACL đích danh có thời hạn ngắn (mặc định 24h) cho riêng tài liệu này.
    - Ghi nhận đồng thời `DocumentAccessLog(action=BREAK_GLASS)`, `AuditLog` và gửi cảnh báo
      bảo mật tới Trưởng ban & Chủ sở hữu tài liệu!
    """
    if not (
        _has_position_in_club(actor, PositionCode.CHAIRMAN)
        or getattr(actor, "is_server_admin", False)
    ):
        raise PermissionDenied(
            "Chỉ Chủ nhiệm CLB đương nhiệm mới được kích hoạt truy cập khẩn cấp Break-Glass."
        )
    clean_reason = (reason or "").strip()
    if len(clean_reason) < 8:
        raise GovernanceError("Bắt buộc nhập lý do khẩn cấp cụ thể (tối thiểu 8 ký tự) khi mở Break-Glass.")

    expires_at = timezone.now() + timedelta(hours=max(1, min(72, int(duration_hours))))
    entry = DocumentACLEntry.objects.create(
        document=document,
        subject_type=AclSubjectType.USER,
        user=actor,
        permission_level=AclPermissionLevel.DOWNLOAD,
        is_break_glass=True,
        reason=f"[BREAK-GLASS] {clean_reason}"[:255],
        expires_at=expires_at,
        granted_by=actor,
    )
    record_document_access(
        document=document,
        version=document.latest_version,
        actor=actor,
        action=DocumentAccessAction.BREAK_GLASS,
        request=request,
        reason=clean_reason,
    )
    AuditLog.write(
        actor,
        "Mở khoá khẩn cấp Break-Glass tài liệu",
        f"[{document.code}] {document.title}",
        note=clean_reason[:180],
    )

    alert_users: list[User] = []
    if document.owner_id and document.owner_id != actor.id:
        alert_users.append(document.owner)
    if document.department_id:
        head_appts = Appointment.objects.select_related("user").filter(
            department=document.department,
            position__code=PositionCode.DEPT_HEAD,
            is_active=True,
            ended_at__isnull=True,
        )
        for ha in head_appts:
            if ha.user_id != actor.id and ha.user not in alert_users:
                alert_users.append(ha.user)
    for recipient in alert_users:
        send_operational_alert(
            user=recipient,
            kind=NotificationKind.DOCUMENT_SECURITY,
            title=f"Cảnh báo Break-Glass: {document.code}",
            message=f"{actor.public_name} vừa kích hoạt Break-Glass xem tài liệu '{document.title}'. Lý do: {clean_reason[:140]}",
            url=f"/workspace/tai-lieu/{document.pk}/",
            email_category="important",
        )
    return entry


# ---------------------------------------------------------------------------
# 2. QUY TRÌNH ĐỀ XUẤT HOẠT ĐỘNG & CHUYỂN ĐỔI THỰC THI (`WF17`, `WF18`, `DB-07`)
# ---------------------------------------------------------------------------
def _generate_proposal_code() -> str:
    yr = timezone.localdate().year
    base = f"PROP-{yr}"
    for seq in range(DepartmentProposal.objects.filter(code__startswith=base).count() + 1, 99999):
        candidate = f"{base}-{seq:04d}"
        if not DepartmentProposal.objects.filter(code=candidate).exists():
            return candidate
    return f"{base}-{uuid.uuid4().hex[:6].upper()}"


def can_view_proposal(actor: User, proposal: DepartmentProposal) -> bool:
    if not _is_active_club_actor(actor):
        return False
    if getattr(actor, "is_server_admin", False):
        return True
    if _is_pure_advisor(actor):
        # Cố vấn xem đề xuất cấp CLB hoặc đề xuất đã trình BCN / đã duyệt ở chế độ Hard Read-Only
        return (
            proposal.scope == ProposalScope.CLUB
            or proposal.is_escalated_to_bcn
            or proposal.status in (ProposalStatus.APPROVED, ProposalStatus.IN_PROGRESS, ProposalStatus.COMPLETED)
        )
    if proposal.proposer_id == actor.id:
        return True
    if PermissionEngine.authorize(actor, "club.proposal.review_comment") or PermissionEngine.authorize(
        actor, "club.event.approve"
    ) or PermissionEngine.authorize(actor, "club.dept.supervise_ops"):
        return True
    if proposal.department_id in PermissionEngine.get_active_department_ids(actor):
        return True
    if PermissionEngine.authorize(actor, "dept.page.view", department=proposal.department):
        return proposal.status in (ProposalStatus.APPROVED, ProposalStatus.IN_PROGRESS, ProposalStatus.COMPLETED)
    return False


@transaction.atomic
def create_proposal(
    *,
    actor: User,
    department: Department,
    title: str,
    summary: str,
    proposal_type: str = ProposalType.EVENT,
    scope: str = ProposalScope.DEPARTMENT,
    objectives: str = "",
    estimated_budget: Decimal | int | str = 0,
    proposed_start_at=None,
    proposed_location: str = "",
    attachment=None,
    submit_immediately: bool = False,
) -> DepartmentProposal:
    if _is_pure_advisor(actor):
        raise PermissionDenied("Cố vấn ở chế độ Hard Read-Only, không được tạo đề xuất.")
    if not (
        PermissionEngine.authorize(actor, "dept.proposal.create_member", department=department)
        or PermissionEngine.authorize(actor, "dept.proposal.submit_to_bcn", department=department)
        or PermissionEngine.authorize(actor, "club.dept.supervise_ops")
    ):
        PermissionEngine.require(actor, "dept.proposal.create_member", department=department)

    clean_title = (title or "").strip()
    clean_summary = (summary or "").strip()
    if not clean_title or not clean_summary:
        raise GovernanceError("Tiêu đề và nội dung kế hoạch đề xuất không được để trống.")
    if proposal_type not in ProposalType.values:
        proposal_type = ProposalType.OTHER
    if scope not in ProposalScope.values:
        scope = ProposalScope.DEPARTMENT

    saved_file = None
    if attachment is not None:
        prepared = validate_and_prepare_vault_file(attachment)
        saved_file = prepared["content_file"]

    proposal = DepartmentProposal.objects.create(
        code=_generate_proposal_code(),
        title=clean_title[:200],
        proposal_type=proposal_type,
        scope=scope,
        department=department,
        proposer=actor,
        summary=clean_summary,
        objectives=(objectives or "").strip(),
        estimated_budget=Decimal(str(estimated_budget or 0)),
        proposed_start_at=proposed_start_at,
        proposed_location=(proposed_location or "").strip()[:200],
        status=ProposalStatus.SUBMITTED if submit_immediately else ProposalStatus.DRAFT,
        submitted_at=timezone.now() if submit_immediately else None,
        attachment=saved_file,
    )
    if submit_immediately:
        _notify_dept_leads_new_proposal(proposal)
    AuditLog.write(actor, "Tạo đề xuất hoạt động", f"[{proposal.code}] {proposal.title}", note=department.name)
    return proposal


def _notify_dept_leads_new_proposal(proposal: DepartmentProposal) -> None:
    leads = Appointment.objects.select_related("user").filter(
        department=proposal.department,
        position__code__in=[PositionCode.DEPT_HEAD, PositionCode.DEPUTY_HEAD],
        is_active=True,
        ended_at__isnull=True,
    )
    for appt in leads:
        if appt.user_id != proposal.proposer_id:
            send_operational_alert(
                user=appt.user,
                kind=NotificationKind.PROPOSAL_UPDATE,
                title=f"Đề xuất mới tại {proposal.department.name}",
                message=f"[{proposal.code}] {proposal.title} — chờ Ban xem xét.",
                url=f"/workspace/de-xuat/{proposal.pk}/",
            )


@transaction.atomic
def submit_proposal(*, actor: User, proposal: DepartmentProposal) -> DepartmentProposal:
    if _is_pure_advisor(actor):
        raise PermissionDenied("Cố vấn ở chế độ Hard Read-Only, không được gửi đề xuất.")
    is_proposer = proposal.proposer_id == actor.id
    can_manage = PermissionEngine.authorize(
        actor, "dept.proposal.submit_to_bcn", department=proposal.department
    )
    if not (is_proposer or can_manage or getattr(actor, "is_server_admin", False)):
        raise PermissionDenied("Chỉ tác giả hoặc ban điều hành Ban mới được gửi duyệt đề xuất này.")
    if proposal.status not in (ProposalStatus.DRAFT, ProposalStatus.REJECTED):
        raise GovernanceError("Chỉ có thể gửi duyệt đề xuất ở trạng thái Bản nháp hoặc Đang chờ chỉnh sửa.")

    proposal.status = ProposalStatus.SUBMITTED
    proposal.submitted_at = timezone.now()
    proposal.is_escalated_to_bcn = False
    proposal.save(update_fields=["status", "submitted_at", "is_escalated_to_bcn", "updated_at"])
    _notify_dept_leads_new_proposal(proposal)
    AuditLog.write(actor, "Gửi duyệt đề xuất", f"[{proposal.code}] {proposal.title}")
    return proposal


@transaction.atomic
def add_proposal_comment(*, actor: User, proposal: DepartmentProposal, body: str) -> ProposalComment:
    if _is_pure_advisor(actor):
        raise PermissionDenied("Cố vấn ở chế độ Hard Read-Only (`INV-04`), không được gửi bình luận ghi dữ liệu.")
    if not can_view_proposal(actor, proposal):
        raise PermissionDenied("Bạn không có quyền truy cập đề xuất này.")
    clean_body = (body or "").strip()
    if not clean_body:
        raise GovernanceError("Nội dung góp ý không được để trống.")
    comment = ProposalComment.objects.create(proposal=proposal, author=actor, body=clean_body)
    if proposal.proposer_id != actor.id:
        send_operational_alert(
            user=proposal.proposer,
            kind=NotificationKind.PROPOSAL_UPDATE,
            title=f"Góp ý mới cho đề xuất {proposal.code}",
            message=f"{actor.public_name}: {clean_body[:140]}",
            url=f"/workspace/de-xuat/{proposal.pk}/",
        )
    return comment


@transaction.atomic
def review_proposal(
    *,
    actor: User,
    proposal: DepartmentProposal,
    decision: str,
    feedback: str = "",
) -> ProposalReview:
    """
    Thẩm định đề xuất hai cấp (`WF17`, `WF18`, `INV-03`):
    - Cấp Ban (`dept.proposal.submit_to_bcn`): Sơ duyệt, yêu cầu chỉnh sửa, từ chối,
      duyệt đề xuất cấp Ban (`ProposalScope.DEPARTMENT`), hoặc trình lên BCN (`ESCALATE_BCN`).
    - Cấp BCN (`club.event.approve` / `club.dept.supervise_ops`): Duyệt cuối đề xuất `ProposalScope.CLUB`
      hoặc đề xuất đã trình BCN (`UNDER_REVIEW`).
    - Chặn cứng `INV-03`: Tác giả đề xuất không được tự phê duyệt (`APPROVE`) đề xuất của chính mình.
    """
    if _is_pure_advisor(actor):
        raise PermissionDenied("Cố vấn ở chế độ Hard Read-Only (`INV-04`), không được thẩm định đề xuất.")
    if decision not in ProposalReviewDecision.values:
        raise GovernanceError("Quyết định thẩm định không hợp lệ.")
    if proposal.status in (ProposalStatus.APPROVED, ProposalStatus.IN_PROGRESS, ProposalStatus.COMPLETED):
        raise GovernanceError("Đề xuất này đã được phê duyệt hoặc đang triển khai.")
    if proposal.status == ProposalStatus.DRAFT:
        raise GovernanceError("Đề xuất vẫn đang là Bản nháp, tác giả cần gửi duyệt trước.")

    clean_feedback = (feedback or "").strip()
    if decision in (ProposalReviewDecision.REJECT, ProposalReviewDecision.REQUEST_REVISION) and not clean_feedback:
        raise GovernanceError("Bắt buộc nhập lý do / góp ý chỉnh sửa khi từ chối hoặc trả lại đề xuất.")

    if decision == ProposalReviewDecision.APPROVE and actor.id == proposal.proposer_id and not getattr(
        actor, "is_server_admin", False
    ):
        raise PermissionDenied(
            "Vi phạm nguyên tắc phân tách nhiệm vụ (INV-03): Không thể tự phê duyệt đề xuất của chính mình."
        )

    is_bcn_approver = (
        PermissionEngine.authorize(actor, "club.event.approve")
        or PermissionEngine.authorize(actor, "club.dept.supervise_ops")
        or getattr(actor, "is_server_admin", False)
    )
    is_dept_reviewer = PermissionEngine.authorize(
        actor, "dept.proposal.submit_to_bcn", department=proposal.department
    ) or getattr(actor, "is_server_admin", False)

    stage = "BCN" if (proposal.status == ProposalStatus.UNDER_REVIEW or proposal.is_escalated_to_bcn) else "DEPARTMENT"

    if decision == ProposalReviewDecision.ESCALATE_BCN:
        if not (is_dept_reviewer or is_bcn_approver):
            PermissionEngine.require(actor, "dept.proposal.submit_to_bcn", department=proposal.department)
        proposal.status = ProposalStatus.UNDER_REVIEW
        proposal.is_escalated_to_bcn = True
    elif decision == ProposalReviewDecision.APPROVE:
        if proposal.scope == ProposalScope.CLUB or proposal.status == ProposalStatus.UNDER_REVIEW:
            if not is_bcn_approver:
                raise PermissionDenied(
                    "Đề xuất phạm vi Toàn CLB hoặc đã trình BCN chỉ Chủ nhiệm / Phó chủ nhiệm có thẩm quyền mới được phê duyệt."
                )
        else:
            if not (is_dept_reviewer or is_bcn_approver):
                PermissionEngine.require(actor, "dept.proposal.submit_to_bcn", department=proposal.department)
        proposal.status = ProposalStatus.APPROVED
        proposal.approved_by = actor
        proposal.approved_at = timezone.now()
        proposal.decision_note = (clean_feedback or "Đã phê duyệt thực hiện")[:255]
    elif decision in (ProposalReviewDecision.REJECT, ProposalReviewDecision.REQUEST_REVISION):
        if stage == "BCN" and not is_bcn_approver:
            raise PermissionDenied("Đề xuất đang ở cấp BCN thẩm định.")
        if not (is_dept_reviewer or is_bcn_approver):
            PermissionEngine.require(actor, "dept.proposal.submit_to_bcn", department=proposal.department)
        proposal.status = ProposalStatus.REJECTED
        proposal.decision_note = clean_feedback[:255]

    review = ProposalReview.objects.create(
        proposal=proposal,
        reviewer=actor,
        stage=stage,
        decision=decision,
        feedback=clean_feedback or decision,
    )
    proposal.save(
        update_fields=[
            "status",
            "is_escalated_to_bcn",
            "approved_by",
            "approved_at",
            "decision_note",
            "updated_at",
        ]
    )

    if decision == ProposalReviewDecision.ESCALATE_BCN:
        for bcn_appt in Appointment.objects.select_related("user").filter(
            position__code__in=[PositionCode.CHAIRMAN, PositionCode.VICE_CHAIRMAN],
            is_active=True,
            ended_at__isnull=True,
        ):
            if bcn_appt.user_id != actor.id:
                send_operational_alert(
                    user=bcn_appt.user,
                    kind=NotificationKind.PROPOSAL_UPDATE,
                    title=f"Đề xuất chờ BCN duyệt: {proposal.code}",
                    message=f"{proposal.department.name} trình đề xuất '{proposal.title}'.",
                    url=f"/workspace/de-xuat/{proposal.pk}/",
                    email_category="important",
                )
    if proposal.proposer_id != actor.id:
        send_operational_alert(
            user=proposal.proposer,
            kind=NotificationKind.PROPOSAL_UPDATE,
            title=f"Cập nhật đề xuất {proposal.code}: {proposal.get_status_display()}",
            message=(clean_feedback or review.get_decision_display())[:200],
            url=f"/workspace/de-xuat/{proposal.pk}/",
            email_category="important",
        )
    AuditLog.write(
        actor,
        "Thẩm định đề xuất",
        f"[{proposal.code}] -> {review.get_decision_display()}",
        note=clean_feedback[:160],
    )
    return review


@transaction.atomic
def convert_proposal_to_event(
    *,
    actor: User,
    proposal: DepartmentProposal,
    starts_at=None,
    ends_at=None,
    location: str = "",
    capacity: int = 80,
):
    """Chuyển đề xuất `APPROVED` thành Dự thảo Sự kiện Kép (`ClubEventProfile`)."""
    if _is_pure_advisor(actor):
        raise PermissionDenied("Cố vấn ở chế độ Hard Read-Only.")
    if proposal.status != ProposalStatus.APPROVED:
        raise GovernanceError("Chỉ có thể khởi tạo Sự kiện từ Đề xuất đã được Phê duyệt.")
    if proposal.linked_event_id is not None:
        raise GovernanceError("Đề xuất này đã được chuyển đổi thành Sự kiện trước đó.")

    now = timezone.now()
    st = starts_at or proposal.proposed_start_at or (now + timedelta(days=10))
    if st <= now:
        st = now + timedelta(days=7)
    en = ends_at or (st + timedelta(hours=3))
    ev_scope = (
        ClubEventScope.CLUB_WIDE
        if proposal.scope == ProposalScope.CLUB
        else ClubEventScope.DEPT_INTERNAL
    )

    ce = create_club_event(
        actor=actor,
        lead_department=proposal.department,
        name=proposal.title,
        location=location or proposal.proposed_location or "Phòng Studio KMG",
        starts_at=st,
        ends_at=en,
        event_scope=ev_scope,
        capacity=max(10, int(capacity)),
        description=proposal.summary,
        proposal_note=f"Khởi tạo từ Đề xuất {proposal.code}: {proposal.objectives[:200]}",
    )
    proposal.linked_event = ce
    proposal.status = ProposalStatus.IN_PROGRESS
    proposal.save(update_fields=["linked_event", "status", "updated_at"])
    AuditLog.write(actor, "Chuyển đề xuất thành Sự kiện", f"{proposal.code} -> {ce.event.name}")
    return ce


@transaction.atomic
def convert_proposal_to_course(
    *,
    actor: User,
    proposal: DepartmentProposal,
    starts_at=None,
    ends_at=None,
    location: str = "",
    capacity: int = 25,
    instructor: User | None = None,
) -> TrainingCourse:
    """Chuyển đề xuất `APPROVED` thành Khóa Đào tạo (`TrainingCourse`)."""
    if _is_pure_advisor(actor):
        raise PermissionDenied("Cố vấn ở chế độ Hard Read-Only.")
    if proposal.status != ProposalStatus.APPROVED:
        raise GovernanceError("Chỉ có thể khởi tạo Khóa đào tạo từ Đề xuất đã được Phê duyệt.")
    if proposal.linked_course_id is not None:
        raise GovernanceError("Đề xuất này đã được chuyển đổi thành Khóa đào tạo trước đó.")

    now = timezone.now()
    st = starts_at or proposal.proposed_start_at or (now + timedelta(days=5))
    if st <= now:
        st = now + timedelta(days=5)
    en = ends_at or (st + timedelta(hours=2))

    course = create_training_course(
        actor=actor,
        department=proposal.department,
        title=proposal.title,
        description=proposal.summary,
        location=location or proposal.proposed_location or "Phòng Tập KMG",
        starts_at=st,
        ends_at=en,
        capacity=max(5, int(capacity)),
        instructor=instructor or proposal.proposer,
    )
    proposal.linked_course = course
    proposal.status = ProposalStatus.IN_PROGRESS
    proposal.save(update_fields=["linked_course", "status", "updated_at"])
    AuditLog.write(actor, "Chuyển đề xuất thành Khóa đào tạo", f"{proposal.code} -> {course.title}")
    return course


# ---------------------------------------------------------------------------
# 3. ĐÀO TẠO CHUYÊN MÔN, LỊCH TẬP BAND (`BE-04`) & NHẮC LỊCH CHỦ ĐỘNG (`DB-06`)
# ---------------------------------------------------------------------------
@transaction.atomic
def create_training_course(
    *,
    actor: User,
    department: Department,
    title: str,
    location: str,
    starts_at,
    ends_at,
    description: str = "",
    custom_category: str = "",
    target_skill: Skill | None = None,
    instructor: User | None = None,
    capacity: int = 25,
    status: str = TrainingCourseStatus.OPEN,
) -> TrainingCourse:
    if _is_pure_advisor(actor):
        raise PermissionDenied("Cố vấn ở chế độ Hard Read-Only.")
    if not (
        PermissionEngine.authorize(actor, "dept.training.manage", department=department)
        or PermissionEngine.authorize(actor, "club.dept.supervise_ops")
    ):
        PermissionEngine.require(actor, "dept.training.manage", department=department)

    clean_title = (title or "").strip()
    if not clean_title:
        raise GovernanceError("Tên khóa đào tạo không được để trống.")
    if ends_at <= starts_at:
        raise GovernanceError("Thời gian kết thúc khóa đào tạo phải sau thời gian bắt đầu.")

    course = TrainingCourse.objects.create(
        department=department,
        title=clean_title[:200],
        description=(description or "").strip(),
        custom_category=(custom_category or "").strip()[:80],
        target_skill=target_skill,
        instructor=instructor or actor,
        location=(location or "Phòng Studio KMG").strip()[:200],
        starts_at=starts_at,
        ends_at=ends_at,
        capacity=max(1, int(capacity)),
        status=status if status in TrainingCourseStatus.values else TrainingCourseStatus.OPEN,
        created_by=actor,
    )
    AuditLog.write(actor, "Tạo khóa đào tạo chuyên môn", course.title, note=department.name)
    return course


@transaction.atomic
def enroll_in_training(
    *,
    actor: User,
    course: TrainingCourse,
    target_user: User | None = None,
) -> TrainingEnrollment:
    """Thành viên CLB đăng ký khóa đào tạo (chống race condition sĩ số, tự đưa vào Waitlist nếu đầy)."""
    if not _is_active_club_actor(actor) or _is_pure_advisor(actor):
        raise PermissionDenied("Chỉ thành viên chính thức CLB mới được đăng ký tham gia đào tạo.")
    recipient = target_user or actor
    if recipient.id != actor.id:
        if not (
            PermissionEngine.authorize(actor, "dept.training.manage", department=course.department)
            or PermissionEngine.authorize(actor, "club.dept.supervise_ops")
        ):
            PermissionEngine.require(actor, "dept.training.manage", department=course.department)

    locked_course = TrainingCourse.objects.select_for_update().get(pk=course.pk)
    if locked_course.status not in (TrainingCourseStatus.OPEN, TrainingCourseStatus.ONGOING):
        raise GovernanceError("Khóa đào tạo này hiện không mở đăng ký.")

    existing = TrainingEnrollment.objects.filter(course=locked_course, user=recipient).first()
    if existing and existing.status in (
        TrainingEnrollmentStatus.ENROLLED,
        TrainingEnrollmentStatus.COMPLETED,
    ):
        return existing

    current_count = locked_course.enrollments.filter(
        status__in=[TrainingEnrollmentStatus.ENROLLED, TrainingEnrollmentStatus.COMPLETED]
    ).count()
    next_status = (
        TrainingEnrollmentStatus.WAITLIST
        if current_count >= locked_course.capacity
        else TrainingEnrollmentStatus.ENROLLED
    )
    enrollment, _ = TrainingEnrollment.objects.update_or_create(
        course=locked_course,
        user=recipient,
        defaults={"status": next_status},
    )
    send_operational_alert(
        user=recipient,
        kind=NotificationKind.TRAINING_REMINDER,
        title=f"Ghi danh đào tạo: {locked_course.title}",
        message=f"Trạng thái: {enrollment.get_status_display()} · {locked_course.location}",
        url="/workspace/dao-tao/",
    )
    return enrollment


@transaction.atomic
def update_training_enrollment_status(
    *,
    actor: User,
    enrollment: TrainingEnrollment,
    new_status: str,
    attendance_count: int | None = None,
    completion_note: str = "",
) -> TrainingEnrollment:
    if new_status not in TrainingEnrollmentStatus.values:
        raise GovernanceError("Trạng thái ghi danh không hợp lệ.")
    is_self_drop = actor.id == enrollment.user_id and new_status == TrainingEnrollmentStatus.DROPPED
    if not is_self_drop:
        if _is_pure_advisor(actor):
            raise PermissionDenied("Cố vấn ở chế độ Hard Read-Only.")
        if not (
            PermissionEngine.authorize(actor, "dept.training.manage", department=enrollment.course.department)
            or PermissionEngine.authorize(actor, "club.dept.supervise_ops")
        ):
            PermissionEngine.require(actor, "dept.training.manage", department=enrollment.course.department)

    enrollment.status = new_status
    if attendance_count is not None:
        enrollment.attendance_count = max(0, int(attendance_count))
    if completion_note:
        enrollment.completion_note = completion_note.strip()[:255]
    if new_status == TrainingEnrollmentStatus.COMPLETED and enrollment.completed_at is None:
        enrollment.completed_at = timezone.now()
    enrollment.save()
    return enrollment


@transaction.atomic
def create_practice_session(
    *,
    actor: User,
    department: Department,
    title: str,
    location: str,
    starts_at,
    ends_at,
    repertoire_note: str = "",
    club_event=None,
    lead_coordinator: User | None = None,
    participants_specs: list[tuple[User, str, Skill | None]] | None = None,
) -> PracticeSession:
    """Lên lịch tập Band / Rehearsal (`BE-04`) gắn vai trò nhạc cụ & gửi thông báo thành viên."""
    if _is_pure_advisor(actor):
        raise PermissionDenied("Cố vấn ở chế độ Hard Read-Only.")
    if not (
        PermissionEngine.authorize(actor, "dept.training.manage", department=department)
        or PermissionEngine.authorize(actor, "dept.event.manage_internal", department=department)
        or PermissionEngine.authorize(actor, "club.dept.supervise_ops")
    ):
        PermissionEngine.require(actor, "dept.training.manage", department=department)

    clean_title = (title or "").strip()
    if not clean_title:
        raise GovernanceError("Tên buổi tập luyện không được để trống.")
    if ends_at <= starts_at:
        raise GovernanceError("Thời gian kết thúc buổi tập phải sau thời gian bắt đầu.")

    session = PracticeSession.objects.create(
        department=department,
        club_event=club_event,
        title=clean_title[:200],
        repertoire_note=(repertoire_note or "").strip(),
        location=(location or "Phòng Studio B204").strip()[:200],
        starts_at=starts_at,
        ends_at=ends_at,
        lead_coordinator=lead_coordinator or actor,
        created_by=actor,
    )

    if participants_specs:
        seen_ids = set()
        for user_obj, role_label, skill_obj in participants_specs:
            if user_obj.id in seen_ids:
                continue
            seen_ids.add(user_obj.id)
            PracticeParticipant.objects.create(
                session=session,
                user=user_obj,
                assigned_role=(role_label or "Thành viên biểu diễn")[:80],
                skill=skill_obj,
                response_status=PracticeResponseStatus.INVITED,
            )
            send_operational_alert(
                user=user_obj,
                kind=NotificationKind.PRACTICE_REMINDER,
                title=f"Lịch tập mới: {session.title}",
                message=(
                    f"Vai trò: {role_label or 'Thành viên'} · "
                    f"{timezone.localtime(session.starts_at):%H:%M %d/%m/%Y} tại {session.location}"
                ),
                url="/workspace/dao-tao/",
                email_category="training_practice",
            )

    AuditLog.write(actor, "Lên lịch tập luyện Band", session.title, note=department.name)
    return session


@transaction.atomic
def update_practice_participant_status(
    *,
    actor: User,
    participant: PracticeParticipant,
    new_status: str,
    note: str = "",
) -> PracticeParticipant:
    if new_status not in PracticeResponseStatus.values:
        raise GovernanceError("Trạng thái phản hồi buổi tập không hợp lệ.")
    if _is_pure_advisor(actor):
        raise PermissionDenied("Cố vấn ở chế độ Hard Read-Only.")

    is_self_rsvp = actor.id == participant.user_id and new_status in (
        PracticeResponseStatus.CONFIRMED,
        PracticeResponseStatus.EXCUSED,
    )
    if not is_self_rsvp:
        dept = participant.session.department
        if not (
            PermissionEngine.authorize(actor, "dept.training.manage", department=dept)
            or PermissionEngine.authorize(actor, "club.dept.supervise_ops")
            or participant.session.lead_coordinator_id == actor.id
        ):
            PermissionEngine.require(actor, "dept.training.manage", department=dept)

    participant.response_status = new_status
    if note:
        participant.note = note.strip()[:255]
    participant.save(update_fields=["response_status", "note", "updated_at"])
    return participant


def dispatch_training_and_practice_reminders(ref_now=None) -> dict:
    """
    Nhắc lịch đào tạo & lịch tập Band idempotent (`T_48H`, `T_12H`) sử dụng chung sổ cái
    `ScheduledReminder` của nền tảng (`Chỉ thị 3.5` & `DB-06`).
    """
    now = ref_now or timezone.now()
    training_sent = 0
    practice_sent = 0

    # 1. Nhắc lịch Khóa đào tạo
    upcoming_courses = list(
        TrainingCourse.objects.select_related("department", "instructor")
        .prefetch_related("enrollments__user")
        .filter(
            status__in=[TrainingCourseStatus.OPEN, TrainingCourseStatus.ONGOING],
            starts_at__gt=now,
        )
    )
    for course in upcoming_courses:
        delta = course.starts_at - now
        stage = None
        if delta <= timedelta(hours=12):
            stage = ReminderStage.T_12H
        elif delta <= timedelta(hours=48):
            stage = ReminderStage.T_48H
        if stage is None:
            continue
        recipients = [
            e.user
            for e in course.enrollments.all()
            if e.status == TrainingEnrollmentStatus.ENROLLED
        ]
        if course.instructor_id and all(u.id != course.instructor_id for u in recipients):
            recipients.append(course.instructor)
        for u in recipients:
            if dispatch_idempotent_reminder(
                target_type=ReminderTargetType.TRAINING_SESSION,
                target_id=course.id,
                recipient=u,
                stage=stage,
                kind=NotificationKind.TRAINING_REMINDER,
                title=f"Nhắc lịch đào tạo: {course.title}",
                message=(
                    f"{course.department.name} · Bắt đầu lúc "
                    f"{timezone.localtime(course.starts_at):%H:%M %d/%m/%Y} tại {course.location}"
                ),
                url="/workspace/dao-tao/",
                email_category="training_practice",
            ):
                training_sent += 1

    # 2. Nhắc lịch Tập luyện Band / Rehearsal
    upcoming_sessions = list(
        PracticeSession.objects.select_related("department", "lead_coordinator")
        .prefetch_related("participants__user")
        .filter(
            status=PracticeSessionStatus.SCHEDULED,
            starts_at__gt=now,
        )
    )
    for sess in upcoming_sessions:
        delta = sess.starts_at - now
        stage = None
        if delta <= timedelta(hours=12):
            stage = ReminderStage.T_12H
        elif delta <= timedelta(hours=48):
            stage = ReminderStage.T_48H
        if stage is None:
            continue
        for part in sess.participants.all():
            if part.response_status in (
                PracticeResponseStatus.EXCUSED,
                PracticeResponseStatus.ABSENT,
            ):
                continue
            if dispatch_idempotent_reminder(
                target_type=ReminderTargetType.PRACTICE_SESSION,
                target_id=sess.id,
                recipient=part.user,
                stage=stage,
                kind=NotificationKind.PRACTICE_REMINDER,
                title=f"Nhắc lịch tập Band: {sess.title}",
                message=(
                    f"Vai trò: {part.assigned_role} · "
                    f"{timezone.localtime(sess.starts_at):%H:%M %d/%m/%Y} tại {sess.location}"
                ),
                url="/workspace/dao-tao/",
                email_category="training_practice",
            ):
                practice_sent += 1

    return {
        "training_reminders_sent": training_sent,
        "practice_reminders_sent": practice_sent,
    }


@transaction.atomic
def create_department_showcase_item(
    *,
    actor: User,
    department: Department,
    category_label: str,
    title: str,
    summary: str,
    item_type: str = ShowcaseItemType.SOP_GUIDE,
    external_url: str = "",
    linked_document: ConfidentialDocument | None = None,
    is_pinned: bool = False,
) -> DepartmentShowcaseItem:
    """Thêm nội dung chuyên môn / Portfolio / Danh mục thiết bị vào Cổng Ban chuyên biệt."""
    if _is_pure_advisor(actor):
        raise PermissionDenied("Cố vấn ở chế độ Hard Read-Only.")
    if not (
        PermissionEngine.authorize(actor, "dept.event.manage_internal", department=department)
        or PermissionEngine.authorize(actor, "dept.training.manage", department=department)
        or PermissionEngine.authorize(actor, "dept.document.manage", department=department)
        or PermissionEngine.authorize(actor, "club.dept.supervise_ops")
    ):
        PermissionEngine.require(actor, "dept.event.manage_internal", department=department)

    clean_title = (title or "").strip()
    clean_summary = (summary or "").strip()
    if not clean_title or not clean_summary:
        raise GovernanceError("Tiêu đề và mô tả mục chuyên môn không được để trống.")
    safe_url = clean_evidence_url(external_url)

    return DepartmentShowcaseItem.objects.create(
        department=department,
        category_label=(category_label or "Chuyên môn Ban").strip()[:80],
        item_type=item_type if item_type in ShowcaseItemType.values else ShowcaseItemType.SOP_GUIDE,
        title=clean_title[:200],
        summary=clean_summary,
        external_url=safe_url,
        linked_document=linked_document,
        is_pinned=is_pinned,
        created_by=actor,
    )
