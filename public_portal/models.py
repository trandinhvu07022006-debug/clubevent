"""Mô hình dữ liệu Liên hệ Công khai từ Public Website KMG."""
from django.db import models


class ContactTopic(models.TextChoices):
    RECRUITMENT = "RECRUITMENT", "Đăng ký thành viên / Casting"
    COLLABORATION = "COLLABORATION", "Hợp tác biểu diễn & Sự kiện"
    SPONSORSHIP = "SPONSORSHIP", "Tài trợ & Đối tác truyền thông"
    GENERAL = "GENERAL", "Câu hỏi chung"


class ContactStatus(models.TextChoices):
    NEW = "NEW", "Mới tiếp nhận"
    IN_PROGRESS = "IN_PROGRESS", "Đang phản hồi"
    RESOLVED = "RESOLVED", "Đã xử lý"


class ContactSubmission(models.Model):
    """Tin nhắn liên hệ từ khách truy cập trang chủ KMG."""

    full_name = models.CharField("Họ tên", max_length=120)
    email = models.EmailField("Email liên hệ")
    phone = models.CharField("Số điện thoại", max_length=20, blank=True)
    topic = models.CharField(
        "Chủ đề",
        max_length=24,
        choices=ContactTopic.choices,
        default=ContactTopic.RECRUITMENT,
    )
    message = models.TextField("Nội dung liên hệ", max_length=2000)
    status = models.CharField(
        "Trạng thái xử lý",
        max_length=16,
        choices=ContactStatus.choices,
        default=ContactStatus.NEW,
        db_index=True,
    )
    ip_hash = models.CharField("Mã băm IP (chống spam)", max_length=64, blank=True)
    created_at = models.DateTimeField("Gửi lúc", auto_now_add=True)

    class Meta:
        verbose_name = "Liên hệ từ Trang chủ"
        verbose_name_plural = "Liên hệ từ Trang chủ"
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"[{self.get_topic_display()}] {self.full_name} ({self.email})"
