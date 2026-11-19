"""
Mô hình dữ liệu Phase 5: Đánh giá Thành viên 7 Tiêu chí & Vinh danh (`evaluations`).

Chỉ thị 3.3 của Nhà tài trợ:
- Đánh giá mang tính PHÁT TRIỂN (developmental), riêng tư; KHÔNG xếp hạng điểm số công khai.
- Thành viên đa Ban nhận đánh giá ĐỘC LẬP theo từng Ban (`UNIQUE(cycle, member, department)`).
- Phản hồi hai chiều nhẹ nhàng (`BE-06` — `EvaluationResponse`), tách biệt hoàn toàn với Kỷ luật/Khiếu nại.
- Vinh danh (`MemberRecognition`) là luồng riêng, công nhận định tính, không dựa trên bảng điểm.
"""
from __future__ import annotations

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from organization.models import Department


class EvaluationCycleStatus(models.TextChoices):
    OPEN = "OPEN", "Đang mở đánh giá"
    CLOSED = "CLOSED", "Đã khoá kỳ"


class EvaluationCycle(models.Model):
    code = models.CharField("Mã kỳ", max_length=32, unique=True)
    name = models.CharField("Tên kỳ đánh giá", max_length=160)
    starts_on = models.DateField("Từ ngày")
    ends_on = models.DateField("Đến ngày")
    response_deadline = models.DateField("Hạn phản hồi của thành viên", null=True, blank=True)
    status = models.CharField(
        "Trạng thái", max_length=10, choices=EvaluationCycleStatus.choices, default=EvaluationCycleStatus.OPEN
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Kỳ đánh giá"
        verbose_name_plural = "Kỳ đánh giá"
        ordering = ["-starts_on", "-id"]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"

    @property
    def is_open(self) -> bool:
        return self.status == EvaluationCycleStatus.OPEN


class EvaluationCriterion(models.TextChoices):
    """7 Tiêu chí đánh giá thành viên chuẩn (Chỉ thị 3.3)."""

    TASK_COMPLETION = "TASK_COMPLETION", "1. Mức độ hoàn thành nhiệm vụ được giao"
    ATTENDANCE = "ATTENDANCE", "2. Chuyên cần & tham gia sự kiện CLB"
    PROFESSIONAL_SKILL = "PROFESSIONAL_SKILL", "3. Năng lực chuyên môn"
    TRAINING_GROWTH = "TRAINING_GROWTH", "4. Tham gia đào tạo, tập luyện & tiến bộ"
    TEAMWORK = "TEAMWORK", "5. Tinh thần phối hợp đội nhóm"
    INITIATIVE = "INITIATIVE", "6. Chủ động, sáng kiến & đóng góp ý tưởng"
    CULTURE = "CULTURE", "7. Ý thức kỷ luật & văn hoá CLB"


class RatingLevel(models.IntegerChoices):
    NEEDS_SUPPORT = 1, "Cần hỗ trợ thêm"
    DEVELOPING = 2, "Đang phát triển"
    MEETS = 3, "Đạt kỳ vọng"
    STRONG = 4, "Vượt kỳ vọng"
    EXEMPLARY = 5, "Tiêu biểu / Truyền cảm hứng"


class OverallRating(models.TextChoices):
    NEEDS_SUPPORT = "NEEDS_SUPPORT", "Cần đồng hành hỗ trợ"
    DEVELOPING = "DEVELOPING", "Đang phát triển tốt"
    MEETS = "MEETS", "Hoàn thành tốt vai trò"
    STRONG = "STRONG", "Đóng góp nổi bật"
    EXEMPLARY = "EXEMPLARY", "Tiêu biểu của Ban"


class EvaluationStatus(models.TextChoices):
    DRAFT = "DRAFT", "Bản nháp (chỉ cán bộ Ban thấy)"
    CONFIRMED = "CONFIRMED", "Đã chốt & gửi thành viên"


class MemberEvaluation(models.Model):
    cycle = models.ForeignKey(EvaluationCycle, on_delete=models.PROTECT, related_name="evaluations")
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="evaluations_received"
    )
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="member_evaluations")
    status = models.CharField(
        "Trạng thái", max_length=12, choices=EvaluationStatus.choices, default=EvaluationStatus.DRAFT
    )
    overall_rating = models.CharField(
        "Nhận định tổng quát", max_length=16, choices=OverallRating.choices, blank=True
    )
    strengths = models.TextField("Điểm mạnh ghi nhận", blank=True)
    growth_areas = models.TextField("Định hướng cải thiện mang tính xây dựng", blank=True)
    development_plan = models.TextField("Kế hoạch phát triển kỳ tới", blank=True)
    telemetry_snapshot = models.JSONField("Số liệu hoạt động tự động (Phase 2/3)", default=dict, blank=True)
    drafted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="evaluations_drafted"
    )
    finalized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="evaluations_finalized",
        null=True,
        blank=True,
    )
    finalized_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Phiếu đánh giá thành viên"
        verbose_name_plural = "Phiếu đánh giá thành viên"
        ordering = ["-cycle__starts_on", "department__display_order", "member__full_name"]
        indexes = [
            models.Index(fields=["cycle", "department", "status"], name="eval_cycle_dept_status_idx"),
            models.Index(fields=["member", "status"], name="eval_member_status_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["cycle", "member", "department"],
                name="uniq_eval_cycle_member_department",
            )
        ]

    def __str__(self) -> str:
        return f"{self.cycle.code} · {self.member} · {self.department.name}"


class EvaluationCriterionScore(models.Model):
    evaluation = models.ForeignKey(MemberEvaluation, on_delete=models.CASCADE, related_name="criterion_scores")
    criterion = models.CharField("Tiêu chí", max_length=24, choices=EvaluationCriterion.choices)
    rating_level = models.PositiveSmallIntegerField(
        "Mức độ (1-5)",
        choices=RatingLevel.choices,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        default=RatingLevel.MEETS,
    )
    auto_evidence = models.CharField("Minh chứng tự động", max_length=255, blank=True)
    comment = models.CharField("Nhận xét", max_length=500, blank=True)

    class Meta:
        verbose_name = "Điểm tiêu chí"
        verbose_name_plural = "Điểm tiêu chí"
        ordering = ["evaluation", "id"]
        constraints = [
            models.UniqueConstraint(fields=["evaluation", "criterion"], name="uniq_eval_criterion")
        ]

    def __str__(self) -> str:
        return f"{self.evaluation_id} · {self.criterion} = {self.rating_level}"


class EvaluationResponse(models.Model):
    """Phản hồi hai chiều về phiếu đánh giá (`BE-06`) — KHÔNG phải đơn khiếu nại."""

    evaluation = models.ForeignKey(MemberEvaluation, on_delete=models.CASCADE, related_name="responses")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    is_member_response = models.BooleanField(default=True)
    message = models.TextField("Nội dung phản hồi")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Phản hồi đánh giá"
        verbose_name_plural = "Phản hồi đánh giá"
        ordering = ["created_at", "id"]


class RecognitionScope(models.TextChoices):
    CLUB = "CLUB", "Toàn CLB"
    DEPARTMENT = "DEPARTMENT", "Cấp Ban"


class RecognitionStatus(models.TextChoices):
    PROPOSED = "PROPOSED", "Đề cử chờ xác nhận"
    VERIFIED = "VERIFIED", "Đã xác nhận vinh danh"
    REJECTED = "REJECTED", "Không xác nhận"


class MemberRecognition(models.Model):
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recognitions_received"
    )
    scope = models.CharField(max_length=12, choices=RecognitionScope.choices, default=RecognitionScope.DEPARTMENT)
    department = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="recognitions"
    )
    cycle = models.ForeignKey(
        EvaluationCycle, on_delete=models.SET_NULL, null=True, blank=True, related_name="recognitions"
    )
    title = models.CharField("Danh hiệu", max_length=160)
    citation = models.TextField("Lời vinh danh")
    status = models.CharField(
        max_length=12, choices=RecognitionStatus.choices, default=RecognitionStatus.PROPOSED
    )
    is_public = models.BooleanField("Hiển thị trên Trang chủ công khai", default=False)
    proposed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="recognitions_proposed"
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recognitions_verified",
        null=True,
        blank=True,
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Vinh danh thành viên"
        verbose_name_plural = "Vinh danh thành viên"
        ordering = ["-verified_at", "-created_at"]

    def __str__(self) -> str:
        return f"{self.title} — {self.recipient}"
