"""
M3 - Phân công công việc BTC.

Task có máy trạng thái: Chưa làm -> Đang làm -> Xong (và lùi lại được).
Đây là module làm nên ý nghĩa "hỗ trợ tổ chức" của đề tài.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from events.models import Event


class TaskStatus(models.TextChoices):
    TODO = "TODO", "Chưa làm"
    DOING = "DOING", "Đang làm"
    DONE = "DONE", "Xong"


class Task(models.Model):
    """Một công việc chuẩn bị cho sự kiện, giao cho 1 thành viên BTC."""

    event = models.ForeignKey(Event, on_delete=models.CASCADE,
                              related_name="tasks", verbose_name="Sự kiện")
    title = models.CharField("Tên công việc", max_length=200)
    description = models.TextField("Mô tả", blank=True)
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL,
                                 on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="tasks_assigned",
                                 verbose_name="Người phụ trách")
    deadline = models.DateTimeField("Deadline", null=True, blank=True)
    status = models.CharField("Trạng thái", max_length=6,
                              choices=TaskStatus.choices, default=TaskStatus.TODO)
    note = models.CharField("Ghi chú tiến độ", max_length=255, blank=True)
    created_by_ai = models.BooleanField("Do AI gợi ý", default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    done_at = models.DateTimeField("Hoàn thành lúc", null=True, blank=True)

    class Meta:
        verbose_name = "Công việc"
        verbose_name_plural = "Công việc"
        ordering = ["deadline", "id"]

    def __str__(self):
        return self.title

    @property
    def is_overdue(self):
        """F3.3 - task quá hạn thì tô đỏ trên giao diện."""
        if self.status == TaskStatus.DONE or not self.deadline:
            return False
        return self.deadline < timezone.now()

    @property
    def is_done_on_time(self):
        """Dùng cho thống kê F6.3 - tỉ lệ hoàn thành đúng hạn."""
        if self.status != TaskStatus.DONE or not self.deadline or not self.done_at:
            return None
        return self.done_at <= self.deadline

    def can_be_edited_by(self, user):
        """F3.4 - chỉ người phụ trách hoặc Trưởng BTC được cập nhật tiến độ."""
        return user.is_lead or self.assignee_id == user.id

    def mark(self, new_status):
        """Đổi trạng thái, tự ghi nhận thời điểm hoàn thành."""
        self.status = new_status
        self.done_at = timezone.now() if new_status == TaskStatus.DONE else None
        self.save(update_fields=["status", "done_at"])
