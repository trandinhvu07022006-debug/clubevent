from django.db import models
from accounts.models import User

class NotificationKind(models.TextChoices):
    TICKET_CONFIRMED = "TICKET_OK", "Vé đã xác nhận"
    TICKET_PENDING   = "TICKET_PEND", "Vé chờ thanh toán"
    TICKET_EXPIRED   = "TICKET_EXP", "Vé hết hạn thanh toán"
    EVENT_CANCELLED  = "EVENT_CXL", "Sự kiện bị huỷ"
    EVENT_REMINDER   = "REMINDER", "Nhắc lịch"
    WAITLIST_PROMOTED= "WAIT_OK", "Có vé từ danh sách chờ"
    WAITLIST_EXPIRED = "WAIT_EXP", "Danh sách chờ kết thúc"
    TASK_ASSIGNED    = "TASK", "Được giao việc"
    TASK_DUE         = "TASK_DUE", "Nhắc hạn công việc"
    APPLICATION      = "APPLY", "Kết quả ứng tuyển"

class Notification(models.Model):
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    kind       = models.CharField(max_length=12, choices=NotificationKind.choices)
    title      = models.CharField(max_length=120)
    message    = models.CharField(max_length=255)
    url        = models.CharField(max_length=255, blank=True)   # đường dẫn NỘI BỘ, vd "/ve/cua-toi/"
    is_read    = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Thông báo"
        verbose_name_plural = "Thông báo"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "is_read", "-created_at"])]

    def __str__(self):
        return f"{self.user} - {self.title}"

    @property
    def icon(self):
        """Icon Bootstrap theo loại thông báo, dùng ở chuông và trang danh sách."""
        return {
            NotificationKind.TICKET_CONFIRMED: "bi-check-circle",
            NotificationKind.TICKET_PENDING: "bi-hourglass-split",
            NotificationKind.TICKET_EXPIRED: "bi-x-circle",
            NotificationKind.EVENT_CANCELLED: "bi-calendar-x",
            NotificationKind.EVENT_REMINDER: "bi-alarm",
            NotificationKind.WAITLIST_PROMOTED: "bi-stars",
            NotificationKind.WAITLIST_EXPIRED: "bi-hourglass-bottom",
            NotificationKind.TASK_ASSIGNED: "bi-list-task",
            NotificationKind.TASK_DUE: "bi-hourglass-split",
            NotificationKind.APPLICATION: "bi-person-plus",
        }.get(self.kind, "bi-bell")
