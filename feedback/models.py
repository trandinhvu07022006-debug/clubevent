"""
M6 - Phản hồi sau sự kiện.

Chỉ người ĐÃ CHECK-IN mới được gửi đánh giá, và mỗi người chỉ gửi 1 lần
cho mỗi sự kiện (ràng buộc unique_together ở tầng DB, không chỉ ở tầng code).
"""
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from events.models import Event


class Feedback(models.Model):
    """Một đánh giá của người tham gia."""

    event = models.ForeignKey(Event, on_delete=models.CASCADE,
                              related_name="feedbacks", verbose_name="Sự kiện")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="feedbacks", verbose_name="Người gửi")
    rating = models.PositiveSmallIntegerField(
        "Số sao", validators=[MinValueValidator(1), MaxValueValidator(5)])
    content = models.TextField("Góp ý", blank=True)
    created_at = models.DateTimeField("Ngày gửi", auto_now_add=True)

    class Meta:
        verbose_name = "Phản hồi"
        verbose_name_plural = "Phản hồi"
        ordering = ["-created_at"]
        # Chặn gửi 2 lần ngay ở tầng CSDL
        constraints = [
            models.UniqueConstraint(fields=["event", "user"],
                                    name="unique_feedback_per_user_event")
        ]

    def __str__(self):
        return f"{self.user} - {self.event} - {self.rating} sao"


class FeedbackSummary(models.Model):
    """
    Kết quả AI tóm tắt phản hồi (F6.2 + tích hợp AI).

    Lưu lại vào DB để không phải gọi API mỗi lần mở trang, vừa nhanh vừa
    tiết kiệm quota.
    """

    event = models.OneToOneField(Event, on_delete=models.CASCADE,
                                 related_name="ai_summary", verbose_name="Sự kiện")
    positive = models.TextField("Điểm được khen", blank=True)
    negative = models.TextField("Điểm bị góp ý", blank=True)
    suggestion = models.TextField("Đề xuất cải thiện", blank=True)
    feedback_count = models.PositiveIntegerField("Số phản hồi đã tóm tắt", default=0)
    generated_at = models.DateTimeField("Tạo lúc", auto_now=True)

    class Meta:
        verbose_name = "Tóm tắt phản hồi (AI)"
        verbose_name_plural = "Tóm tắt phản hồi (AI)"

    def __str__(self):
        return f"Tóm tắt AI - {self.event.name}"
