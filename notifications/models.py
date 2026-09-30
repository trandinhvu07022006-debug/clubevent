from django.db import models
from accounts.models import User

class NotificationKind(models.TextChoices):
    TICKET_CONFIRMED = "TICKET_OK", "Vé đã xác nhận"
    TICKET_PENDING   = "TICKET_PEND", "Vé chờ thanh toán"
    TICKET_EXPIRED   = "TICKET_EXP", "Vé hết hạn thanh toán"
    EVENT_CANCELLED  = "EVENT_CXL", "Sự kiện bị huỷ"
    EVENT_REMINDER   = "REMINDER", "Nhắc lịch"
    WAITLIST_PROMOTED= "WAIT_OK", "Có vé từ danh sách chờ"
    TASK_ASSIGNED    = "TASK", "Được giao việc"

class Notification(models.Model):
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    kind       = models.CharField(max_length=12, choices=NotificationKind.choices)
    title      = models.CharField(max_length=120)
    message    = models.CharField(max_length=255)
    url        = models.CharField(max_length=255, blank=True)   # đường dẫn NỘI BỘ, vd "/ve/cua-toi/"
    is_read    = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "is_read", "-created_at"])]
