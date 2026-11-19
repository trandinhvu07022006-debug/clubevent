"""
Mô hình dữ liệu Vận hành Cốt lõi CLB KMG (Phase 2 — Core Management).

Thiết kế chuẩn MySQL 8.4 (`InnoDB`, `utf8mb4_0900_ai_ci`) & nguyên vẹn 100% module legacy:
1. Công việc Đa chiều 10 bước (`ClubTask`, `ClubTaskAssignee`, `TaskSubmission` lưu tại `PrivateVaultStorage` `SEC-01`,
   `TaskExtensionRequest`, và Sổ cái nghiệm thu bất biến `TaskReview` `PA-04` / `CM-01` / `CM-02` / `BE-02`).
2. Sự kiện Kép & Phối hợp Liên Ban (`ClubEventProfile` mở rộng `events.Event`, `EventDepartmentRole` `CF-05`,
   và Điểm danh RSVP cấp CLB `EventAttendance` + `EventAttendanceHistory` tách rời quota vé thương mại `CM-04` / `CF-02`).
3. Động cơ Cảnh báo Kỷ luật Minh bạch (`DisciplineCase` — vượt ngưỡng `> 3` chỉ gắn cờ `FLAGGED`, cấm tự khóa `R04`)
   và Hệ thống Khiếu nại Độc lập (`Appeal` — mở cho cả thành viên đang `SUSPENDED`, phân tách người xử lý `WF24`).
4. Bản tin Thông báo Chính thức cấp CLB / cấp Ban (`ClubAnnouncement`).
"""
from __future__ import annotations

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from core.storage import private_vault_storage


# ---------------------------------------------------------------------------
# 1. QUẢN LÝ CÔNG VIỆC ĐA CHIỀU (`WF13–WF15`, `CM-01`, `CM-02`, `BE-02`, `PA-04`)
# ---------------------------------------------------------------------------
class TaskPriority(models.TextChoices):
    LOW = "LOW", "Thấp"
    MEDIUM = "MEDIUM", "Trung bình"
    HIGH = "HIGH", "Cao"
    URGENT = "URGENT", "Khẩn cấp"


class TaskWorkflowStatus(models.TextChoices):
    """
    9+1 trạng thái tiến trình công việc chuẩn `CM-01`.
    Lưu ý `CM-01`: `OVERDUE` KHÔNG phải là một giá trị cứng làm kẹt luồng nộp bài,
    mà là thuộc tính suy diễn `ClubTask.is_overdue` theo thời gian thực.
    """

    DRAFT = "DRAFT", "Bản nháp"
    ASSIGNED = "ASSIGNED", "Đã giao việc"
    ACCEPTED = "ACCEPTED", "Đã tiếp nhận"
    IN_PROGRESS = "IN_PROGRESS", "Đang thực hiện"
    SUBMITTED = "SUBMITTED", "Đã nộp kết quả"
    UNDER_REVIEW = "UNDER_REVIEW", "Đang nghiệm thu"
    REVISION_REQUESTED = "REVISION_REQUESTED", "Yêu cầu chỉnh sửa"
    APPROVED = "APPROVED", "Đã duyệt hoàn thành"
    REJECTED = "REJECTED", "Không đạt"
    CANCELLED = "CANCELLED", "Đã huỷ"


class TaskSubmissionMode(models.TextChoices):
    ANY_ONE = "ANY_ONE", "Một đại diện nộp là hoàn tất nhóm"
    ALL_ASSIGNEES = "ALL_ASSIGNEES", "Mọi thành viên được giao đều phải nộp"


class AssigneeRole(models.TextChoices):
    LEAD = "LEAD", "Chủ trì"
    COLLABORATOR = "COLLABORATOR", "Phối hợp"


class ClubTask(models.Model):
    """Nhiệm vụ nội bộ cấp Ban hoặc gắn với Sự kiện CLB (tách rời `organizing.Task` legacy)."""

    title = models.CharField("Tên nhiệm vụ", max_length=200)
    description = models.TextField("Mô tả & yêu cầu đầu ra", blank=True)
    department = models.ForeignKey(
        "organization.Department",
        on_delete=models.CASCADE,
        related_name="club_tasks",
        verbose_name="Ban chủ quản",
    )
    event = models.ForeignKey(
        "events.Event",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="club_tasks",
        verbose_name="Sự kiện liên quan",
    )
    recommended_skill = models.ForeignKey(
        "organization.Skill",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recommended_tasks",
        verbose_name="Kỹ năng gợi ý nhân sự (INV-01)",
    )
    category_tag = models.CharField("Nhãn phân loại Ban", max_length=60, blank=True)
    priority = models.CharField(
        "Độ ưu tiên",
        max_length=12,
        choices=TaskPriority.choices,
        default=TaskPriority.MEDIUM,
    )
    workflow_status = models.CharField(
        "Trạng thái quy trình",
        max_length=24,
        choices=TaskWorkflowStatus.choices,
        default=TaskWorkflowStatus.ASSIGNED,
        db_index=True,
    )
    submission_mode = models.CharField(
        "Chế độ nộp nhóm",
        max_length=16,
        choices=TaskSubmissionMode.choices,
        default=TaskSubmissionMode.ANY_ONE,
    )
    progress_percent = models.PositiveSmallIntegerField(
        "Tiến độ (%)",
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    deadline = models.DateTimeField("Hạn hoàn thành", db_index=True)
    reassignment_needed = models.BooleanField(
        "Cần phân công lại (BE-02)",
        default=False,
        db_index=True,
        help_text="Tự động bật khi người nhận việc chuyển Ban, bị tạm khoá hoặc rời CLB.",
    )
    reassignment_reason = models.CharField("Lý do cần giao lại", max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="club_tasks_created",
        verbose_name="Người giao việc",
    )
    completed_at = models.DateTimeField("Hoàn tất lúc", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Nhiệm vụ CLB"
        verbose_name_plural = "Nhiệm vụ CLB"
        ordering = ["deadline", "-created_at"]
        indexes = [
            models.Index(fields=["department", "workflow_status", "deadline"]),
            models.Index(fields=["reassignment_needed", "department"]),
        ]

    @property
    def is_finalized(self) -> bool:
        return self.workflow_status in {
            TaskWorkflowStatus.APPROVED,
            TaskWorkflowStatus.REJECTED,
            TaskWorkflowStatus.CANCELLED,
        }

    @property
    def is_overdue(self) -> bool:
        return not self.is_finalized and self.deadline < timezone.now()

    @property
    def assignee_user_ids(self) -> set[int]:
        return set(
            self.assignees.filter(is_active=True).values_list("user_id", flat=True)
        )

    def __str__(self) -> str:
        return f"[{self.department.code}] {self.title} ({self.get_workflow_status_display()})"


class ClubTaskAssignee(models.Model):
    """Bảng phân công cá nhân / nhóm cho một `ClubTask` (`CM-02`)."""

    task = models.ForeignKey(
        ClubTask,
        on_delete=models.CASCADE,
        related_name="assignees",
        verbose_name="Nhiệm vụ",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="club_task_assignments",
        verbose_name="Người nhận việc",
    )
    role = models.CharField(
        "Vai trò thực hiện",
        max_length=16,
        choices=AssigneeRole.choices,
        default=AssigneeRole.COLLABORATOR,
    )
    personal_status = models.CharField(
        "Trạng thái cá nhân",
        max_length=24,
        choices=TaskWorkflowStatus.choices,
        default=TaskWorkflowStatus.ASSIGNED,
    )
    progress_percent = models.PositiveSmallIntegerField(
        "Tiến độ cá nhân (%)",
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    is_active = models.BooleanField("Đang phụ trách", default=True)
    accepted_at = models.DateTimeField("Tiếp nhận lúc", null=True, blank=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Người phân công",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Phân công Nhiệm vụ CLB"
        verbose_name_plural = "Phân công Nhiệm vụ CLB"
        ordering = ["role", "assigned_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["task", "user"],
                name="uniq_club_task_assignee",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user.public_name} -> {self.task.title}"


class TaskSubmission(models.Model):
    """
    Bài nộp / minh chứng kết quả thực hiện nhiệm vụ (`WF14`).
    Tệp đính kèm bắt buộc lưu tại `private_vault_storage` ngoài `/media/` (`SEC-01`).
    """

    task = models.ForeignKey(
        ClubTask,
        on_delete=models.CASCADE,
        related_name="submissions",
        verbose_name="Nhiệm vụ",
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="club_task_submissions",
        verbose_name="Người nộp",
    )
    submission_note = models.TextField("Báo cáo kết quả thực hiện")
    evidence_url = models.URLField("Liên kết sản phẩm / Demo / Drive", blank=True)
    attachment = models.FileField(
        "Tệp đính kèm bảo mật (Private Vault)",
        upload_to="task_submissions/%Y/%m/",
        storage=private_vault_storage,
        null=True,
        blank=True,
    )
    is_late = models.BooleanField("Nộp trễ sau hạn", default=False)
    submitted_at = models.DateTimeField("Thời điểm nộp", auto_now_add=True)

    class Meta:
        verbose_name = "Bài nộp Nhiệm vụ"
        verbose_name_plural = "Bài nộp Nhiệm vụ"
        ordering = ["-submitted_at", "-id"]

    def __str__(self) -> str:
        return f"Bài nộp #{self.pk} ({self.submitted_by.public_name}) — {self.task.title}"


class ExtensionStatus(models.TextChoices):
    PENDING = "PENDING", "Chờ duyệt gia hạn"
    APPROVED = "APPROVED", "Đã đồng ý gia hạn"
    REJECTED = "REJECTED", "Từ chối gia hạn"


class TaskExtensionRequest(models.Model):
    """Yêu cầu xin gia hạn deadline nhiệm vụ minh bạch trước khi chốt đánh giá."""

    task = models.ForeignKey(
        ClubTask,
        on_delete=models.CASCADE,
        related_name="extension_requests",
        verbose_name="Nhiệm vụ",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="task_extension_requests",
        verbose_name="Người xin gia hạn",
    )
    requested_deadline = models.DateTimeField("Hạn mới đề xuất")
    reason = models.CharField("Lý do xin gia hạn", max_length=255)
    status = models.CharField(
        "Trạng thái",
        max_length=16,
        choices=ExtensionStatus.choices,
        default=ExtensionStatus.PENDING,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Người xét duyệt",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField("Phản hồi của cán bộ", max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Yêu cầu Gia hạn Nhiệm vụ"
        verbose_name_plural = "Yêu cầu Gia hạn Nhiệm vụ"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Gia hạn {self.task.title} ({self.get_status_display()})"


class TaskReviewDecision(models.TextChoices):
    APPROVED = "APPROVED", "Đạt — Duyệt hoàn thành"
    REVISION_REQUESTED = "REVISION_REQUESTED", "Yêu cầu bổ sung / chỉnh sửa"
    REJECTED = "REJECTED", "Không đạt"


class TaskReview(models.Model):
    """
    Sổ cái nghiệm thu nhiệm vụ BẤT BIẾN (Append-only Immutable Ledger — `WF15`, `PA-04`).

    - Một khi đã ghi quyết định nghiệm thu, không ai được sửa hoặc xoá bản ghi này.
    - Tầng Service chặn cứng người được giao việc tự duyệt nhiệm vụ của chính mình (`PA-04`).
    """

    task = models.ForeignKey(
        ClubTask,
        on_delete=models.CASCADE,
        related_name="reviews",
        verbose_name="Nhiệm vụ",
    )
    submission = models.ForeignKey(
        TaskSubmission,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviews",
        verbose_name="Bài nộp được chấm",
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="club_task_reviews_given",
        verbose_name="Cán bộ nghiệm thu",
    )
    decision = models.CharField(
        "Quyết định nghiệm thu",
        max_length=24,
        choices=TaskReviewDecision.choices,
    )
    quality_score = models.PositiveSmallIntegerField(
        "Điểm chất lượng (1–5)",
        default=5,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    feedback = models.TextField("Nhận xét nghiệm thu")
    created_at = models.DateTimeField("Thời điểm nghiệm thu", auto_now_add=True)

    class Meta:
        verbose_name = "Biên bản Nghiệm thu Nhiệm vụ"
        verbose_name_plural = "Biên bản Nghiệm thu Nhiệm vụ"
        ordering = ["-created_at", "-id"]

    def save(self, *args, **kwargs):
        if not self._state.adding and self.pk is not None:
            raise ValueError(
                "Biên bản nghiệm thu công việc (TaskReview) là dữ liệu bất biến, không được phép chỉnh sửa."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError(
            "Biên bản nghiệm thu công việc (TaskReview) là dữ liệu bất biến, không được phép xoá."
        )

    def __str__(self) -> str:
        return f"Review {self.task.title}: {self.get_decision_display()} ({self.quality_score}/5)"


# ---------------------------------------------------------------------------
# 2. QUẢN LÝ SỰ KIỆN KÉP, PHỐI HỢP LIÊN BAN & ĐIỂM DANH RSVP (`WF09–WF12`)
# ---------------------------------------------------------------------------
class ClubEventScope(models.TextChoices):
    DEPT_INTERNAL = "DEPT_INTERNAL", "Sự kiện sinh hoạt nội bộ Ban"
    CLUB_WIDE = "CLUB_WIDE", "Sự kiện nội bộ toàn CLB (Có RSVP)"
    PUBLIC_SHOW = "PUBLIC_SHOW", "Show diễn / Sự kiện công khai bán vé"


class ClubEventApprovalStatus(models.TextChoices):
    DRAFT = "DRAFT", "Bản nháp"
    SUBMITTED = "SUBMITTED", "Đã trình phê duyệt"
    UNDER_REVIEW = "UNDER_REVIEW", "Đang thẩm định"
    APPROVED = "APPROVED", "Đã phê duyệt"
    REJECTED = "REJECTED", "Từ chối đề xuất"
    PUBLISHED = "PUBLISHED", "Đã ban hành / Mở tham gia"
    ONGOING = "ONGOING", "Đang diễn ra"
    COMPLETED = "COMPLETED", "Đã hoàn thành"
    CANCELLED = "CANCELLED", "Đã huỷ"
    ARCHIVED = "ARCHIVED", "Lưu trữ"


class ClubEventProfile(models.Model):
    """
    Hồ sơ quản trị sự kiện nội bộ & công khai mở rộng `events.Event` (`OneToOne`),
    bảo toàn 100% luồng bán vé/QR check-in cũ (`INT-01`, `CM-04`, `BE-08`).
    """

    event = models.OneToOneField(
        "events.Event",
        on_delete=models.CASCADE,
        related_name="club_profile",
        verbose_name="Sự kiện gốc",
    )
    event_scope = models.CharField(
        "Cấp sự kiện",
        max_length=20,
        choices=ClubEventScope.choices,
        default=ClubEventScope.DEPT_INTERNAL,
        db_index=True,
    )
    approval_status = models.CharField(
        "Trạng thái phê duyệt",
        max_length=20,
        choices=ClubEventApprovalStatus.choices,
        default=ClubEventApprovalStatus.DRAFT,
        db_index=True,
    )
    lead_department = models.ForeignKey(
        "organization.Department",
        on_delete=models.PROTECT,
        related_name="led_club_events",
        verbose_name="Ban chủ trì",
    )
    require_club_rsvp = models.BooleanField(
        "Yêu cầu thành viên CLB phản hồi RSVP",
        default=False,
    )
    default_opt_out_rsvp = models.BooleanField(
        "Sau hạn chốt mặc định tính tham gia (Quyết định A3)",
        default=True,
    )
    rsvp_freeze_at = models.DateTimeField(
        "Thời hạn chốt danh sách RSVP",
        null=True,
        blank=True,
    )
    rsvp_frozen_at = models.DateTimeField(
        "Đã khoá sổ RSVP lúc",
        null=True,
        blank=True,
    )
    policy_version = models.ForeignKey(
        "organization.PolicyVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Phiên bản chính sách áp dụng (BE-08)",
    )
    proposal_note = models.TextField(" Tờ trình kế hoạch / Mục tiêu", blank=True)
    review_note = models.CharField("Ý kiến phê duyệt BCN / Trưởng ban", max_length=255, blank=True)
    proposed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Người đề xuất",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Người phê duyệt",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Hồ sơ Quản trị Sự kiện CLB"
        verbose_name_plural = "Hồ sơ Quản trị Sự kiện CLB"
        ordering = ["-event__starts_at"]

    @property
    def is_rsvp_frozen(self) -> bool:
        if self.rsvp_frozen_at is not None:
            return True
        if self.rsvp_freeze_at is not None and timezone.now() >= self.rsvp_freeze_at:
            return True
        return False

    def __str__(self) -> str:
        return f"{self.event.name} [{self.get_event_scope_display()} · {self.get_approval_status_display()}]"


class EventDeptRoleType(models.TextChoices):
    LEAD = "LEAD", "Ban Chủ trì"
    CO_ORGANIZER = "CO_ORGANIZER", "Ban Đồng tổ chức"
    SUPPORT = "SUPPORT", "Ban Phối hợp hỗ trợ"


class EventDepartmentRole(models.Model):
    """Phân công trách nhiệm phối hợp đa Ban cho một sự kiện (`CF-05`)."""

    club_event = models.ForeignKey(
        ClubEventProfile,
        on_delete=models.CASCADE,
        related_name="department_roles",
        verbose_name="Sự kiện CLB",
    )
    department = models.ForeignKey(
        "organization.Department",
        on_delete=models.CASCADE,
        related_name="event_participations",
        verbose_name="Ban tham gia",
    )
    role_type = models.CharField(
        "Vai trò của Ban",
        max_length=16,
        choices=EventDeptRoleType.choices,
        default=EventDeptRoleType.SUPPORT,
    )
    responsibility_note = models.CharField("Đầu việc phụ trách", max_length=255, blank=True)

    class Meta:
        verbose_name = "Vai trò Ban trong Sự kiện"
        verbose_name_plural = "Vai trò Ban trong Sự kiện"
        constraints = [
            models.UniqueConstraint(
                fields=["club_event", "department"],
                name="uniq_club_event_dept_role",
            )
        ]

    def __str__(self) -> str:
        return f"{self.department.name} ({self.get_role_type_display()}) @ {self.club_event.event.name}"


class RsvpStatus(models.TextChoices):
    PENDING_RESPONSE = "PENDING_RESPONSE", "Chờ phản hồi"
    CONFIRMED_ATTENDING = "CONFIRMED_ATTENDING", "Xác nhận tham gia"
    AUTO_COMMITTED = "AUTO_COMMITTED", "Mặc định tham gia (sau hạn chốt)"
    DECLINED_PENDING = "DECLINED_PENDING", "Xin vắng — Chờ duyệt lý do"
    DECLINED_EXEMPTED = "DECLINED_EXEMPTED", "Xin vắng có phép (Miễn trừ)"
    DECLINED_UNEXCUSED = "DECLINED_UNEXCUSED", "Vắng không lý do hợp lệ"
    EXEMPT_SUSPENDED = "EXEMPT_SUSPENDED", "Miễn trừ do đang tạm khoá CLB"


class CheckinStatus(models.TextChoices):
    NOT_YET = "NOT_YET", "Chưa điểm danh"
    PRESENT = "PRESENT", "Có mặt"
    LATE = "LATE", "Đến trễ"
    NO_SHOW = "NO_SHOW", "Vắng mặt (No-show)"


class EventAttendance(models.Model):
    """
    Sổ theo dõi RSVP & Điểm danh thành viên nội bộ CLB (`CM-04`, `BE-03`, `CF-02`).
    Tách biệt hoàn toàn với `registrations.Ticket` để không bao giờ ăn vào quota vé khán giả.
    """

    club_event = models.ForeignKey(
        ClubEventProfile,
        on_delete=models.CASCADE,
        related_name="attendances",
        verbose_name="Sự kiện CLB",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="club_event_attendances",
        verbose_name="Thành viên",
    )
    rsvp_status = models.CharField(
        "Trạng thái RSVP",
        max_length=24,
        choices=RsvpStatus.choices,
        default=RsvpStatus.PENDING_RESPONSE,
        db_index=True,
    )
    decline_reason = models.CharField("Lý do xin vắng", max_length=255, blank=True)
    exemption_reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Người duyệt đơn xin vắng",
    )
    exemption_reviewed_at = models.DateTimeField(null=True, blank=True)
    exemption_note = models.CharField("Phản hồi duyệt lý do vắng", max_length=255, blank=True)
    checkin_status = models.CharField(
        "Điểm danh thực tế",
        max_length=16,
        choices=CheckinStatus.choices,
        default=CheckinStatus.NOT_YET,
        db_index=True,
    )
    checked_in_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Người điểm danh",
    )
    checked_in_at = models.DateTimeField(null=True, blank=True)
    responded_at = models.DateTimeField("Phản hồi lúc", null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Điểm danh & RSVP Thành viên"
        verbose_name_plural = "Điểm danh & RSVP Thành viên"
        ordering = ["user__full_name", "user__username"]
        indexes = [
            models.Index(fields=["user", "checkin_status"], name="att_user_checkin_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["club_event", "user"],
                name="uniq_club_event_attendance_user",
            )
        ]

    @property
    def counts_as_unexcused_violation(self) -> bool:
        """
        Chỉ tính là 01 lần vi phạm chuyên cần sự kiện cấp CLB khi:
        - Xin vắng nhưng bị bác lý do (`DECLINED_UNEXCUSED`), HOẶC
        - Đã cam kết tham gia (`CONFIRMED_ATTENDING` / `AUTO_COMMITTED` / `PENDING_RESPONSE`) nhưng điểm danh `NO_SHOW`.
        Thành viên được miễn trừ (`DECLINED_EXEMPTED`) hoặc đang bị tạm khoá (`EXEMPT_SUSPENDED` — `CF-02`) KHÔNG BAO GIỜ bị tính vi phạm!
        """
        if self.rsvp_status in (
            RsvpStatus.DECLINED_EXEMPTED,
            RsvpStatus.EXEMPT_SUSPENDED,
        ):
            return False
        if self.rsvp_status == RsvpStatus.DECLINED_UNEXCUSED:
            return True
        if self.checkin_status == CheckinStatus.NO_SHOW and self.rsvp_status in (
            RsvpStatus.CONFIRMED_ATTENDING,
            RsvpStatus.AUTO_COMMITTED,
            RsvpStatus.PENDING_RESPONSE,
        ):
            return True
        return False

    def __str__(self) -> str:
        return f"{self.user.public_name} @ {self.club_event.event.name}: {self.get_rsvp_status_display()}"


class EventAttendanceHistory(models.Model):
    """Nhật ký thay đổi phản hồi RSVP & chốt danh sách tự động (`WF12`)."""

    attendance = models.ForeignKey(
        EventAttendance,
        on_delete=models.CASCADE,
        related_name="history",
    )
    previous_rsvp_status = models.CharField(max_length=24, blank=True)
    new_rsvp_status = models.CharField(max_length=24)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Lịch sử Thay đổi RSVP"
        verbose_name_plural = "Lịch sử Thay đổi RSVP"
        ordering = ["-created_at", "-id"]


# ---------------------------------------------------------------------------
# 3. ĐỘNG CƠ CẢNH BÁO KỶ LUẬT MINH BẠCH & HỆ THỐNG KHIẾU NẠI ĐỘC LẬP (`WF23`, `WF24`)
# ---------------------------------------------------------------------------
class DisciplineTriggerType(models.TextChoices):
    EVENT_ATTENDANCE_THRESHOLD = (
        "EVENT_ATTENDANCE_THRESHOLD",
        "Vượt ngưỡng > 3 lần vắng sự kiện cấp CLB không phép",
    )
    EVENT_TASK_THRESHOLD = (
        "EVENT_TASK_THRESHOLD",
        "Vượt ngưỡng > 3 nhiệm vụ sự kiện không đạt / quá hạn",
    )
    MANUAL_PROPOSAL = (
        "MANUAL_PROPOSAL",
        "Hồ sơ đề xuất xem xét từ Ban chuyên môn",
    )


class DisciplineStatus(models.TextChoices):
    FLAGGED = "FLAGGED", "Hệ thống gắn cờ cảnh báo — Chờ BCN xem xét"
    UNDER_REVIEW = "UNDER_REVIEW", "Đang xác minh & lắng nghe giải trình"
    EXEMPTED_DISMISSED = "EXEMPTED_DISMISSED", "Miễn trừ / Đóng hồ sơ không kỷ luật"
    WARNING_ISSUED = "WARNING_ISSUED", "Nhắc nhở / Cảnh cáo chính thức"
    SUSPENSION_APPLIED = "SUSPENSION_APPLIED", "Đã ra quyết định tạm khoá tư cách thành viên"


class DisciplineCase(models.Model):
    """
    Hồ sơ cảnh báo chuyên cần / kỷ luật minh bạch (`R04`, `CF-03`, `BE-08`).

    QUY TẮC CỐT LÕI `R04`: Vượt ngưỡng `> 3` lần vi phạm chỉ tạo/cập nhật hồ sơ ở trạng thái
    `FLAGGED` để báo cáo Ban Chủ nhiệm xem xét, TUYỆT ĐỐI KHÔNG tự động khoá tài khoản hay tạm khoá thành viên!
    """

    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="discipline_cases",
        verbose_name="Thành viên liên quan",
    )
    department = models.ForeignKey(
        "organization.Department",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="discipline_cases",
        verbose_name="Ban liên quan",
    )
    trigger_type = models.CharField(
        "Nguồn phát sinh",
        max_length=32,
        choices=DisciplineTriggerType.choices,
        db_index=True,
    )
    term_label = models.CharField("Học kỳ / Nhiệm kỳ xét", max_length=40, default="2026-2027")
    violation_count = models.PositiveSmallIntegerField("Số lần vi phạm ghi nhận", default=0)
    threshold_applied = models.PositiveSmallIntegerField("Ngưỡng chính sách (> N)", default=3)
    policy_version = models.ForeignKey(
        "organization.PolicyVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Phiên bản chính sách (BE-08)",
    )
    summary = models.CharField("Tóm tắt cảnh báo", max_length=255)
    evidence_snapshot = models.JSONField(
        "Bằng chứng đối chiếu minh bạch",
        default=dict,
        blank=True,
    )
    status = models.CharField(
        "Trạng thái xử lý",
        max_length=24,
        choices=DisciplineStatus.choices,
        default=DisciplineStatus.FLAGGED,
        db_index=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Người lập hồ sơ (Trống nếu hệ thống tự gắn cờ)",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Lãnh đạo BCN xử lý",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField("Kết luận xem xét của Ban Chủ nhiệm", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Hồ sơ Cảnh báo & Kỷ luật"
        verbose_name_plural = "Hồ sơ Cảnh báo & Kỷ luật"
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"Hồ sơ #{self.pk} — {self.target_user.public_name} ({self.get_status_display()})"


class AppealTargetType(models.TextChoices):
    MEMBERSHIP_SUSPENSION = (
        "MEMBERSHIP_SUSPENSION",
        "Khiếu nại quyết định tạm khoá tư cách thành viên",
    )
    DISCIPLINE_CASE = (
        "DISCIPLINE_CASE",
        "Giải trình / Khiếu nại hồ sơ cảnh báo chuyên cần",
    )
    TASK_REVIEW = (
        "TASK_REVIEW",
        "Phản hồi kết quả nghiệm thu công việc",
    )


class AppealStatus(models.TextChoices):
    SUBMITTED = "SUBMITTED", "Mới gửi khiếu nại"
    UNDER_REVIEW = "UNDER_REVIEW", "Đang thụ lý độc lập"
    UPHELD = "UPHELD", "Giữ nguyên quyết định ban đầu"
    OVERTURNED = "OVERTURNED", "Chấp nhận khiếu nại — Khôi phục / Huỷ quyết định cũ"


class Appeal(models.Model):
    """
    Hệ thống Khiếu nại & Giải trình Độc lập (`WF24`, `CF-04`, Chỉ thị 3.3).

    - Thành viên đang bị `SUSPENDED` VẪN có toàn quyền gửi và theo dõi `Appeal` của chính mình!
    - Người ra quyết định giải quyết khiếu nại (`decided_by`) bắt buộc KHÁC người ra quyết định bị khiếu nại
      (`original_actor`) để bảo đảm tính khách quan độc lập.
    """

    appellant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="appeals",
        verbose_name="Người gửi khiếu nại",
    )
    target_type = models.CharField(
        "Loại khiếu nại",
        max_length=28,
        choices=AppealTargetType.choices,
        default=AppealTargetType.MEMBERSHIP_SUSPENSION,
    )
    discipline_case = models.ForeignKey(
        DisciplineCase,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appeals",
        verbose_name="Hồ sơ kỷ luật liên quan",
    )
    task_review = models.ForeignKey(
        TaskReview,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appeals",
        verbose_name="Biên bản nghiệm thu bị khiếu nại",
    )
    original_actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Người ra quyết định ban đầu",
    )
    reason = models.TextField("Nội dung giải trình & khiếu nại")
    evidence_url = models.URLField("Liên kết minh chứng đính kèm", blank=True)
    status = models.CharField(
        "Trạng thái giải quyết",
        max_length=20,
        choices=AppealStatus.choices,
        default=AppealStatus.SUBMITTED,
        db_index=True,
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Người thụ lý & phán quyết độc lập",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField("Kết luận giải quyết khiếu nại", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Đơn Khiếu nại & Giải trình"
        verbose_name_plural = "Đơn Khiếu nại & Giải trình"
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"Khiếu nại #{self.pk} của {self.appellant.public_name} ({self.get_status_display()})"


# ---------------------------------------------------------------------------
# 4. BẢN TIN THÔNG BÁO CHÍNH THỨC CẤP CLB / CẤP BAN (`ClubAnnouncement`)
# ---------------------------------------------------------------------------
class ClubAnnouncement(models.Model):
    """Thông báo điều hành chính thức phát tới Toàn CLB hoặc một Ban cụ thể."""

    title = models.CharField("Tiêu đề thông báo", max_length=160)
    content = models.TextField("Nội dung thông báo")
    department = models.ForeignKey(
        "organization.Department",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="announcements",
        verbose_name="Phạm vi Ban (Để trống = Toàn CLB)",
    )
    is_pinned = models.BooleanField("Ghim nổi bật", default=False)
    send_email = models.BooleanField("Gửi kèm Email quan trọng", default=False)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="published_announcements",
        verbose_name="Người phát thông báo",
    )
    recipient_count = models.PositiveIntegerField("Số thành viên nhận", default=0)
    created_at = models.DateTimeField("Phát lúc", auto_now_add=True)

    class Meta:
        verbose_name = "Thông báo Chính thức CLB"
        verbose_name_plural = "Thông báo Chính thức CLB"
        ordering = ["-is_pinned", "-created_at"]

    def __str__(self) -> str:
        scope = self.department.name if self.department_id else "Toàn CLB"
        return f"[{scope}] {self.title}"
