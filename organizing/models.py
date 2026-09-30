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


class TaskPriority(models.TextChoices):
    LOW = "LOW", "Thấp"
    NORMAL = "NORMAL", "Bình thường"
    HIGH = "HIGH", "Cao"
    URGENT = "URGENT", "Gấp"


class Task(models.Model):
    """
    Một công việc giao cho 1 thành viên BTC.

    Gắn với một sự kiện (chuẩn bị sự kiện), hoặc để trống sự kiện = VIỆC CHUNG
    của CLB do Ban chủ nhiệm giao (họp định kỳ, tuyển thành viên, quyết toán...).
    """

    event = models.ForeignKey(Event, on_delete=models.CASCADE, null=True, blank=True,
                              related_name="tasks", verbose_name="Sự kiện",
                              help_text="Để trống nếu là việc chung của CLB.")
    title = models.CharField("Tên công việc", max_length=200)
    description = models.TextField("Mô tả", blank=True)
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL,
                                 on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="tasks_assigned",
                                 verbose_name="Người phụ trách")
    deadline = models.DateTimeField("Deadline", null=True, blank=True)
    status = models.CharField("Trạng thái", max_length=6,
                              choices=TaskStatus.choices, default=TaskStatus.TODO)
    priority = models.CharField("Mức ưu tiên", max_length=6,
                                choices=TaskPriority.choices,
                                default=TaskPriority.NORMAL)
    note = models.CharField("Ghi chú tiến độ", max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL,
                                   on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="tasks_created",
                                   verbose_name="Người giao")
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
    def scope_label(self):
        """Tên sự kiện, hoặc 'Việc chung CLB' khi không gắn sự kiện."""
        return self.event.name if self.event_id else "Việc chung CLB"

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


class ExpenseCategory(models.TextChoices):
    VENUE = "VENUE", "Địa điểm"
    EQUIPMENT = "EQUIP", "Âm thanh - thiết bị"
    PRINTING = "PRINT", "In ấn - truyền thông"
    FOOD = "FOOD", "Ăn uống"
    GIFT = "GIFT", "Quà tặng"
    TRANSPORT = "TRANS", "Di chuyển"
    OTHER = "OTHER", "Khác"


class Expense(models.Model):
    """
    Ngân sách sự kiện - một khoản chi.

    Thu tính tự động từ vé đã xác nhận/đã check-in, nên chỉ cần ghi khoản
    chi. Chỉ Trưởng BTC trở lên được xem vì đây là dữ liệu tài chính.
    """

    event = models.ForeignKey(Event, on_delete=models.CASCADE,
                              related_name="expenses", verbose_name="Sự kiện")
    title = models.CharField("Khoản chi", max_length=200)
    category = models.CharField("Hạng mục", max_length=6,
                                choices=ExpenseCategory.choices,
                                default=ExpenseCategory.OTHER)
    amount = models.PositiveIntegerField("Số tiền (VNĐ)")
    paid_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                null=True, blank=True, related_name="expenses_paid",
                                verbose_name="Người chi")
    spent_on = models.DateField("Ngày chi", default=timezone.localdate)
    note = models.CharField("Ghi chú", max_length=255, blank=True)
    receipt = models.ImageField("Ảnh hoá đơn", upload_to="receipts/",
                                null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, related_name="+", verbose_name="Người ghi")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Khoản chi"
        verbose_name_plural = "Khoản chi"
        ordering = ["-spent_on", "-id"]

    def __str__(self):
        return f"{self.title} - {self.amount}đ"
