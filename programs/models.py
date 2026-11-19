"""
Mô hình dữ liệu Phase 3: Department Management (`programs`):
1. Kho Tài liệu Mật & Phân quyền Tài nguyên (`DocumentCategory`, `ConfidentialDocument`,
   `DocumentVersion`, `DocumentACLEntry`, `DocumentAccessLog` bất biến).
   - Tuân thủ `SEC-01` (`PrivateVaultStorage` ngoài `/media/`).
   - Tuân thủ `INV-01` & `PA-01` (`Skill != Permission` — không có SubjectType=SKILL trong ACL).
2. Quy trình Đề xuất Hoạt động & Sáng kiến (`DepartmentProposal`, `ProposalReview` bất biến, `ProposalComment`).
3. Đào tạo & Lịch tập Band (`TrainingCourse`, `TrainingEnrollment`, `PracticeSession`, `PracticeParticipant`).
4. Nội dung Chuyên môn / Showcase theo từng Ban (`DepartmentShowcaseItem`).
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.storage import private_vault_storage
from organization.models import (
    Appointment,
    Department,
    DepartmentMembership,
    DeptMembershipStatus,
    Position,
    Skill,
)


# ---------------------------------------------------------------------------
# 1. KHO TÀI LIỆU MẬT & PHÂN QUYỀN TÀI NGUYÊN (`WF20`, `INV-01`, `PA-01`, `PA-02`, `SEC-01`)
# ---------------------------------------------------------------------------
class DocumentClassification(models.TextChoices):
    PUBLIC = "PUBLIC", "Công khai nội bộ CLB"
    CLUB_INTERNAL = "CLUB_INTERNAL", "Nội bộ Toàn CLB"
    DEPT_INTERNAL = "DEPT_INTERNAL", "Nội bộ Ban"
    RESTRICTED = "RESTRICTED", "Tài liệu mật theo danh sách ACL"
    HIGHLY_RESTRICTED = "HIGHLY_RESTRICTED", "Tuyệt mật (Trưởng ban / Đích danh)"


class AclSubjectType(models.TextChoices):
    """Chỉ hỗ trợ USER / POSITION / TASK / DEPARTMENT — TUYỆT ĐỐI KHÔNG CÓ SKILL (`PA-01`)."""

    USER = "USER", "Thành viên đích danh"
    POSITION = "POSITION", "Chức vụ cụ thể"
    TASK = "TASK", "Thành viên đang thực hiện Nhiệm vụ"
    DEPARTMENT = "DEPARTMENT", "Thành viên đang sinh hoạt tại Ban"


class AclPermissionLevel(models.TextChoices):
    VIEW = "VIEW", "Chỉ xem thông tin"
    DOWNLOAD = "DOWNLOAD", "Xem & tải tệp"
    MANAGE = "MANAGE", "Quản lý phiên bản & ACL"


class DocumentAccessAction(models.TextChoices):
    VIEW = "VIEW", "Xem chi tiết tài liệu"
    DOWNLOAD = "DOWNLOAD", "Tải tệp tài liệu"
    DENIED_ATTEMPT = "DENIED_ATTEMPT", "Truy cập bị từ chối (403)"
    BREAK_GLASS = "BREAK_GLASS", "Truy cập khẩn cấp Break-Glass (Chủ nhiệm)"
    ACL_GRANT = "ACL_GRANT", "Cấp quyền truy cập ACL"
    ACL_REVOKE = "ACL_REVOKE", "Thu hồi quyền ACL"
    VERSION_UPLOAD = "VERSION_UPLOAD", "Tải lên phiên bản tài liệu"


class DocumentCategory(models.Model):
    """Danh mục phân loại tài liệu (hỗ trợ mở rộng theo từng Ban)."""

    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="document_categories",
        verbose_name="Ban chủ quản",
    )
    code = models.CharField("Mã danh mục", max_length=40, unique=True)
    name = models.CharField("Tên danh mục", max_length=120)
    description = models.CharField("Mô tả", max_length=255, blank=True)
    display_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Danh mục Tài liệu"
        verbose_name_plural = "Danh mục Tài liệu"
        ordering = ["display_order", "name"]

    def __str__(self):
        return f"{self.name} ({self.department.name})" if self.department_id else self.name


class ConfidentialDocument(models.Model):
    """Hồ sơ tài liệu trong Kho Tài liệu Bảo mật KMG."""

    code = models.CharField("Mã tài liệu", max_length=48, unique=True)
    title = models.CharField("Tiêu đề tài liệu", max_length=200)
    description = models.TextField("Mô tả tóm tắt", blank=True)
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="confidential_documents",
        verbose_name="Ban sở hữu",
    )
    category = models.ForeignKey(
        DocumentCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
        verbose_name="Danh mục tài liệu",
    )
    custom_category_label = models.CharField(
        "Phân loại tuỳ biến theo Ban", max_length=80, blank=True
    )
    classification = models.CharField(
        "Mức độ bảo mật",
        max_length=24,
        choices=DocumentClassification.choices,
        default=DocumentClassification.DEPT_INTERNAL,
        db_index=True,
    )
    recommended_skills = models.ManyToManyField(
        Skill,
        blank=True,
        related_name="recommended_documents",
        verbose_name="Kỹ năng gợi ý (chỉ dùng lọc UX, KHÔNG cấp quyền INV-01)",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="owned_documents",
        verbose_name="Người khởi tạo / Chủ sở hữu",
    )
    is_archived = models.BooleanField("Đã lưu trữ", default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Tài liệu Bảo mật"
        verbose_name_plural = "Kho Tài liệu Bảo mật"
        ordering = ["-updated_at", "-id"]
        indexes = [
            models.Index(
                fields=["department", "classification", "is_archived"],
                name="idx_doc_dept_cls_arch",
            ),
        ]

    @property
    def latest_version(self):
        return (
            self.versions.filter(is_current=True)
            .order_by("-version_number", "-id")
            .first()
            or self.versions.order_by("-version_number", "-id").first()
        )

    def __str__(self):
        return f"[{self.code}] {self.title} ({self.get_classification_display()})"


class DocumentVersion(models.Model):
    """Phiên bản tệp vật lý lưu trong `PrivateVaultStorage` kèm mã băm SHA-256 (`SEC-01`)."""

    document = models.ForeignKey(
        ConfidentialDocument,
        on_delete=models.CASCADE,
        related_name="versions",
        verbose_name="Tài liệu",
    )
    version_number = models.PositiveIntegerField("Phiên bản số", default=1)
    file = models.FileField(
        "Tệp trong Kho Mật",
        storage=private_vault_storage,
        upload_to="vault_docs/%Y/%m/",
    )
    original_filename = models.CharField("Tên tệp gốc", max_length=255)
    content_type = models.CharField(
        "Kiểu MIME", max_length=120, default="application/octet-stream"
    )
    file_size = models.PositiveBigIntegerField("Dung lượng (bytes)", default=0)
    checksum_sha256 = models.CharField("Mã băm SHA-256", max_length=64)
    change_note = models.CharField("Ghi chú phiên bản", max_length=255, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="uploaded_doc_versions",
        verbose_name="Người tải lên",
    )
    is_current = models.BooleanField("Là bản mới nhất", default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Phiên bản Tài liệu"
        verbose_name_plural = "Các Phiên bản Tài liệu"
        ordering = ["-version_number", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "version_number"],
                name="uniq_doc_version_num",
            ),
        ]

    def __str__(self):
        return f"{self.document.code} v{self.version_number} ({self.original_filename})"


class DocumentACLEntry(models.Model):
    """
    Danh sách kiểm soát truy cập chi tiết theo từng tài nguyên (`Resource-level ACL`).
    Gắn vòng đời (`bound_dept_membership`, `bound_appointment`) để tự động thu hồi khi
    chuyển Ban / hết nhiệm kỳ / tạm khoá (`PA-02`).
    """

    document = models.ForeignKey(
        ConfidentialDocument,
        on_delete=models.CASCADE,
        related_name="acl_entries",
        verbose_name="Tài liệu",
    )
    subject_type = models.CharField(
        "Loại đối tượng được cấp quyền",
        max_length=16,
        choices=AclSubjectType.choices,
        db_index=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="document_acl_entries",
        verbose_name="Thành viên được cấp",
    )
    position = models.ForeignKey(
        Position,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="document_acl_entries",
        verbose_name="Chức vụ được cấp",
    )
    position_department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Ban của chức vụ",
    )
    task = models.ForeignKey(
        "operations.ClubTask",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="document_acl_entries",
        verbose_name="Nhiệm vụ liên kết",
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="document_acl_entries",
        verbose_name="Ban được cấp",
    )
    permission_level = models.CharField(
        "Mức quyền",
        max_length=12,
        choices=AclPermissionLevel.choices,
        default=AclPermissionLevel.DOWNLOAD,
    )
    is_break_glass = models.BooleanField(
        "Cấp quyền khẩn cấp Break-Glass", default=False
    )
    bound_dept_membership = models.ForeignKey(
        DepartmentMembership,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bound_document_acls",
        verbose_name="Gắn tư cách Ban (PA-02)",
    )
    bound_appointment = models.ForeignKey(
        Appointment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bound_document_acls",
        verbose_name="Gắn quyết định bổ nhiệm (PA-02)",
    )
    reason = models.CharField("Lý do cấp quyền", max_length=255, blank=True)
    expires_at = models.DateTimeField("Hết hạn lúc", null=True, blank=True)
    is_active = models.BooleanField("Đang hiệu lực", default=True, db_index=True)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
        verbose_name="Người cấp quyền",
    )
    revoked_at = models.DateTimeField("Thu hồi lúc", null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Người thu hồi",
    )
    revoked_reason = models.CharField("Lý do thu hồi", max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Mục Phân quyền Tài liệu (ACL)"
        verbose_name_plural = "Danh sách Phân quyền Tài liệu (ACL)"
        ordering = ["-is_active", "-created_at"]

    @property
    def is_currently_effective(self) -> bool:
        now = timezone.now()
        if not self.is_active or self.revoked_at is not None:
            return False
        if self.expires_at is not None and self.expires_at <= now:
            return False
        if self.bound_dept_membership_id is not None:
            if self.bound_dept_membership.status != DeptMembershipStatus.ACTIVE:
                return False
        if self.bound_appointment_id is not None:
            if not self.bound_appointment.is_currently_effective:
                return False
        return True

    def __str__(self):
        return f"ACL {self.document.code} [{self.subject_type}] -> {self.permission_level}"


class DocumentAccessLog(models.Model):
    """Sổ cái kiểm toán truy cập tài liệu mật (Bất biến — Append-only Ledger)."""

    document = models.ForeignKey(
        ConfidentialDocument,
        on_delete=models.CASCADE,
        related_name="access_logs",
        verbose_name="Tài liệu",
    )
    version = models.ForeignKey(
        DocumentVersion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="access_logs",
        verbose_name="Phiên bản",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="document_access_logs",
        verbose_name="Người thao tác",
    )
    action = models.CharField(
        "Hành động",
        max_length=20,
        choices=DocumentAccessAction.choices,
        db_index=True,
    )
    ip_address = models.GenericIPAddressField("Địa chỉ IP", null=True, blank=True)
    user_agent = models.CharField("Thiết bị / Trình duyệt", max_length=255, blank=True)
    reason = models.CharField("Lý do / Ghi chú", max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Nhật ký Truy cập Tài liệu"
        verbose_name_plural = "Nhật ký Truy cập Tài liệu"
        ordering = ["-created_at", "-id"]

    def save(self, *args, **kwargs):
        if not self._state.adding and self.pk is not None:
            raise ValueError("Nhật ký truy cập tài liệu là dữ liệu bất biến, không được sửa.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Nhật ký truy cập tài liệu là dữ liệu bất biến, không được xoá.")

    def __str__(self):
        who = self.actor.public_name if self.actor_id else "Ẩn danh"
        return f"[{self.created_at:%d/%m %H:%M}] {who} -> {self.action} ({self.document.code})"


# ---------------------------------------------------------------------------
# 2. QUY TRÌNH ĐỀ XUẤT HOẠT ĐỘNG & CHUYỂN ĐỔI THỰC THI (`WF17`, `WF18`, `DB-07`)
# ---------------------------------------------------------------------------
class ProposalType(models.TextChoices):
    EVENT = "EVENT", "Tổ chức Sự kiện / Show diễn"
    TRAINING = "TRAINING", "Khóa / Buổi Đào tạo Chuyên môn"
    PURCHASE_EQUIPMENT = "PURCHASE_EQUIPMENT", "Mua sắm / Nâng cấp Thiết bị"
    MEDIA_CAMPAIGN = "MEDIA_CAMPAIGN", "Chiến dịch Truyền thông"
    PROCESS_IMPROVEMENT = "PROCESS_IMPROVEMENT", "Cải tiến Quy trình Ban"
    OTHER = "OTHER", "Đề xuất khác"


class ProposalScope(models.TextChoices):
    DEPARTMENT = "DEPARTMENT", "Phạm vi Cấp Ban"
    CLUB = "CLUB", "Phạm vi Toàn CLB (Cần BCN duyệt)"


class ProposalStatus(models.TextChoices):
    DRAFT = "DRAFT", "Bản nháp"
    SUBMITTED = "SUBMITTED", "Chờ Ban xem xét"
    UNDER_REVIEW = "UNDER_REVIEW", "Đang thẩm định (Đã trình BCN)"
    APPROVED = "APPROVED", "Đã phê duyệt"
    REJECTED = "REJECTED", "Không duyệt / Cần sửa"
    IN_PROGRESS = "IN_PROGRESS", "Đang triển khai thực tế"
    COMPLETED = "COMPLETED", "Đã hoàn thành"


class ProposalReviewDecision(models.TextChoices):
    ESCALATE_BCN = "ESCALATE_BCN", "Thông qua Ban & Trình BCN duyệt"
    REQUEST_REVISION = "REQUEST_REVISION", "Yêu cầu chỉnh sửa lại"
    APPROVE = "APPROVE", "Phê duyệt chính thức"
    REJECT = "REJECT", "Từ chối đề xuất"


class DepartmentProposal(models.Model):
    """Đề xuất hoạt động/sáng kiến từ thành viên & Ban hướng tới triển khai Sự kiện/Đào tạo."""

    code = models.CharField("Mã đề xuất", max_length=32, unique=True)
    title = models.CharField("Tên đề xuất", max_length=200)
    proposal_type = models.CharField(
        "Loại đề xuất",
        max_length=24,
        choices=ProposalType.choices,
        default=ProposalType.EVENT,
    )
    scope = models.CharField(
        "Phạm vi ảnh hưởng",
        max_length=16,
        choices=ProposalScope.choices,
        default=ProposalScope.DEPARTMENT,
        db_index=True,
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="proposals",
        verbose_name="Ban chủ quản đề xuất",
    )
    proposer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="department_proposals",
        verbose_name="Người đề xuất",
    )
    summary = models.TextField("Nội dung & Kế hoạch chi tiết")
    objectives = models.TextField("Mục tiêu & Kết quả kỳ vọng", blank=True)
    estimated_budget = models.DecimalField(
        "Dự trù kinh phí (VNĐ)", max_digits=12, decimal_places=0, default=0
    )
    proposed_start_at = models.DateTimeField("Thời gian dự kiến", null=True, blank=True)
    proposed_location = models.CharField("Địa điểm dự kiến", max_length=200, blank=True)
    status = models.CharField(
        "Trạng thái vòng đời",
        max_length=16,
        choices=ProposalStatus.choices,
        default=ProposalStatus.DRAFT,
        db_index=True,
    )
    is_escalated_to_bcn = models.BooleanField("Đã trình lên Ban Chủ nhiệm", default=False)
    attachment = models.FileField(
        "Tệp kế hoạch đính kèm",
        storage=private_vault_storage,
        upload_to="vault_proposals/%Y/%m/",
        null=True,
        blank=True,
    )
    linked_event = models.OneToOneField(
        "operations.ClubEventProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_proposal",
        verbose_name="Sự kiện được khởi tạo",
    )
    linked_course = models.OneToOneField(
        "TrainingCourse",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_proposal",
        verbose_name="Khóa đào tạo được khởi tạo",
    )
    submitted_at = models.DateTimeField("Gửi duyệt lúc", null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_proposals",
        verbose_name="Người ra quyết định cuối",
    )
    approved_at = models.DateTimeField("Phê duyệt lúc", null=True, blank=True)
    decision_note = models.CharField("Kết luận phê duyệt", max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Đề xuất Hoạt động & Sáng kiến"
        verbose_name_plural = "Đề xuất Hoạt động & Sáng kiến"
        ordering = ["-updated_at", "-id"]

    def __str__(self):
        return f"[{self.code}] {self.title} ({self.get_status_display()})"


class ProposalReview(models.Model):
    """Biên bản thẩm định đề xuất bất biến (`WF17`)."""

    proposal = models.ForeignKey(
        DepartmentProposal,
        on_delete=models.CASCADE,
        related_name="reviews",
        verbose_name="Đề xuất",
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="proposal_reviews",
        verbose_name="Người thẩm định",
    )
    stage = models.CharField("Cấp thẩm định", max_length=16, default="DEPARTMENT")
    decision = models.CharField(
        "Quyết định",
        max_length=20,
        choices=ProposalReviewDecision.choices,
    )
    feedback = models.TextField("Nhận xét & Phản hồi")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Biên bản Thẩm định Đề xuất"
        verbose_name_plural = "Biên bản Thẩm định Đề xuất"
        ordering = ["-created_at", "-id"]

    def save(self, *args, **kwargs):
        if not self._state.adding and self.pk is not None:
            raise ValueError("Biên bản thẩm định đề xuất là dữ liệu bất biến, không được sửa.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Biên bản thẩm định đề xuất là dữ liệu bất biến, không được xoá.")

    def __str__(self):
        return f"{self.proposal.code} - {self.get_decision_display()} ({self.reviewer.public_name})"


class ProposalComment(models.Model):
    """Thảo luận đóng góp ý kiến trên đề xuất (Cố vấn Hard Read-Only bị chặn)."""

    proposal = models.ForeignKey(
        DepartmentProposal,
        on_delete=models.CASCADE,
        related_name="comments",
        verbose_name="Đề xuất",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="proposal_comments",
        verbose_name="Người bình luận",
    )
    body = models.TextField("Nội dung góp ý")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Góp ý Đề xuất"
        verbose_name_plural = "Góp ý Đề xuất"
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.author.public_name} @ {self.proposal.code}"


# ---------------------------------------------------------------------------
# 3. ĐÀO TẠO CHUYÊN MÔN & LỊCH TẬP BAND (`WF18`, `BE-04`, `DB-05`, Chỉ thị 3.5)
# ---------------------------------------------------------------------------
class TrainingCourseStatus(models.TextChoices):
    DRAFT = "DRAFT", "Đang chuẩn bị"
    OPEN = "OPEN", "Đang mở đăng ký"
    ONGOING = "ONGOING", "Đang diễn ra"
    COMPLETED = "COMPLETED", "Đã kết thúc"
    CANCELLED = "CANCELLED", "Đã huỷ"


class TrainingEnrollmentStatus(models.TextChoices):
    ENROLLED = "ENROLLED", "Đã đăng ký tham gia"
    WAITLIST = "WAITLIST", "Danh sách chờ"
    COMPLETED = "COMPLETED", "Đã hoàn thành khóa học"
    DROPPED = "DROPPED", "Đã rút / Ngưng tham gia"


class TrainingCourse(models.Model):
    """Khóa / Buổi Đào tạo Chuyên môn tại Ban (Thanh nhạc, Nhạc cụ, FOH, Media)."""

    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="training_courses",
        verbose_name="Ban tổ chức",
    )
    title = models.CharField("Tên khóa / buổi đào tạo", max_length=200)
    description = models.TextField("Nội dung giáo trình & Mục tiêu", blank=True)
    custom_category = models.CharField("Chuyên đề / Phân loại Ban", max_length=80, blank=True)
    target_skill = models.ForeignKey(
        Skill,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="training_courses",
        verbose_name="Kỹ năng mục tiêu (chỉ gợi ý UX)",
    )
    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="instructed_courses",
        verbose_name="Giảng viên / Người hướng dẫn",
    )
    location = models.CharField("Phòng tập / Địa điểm", max_length=200)
    starts_at = models.DateTimeField("Thời gian bắt đầu")
    ends_at = models.DateTimeField("Thời gian kết thúc")
    capacity = models.PositiveIntegerField("Sĩ số tối đa", default=25)
    status = models.CharField(
        "Trạng thái",
        max_length=16,
        choices=TrainingCourseStatus.choices,
        default=TrainingCourseStatus.OPEN,
        db_index=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_training_courses",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Khóa Đào tạo Chuyên môn"
        verbose_name_plural = "Các Khóa Đào tạo Chuyên môn"
        ordering = ["starts_at", "-id"]

    @property
    def active_enrollments_count(self) -> int:
        return self.enrollments.filter(
            status__in=[TrainingEnrollmentStatus.ENROLLED, TrainingEnrollmentStatus.COMPLETED]
        ).count()

    @property
    def is_full(self) -> bool:
        return self.active_enrollments_count >= self.capacity

    def __str__(self):
        return f"{self.title} ({self.department.name})"


class TrainingEnrollment(models.Model):
    """Ghi danh tham gia Khóa đào tạo (có danh sách chờ khi đủ sĩ số)."""

    course = models.ForeignKey(
        TrainingCourse,
        on_delete=models.CASCADE,
        related_name="enrollments",
        verbose_name="Khóa đào tạo",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="training_enrollments",
        verbose_name="Học viên",
    )
    status = models.CharField(
        "Trạng thái",
        max_length=16,
        choices=TrainingEnrollmentStatus.choices,
        default=TrainingEnrollmentStatus.ENROLLED,
        db_index=True,
    )
    attendance_count = models.PositiveSmallIntegerField("Số buổi có mặt", default=0)
    completion_note = models.CharField("Nhận xét hoàn thành", max_length=255, blank=True)
    enrolled_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Học viên Khóa Đào tạo"
        verbose_name_plural = "Danh sách Học viên Đào tạo"
        ordering = ["enrolled_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["course", "user"],
                name="uniq_training_enroll_course_user",
            ),
        ]

    def __str__(self):
        return f"{self.user.public_name} @ {self.course.title} ({self.get_status_display()})"


class PracticeSessionStatus(models.TextChoices):
    SCHEDULED = "SCHEDULED", "Đã lên lịch tập"
    ONGOING = "ONGOING", "Đang tập luyện"
    COMPLETED = "COMPLETED", "Đã hoàn thành buổi tập"
    CANCELLED = "CANCELLED", "Đã huỷ buổi tập"


class PracticeResponseStatus(models.TextChoices):
    INVITED = "INVITED", "Chờ xác nhận lịch tập"
    CONFIRMED = "CONFIRMED", "Xác nhận tham gia tập"
    EXCUSED = "EXCUSED", "Xin phép vắng buổi tập"
    ATTENDED = "ATTENDED", "Đã có mặt tập luyện"
    ABSENT = "ABSENT", "Vắng mặt"


class PracticeSession(models.Model):
    """Lịch tập luyện Band / Ghép tiết mục (`BE-04` tách rời khỏi `Event` sự kiện chính thức)."""

    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="practice_sessions",
        verbose_name="Ban tổ chức",
    )
    club_event = models.ForeignKey(
        "operations.ClubEventProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="practice_sessions",
        verbose_name="Chuẩn bị cho Sự kiện (tuỳ chọn)",
    )
    title = models.CharField("Tên buổi tập luyện / Rehearsal", max_length=200)
    repertoire_note = models.TextField("Danh sách bài tập & Tempo / Phân đoạn", blank=True)
    location = models.CharField("Phòng tập / Studio", max_length=200)
    starts_at = models.DateTimeField("Bắt đầu tập")
    ends_at = models.DateTimeField("Kết thúc tập")
    lead_coordinator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="led_practice_sessions",
        verbose_name="Band Leader / Điều phối buổi tập",
    )
    status = models.CharField(
        "Trạng thái buổi tập",
        max_length=16,
        choices=PracticeSessionStatus.choices,
        default=PracticeSessionStatus.SCHEDULED,
        db_index=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_practice_sessions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Buổi Tập luyện / Rehearsal"
        verbose_name_plural = "Lịch Tập luyện Band"
        ordering = ["starts_at", "-id"]

    def __str__(self):
        return f"{self.title} ({self.department.name})"


class PracticeParticipant(models.Model):
    """Nhân sự & vai trò nhạc cụ tham gia buổi tập Band (`BE-04`)."""

    session = models.ForeignKey(
        PracticeSession,
        on_delete=models.CASCADE,
        related_name="participants",
        verbose_name="Buổi tập",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="practice_participations",
        verbose_name="Thành viên",
    )
    assigned_role = models.CharField(
        "Vai trò / Nhạc cụ phụ trách", max_length=80, default="Thành viên biểu diễn"
    )
    skill = models.ForeignKey(
        Skill,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Kỹ năng liên quan",
    )
    response_status = models.CharField(
        "Phản hồi & Điểm danh",
        max_length=16,
        choices=PracticeResponseStatus.choices,
        default=PracticeResponseStatus.INVITED,
        db_index=True,
    )
    note = models.CharField("Ghi chú", max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Nhân sự Buổi tập"
        verbose_name_plural = "Nhân sự Buổi tập"
        ordering = ["assigned_role", "user__full_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "user"],
                name="uniq_practice_part_sess_user",
            ),
        ]

    def __str__(self):
        return f"{self.user.public_name} [{self.assigned_role}] @ {self.session.title}"


# ---------------------------------------------------------------------------
# 4. NỘI DUNG CHUYÊN MÔN & SHOWCASE THEO TỪNG BAN (TRUYỀN THÔNG / CHUYÊN MÔN / KỸ THUẬT DEMO)
# ---------------------------------------------------------------------------
class ShowcaseItemType(models.TextChoices):
    MEDIA_PORTFOLIO = "MEDIA_PORTFOLIO", "Portfolio & Ấn phẩm Truyền thông"
    REPERTOIRE = "REPERTOIRE", "Kho Bài tập & Dàn dựng Chuyên môn"
    EQUIPMENT_SPEC = "EQUIPMENT_SPEC", "Danh mục Thiết bị & Kỹ thuật Sân khấu"
    SOP_GUIDE = "SOP_GUIDE", "Hướng dẫn Vận hành Ban"


class DepartmentShowcaseItem(models.Model):
    """Bảng nội dung chuyên biệt theo danh mục động (`Department.custom_categories`) của từng Ban."""

    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="showcase_items",
        verbose_name="Ban chủ quản",
    )
    category_label = models.CharField("Danh mục chuyên biệt của Ban", max_length=80)
    item_type = models.CharField(
        "Loại nội dung",
        max_length=20,
        choices=ShowcaseItemType.choices,
        default=ShowcaseItemType.SOP_GUIDE,
    )
    title = models.CharField("Tiêu đề mục", max_length=200)
    summary = models.TextField("Mô tả / Thông số kỹ thuật / Kịch bản")
    external_url = models.URLField("Liên kết tham khảo / Drive / Recap", blank=True)
    linked_document = models.ForeignKey(
        ConfidentialDocument,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="showcase_refs",
        verbose_name="Tài liệu liên kết trong Kho (nếu có)",
    )
    is_pinned = models.BooleanField("Ghim nổi bật ở Cổng Ban", default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Mục Chuyên môn / Showcase Ban"
        verbose_name_plural = "Các Mục Chuyên môn / Showcase Ban"
        ordering = ["-is_pinned", "-created_at", "-id"]

    def __str__(self):
        return f"[{self.department.name}] {self.title}"
