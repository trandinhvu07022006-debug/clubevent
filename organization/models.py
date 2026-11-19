"""
Mô hình dữ liệu Nền tảng Tổ chức & Phân quyền Đa chiều (Phase 1 — Core Foundation).

Thiết kế tối ưu cho MySQL 8.4 (`InnoDB`, `utf8mb4_0900_ai_ci`) & tương thích SQLite:
- Đa tư cách thành viên theo Ban (`DepartmentMembership` M-N).
- Đơn nhiệm đang hiệu lực ở tầng CSDL (`Appointment.singleton_active_key` UNIQUE NULL).
- Lịch sử thành viên 8+ chặng bất biến (`MemberLifecycleEvent` chặn sửa/xóa).
- Hồ sơ kỹ năng có xác minh (`UserSkill`), tách bạch tuyệt đối `Skill != Permission` (`INV-01`).
- Ủy quyền theo Gói năng lực cho Phó ban & Mảng phụ trách cho Phó chủ nhiệm (`PermissionGrant`).
- Phân quyền tài nguyên độc lập (`ResourceAccessRule`) và Chính sách có phiên bản (`PolicyVersion`).
"""
from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Department(models.Model):
    """Một Ban chuyên môn/chức năng trực thuộc CLB KMG."""

    code = models.CharField("Mã Ban", max_length=32, unique=True)
    name = models.CharField("Tên Ban", max_length=120)
    slug = models.SlugField("Slug đường dẫn", max_length=80, unique=True)
    short_description = models.CharField("Mô tả ngắn", max_length=255, blank=True)
    description = models.TextField("Giới thiệu chi tiết", blank=True)
    icon = models.CharField("Biểu tượng Bootstrap", max_length=60, default="bi-music-note-list")
    is_demo = models.BooleanField(
        "Đang giai đoạn Demo",
        default=False,
        help_text="Ví dụ: Ban Kỹ thuật đang vận hành thử nghiệm.",
    )
    is_active = models.BooleanField("Đang hoạt động", default=True)
    custom_categories = models.JSONField(
        "Danh mục tuỳ biến theo Ban",
        default=list,
        blank=True,
        help_text="Cho phép mỗi Ban mở rộng phân loại hoạt động/tài liệu mà không cần sửa code.",
    )
    display_order = models.PositiveSmallIntegerField("Thứ tự hiển thị", default=0)
    created_at = models.DateTimeField("Tạo lúc", auto_now_add=True)

    class Meta:
        verbose_name = "Ban trực thuộc"
        verbose_name_plural = "Các Ban trực thuộc"
        ordering = ["display_order", "name"]

    def __str__(self):
        suffix = " (Demo)" if self.is_demo else ""
        return f"{self.name}{suffix}"


class ClubMembershipStatus(models.TextChoices):
    PENDING = "PENDING", "Chờ xét duyệt"
    ACTIVE = "ACTIVE", "Thành viên chính thức"
    SUSPENDED = "SUSPENDED", "Đang tạm khoá"
    ALUMNI = "ALUMNI", "Cựu thành viên"
    LEFT = "LEFT", "Đã rời CLB"


class ClubMembership(models.Model):
    """Tư cách thành viên cấp CLB (độc lập với trạng thái tài khoản kỹ thuật `AccountStatus`)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="club_membership",
        verbose_name="Thành viên",
    )
    member_code = models.CharField("Mã thành viên (Member ID)", max_length=24, unique=True)
    status = models.CharField(
        "Trạng thái tại CLB",
        max_length=16,
        choices=ClubMembershipStatus.choices,
        default=ClubMembershipStatus.ACTIVE,
        db_index=True,
    )
    joined_at = models.DateField("Ngày gia nhập", default=timezone.localdate)
    left_at = models.DateField("Ngày rời CLB", null=True, blank=True)
    suspended_until = models.DateTimeField("Tạm khoá đến", null=True, blank=True)
    suspended_reason = models.CharField("Lý do tạm khoá", max_length=255, blank=True)
    is_featured = models.BooleanField("Thành viên tiêu biểu (Trang chủ)", default=False)
    featured_title = models.CharField("Danh hiệu vinh danh", max_length=120, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Người duyệt gia nhập",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Hồ sơ Thành viên CLB"
        verbose_name_plural = "Hồ sơ Thành viên CLB"
        ordering = ["member_code"]

    def __str__(self):
        return f"{self.member_code} - {self.user.public_name} ({self.get_status_display()})"


class DeptMembershipStatus(models.TextChoices):
    PENDING = "PENDING", "Chờ tiếp nhận"
    ACTIVE = "ACTIVE", "Đang sinh hoạt"
    SUSPENDED = "SUSPENDED", "Tạm ngưng tại Ban"
    TRANSFERRED = "TRANSFERRED", "Đã chuyển Ban"
    LEFT = "LEFT", "Đã rời Ban"


class DepartmentMembership(models.Model):
    """Quan hệ M-N: Một thành viên có thể thuộc đồng thời một hoặc nhiều Ban."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="department_memberships",
        verbose_name="Thành viên",
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="memberships",
        verbose_name="Ban",
    )
    status = models.CharField(
        "Trạng thái trong Ban",
        max_length=16,
        choices=DeptMembershipStatus.choices,
        default=DeptMembershipStatus.ACTIVE,
        db_index=True,
    )
    joined_at = models.DateField("Ngày vào Ban", default=timezone.localdate)
    left_at = models.DateField("Ngày rời Ban", null=True, blank=True)
    note = models.CharField("Ghi chú", max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Thành viên thuộc Ban"
        verbose_name_plural = "Thành viên thuộc Ban"
        ordering = ["department__display_order", "user__full_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "department"],
                name="uniq_dept_membership_user_dept",
            ),
        ]

    def __str__(self):
        return f"{self.user.public_name} @ {self.department.name} ({self.get_status_display()})"


class ApplicationStatus(models.TextChoices):
    SUBMITTED = "SUBMITTED", "Mới nộp đơn"
    DEPT_SCREENED = "DEPT_SCREENED", "Ban đã sơ duyệt"
    APPROVED = "APPROVED", "Đã duyệt vào CLB"
    REJECTED = "REJECTED", "Từ chối"


class MembershipApplication(models.Model):
    """Đơn đăng ký gia nhập CLB từ tài khoản Guest (`WF01`)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="membership_applications",
        verbose_name="Ứng viên",
    )
    primary_department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="primary_applications",
        verbose_name="Ban nguyện vọng 1",
    )
    secondary_department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="secondary_applications",
        verbose_name="Ban nguyện vọng 2 (tuỳ chọn)",
    )
    declared_skills_text = models.CharField(
        "Năng khiếu / Kỹ năng tự giới thiệu",
        max_length=255,
        blank=True,
    )
    motivation = models.TextField("Lý do & mong muốn gia nhập KMG", max_length=1500)
    portfolio_url = models.URLField("Link Demo / Video / Portfolio", blank=True)
    status = models.CharField(
        "Trạng thái xét duyệt",
        max_length=16,
        choices=ApplicationStatus.choices,
        default=ApplicationStatus.SUBMITTED,
        db_index=True,
    )
    screening_note = models.CharField("Nhận xét sơ duyệt của Ban", max_length=255, blank=True)
    screened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    screened_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField("Phản hồi quyết định cuối", max_length=255, blank=True)
    created_at = models.DateTimeField("Nộp lúc", auto_now_add=True)

    class Meta:
        verbose_name = "Đơn ứng tuyển CLB"
        verbose_name_plural = "Đơn ứng tuyển CLB"
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"Đơn {self.user.public_name} -> {self.primary_department.name} ({self.get_status_display()})"


class PositionCode(models.TextChoices):
    CHAIRMAN = "CHAIRMAN", "Chủ nhiệm CLB"
    VICE_CHAIRMAN = "VICE_CHAIRMAN", "Phó chủ nhiệm CLB"
    ADVISOR = "ADVISOR", "Cố vấn CLB"
    DEPT_HEAD = "DEPT_HEAD", "Trưởng ban"
    DEPUTY_HEAD = "DEPUTY_HEAD", "Phó ban"
    CORE_MEMBER = "CORE_MEMBER", "Thành viên nòng cốt"


class ScopeType(models.TextChoices):
    CLUB = "CLUB", "Toàn CLB"
    DEPARTMENT = "DEPARTMENT", "Cấp Ban"
    EVENT = "EVENT", "Theo Sự kiện"


class Position(models.Model):
    """Danh mục chức vụ chính thức trong cơ cấu KMG."""

    code = models.CharField(
        "Mã chức vụ",
        max_length=32,
        choices=PositionCode.choices,
        unique=True,
    )
    name = models.CharField("Tên chức vụ", max_length=80)
    scope_type = models.CharField("Cấp phạm vi chuẩn", max_length=16, choices=ScopeType.choices)
    is_officer = models.BooleanField("Là cán bộ điều hành", default=True)
    is_singleton = models.BooleanField(
        "Đơn nhiệm trong phạm vi",
        default=False,
        help_text="True đối với Chủ nhiệm (1 người/CLB) và Trưởng ban (1 người/Ban).",
    )
    is_read_only = models.BooleanField(
        "Chế độ Giám sát Read-Only",
        default=False,
        help_text="True đối với Cố vấn (INV-04).",
    )
    rank_order = models.PositiveSmallIntegerField("Thứ bậc hiển thị", default=10)

    class Meta:
        verbose_name = "Danh mục Chức vụ"
        verbose_name_plural = "Danh mục Chức vụ"
        ordering = ["rank_order", "id"]

    def __str__(self):
        return self.name


class Appointment(models.Model):
    """
    Quyết định bổ nhiệm chức vụ gắn với phạm vi & nhiệm kỳ cụ thể.

    - Lưu toàn bộ lịch sử nhiệm kỳ (không bao giờ xóa khi kết thúc nhiệm kỳ).
    - `singleton_active_key` (`UNIQUE NULL`) đảm bảo ở tầng MySQL 8.4 rằng không bao giờ
      tồn tại 2 Chủ nhiệm đang đương nhiệm hoặc 2 Trưởng ban cùng một Ban, trong khi
      các bản ghi đã miễn nhiệm (`ended_at IS NOT NULL`) có `singleton_active_key = NULL`.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="appointments",
        verbose_name="Cán bộ được bổ nhiệm",
    )
    position = models.ForeignKey(
        Position,
        on_delete=models.PROTECT,
        related_name="appointments",
        verbose_name="Chức vụ",
    )
    scope_type = models.CharField("Phạm vi", max_length=16, choices=ScopeType.choices)
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="appointments",
        verbose_name="Ban phụ trách",
    )
    event = models.ForeignKey(
        "events.Event",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="appointments",
        verbose_name="Sự kiện phụ trách",
    )
    title_note = models.CharField("Ghi chú chức danh / mảng", max_length=120, blank=True)
    term_label = models.CharField("Nhiệm kỳ", max_length=40, default="2026-2027")
    started_at = models.DateTimeField("Hiệu lực từ", default=timezone.now)
    ends_at = models.DateTimeField("Dự kiến kết thúc", null=True, blank=True)
    ended_at = models.DateTimeField("Kết thúc thực tế", null=True, blank=True)
    ended_reason = models.CharField("Lý do kết thúc", max_length=255, blank=True)
    is_active = models.BooleanField("Đang đương nhiệm", default=True, db_index=True)
    singleton_active_key = models.CharField(
        "Khoá đơn nhiệm đương nhiệm",
        max_length=120,
        unique=True,
        null=True,
        blank=True,
        editable=False,
    )
    appointed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Người bổ nhiệm",
    )
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Người miễn nhiệm",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Quyết định Bổ nhiệm"
        verbose_name_plural = "Quyết định Bổ nhiệm"
        ordering = ["-is_active", "position__rank_order", "-started_at"]
        indexes = [
            models.Index(fields=["user", "is_active", "ended_at"]),
            models.Index(fields=["department", "is_active"]),
        ]

    @property
    def is_currently_effective(self) -> bool:
        now = timezone.now()
        if not self.is_active or self.ended_at is not None:
            return False
        if self.ends_at is not None and self.ends_at <= now:
            return False
        return True

    def _compute_singleton_key(self) -> str | None:
        if (
            self.is_active
            and self.ended_at is None
            and (self.ends_at is None or self.ends_at > timezone.now())
            and self.position_id
            and self.position.is_singleton
        ):
            dept_part = self.department_id or 0
            event_part = self.event_id or 0
            return f"{self.scope_type}:{dept_part}:{event_part}:{self.position.code}"
        return None

    def clean(self):
        if self.scope_type == ScopeType.DEPARTMENT and not self.department_id:
            raise ValidationError("Chức vụ cấp Ban bắt buộc phải chỉ định Ban trực thuộc.")
        if self.scope_type == ScopeType.CLUB and self.department_id:
            raise ValidationError("Chức vụ cấp Toàn CLB không gắn cố định vào một Ban lẻ.")
        if self.ends_at and self.started_at and self.ends_at <= self.started_at:
            raise ValidationError("Thời điểm kết thúc nhiệm kỳ phải sau thời điểm bắt đầu.")

    def save(self, *args, **kwargs):
        if self.ended_at is not None:
            self.is_active = False
        self.singleton_active_key = self._compute_singleton_key()
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            update_set = set(update_fields)
            update_set.add("singleton_active_key")
            update_set.add("is_active")
            kwargs["update_fields"] = list(update_set)
        super().save(*args, **kwargs)

    def __str__(self):
        scope_label = self.department.name if self.department_id else "Toàn CLB"
        state = "Đương nhiệm" if self.is_currently_effective else "Đã kết thúc"
        return f"{self.user.public_name} - {self.position.name} ({scope_label}) [{state}]"


class LifecycleEventType(models.TextChoices):
    """Đầy đủ các chặng vòng đời thành viên theo Chỉ thị 3.2."""

    REGISTERED = "REGISTERED", "Đăng ký tài khoản"
    APPROVED_CLUB = "APPROVED_CLUB", "Được duyệt vào CLB"
    JOINED_DEPT = "JOINED_DEPT", "Gia nhập Ban"
    APPOINTED = "APPOINTED", "Được bổ nhiệm chức vụ"
    ROLE_ENDED = "ROLE_ENDED", "Kết thúc nhiệm kỳ / Miễn nhiệm"
    DELEGATION_GRANTED = "DELEGATION_GRANTED", "Được cấp quyền ủy quyền"
    DELEGATION_REVOKED = "DELEGATION_REVOKED", "Thu hồi quyền ủy quyền"
    TRANSFERRED_DEPT = "TRANSFERRED_DEPT", "Chuyển Ban"
    DEPT_LEFT = "DEPT_LEFT", "Rời Ban"
    SUSPENDED = "SUSPENDED", "Bị tạm khoá tư cách thành viên"
    RESTORED = "RESTORED", "Được khôi phục tư cách thành viên"
    LEFT_CLUB = "LEFT_CLUB", "Rời CLB / Chuyển Cựu thành viên"


class MemberLifecycleEvent(models.Model):
    """
    Sổ cái bất biến (Append-only Ledger) lưu toàn bộ lịch sử thành viên (Chỉ thị 3.2).

    Tuyệt đối không cho phép sửa hoặc xóa bản ghi đã ghi vào CSDL.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="lifecycle_events",
        verbose_name="Thành viên",
    )
    event_type = models.CharField(
        "Loại sự kiện vòng đời",
        max_length=24,
        choices=LifecycleEventType.choices,
        db_index=True,
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Ban liên quan",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Người ra quyết định",
    )
    title = models.CharField("Tiêu đề mốc lịch sử", max_length=200)
    note = models.CharField("Chi tiết / Lý do", max_length=255, blank=True)
    metadata = models.JSONField("Dữ liệu đối chiếu", default=dict, blank=True)
    created_at = models.DateTimeField("Thời điểm ghi nhận", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Lịch sử Vòng đời Thành viên"
        verbose_name_plural = "Lịch sử Vòng đời Thành viên"
        ordering = ["-created_at", "-id"]

    def save(self, *args, **kwargs):
        if not self._state.adding and self.pk is not None:
            raise ValueError("Lịch sử thành viên là dữ liệu bất biến, không được phép chỉnh sửa.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Lịch sử thành viên là dữ liệu bất biến, không được phép xoá.")

    def __str__(self):
        return f"[{self.created_at:%d/%m/%Y}] {self.user.public_name}: {self.title}"


class SkillCategory(models.Model):
    """Nhóm kỹ năng nghệ thuật / chuyên môn / kỹ thuật / truyền thông."""

    code = models.CharField("Mã nhóm", max_length=32, unique=True)
    name = models.CharField("Tên nhóm kỹ năng", max_length=80)
    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="skill_categories",
        verbose_name="Ban chủ quản gợi ý",
    )
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "Nhóm Kỹ năng"
        verbose_name_plural = "Nhóm Kỹ năng"
        ordering = ["display_order", "name"]

    def __str__(self):
        return self.name


class Skill(models.Model):
    """Một kỹ năng cụ thể (Guitar, Vocal, Piano, Drums, Sound Mixing, Media Design...)."""

    category = models.ForeignKey(
        SkillCategory,
        on_delete=models.CASCADE,
        related_name="skills",
        verbose_name="Nhóm kỹ năng",
    )
    code = models.CharField("Mã kỹ năng", max_length=40, unique=True)
    name = models.CharField("Tên kỹ năng", max_length=80)
    description = models.CharField("Mô tả", max_length=200, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Kỹ năng"
        verbose_name_plural = "Danh mục Kỹ năng"
        ordering = ["category__display_order", "name"]

    def __str__(self):
        return f"{self.name} ({self.category.name})"


class SkillProficiency(models.TextChoices):
    BEGINNER = "BEGINNER", "Cơ bản"
    INTERMEDIATE = "INTERMEDIATE", "Khá / Biểu diễn nhóm"
    ADVANCED = "ADVANCED", "Thành thạo / Solo"
    MASTER = "MASTER", "Nòng cốt / Hướng dẫn"


class SkillVerificationStatus(models.TextChoices):
    SELF_DECLARED = "SELF_DECLARED", "Tự khai báo (Chờ xác minh)"
    VERIFIED = "VERIFIED", "Đã xác minh chuyên môn"
    REJECTED = "REJECTED", "Chưa đạt xác minh"


class UserSkill(models.Model):
    """
    Hồ sơ kỹ năng của từng thành viên.

    BẤT BIẾN BẢO MẬT `INV-01`: `UserSkill` chỉ dùng cho hồ sơ năng lực, lọc và gợi ý
    nhân sự/nội dung. `PermissionEngine` TUYỆT ĐỐI KHÔNG đọc `UserSkill` để cấp quyền!
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="user_skills",
        verbose_name="Thành viên",
    )
    skill = models.ForeignKey(
        Skill,
        on_delete=models.CASCADE,
        related_name="holders",
        verbose_name="Kỹ năng",
    )
    proficiency = models.CharField(
        "Mức độ thành thạo",
        max_length=16,
        choices=SkillProficiency.choices,
        default=SkillProficiency.BEGINNER,
    )
    verification_status = models.CharField(
        "Trạng thái xác minh",
        max_length=16,
        choices=SkillVerificationStatus.choices,
        default=SkillVerificationStatus.SELF_DECLARED,
        db_index=True,
    )
    experience_note = models.CharField("Kinh nghiệm / Nhạc cụ sở hữu", max_length=255, blank=True)
    evidence_url = models.URLField("Link Video / Bản thu minh chứng", blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Người xác minh",
    )
    verified_at = models.DateTimeField("Xác minh lúc", null=True, blank=True)
    review_note = models.CharField("Nhận xét chuyên môn", max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Kỹ năng Thành viên"
        verbose_name_plural = "Kỹ năng Thành viên"
        ordering = ["-verification_status", "skill__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "skill"],
                name="uniq_user_skill_pair",
            ),
        ]

    def __str__(self):
        return f"{self.user.public_name} - {self.skill.name} ({self.get_verification_status_display()})"


class Permission(models.Model):
    """Mã quyền nguyên tử theo Ma trận Phân quyền Chuẩn `D04 v1.1`."""

    code = models.CharField("Mã quyền", max_length=64, unique=True)
    name = models.CharField("Tên quyền", max_length=140)
    module = models.CharField("Phân hệ", max_length=40, db_index=True)
    scope_type = models.CharField("Phạm vi áp dụng", max_length=16, choices=ScopeType.choices)
    is_mutation = models.BooleanField(
        "Là quyền thay đổi dữ liệu / phê duyệt",
        default=True,
        help_text="True đối với mọi thao tác ghi/duyệt/xóa để chặn cứng Cố vấn (INV-04).",
    )

    class Meta:
        verbose_name = "Mã Quyền hệ thống"
        verbose_name_plural = "Danh mục Quyền hệ thống"
        ordering = ["module", "code"]

    def __str__(self):
        return f"{self.code} — {self.name}"


class PositionPermission(models.Model):
    """Quyền mặc định gắn với từng chức vụ (`Position`)."""

    position = models.ForeignKey(
        Position,
        on_delete=models.CASCADE,
        related_name="position_permissions",
    )
    permission = models.ForeignKey(
        Permission,
        on_delete=models.CASCADE,
        related_name="position_bindings",
    )

    class Meta:
        verbose_name = "Quyền mặc định theo Chức vụ"
        verbose_name_plural = "Quyền mặc định theo Chức vụ"
        constraints = [
            models.UniqueConstraint(
                fields=["position", "permission"],
                name="uniq_position_permission",
            ),
        ]


class GrantBundleCode(models.TextChoices):
    """
    Các gói ủy quyền chuẩn theo Ma trận Phân quyền `v1.1` (Chỉ thị 3.1):
    - 4 Gói năng lực cho Phó ban (`BUNDLE_*`) do Trưởng ban / Chủ nhiệm cấp.
    - 4 Mảng phụ trách cho Phó chủ nhiệm (`PORTFOLIO_*`) do Chủ nhiệm cấp.
    - `CUSTOM`: Gói chọn từng quyền nguyên tử lẻ (vẫn bị chặn bởi Hard Ceiling).
    """

    # Gói ủy quyền cấp Ban dành cho Phó ban
    BUNDLE_TASK_OPS = "BUNDLE_TASK_OPS", "Phó ban — Gói Điều phối Công việc Ban"
    BUNDLE_TRAINING_CONTENT = (
        "BUNDLE_TRAINING_CONTENT",
        "Phó ban — Gói Đào tạo & Xác minh Kỹ năng",
    )
    BUNDLE_HR_SCREENING = "BUNDLE_HR_SCREENING", "Phó ban — Gói Sơ duyệt Nhân sự & Đánh giá"
    BUNDLE_RESOURCE_PROPOSAL = (
        "BUNDLE_RESOURCE_PROPOSAL",
        "Phó ban — Gói Tài liệu, Sự kiện Ban & Đề xuất BCN",
    )

    # Mảng phụ trách cấp CLB dành cho Phó chủ nhiệm
    PORTFOLIO_OPS = "PORTFOLIO_OPS", "Phó CN — Mảng Vận hành chung các Ban"
    PORTFOLIO_HR = "PORTFOLIO_HR", "Phó CN — Mảng Nhân sự & Tổ chức"
    PORTFOLIO_EVENT = "PORTFOLIO_EVENT", "Phó CN — Mảng Sự kiện & Truyền thông công khai"
    PORTFOLIO_FINANCE_DOC = (
        "PORTFOLIO_FINANCE_DOC",
        "Phó CN — Mảng Tài chính & Tài liệu điều hành",
    )

    CUSTOM = "CUSTOM", "Ủy quyền tuỳ chỉnh (chọn quyền lẻ)"


class PermissionGrant(models.Model):
    """
    Bản ghi ủy quyền động / tạm thời gắn với nhiệm kỳ (`bound_appointment`) và thời hạn.

    Tuân thủ `INV-02`: khi `bound_appointment` kết thúc hoặc quá `expires_at`,
    gói quyền tự động hết hiệu lực ngay lập tức.
    """

    grantee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="permission_grants",
        verbose_name="Người nhận ủy quyền",
    )
    bound_appointment = models.ForeignKey(
        Appointment,
        on_delete=models.CASCADE,
        related_name="permission_grants",
        verbose_name="Gắn với quyết định bổ nhiệm",
    )
    bundle_code = models.CharField(
        "Gói ủy quyền / Mảng phụ trách",
        max_length=40,
        choices=GrantBundleCode.choices,
    )
    scope_type = models.CharField("Phạm vi", max_length=16, choices=ScopeType.choices)
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="permission_grants",
        verbose_name="Phạm vi Ban",
    )
    custom_permissions = models.ManyToManyField(
        Permission,
        blank=True,
        related_name="custom_grants",
        verbose_name="Quyền lẻ bổ sung",
    )
    reason = models.CharField("Lý do / Văn bản phân công", max_length=255)
    starts_at = models.DateTimeField("Hiệu lực từ", default=timezone.now)
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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ủy quyền Chức năng"
        verbose_name_plural = "Ủy quyền Chức năng"
        ordering = ["-is_active", "-created_at"]

    @property
    def is_currently_effective(self) -> bool:
        now = timezone.now()
        if not self.is_active or self.revoked_at is not None:
            return False
        if self.starts_at and self.starts_at > now:
            return False
        if self.expires_at and self.expires_at <= now:
            return False
        if not self.bound_appointment.is_currently_effective:
            return False
        return True

    def __str__(self):
        scope = self.department.name if self.department_id else "Toàn CLB"
        return f"{self.grantee.public_name} <- {self.get_bundle_code_display()} ({scope})"


class ResourceClassification(models.TextChoices):
    """4 mức độ bảo mật tài nguyên / tài liệu theo Chỉ thị 3.4."""

    PUBLIC_CLUB = "PUBLIC_CLUB", "Chung toàn CLB (mọi thành viên ACTIVE)"
    DEPARTMENT_INTERNAL = "DEPARTMENT_INTERNAL", "Nội bộ Ban (chỉ thành viên ACTIVE của Ban)"
    RESTRICTED_ACL = "RESTRICTED_ACL", "Tài liệu mật theo danh sách cấp quyền (ACL)"
    EXECUTIVE_CONFIDENTIAL = "EXECUTIVE_CONFIDENTIAL", "Mật Ban Chủ nhiệm"


class ResourceAccessRule(models.Model):
    """
    Danh sách kiểm soát truy cập cấp từng tài nguyên (Resource-level ACL — Chỉ thị 3.4).

    Chứng minh thực thi `Skill != Permission`: có kỹ năng `Guitar` KHÔNG tự động mở khóa
    tài liệu `RESTRICTED_ACL`; ngược lại thành viên chưa có kỹ năng `Guitar` nhưng được
    Trưởng ban cấp vào `allowed_users` thì ĐƯỢC phép truy cập.
    """

    resource_type = models.CharField("Loại tài nguyên", max_length=40, default="DOCUMENT")
    resource_code = models.CharField("Mã định danh tài nguyên", max_length=80, unique=True)
    title = models.CharField("Tên tài nguyên", max_length=200)
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="resource_rules",
        verbose_name="Ban sở hữu",
    )
    classification = models.CharField(
        "Mức phân loại bảo mật",
        max_length=28,
        choices=ResourceClassification.choices,
        default=ResourceClassification.DEPARTMENT_INTERNAL,
    )
    recommended_skill = models.ForeignKey(
        Skill,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Kỹ năng gợi ý (chỉ dùng để lọc, KHÔNG cấp quyền)",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    allowed_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="accessible_resources",
        verbose_name="Thành viên được cấp quyền đích danh",
    )
    allowed_positions = models.ManyToManyField(
        Position,
        blank=True,
        related_name="accessible_resources",
        verbose_name="Chức vụ được phép truy cập",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Quy tắc ACL Tài nguyên"
        verbose_name_plural = "Quy tắc ACL Tài nguyên"

    def __str__(self):
        return f"{self.title} [{self.get_classification_display()}]"


class PolicyVersion(models.Model):
    """Cấu hình chính sách vận hành CLB có đánh phiên bản (Quyết định A3 & Ngưỡng kỷ luật)."""

    policy_key = models.CharField("Mã chính sách", max_length=64, db_index=True)
    version_number = models.PositiveIntegerField("Phiên bản", default=1)
    title = models.CharField("Tên chính sách", max_length=160)
    config = models.JSONField("Tham số cấu hình", default=dict)
    is_current = models.BooleanField("Đang áp dụng", default=True, db_index=True)
    effective_from = models.DateTimeField("Hiệu lực từ", default=timezone.now)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Phiên bản Chính sách CLB"
        verbose_name_plural = "Phiên bản Chính sách CLB"
        ordering = ["policy_key", "-version_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["policy_key", "version_number"],
                name="uniq_policy_key_version",
            ),
        ]

    def __str__(self):
        return f"{self.policy_key} v{self.version_number} ({'Hiện hành' if self.is_current else 'Lịch sử'})"


def serialize_member_contact_for_viewer(viewer, target_user, can_manage_target: bool = False) -> dict:
    """
    Bảo vệ dữ liệu cá nhân (Data Privacy Rule 10):
    Thành viên bình thường hoặc cán bộ xem chéo ban (`can_manage_target=False`) chỉ thấy
    SĐT / Email / Ngày sinh nếu chủ hồ sơ bật cờ cho phép trong `UserProfile`.
    """
    is_self = bool(viewer and getattr(viewer, "pk", None) == target_user.pk)
    profile = getattr(target_user, "profile", None)
    show_email = is_self or can_manage_target or (profile.privacy_show_email if profile else True)
    show_phone = is_self or can_manage_target or (profile.privacy_show_phone if profile else False)
    show_dob = is_self or can_manage_target or (profile.privacy_show_dob if profile else False)
    return {
        "email": target_user.email if show_email else "(Đã ẩn theo quyền riêng tư)",
        "phone": (target_user.phone or "") if show_phone else "(Đã ẩn)",
        "date_of_birth": (
            profile.date_of_birth.isoformat()
            if (profile and profile.date_of_birth and show_dob)
            else None
        ),
    }
